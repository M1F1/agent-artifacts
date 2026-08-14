"""Source-aware prepare/review/finalize orchestration for canonical installs."""

from __future__ import annotations

import json
import posixpath
import re
from dataclasses import dataclass, replace
from typing import Literal, Mapping, Protocol, cast

from agent_artifacts.compiler.graph import CompatibilityTarget, evaluate_compatibility
from agent_artifacts.configuration.model import SourceKind, git_location_parts
from agent_artifacts.configuration.policy import EffectiveConfiguration
from agent_artifacts.configuration.schema import organization_policy_bytes
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import ArtifactCoordinate
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.install_state.model import (
    ArtifactEvidence,
    EffectProof,
    InstallationRecord,
    InstallState,
    SourceEvidence,
)
from agent_artifacts.install_state.paths import install_state_paths
from agent_artifacts.install_state.schema import install_state_bytes, parse_install_state
from agent_artifacts.marketplace.catalog import resolve_artifact
from agent_artifacts.marketplace.model import ArtifactQuery, TrustClass
from agent_artifacts.profiles.model import Profile
from agent_artifacts.profiles.scope import profile_for_scope
from agent_artifacts.protocol.hashing import (
    json_digest,
    sha256_bytes,
)
from agent_artifacts.protocol.json import JsonArray, JsonObject, JsonValue, parse_json
from agent_artifacts.protocol.native_tree import SnapshotEntryKind, compile_native_package
from agent_artifacts.protocol.paths import parse_relative_path
from agent_artifacts.runtime_contract import EXECUTABLE_VERSION
from agent_artifacts.store.model import ObjectReadRequest, ObjectStorePaths, StoredObject

from .model import (
    CopyTreeOperation,
    EffectOutcome,
    InstallLocation,
    InstallOperation,
    InstallOutcome,
    InstallPlan,
    InstallProvenance,
    InstallRequest,
    InstallStatus,
    LinkOperation,
    MergeJsonOperation,
    PathSnapshot,
    TreeMember,
    WriteFileOperation,
    file_snapshot_digest,
    link_snapshot_digest,
    operation_is_current,
    tree_members_digest,
)

INSTALL_OBJECT_UNAVAILABLE = DiagnosticCode("install-object-unavailable")
INSTALL_OBJECT_EVIDENCE_INVALID = DiagnosticCode("install-object-evidence-invalid")
INSTALL_POLICY_DENIED = DiagnosticCode("install-policy-denied")
INSTALL_CONFLICT = DiagnosticCode("install-conflict")
INSTALL_INVALID = DiagnosticCode("install-invalid")
INSTALL_REVIEW_MISMATCH = DiagnosticCode("install-review-mismatch")

_TRUST_RANK = {
    TrustClass.UNVERIFIED.value: 0,
    TrustClass.LOCAL.value: 1,
    TrustClass.DIRECT_SOURCE.value: 2,
    TrustClass.REGISTRY_REVIEWED.value: 3,
    TrustClass.COMPANY_REVIEWED.value: 4,
}
_PLACEHOLDER = re.compile(r"\$\{([^}]+)\}")
# The sidecar a memory ``replace`` parks displaced content in, sitting beside the destination so
# the operator finds it without consulting install state (docs/design/DESIGN-memory.md §8.3).
_BACKUP_SUFFIX = ".agent-artifacts-bak"


@dataclass(frozen=True, slots=True)
class _CopyPayload:
    destination: str


@dataclass(frozen=True, slots=True)
class _WritePayload:
    destination: str
    content: bytes
    # Names the sibling write this one must be restored from when the installation is removed.
    restores_from: str | None = None


@dataclass(frozen=True, slots=True)
class _MergePayload:
    destination: str
    json_path: str
    mode: Literal["key", "list"]
    value: object
    identity: tuple[str, ...]


_NativeAction = _CopyPayload | _WritePayload | _MergePayload


def _error(code: DiagnosticCode, message: str) -> Err:
    return Err((Diagnostic(code, Severity.ERROR, message),))


class InstallReadPorts(Protocol):
    def read_object(self, request: ObjectReadRequest) -> Result[StoredObject | None]: ...

    def read_state(self, path: str) -> Result[InstallState | None]: ...

    def inspect_path(self, path: str) -> Result[PathSnapshot]: ...

    def inspect_link_target(self, path: str, boundary: str) -> Result[PathSnapshot]: ...


class InstallApplyPorts(InstallReadPorts, Protocol):
    def apply_plan(self, plan: InstallPlan) -> Result[InstallOutcome]: ...


def _json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, Mapping):
        return JsonObject(
            tuple(sorted((str(key), _json_value(item)) for key, item in value.items()))
        )
    if isinstance(value, (list, tuple)):
        return JsonArray(tuple(_json_value(item) for item in value))
    raise ValueError("install merge value is not strict JSON data")


def _to_python(value: JsonValue) -> object:
    if isinstance(value, JsonObject):
        return {key: _to_python(item) for key, item in value.entries}
    if isinstance(value, JsonArray):
        return [_to_python(item) for item in value.items]
    return value


def _strict_mapping(content: bytes, *, path: str) -> Result[dict[str, object]]:
    parsed = parse_json(content)
    if isinstance(parsed, Err) or not isinstance(parsed.value, JsonObject):
        return _error(INSTALL_INVALID, f"install JSON input is invalid: {path}")
    return Ok(cast(dict[str, object], _to_python(parsed.value)))


def _configured_source(effective: EffectiveConfiguration, alias):
    return next(
        (
            source
            for source in effective.configuration.sources
            if source.alias == alias and source.enabled
        ),
        None,
    )


