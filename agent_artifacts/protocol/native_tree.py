"""Pure native-source loader over already acquired local or immutable Git trees."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity, SourceLocation
from agent_artifacts.domain.identifiers import ArtifactIdentity, ObjectDigest
from agent_artifacts.domain.result import Err, Ok, Result

from .capabilities import Capability, negotiate_capabilities
from .codes import (
    ARTIFACT_INVALID,
    COLLECTION_INVALID,
    SOURCE_INCOMPATIBLE,
    SOURCE_MARKER_MISSING,
    SOURCE_TREE_INVALID,
)
from .hashing import directory_entry, file_entry, json_digest, tree_digest
from .json import JsonObject, parse_json
from .native_models import ArtifactManifest, CollectionManifest, Provenance, SourceManifest
from .native_schema import (
    artifact_manifest_to_json,
    parse_artifact_manifest,
    parse_collection_manifest,
    parse_provenance,
    parse_source_manifest,
    source_manifest_to_json,
)
from .paths import SafeRelativePath, parse_relative_path
from .semver import SemVer


class SnapshotOrigin(str, Enum):
    LOCAL = "local"
    IMMUTABLE_GIT = "immutable-git"


class SnapshotEntryKind(str, Enum):
    FILE = "file"
    DIRECTORY = "directory"
    SYMLINK = "symlink"
    SPECIAL = "special"


@dataclass(frozen=True, slots=True)
class SnapshotEntry:
    path: SafeRelativePath
    kind: SnapshotEntryKind
    content: bytes = b""
    executable: bool = False


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    origin: SnapshotOrigin
    entries: tuple[SnapshotEntry, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "entries",
            tuple(sorted(self.entries, key=lambda entry: str(entry.path))),
        )


@dataclass(frozen=True, slots=True)
class NativeArtifactPackage:
    manifest: ArtifactManifest
    provenance: Provenance | None
    manifest_digest: ObjectDigest
    payload_digest: ObjectDigest


@dataclass(frozen=True, slots=True)
class NativeSource:
    manifest: SourceManifest
    artifacts: tuple[NativeArtifactPackage, ...]
    collections: tuple[CollectionManifest, ...]
    manifest_digest: ObjectDigest


def _diagnostic(code: DiagnosticCode, message: str, path: str | None = None) -> Diagnostic:
    return Diagnostic(code, Severity.ERROR, message, SourceLocation(path=path))


def _error(code: DiagnosticCode, message: str, path: str | None = None) -> Err:
    return Err((_diagnostic(code, message, path),))


def _validated_entries(snapshot: SourceSnapshot) -> Result[dict[str, SnapshotEntry]]:
    if not isinstance(snapshot.origin, SnapshotOrigin):
        return _error(SOURCE_TREE_INVALID, "snapshot origin is invalid")
    entries: dict[str, SnapshotEntry] = {}
    for entry in snapshot.entries:
        raw_path = str(entry.path)
        canonical = parse_relative_path(raw_path)
        if not isinstance(canonical, Ok) or canonical.value != entry.path:
            return _error(SOURCE_TREE_INVALID, f"snapshot path is not canonical: {raw_path!r}")
        if raw_path in entries:
            return _error(SOURCE_TREE_INVALID, f"duplicate snapshot path: {raw_path}", raw_path)
        if not isinstance(entry.kind, SnapshotEntryKind):
            return _error(SOURCE_TREE_INVALID, f"invalid snapshot entry kind: {raw_path}", raw_path)
        if not isinstance(entry.content, bytes) or not isinstance(entry.executable, bool):
            return _error(SOURCE_TREE_INVALID, f"invalid snapshot metadata: {raw_path}", raw_path)
        if entry.kind is SnapshotEntryKind.DIRECTORY and (entry.content or entry.executable):
            return _error(SOURCE_TREE_INVALID, f"directory has file metadata: {raw_path}", raw_path)
        entries[raw_path] = entry
    return Ok(entries)


def _validate_protocol_entry_kinds(
    entries: dict[str, SnapshotEntry],
    manifest: SourceManifest,
) -> Result[None]:
    roots = (*manifest.artifact_roots, *manifest.collection_roots)
    for path, entry in entries.items():
        relevant = path == "aart-source.json" or any(
            _under(path, root) is not None for root in roots
        )
        if relevant and entry.kind in {SnapshotEntryKind.SYMLINK, SnapshotEntryKind.SPECIAL}:
            return _error(
                SOURCE_TREE_INVALID,
                f"protocol v1 forbids {entry.kind.value} entries in declared content: {path}",
                path,
            )
    return Ok(None)


def _file(
    entries: dict[str, SnapshotEntry],
    path: str,
    code: DiagnosticCode = ARTIFACT_INVALID,
) -> Result[SnapshotEntry]:
    entry = entries.get(path)
    if entry is None or entry.kind is not SnapshotEntryKind.FILE:
        return _error(code, f"required file is missing: {path}", path)
    return Ok(entry)


def _under(path: str, root: SafeRelativePath) -> tuple[str, ...] | None:
    root_parts = root.parts
    parsed = path.split("/")
    if tuple(parsed[: len(root_parts)]) != root_parts:
        return None
    return tuple(parsed[len(root_parts) :])


def _package_candidates(
    entries: dict[str, SnapshotEntry],
    manifest: SourceManifest,
) -> Result[tuple[tuple[SafeRelativePath, str, str], ...]]:
    candidates: set[tuple[SafeRelativePath, str, str]] = set()
    for root in manifest.artifact_roots:
        for path, entry in entries.items():
            relative = _under(path, root)
            if relative is None or not relative:
                continue
            if len(relative) < 2:
                if entry.kind is SnapshotEntryKind.DIRECTORY:
                    continue
                return _error(
                    SOURCE_TREE_INVALID,
                    f"artifact root entries must use <type>/<name>/...: {path}",
                    path,
                )
            artifact_type, name = relative[:2]
            if artifact_type not in {"skill", "guideline", "mcp", "hook", "memory"}:
                return _error(
                    SOURCE_TREE_INVALID,
                    f"unsupported artifact type directory {artifact_type!r}",
                    path,
                )
            candidates.add((root, artifact_type, name))
    if not candidates:
        return _error(SOURCE_TREE_INVALID, "native source contains no canonical artifact packages")
    return Ok(tuple(sorted(candidates, key=lambda item: (str(item[0]), item[1], item[2]))))


def _relative_package_entries(
    entries: dict[str, SnapshotEntry],
    base: str,
) -> dict[str, SnapshotEntry]:
    prefix = f"{base}/"
    return {
        path.removeprefix(prefix): entry
        for path, entry in entries.items()
        if path.startswith(prefix)
    }


def _validate_primary_payload(
    manifest: ArtifactManifest,
    package_entries: dict[str, SnapshotEntry],
    *,
    manifest_path: str,
) -> Result[None]:
    files = {
        path: entry
        for path, entry in package_entries.items()
        if path.startswith("payload/") and entry.kind is SnapshotEntryKind.FILE
    }
    if not files:
        return _error(ARTIFACT_INVALID, "payload contains no files", manifest_path)
    artifact_type = manifest.identity.kind
    text_files: tuple[SnapshotEntry, ...]
    if artifact_type == "skill":
        required = files.get("payload/SKILL.md")
        if required is None:
            return _error(
                ARTIFACT_INVALID, "skill payload requires payload/SKILL.md", manifest_path
            )
        text_files = (required,)
    elif artifact_type in {"guideline", "memory"}:
        markdown = tuple(entry for path, entry in files.items() if path.endswith(".md"))
        if len(files) != 1 or len(markdown) != 1:
            return _error(
                ARTIFACT_INVALID,
                f"{artifact_type} payload requires exactly one Markdown document",
                manifest_path,
            )
        text_files = markdown
    elif artifact_type in {"mcp", "hook"}:
        primary_path = "payload/mcp.json" if artifact_type == "mcp" else "payload/hook.json"
        primary = files.get(primary_path)
        if primary is None:
            return _error(
                ARTIFACT_INVALID, f"{artifact_type} payload requires {primary_path}", manifest_path
            )
        parsed = parse_json(primary.content, location=SourceLocation(path=primary_path))
        if isinstance(parsed, Err) or not isinstance(parsed.value, JsonObject):
            return _error(
                ARTIFACT_INVALID, f"{primary_path} must be a strict JSON object", primary_path
            )
        text_files = ()
    else:
        return _error(
            ARTIFACT_INVALID, f"unsupported artifact type {artifact_type!r}", manifest_path
        )
    for entry in text_files:
        try:
            entry.content.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return _error(ARTIFACT_INVALID, "text payload must be valid UTF-8", manifest_path)
    return Ok(None)


def _payload_digest(
    package_entries: dict[str, SnapshotEntry],
    *,
    manifest_path: str,
) -> Result[ObjectDigest]:
    payload_files = tuple(
        (path.removeprefix("payload/"), entry)
        for path, entry in package_entries.items()
        if path.startswith("payload/") and entry.kind is SnapshotEntryKind.FILE
    )
    tree_entries = []
    directories: set[str] = set()
    for relative, entry in payload_files:
        parsed_path = parse_relative_path(relative)
        if isinstance(parsed_path, Err):
            return _error(ARTIFACT_INVALID, f"invalid payload path: {relative}", manifest_path)
        tree_entries.append(
            file_entry(parsed_path.value, entry.content, executable=entry.executable)
        )
        parts = parsed_path.value.parts
        for length in range(1, len(parts)):
            directories.add("/".join(parts[:length]))
    for directory in sorted(directories):
        parsed_directory = parse_relative_path(directory)
        if isinstance(parsed_directory, Err):
            return _error(
                ARTIFACT_INVALID, f"invalid payload directory: {directory}", manifest_path
            )
        tree_entries.append(directory_entry(parsed_directory.value))
    digest = tree_digest(tree_entries)
    if isinstance(digest, Err):
        return _error(ARTIFACT_INVALID, "payload tree cannot be hashed", manifest_path)
    return digest


def _load_package(
    entries: dict[str, SnapshotEntry],
    root: SafeRelativePath,
    expected_type: str,
    expected_name: str,
) -> Result[NativeArtifactPackage]:
    base = f"{root}/{expected_type}/{expected_name}"
    manifest_path = f"{base}/artifact.json"
    manifest_file = _file(entries, manifest_path)
    if isinstance(manifest_file, Err):
        return manifest_file
    parsed_manifest = parse_artifact_manifest(manifest_file.value.content, path=manifest_path)
    if isinstance(parsed_manifest, Err):
        return parsed_manifest
    manifest = parsed_manifest.value
    expected_identity = f"{expected_type}/{expected_name}"
    if str(manifest.identity) != expected_identity:
        return _error(
            ARTIFACT_INVALID,
            f"manifest identity {manifest.identity} does not match package path {expected_identity}",
            manifest_path,
        )
    package_entries = _relative_package_entries(entries, base)
    allowed_roots = {"artifact.json", "README.md", "provenance.json", "payload", "setup"}
    for relative_path in package_entries:
        if relative_path.split("/", 1)[0] not in allowed_roots:
            return _error(
                ARTIFACT_INVALID,
                f"unexpected canonical package path: {relative_path}",
                f"{base}/{relative_path}",
            )
    primary = _validate_primary_payload(manifest, package_entries, manifest_path=manifest_path)
    if isinstance(primary, Err):
        return primary
    if manifest.setup is not None:
        recipe_path = f"{base}/{manifest.setup.recipe}"
        recipe = _file(entries, recipe_path)
        if isinstance(recipe, Err):
            return recipe
    elif any(path.startswith("setup/") for path in package_entries):
        return _error(
            ARTIFACT_INVALID, "setup content requires a declared setup reference", manifest_path
        )
    provenance: Provenance | None = None
    provenance_entry = package_entries.get("provenance.json")
    if provenance_entry is not None:
        if provenance_entry.kind is not SnapshotEntryKind.FILE:
            return _error(ARTIFACT_INVALID, "provenance.json must be a file", manifest_path)
        parsed_provenance = parse_provenance(
            provenance_entry.content,
            path=f"{base}/provenance.json",
        )
        if isinstance(parsed_provenance, Err):
            return parsed_provenance
        provenance = parsed_provenance.value
    digest = _payload_digest(package_entries, manifest_path=manifest_path)
    if isinstance(digest, Err):
        return digest
    return Ok(
        NativeArtifactPackage(
            manifest,
            provenance,
            json_digest(artifact_manifest_to_json(manifest)),
            digest.value,
        )
    )


def _load_collections(
    entries: dict[str, SnapshotEntry],
    manifest: SourceManifest,
) -> Result[tuple[CollectionManifest, ...]]:
    collections: list[CollectionManifest] = []
    names: set[str] = set()
    for root in manifest.collection_roots:
        for path, entry in entries.items():
            relative = _under(path, root)
            if relative is None or not relative:
                continue
            if entry.kind is SnapshotEntryKind.DIRECTORY:
                continue
            if len(relative) != 1 or not relative[0].endswith(".json"):
                return _error(
                    COLLECTION_INVALID,
                    f"collection files must be direct JSON children of {root}: {path}",
                    path,
                )
            parsed = parse_collection_manifest(entry.content, path=path)
            if isinstance(parsed, Err):
                return parsed
            expected_name = relative[0].removesuffix(".json")
            if parsed.value.name != expected_name:
                return _error(
                    COLLECTION_INVALID,
                    f"collection name {parsed.value.name!r} does not match {expected_name!r}",
                    path,
                )
            if parsed.value.name in names:
                return _error(
                    COLLECTION_INVALID,
                    f"duplicate collection identity: {parsed.value.name}",
                    path,
                )
            names.add(parsed.value.name)
            collections.append(parsed.value)
    return Ok(tuple(sorted(collections, key=lambda item: item.name)))


def _compatibility_diagnostics(
    manifest: SourceManifest,
    executable_version: SemVer,
    available_capabilities: Iterable[Capability],
) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    if not manifest.requires_aart.allows(executable_version):
        diagnostics.append(
            _diagnostic(
                SOURCE_INCOMPATIBLE,
                f"AART {executable_version} is outside source compatibility bounds",
                "aart-source.json",
            )
        )
    decision = negotiate_capabilities(
        manifest.required_capabilities,
        (),
        available_capabilities,
    )
    if decision.missing_required:
        missing = ", ".join(str(item) for item in decision.missing_required)
        diagnostics.append(
            _diagnostic(
                SOURCE_INCOMPATIBLE,
                f"source requires unavailable capabilities: {missing}",
                "aart-source.json",
            )
        )
    return tuple(diagnostics)


def load_native_source(
    snapshot: SourceSnapshot,
    *,
    executable_version: SemVer,
    available_capabilities: Iterable[Capability],
) -> Result[NativeSource]:
    """Validate and load a native source from an effect-free acquired snapshot."""

    validated = _validated_entries(snapshot)
    if isinstance(validated, Err):
        return validated
    entries = validated.value
    marker = entries.get("aart-source.json")
    if marker is None or marker.kind is not SnapshotEntryKind.FILE:
        return _error(
            SOURCE_MARKER_MISSING,
            "native source requires aart-source.json at the acquired tree root",
        )
    parsed_manifest = parse_source_manifest(marker.content)
    if isinstance(parsed_manifest, Err):
        return parsed_manifest
    manifest = parsed_manifest.value
    entry_kinds = _validate_protocol_entry_kinds(entries, manifest)
    if isinstance(entry_kinds, Err):
        return entry_kinds
    diagnostics = _compatibility_diagnostics(
        manifest,
        executable_version,
        available_capabilities,
    )
    if diagnostics:
        return Err(diagnostics)
    candidates = _package_candidates(entries, manifest)
    if isinstance(candidates, Err):
        return candidates
    packages: list[NativeArtifactPackage] = []
    identities: set[ArtifactIdentity] = set()
    for root, artifact_type, name in candidates.value:
        package = _load_package(entries, root, artifact_type, name)
        if isinstance(package, Err):
            return package
        if package.value.manifest.identity in identities:
            return _error(
                ARTIFACT_INVALID,
                f"duplicate artifact identity: {package.value.manifest.identity}",
            )
        identities.add(package.value.manifest.identity)
        packages.append(package.value)
    collections = _load_collections(entries, manifest)
    if isinstance(collections, Err):
        return collections
    return Ok(
        NativeSource(
            manifest,
            tuple(sorted(packages, key=lambda item: str(item.manifest.identity))),
            collections.value,
            json_digest(source_manifest_to_json(manifest)),
        )
    )
