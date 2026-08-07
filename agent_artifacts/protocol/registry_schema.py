"""Strict parsers and canonical projections for registry protocol v1 documents."""

from __future__ import annotations

import re
from typing import Iterable, cast

from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity, SourceLocation
from agent_artifacts.domain.identifiers import ArtifactIdentity, ObjectDigest, SourceId
from agent_artifacts.domain.result import Err, Ok, Result

from .capabilities import Capability, parse_capability
from .codes import (
    REGISTRY_ENTRY_INVALID,
    REGISTRY_INDEX_INVALID,
    REGISTRY_INVALID,
    REGISTRY_LOCK_INVALID,
)
from .hashing import parse_sha256
from .json import JsonArray, JsonObject, JsonValue, canonical_json_bytes, parse_json
from .native_models import (
    INSTALL_EFFECTS_BY_TYPE,
    PAYLOAD_FORMAT_BY_TYPE,
    CanonicalArtifactType,
    CollectionManifest,
    CompatibilitySpec,
    InstallEffect,
    InstallMode,
    InstallScope,
    InstallSpec,
)
from .native_schema import parse_collection_manifest
from .paths import parse_relative_path
from .registry_models import (
    GitArtifactReference,
    IndexArtifact,
    IndexProvenance,
    IndexSetup,
    LockedArtifact,
    RegistryEntry,
    RegistryIndex,
    RegistryLock,
    RegistryManifest,
    ReviewRecord,
    ReviewStatus,
    ServiceAdvertisement,
)
from .schema import validate_object_fields
from .semver import SemVer, VersionBounds, parse_semver, version_bounds