def _policy_allows(
    request: InstallRequest, trust: str, effective: EffectiveConfiguration
) -> Result[None]:
    minimum = effective.policy.minimum_trust_for_user_scope
    if (
        request.scope == "user"
        and minimum is not None
        and _TRUST_RANK[trust] < _TRUST_RANK[minimum]
    ):
        return _error(
            INSTALL_POLICY_DENIED,
            f"user-scope install requires trust {minimum!r}; artifact trust is {trust!r}",
        )
    return Ok(None)


def _payload_members(stored: StoredObject) -> Result[tuple[TreeMember, ...]]:
    members: list[TreeMember] = []
    for entry in stored.candidate.entries:
        raw = str(entry.path)
        if raw == "payload" or not raw.startswith("payload/"):
            continue
        relative = raw.removeprefix("payload/")
        parsed = parse_relative_path(relative)
        if isinstance(parsed, Err):
            return _error(INSTALL_INVALID, f"object payload path is invalid: {raw}")
        if entry.kind is SnapshotEntryKind.DIRECTORY:
            members.append(TreeMember(parsed.value, "directory"))
        elif entry.kind is SnapshotEntryKind.FILE:
            members.append(TreeMember(parsed.value, "file", entry.content, entry.executable))
        else:
            return _error(INSTALL_INVALID, f"object payload entry is unsafe: {raw}")
    if not any(member.kind == "file" for member in members):
        return _error(INSTALL_INVALID, "canonical object payload contains no files")
    return Ok(tuple(sorted(members, key=lambda member: str(member.path))))


def _validate_object_evidence(stored: StoredObject, indexed) -> Result[None]:
    compiled = compile_native_package(
        stored.candidate.entries,
        expected_identity=indexed.identity,
    )
    if isinstance(compiled, Err):
        detail = compiled.diagnostics[0].message if compiled.diagnostics else "invalid package"
        return _error(
            INSTALL_OBJECT_EVIDENCE_INVALID, f"canonical object package is invalid: {detail}"
        )
    package = compiled.value
    manifest = package.manifest
    setup_matches = (manifest.setup is None) == (indexed.setup is None)
    if manifest.setup is not None and indexed.setup is not None:
        setup_matches = (
            manifest.setup.recipe == indexed.setup.recipe
            and manifest.setup.platforms == indexed.setup.platforms
        )
    provenance_matches = (package.provenance is None) == (indexed.provenance is None)
    if package.provenance is not None and indexed.provenance is not None:
        provenance_matches = (
            package.provenance.origin.url == indexed.provenance.origin_url
            and package.provenance.origin.resolved_commit == indexed.provenance.resolved_commit
            and package.provenance.origin.path == indexed.provenance.path
        )
    if (
        manifest.identity != indexed.identity
        or manifest.version != indexed.version
        or manifest.summary != indexed.summary
        or manifest.compatibility != indexed.compatibility
        or manifest.install != indexed.install
        or manifest.requires_aart != indexed.requires_aart
        or not setup_matches
        or not provenance_matches
        or package.manifest_digest != indexed.manifest_digest
        or package.payload_digest != indexed.payload_digest
    ):
        return _error(
            INSTALL_OBJECT_EVIDENCE_INVALID,
            "object bytes do not match indexed manifest/payload/install evidence",
        )
    return Ok(None)


def _payload_file(
    stored: StoredObject, suffix: str | None = None
) -> Result[tuple[str, bytes, bool]]:
    files = tuple(
        entry
        for entry in stored.candidate.entries
        if entry.kind is SnapshotEntryKind.FILE
        and str(entry.path).startswith("payload/")
        and (suffix is None or str(entry.path) == suffix)
    )
    if len(files) != 1:
        label = "the primary payload file" if suffix is None else suffix
        return _error(INSTALL_INVALID, f"canonical object must contain exactly one {label}")
    return Ok((str(files[0].path), files[0].content, files[0].executable))


def _destination(
    path: str, request: InstallRequest, location: InstallLocation
) -> Result[tuple[str, str]]:
    normalized = posixpath.normpath(path)
    if request.scope == "project":
        parsed = parse_relative_path(normalized)
        if isinstance(parsed, Err):
            return _error(INSTALL_INVALID, f"project install destination is unsafe: {path}")
        absolute = posixpath.normpath(posixpath.join(location.project_root, normalized))
        if posixpath.commonpath((location.project_root, absolute)) != location.project_root:
            return _error(INSTALL_INVALID, f"project install destination escapes root: {path}")
        return Ok((normalized, absolute))
    if not posixpath.isabs(normalized) or normalized == "/":
        return _error(INSTALL_INVALID, f"user install destination is not absolute: {path}")
    return Ok((normalized, normalized))


def _target_paths(kind: str, name: str, profile: Profile) -> Result[tuple[str, ...]]:
    if kind == "skill" and profile.skills is not None:
        target = profile.skills.dir.replace("<name>", name).rstrip("/")
        if "<name>" not in profile.skills.dir:
            target = posixpath.join(profile.skills.dir, name)
        return Ok((target,))
    if kind == "guideline" and profile.guidelines is not None:
        return Ok((posixpath.join(profile.guidelines.dest, f"{name}.md"),))
    if kind == "mcp" and profile.mcp is not None:
        return Ok((profile.mcp.file,))
    if kind == "hook" and profile.hooks is not None:
        return Ok(
            (
                profile.hooks.scripts_dir.replace("<name>", name).rstrip("/"),
                profile.hooks.merge.file,
            )
        )
    if kind == "memory" and profile.memory is not None:
        target = (
            profile.memory.dest
            if profile.memory.kind == "file"
            else posixpath.join(profile.memory.dest, f"{name}.md")
        )
        # The replace sidecar is snapshotted alongside the destination whichever mode runs: the
        # mode is resolved later, and a path the planner may write must be observed before review
        # so its precondition is part of what the operator approves.
        return Ok((target, target + _BACKUP_SUFFIX))
    return _error(
        INSTALL_INVALID,
        f"profile {profile.name!r} does not support canonical {kind} installs in this scope",
    )


