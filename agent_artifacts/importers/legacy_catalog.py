"""Deterministic importer for the complete AART 0.1.x catalog layout."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Protocol, cast
from urllib.parse import urlsplit

from agent_artifacts import catalog as legacy_catalog
from agent_artifacts.domain.diagnostics import (
    Diagnostic,
    DiagnosticCode,
    Severity,
    SourceLocation,
    sort_diagnostics,
)
from agent_artifacts.domain.identifiers import (
    ArtifactIdentity,
    ArtifactKind,
    ObjectDigest,
    SourceId,
)
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.model import Artifact as LegacyArtifact
from agent_artifacts.model import ArtifactType as LegacyArtifactType
from agent_artifacts.model import Catalog as LegacyCatalog
from agent_artifacts.model import Err as LegacyErr
from agent_artifacts.model import Ok as LegacyOk
from agent_artifacts.protocol.hashing import json_digest, parse_sha256, sha256_bytes
from agent_artifacts.protocol.json import (
    JsonArray,
    JsonObject,
    JsonValue,
    canonical_json_bytes,
    parse_json,
)
from agent_artifacts.protocol.native_models import (
    INSTALL_EFFECTS_BY_TYPE,
    PAYLOAD_FORMAT_BY_TYPE,
    ArtifactManifest,
    ArtifactSelector,
    CanonicalArtifactType,
    CollectionManifest,
    CompatibilitySpec,
    ImporterProvenance,
    InstallMode,
    InstallScope,
    InstallSpec,
    OriginProvenance,
    PayloadSpec,
    Provenance,
    SetupReference,
    SourceManifest,
)
from agent_artifacts.protocol.native_schema import (
    artifact_manifest_to_json,
    collection_manifest_to_json,
    provenance_to_json,
    source_manifest_to_json,
)
from agent_artifacts.protocol.native_tree import (
    SnapshotEntry,
    SnapshotEntryKind,
    SnapshotOrigin,
    SourceSnapshot,
    load_native_source,
)
from agent_artifacts.protocol.paths import SafeRelativePath, parse_relative_path
from agent_artifacts.protocol.semver import SemVer, VersionBounds, parse_semver
from agent_artifacts.sources.model import source_snapshot_digest
from agent_artifacts.upstreams import (
    UpstreamCatalog,
    UpstreamEntry,
    UpstreamKey,
    parse_upstreams,
)

from .model import (
    ImportApplyPlan,
    ImportChange,
    ImportChangeKind,
    ImportDiff,
    ImporterDescriptor,
    ImporterInput,
    ImportOrigin,
    ImportPlan,
    ImportScan,
    LegacyArtifactCandidate,
    MaterializedImport,
    ValidatedImport,
)

IMPORT_LOSSY = DiagnosticCode("import-lossy")
IMPORT_AMBIGUOUS = DiagnosticCode("import-ambiguous")
IMPORT_STALE = DiagnosticCode("import-stale")
IMPORT_INVALID = DiagnosticCode("import-invalid")
LEGACY_CATALOG_IMPORTER = ImporterDescriptor(
    "legacy-catalog-v1",
    SemVer(1, 0, 0),
    ("bundles", "guidelines", "hooks", "mcp", "memory", "skills", "upstreams.json"),
    ("guideline", "hook", "mcp", "memory", "skill"),
)

_SLUG_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_LICENSE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+() -]{0,99}$")
_MAX_ENTRIES = 100_000
_MAX_FILE_BYTES = 16 * 1024 * 1024
_MAX_TOTAL_BYTES = 256 * 1024 * 1024
_KNOWN_ROOTS = frozenset({"skills", "guidelines", "mcp", "hooks", "memory", "bundles"})
# Every artifact kind a legacy bundle can include; ``collection`` is never a bundle member.
_BUNDLED_KINDS: tuple[ArtifactKind, ...] = ("skill", "guideline", "mcp", "hook", "memory")


def _diagnostic(code: DiagnosticCode, message: str, path: str | None = None) -> Diagnostic:
    return Diagnostic(code, Severity.ERROR, message, SourceLocation(path=path))


def _error(code: DiagnosticCode, message: str, path: str | None = None) -> Err:
    return Err((_diagnostic(code, message, path),))


def _safe_path(raw: str) -> Result[SafeRelativePath]:
    parsed = parse_relative_path(raw)
    if isinstance(parsed, Err):
        return _error(IMPORT_LOSSY, f"legacy path is not canonical: {raw!r}", raw)
    return parsed


@dataclass(frozen=True, slots=True)
class LegacyCatalogOptions:
    source_id: SourceId
    display_name: str
    artifact_version: SemVer
    profiles: tuple[str, ...]
    platforms: tuple[str, ...]
    scopes: tuple[str, ...] = ("project", "user")
    modes: tuple[str, ...] = ("copy", "symlink")
    license: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.source_id, SourceId)
            or _SLUG_RE.fullmatch(self.source_id.value) is None
            or not isinstance(self.display_name, str)
            or not self.display_name
            or self.display_name != self.display_name.strip()
            or "\n" in self.display_name
            or "\r" in self.display_name
            or not isinstance(self.artifact_version, SemVer)
            or not self.profiles
            or not self.platforms
            or any(_SLUG_RE.fullmatch(item) is None for item in (*self.profiles, *self.platforms))
            or not self.scopes
            or not set(self.scopes) <= {"project", "user"}
            or not self.modes
            or not set(self.modes) <= {"copy", "symlink"}
            or (self.license is not None and _LICENSE_RE.fullmatch(self.license) is None)
        ):
            raise ValueError("legacy catalog importer options are invalid")
        object.__setattr__(self, "profiles", tuple(sorted(set(self.profiles))))
        object.__setattr__(self, "platforms", tuple(sorted(set(self.platforms))))
        object.__setattr__(self, "scopes", tuple(sorted(set(self.scopes))))
        object.__setattr__(self, "modes", tuple(sorted(set(self.modes))))


def _options_json(options: LegacyCatalogOptions) -> JsonObject:
    entries: list[tuple[str, JsonValue]] = [
        ("artifact_version", str(options.artifact_version)),
        ("display_name", options.display_name),
        ("modes", JsonArray(options.modes)),
        ("platforms", JsonArray(options.platforms)),
        ("profiles", JsonArray(options.profiles)),
        ("schema_version", 1),
        ("scopes", JsonArray(options.scopes)),
        ("source_id", options.source_id.value),
    ]
    if options.license is not None:
        entries.append(("license", options.license))
    return JsonObject(tuple(entries))


def _options_from_json(value: JsonObject) -> Result[LegacyCatalogOptions]:
    entries = dict(value.entries)
    expected = {
        "artifact_version",
        "display_name",
        "modes",
        "platforms",
        "profiles",
        "schema_version",
        "scopes",
        "source_id",
    }
    if (
        set(entries) not in {frozenset(expected), frozenset((*expected, "license"))}
        or entries.get("schema_version") != 1
    ):
        return _error(IMPORT_INVALID, "import plan options are malformed")

    def strings(name: str) -> tuple[str, ...] | None:
        item = entries[name]
        if not isinstance(item, JsonArray) or not all(
            isinstance(value, str) for value in item.items
        ):
            return None
        return tuple(cast(str, value) for value in item.items)

    profiles = strings("profiles")
    platforms = strings("platforms")
    scopes = strings("scopes")
    modes = strings("modes")
    raw_version = entries["artifact_version"]
    raw_license = entries.get("license")
    if (
        not isinstance(entries["source_id"], str)
        or not isinstance(entries["display_name"], str)
        or not isinstance(raw_version, str)
        or profiles is None
        or platforms is None
        or scopes is None
        or modes is None
        or (raw_license is not None and not isinstance(raw_license, str))
    ):
        return _error(IMPORT_INVALID, "import plan options have invalid types")
    version = parse_semver(raw_version)
    if isinstance(version, Err):
        return _error(IMPORT_INVALID, "import plan artifact version is invalid")
    try:
        return Ok(
            LegacyCatalogOptions(
                SourceId(entries["source_id"]),
                entries["display_name"],
                version.value,
                profiles,
                platforms,
                scopes,
                modes,
                raw_license,
            )
        )
    except ValueError as error:
        return _error(IMPORT_INVALID, str(error))


def _snapshot_index(
    snapshot: SourceSnapshot,
) -> Result[tuple[dict[str, SnapshotEntry], ObjectDigest]]:
    if len(snapshot.entries) > _MAX_ENTRIES:
        return _error(IMPORT_LOSSY, "legacy input exceeds the entry-count bound")
    total_bytes = 0
    for entry in snapshot.entries:
        if entry.kind is SnapshotEntryKind.FILE:
            if len(entry.content) > _MAX_FILE_BYTES:
                return _error(
                    IMPORT_LOSSY,
                    "legacy input file exceeds the size bound",
                    str(entry.path),
                )
            total_bytes += len(entry.content)
            if total_bytes > _MAX_TOTAL_BYTES:
                return _error(IMPORT_LOSSY, "legacy input exceeds the total-size bound")
    digest = source_snapshot_digest(snapshot)
    if isinstance(digest, Err):
        message = "; ".join(item.message for item in digest.diagnostics)
        return _error(IMPORT_LOSSY, f"legacy input is not an inert canonical tree: {message}")
    return Ok(({str(entry.path): entry for entry in snapshot.entries}, digest.value))


def _file(index: dict[str, SnapshotEntry], path: str) -> Result[SnapshotEntry]:
    entry = index.get(path)
    if entry is None or entry.kind is not SnapshotEntryKind.FILE:
        return _error(IMPORT_LOSSY, f"required legacy file is missing: {path}", path)
    return Ok(entry)


def _strict_object(data: bytes, path: str) -> Result[JsonObject]:
    parsed = parse_json(data, location=SourceLocation(path=path))
    if isinstance(parsed, Err) or not isinstance(parsed.value, JsonObject):
        return _error(IMPORT_LOSSY, f"legacy JSON must be one strict object: {path}", path)
    return Ok(parsed.value)


def _text(entry: SnapshotEntry, path: str) -> Result[str]:
    try:
        return Ok(entry.content.decode("utf-8", errors="strict"))
    except UnicodeDecodeError:
        return _error(IMPORT_LOSSY, f"legacy text is not UTF-8: {path}", path)


def _recognized_names(index: dict[str, SnapshotEntry], root: str) -> tuple[str, ...]:
    names = {
        path.split("/")[1]
        for path, entry in index.items()
        if entry.kind is SnapshotEntryKind.FILE
        and path.startswith(f"{root}/")
        and len(path.split("/")) >= 2
    }
    return tuple(sorted(names))


def _artifact_shape(
    index: dict[str, SnapshotEntry], artifact_type: str, name: str
) -> Result[tuple[str, str]]:
    canonical_name = name.removesuffix(".md") if artifact_type in {"guideline", "memory"} else name
    if _SLUG_RE.fullmatch(canonical_name) is None:
        return _error(
            IMPORT_LOSSY,
            f"legacy artifact name cannot be represented canonically: {artifact_type}/{canonical_name}",
        )
    if artifact_type == "skill":
        source = f"skills/{name}"
        descriptor = f"{source}/SKILL.md"
        required = _file(index, descriptor)
        return required if isinstance(required, Err) else Ok((source, descriptor))
    if artifact_type in {"guideline", "memory"}:
        root = "guidelines" if artifact_type == "guideline" else "memory"
        source = f"{root}/{name}"
        if not name.endswith(".md"):
            return _error(IMPORT_LOSSY, f"unexpected legacy file below {root}: {source}", source)
        canonical_name = name.removesuffix(".md")
        if _SLUG_RE.fullmatch(canonical_name) is None:
            return _error(
                IMPORT_LOSSY,
                f"legacy artifact name cannot be represented canonically: {artifact_type}/{canonical_name}",
                source,
            )
        required = _file(index, source)
        return required if isinstance(required, Err) else Ok((source, source))
    if artifact_type == "hook":
        source = f"hooks/{name}"
        descriptor = f"{source}/hook.json"
        required = _file(index, descriptor)
        return required if isinstance(required, Err) else Ok((source, descriptor))
    if artifact_type == "mcp":
        flat = f"mcp/{name}.json"
        directory = f"mcp/{name}"
        flat_exists = flat in index and index[flat].kind is SnapshotEntryKind.FILE
        directory_files = tuple(
            path
            for path, entry in index.items()
            if entry.kind is SnapshotEntryKind.FILE and path.startswith(f"{directory}/")
        )
        if flat_exists and directory_files:
            return _error(
                IMPORT_AMBIGUOUS,
                f"legacy MCP has both flat and directory representations: {name}",
            )
        if flat_exists:
            return Ok((flat, flat))
        descriptors = tuple(
            path
            for path in (f"{directory}/mcp.json", f"{directory}/{name}.json")
            if path in index and index[path].kind is SnapshotEntryKind.FILE
        )
        if len(descriptors) != 1:
            return _error(
                IMPORT_AMBIGUOUS if descriptors else IMPORT_LOSSY,
                f"legacy MCP {name!r} requires exactly one recognized descriptor",
                directory,
            )
        return Ok((directory, descriptors[0]))
    return _error(IMPORT_LOSSY, f"unsupported legacy artifact type: {artifact_type}")


def _subtree_entries(
    index: dict[str, SnapshotEntry], source_path: str
) -> Result[tuple[SnapshotEntry, ...]]:
    source = index.get(source_path)
    if source is not None and source.kind is SnapshotEntryKind.FILE:
        parsed = _safe_path(source_path.split("/")[-1])
        if isinstance(parsed, Err):
            return parsed
        return Ok(
            (
                SnapshotEntry(
                    parsed.value, SnapshotEntryKind.FILE, source.content, source.executable
                ),
            )
        )
    prefix = f"{source_path}/"
    entries: list[SnapshotEntry] = []
    for path, entry in index.items():
        if not path.startswith(prefix):
            continue
        relative = path.removeprefix(prefix)
        parsed = _safe_path(relative)
        if isinstance(parsed, Err):
            return parsed
        entries.append(SnapshotEntry(parsed.value, entry.kind, entry.content, entry.executable))
    if not entries:
        return _error(IMPORT_LOSSY, f"legacy artifact content is missing: {source_path}")
    return Ok(tuple(entries))


def _subtree_digest(index: dict[str, SnapshotEntry], source_path: str) -> Result[ObjectDigest]:
    source = index.get(source_path)
    if source is not None and source.kind is SnapshotEntryKind.FILE:
        return Ok(sha256_bytes(source.content))
    entries = _subtree_entries(index, source_path)
    if isinstance(entries, Err):
        return entries
    digest = source_snapshot_digest(SourceSnapshot(SnapshotOrigin.IMMUTABLE_GIT, entries.value))
    if isinstance(digest, Err):
        return _error(IMPORT_LOSSY, f"legacy artifact cannot be hashed: {source_path}")
    return digest


class _Hasher(Protocol):
    def update(self, data: bytes) -> object: ...


def _legacy_token(hasher: _Hasher, value: bytes) -> None:
    hasher.update(str(len(value)).encode("ascii"))
    hasher.update(b":")
    hasher.update(value)
    hasher.update(b";")


def _legacy_content_hash(index: dict[str, SnapshotEntry], source_path: str) -> Result[str]:
    source = index.get(source_path)
    if source is not None and source.kind is SnapshotEntryKind.FILE:
        return Ok(str(sha256_bytes(source.content)))
    subtree = _subtree_entries(index, source_path)
    if isinstance(subtree, Err):
        return subtree
    by_parent: dict[str, list[tuple[str, SnapshotEntry]]] = {}
    for entry in subtree.value:
        raw = str(entry.path)
        parent, _, name = raw.rpartition("/")
        by_parent.setdefault(parent, []).append((name, entry))
    hasher = hashlib.sha256()
    _legacy_token(hasher, b"agent-artifacts-tree-v1")

    def visit(parent: str) -> None:
        children = by_parent.get(parent, [])
        directories = sorted(
            (name, entry) for name, entry in children if entry.kind is SnapshotEntryKind.DIRECTORY
        )
        files = sorted(
            (name, entry) for name, entry in children if entry.kind is SnapshotEntryKind.FILE
        )
        for _name, entry in directories:
            _legacy_token(hasher, b"dir")
            _legacy_token(hasher, str(entry.path).encode("utf-8"))
        for _name, entry in files:
            _legacy_token(hasher, b"file")
            _legacy_token(hasher, str(entry.path).encode("utf-8"))
            _legacy_token(hasher, str(len(entry.content)).encode("ascii"))
            hasher.update(entry.content)
        for _name, entry in directories:
            visit(str(entry.path))

    visit("")
    return Ok(f"sha256:{hasher.hexdigest()}")


def _strict_upstreams(data: bytes) -> Result[UpstreamCatalog]:
    parsed = _strict_object(data, "upstreams.json")
    if isinstance(parsed, Err):
        return parsed
    root = dict(parsed.value.entries)
    if set(root) != {"version", "artifacts"} or not isinstance(root["artifacts"], JsonObject):
        return _error(IMPORT_LOSSY, "upstreams.json has unsupported structural fields")
    for key, value in root["artifacts"].entries:
        if not isinstance(value, JsonObject):
            return _error(IMPORT_LOSSY, f"upstreams entry must be an object: {key}")
        fields = dict(value.entries)
        if set(fields) != {"source", "last_synced"}:
            return _error(IMPORT_LOSSY, f"upstreams entry has unsupported fields: {key}")
        if not isinstance(fields["source"], JsonObject) or not isinstance(
            fields["last_synced"], JsonObject
        ):
            return _error(IMPORT_LOSSY, f"upstreams entry objects are malformed: {key}")
        if not set(fields["source"].keys()) <= {
            "kind",
            "repo",
            "ref",
            "path",
            "api_url",
            "web_url",
        } or set(fields["last_synced"].keys()) != {
            "sha",
            "content_hash",
            "synced_at",
        }:
            return _error(IMPORT_LOSSY, f"upstreams entry has unsupported nested fields: {key}")
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return _error(IMPORT_LOSSY, "upstreams.json is not UTF-8")
    legacy = parse_upstreams(text)
    if isinstance(legacy, LegacyErr):
        return _error(IMPORT_LOSSY, legacy.reason, "upstreams.json")
    assert isinstance(legacy, LegacyOk)
    return Ok(legacy.value)


def _upstream_url(entry: UpstreamEntry) -> Result[str]:
    source = entry.source
    if source.web_url is not None:
        raw = source.web_url
    elif source.repo.startswith("https://"):
        raw = source.repo
    else:
        host = "github.com"
        if source.api_url is not None:
            parsed = urlsplit(source.api_url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
                or parsed.path.rstrip("/") not in {"", "/api/v3"}
            ):
                return _error(IMPORT_LOSSY, "upstream API URL cannot identify a safe Git origin")
            host = "github.com" if parsed.hostname == "api.github.com" else parsed.hostname
        raw = f"https://{host}/{source.repo}"
    if raw.endswith("/"):
        return _error(IMPORT_LOSSY, "upstream repository URL must not end with a slash")
    raw = raw if raw.endswith(".git") else f"{raw}.git"
    try:
        validated = ImportOrigin(raw, "0" * 40, None)
    except ValueError:
        return _error(IMPORT_LOSSY, "upstream URL is not a credential-free Git origin")
    return Ok(validated.url)


def _join_origin_path(root: SafeRelativePath | None, source_path: str) -> Result[SafeRelativePath]:
    raw = source_path if root is None else f"{root}/{source_path}"
    return _safe_path(raw)


def _origin_for(
    request: ImporterInput,
    index: dict[str, SnapshotEntry],
    identity: ArtifactIdentity,
    source_path: str,
    upstreams: UpstreamCatalog,
) -> Result[tuple[OriginProvenance, tuple[tuple[str, JsonValue], ...]]]:
    input_digest = _subtree_digest(index, source_path)
    if isinstance(input_digest, Err):
        return input_digest
    tracked = upstreams.entries.get(
        UpstreamKey(cast(LegacyArtifactType, identity.kind), identity.name)
    )
    if tracked is None:
        origin_path = _join_origin_path(request.origin.root, source_path)
        if isinstance(origin_path, Err):
            return origin_path
        return Ok(
            (
                OriginProvenance(
                    "git",
                    request.origin.url,
                    request.origin.resolved_commit,
                    origin_path.value,
                    input_digest.value,
                ),
                (),
            )
        )
    sync = tracked.last_synced
    if sync is None or _COMMIT_RE.fullmatch(sync.sha) is None:
        return _error(
            IMPORT_LOSSY,
            f"tracked legacy artifact lacks an immutable commit: {identity}",
            "upstreams.json",
        )
    recorded_digest = parse_sha256(sync.content_hash)
    actual_legacy_hash = _legacy_content_hash(index, source_path)
    if isinstance(recorded_digest, Err) or isinstance(actual_legacy_hash, Err):
        return _error(
            IMPORT_LOSSY,
            f"tracked legacy artifact has an invalid content hash: {identity}",
            "upstreams.json",
        )
    if actual_legacy_hash.value != sync.content_hash:
        return _error(
            IMPORT_STALE,
            f"tracked legacy artifact differs from its recorded content hash: {identity}",
            source_path,
        )
    url = _upstream_url(tracked)
    path = _safe_path(tracked.source.path)
    if isinstance(url, Err):
        return url
    if isinstance(path, Err):
        return path
    extension = JsonObject(
        (
            ("legacy_content_hash", sync.content_hash),
            ("ref", tracked.source.ref),
        )
    )
    return Ok(
        (
            OriginProvenance(
                "git",
                url.value,
                sync.sha,
                path.value,
                input_digest.value,
            ),
            (("com.m1f1.legacy-upstream", extension),),
        )
    )


def _setup_metadata(
    index: dict[str, SnapshotEntry], source_path: str, artifact_type: str
) -> Result[tuple[SafeRelativePath | None, tuple[str, ...]]]:
    setup_prefix = f"{source_path}/setup/"
    setup_files = tuple(
        path
        for path, entry in index.items()
        if entry.kind is SnapshotEntryKind.FILE and path.startswith(setup_prefix)
    )
    if not setup_files:
        return Ok((None, ()))
    if artifact_type not in {"mcp", "hook", "skill"}:
        return _error(IMPORT_LOSSY, "legacy setup content is unsupported for this artifact type")
    recipe_path = f"{source_path}/setup/installer.json"
    recipe = _file(index, recipe_path)
    if isinstance(recipe, Err):
        return recipe
    document = _strict_object(recipe.value.content, recipe_path)
    if isinstance(document, Err):
        return document
    platforms = dict(document.value.entries).get("platforms")
    if (
        not isinstance(platforms, JsonArray)
        or not platforms.items
        or not all(isinstance(item, str) and _SLUG_RE.fullmatch(item) for item in platforms.items)
    ):
        return _error(IMPORT_LOSSY, "legacy setup platforms are missing or ambiguous", recipe_path)
    return Ok((SafeRelativePath(("setup", "installer.json")), tuple(platforms.items)))  # type: ignore[arg-type]


def _parse_artifact(
    request: ImporterInput,
    index: dict[str, SnapshotEntry],
    artifact_type: str,
    raw_name: str,
    upstreams: UpstreamCatalog,
) -> Result[LegacyArtifactCandidate]:
    shape = _artifact_shape(index, artifact_type, raw_name)
    if isinstance(shape, Err):
        return shape
    source_path, descriptor_path = shape.value
    canonical_name = (
        raw_name.removesuffix(".md") if artifact_type in {"guideline", "memory"} else raw_name
    )
    descriptor = _file(index, descriptor_path)
    if isinstance(descriptor, Err):
        return descriptor
    if artifact_type in {"mcp", "hook"}:
        strict = _strict_object(descriptor.value.content, descriptor_path)
        if isinstance(strict, Err):
            return strict
    text = _text(descriptor.value, descriptor_path)
    if isinstance(text, Err):
        return text
    if artifact_type == "skill":
        parsed = legacy_catalog.parse_skill(text.value, canonical_name)
    elif artifact_type == "guideline":
        parsed = legacy_catalog.parse_guideline(text.value, canonical_name)
    elif artifact_type == "memory":
        parsed = legacy_catalog.parse_memory(text.value, canonical_name)
    elif artifact_type == "mcp":
        parsed = legacy_catalog.parse_mcp(text.value, canonical_name, root=source_path)
    else:
        parsed = legacy_catalog.parse_hook(text.value, canonical_name)
    if isinstance(parsed, LegacyErr):
        return _error(IMPORT_LOSSY, parsed.reason, descriptor_path)
    assert isinstance(parsed, LegacyOk)
    identity = ArtifactIdentity(cast(CanonicalArtifactType, artifact_type), canonical_name)
    origin = _origin_for(request, index, identity, source_path, upstreams)
    if isinstance(origin, Err):
        return origin
    setup = _setup_metadata(index, source_path, artifact_type)
    if isinstance(setup, Err):
        return setup
    source = _safe_path(source_path)
    descriptor_safe = _safe_path(descriptor_path)
    if isinstance(source, Err):
        return source
    if isinstance(descriptor_safe, Err):
        return descriptor_safe
    profiles = None if parsed.value.compatibility is None else parsed.value.compatibility.profiles
    try:
        return Ok(
            LegacyArtifactCandidate(
                identity,
                source.value,
                descriptor_safe.value,
                parsed.value.description,
                profiles,
                setup.value[0],
                setup.value[1],
                origin.value[0],
                origin.value[1],
            )
        )
    except ValueError as error:
        return _error(IMPORT_LOSSY, str(error), source_path)


def _parse_collections(
    index: dict[str, SnapshotEntry], artifacts: tuple[LegacyArtifactCandidate, ...]
) -> Result[tuple[CollectionManifest, ...]]:
    paths = tuple(
        sorted(
            path
            for path, entry in index.items()
            if entry.kind is SnapshotEntryKind.FILE and path.startswith("bundles/")
        )
    )
    bundles = {}
    for path in paths:
        parts = path.split("/")
        if len(parts) != 2 or not parts[1].endswith(".json"):
            return _error(IMPORT_LOSSY, f"unexpected legacy bundle path: {path}", path)
        name = parts[1].removesuffix(".json")
        if _SLUG_RE.fullmatch(name) is None:
            return _error(IMPORT_LOSSY, f"bundle name is not canonical: {name}", path)
        document = _strict_object(index[path].content, path)
        if isinstance(document, Err):
            return document
        fields = dict(document.value.entries)
        if not set(fields) <= {"name", "description", "extends", "includes", "pins"}:
            return _error(
                IMPORT_LOSSY, f"bundle contains unsupported structural fields: {name}", path
            )
        if fields.get("name") != name:
            return _error(IMPORT_LOSSY, f"bundle name does not match its path: {name}", path)
        text = _text(index[path], path)
        if isinstance(text, Err):
            return text
        parsed = legacy_catalog.parse_bundle(text.value, name)
        if isinstance(parsed, LegacyErr):
            return _error(IMPORT_LOSSY, parsed.reason, path)
        assert isinstance(parsed, LegacyOk)
        bundles[name] = parsed.value
    legacy = LegacyCatalog(
        {
            (cast(LegacyArtifactType, item.identity.kind), item.identity.name): LegacyArtifact(
                cast(LegacyArtifactType, item.identity.kind),
                item.identity.name,
                str(item.source_path),
                description=item.summary,
            )
            for item in artifacts
        },
        bundles,
    )
    diagnostics = legacy_catalog.validate_catalog(legacy)
    if diagnostics:
        return Err(
            tuple(
                _diagnostic(IMPORT_LOSSY, item.reason, f"bundles/{name}.json")
                for name, item in zip(sorted(bundles), diagnostics, strict=False)
            )
        )
    collections: list[CollectionManifest] = []
    for name in sorted(bundles):
        bundle = bundles[name]
        selectors = tuple(
            ArtifactSelector(ArtifactIdentity(artifact_type, artifact_name))
            for artifact_type in _BUNDLED_KINDS
            for artifact_name in bundle.includes.get(artifact_type, ())
        )
        extensions: tuple[tuple[str, JsonValue], ...] = ()
        if bundle.pins:
            extensions = (
                (
                    "com.m1f1.legacy-pins",
                    JsonObject(tuple(sorted(bundle.pins.items()))),
                ),
            )
        collections.append(
            CollectionManifest(
                1,
                name,
                bundle.description,
                selectors,
                tuple(bundle.extends),
                extensions,
            )
        )
    return Ok(tuple(collections))


def scan_legacy_catalog(request: ImporterInput) -> Result[ImportScan]:
    """Recognize the complete legacy catalog without executing or mutating input."""

    if not isinstance(request, ImporterInput):
        return _error(IMPORT_INVALID, "legacy importer request is invalid")
    indexed = _snapshot_index(request.snapshot)
    if isinstance(indexed, Err):
        return indexed
    index, input_digest = indexed.value
    upstreams = UpstreamCatalog(1, {})
    upstream_entry = index.get("upstreams.json")
    if upstream_entry is not None:
        if upstream_entry.kind is not SnapshotEntryKind.FILE:
            return _error(IMPORT_LOSSY, "upstreams.json must be a file")
        parsed_upstreams = _strict_upstreams(upstream_entry.content)
        if isinstance(parsed_upstreams, Err):
            return parsed_upstreams
        upstreams = parsed_upstreams.value
    diagnostics: list[Diagnostic] = []
    artifacts: list[LegacyArtifactCandidate] = []
    names_by_type = {
        "skill": _recognized_names(index, "skills"),
        "guideline": _recognized_names(index, "guidelines"),
        "mcp": _recognized_names(index, "mcp"),
        "hook": _recognized_names(index, "hooks"),
        "memory": _recognized_names(index, "memory"),
    }
    for artifact_type in ("skill", "guideline", "mcp", "hook", "memory"):
        names = names_by_type[artifact_type]
        if artifact_type == "mcp":
            names = tuple(sorted(set(name.removesuffix(".json") for name in names)))
        for name in names:
            parsed = _parse_artifact(request, index, artifact_type, name, upstreams)
            if isinstance(parsed, Err):
                diagnostics.extend(parsed.diagnostics)
            else:
                artifacts.append(parsed.value)
    identities = tuple(item.identity for item in artifacts)
    if len(set(identities)) != len(identities):
        diagnostics.append(_diagnostic(IMPORT_AMBIGUOUS, "legacy catalog has duplicate identities"))
    candidate_keys = {
        UpstreamKey(cast(LegacyArtifactType, item.identity.kind), item.identity.name)
        for item in artifacts
    }
    for key in sorted(set(upstreams.entries) - candidate_keys, key=str):
        diagnostics.append(
            _diagnostic(
                IMPORT_LOSSY,
                f"upstreams.json references an artifact absent from the catalog: {key}",
                "upstreams.json",
            )
        )
    if diagnostics:
        return Err(sort_diagnostics(diagnostics))
    collections = _parse_collections(index, tuple(artifacts))
    if isinstance(collections, Err):
        return collections
    try:
        return Ok(
            ImportScan(
                LEGACY_CATALOG_IMPORTER,
                input_digest,
                tuple(artifacts),
                collections.value,
            )
        )
    except ValueError as error:
        return _error(IMPORT_LOSSY, str(error))


def plan_legacy_catalog(scan: ImportScan, options: LegacyCatalogOptions) -> Result[ImportPlan]:
    if scan.importer != LEGACY_CATALOG_IMPORTER:
        return _error(IMPORT_INVALID, "scan was produced by a different importer")
    option_values = _options_json(options)
    options_digest = json_digest(option_values)
    plan_value = _plan_json(scan, options_digest)
    return Ok(ImportPlan(scan, option_values, options_digest, json_digest(plan_value)))


def _plan_json(scan: ImportScan, options_digest: ObjectDigest) -> JsonObject:
    return JsonObject(
        (
            ("artifacts", JsonArray(tuple(str(item.identity) for item in scan.artifacts))),
            ("collections", JsonArray(tuple(item.name for item in scan.collections))),
            ("importer_id", scan.importer.id),
            ("importer_version", str(scan.importer.version)),
            ("input_digest", str(scan.input_digest)),
            ("options_digest", str(options_digest)),
        )
    )


def _put(
    output: dict[str, SnapshotEntry],
    path: str,
    kind: SnapshotEntryKind,
    content: bytes = b"",
    executable: bool = False,
) -> Result[None]:
    parsed = _safe_path(path)
    if isinstance(parsed, Err):
        return parsed
    existing = output.get(path)
    entry = SnapshotEntry(parsed.value, kind, content, executable)
    if existing is not None and existing != entry:
        return _error(IMPORT_AMBIGUOUS, f"canonical output path collision: {path}", path)
    output[path] = entry
    parts = parsed.value.parts
    for length in range(1, len(parts)):
        parent = "/".join(parts[:length])
        parent_path = SafeRelativePath(parts[:length])
        prior = output.get(parent)
        directory = SnapshotEntry(parent_path, SnapshotEntryKind.DIRECTORY)
        if prior is not None and prior != directory:
            return _error(IMPORT_AMBIGUOUS, f"canonical parent path collision: {parent}")
        output[parent] = directory
    return Ok(None)


def _copy_payload(
    output: dict[str, SnapshotEntry],
    index: dict[str, SnapshotEntry],
    candidate: LegacyArtifactCandidate,
    base: str,
) -> Result[None]:
    source_path = str(candidate.source_path)
    source = index.get(source_path)
    if source is not None and source.kind is SnapshotEntryKind.FILE:
        filename = "mcp.json" if candidate.identity.kind == "mcp" else source_path.split("/")[-1]
        return _put(
            output,
            f"{base}/payload/{filename}",
            SnapshotEntryKind.FILE,
            source.content,
            source.executable,
        )
    prefix = f"{source_path}/"
    descriptor_relative = str(candidate.descriptor_path).removeprefix(prefix)
    for path, entry in sorted(index.items()):
        if not path.startswith(prefix):
            continue
        relative = path.removeprefix(prefix)
        if relative == "setup" or relative.startswith("setup/"):
            destination = f"{base}/{relative}"
        else:
            payload_relative = (
                "mcp.json"
                if candidate.identity.kind == "mcp" and relative == descriptor_relative
                else relative
            )
            destination = f"{base}/payload/{payload_relative}"
        written = _put(
            output,
            destination,
            entry.kind,
            entry.content,
            entry.executable,
        )
        if isinstance(written, Err):
            return written
    return Ok(None)


def materialize_legacy_catalog(
    request: ImporterInput,
    plan: ImportPlan,
) -> Result[MaterializedImport]:
    current_scan = scan_legacy_catalog(request)
    if isinstance(current_scan, Err):
        return current_scan
    if current_scan.value != plan.scan:
        return _error(IMPORT_STALE, "legacy input changed after the reviewed scan")
    options = _options_from_json(plan.options)
    if isinstance(options, Err):
        return options
    if json_digest(plan.options) != plan.options_digest:
        return _error(IMPORT_INVALID, "import plan options digest does not match")
    if json_digest(_plan_json(plan.scan, plan.options_digest)) != plan.plan_digest:
        return _error(IMPORT_INVALID, "import plan digest does not match its reviewed inputs")
    indexed = _snapshot_index(request.snapshot)
    if isinstance(indexed, Err):
        return indexed
    index = indexed.value[0]
    output: dict[str, SnapshotEntry] = {}
    source_manifest = SourceManifest(
        1,
        1,
        options.value.source_id,
        options.value.display_name,
        VersionBounds(SemVer(1, 0, 0, ("a1",)), SemVer(2, 0, 0)),
        (),
        (SafeRelativePath(("artifacts",)),),
        (SafeRelativePath(("collections",)),) if plan.scan.collections else (),
    )
    source_written = _put(
        output,
        "aart-source.json",
        SnapshotEntryKind.FILE,
        canonical_json_bytes(source_manifest_to_json(source_manifest)),
    )
    if isinstance(source_written, Err):
        return source_written
    for candidate in plan.scan.artifacts:
        identity = candidate.identity
        artifact_type = cast(CanonicalArtifactType, identity.kind)
        base = f"artifacts/{identity.kind}/{identity.name}"
        setup = (
            None
            if candidate.setup_recipe is None
            else SetupReference(candidate.setup_recipe, candidate.setup_platforms)
        )
        manifest = ArtifactManifest(
            1,
            identity,
            options.value.artifact_version,
            candidate.summary,
            PayloadSpec(SafeRelativePath(("payload",)), PAYLOAD_FORMAT_BY_TYPE[artifact_type]),
            CompatibilitySpec(
                options.value.profiles if candidate.profiles is None else candidate.profiles,
                options.value.platforms,
            ),
            InstallSpec(
                cast(tuple[InstallScope, ...], options.value.scopes),
                cast(tuple[InstallMode, ...], options.value.modes),
                tuple(sorted(INSTALL_EFFECTS_BY_TYPE[artifact_type])),
            ),
            setup=setup,
            authors=(),
            license=options.value.license,
        )
        provenance = Provenance(
            1,
            candidate.provenance,
            ImporterProvenance(
                plan.scan.importer.id,
                plan.scan.importer.version,
                plan.options_digest,
            ),
            candidate.warnings,
            candidate.provenance_extensions,
        )
        for path, content in (
            (f"{base}/artifact.json", canonical_json_bytes(artifact_manifest_to_json(manifest))),
            (f"{base}/provenance.json", canonical_json_bytes(provenance_to_json(provenance))),
        ):
            written = _put(output, path, SnapshotEntryKind.FILE, content)
            if isinstance(written, Err):
                return written
        copied = _copy_payload(output, index, candidate, base)
        if isinstance(copied, Err):
            return copied
    for collection in plan.scan.collections:
        written = _put(
            output,
            f"collections/{collection.name}.json",
            SnapshotEntryKind.FILE,
            canonical_json_bytes(collection_manifest_to_json(collection)),
        )
        if isinstance(written, Err):
            return written
    snapshot = SourceSnapshot(SnapshotOrigin.LOCAL, tuple(output.values()))
    digest = source_snapshot_digest(snapshot)
    if isinstance(digest, Err):
        return _error(IMPORT_INVALID, "materialized canonical output cannot be hashed")
    return Ok(MaterializedImport(plan, snapshot, digest.value))


def validate_legacy_import(
    materialized: MaterializedImport,
    *,
    executable_version: SemVer,
) -> Result[ValidatedImport]:
    digest = source_snapshot_digest(materialized.snapshot)
    if isinstance(digest, Err) or digest.value != materialized.output_digest:
        return _error(IMPORT_INVALID, "materialized output digest does not match its exact tree")
    loaded = load_native_source(
        materialized.snapshot,
        executable_version=executable_version,
        available_capabilities=(),
    )
    if isinstance(loaded, Err):
        return loaded
    return Ok(ValidatedImport(materialized, loaded.value))


def _entry_value(entry: SnapshotEntry) -> tuple[SnapshotEntryKind, bool, bytes]:
    return (entry.kind, entry.executable, entry.content)


def diff_legacy_import(
    validated: ValidatedImport,
    destination: SourceSnapshot | None,
) -> Result[ImportDiff]:
    before_digest: ObjectDigest | None = None
    before: dict[str, SnapshotEntry] = {}
    if destination is not None:
        calculated = source_snapshot_digest(destination)
        if isinstance(calculated, Err):
            return _error(IMPORT_INVALID, "destination is not an inert canonical tree")
        before_digest = calculated.value
        before = {str(entry.path): entry for entry in destination.entries}
    after = {str(entry.path): entry for entry in validated.materialized.snapshot.entries}
    changes: list[ImportChange] = []
    for path in sorted(set(before) | set(after)):
        if path not in before:
            kind = ImportChangeKind.ADDED
        elif path not in after:
            kind = ImportChangeKind.REMOVED
        elif _entry_value(before[path]) == _entry_value(after[path]):
            kind = ImportChangeKind.UNCHANGED
        else:
            kind = ImportChangeKind.CHANGED
        parsed = _safe_path(path)
        if isinstance(parsed, Err):
            return parsed
        changes.append(ImportChange(parsed.value, kind))
    return Ok(ImportDiff(before_digest, validated.materialized.output_digest, tuple(changes)))


def build_import_apply_plan(
    validated: ValidatedImport,
    diff: ImportDiff,
) -> ImportApplyPlan:
    if diff.after_digest != validated.materialized.output_digest:
        raise ValueError("import diff does not describe the validated output")
    evidence = JsonObject(
        (
            (
                "changes",
                JsonArray(
                    tuple(
                        JsonObject((("kind", item.kind.value), ("path", str(item.path))))
                        for item in diff.changes
                    )
                ),
            ),
            (
                "expected_destination_digest",
                None if diff.before_digest is None else str(diff.before_digest),
            ),
            ("import_plan_digest", str(validated.materialized.plan.plan_digest)),
            ("output_digest", str(validated.materialized.output_digest)),
        )
    )
    return ImportApplyPlan(
        validated.materialized,
        diff.before_digest,
        diff.changes,
        json_digest(evidence),
    )