_SLUG_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_SERVICE_RE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SCP_GIT_RE = re.compile(r"^git@[A-Za-z0-9.-]+:[^\s?#]+$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_ARTIFACT_TYPES = frozenset(PAYLOAD_FORMAT_BY_TYPE)
_SCOPES = frozenset({"project", "user"})
_MODES = frozenset({"copy", "symlink"})
_EFFECTS = frozenset({"copy-tree", "write-file", "merge-json", "managed-block"})
_REVIEW_STATUSES = frozenset({"approved", "pending", "rejected"})


def _location(path: str, pointer: str | None = None) -> SourceLocation:
    return SourceLocation(path=path, pointer=pointer)


def _error(
    code: DiagnosticCode,
    message: str,
    *,
    path: str,
    pointer: str | None = None,
) -> Err:
    return Err((Diagnostic(code, Severity.ERROR, message, _location(path, pointer)),))


def _document(data: bytes | str, code: DiagnosticCode, *, path: str) -> Result[JsonObject]:
    parsed = parse_json(data, location=_location(path))
    if isinstance(parsed, Err):
        return parsed
    if not isinstance(parsed.value, JsonObject):
        return _error(code, "protocol document must be an object", path=path)
    return Ok(parsed.value)


def _object(value: JsonValue, code: DiagnosticCode, label: str, *, path: str) -> Result[JsonObject]:
    if isinstance(value, JsonObject):
        return Ok(value)
    return _error(code, f"{label} must be an object", path=path)


def _field(value: JsonObject, name: str) -> JsonValue:
    return dict(value.entries)[name]


def _extensions(value: JsonObject, known: frozenset[str]) -> tuple[tuple[str, JsonValue], ...]:
    return tuple((key, item) for key, item in value.entries if key not in known)


def _string(
    value: JsonValue,
    code: DiagnosticCode,
    label: str,
    *,
    path: str,
    single_line: bool = True,
) -> Result[str]:
    if not isinstance(value, str):
        return _error(code, f"{label} must be a string", path=path)
    if not value or value != value.strip():
        return _error(code, f"{label} must be non-empty without surrounding whitespace", path=path)
    if single_line and ("\n" in value or "\r" in value):
        return _error(code, f"{label} must be one line", path=path)
    return Ok(value)


def _integer(value: JsonValue, code: DiagnosticCode, label: str, *, path: str) -> Result[int]:
    if isinstance(value, int) and not isinstance(value, bool):
        return Ok(value)
    return _error(code, f"{label} must be an integer", path=path)


def _strings(
    value: JsonValue,
    code: DiagnosticCode,
    label: str,
    *,
    path: str,
    allow_empty: bool,
) -> Result[tuple[str, ...]]:
    if not isinstance(value, JsonArray):
        return _error(code, f"{label} must be an array", path=path)
    if not allow_empty and not value.items:
        return _error(code, f"{label} must not be empty", path=path)
    result: list[str] = []
    for item in value.items:
        parsed = _string(item, code, f"{label} item", path=path)
        if isinstance(parsed, Err):
            return parsed
        result.append(parsed.value)
    return Ok(tuple(sorted(set(result))))


def _schema_version(value: JsonObject, code: DiagnosticCode, *, path: str) -> Result[int]:
    parsed = _integer(_field(value, "schema_version"), code, "schema_version", path=path)
    if isinstance(parsed, Err):
        return parsed
    if parsed.value != 1:
        return _error(code, f"unsupported schema_version {parsed.value}", path=path)
    return parsed


def _bounds(value: JsonValue, code: DiagnosticCode, *, path: str) -> Result[VersionBounds]:
    object_result = _object(value, code, "version bounds", path=path)
    if isinstance(object_result, Err):
        return object_result
    validated = validate_object_fields(
        object_result.value,
        required=frozenset(),
        optional=frozenset({"min_inclusive", "max_exclusive"}),
        location=_location(path),
    )
    if isinstance(validated, Err):
        return validated
    values = dict(validated.value.entries)
    minimum: SemVer | None = None
    maximum: SemVer | None = None
    if "min_inclusive" in values:
        raw = _string(values["min_inclusive"], code, "min_inclusive", path=path)
        if isinstance(raw, Err):
            return raw
        parsed = parse_semver(raw.value, location=_location(path, "/min_inclusive"))
        if isinstance(parsed, Err):
            return parsed
        minimum = parsed.value
    if "max_exclusive" in values:
        raw = _string(values["max_exclusive"], code, "max_exclusive", path=path)
        if isinstance(raw, Err):
            return raw
        parsed = parse_semver(raw.value, location=_location(path, "/max_exclusive"))
        if isinstance(parsed, Err):
            return parsed
        maximum = parsed.value
    return version_bounds(minimum, maximum, location=_location(path))


def _slug(raw: str) -> bool:
    return _SLUG_RE.fullmatch(raw) is not None


def _safe_https_url(raw: str) -> bool:
    if not raw.startswith("https://"):
        return False
    authority = raw.removeprefix("https://").split("/", 1)[0]
    return (
        bool(authority)
        and "@" not in authority
        and "?" not in raw
        and "#" not in raw
        and not any(character.isspace() for character in raw)
    )


def _safe_git_url(raw: str) -> bool:
    return _SCP_GIT_RE.fullmatch(raw) is not None or _safe_https_url(raw)


def _safe_ref(raw: str) -> bool:
    forbidden = ("..", "@{", "\\", "~", "^", ":", "?", "*", "[")
    components = raw.split("/")
    return (
        bool(raw)
        and raw != "@"
        and not raw.startswith("-")
        and not raw.startswith("/")
        and not raw.endswith("/")
        and not raw.endswith(".")
        and "//" not in raw
        and not any(
            component.startswith(".") or component.endswith(".lock") for component in components
        )
        and not any(item in raw for item in forbidden)
        and not any(
            character.isspace() or ord(character) < 32 or ord(character) == 127 for character in raw
        )
    )


def _artifact_identity(
    raw_type: JsonValue, raw_name: JsonValue, *, path: str
) -> Result[ArtifactIdentity]:
    artifact_type = _string(raw_type, REGISTRY_ENTRY_INVALID, "type", path=path)
    name = _string(raw_name, REGISTRY_ENTRY_INVALID, "name", path=path)
    if isinstance(artifact_type, Err):
        return artifact_type
    if isinstance(name, Err):
        return name
    if artifact_type.value not in _ARTIFACT_TYPES or not _slug(name.value):
        return _error(REGISTRY_ENTRY_INVALID, "artifact identity is invalid", path=path)
    return Ok(ArtifactIdentity(artifact_type.value, name.value))


def _identity_key(raw: str, code: DiagnosticCode, *, path: str) -> Result[ArtifactIdentity]:
    parts = raw.split("/")
    if len(parts) != 2 or parts[0] not in _ARTIFACT_TYPES or not _slug(parts[1]):
        return _error(code, f"invalid artifact identity key: {raw!r}", path=path)
    return Ok(ArtifactIdentity(parts[0], parts[1]))


def _services(
    value: JsonValue, code: DiagnosticCode, *, path: str
) -> Result[tuple[ServiceAdvertisement, ...]]:
    parsed = _object(value, code, "services", path=path)
    if isinstance(parsed, Err):
        return parsed
    services: list[ServiceAdvertisement] = []
    for name, raw_service in parsed.value.entries:
        if _SERVICE_RE.fullmatch(name) is None:
            return _error(code, f"invalid service name: {name!r}", path=path)
        service_object = _object(raw_service, code, f"service {name}", path=path)
        if isinstance(service_object, Err):
            return service_object
        validated = validate_object_fields(
            service_object.value,
            required=frozenset({"kind"}),
            optional=frozenset({"repository"}),
            location=_location(path),
        )
        if isinstance(validated, Err):
            return validated
        kind = _string(_field(validated.value, "kind"), code, "service kind", path=path)
        if isinstance(kind, Err):
            return kind
        if not _slug(kind.value):
            return _error(code, "service kind must be a lowercase slug", path=path)
        repository: str | None = None
        if "repository" in validated.value.keys():
            raw_repository = _string(
                _field(validated.value, "repository"), code, "service repository", path=path
            )
            if isinstance(raw_repository, Err):
                return raw_repository
            if _REPOSITORY_RE.fullmatch(raw_repository.value) is None:
                return _error(
                    code, "service repository must be an owner/name coordinate", path=path
                )
            repository = raw_repository.value
        if kind.value == "github-issues" and repository is None:
            return _error(code, "github-issues service requires repository", path=path)
        services.append(ServiceAdvertisement(name, kind.value, repository))
    return Ok(tuple(sorted(services, key=lambda service: service.name)))


def _review(value: JsonValue, code: DiagnosticCode, *, path: str) -> Result[ReviewRecord]:
    parsed = _object(value, code, "review", path=path)
    if isinstance(parsed, Err):
        return parsed
    validated = validate_object_fields(
        parsed.value,
        required=frozenset({"status", "policy"}),
        location=_location(path),
    )
    if isinstance(validated, Err):
        return validated
    status = _string(_field(validated.value, "status"), code, "review.status", path=path)
    policy = _string(_field(validated.value, "policy"), code, "review.policy", path=path)
    if isinstance(status, Err):
        return status
    if isinstance(policy, Err):
        return policy
    if status.value not in _REVIEW_STATUSES or not _slug(policy.value):
        return _error(code, "review record is invalid", path=path)
    return Ok(ReviewRecord(cast(ReviewStatus, status.value), policy.value))


def parse_registry_manifest(
    data: bytes | str,
    *,
    path: str = "aart-registry.json",
) -> Result[RegistryManifest]:
    document = _document(data, REGISTRY_INVALID, path=path)
    if isinstance(document, Err):
        return document
    required = frozenset(
        {
            "schema_version",
            "protocol_version",
            "registry_id",
            "display_name",
            "requires_aart",
            "required_capabilities",
            "default_channel",
            "services",
        }
    )
    validated = validate_object_fields(
        document.value,
        required=required,
        allow_extensions=True,
        location=_location(path),
    )
    if isinstance(validated, Err):
        return validated
    value = validated.value
    schema = _schema_version(value, REGISTRY_INVALID, path=path)
    protocol = _integer(
        _field(value, "protocol_version"), REGISTRY_INVALID, "protocol_version", path=path
    )
    registry_id = _string(_field(value, "registry_id"), REGISTRY_INVALID, "registry_id", path=path)
    display_name = _string(
        _field(value, "display_name"), REGISTRY_INVALID, "display_name", path=path
    )
    bounds = _bounds(_field(value, "requires_aart"), REGISTRY_INVALID, path=path)
    capabilities = _strings(
        _field(value, "required_capabilities"),
        REGISTRY_INVALID,
        "required_capabilities",
        path=path,
        allow_empty=True,
    )
    channel = _string(
        _field(value, "default_channel"), REGISTRY_INVALID, "default_channel", path=path
    )
    services = _services(_field(value, "services"), REGISTRY_INVALID, path=path)
    for result in (
        schema,
        protocol,
        registry_id,
        display_name,
        bounds,
        capabilities,
        channel,
        services,
    ):
        if isinstance(result, Err):
            return result
    assert isinstance(schema, Ok)
    assert isinstance(protocol, Ok)
    assert isinstance(registry_id, Ok)
    assert isinstance(display_name, Ok)
    assert isinstance(bounds, Ok)
    assert isinstance(capabilities, Ok)
    assert isinstance(channel, Ok)
    assert isinstance(services, Ok)
    if protocol.value != 1:
        return _error(REGISTRY_INVALID, f"unsupported protocol_version {protocol.value}", path=path)
    if not _slug(registry_id.value):
        return _error(REGISTRY_INVALID, "registry_id must be a lowercase slug", path=path)
    if not _safe_ref(channel.value):
        return _error(REGISTRY_INVALID, "default_channel must be a safe Git ref", path=path)
    parsed_capabilities: list[Capability] = []
    for raw in capabilities.value:
        parsed = parse_capability(raw, location=_location(path))
        if isinstance(parsed, Err):
            return parsed
        parsed_capabilities.append(parsed.value)
    return Ok(
        RegistryManifest(
            schema.value,
            protocol.value,
            SourceId(registry_id.value),
            display_name.value,
            bounds.value,
            tuple(sorted(set(parsed_capabilities))),
            channel.value,
            services.value,
            _extensions(value, required),
        )
    )


def parse_registry_entry(
    data: bytes | str,
    *,
    path: str = "entry.json",
) -> Result[RegistryEntry]:
    document = _document(data, REGISTRY_ENTRY_INVALID, path=path)
    if isinstance(document, Err):
        return document
    validated = validate_object_fields(
        document.value,
        required=frozenset({"schema_version", "type", "name", "source", "review"}),
        allow_extensions=True,
        location=_location(path),
    )
    if isinstance(validated, Err):
        return validated
    value = validated.value
    schema = _schema_version(value, REGISTRY_ENTRY_INVALID, path=path)
    identity = _artifact_identity(_field(value, "type"), _field(value, "name"), path=path)
    source_object = _object(_field(value, "source"), REGISTRY_ENTRY_INVALID, "source", path=path)
    review = _review(_field(value, "review"), REGISTRY_ENTRY_INVALID, path=path)
    if isinstance(schema, Err):
        return schema
    if isinstance(identity, Err):
        return identity
    if isinstance(source_object, Err):
        return source_object
    if isinstance(review, Err):
        return review
    source_fields = validate_object_fields(
        source_object.value,
        required=frozenset({"kind", "url", "ref", "path"}),
        location=_location(path),
    )
    if isinstance(source_fields, Err):
        return source_fields
    kind = _string(
        _field(source_fields.value, "kind"), REGISTRY_ENTRY_INVALID, "source.kind", path=path
    )
    url = _string(
        _field(source_fields.value, "url"), REGISTRY_ENTRY_INVALID, "source.url", path=path
    )
    ref = _string(
        _field(source_fields.value, "ref"), REGISTRY_ENTRY_INVALID, "source.ref", path=path
    )
    raw_path = _string(
        _field(source_fields.value, "path"), REGISTRY_ENTRY_INVALID, "source.path", path=path
    )
    for result in (kind, url, ref, raw_path):
        if isinstance(result, Err):
            return result
    assert isinstance(kind, Ok)
    assert isinstance(url, Ok)
    assert isinstance(ref, Ok)
    assert isinstance(raw_path, Ok)
    if kind.value != "git" or not _safe_git_url(url.value):
        return _error(
            REGISTRY_ENTRY_INVALID,
            "entry source must be a credential-free Git URL",
            path=path,
        )
    if not _safe_ref(ref.value):
        return _error(REGISTRY_ENTRY_INVALID, "entry source ref is unsafe", path=path)
    parsed_path = parse_relative_path(raw_path.value, location=_location(path, "/source/path"))
    if isinstance(parsed_path, Err):
        return parsed_path
    if parsed_path.value.parts[-2:] != (identity.value.kind, identity.value.name):
        return _error(
            REGISTRY_ENTRY_INVALID,
            "entry source path must end with its artifact type/name identity",
            path=path,
        )
    return Ok(
        RegistryEntry(
            schema.value,
            identity.value,
            GitArtifactReference("git", url.value, ref.value, parsed_path.value),
            review.value,
            _extensions(
                value,
                frozenset({"schema_version", "type", "name", "source", "review"}),
            ),
        )
    )


def _digest(
    value: JsonValue, code: DiagnosticCode, label: str, *, path: str
) -> Result[ObjectDigest]:
    raw = _string(value, code, label, path=path)
    if isinstance(raw, Err):
        return raw
    parsed = parse_sha256(raw.value, location=_location(path))
    if isinstance(parsed, Err):
        return _error(code, f"{label} must be canonical SHA-256", path=path)
    return parsed


def _locked_artifact(
    identity: ArtifactIdentity,
    value: JsonValue,
    *,
    path: str,
) -> Result[LockedArtifact]:
    parsed = _object(value, REGISTRY_LOCK_INVALID, "locked entry", path=path)
    if isinstance(parsed, Err):
        return parsed
    required = frozenset(
        {
            "origin_url",
            "requested_ref",
            "resolved_commit",
            "path",
            "manifest_digest",
            "payload_digest",
            "object_digest",
            "artifact_version",
            "review",
        }
    )
    validated = validate_object_fields(
        parsed.value,
        required=required,
        optional=frozenset({"provenance_digest"}),
        location=_location(path),
    )
    if isinstance(validated, Err):
        return validated
    item = validated.value
    origin = _string(_field(item, "origin_url"), REGISTRY_LOCK_INVALID, "origin_url", path=path)
    requested_ref = _string(
        _field(item, "requested_ref"), REGISTRY_LOCK_INVALID, "requested_ref", path=path
    )
    commit = _string(
        _field(item, "resolved_commit"), REGISTRY_LOCK_INVALID, "resolved_commit", path=path
    )
    raw_path = _string(_field(item, "path"), REGISTRY_LOCK_INVALID, "path", path=path)
    manifest_digest = _digest(
        _field(item, "manifest_digest"), REGISTRY_LOCK_INVALID, "manifest_digest", path=path
    )
    payload_digest = _digest(
        _field(item, "payload_digest"), REGISTRY_LOCK_INVALID, "payload_digest", path=path
    )
    object_digest = _digest(
        _field(item, "object_digest"), REGISTRY_LOCK_INVALID, "object_digest", path=path
    )
    raw_version = _string(
        _field(item, "artifact_version"), REGISTRY_LOCK_INVALID, "artifact_version", path=path
    )
    review = _review(_field(item, "review"), REGISTRY_LOCK_INVALID, path=path)
    for result in (
        origin,
        requested_ref,
        commit,
        raw_path,
        manifest_digest,
        payload_digest,
        object_digest,
        raw_version,
        review,
    ):
        if isinstance(result, Err):
            return result
    assert isinstance(origin, Ok)
    assert isinstance(requested_ref, Ok)
    assert isinstance(commit, Ok)
    assert isinstance(raw_path, Ok)
    assert isinstance(manifest_digest, Ok)
    assert isinstance(payload_digest, Ok)
    assert isinstance(object_digest, Ok)
    assert isinstance(raw_version, Ok)
    assert isinstance(review, Ok)
    if not _safe_git_url(origin.value) or not _safe_ref(requested_ref.value):
        return _error(REGISTRY_LOCK_INVALID, "locked source is unsafe", path=path)
    if _COMMIT_RE.fullmatch(commit.value) is None:
        return _error(REGISTRY_LOCK_INVALID, "resolved_commit must be 40 lowercase hex", path=path)
    parsed_path = parse_relative_path(raw_path.value, location=_location(path))
    if isinstance(parsed_path, Err):
        return parsed_path
    if parsed_path.value.parts[-2:] != (identity.kind, identity.name):
        return _error(REGISTRY_LOCK_INVALID, "locked path identity mismatch", path=path)
    version = parse_semver(raw_version.value, location=_location(path))
    if isinstance(version, Err):
        return _error(REGISTRY_LOCK_INVALID, "artifact_version must be SemVer", path=path)
    provenance_digest: ObjectDigest | None = None
    if "provenance_digest" in item.keys():
        parsed_provenance = _digest(
            _field(item, "provenance_digest"),
            REGISTRY_LOCK_INVALID,
            "provenance_digest",
            path=path,
        )
        if isinstance(parsed_provenance, Err):
            return parsed_provenance
        provenance_digest = parsed_provenance.value
    return Ok(
        LockedArtifact(
            origin.value,
            requested_ref.value,
            commit.value,
            parsed_path.value,
            manifest_digest.value,
            payload_digest.value,
            object_digest.value,
            version.value,
            review.value,
            provenance_digest,
        )
    )


def parse_registry_lock(
    data: bytes | str,
    *,
    path: str = "aart.lock.json",
) -> Result[RegistryLock]:
    document = _document(data, REGISTRY_LOCK_INVALID, path=path)
    if isinstance(document, Err):
        return document
    validated = validate_object_fields(
        document.value,
        required=frozenset({"schema_version", "registry_inputs_digest", "entries"}),
        location=_location(path),
    )
    if isinstance(validated, Err):
        return validated
    value = validated.value
    schema = _schema_version(value, REGISTRY_LOCK_INVALID, path=path)
    inputs_digest = _digest(
        _field(value, "registry_inputs_digest"),
        REGISTRY_LOCK_INVALID,
        "registry_inputs_digest",
        path=path,
    )
    entries_object = _object(_field(value, "entries"), REGISTRY_LOCK_INVALID, "entries", path=path)
    if isinstance(schema, Err):
        return schema
    if isinstance(inputs_digest, Err):
        return inputs_digest
    if isinstance(entries_object, Err):
        return entries_object
    entries: list[tuple[ArtifactIdentity, LockedArtifact]] = []
    for raw_identity, raw_locked in entries_object.value.entries:
        identity = _identity_key(raw_identity, REGISTRY_LOCK_INVALID, path=path)
        if isinstance(identity, Err):
            return identity
        locked = _locked_artifact(identity.value, raw_locked, path=path)
        if isinstance(locked, Err):
            return locked
        entries.append((identity.value, locked.value))
    return Ok(
        RegistryLock(
            schema.value,
            inputs_digest.value,
            tuple(sorted(entries, key=lambda item: str(item[0]))),
        )
    )


def _named_values(
    value: JsonValue,
    label: str,
    allowed: frozenset[str] | None,
    *,
    path: str,
    allow_empty: bool = False,
) -> Result[tuple[str, ...]]:
    parsed = _strings(
        value,
        REGISTRY_INDEX_INVALID,
        label,
        path=path,
        allow_empty=allow_empty,
    )
    if isinstance(parsed, Err):
        return parsed
    if any(
        not _slug(item) or (allowed is not None and item not in allowed) for item in parsed.value
    ):
        return _error(REGISTRY_INDEX_INVALID, f"{label} contains an unsupported value", path=path)
    return parsed


def _index_setup(value: JsonValue, *, path: str) -> Result[IndexSetup | None]:
    if value is None:
        return Ok(None)
    parsed = _object(value, REGISTRY_INDEX_INVALID, "setup", path=path)
    if isinstance(parsed, Err):
        return parsed
    validated = validate_object_fields(
        parsed.value,
        required=frozenset({"recipe", "platforms", "capabilities"}),
        location=_location(path),
    )
    if isinstance(validated, Err):
        return validated
    recipe_raw = _string(
        _field(validated.value, "recipe"), REGISTRY_INDEX_INVALID, "setup.recipe", path=path
    )
    platforms = _named_values(
        _field(validated.value, "platforms"), "setup platforms", None, path=path
    )
    capability_names = _strings(
        _field(validated.value, "capabilities"),
        REGISTRY_INDEX_INVALID,
        "setup capabilities",
        path=path,
        allow_empty=True,
    )
    if isinstance(recipe_raw, Err):
        return recipe_raw
    if isinstance(platforms, Err):
        return platforms
    if isinstance(capability_names, Err):
        return capability_names
    recipe = parse_relative_path(recipe_raw.value, location=_location(path))
    if isinstance(recipe, Err) or recipe.value.parts[0] != "setup":
        return _error(REGISTRY_INDEX_INVALID, "setup recipe must be below setup/", path=path)
    capabilities: list[Capability] = []
    for raw in capability_names.value:
        parsed_capability = parse_capability(raw, location=_location(path))
        if isinstance(parsed_capability, Err):
            return parsed_capability
        capabilities.append(parsed_capability.value)
    return Ok(IndexSetup(recipe.value, platforms.value, tuple(sorted(set(capabilities)))))


def _index_provenance(value: JsonValue, *, path: str) -> Result[IndexProvenance | None]:
    if value is None:
        return Ok(None)
    parsed = _object(value, REGISTRY_INDEX_INVALID, "provenance", path=path)
    if isinstance(parsed, Err):
        return parsed
    validated = validate_object_fields(
        parsed.value,
        required=frozenset({"origin_url", "resolved_commit", "path"}),
        location=_location(path),
    )
    if isinstance(validated, Err):
        return validated
    url = _string(
        _field(validated.value, "origin_url"), REGISTRY_INDEX_INVALID, "origin_url", path=path
    )
    commit = _string(
        _field(validated.value, "resolved_commit"),
        REGISTRY_INDEX_INVALID,
        "resolved_commit",
        path=path,
    )
    raw_path = _string(
        _field(validated.value, "path"), REGISTRY_INDEX_INVALID, "provenance.path", path=path
    )
    if isinstance(url, Err):
        return url
    if isinstance(commit, Err):
        return commit
    if isinstance(raw_path, Err):
        return raw_path
    if not _safe_git_url(url.value) or _COMMIT_RE.fullmatch(commit.value) is None:
        return _error(
            REGISTRY_INDEX_INVALID, "provenance must identify pinned Git content", path=path
        )
    parsed_path = parse_relative_path(raw_path.value, location=_location(path))
    if isinstance(parsed_path, Err):
        return parsed_path
    return Ok(IndexProvenance(url.value, commit.value, parsed_path.value))


def _index_artifact(value: JsonValue, *, path: str) -> Result[IndexArtifact]:
    parsed = _object(value, REGISTRY_INDEX_INVALID, "index artifact", path=path)
    if isinstance(parsed, Err):
        return parsed
    required = frozenset(
        {
            "source_id",
            "type",
            "name",
            "version",
            "summary",
            "manifest_digest",
            "payload_digest",
            "object_digest",
            "compatibility",
            "install",
            "setup",
            "review",
            "provenance",
            "collections",
        }
    )
    validated = validate_object_fields(parsed.value, required=required, location=_location(path))
    if isinstance(validated, Err):
        return validated
    item = validated.value
    source_id = _string(_field(item, "source_id"), REGISTRY_INDEX_INVALID, "source_id", path=path)
    identity = _artifact_identity(_field(item, "type"), _field(item, "name"), path=path)
    raw_version = _string(_field(item, "version"), REGISTRY_INDEX_INVALID, "version", path=path)
    summary = _string(_field(item, "summary"), REGISTRY_INDEX_INVALID, "summary", path=path)
    manifest_digest = _digest(
        _field(item, "manifest_digest"), REGISTRY_INDEX_INVALID, "manifest_digest", path=path
    )
    payload_digest = _digest(
        _field(item, "payload_digest"), REGISTRY_INDEX_INVALID, "payload_digest", path=path
    )
    object_digest = _digest(
        _field(item, "object_digest"), REGISTRY_INDEX_INVALID, "object_digest", path=path
    )
    for result in (
        source_id,
        identity,
        raw_version,
        summary,
        manifest_digest,
        payload_digest,
        object_digest,
    ):
        if isinstance(result, Err):
            return result
    assert isinstance(source_id, Ok)
    assert isinstance(identity, Ok)
    assert isinstance(raw_version, Ok)
    assert isinstance(summary, Ok)
    assert isinstance(manifest_digest, Ok)
    assert isinstance(payload_digest, Ok)
    assert isinstance(object_digest, Ok)
    if not _slug(source_id.value):
        return _error(REGISTRY_INDEX_INVALID, "source_id must be a lowercase slug", path=path)
    version = parse_semver(raw_version.value, location=_location(path))
    if isinstance(version, Err):
        return version
    compatibility_object = _object(
        _field(item, "compatibility"), REGISTRY_INDEX_INVALID, "compatibility", path=path
    )
    install_object = _object(_field(item, "install"), REGISTRY_INDEX_INVALID, "install", path=path)
    if isinstance(compatibility_object, Err):
        return compatibility_object
    if isinstance(install_object, Err):
        return install_object
    compatibility_fields = validate_object_fields(
        compatibility_object.value,
        required=frozenset({"profiles", "platforms"}),
        location=_location(path),
    )
    install_fields = validate_object_fields(
        install_object.value,
        required=frozenset({"scopes", "modes", "effects"}),
        location=_location(path),
    )
    if isinstance(compatibility_fields, Err):
        return compatibility_fields
    if isinstance(install_fields, Err):
        return install_fields
    profiles = _named_values(
        _field(compatibility_fields.value, "profiles"), "profiles", None, path=path
    )
    platforms = _named_values(
        _field(compatibility_fields.value, "platforms"), "platforms", None, path=path
    )
    scopes = _named_values(_field(install_fields.value, "scopes"), "scopes", _SCOPES, path=path)
    modes = _named_values(_field(install_fields.value, "modes"), "modes", _MODES, path=path)
    effects = _named_values(_field(install_fields.value, "effects"), "effects", _EFFECTS, path=path)
    for named_result in (profiles, platforms, scopes, modes, effects):
        if isinstance(named_result, Err):
            return named_result
    assert isinstance(profiles, Ok)
    assert isinstance(platforms, Ok)
    assert isinstance(scopes, Ok)
    assert isinstance(modes, Ok)
    assert isinstance(effects, Ok)
    artifact_type = cast(CanonicalArtifactType, identity.value.kind)
    if not set(effects.value) <= INSTALL_EFFECTS_BY_TYPE[artifact_type]:
        return _error(REGISTRY_INDEX_INVALID, "index install effects are incompatible", path=path)
    setup = _index_setup(_field(item, "setup"), path=path)
    provenance = _index_provenance(_field(item, "provenance"), path=path)
    collections = _named_values(
        _field(item, "collections"), "collections", None, path=path, allow_empty=True
    )
    if isinstance(setup, Err):
        return setup
    if isinstance(provenance, Err):
        return provenance
    if isinstance(collections, Err):
        return collections
    review: ReviewRecord | None = None
    if _field(item, "review") is not None:
        parsed_review = _review(_field(item, "review"), REGISTRY_INDEX_INVALID, path=path)
        if isinstance(parsed_review, Err):
            return parsed_review
        review = parsed_review.value
    return Ok(
        IndexArtifact(
            SourceId(source_id.value),
            identity.value,
            version.value,
            summary.value,
            manifest_digest.value,
            payload_digest.value,
            object_digest.value,
            CompatibilitySpec(profiles.value, platforms.value),
            InstallSpec(
                cast(tuple[InstallScope, ...], scopes.value),
                cast(tuple[InstallMode, ...], modes.value),
                cast(tuple[InstallEffect, ...], effects.value),
            ),
            setup.value,
            review,
            provenance.value,
            collections.value,
        )
    )


def _index_collection(value: JsonValue, *, path: str) -> Result[CollectionManifest]:
    parsed = _object(value, REGISTRY_INDEX_INVALID, "index collection", path=path)
    if isinstance(parsed, Err):
        return parsed
    if "schema_version" in parsed.value.keys():
        return _error(
            REGISTRY_INDEX_INVALID,
            "compiled collection must not repeat schema_version",
            path=path,
        )
    with_schema = JsonObject((("schema_version", 1), *parsed.value.entries))
    result = parse_collection_manifest(canonical_json_bytes(with_schema), path=path)
    if isinstance(result, Err):
        return _error(REGISTRY_INDEX_INVALID, "compiled collection is invalid", path=path)
    return result


def parse_registry_index(
    data: bytes | str,
    *,
    path: str = "aart.index.json",
) -> Result[RegistryIndex]:
    document = _document(data, REGISTRY_INDEX_INVALID, path=path)
    if isinstance(document, Err):
        return document
    required = frozenset(
        {
            "schema_version",
            "protocol_version",
            "registry_id",
            "registry_inputs_digest",
            "artifacts",
            "collections",
            "services",
        }
    )
    validated = validate_object_fields(document.value, required=required, location=_location(path))
    if isinstance(validated, Err):
        return validated
    value = validated.value
    schema = _schema_version(value, REGISTRY_INDEX_INVALID, path=path)
    protocol = _integer(
        _field(value, "protocol_version"), REGISTRY_INDEX_INVALID, "protocol_version", path=path
    )
    registry_id = _string(
        _field(value, "registry_id"), REGISTRY_INDEX_INVALID, "registry_id", path=path
    )
    inputs_digest = _digest(
        _field(value, "registry_inputs_digest"),
        REGISTRY_INDEX_INVALID,
        "registry_inputs_digest",
        path=path,
    )
    services = _services(_field(value, "services"), REGISTRY_INDEX_INVALID, path=path)
    for result in (schema, protocol, registry_id, inputs_digest, services):
        if isinstance(result, Err):
            return result
    assert isinstance(schema, Ok)
    assert isinstance(protocol, Ok)
    assert isinstance(registry_id, Ok)
    assert isinstance(inputs_digest, Ok)
    assert isinstance(services, Ok)
    if protocol.value != 1 or not _slug(registry_id.value):
        return _error(REGISTRY_INDEX_INVALID, "compiled index header is invalid", path=path)
    raw_artifacts = _field(value, "artifacts")
    raw_collections = _field(value, "collections")
    if not isinstance(raw_artifacts, JsonArray) or not isinstance(raw_collections, JsonArray):
        return _error(
            REGISTRY_INDEX_INVALID, "index artifacts/collections must be arrays", path=path
        )
    artifacts: list[IndexArtifact] = []
    for raw_artifact in raw_artifacts.items:
        parsed_artifact = _index_artifact(raw_artifact, path=path)
        if isinstance(parsed_artifact, Err):
            return parsed_artifact
        artifacts.append(parsed_artifact.value)
    collections: list[CollectionManifest] = []
    for raw_collection in raw_collections.items:
        parsed_collection = _index_collection(raw_collection, path=path)
        if isinstance(parsed_collection, Err):
            return parsed_collection
        collections.append(parsed_collection.value)
    artifact_keys = tuple((str(item.source_id), str(item.identity)) for item in artifacts)
    collection_names = tuple(item.name for item in collections)
    if len(set(artifact_keys)) != len(artifact_keys) or len(set(collection_names)) != len(
        collection_names
    ):
        return _error(
            REGISTRY_INDEX_INVALID, "compiled index contains duplicate identities", path=path
        )
    from .registry_index import validate_registry_graph

    graph = validate_registry_graph(tuple(artifacts), tuple(collections))
    if isinstance(graph, Err):
        return graph
    if graph.value != tuple(
        sorted(artifacts, key=lambda item: (str(item.source_id), str(item.identity)))
    ):
        return _error(
            REGISTRY_INDEX_INVALID,
            "compiled index collection memberships do not match its graph",
            path=path,
        )
    return Ok(
        RegistryIndex(
            schema.value,
            protocol.value,
            SourceId(registry_id.value),
            inputs_digest.value,
            tuple(sorted(artifacts, key=lambda item: (str(item.source_id), str(item.identity)))),
            tuple(sorted(collections, key=lambda item: item.name)),
            services.value,
        )
    )


def _json_object(entries: Iterable[tuple[str, JsonValue]]) -> JsonObject:
    return JsonObject(tuple(entries))


def _json_array(values: Iterable[JsonValue]) -> JsonArray:
    return JsonArray(tuple(values))


def _string_array(values: Iterable[object]) -> JsonArray:
    return _json_array(str(value) for value in values)


def _bounds_json(bounds: VersionBounds) -> JsonObject:
    entries: list[tuple[str, JsonValue]] = []
    if bounds.min_inclusive is not None:
        entries.append(("min_inclusive", str(bounds.min_inclusive)))
    if bounds.max_exclusive is not None:
        entries.append(("max_exclusive", str(bounds.max_exclusive)))
    return _json_object(entries)


def _services_json(services: Iterable[ServiceAdvertisement]) -> JsonObject:
    entries: list[tuple[str, JsonValue]] = []
    for service in services:
        service_entries: list[tuple[str, JsonValue]] = [("kind", service.kind)]
        if service.repository is not None:
            service_entries.append(("repository", service.repository))
        entries.append((service.name, _json_object(service_entries)))
    return _json_object(entries)


def _review_json(review: ReviewRecord) -> JsonObject:
    return _json_object((("status", review.status), ("policy", review.policy)))


def registry_manifest_to_json(manifest: RegistryManifest) -> JsonObject:
    entries: list[tuple[str, JsonValue]] = [
        ("schema_version", manifest.schema_version),
        ("protocol_version", manifest.protocol_version),
        ("registry_id", str(manifest.registry_id)),
        ("display_name", manifest.display_name),
        ("requires_aart", _bounds_json(manifest.requires_aart)),
        ("required_capabilities", _string_array(manifest.required_capabilities)),
        ("default_channel", manifest.default_channel),
        ("services", _services_json(manifest.services)),
    ]
    entries.extend(manifest.extensions)
    return _json_object(entries)


def registry_entry_to_json(entry: RegistryEntry) -> JsonObject:
    entries: list[tuple[str, JsonValue]] = [
        ("schema_version", entry.schema_version),
        ("type", entry.identity.kind),
        ("name", entry.identity.name),
        (
            "source",
            _json_object(
                (
                    ("kind", entry.source.kind),
                    ("url", entry.source.url),
                    ("ref", entry.source.ref),
                    ("path", str(entry.source.path)),
                )
            ),
        ),
        ("review", _review_json(entry.review)),
    ]
    entries.extend(entry.extensions)
    return _json_object(entries)


def registry_lock_to_json(lock: RegistryLock) -> JsonObject:
    entries: list[tuple[str, JsonValue]] = []
    for identity, item in lock.entries:
        locked_entries: list[tuple[str, JsonValue]] = [
            ("origin_url", item.origin_url),
            ("requested_ref", item.requested_ref),
            ("resolved_commit", item.resolved_commit),
            ("path", str(item.path)),
            ("manifest_digest", str(item.manifest_digest)),
            ("payload_digest", str(item.payload_digest)),
            ("object_digest", str(item.object_digest)),
            ("artifact_version", str(item.artifact_version)),
            ("review", _review_json(item.review)),
        ]
        if item.provenance_digest is not None:
            locked_entries.append(("provenance_digest", str(item.provenance_digest)))
        entries.append((str(identity), _json_object(locked_entries)))
    return _json_object(
        (
            ("schema_version", lock.schema_version),
            ("registry_inputs_digest", str(lock.registry_inputs_digest)),
            ("entries", _json_object(entries)),
        )
    )


def _collection_json(collection: CollectionManifest) -> JsonObject:
    artifact_values: list[JsonValue] = []
    for selector in collection.artifacts:
        selector_entries: list[tuple[str, JsonValue]] = [
            ("type", selector.identity.kind),
            ("name", selector.identity.name),
        ]
        if selector.version is not None:
            selector_entries.append(("version", _bounds_json(selector.version)))
        artifact_values.append(_json_object(selector_entries))
    entries: list[tuple[str, JsonValue]] = [
        ("name", collection.name),
        ("summary", collection.summary),
        ("artifacts", _json_array(artifact_values)),
        ("collections", _string_array(collection.collections)),
    ]
    entries.extend(collection.extensions)
    return _json_object(entries)


def _index_artifact_json(artifact: IndexArtifact) -> JsonObject:
    setup: JsonValue = None
    if artifact.setup is not None:
        setup = _json_object(
            (
                ("recipe", str(artifact.setup.recipe)),
                ("platforms", _string_array(artifact.setup.platforms)),
                ("capabilities", _string_array(artifact.setup.capabilities)),
            )
        )
    review: JsonValue = None if artifact.review is None else _review_json(artifact.review)
    provenance: JsonValue = None
    if artifact.provenance is not None:
        provenance = _json_object(
            (
                ("origin_url", artifact.provenance.origin_url),
                ("resolved_commit", artifact.provenance.resolved_commit),
                ("path", str(artifact.provenance.path)),
            )
        )
    return _json_object(
        (
            ("source_id", str(artifact.source_id)),
            ("type", artifact.identity.kind),
            ("name", artifact.identity.name),
            ("version", str(artifact.version)),
            ("summary", artifact.summary),
            ("manifest_digest", str(artifact.manifest_digest)),
            ("payload_digest", str(artifact.payload_digest)),
            ("object_digest", str(artifact.object_digest)),
            (
                "compatibility",
                _json_object(
                    (
                        ("profiles", _string_array(artifact.compatibility.profiles)),
                        ("platforms", _string_array(artifact.compatibility.platforms)),
                    )
                ),
            ),
            (
                "install",
                _json_object(
                    (
                        ("scopes", _string_array(artifact.install.scopes)),
                        ("modes", _string_array(artifact.install.modes)),
                        ("effects", _string_array(artifact.install.effects)),
                    )
                ),
            ),
            ("setup", setup),
            ("review", review),
            ("provenance", provenance),
            ("collections", _string_array(artifact.collections)),
        )
    )


def registry_index_to_json(index: RegistryIndex) -> JsonObject:
    return _json_object(
        (
            ("schema_version", index.schema_version),
            ("protocol_version", index.protocol_version),
            ("registry_id", str(index.registry_id)),
            ("registry_inputs_digest", str(index.registry_inputs_digest)),
            ("artifacts", _json_array(_index_artifact_json(item) for item in index.artifacts)),
            ("collections", _json_array(_collection_json(item) for item in index.collections)),
            ("services", _services_json(index.services)),
        )
    )