def _existing_mapping(snapshot: PathSnapshot) -> Result[dict[str, object]]:
    if snapshot.kind == "absent":
        return Ok({})
    if snapshot.kind != "file":
        return _error(INSTALL_CONFLICT, f"merge destination is not a regular file: {snapshot.path}")
    return _strict_mapping(snapshot.content, path=snapshot.path)


def _render_template(template: object, values: Mapping[str, object]) -> object:
    """Render profile-owned JSON templates without importing the retired action algebra."""

    if isinstance(template, str):
        whole = _PLACEHOLDER.fullmatch(template)
        if whole:
            return values.get(whole.group(1))
        return _PLACEHOLDER.sub(lambda match: str(values.get(match.group(1), "")), template)
    if isinstance(template, Mapping):
        return {key: _render_template(value, values) for key, value in template.items()}
    if isinstance(template, (list, tuple)):
        return [_render_template(value, values) for value in template]
    return template


def _memory_block(existing: str | None, name: str, body: str, *, position: str) -> str:
    begin = f"<!-- >>> agent-artifacts memory:{name} >>> -->"
    end = f"<!-- <<< agent-artifacts memory:{name} <<< -->"
    block = f"{begin}\n{body.rstrip(chr(10))}\n{end}"
    base = existing or ""
    start = base.find(begin)
    if start != -1:
        stop = base.find(end, start)
        if stop != -1:
            tail = base[stop + len(end) :]
            if tail.startswith("\n"):
                tail = tail[1:]
            return base[:start] + block + ("\n" + tail if tail else "\n")
        return base[:start] + block + "\n"
    if not base:
        return block + "\n"
    if not base.endswith("\n"):
        base += "\n"
    return (block + "\n\n" + base) if position == "top" else (base + "\n" + block + "\n")


def _native_actions(
    request: InstallRequest,
    stored: StoredObject,
    profile: Profile,
    snapshots: Mapping[str, PathSnapshot],
) -> Result[tuple[_NativeAction, ...]]:
    """Project a compiled native package directly to canonical install operations."""

    kind = request.identity.kind
    if kind == "skill":
        assert profile.skills is not None
        target = profile.skills.dir.replace("<name>", request.identity.name).rstrip("/")
        if "<name>" not in profile.skills.dir:
            target = posixpath.join(target, request.identity.name)
        return Ok((_CopyPayload(target),))
    if kind == "guideline":
        assert profile.guidelines is not None
        primary = _payload_file(stored)
        if isinstance(primary, Err):
            return primary
        return Ok(
            (
                _WritePayload(
                    posixpath.join(profile.guidelines.dest, f"{request.identity.name}.md"),
                    primary.value[1],
                ),
            )
        )
    if kind == "mcp":
        assert profile.mcp is not None
        primary = _payload_file(stored, "payload/mcp.json")
        if isinstance(primary, Err):
            return primary
        descriptor = _strict_mapping(primary.value[1], path=primary.value[0])
        if isinstance(descriptor, Err):
            return descriptor
        destination_snapshot = snapshots[profile.mcp.file]
        existing = _existing_mapping(destination_snapshot)
        if isinstance(existing, Err):
            return existing
        name = descriptor.value.get("name", request.identity.name)
        server = descriptor.value.get("server", {})
        if not isinstance(name, str) or not name:
            return _error(INSTALL_INVALID, "MCP descriptor has no canonical server name")
        return Ok(
            (
                _MergePayload(
                    profile.mcp.file,
                    profile.mcp.json_path,
                    "key",
                    server,
                    (name,),
                ),
            )
        )
    if kind == "hook":
        assert profile.hooks is not None
        primary = _payload_file(stored, "payload/hook.json")
        if isinstance(primary, Err):
            return primary
        descriptor = _strict_mapping(primary.value[1], path=primary.value[0])
        if isinstance(descriptor, Err):
            return descriptor
        destination_snapshot = snapshots[profile.hooks.merge.file]
        existing = _existing_mapping(destination_snapshot)
        if isinstance(existing, Err):
            return existing
        values = dict(descriptor.value)
        command = values.get("command")
        scripts_dir = profile.hooks.scripts_dir.replace("<name>", request.identity.name).rstrip("/")
        if isinstance(command, str):
            values["command"] = command.replace("${SCRIPT_DIR}", scripts_dir)
        rendered = _render_template(profile.hooks.merge.entry_template or {}, values)
        if not isinstance(rendered, Mapping):
            return _error(INSTALL_INVALID, "hook profile template must render a JSON object")
        return Ok(
            (
                _CopyPayload(scripts_dir),
                _MergePayload(
                    profile.hooks.merge.file,
                    profile.hooks.merge.json_path,
                    profile.hooks.merge.mode,
                    rendered,
                    profile.hooks.merge.identity,
                ),
            )
        )
    if kind == "memory":
        assert profile.memory is not None
        primary = _payload_file(stored)
        if isinstance(primary, Err):
            return primary
        try:
            text = primary.value[1].decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return _error(INSTALL_INVALID, "memory payload is not UTF-8")
        target_path = (
            profile.memory.dest
            if profile.memory.kind == "file"
            else posixpath.join(profile.memory.dest, f"{request.identity.name}.md")
        )
        snapshot = snapshots[target_path]
        if snapshot.kind not in {"absent", "file"}:
            return _error(INSTALL_CONFLICT, "memory destination is not a regular file")
        try:
            existing_text = (
                None
                if snapshot.kind == "absent"
                else snapshot.content.decode("utf-8", errors="strict")
            )
        except UnicodeDecodeError:
            return _error(INSTALL_CONFLICT, "existing memory destination is not UTF-8")
        if profile.memory.kind == "dir":
            if request.memory_mode == "skip" and snapshot.kind != "absent":
                return _error(
                    INSTALL_INVALID, "memory install was skipped and has no managed effect"
                )
            return Ok((_WritePayload(target_path, text.encode("utf-8")),))
        if request.memory_mode == "skip":
            if snapshot.kind != "absent":
                return _error(
                    INSTALL_INVALID, "memory install was skipped and has no managed effect"
                )
            return Ok((_WritePayload(target_path, text.encode("utf-8")),))
        if request.memory_mode == "replace":
            displaced = bool((existing_text or "").strip())
            if displaced and not request.force:
                return _error(
                    INSTALL_CONFLICT,
                    f"memory {request.identity.name!r}: {target_path} exists; use force to replace",
                )
            if not displaced:
                return Ok((_WritePayload(target_path, text.encode("utf-8")),))
            # ``replace`` is the one mode that destroys content the operator wrote, and forcing it
            # says "put yours here", not "lose mine forever".  The displaced bytes go to a sidecar
            # that uninstall reads back, so the destructive mode stays reversible.
            backup_path = target_path + _BACKUP_SUFFIX
            return Ok(
                (
                    _WritePayload(backup_path, (existing_text or "").encode("utf-8")),
                    _WritePayload(target_path, text.encode("utf-8"), restores_from=backup_path),
                )
            )
        if request.memory_mode in {"prepend", "append"}:
            merged = _memory_block(
                existing_text,
                request.identity.name,
                text,
                position="top" if request.memory_mode == "prepend" else "bottom",
            )
            return Ok((_WritePayload(target_path, merged.encode("utf-8")),))
        return _error(INSTALL_INVALID, f"unknown canonical memory mode: {request.memory_mode!r}")
    return _error(INSTALL_INVALID, f"canonical {kind} install is not implemented by INS01")


