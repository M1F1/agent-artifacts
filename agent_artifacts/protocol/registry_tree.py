"""Pure registry input hashing and committed-lock consumer resolution."""

from __future__ import annotations

from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity, SourceLocation
from agent_artifacts.domain.identifiers import ArtifactIdentity, ObjectDigest
from agent_artifacts.domain.result import Err, Ok, Result

from .codes import (
    REGISTRY_LOCK_INVALID,
    REGISTRY_LOCK_STALE,
    REGISTRY_SELF_REFERENCE,
    REGISTRY_TREE_INVALID,
)
from .hashing import directory_entry, file_entry, tree_digest
from .json import canonical_json_bytes, parse_json
from .native_tree import SnapshotEntry, SnapshotEntryKind, SnapshotOrigin, SourceSnapshot
from .paths import parse_relative_path
from .registry_models import (
    RegistryEntry,
    RegistryLock,
    ResolvedRegistryReference,
)

_GENERATED_PATHS = frozenset({"aart.lock.json", "aart.index.json"})
_INPUT_MARKERS = frozenset({"aart-registry.json", "aart-source.json"})
_INPUT_ROOTS = ("entries/", "artifacts/", "collections/")


def _error(code: DiagnosticCode, message: str, *, path: str | None = None) -> Err:
    return Err(
        (
            Diagnostic(
                code,
                Severity.ERROR,
                message,
                None if path is None else SourceLocation(path=path),
            ),
        )
    )


def _is_registry_input(path: str) -> bool:
    return path in _INPUT_MARKERS or any(path.startswith(root) for root in _INPUT_ROOTS)


def _validated_input_files(snapshot: SourceSnapshot) -> Result[tuple[SnapshotEntry, ...]]:
    if not isinstance(snapshot.origin, SnapshotOrigin):
        return _error(REGISTRY_TREE_INVALID, "snapshot origin is invalid")
    seen: set[str] = set()
    files: list[SnapshotEntry] = []
    marker_found = False
    for entry in snapshot.entries:
        path = str(entry.path)
        parsed_path = parse_relative_path(path)
        if not isinstance(parsed_path, Ok) or parsed_path.value != entry.path:
            return _error(REGISTRY_TREE_INVALID, f"snapshot path is not canonical: {path!r}")
        if path in seen:
            return _error(REGISTRY_TREE_INVALID, f"duplicate snapshot path: {path}", path=path)
        seen.add(path)
        if not isinstance(entry.kind, SnapshotEntryKind):
            return _error(REGISTRY_TREE_INVALID, f"invalid entry kind: {path}", path=path)
        if not isinstance(entry.content, bytes) or not isinstance(entry.executable, bool):
            return _error(REGISTRY_TREE_INVALID, f"invalid entry metadata: {path}", path=path)
        if path == "aart-registry.json" and entry.kind is SnapshotEntryKind.FILE:
            marker_found = True
        if path in _GENERATED_PATHS or not _is_registry_input(path):
            continue
        if entry.kind in {SnapshotEntryKind.SYMLINK, SnapshotEntryKind.SPECIAL}:
            return _error(
                REGISTRY_TREE_INVALID,
                f"registry inputs forbid {entry.kind.value} entries: {path}",
                path=path,
            )
        if entry.kind is SnapshotEntryKind.FILE:
            files.append(entry)
    if not marker_found:
        return _error(REGISTRY_TREE_INVALID, "registry inputs require root aart-registry.json")
    return Ok(tuple(sorted(files, key=lambda entry: str(entry.path))))


def registry_inputs_digest(snapshot: SourceSnapshot) -> Result[ObjectDigest]:
    """Hash declared registry inputs, excluding generated lock/index and unrelated repo files."""

    validated = _validated_input_files(snapshot)
    if isinstance(validated, Err):
        return validated
    tree_entries = []
    directories: set[str] = set()
    for entry in validated.value:
        path = str(entry.path)
        content = entry.content
        if path.endswith(".json"):
            parsed_json = parse_json(content, location=SourceLocation(path=path))
            if isinstance(parsed_json, Err):
                return _error(
                    REGISTRY_TREE_INVALID, f"registry JSON input is invalid: {path}", path=path
                )
            content = canonical_json_bytes(parsed_json.value)
        tree_entries.append(file_entry(entry.path, content, executable=entry.executable))
        for length in range(1, len(entry.path.parts)):
            directories.add("/".join(entry.path.parts[:length]))
    for raw_directory in sorted(directories):
        parsed_directory = parse_relative_path(raw_directory)
        if isinstance(parsed_directory, Err):
            return _error(
                REGISTRY_TREE_INVALID,
                f"registry input directory is invalid: {raw_directory}",
            )
        tree_entries.append(directory_entry(parsed_directory.value))
    digest = tree_digest(tree_entries)
    if isinstance(digest, Err):
        return _error(REGISTRY_TREE_INVALID, "registry inputs cannot be hashed")
    return digest


def _normalized_origin(url: str) -> str:
    normalized = url.rstrip("/").removesuffix(".git")
    if normalized.startswith("https://"):
        remainder = normalized.removeprefix("https://")
        authority, separator, path = remainder.partition("/")
        return f"https://{authority.casefold()}{separator}{path}"
    if normalized.startswith("git@"):
        authority, separator, path = normalized.partition(":")
        return f"{authority.casefold()}{separator}{path}"
    return normalized


def resolve_locked_references(
    entries: tuple[RegistryEntry, ...],
    lock: RegistryLock,
    *,
    expected_inputs_digest: ObjectDigest,
    registry_origin_url: str | None = None,
) -> Result[tuple[ResolvedRegistryReference, ...]]:
    """Resolve references only from a matching committed lock; never dereference a moving ref."""

    if lock.registry_inputs_digest != expected_inputs_digest:
        return _error(
            REGISTRY_LOCK_STALE,
            "registry lock does not match deterministic registry inputs",
        )
    entry_map: dict[ArtifactIdentity, RegistryEntry] = {}
    for entry in entries:
        if entry.identity in entry_map:
            return _error(
                REGISTRY_LOCK_INVALID,
                f"duplicate registry entry: {entry.identity}",
            )
        entry_map[entry.identity] = entry
    locked_map = dict(lock.entries)
    resolved: list[ResolvedRegistryReference] = []
    registry_origin = (
        None if registry_origin_url is None else _normalized_origin(registry_origin_url)
    )
    for identity in sorted(entry_map):
        entry = entry_map[identity]
        locked = locked_map.get(identity)
        if locked is None:
            return _error(REGISTRY_LOCK_STALE, f"registry lock is missing {identity}")
        if registry_origin is not None and _normalized_origin(entry.source.url) == registry_origin:
            return _error(
                REGISTRY_SELF_REFERENCE,
                f"registry entry {identity} references its own registry origin",
            )
        if (
            entry.source.url != locked.origin_url
            or entry.source.ref != locked.requested_ref
            or entry.source.path != locked.path
            or entry.review != locked.review
        ):
            return _error(
                REGISTRY_LOCK_STALE,
                f"registry entry and lock disagree for {identity}",
            )
        if entry.review.status != "approved":
            return _error(
                REGISTRY_LOCK_INVALID,
                f"registry entry {identity} is not approved",
            )
        resolved.append(
            ResolvedRegistryReference(
                identity,
                locked.origin_url,
                locked.requested_ref,
                locked.resolved_commit,
                locked.path,
                locked.manifest_digest,
                locked.payload_digest,
                locked.object_digest,
                locked.artifact_version,
                locked.review,
                locked.provenance_digest,
            )
        )
    return Ok(tuple(resolved))
