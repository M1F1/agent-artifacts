"""Pure native-source loader over already acquired local or immutable Git trees."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping

from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity, SourceLocation
from agent_artifacts.domain.identifiers import ArtifactIdentity, ArtifactKind, ObjectDigest
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.model import Err as SetupErr
from agent_artifacts.model import Ok as SetupOk
from agent_artifacts.model import SetupInstaller
from agent_artifacts.setup import custom_entrypoint_name, has_manual_setup_header, parse_installer

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
    setup_installer: SetupInstaller | None = None


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


# A package directory names its kind, and only these five are packageable — ``collection`` is a
# manifest concept, not a package.  The mapping keeps that closed set in one place and hands the
# validated literal straight to ``ArtifactIdentity`` instead of re-asserting it downstream.
_PACKAGE_KINDS: Mapping[str, ArtifactKind] = {
    "skill": "skill",
    "guideline": "guideline",
    "mcp": "mcp",
    "hook": "hook",
    "memory": "memory",
}


def _package_candidates(
    entries: dict[str, SnapshotEntry],
    manifest: SourceManifest,
) -> Result[tuple[tuple[SafeRelativePath, ArtifactKind, str], ...]]:
    candidates: set[tuple[SafeRelativePath, ArtifactKind, str]] = set()
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
            kind = _PACKAGE_KINDS.get(artifact_type)
            if kind is None:
                return _error(
                    SOURCE_TREE_INVALID,
                    f"unsupported artifact type directory {artifact_type!r}",
                    path,
                )
            candidates.add((root, kind, name))
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
        if artifact_type == "hook":
            name = parsed.value.get("name")
            command = parsed.value.get("command")
            if not isinstance(name, str) or not name or not isinstance(command, str) or not command:
                return _error(
                    ARTIFACT_INVALID,
                    "payload/hook.json requires non-empty string name and command fields",
                    primary_path,
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


def _validate_setup_package(
    manifest: ArtifactManifest,
    package_entries: dict[str, SnapshotEntry],
    *,
    manifest_path: str,
) -> Result[SetupInstaller]:
    """Validate the one current setup protocol inside a canonical package.

    This is intentionally shared by native source compilation and stored-object validation.
    A setup package therefore cannot pass registry publication yet fail only after consumer payload
    effects have been applied.
    """

    assert manifest.setup is not None
    recipe_path = str(manifest.setup.recipe)
    recipe = package_entries.get(recipe_path)
    if recipe is None or recipe.kind is not SnapshotEntryKind.FILE:
        return _error(
            ARTIFACT_INVALID, f"declared setup recipe is missing: {recipe_path}", manifest_path
        )
    custom_name = custom_entrypoint_name(recipe.content)
    if isinstance(custom_name, SetupErr):
        return _error(ARTIFACT_INVALID, custom_name.reason, recipe_path)
    assert isinstance(custom_name, SetupOk)
    custom_entry: SnapshotEntry | None = None
    if custom_name.value is not None:
        custom_path = f"setup/{custom_name.value}"
        custom_entry = package_entries.get(custom_path)
        if (
            custom_entry is None
            or custom_entry.kind is not SnapshotEntryKind.FILE
            or not custom_entry.executable
        ):
            return _error(
                ARTIFACT_INVALID,
                "custom setup entrypoint must be an executable regular file below setup/",
                custom_path,
            )
    installer = parse_installer(
        recipe.content,
        artifact_key=str(manifest.identity),
        descriptor_path=recipe_path,
        custom_bytes=None if custom_entry is None else custom_entry.content,
    )
    if isinstance(installer, SetupErr):
        return _error(ARTIFACT_INVALID, installer.reason, recipe_path)
    assert isinstance(installer, SetupOk)
    manual_path = installer.value.manual_path
    manual = package_entries.get(manual_path)
    if manual is None or manual.kind is not SnapshotEntryKind.FILE:
        return _error(
            ARTIFACT_INVALID,
            "setup requires a regular package-root SETUP.md file",
            manual_path,
        )
    try:
        manual_text = manual.content.decode("utf-8")
    except UnicodeDecodeError:
        return _error(ARTIFACT_INVALID, "SETUP.md must be valid UTF-8", manual_path)
    if not manual_text.strip() or "\x00" in manual_text:
        return _error(ARTIFACT_INVALID, "SETUP.md must be non-empty safe UTF-8 text", manual_path)
    if custom_entry is not None and not has_manual_setup_header(custom_entry.content):
        return _error(
            ARTIFACT_INVALID,
            "custom setup entrypoint lacks the SETUP.md header",
            f"setup/{custom_name.value}",
        )
    if installer.value.platforms != manifest.setup.platforms:
        return _error(
            ARTIFACT_INVALID,
            "setup recipe platforms do not match the artifact manifest",
            recipe_path,
        )
    return Ok(installer.value)


def _compile_package_entries(
    package_entries: dict[str, SnapshotEntry],
    *,
    expected_identity: ArtifactIdentity | None,
    manifest_path: str,
) -> Result[NativeArtifactPackage]:
    """Compile one package tree whose mapping keys are package-relative paths."""

    manifest_file = package_entries.get("artifact.json")
    if manifest_file is None or manifest_file.kind is not SnapshotEntryKind.FILE:
        return _error(ARTIFACT_INVALID, "required file is missing: artifact.json", manifest_path)
    parsed_manifest = parse_artifact_manifest(manifest_file.content, path=manifest_path)
    if isinstance(parsed_manifest, Err):
        return parsed_manifest
    manifest = parsed_manifest.value
    if expected_identity is not None and manifest.identity != expected_identity:
        return _error(
            ARTIFACT_INVALID,
            f"manifest identity {manifest.identity} does not match package path {expected_identity}",
            manifest_path,
        )
    allowed_roots = {
        "artifact.json",
        "README.md",
        "SETUP.md",
        "provenance.json",
        "payload",
        "setup",
    }
    package_root = manifest_path.removesuffix("/artifact.json")
    for relative_path in package_entries:
        if relative_path.split("/", 1)[0] not in allowed_roots:
            location = relative_path if not package_root else f"{package_root}/{relative_path}"
            return _error(
                ARTIFACT_INVALID,
                f"unexpected canonical package path: {relative_path}",
                location,
            )
    primary = _validate_primary_payload(manifest, package_entries, manifest_path=manifest_path)
    if isinstance(primary, Err):
        return primary
    setup_installer: SetupInstaller | None = None
    if manifest.setup is not None:
        setup = _validate_setup_package(
            manifest,
            package_entries,
            manifest_path=manifest_path,
        )
        if isinstance(setup, Err):
            return setup
        setup_installer = setup.value
    elif any(path == "SETUP.md" or path.startswith("setup/") for path in package_entries):
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
            path=("provenance.json" if not package_root else f"{package_root}/provenance.json"),
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
            setup_installer,
        )
    )


def compile_native_package(
    entries: Iterable[SnapshotEntry],
    *,
    expected_identity: ArtifactIdentity | None = None,
) -> Result[NativeArtifactPackage]:
    """Compile a standalone canonical object package from package-relative entries.

    Source loading, registry publication, object-store reads, install planning, and setup planning
    use this same current-protocol boundary.  The function accepts no legacy layout and never
    performs migration or path guessing.
    """

    package_entries: dict[str, SnapshotEntry] = {}
    for entry in entries:
        raw_path = str(entry.path)
        parsed_path = parse_relative_path(raw_path)
        if isinstance(parsed_path, Err) or parsed_path.value != entry.path:
            return _error(
                ARTIFACT_INVALID, f"package path is not canonical: {raw_path!r}", raw_path
            )
        if raw_path in package_entries:
            return _error(ARTIFACT_INVALID, f"duplicate package path: {raw_path}", raw_path)
        if not isinstance(entry.kind, SnapshotEntryKind):
            return _error(ARTIFACT_INVALID, f"invalid package entry kind: {raw_path}", raw_path)
        if not isinstance(entry.content, bytes) or not isinstance(entry.executable, bool):
            return _error(ARTIFACT_INVALID, f"invalid package metadata: {raw_path}", raw_path)
        if entry.kind in {SnapshotEntryKind.SYMLINK, SnapshotEntryKind.SPECIAL}:
            return _error(
                ARTIFACT_INVALID,
                f"canonical package forbids {entry.kind.value} entries: {raw_path}",
                raw_path,
            )
        if entry.kind is SnapshotEntryKind.DIRECTORY and (entry.content or entry.executable):
            return _error(ARTIFACT_INVALID, f"directory has file metadata: {raw_path}", raw_path)
        package_entries[raw_path] = entry
    return _compile_package_entries(
        package_entries,
        expected_identity=expected_identity,
        manifest_path="artifact.json",
    )


def _load_package(
    entries: dict[str, SnapshotEntry],
    root: SafeRelativePath,
    expected_type: ArtifactKind,
    expected_name: str,
) -> Result[NativeArtifactPackage]:
    base = f"{root}/{expected_type}/{expected_name}"
    package_entries = _relative_package_entries(entries, base)
    return _compile_package_entries(
        package_entries,
        expected_identity=ArtifactIdentity(expected_type, expected_name),
        manifest_path=f"{base}/artifact.json",
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


def _validate_declared_dependencies(
    packages: tuple[NativeArtifactPackage, ...],
) -> Result[None]:
    """Require a complete, acyclic local package graph before a source is consumable."""

    by_identity = {item.manifest.identity: item for item in packages}
    dependencies: dict[ArtifactIdentity, tuple[ArtifactIdentity, ...]] = {}
    for package in packages:
        resolved: list[ArtifactIdentity] = []
        for selector in package.manifest.requires:
            dependency = by_identity.get(selector.identity)
            if dependency is None:
                return _error(
                    ARTIFACT_INVALID,
                    f"{package.manifest.identity} requires missing {selector.identity}",
                )
            if selector.version is not None and not selector.version.allows(
                dependency.manifest.version
            ):
                return _error(
                    ARTIFACT_INVALID,
                    f"{package.manifest.identity} excludes available dependency {selector.identity}",
                )
            resolved.append(selector.identity)
        dependencies[package.manifest.identity] = tuple(sorted(resolved, key=str))

    visited: set[ArtifactIdentity] = set()

    def visit(identity: ArtifactIdentity, trail: tuple[ArtifactIdentity, ...]) -> Result[None]:
        if identity in trail:
            cycle = " -> ".join(str(item) for item in (*trail, identity))
            return _error(ARTIFACT_INVALID, f"artifact dependency cycle: {cycle}")
        if identity in visited:
            return Ok(None)
        next_trail = (*trail, identity)
        for dependency in dependencies[identity]:
            checked = visit(dependency, next_trail)
            if isinstance(checked, Err):
                return checked
        visited.add(identity)
        return Ok(None)

    for identity in sorted(dependencies, key=str):
        checked = visit(identity, ())
        if isinstance(checked, Err):
            return checked
    return Ok(None)


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
    dependency_graph = _validate_declared_dependencies(tuple(packages))
    if isinstance(dependency_graph, Err):
        return dependency_graph
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