def _descend(root: dict[str, object], json_path: str, *, force: bool) -> Result[dict[str, object]]:
    node = root
    for part in json_path.split(".") if json_path else ():
        child: object
        if part not in node:
            child = {}
            node[part] = child
        else:
            child = node[part]
        if not isinstance(child, dict):
            if not force:
                return _error(
                    INSTALL_CONFLICT,
                    f"JSON merge path {json_path!r} crosses non-object field {part!r}",
                )
            child = {}
            node[part] = child
        node = cast(dict[str, object], child)
    return Ok(node)


def _merged_content(
    action: _MergePayload,
    snapshot: PathSnapshot,
    identity_evidence: JsonValue,
    *,
    force: bool,
) -> Result[bytes]:
    existing = _existing_mapping(snapshot)
    if isinstance(existing, Err):
        return existing
    root = json.loads(json.dumps(existing.value))
    if action.mode == "key":
        if not action.identity:
            return _error(INSTALL_INVALID, "key merge has no identity")
        container = _descend(root, action.json_path, force=force)
        if isinstance(container, Err):
            return container
        key = action.identity[0]
        key_exists = key in container.value
        key_current = container.value.get(key)
        if key_exists and key_current != action.value and not force:
            return _error(
                INSTALL_CONFLICT,
                f"JSON merge identity {action.json_path}.{key} already differs",
            )
        container.value[key] = action.value
    else:
        if not action.json_path:
            return _error(INSTALL_INVALID, "list merge requires a JSON path")
        parts = action.json_path.split(".") if action.json_path else [""]
        parent = _descend(root, ".".join(parts[:-1]), force=force)
        if isinstance(parent, Err):
            return parent
        key_exists = parts[-1] in parent.value
        value = parent.value.get(parts[-1])
        if not key_exists:
            list_current: list[object] = []
        elif isinstance(value, list):
            list_current = list(value)
        elif not force:
            return _error(
                INSTALL_CONFLICT,
                f"JSON merge path {action.json_path!r} is not a list",
            )
        else:
            list_current = []
        matching = tuple(
            index
            for index, item in enumerate(list_current)
            if _identity_evidence(item, action.identity) == identity_evidence
        )
        if len(matching) > 1:
            return _error(
                INSTALL_CONFLICT,
                f"JSON merge identity is duplicated at {action.json_path!r}",
            )
        if matching:
            index = matching[0]
            if list_current[index] != action.value:
                if not force:
                    return _error(
                        INSTALL_CONFLICT,
                        f"JSON merge identity already differs at {action.json_path!r}",
                    )
                list_current[index] = action.value
        else:
            list_current.append(action.value)
        parent.value[parts[-1]] = list_current
    try:
        return Ok(json.dumps(root, indent=2, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError):
        return _error(INSTALL_INVALID, "merge output is not JSON serializable")


def _identity_value(node: object, field: str) -> tuple[bool, object]:
    if isinstance(node, Mapping):
        if field in node:
            return True, node[field]
        for child in node.values():
            found, value = _identity_value(child, field)
            if found:
                return True, value
    elif isinstance(node, (list, tuple)):
        for child in node:
            found, value = _identity_value(child, field)
            if found:
                return True, value
    return False, None


def _identity_evidence(value: object, identity: tuple[str, ...]) -> JsonValue | None:
    fields = []
    for field in identity:
        found, item = _identity_value(value, field)
        if not found:
            return None
        fields.append((field, _json_value(item)))
    return JsonObject(tuple(fields))


def _merge_identity_evidence(action: _MergePayload) -> Result[JsonValue]:
    if action.mode == "key":
        if not action.identity:
            return _error(INSTALL_INVALID, "key merge has no identity")
        return Ok(JsonArray(tuple(action.identity)))
    evidence = _identity_evidence(action.value, action.identity)
    if evidence is None:
        return _error(INSTALL_INVALID, "list merge value has incomplete identity evidence")
    return Ok(evidence)


def _convert_actions(
    actions: tuple[_NativeAction, ...],
    request: InstallRequest,
    stored: StoredObject,
    location: InstallLocation,
    snapshots: Mapping[str, PathSnapshot],
    ports: InstallReadPorts,
    link_boundary: str,
) -> Result[tuple[InstallOperation, ...]]:
    payload = _payload_members(stored)
    if isinstance(payload, Err):
        return payload
    primary = _payload_file(stored)
    converted: list[InstallOperation] = []
    for action in actions:
        target_path = action.destination
        destination = _destination(target_path, request, location)
        if isinstance(destination, Err):
            return destination
        logical, absolute = destination.value
        snapshot = snapshots[target_path]
        operation: InstallOperation
        if isinstance(action, _CopyPayload):
            desired = tree_members_digest(payload.value)
            if request.mode == "symlink":
                payload_root = request.mutable_local_payload_root or posixpath.join(
                    stored.root, "payload"
                )
                target_snapshot = ports.inspect_link_target(payload_root, link_boundary)
                if isinstance(target_snapshot, Err):
                    return target_snapshot
                if target_snapshot.value.kind != "tree" or target_snapshot.value.digest != desired:
                    return _error(
                        INSTALL_CONFLICT,
                        "link payload tree changed, is missing, or is not a real directory",
                    )
                operation = LinkOperation(
                    "payload",
                    logical,
                    absolute,
                    payload_root,
                    "tree",
                    (
                        "mutable-local"
                        if request.mutable_local_payload_root is not None
                        else "immutable-object"
                    ),
                    desired,
                    link_snapshot_digest(payload_root),
                    target_snapshot.value,
                    snapshot,
                    snapshot.kind != "absent"
                    and not (
                        snapshot.kind == "symlink"
                        and snapshot.link_target == payload_root
                        and snapshot.target_exists
                    ),
                )
            else:
                operation = CopyTreeOperation(
                    "payload",
                    logical,
                    absolute,
                    payload.value,
                    desired,
                    snapshot,
                    snapshot.kind != "absent" and snapshot.digest != desired,
                )
        elif isinstance(action, _WritePayload):
            source_path = "payload"
            executable = False
            if isinstance(primary, Ok):
                source_path, _source_content, executable = primary.value
            desired = file_snapshot_digest(action.content, executable)
            pure_file_link = request.mode == "symlink" and request.identity.kind == "guideline"
            if pure_file_link:
                relative = source_path.removeprefix("payload/")
                payload_root = request.mutable_local_payload_root or posixpath.join(
                    stored.root, "payload"
                )
                link_target = posixpath.join(payload_root, relative)
                target_snapshot = ports.inspect_link_target(link_target, link_boundary)
                if isinstance(target_snapshot, Err):
                    return target_snapshot
                if target_snapshot.value.kind != "file" or target_snapshot.value.digest != desired:
                    return _error(
                        INSTALL_CONFLICT,
                        "link payload file changed, is missing, or is not a regular file",
                    )
                operation = LinkOperation(
                    source_path,
                    logical,
                    absolute,
                    link_target,
                    "file",
                    (
                        "mutable-local"
                        if request.mutable_local_payload_root is not None
                        else "immutable-object"
                    ),
                    desired,
                    link_snapshot_digest(link_target),
                    target_snapshot.value,
                    snapshot,
                    snapshot.kind != "absent"
                    and not (
                        snapshot.kind == "symlink"
                        and snapshot.link_target == link_target
                        and snapshot.target_exists
                    ),
                )
            else:
                operation = WriteFileOperation(
                    source_path,
                    logical,
                    absolute,
                    action.content,
                    executable,
                    desired,
                    snapshot,
                    effect_kind=(
                        "managed-block"
                        if request.identity.kind == "memory"
                        and request.memory_mode in {"prepend", "append"}
                        else "write-file"
                    ),
                    overwrote=snapshot.kind != "absent" and snapshot.digest != desired,
                    restores_from=action.restores_from,
                )
        elif isinstance(action, _MergePayload):
            identity_evidence = _merge_identity_evidence(action)
            if isinstance(identity_evidence, Err):
                return identity_evidence
            merged = _merged_content(
                action,
                snapshot,
                identity_evidence.value,
                force=request.force,
            )
            if isinstance(merged, Err):
                return merged
            value = _json_value(action.value)
            identity = action.identity or (request.identity.name,)
            operation = MergeJsonOperation(
                logical,
                absolute,
                action.json_path,
                action.mode,
                identity,
                identity_evidence.value,
                json_digest(value),
                json_digest(identity_evidence.value),
                merged.value,
                file_snapshot_digest(merged.value),
                snapshot,
                overwrote=(
                    action.mode == "key"
                    and snapshot.kind != "absent"
                    and snapshot.digest != file_snapshot_digest(merged.value)
                ),
            )
        converted.append(operation)
    return Ok(tuple(converted))


def _operation_kind(operation: InstallOperation) -> str:
    if isinstance(operation, CopyTreeOperation):
        return "copy-tree"
    if isinstance(operation, WriteFileOperation):
        return operation.effect_kind
    if isinstance(operation, LinkOperation):
        return "symlink-tree" if operation.target_kind == "tree" else "symlink-file"
    return "merge-json"


def _previous_effect(
    state: InstallState, request: InstallRequest, coordinate: ArtifactCoordinate, destination: str
):
    for record in state.installations:
        if (
            record.coordinate.source == coordinate.source
            and record.coordinate.artifact == coordinate.artifact
            and record.profile == request.profile
            and record.scope == request.scope
        ):
            return next(
                (effect for effect in record.effects if effect.destination == destination), None
            )
    return None


def _conflicts(
    operations: tuple[InstallOperation, ...],
    state: InstallState,
    request: InstallRequest,
    coordinate: ArtifactCoordinate,
) -> tuple[str, ...]:
    if request.force:
        return ()
    conflicts: list[str] = []
    for operation in operations:
        current = operation.precondition
        if current.kind == "absent" or operation_is_current(operation):
            continue
        if isinstance(operation, MergeJsonOperation):
            continue
        previous = _previous_effect(state, request, coordinate, operation.destination)
        previous_owns = previous is not None and (
            (
                previous.actual_mode == "symlink"
                and current.kind == "symlink"
                and current.link_target == previous.link_target
            )
            or (
                previous.actual_mode == "copy"
                and current.kind in {"file", "tree"}
                and previous.installed_digest == current.digest
            )
        )
        if not previous_owns:
            conflicts.append(operation.destination)
    return tuple(conflicts)


def _proof(operation: InstallOperation) -> EffectProof:
    created = operation.precondition.kind == "absent"
    if isinstance(operation, CopyTreeOperation):
        return EffectProof(
            "copy-tree",
            operation.destination,
            "copy",
            operation.desired_digest,
            source_path=operation.source_path,
            created_destination=created,
            overwrote=operation.overwrote,
        )
    if isinstance(operation, WriteFileOperation):
        return EffectProof(
            operation.effect_kind,
            operation.destination,
            "copy",
            operation.desired_digest,
            source_path=(operation.source_path if operation.effect_kind == "write-file" else None),
            created_destination=created,
            overwrote=operation.overwrote,
            restores_from=operation.restores_from,
        )
    if isinstance(operation, LinkOperation):
        return EffectProof(
            "symlink-tree" if operation.target_kind == "tree" else "symlink-file",
            operation.destination,
            "symlink",
            operation.target_content_digest,
            source_path=operation.source_path,
            link_target=operation.target,
            link_semantics=operation.semantics,
            created_destination=created,
            overwrote=operation.overwrote,
        )
    return EffectProof(
        "merge-json",
        operation.destination,
        "copy",
        operation.value_digest,
        json_path=operation.json_path,
        merge_mode=operation.merge_mode,
        identity_digest=operation.identity_digest,
        identity_evidence=operation.identity_evidence,
        created_destination=created,
        overwrote=operation.overwrote,
    )


def _replacement_state(
    current: InstallState,
    request: InstallRequest,
    coordinate: ArtifactCoordinate,
    source: SourceEvidence,
    artifact: ArtifactEvidence,
    operations: tuple[InstallOperation, ...],
) -> Result[InstallState]:
    prior = next(
        (
            item
            for item in current.installations
            if item.coordinate.source == coordinate.source
            and item.coordinate.artifact == coordinate.artifact
            and item.profile == request.profile
            and item.scope == request.scope
        ),
        None,
    )
    prior_effects = {} if prior is None else {effect.locator: effect for effect in prior.effects}
    effects = []
    for operation in operations:
        proof = _proof(operation)
        previous = prior_effects.get(proof.locator)
        if previous is not None and previous.kind == proof.kind:
            proof = replace(
                proof,
                created_destination=previous.created_destination,
                overwrote=previous.overwrote or proof.overwrote,
            )
        effects.append(proof)
    try:
        record = InstallationRecord(
            ArtifactCoordinate(coordinate.source, coordinate.artifact),
            source,
            artifact,
            request.profile,
            request.profile_version,
            request.scope,
            request.mode,
            tuple(effects),
            memory_mode=(request.memory_mode if request.identity.kind == "memory" else None),
        )
        retained = tuple(item for item in current.installations if item.key != record.key)
        return Ok(InstallState(2, (*retained, record)))
    except ValueError as error:
        return _error(INSTALL_CONFLICT, f"installation state ownership conflict: {error}")


def prepare_install(
    request: InstallRequest,
    catalog,
    effective: EffectiveConfiguration,
    profile: Profile,
    location: InstallLocation,
    store_paths: ObjectStorePaths,
    ports: InstallReadPorts,
) -> Result[InstallPlan]:
    """Resolve and prepare one immutable plan without applying any effect."""

    resolved = resolve_artifact(
        catalog,
        ArtifactQuery(request.identity, request.source, request.version),
        offline=request.offline,
    )
    if isinstance(resolved, Err):
        return resolved
    item = resolved.value
    source_config = _configured_source(effective, item.source.alias)
    if (
        source_config is None
        or item.source.source_id is None
        or item.source.resolved_revision is None
        or item.source.snapshot_digest is None
        or item.source.age_seconds is None
    ):
        return _error(
            INSTALL_INVALID, "resolved marketplace source is no longer configured/current"
        )
    if request.mutable_local_payload_root is not None:
        try:
            within_source = (
                source_config.kind is SourceKind.SOURCE_LOCAL
                and posixpath.commonpath(
                    (source_config.location, request.mutable_local_payload_root)
                )
                == source_config.location
            )
        except ValueError:
            within_source = False
        if not within_source:
            return _error(
                INSTALL_POLICY_DENIED,
                "mutable-local links require an explicit payload root inside the selected local source",
            )
    allowed = _policy_allows(request, item.trust.kind.value, effective)
    if isinstance(allowed, Err):
        return allowed
    target = CompatibilityTarget(
        request.profile,
        request.platform,
        request.scope,
        request.mode,
        ("copy-tree", "managed-block", "merge-json", "write-file"),
        EXECUTABLE_VERSION,
        require_setup=False,
    )
    compatibility = evaluate_compatibility(item.artifact, target)
    if not compatibility.compatible:
        return _error(
            DiagnosticCode("artifact-incompatible"),
            "; ".join(reason.message for reason in compatibility.reasons),
        )
    loaded = ports.read_object(ObjectReadRequest(store_paths, item.artifact.artifact.object_digest))
    if isinstance(loaded, Err):
        return loaded
    if loaded.value is None:
        suffix = " while offline" if request.offline else ""
        return _error(
            INSTALL_OBJECT_UNAVAILABLE,
            f"verified cached object is unavailable{suffix}: {item.coordinate}",
        )
    stored = loaded.value
    if stored.candidate.digest != item.artifact.artifact.object_digest:
        return _error(INSTALL_INVALID, "loaded object does not match marketplace evidence")
    object_evidence = _validate_object_evidence(stored, item.artifact.artifact)
    if isinstance(object_evidence, Err):
        return object_evidence
    scoped_profile = profile_for_scope(profile, request.scope, location.user_home)
    target_paths = _target_paths(request.identity.kind, request.identity.name, scoped_profile)
    if isinstance(target_paths, Err):
        return target_paths
    snapshots: dict[str, PathSnapshot] = {}
    for target_path in target_paths.value:
        destination = _destination(target_path, request, location)
        if isinstance(destination, Err):
            return destination
        observed = ports.inspect_path(destination.value[1])
        if isinstance(observed, Err):
            return observed
        if observed.value.kind == "special" or (
            observed.value.kind == "symlink" and request.mode == "copy"
        ):
            return _error(
                INSTALL_CONFLICT,
                f"install destination has an unsafe existing type: {destination.value[1]}",
            )
        snapshots[target_path] = observed.value
    actions = _native_actions(request, stored, scoped_profile, snapshots)
    if isinstance(actions, Err):
        return actions
    converted = _convert_actions(
        actions.value,
        request,
        stored,
        location,
        snapshots,
        ports,
        source_config.location if request.mutable_local_payload_root is not None else stored.root,
    )
    if isinstance(converted, Err):
        return converted
    state_paths = install_state_paths(
        request.scope,
        project_root=location.project_root,
        user_home=location.user_home,
        data_root=location.data_root,
    )
    state_read = ports.read_state(state_paths.destination_path)
    if isinstance(state_read, Err):
        return state_read
    current_state = InstallState(2, ()) if state_read.value is None else state_read.value
    state_snapshot = ports.inspect_path(state_paths.destination_path)
    if isinstance(state_snapshot, Err):
        return state_snapshot
    if state_snapshot.value.kind == "absent":
        if state_read.value is not None:
            return _error(INSTALL_CONFLICT, "installation state changed while preparing the plan")
    elif state_snapshot.value.kind == "file":
        parsed_snapshot = parse_install_state(
            state_snapshot.value.content,
            path=state_paths.destination_path,
        )
        if isinstance(parsed_snapshot, Err):
            return parsed_snapshot
        if state_read.value != parsed_snapshot.value:
            return _error(INSTALL_CONFLICT, "installation state changed while preparing the plan")
    else:
        return _error(INSTALL_CONFLICT, "installation state path is not a regular file")
    conflicts = _conflicts(converted.value, current_state, request, item.coordinate)
    if conflicts:
        return _error(
            INSTALL_CONFLICT,
            "install destinations contain unowned or drifted content; use force: "
            + ", ".join(conflicts),
        )
    indexed = item.artifact.artifact
    try:
        source = SourceEvidence(
            item.source.alias,
            item.source.source_id,
            item.source.kind,
            item.source.origin,
            item.source.resolved_revision,
            source_config.ref,
        )
        artifact = ArtifactEvidence(
            indexed.identity,
            indexed.version,
            indexed.manifest_digest,
            indexed.payload_digest,
            indexed.object_digest,
        )
    except ValueError as error:
        return _error(INSTALL_INVALID, f"install evidence is invalid: {error}")
    replacement_state = _replacement_state(
        current_state,
        request,
        item.coordinate,
        source,
        artifact,
        converted.value,
    )
    if isinstance(replacement_state, Err):
        return replacement_state
    replacement_digest = sha256_bytes(install_state_bytes(replacement_state.value))
    policy_digest = sha256_bytes(organization_policy_bytes(effective.policy))
    reference_owner = (
        f"{request.scope}/{item.source.alias.value}/{request.identity.kind}/"
        f"{request.identity.name}/{request.profile}"
    )
    provenance = None
    if indexed.provenance is not None:
        origin = git_location_parts(indexed.provenance.origin_url)
        if origin is None:
            return _error(INSTALL_INVALID, "artifact provenance origin is not credential-free Git")
        try:
            provenance = InstallProvenance(
                f"{origin[0]}/{origin[1]}",
                indexed.provenance.resolved_commit,
                indexed.provenance.path,
            )
        except ValueError as error:
            return _error(INSTALL_INVALID, f"artifact provenance is invalid: {error}")
    placeholder = sha256_bytes(b"unreviewed-install-plan")
    try:
        plan = InstallPlan(
            request=request,
            coordinate=item.coordinate,
            source=source,
            source_health=item.source.health.value,
            source_age_seconds=item.source.age_seconds,
            source_snapshot_digest=item.source.snapshot_digest,
            artifact=artifact,
            trust=item.trust.kind.value,
            trust_evidence_digest=item.trust.evidence_digest,
            policy_digest=policy_digest,
            object_store_paths=store_paths,
            object_candidate=stored.candidate,
            object_root=stored.root,
            object_digest=stored.candidate.digest,
            provenance=provenance,
            operations=converted.value,
            state_path=state_paths.destination_path,
            state_lock_path=state_paths.lock_path,
            state_precondition=state_snapshot.value,
            replacement_state=replacement_state.value,
            replacement_state_digest=replacement_digest,
            reference_owner=reference_owner,
            review_digest=placeholder,
        )
    except ValueError as error:
        return _error(INSTALL_INVALID, f"canonical install plan is invalid: {error}")
    return Ok(plan)


def _conflicted_outcome(plan: InstallPlan, detail: str) -> InstallOutcome:
    return InstallOutcome(
        plan.review_digest,
        InstallStatus.CONFLICTED,
        tuple(
            EffectOutcome(_operation_kind(item), item.destination, "skipped", detail)
            for item in plan.operations
        ),
        False,
    )


def _marketplace_precondition_is_current(
    plan: InstallPlan,
    catalog,
    effective: EffectiveConfiguration,
) -> bool:
    if sha256_bytes(organization_policy_bytes(effective.policy)) != plan.policy_digest:
        return False
    resolved = resolve_artifact(
        catalog,
        ArtifactQuery(
            plan.coordinate.artifact,
            plan.coordinate.source,
            plan.coordinate.version,
        ),
    )
    if not isinstance(resolved, Ok):
        return False
    item = resolved.value
    source_config = _configured_source(effective, item.source.alias)
    if (
        source_config is None
        or item.source.source_id is None
        or item.source.resolved_revision is None
        or item.source.snapshot_digest is None
        # Not equality: healthy and stale differ only by how long ago the pinned snapshot was
        # published, and the plan pins that snapshot by digest, so ageing across the freshness
        # threshold between review and finalize changes nothing the operator reviewed. Acquiring
        # diagnostics does, so a source that degraded since the review still invalidates the plan.
        or (item.source.health.value == "degraded" and plan.source_health != "degraded")
        or item.source.snapshot_digest != plan.source_snapshot_digest
        or item.trust.kind.value != plan.trust
        or item.trust.evidence_digest != plan.trust_evidence_digest
    ):
        return False
    try:
        source = SourceEvidence(
            item.source.alias,
            item.source.source_id,
            item.source.kind,
            item.source.origin,
            item.source.resolved_revision,
            source_config.ref,
        )
        indexed = item.artifact.artifact
        artifact = ArtifactEvidence(
            indexed.identity,
            indexed.version,
            indexed.manifest_digest,
            indexed.payload_digest,
            indexed.object_digest,
        )
    except ValueError:
        return False
    if source != plan.source or artifact != plan.artifact or item.coordinate != plan.coordinate:
        return False
    if indexed.provenance is None:
        return plan.provenance is None
    origin = git_location_parts(indexed.provenance.origin_url)
    if origin is None:
        return False
    try:
        provenance = InstallProvenance(
            f"{origin[0]}/{origin[1]}",
            indexed.provenance.resolved_commit,
            indexed.provenance.path,
        )
    except ValueError:
        return False
    return provenance == plan.provenance


def finalize_install(
    plan: InstallPlan,
    reviewed_digest,
    catalog,
    effective: EffectiveConfiguration,
    ports: InstallApplyPorts,
) -> Result[InstallOutcome]:
    """Apply only the exact reviewed object, destination snapshots, and state precondition."""

    if reviewed_digest != plan.review_digest:
        return _error(INSTALL_REVIEW_MISMATCH, "finalize digest does not match the reviewed plan")
    if not _marketplace_precondition_is_current(plan, catalog, effective):
        return Ok(
            _conflicted_outcome(
                plan,
                "marketplace source, trust, artifact, or organization policy changed after review",
            )
        )
    loaded = ports.read_object(ObjectReadRequest(plan.object_store_paths, plan.object_digest))
    if isinstance(loaded, Err):
        return loaded
    if (
        loaded.value is None
        or loaded.value.candidate != plan.object_candidate
        or loaded.value.root != plan.object_root
    ):
        return Ok(_conflicted_outcome(plan, "reviewed immutable object changed or disappeared"))
    for operation in plan.operations:
        if isinstance(operation, LinkOperation):
            boundary = (
                plan.source.origin if operation.semantics == "mutable-local" else plan.object_root
            )
            assert boundary is not None
            target = ports.inspect_link_target(operation.target, boundary)
            if isinstance(target, Err):
                return target
            if target.value != operation.target_precondition:
                return Ok(_conflicted_outcome(plan, "link target changed after review"))
        current = ports.inspect_path(operation.absolute_destination)
        if isinstance(current, Err):
            return current
        if current.value != operation.precondition:
            return Ok(_conflicted_outcome(plan, "destination changed after review"))
    state = ports.inspect_path(plan.state_path)
    if isinstance(state, Err):
        return state
    if state.value != plan.state_precondition:
        return Ok(_conflicted_outcome(plan, "installation state changed after review"))
    return ports.apply_plan(plan)
