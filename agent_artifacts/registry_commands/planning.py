"""Pure registry workspace planning and quality checks over inert snapshots."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import cast

from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import ArtifactIdentity, ObjectDigest, SourceId
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.protocol.capabilities import Capability
from agent_artifacts.protocol.hashing import sha256_bytes
from agent_artifacts.protocol.json import (
    JsonArray,
    JsonObject,
    canonical_json_bytes,
    parse_json,
)
from agent_artifacts.protocol.native_models import (
    INSTALL_EFFECTS_BY_TYPE,
    PAYLOAD_FORMAT_BY_TYPE,
    ArtifactManifest,
    CanonicalArtifactType,
    CompatibilitySpec,
    InstallMode,
    InstallScope,
    InstallSpec,
    PayloadSpec,
    SourceManifest,
)
from agent_artifacts.protocol.native_schema import (
    artifact_manifest_to_json,
    parse_artifact_manifest,
    parse_provenance,
    parse_source_manifest,
    source_manifest_to_json,
)
from agent_artifacts.protocol.native_tree import (
    SnapshotEntry,
    SnapshotEntryKind,
    SourceSnapshot,
)
from agent_artifacts.protocol.paths import SafeRelativePath, parse_relative_path
from agent_artifacts.protocol.registry_index import (
    build_registry_index,
    index_artifact_from_package,
)
from agent_artifacts.protocol.registry_models import (
    LockedArtifact,
    RegistryLock,
    RegistryManifest,
    ReviewRecord,
)
from agent_artifacts.protocol.registry_schema import (
    parse_registry_entry,
    parse_registry_index,
    parse_registry_lock,
    parse_registry_manifest,
    registry_index_to_json,
    registry_lock_to_json,
    registry_manifest_to_json,
)
from agent_artifacts.protocol.registry_tree import (
    registry_inputs_digest,
    resolve_locked_references,
)
from agent_artifacts.protocol.semver import SemVer, VersionBounds
from agent_artifacts.registry_maintenance.model import (
    NativeAcquirer,
    NativeReferenceAcquisition,
    NativeReferenceDisposition,
)
from agent_artifacts.registry_maintenance.planning import (
    registry_native_content,
    resolve_native_acquisition,
)
from agent_artifacts.registry_maintenance.vendoring import (
    VENDOR_IMPORTER_ID,
    VendorOptions,
    VendorOrigin,
    assess_vendored_package,
    project_vendored_package,
    read_vendor_record,
)
from agent_artifacts.security.application import verify_security_index
from agent_artifacts.security.attestation_schema import parse_security_index
from agent_artifacts.security.model import InstallationRisk
from agent_artifacts.sources.model import source_snapshot_digest
from agent_artifacts.sources.subtree import TakenSubtree, take_subtree

from .model import (
    ArtifactScaffoldOptions,
    RegistryInitOptions,
    RegistryOperation,
    RegistryQualityCheck,
    RegistryQualityReport,
    RegistryWorkspaceChange,
    RegistryWorkspacePlan,
    VendoredArtifactCheck,
    VendoredArtifactPlan,
    WorkspaceChangeKind,
    registry_workspace_review_digest,
)
from .templates import REGISTRY_CI_WORKFLOW, REPORTING_TEMPLATES

REGISTRY_COMMAND_INVALID = DiagnosticCode("registry-command-invalid")
REGISTRY_AUDIT_WARNING = DiagnosticCode("registry-audit-warning")


def _error(message: str) -> Err:
    return Err((Diagnostic(REGISTRY_COMMAND_INVALID, Severity.ERROR, message),))


def _diagnostic(message: str, *, warning: bool = False) -> Diagnostic:
    return Diagnostic(
        REGISTRY_AUDIT_WARNING if warning else REGISTRY_COMMAND_INVALID,
        Severity.WARNING if warning else Severity.ERROR,
        message,
    )


def _files(snapshot: SourceSnapshot) -> Result[dict[str, SnapshotEntry]]:
    digest = source_snapshot_digest(snapshot)
    if isinstance(digest, Err):
        return _error("registry command requires one safe inert workspace snapshot")
    return Ok({str(item.path): item for item in snapshot.entries})


def _path(raw: str) -> SafeRelativePath:
    parsed = parse_relative_path(raw)
    assert isinstance(parsed, Ok)
    return parsed.value


def _change(
    raw_path: str,
    before: SnapshotEntry | None,
    content: bytes,
    *,
    executable: bool = False,
) -> RegistryWorkspaceChange:
    before_digest = None if before is None else sha256_bytes(before.content)
    after_digest = sha256_bytes(content)
    if before is None:
        kind = WorkspaceChangeKind.ADDED
    elif before.content == content and before.executable == executable:
        kind = WorkspaceChangeKind.UNCHANGED
    else:
        kind = WorkspaceChangeKind.CHANGED
    return RegistryWorkspaceChange(
        _path(raw_path),
        kind,
        content,
        before_digest,
        after_digest,
        executable,
    )


def _removal(raw_path: str, before: SnapshotEntry) -> RegistryWorkspaceChange:
    return RegistryWorkspaceChange(
        _path(raw_path),
        WorkspaceChangeKind.REMOVED,
        b"",
        sha256_bytes(before.content),
        None,
        before.executable,
    )


def _project_changes(
    snapshot: SourceSnapshot,
    changes: tuple[RegistryWorkspaceChange, ...],
) -> Result[SourceSnapshot]:
    current = _files(snapshot)
    if isinstance(current, Err):
        return current
    output = dict(current.value)
    for change in changes:
        raw = str(change.path)
        before = output.get(raw)
        if before is not None and before.kind is not SnapshotEntryKind.FILE:
            return _error(f"registry change target is not a regular file: {raw}")
        actual = None if before is None else sha256_bytes(before.content)
        if actual != change.before_digest:
            return _error(f"registry change precondition changed: {raw}")
        if change.kind is WorkspaceChangeKind.REMOVED:
            # The directory entries stay: an emptied directory is still on disk after the file is
            # unlinked, and a projection that dropped it would disagree with the snapshot the
            # applier re-reads to verify itself.  Git does not track empty directories, so the
            # maintainer's commit is unaffected either way.
            del output[raw]
            continue
        output[raw] = SnapshotEntry(
            change.path,
            SnapshotEntryKind.FILE,
            change.content,
            change.executable,
        )
        for length in range(1, len(change.path.parts)):
            parent = SafeRelativePath(change.path.parts[:length])
            existing = output.get(str(parent))
            if existing is not None and existing.kind is not SnapshotEntryKind.DIRECTORY:
                return _error(f"registry change parent is not a directory: {parent}")
            output.setdefault(
                str(parent),
                SnapshotEntry(parent, SnapshotEntryKind.DIRECTORY),
            )
    return Ok(SourceSnapshot(snapshot.origin, tuple(output.values())))


def _plan(
    operation: RegistryOperation,
    snapshot: SourceSnapshot,
    desired: tuple[tuple[str, bytes, bool], ...],
    *,
    prune_under: str | None = None,
) -> Result[RegistryWorkspacePlan]:
    """Plan exactly ``desired``; under ``prune_under``, also remove what ``desired`` no longer names.

    Pruning is opt-in and confined to one directory because every other operation writes a fixed set
    of derived documents and owns nothing else in the workspace.
    """

    current = _files(snapshot)
    if isinstance(current, Err):
        return current
    expected = source_snapshot_digest(snapshot)
    if isinstance(expected, Err):
        return expected
    kept = {path for path, _content, _executable in desired}
    changes = tuple(
        _change(path, current.value.get(path), content, executable=executable)
        for path, content, executable in sorted(desired)
    ) + (
        ()
        if prune_under is None
        else tuple(
            _removal(raw, entry)
            for raw, entry in sorted(current.value.items())
            if raw.startswith(f"{prune_under}/")
            and entry.kind is SnapshotEntryKind.FILE
            and raw not in kept
        )
    )
    projected = _project_changes(snapshot, changes)
    if isinstance(projected, Err):
        return projected
    next_digest = source_snapshot_digest(projected.value)
    if isinstance(next_digest, Err):
        return next_digest
    return Ok(
        RegistryWorkspacePlan(
            operation,
            expected.value,
            next_digest.value,
            changes,
            registry_workspace_review_digest(
                operation,
                expected.value,
                next_digest.value,
                changes,
            ),
        )
    )


def project_registry_workspace_plan(
    snapshot: SourceSnapshot,
    plan: RegistryWorkspacePlan,
) -> Result[SourceSnapshot]:
    current = source_snapshot_digest(snapshot)
    if isinstance(current, Err):
        return current
    if current.value != plan.expected_snapshot_digest:
        return _error("registry workspace changed after plan review")
    projected = _project_changes(snapshot, plan.changes)
    if isinstance(projected, Err):
        return projected
    digest = source_snapshot_digest(projected.value)
    if isinstance(digest, Err) or digest.value != plan.next_snapshot_digest:
        return _error("registry plan no longer produces its reviewed snapshot")
    return projected


def plan_registry_workspace_files(
    operation: RegistryOperation,
    snapshot: SourceSnapshot,
    desired: tuple[tuple[str, bytes, bool], ...],
) -> Result[RegistryWorkspacePlan]:
    """Build a reviewed plan for already-materialized deterministic managed files."""

    return _plan(operation, snapshot, desired)


def plan_registry_init(
    snapshot: SourceSnapshot,
    options: RegistryInitOptions,
) -> Result[RegistryWorkspacePlan]:
    files = _files(snapshot)
    if isinstance(files, Err):
        return files
    occupied = {
        "aart-registry.json",
        "aart-source.json",
        "aart.lock.json",
        "aart.index.json",
    } & files.value.keys()
    if occupied:
        return _error("registry init refuses an existing registry workspace")
    templates = (
        (".github/workflows/aart-registry.yml", REGISTRY_CI_WORKFLOW),
        *REPORTING_TEMPLATES,
    )
    for path, expected in templates:
        existing = files.value.get(path)
        if existing is not None and (
            existing.kind is not SnapshotEntryKind.FILE
            or existing.content != expected
            or existing.executable
        ):
            return _error(f"registry init refuses to overwrite an existing template: {path}")
    bounds = VersionBounds(options.minimum_aart, options.maximum_aart_exclusive)
    registry = RegistryManifest(
        1,
        1,
        SourceId(options.registry_id),
        options.display_name,
        bounds,
        tuple(
            Capability(value)
            for value in (
                "artifact-manifest-v1",
                "lockfile-v1",
                "registry-entry-v1",
            )
        ),
        "main",
    )
    source = SourceManifest(
        1,
        1,
        SourceId(options.registry_id),
        options.display_name,
        bounds,
        (Capability("artifact-manifest-v1"),),
        (_path("artifacts"),),
        (_path("collections"),),
    )
    return _plan(
        RegistryOperation.INIT,
        snapshot,
        (
            *((path, content, False) for path, content in templates),
            (
                "aart-registry.json",
                canonical_json_bytes(registry_manifest_to_json(registry)),
                False,
            ),
            (
                "aart-source.json",
                canonical_json_bytes(source_manifest_to_json(source)),
                False,
            ),
        ),
    )


def _source_manifest(files: dict[str, SnapshotEntry]) -> Result[SourceManifest]:
    marker = files.get("aart-source.json")
    if marker is None or marker.kind is not SnapshotEntryKind.FILE:
        return _error("registry workspace requires aart-source.json")
    parsed = parse_source_manifest(marker.content)
    if isinstance(parsed, Err):
        return parsed
    if parsed.value.artifact_roots != (
        _path("artifacts"),
    ) or parsed.value.collection_roots not in {
        (),
        (_path("collections"),),
    }:
        return _error(
            "registry maintainer commands require canonical artifacts/ and collections/ roots"
        )
    return parsed


def _payload(
    options: ArtifactScaffoldOptions,
    *,
    base: str,
) -> tuple[tuple[str, bytes, bool], ...]:
    """Create a minimally runnable primary payload for a new canonical package.

    A scaffold must itself satisfy the same compiler used by publication.  In particular, hook
    descriptors cannot be empty placeholders: they need a registration and an executable target.
    """

    if options.kind == "skill":
        return (
            (
                f"{base}/SKILL.md",
                (
                    f"---\nname: {options.name}\ndescription: {options.summary}\n---\n\n"
                    f"# {options.name.replace('-', ' ').title()}\n"
                ).encode(),
                False,
            ),
        )
    if options.kind in {"guideline", "memory"}:
        return (
            (
                f"{base}/{options.name}.md",
                f"# {options.name.replace('-', ' ').title()}\n\n{options.summary}\n".encode(),
                False,
            ),
        )
    if options.kind == "mcp":
        return (
            (
                f"{base}/mcp.json",
                canonical_json_bytes(
                    JsonObject(
                        (
                            ("name", options.name),
                            (
                                "server",
                                JsonObject(
                                    (
                                        ("command", "echo"),
                                        (
                                            "args",
                                            JsonArray(
                                                (
                                                    f"{options.name} is a scaffold; review its "
                                                    "MCP command before use.",
                                                )
                                            ),
                                        ),
                                    )
                                ),
                            ),
                        )
                    )
                ),
                False,
            ),
        )
    return (
        (
            f"{base}/hook.json",
            canonical_json_bytes(
                JsonObject(
                    (
                        ("name", options.name),
                        ("command", f"${{SCRIPT_DIR}}/{options.name}.sh"),
                    )
                )
            ),
            False,
        ),
        (
            f"{base}/{options.name}.sh",
            (
                f"#!/bin/sh\nprintf '%s\\n' '{options.name} hook scaffold requires author review'\n"
            ).encode(),
            True,
        ),
    )


def plan_artifact_scaffold(
    snapshot: SourceSnapshot,
    options: ArtifactScaffoldOptions,
) -> Result[RegistryWorkspacePlan]:
    files = _files(snapshot)
    if isinstance(files, Err):
        return files
    source = _source_manifest(files.value)
    if isinstance(source, Err):
        return source
    root = source.value.artifact_roots[0]
    base = f"{root}/{options.kind}/{options.name}"
    if any(path == base or path.startswith(f"{base}/") for path in files.value):
        return _error(f"artifact package already exists: {options.kind}/{options.name}")
    kind = cast(CanonicalArtifactType, options.kind)
    manifest = ArtifactManifest(
        1,
        ArtifactIdentity(kind, options.name),
        options.version,
        options.summary,
        PayloadSpec(_path("payload"), PAYLOAD_FORMAT_BY_TYPE[kind]),
        CompatibilitySpec(options.profiles, options.platforms),
        InstallSpec(
            cast(tuple[InstallScope, ...], options.scopes),
            cast(tuple[InstallMode, ...], options.modes),
            tuple(sorted(INSTALL_EFFECTS_BY_TYPE[kind])),
        ),
    )
    payload = _payload(options, base=f"{base}/payload")
    return _plan(
        RegistryOperation.SCAFFOLD,
        snapshot,
        (
            (
                f"{base}/artifact.json",
                canonical_json_bytes(artifact_manifest_to_json(manifest)),
                False,
            ),
            *payload,
        ),
    )


def _adopted_authored(
    files: dict[str, SnapshotEntry],
    base: str,
) -> tuple[tuple[str, bytes, bool], ...]:
    """Whatever the maintainer already wrote inside the target package.

    A foreign subtree almost never satisfies its kind's payload contract on its own, and no flag can
    carry file bytes. So `vendor` adopts the files the maintainer has already placed at the target
    path — the `payload/mcp.json` wrapper, a `SETUP.md`, a `setup/` recipe — and projects them
    alongside the taken bytes, where `VN-2`'s refusals judge them. `artifact.json` and
    `provenance.json` are excluded because the projection derives them.
    """

    prefix = f"{base}/"
    return tuple(
        (raw.removeprefix(prefix), item.content, item.executable)
        for raw, item in sorted(files.items())
        if raw.startswith(prefix)
        and item.kind is SnapshotEntryKind.FILE
        and raw.removeprefix(prefix) not in {"artifact.json", "provenance.json"}
    )


def plan_artifact_vendor(
    snapshot: SourceSnapshot,
    acquisition: NativeReferenceAcquisition,
    options: VendorOptions,
    *,
    path: SafeRelativePath,
    review: ReviewRecord,
    importer_version: SemVer,
) -> Result[VendoredArtifactPlan]:
    """Plan the owned package a reviewed vendoring would write, writing nothing.

    The approved review record is the same gate `plan_native_promotion` applies: a vendoring is the
    moment foreign bytes become this registry's responsibility, and it does not happen unreviewed.
    """

    if review.status != "approved":
        return _error("vendoring requires an approved review record")
    files = _files(snapshot)
    if isinstance(files, Err):
        return files
    source = _source_manifest(files.value)
    if isinstance(source, Err):
        return source
    root = source.value.artifact_roots[0]
    identity = options.identity
    base = f"{root}/{identity.kind}/{identity.name}"
    # An existing manifest is an existing package: adopting the maintainer's authored wrapper is the
    # point, so their `payload/` and `setup/` files must not read as one.
    if f"{base}/artifact.json" in files.value:
        return _error(f"artifact package already exists: {identity.kind}/{identity.name}")
    taken = take_subtree(acquisition.snapshot, path)
    if isinstance(taken, Err):
        return taken
    projected = project_vendored_package(
        taken.value,
        VendorOrigin(acquisition.url, acquisition.requested_ref, acquisition.resolved_commit),
        replace(options, authored=_adopted_authored(files.value, base)),
        artifact_root=root,
        importer_version=importer_version,
    )
    if isinstance(projected, Err):
        return projected
    written = {relative for relative, _content, _executable in projected.value.files}
    if options.setup_recipe is not None:
        for required in (f"{base}/{options.setup_recipe}", f"{base}/SETUP.md"):
            if required not in written:
                return _error(
                    f"the declared setup recipe requires {required}, which is not present"
                )
    # The assessment runs over the projected object, so the review reports what the baseline found
    # in the exact bytes this vendoring writes — the maintainer's own wrapper as much as the copied
    # payload — and the evidence is committed beside the package for the next reader.
    assessed = assess_vendored_package(projected.value, source_id=source.value.source_id)
    if isinstance(assessed, Err):
        return assessed
    planned = _plan(
        RegistryOperation.VENDOR,
        snapshot,
        (*projected.value.files, (assessed.value.document_path, assessed.value.document, False)),
    )
    if isinstance(planned, Err):
        return planned
    return Ok(
        VendoredArtifactPlan(planned.value, assessed.value.assessment, projected.value.license)
    )


@dataclass(frozen=True, slots=True)
class VendoredArtifactOrigin:
    """What the workspace already knows about one vendored copy, before anything is acquired."""

    base: str
    url: str
    ref: str
    path: SafeRelativePath
    recorded_commit: str
    input_digest: ObjectDigest
    manifest: ArtifactManifest
    authored: tuple[str, ...]


def read_vendored_artifact(
    snapshot: SourceSnapshot,
    identity: ArtifactIdentity,
) -> Result[VendoredArtifactOrigin]:
    """Read one vendored package's own record of where it came from.

    Separate from planning because the caller has to acquire between the two: the recorded ref is
    the thing being resolved, and it lives in the package.
    """

    files = _files(snapshot)
    if isinstance(files, Err):
        return files
    source = _source_manifest(files.value)
    if isinstance(source, Err):
        return source
    base = f"{source.value.artifact_roots[0]}/{identity.kind}/{identity.name}"
    manifest_entry = files.value.get(f"{base}/artifact.json")
    if manifest_entry is None:
        return _error(f"registry has no artifact package {identity.kind}/{identity.name}")
    manifest = parse_artifact_manifest(manifest_entry.content, path=f"{base}/artifact.json")
    if isinstance(manifest, Err):
        return manifest
    return read_vendored_package(files.value, base, manifest.value)


def read_vendored_package(
    files: dict[str, SnapshotEntry],
    base: str,
    manifest: ArtifactManifest,
) -> Result[VendoredArtifactOrigin]:
    """The same read from a package already located, for callers walking every artifact root.

    `registry audit` visits packages by path rather than by identity, and a registry may declare
    more than one artifact root; resolving the identity again would look only under the first.
    """

    provenance_entry = files.get(f"{base}/provenance.json")
    if provenance_entry is None:
        return _error(
            f"{manifest.identity} records no provenance, so it was not vendored; "
            "refresh-native updates a native reference"
        )
    provenance = parse_provenance(provenance_entry.content, path=f"{base}/provenance.json")
    if isinstance(provenance, Err):
        return provenance
    record = read_vendor_record(provenance.value)
    if isinstance(record, Err):
        return record
    origin = provenance.value.origin
    return Ok(
        VendoredArtifactOrigin(
            base,
            origin.url,
            record.value.ref,
            origin.path,
            origin.resolved_commit,
            origin.input_digest,
            manifest,
            record.value.authored,
        )
    )


def _drift_counts(
    files: dict[str, SnapshotEntry],
    vendored: VendoredArtifactOrigin,
    taken: TakenSubtree,
) -> tuple[int, int, int]:
    """Compare upstream's files with the copy's, ignoring what the maintainer wrote themselves.

    Derived documents are excluded because they are projections of these inputs, not evidence of
    upstream movement: reporting `artifact.json` as changed would count the version bump as drift.
    """

    authored = {f"{vendored.base}/{relative}" for relative in vendored.authored} | {
        f"{vendored.base}/artifact.json",
        f"{vendored.base}/provenance.json",
    }
    copied = {
        raw: entry
        for raw, entry in files.items()
        if raw.startswith(f"{vendored.base}/")
        and entry.kind is SnapshotEntryKind.FILE
        and raw not in authored
    }
    upstream = {
        f"{vendored.base}/{vendored.manifest.payload.root}/{entry.path}": entry
        for entry in taken.snapshot.entries
        if entry.kind is SnapshotEntryKind.FILE
    }
    changed = sum(
        1
        for raw, entry in upstream.items()
        if raw in copied
        and (copied[raw].content != entry.content or copied[raw].executable != entry.executable)
    )
    return (
        len(upstream.keys() - copied.keys()),
        changed,
        len(copied.keys() - upstream.keys()),
    )


def plan_artifact_revendor(
    snapshot: SourceSnapshot,
    acquisition: NativeReferenceAcquisition,
    vendored: VendoredArtifactOrigin,
    *,
    version: SemVer | None,
    review: ReviewRecord,
    importer_version: SemVer,
) -> Result[VendoredArtifactCheck]:
    """Re-resolve one vendored copy against upstream and report what that means.

    An `up-to-date` copy is left alone deliberately, including its recorded commit: a ref that has
    moved over content the subtree does not contain has changed nothing this registry ships, and
    re-pinning would produce a diff claiming the copy was refreshed when it was not.
    """

    if review.status != "approved":
        return _error("re-vendoring requires an approved review record")
    if acquisition.url != vendored.url or acquisition.requested_ref != vendored.ref:
        return _error("the acquisition does not resolve the recorded vendoring instruction")
    files = _files(snapshot)
    if isinstance(files, Err):
        return files
    taken = take_subtree(acquisition.snapshot, vendored.path)
    if isinstance(taken, Err):
        return taken
    added, changed, removed = _drift_counts(files.value, vendored, taken.value)
    if taken.value.input_digest == vendored.input_digest:
        return Ok(
            VendoredArtifactCheck(
                NativeReferenceDisposition.UP_TO_DATE,
                acquisition.resolved_commit,
                vendored.recorded_commit,
                0,
                0,
                0,
            )
        )
    drifted = VendoredArtifactCheck(
        NativeReferenceDisposition.CHANGED,
        acquisition.resolved_commit,
        vendored.recorded_commit,
        added,
        changed,
        removed,
    )
    if version is None:
        # The diff is rendered before the refusal, not instead of it: the maintainer cannot choose
        # the version the movement deserves without first seeing the movement (design §4).
        return Ok(drifted)
    manifest = vendored.manifest
    authored: list[tuple[str, bytes, bool]] = []
    for relative in vendored.authored:
        entry = files.value.get(f"{vendored.base}/{relative}")
        if entry is None or entry.kind is not SnapshotEntryKind.FILE:
            return _error(f"the authored file recorded with this copy is missing: {relative}")
        authored.append((relative, entry.content, entry.executable))
    options = VendorOptions(
        manifest.identity,
        version,
        manifest.summary,
        manifest.compatibility.profiles,
        manifest.compatibility.platforms,
        manifest.install.scopes,
        manifest.install.modes,
        None if manifest.setup is None else manifest.setup.recipe,
        () if manifest.setup is None else manifest.setup.platforms,
        tuple(authored),
        (),
        # The recorded licence is carried, not re-derived: it is the registry's own statement about
        # what it publishes, and a re-vendor that silently dropped it would turn every upstream
        # movement into an unlicensed copy.
        license=manifest.license,
    )
    projected = project_vendored_package(
        taken.value,
        VendorOrigin(vendored.url, vendored.ref, acquisition.resolved_commit),
        options,
        artifact_root=_path(vendored.base.split("/", 1)[0]),
        importer_version=importer_version,
    )
    if isinstance(projected, Err):
        return projected
    source = _source_manifest(files.value)
    if isinstance(source, Err):
        return source
    assessed = assess_vendored_package(projected.value, source_id=source.value.source_id)
    if isinstance(assessed, Err):
        return assessed
    planned = _plan(
        RegistryOperation.REVENDOR,
        snapshot,
        (*projected.value.files, (assessed.value.document_path, assessed.value.document, False)),
        # Upstream deletions have to reach the copy.  Confined to this package's own directory, so
        # a re-vendor can never remove another artifact's content.
        prune_under=vendored.base,
    )
    if isinstance(planned, Err):
        return planned
    return Ok(
        replace(drifted, plan=planned.value, assessment=assessed.value.assessment),
    )


def plan_registry_format(snapshot: SourceSnapshot) -> Result[RegistryWorkspacePlan]:
    files = _files(snapshot)
    if isinstance(files, Err):
        return files
    source = _source_manifest(files.value)
    if isinstance(source, Err):
        return source

    def is_protocol_document(path: str) -> bool:
        if path in {
            "aart-registry.json",
            "aart-source.json",
            "aart.lock.json",
            "aart.index.json",
        } or path.startswith("entries/"):
            return path.endswith(".json")
        parts = tuple(path.split("/"))
        for root in source.value.collection_roots:
            if parts[: len(root.parts)] == root.parts:
                return path.endswith(".json")
        for root in source.value.artifact_roots:
            if parts[: len(root.parts)] != root.parts:
                continue
            relative = parts[len(root.parts) :]
            return (
                len(relative) == 3 and relative[-1] in {"artifact.json", "provenance.json"}
            ) or (len(relative) == 4 and relative[-2:] == ("setup", "installer.json"))
        return False

    desired: list[tuple[str, bytes, bool]] = []
    for path, item in sorted(files.value.items()):
        if item.kind is not SnapshotEntryKind.FILE or not is_protocol_document(path):
            continue
        parsed = parse_json(item.content)
        if isinstance(parsed, Err):
            return parsed
        desired.append((path, canonical_json_bytes(parsed.value), item.executable))
    if not desired:
        return _error("registry format found no JSON documents")
    return _plan(RegistryOperation.FORMAT, snapshot, tuple(desired))


def _registry_inputs(
    snapshot: SourceSnapshot,
) -> Result[tuple[RegistryManifest, SourceManifest, tuple]]:
    files = _files(snapshot)
    if isinstance(files, Err):
        return files
    registry_file = files.value.get("aart-registry.json")
    if registry_file is None or registry_file.kind is not SnapshotEntryKind.FILE:
        return _error("registry workspace requires aart-registry.json")
    registry = parse_registry_manifest(registry_file.content)
    source = _source_manifest(files.value)
    if isinstance(registry, Err):
        return registry
    if isinstance(source, Err):
        return source
    if registry.value.registry_id != source.value.source_id:
        return _error("registry and source identities differ")
    entries = []
    for path, item in sorted(files.value.items()):
        if not path.startswith("entries/") or item.kind is not SnapshotEntryKind.FILE:
            continue
        parsed = parse_registry_entry(item.content, path=path)
        if isinstance(parsed, Err):
            return parsed
        expected_path = f"entries/{parsed.value.identity.kind}/{parsed.value.identity.name}.json"
        if path != expected_path:
            return _error(f"registry entry identity does not match its path: {path}")
        entries.append(parsed.value)
    identities = tuple(item.identity for item in entries)
    if len(set(identities)) != len(identities):
        return _error("registry workspace contains duplicate entry identities")
    return Ok((registry.value, source.value, tuple(entries)))


def _acquisitions_by_identity(
    entries: tuple,
    acquisitions: tuple[NativeReferenceAcquisition, ...],
    *,
    executable_version: SemVer,
    available_capabilities: tuple[Capability, ...],
) -> Result[dict[ArtifactIdentity, tuple]]:
    if len(entries) != len(acquisitions):
        return _error("registry lock/build requires one acquisition per entry")
    available = list(acquisitions)
    resolved: dict[ArtifactIdentity, tuple] = {}
    for entry in entries:
        matches = []
        for acquisition in available:
            result = resolve_native_acquisition(
                entry,
                acquisition,
                executable_version=executable_version,
                available_capabilities=available_capabilities,
            )
            if isinstance(result, Ok):
                matches.append((acquisition, (*result.value, acquisition)))
        if len(matches) != 1:
            return _error(f"registry acquisition is missing or ambiguous for {entry.identity}")
        available.remove(matches[0][0])
        resolved[entry.identity] = matches[0][1]
    return Ok(resolved)


def plan_registry_lock(
    snapshot: SourceSnapshot,
    acquisitions: tuple[NativeReferenceAcquisition, ...],
    *,
    executable_version: SemVer,
    available_capabilities: tuple[Capability, ...],
) -> Result[RegistryWorkspacePlan]:
    parsed = _registry_inputs(snapshot)
    if isinstance(parsed, Err):
        return parsed
    _registry, _source, entries = parsed.value
    if any(entry.review.status != "approved" for entry in entries):
        return _error("registry lock requires every authored entry to be approved")
    resolved = _acquisitions_by_identity(
        entries,
        acquisitions,
        executable_version=executable_version,
        available_capabilities=available_capabilities,
    )
    if isinstance(resolved, Err):
        return resolved
    inputs = registry_inputs_digest(snapshot)
    if isinstance(inputs, Err):
        return inputs
    locked = []
    for entry in entries:
        package, candidate, provenance_digest, _source_id, acquisition = resolved.value[
            entry.identity
        ]
        locked.append(
            (
                entry.identity,
                LockedArtifact(
                    acquisition.url,
                    acquisition.requested_ref,
                    acquisition.resolved_commit,
                    entry.source.path,
                    package.manifest_digest,
                    package.payload_digest,
                    candidate.digest,
                    package.manifest.version,
                    entry.review,
                    provenance_digest,
                ),
            )
        )
    lock = RegistryLock(1, inputs.value, tuple(locked))
    return _plan(
        RegistryOperation.LOCK,
        snapshot,
        (("aart.lock.json", canonical_json_bytes(registry_lock_to_json(lock)), False),),
    )


def plan_registry_build(
    snapshot: SourceSnapshot,
    acquisitions: tuple[NativeReferenceAcquisition, ...],
    *,
    executable_version: SemVer,
    available_capabilities: tuple[Capability, ...],
) -> Result[RegistryWorkspacePlan]:
    parsed = _registry_inputs(snapshot)
    if isinstance(parsed, Err):
        return parsed
    registry, _source, entries = parsed.value
    files = _files(snapshot)
    assert isinstance(files, Ok)
    lock_file = files.value.get("aart.lock.json")
    if lock_file is None or lock_file.kind is not SnapshotEntryKind.FILE:
        return _error("registry build requires a committed aart.lock.json")
    lock = parse_registry_lock(lock_file.content)
    inputs = registry_inputs_digest(snapshot)
    if isinstance(lock, Err):
        return lock
    if isinstance(inputs, Err):
        return inputs
    references = resolve_locked_references(
        entries,
        lock.value,
        expected_inputs_digest=inputs.value,
    )
    if isinstance(references, Err):
        return references
    resolved = _acquisitions_by_identity(
        entries,
        acquisitions,
        executable_version=executable_version,
        available_capabilities=available_capabilities,
    )
    if isinstance(resolved, Err):
        return resolved
    native = registry_native_content(
        snapshot,
        files.value,
        registry,
        executable_version=executable_version,
        available_capabilities=available_capabilities,
    )
    if isinstance(native, Err):
        return native
    owned, collections = native.value
    indexed = list(owned)
    locked_by_identity = dict(lock.value.entries)
    for entry in entries:
        package, candidate, provenance_digest, source_id, acquisition = resolved.value[
            entry.identity
        ]
        actual = LockedArtifact(
            acquisition.url,
            acquisition.requested_ref,
            acquisition.resolved_commit,
            entry.source.path,
            package.manifest_digest,
            package.payload_digest,
            candidate.digest,
            package.manifest.version,
            entry.review,
            provenance_digest,
        )
        if locked_by_identity.get(entry.identity) != actual:
            return _error(f"acquired package does not match lock for {entry.identity}")
        indexed.append(
            index_artifact_from_package(
                package,
                source_id=source_id,
                object_digest=candidate.digest,
                review=entry.review,
            )
        )
    index = build_registry_index(registry, inputs.value, tuple(indexed), collections)
    if isinstance(index, Err):
        return index
    return _plan(
        RegistryOperation.BUILD,
        snapshot,
        (("aart.index.json", canonical_json_bytes(registry_index_to_json(index.value)), False),),
    )


def validate_registry_workspace(
    snapshot: SourceSnapshot,
    *,
    executable_version: SemVer,
    available_capabilities: tuple[Capability, ...],
    require_compiled: bool = False,
) -> Result[RegistryQualityReport]:
    diagnostics: list[Diagnostic] = []
    parsed = _registry_inputs(snapshot)
    if isinstance(parsed, Err):
        diagnostics.extend(parsed.diagnostics)
        return Ok(RegistryQualityReport((RegistryQualityCheck("validate", tuple(diagnostics)),)))
    registry, _source, entries = parsed.value
    files = _files(snapshot)
    assert isinstance(files, Ok)
    native = registry_native_content(
        snapshot,
        files.value,
        registry,
        executable_version=executable_version,
        available_capabilities=available_capabilities,
    )
    if isinstance(native, Err):
        diagnostics.extend(native.diagnostics)
    inputs = registry_inputs_digest(snapshot)
    if isinstance(inputs, Err):
        diagnostics.extend(inputs.diagnostics)
    lock_file = files.value.get("aart.lock.json")
    index_file = files.value.get("aart.index.json")
    valid_lock_file = lock_file is not None and lock_file.kind is SnapshotEntryKind.FILE
    valid_index_file = index_file is not None and index_file.kind is SnapshotEntryKind.FILE
    if lock_file is not None and not valid_lock_file:
        diagnostics.append(_diagnostic("aart.lock.json must be a regular file"))
    if index_file is not None and not valid_index_file:
        diagnostics.append(_diagnostic("aart.index.json must be a regular file"))
    if require_compiled and (not valid_lock_file or not valid_index_file):
        diagnostics.append(_diagnostic("compiled registry requires lock and index"))
    parsed_lock = None
    if lock_file is not None and lock_file.kind is SnapshotEntryKind.FILE:
        lock = parse_registry_lock(lock_file.content)
        if isinstance(lock, Err):
            diagnostics.extend(lock.diagnostics)
        else:
            parsed_lock = lock.value
        if isinstance(lock, Ok) and isinstance(inputs, Ok):
            resolved = resolve_locked_references(
                entries,
                lock.value,
                expected_inputs_digest=inputs.value,
            )
            if isinstance(resolved, Err):
                diagnostics.extend(resolved.diagnostics)
    parsed_index = None
    if index_file is not None and index_file.kind is SnapshotEntryKind.FILE:
        index = parse_registry_index(index_file.content)
        if isinstance(index, Err):
            diagnostics.extend(index.diagnostics)
        else:
            parsed_index = index.value
            if isinstance(inputs, Ok) and (
                index.value.registry_id != registry.registry_id
                or index.value.protocol_version != registry.protocol_version
                or index.value.registry_inputs_digest != inputs.value
                or index.value.services != registry.services
            ):
                diagnostics.append(_diagnostic("compiled index does not match registry inputs"))
    if parsed_index is not None and parsed_lock is None:
        diagnostics.append(_diagnostic("compiled index requires a valid committed lock"))
    if parsed_index is not None and parsed_lock is not None and isinstance(native, Ok):
        indexed_by_identity = {item.identity: item for item in parsed_index.artifacts}
        locked_by_identity = dict(parsed_lock.entries)
        for identity, locked in sorted(locked_by_identity.items(), key=lambda item: str(item[0])):
            indexed = indexed_by_identity.get(identity)
            if indexed is None or not (
                indexed.version == locked.artifact_version
                and indexed.manifest_digest == locked.manifest_digest
                and indexed.payload_digest == locked.payload_digest
                and indexed.object_digest == locked.object_digest
                and indexed.review == locked.review
                and (indexed.provenance is None) == (locked.provenance_digest is None)
                and (
                    indexed.provenance is None
                    or (
                        indexed.provenance.origin_url == locked.origin_url
                        and indexed.provenance.resolved_commit == locked.resolved_commit
                        and indexed.provenance.path == locked.path
                    )
                )
            ):
                diagnostics.append(
                    _diagnostic(f"compiled index disagrees with lock for {identity}")
                )
        owned_by_identity = {item.identity: item for item in native.value[0]}
        for identity, owned in sorted(owned_by_identity.items(), key=lambda item: str(item[0])):
            indexed = indexed_by_identity.get(identity)
            if indexed is None or replace(indexed, collections=()) != owned:
                diagnostics.append(
                    _diagnostic(f"compiled index disagrees with owned package {identity}")
                )
        if set(indexed_by_identity) != set(locked_by_identity) | set(owned_by_identity):
            diagnostics.append(_diagnostic("compiled index artifact identities are incomplete"))
        if parsed_index.collections != native.value[1]:
            diagnostics.append(_diagnostic("compiled index collections differ from source"))
    return Ok(RegistryQualityReport((RegistryQualityCheck("validate", tuple(diagnostics)),)))


def _vendored_upstream_findings(
    acquirer: NativeAcquirer,
    vendored: VendoredArtifactOrigin,
) -> tuple[Diagnostic, ...]:
    """Report whether one vendored copy still matches upstream, and never guess when it cannot.

    Read-only by construction: it resolves and compares, and no caller can turn the answer into a
    write. An upstream that cannot be read is reported as unknown rather than as drift, because a
    maintainer who has lost access to an origin has a different problem from one who is behind it,
    and neither of them is told their copy is current (design §6).
    """

    identity = vendored.manifest.identity
    acquired = acquirer(vendored.url, vendored.ref)
    if isinstance(acquired, Err):
        return (
            _diagnostic(
                f"vendored artifact upstream could not be read, so drift is unknown: {identity} "
                f"({vendored.url} at {vendored.ref})",
                warning=True,
            ),
        )
    taken = take_subtree(acquired.value.snapshot, vendored.path)
    if isinstance(taken, Err):
        return (
            _diagnostic(
                f"vendored artifact is behind upstream: {identity} was taken from "
                f"{vendored.path}, which {vendored.ref} no longer provides",
                warning=True,
            ),
        )
    if taken.value.input_digest == vendored.input_digest:
        return ()
    return (
        _diagnostic(
            f"vendored artifact is behind upstream: {identity} copies {vendored.path} at "
            f"{vendored.recorded_commit[:12]}, and {vendored.ref} now resolves to "
            f"{acquired.value.resolved_commit[:12]}",
            warning=True,
        ),
    )


def audit_registry_workspace(
    snapshot: SourceSnapshot,
    *,
    executable_version: SemVer,
    available_capabilities: tuple[Capability, ...],
    upstream_acquirer: NativeAcquirer | None = None,
) -> Result[RegistryQualityReport]:
    """Audit committed registry content, optionally resolving vendored origins.

    `upstream_acquirer` is absent by default, which keeps the audit a pure function of the snapshot:
    a command that silently reached the network would make every offline run a failure and every CI
    run dependent on somebody else's uptime. A caller that wants the drift report supplies one, and
    gets findings that report rather than refuse.
    """

    parsed = _registry_inputs(snapshot)
    if isinstance(parsed, Err):
        return Ok(RegistryQualityReport((RegistryQualityCheck("audit", parsed.diagnostics),)))
    registry, source, entries = parsed.value
    files = _files(snapshot)
    assert isinstance(files, Ok)
    diagnostics: list[Diagnostic] = []
    native = registry_native_content(
        snapshot,
        files.value,
        registry,
        executable_version=executable_version,
        available_capabilities=available_capabilities,
    )
    if isinstance(native, Err):
        diagnostics.extend(native.diagnostics)
    if not entries:
        diagnostics.append(
            _diagnostic(
                "registry contains no external references; provenance coverage is partial",
                warning=True,
            )
        )
    for entry in entries:
        if entry.review.status != "approved":
            diagnostics.append(_diagnostic(f"external reference is not approved: {entry.identity}"))
    lock_file = files.value.get("aart.lock.json")
    if entries and (lock_file is None or lock_file.kind is not SnapshotEntryKind.FILE):
        diagnostics.append(_diagnostic("external reference audit requires a valid committed lock"))
    if lock_file is not None and lock_file.kind is SnapshotEntryKind.FILE:
        lock = parse_registry_lock(lock_file.content)
        if isinstance(lock, Err):
            diagnostics.extend(lock.diagnostics)
        else:
            if {identity for identity, _locked in lock.value.entries} != {
                entry.identity for entry in entries
            }:
                diagnostics.append(
                    _diagnostic("committed lock identities differ from authored references")
                )
            for identity, locked in lock.value.entries:
                if locked.provenance_digest is None:
                    diagnostics.append(
                        _diagnostic(
                            f"external reference has no provenance document: {identity}",
                            warning=True,
                        )
                    )
    roots = tuple(f"{root}/" for root in source.artifact_roots)
    for path, item in sorted(files.value.items()):
        if (
            item.kind is not SnapshotEntryKind.FILE
            or not path.endswith("/artifact.json")
            or not any(path.startswith(root) for root in roots)
        ):
            continue
        manifest = parse_artifact_manifest(item.content, path=path)
        if isinstance(manifest, Err):
            diagnostics.extend(manifest.diagnostics)
            continue
        base = path.removesuffix("/artifact.json")
        provenance_path = f"{base}/provenance.json"
        provenance = files.value.get(provenance_path)
        vendored: VendoredArtifactOrigin | None = None
        if provenance is None:
            diagnostics.append(
                _diagnostic(
                    f"owned package has no provenance document: {manifest.value.identity}",
                    warning=True,
                )
            )
        elif provenance.kind is not SnapshotEntryKind.FILE:
            diagnostics.append(_diagnostic(f"provenance is not a file: {provenance_path}"))
        else:
            parsed_provenance = parse_provenance(provenance.content, path=provenance_path)
            if isinstance(parsed_provenance, Err):
                diagnostics.extend(parsed_provenance.diagnostics)
            elif parsed_provenance.value.importer.id == VENDOR_IMPORTER_ID:
                # A vendored package's own record of how the copy was made is checked against the
                # options digest written with it, so a hand-edited `provenance.json` is an audit
                # failure rather than the silent basis of the next re-vendor.
                read = read_vendored_package(files.value, base, manifest.value)
                if isinstance(read, Err):
                    diagnostics.extend(read.diagnostics)
                else:
                    vendored = read.value
        if manifest.value.license is None:
            diagnostics.append(
                _diagnostic(
                    # Vendoring redistributes somebody else's work, so the omission is named as
                    # what it is rather than folded into the generic finding (design §7).
                    f"vendored artifact redistributes upstream bytes with no declared license: "
                    f"{manifest.value.identity}"
                    if vendored is not None
                    else f"owned package has no declared license: {manifest.value.identity}",
                    warning=True,
                )
            )
        if vendored is not None and upstream_acquirer is not None:
            diagnostics.extend(_vendored_upstream_findings(upstream_acquirer, vendored))
        if manifest.value.setup is not None:
            recipe = f"{base}/{manifest.value.setup.recipe}"
            recipe_file = files.value.get(recipe)
            if recipe_file is None or recipe_file.kind is not SnapshotEntryKind.FILE:
                diagnostics.append(_diagnostic(f"declared setup recipe is missing: {recipe}"))
    security_file = files.value.get("security/index.json")
    if security_file is None:
        diagnostics.append(
            _diagnostic(
                "no per-object installation-risk evidence was supplied to registry audit",
                warning=True,
            )
        )
    elif security_file.kind is not SnapshotEntryKind.FILE:
        diagnostics.append(_diagnostic("registry security index is not a regular file"))
    else:
        security_index = parse_security_index(security_file.content)
        if isinstance(security_index, Err):
            diagnostics.extend(security_index.diagnostics)
        else:
            documents = []
            missing_document = False
            for security_entry in security_index.value.entries:
                document = files.value.get(str(security_entry.path))
                if document is None or document.kind is not SnapshotEntryKind.FILE:
                    diagnostics.append(
                        _diagnostic(
                            f"registry security index document is missing: {security_entry.path}"
                        )
                    )
                    missing_document = True
                    continue
                documents.append((security_entry.path, document.content))
            if not missing_document:
                verified = verify_security_index(security_index.value, tuple(documents))
                if isinstance(verified, Err):
                    diagnostics.extend(verified.diagnostics)
                else:
                    compiled_file = files.value.get("aart.index.json")
                    compiled = (
                        parse_registry_index(compiled_file.content)
                        if compiled_file is not None
                        and compiled_file.kind is SnapshotEntryKind.FILE
                        else None
                    )
                    if compiled is None or isinstance(compiled, Err):
                        diagnostics.append(
                            _diagnostic("registry security index requires a valid compiled index")
                        )
                    elif (
                        security_index.value.registry_id != registry.registry_id
                        or security_index.value.registry_id != compiled.value.registry_id
                        or security_index.value.registry_inputs_digest
                        != compiled.value.registry_inputs_digest
                    ):
                        diagnostics.append(
                            _diagnostic(
                                "registry security index identity differs from the compiled registry"
                            )
                        )
                    else:
                        expected_objects = {item.object_digest for item in compiled.value.artifacts}
                        evidence_objects = {
                            item.cache_key.object_digest for item in verified.value.attestations
                        }
                        missing_objects = expected_objects - evidence_objects
                        extra_objects = evidence_objects - expected_objects
                        if missing_objects:
                            diagnostics.append(
                                _diagnostic(
                                    "registry security index lacks evidence for one or more compiled objects"
                                )
                            )
                        if extra_objects:
                            diagnostics.append(
                                _diagnostic(
                                    "registry security index contains evidence for unknown objects"
                                )
                            )
                        for attestation in verified.value.attestations:
                            risk = attestation.assessment.installation_risk
                            if risk is InstallationRisk.CRITICAL:
                                diagnostics.append(
                                    _diagnostic(
                                        "registry security evidence reports critical installation risk "
                                        f"for {attestation.cache_key.object_digest}"
                                    )
                                )
                            elif risk in {InstallationRisk.HIGH, InstallationRisk.UNKNOWN}:
                                diagnostics.append(
                                    _diagnostic(
                                        "registry security evidence requires review because installation "
                                        f"risk is {risk.value} for {attestation.cache_key.object_digest}",
                                        warning=True,
                                    )
                                )
    return Ok(RegistryQualityReport((RegistryQualityCheck("audit", tuple(diagnostics)),)))


def test_registry_compatibility(
    snapshot: SourceSnapshot,
    *,
    minimum: SemVer,
    latest: SemVer,
    available_capabilities: tuple[Capability, ...],
) -> Result[RegistryQualityReport]:
    checks = []
    for name, version in (("minimum", minimum), ("latest", latest)):
        result = validate_registry_workspace(
            snapshot,
            executable_version=version,
            available_capabilities=available_capabilities,
            require_compiled=True,
        )
        assert isinstance(result, Ok)
        diagnostics = tuple(
            diagnostic for check in result.value.checks for diagnostic in check.diagnostics
        )
        checks.append(RegistryQualityCheck(name, diagnostics))
    return Ok(RegistryQualityReport(tuple(checks)))
