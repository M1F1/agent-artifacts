"""Strict parsers and canonical projections for native source protocol v1."""

from __future__ import annotations

import re
from typing import Iterable, cast

from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity, SourceLocation
from agent_artifacts.domain.identifiers import ArtifactIdentity, SourceId
from agent_artifacts.domain.result import Err, Ok, Result

from .capabilities import Capability, parse_capability
from .codes import ARTIFACT_INVALID, COLLECTION_INVALID, PROVENANCE_INVALID, SOURCE_INVALID
from .hashing import parse_sha256
from .json import JsonArray, JsonObject, JsonValue, parse_json
from .native_models import (
    INSTALL_EFFECTS_BY_TYPE,
    PAYLOAD_FORMAT_BY_TYPE,
    ArtifactManifest,
    ArtifactSelector,
    CanonicalArtifactType,
    CollectionManifest,
    CompatibilitySpec,
    ImporterProvenance,
    InstallEffect,
    InstallMode,
    InstallScope,
    InstallSpec,
    OriginProvenance,
    PayloadSpec,
    Provenance,
    SetupReference,
    SourceManifest,
)
from .paths import SafeRelativePath, parse_relative_path
from .schema import validate_object_fields
from .semver import SemVer, VersionBounds, parse_semver, version_bounds

_SLUG_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_SCP_GIT_RE = re.compile(r"^git@[A-Za-z0-9.-]+:[^\s?#]+$")
_ARTIFACT_TYPES = frozenset(PAYLOAD_FORMAT_BY_TYPE)
_SCOPES = frozenset({"project", "user"})
_MODES = frozenset({"copy", "symlink"})
_EFFECTS = frozenset({"copy-tree", "write-file", "merge-json", "managed-block"})


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


def _as_object(
    value: JsonValue, code: DiagnosticCode, label: str, *, path: str
) -> Result[JsonObject]:
    if isinstance(value, JsonObject):
        return Ok(value)
    return _error(code, f"{label} must be an object", path=path)


def _document(data: bytes | str, code: DiagnosticCode, *, path: str) -> Result[JsonObject]:
    parsed = parse_json(data, location=_location(path))
    if isinstance(parsed, Err):
        return parsed
    return _as_object(parsed.value, code, "protocol document", path=path)


def _field(value: JsonObject, name: str) -> JsonValue:
    return dict(value.entries)[name]


def _string(
    value: JsonValue,
    code: DiagnosticCode,
    label: str,
    *,
    path: str,
    single_line: bool = False,
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
    allow_empty: bool = False,
) -> Result[tuple[str, ...]]:
    if not isinstance(value, JsonArray):
        return _error(code, f"{label} must be an array", path=path)
    if not allow_empty and not value.items:
        return _error(code, f"{label} must not be empty", path=path)
    items: list[str] = []
    for item in value.items:
        parsed = _string(item, code, f"{label} item", path=path, single_line=True)
        if isinstance(parsed, Err):
            return parsed
        items.append(parsed.value)
    return Ok(tuple(sorted(set(items))))


def _version_bounds(
    value: JsonValue,
    code: DiagnosticCode = SOURCE_INVALID,
    *,
    path: str,
) -> Result[VersionBounds]:
    object_result = _as_object(value, code, "version bounds", path=path)
    if isinstance(object_result, Err):
        return object_result
    fields = validate_object_fields(
        object_result.value,
        required=frozenset(),
        optional=frozenset({"min_inclusive", "max_exclusive"}),
        location=_location(path),
    )
    if isinstance(fields, Err):
        return fields
    values = dict(fields.value.entries)
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


def _paths(
    value: JsonValue,
    code: DiagnosticCode,
    label: str,
    *,
    path: str,
    allow_empty: bool,
) -> Result[tuple[SafeRelativePath, ...]]:
    raw_items = _strings(value, code, label, path=path, allow_empty=allow_empty)
    if isinstance(raw_items, Err):
        return raw_items
    parsed_items: list[SafeRelativePath] = []
    for raw in raw_items.value:
        parsed = parse_relative_path(raw, location=_location(path))
        if isinstance(parsed, Err):
            return parsed
        parsed_items.append(parsed.value)
    return Ok(tuple(sorted(set(parsed_items))))


def _extensions(value: JsonObject, known: frozenset[str]) -> tuple[tuple[str, JsonValue], ...]:
    return tuple((key, item) for key, item in value.entries if key not in known)


def _check_schema_version(value: JsonObject, code: DiagnosticCode, *, path: str) -> Result[int]:
    parsed = _integer(_field(value, "schema_version"), code, "schema_version", path=path)
    if isinstance(parsed, Err):
        return parsed
    if parsed.value != 1:
        return _error(code, f"unsupported schema_version {parsed.value}", path=path)
    return parsed


def parse_source_manifest(
    data: bytes | str,
    *,
    path: str = "aart-source.json",
) -> Result[SourceManifest]:
    document = _document(data, SOURCE_INVALID, path=path)
    if isinstance(document, Err):
        return document
    required = frozenset(
        {
            "schema_version",
            "protocol_version",
            "source_id",
            "display_name",
            "requires_aart",
            "required_capabilities",
            "artifact_roots",
        }
    )
    optional = frozenset({"collection_roots"})
    validated = validate_object_fields(
        document.value,
        required=required,
        optional=optional,
        allow_extensions=True,
        location=_location(path),
    )
    if isinstance(validated, Err):
        return validated
    value = validated.value
    schema_version = _check_schema_version(value, SOURCE_INVALID, path=path)
    if isinstance(schema_version, Err):
        return schema_version
    protocol_version = _integer(
        _field(value, "protocol_version"), SOURCE_INVALID, "protocol_version", path=path
    )
    if isinstance(protocol_version, Err):
        return protocol_version
    if protocol_version.value != 1:
        return _error(
            SOURCE_INVALID,
            f"unsupported protocol_version {protocol_version.value}",
            path=path,
        )
    source_id = _string(_field(value, "source_id"), SOURCE_INVALID, "source_id", path=path)
    if isinstance(source_id, Err):
        return source_id
    if _SLUG_RE.fullmatch(source_id.value) is None:
        return _error(SOURCE_INVALID, "source_id must be a lowercase slug", path=path)
    display_name = _string(
        _field(value, "display_name"),
        SOURCE_INVALID,
        "display_name",
        path=path,
        single_line=True,
    )
    if isinstance(display_name, Err):
        return display_name
    bounds = _version_bounds(_field(value, "requires_aart"), path=path)
    if isinstance(bounds, Err):
        return bounds
    capability_names = _strings(
        _field(value, "required_capabilities"),
        SOURCE_INVALID,
        "required_capabilities",
        path=path,
        allow_empty=True,
    )
    if isinstance(capability_names, Err):
        return capability_names
    capabilities: list[Capability] = []
    for raw in capability_names.value:
        parsed = parse_capability(raw, location=_location(path))
        if isinstance(parsed, Err):
            return parsed
        capabilities.append(parsed.value)
    artifact_roots = _paths(
        _field(value, "artifact_roots"),
        SOURCE_INVALID,
        "artifact_roots",
        path=path,
        allow_empty=False,
    )
    if isinstance(artifact_roots, Err):
        return artifact_roots
    collection_roots: Result[tuple[SafeRelativePath, ...]] = Ok(())
    if "collection_roots" in value.keys():
        collection_roots = _paths(
            _field(value, "collection_roots"),
            SOURCE_INVALID,
            "collection_roots",
            path=path,
            allow_empty=True,
        )
    if isinstance(collection_roots, Err):
        return collection_roots
    if set(artifact_roots.value) & set(collection_roots.value):
        return _error(SOURCE_INVALID, "artifact and collection roots must not overlap", path=path)
    all_roots = (*artifact_roots.value, *collection_roots.value)
    for index, root in enumerate(all_roots):
        for other in all_roots[index + 1 :]:
            shorter, longer = sorted((root.parts, other.parts), key=len)
            if longer[: len(shorter)] == shorter:
                return _error(SOURCE_INVALID, "source roots must not be nested", path=path)
    known = required | optional
    return Ok(
        SourceManifest(
            schema_version.value,
            protocol_version.value,
            SourceId(source_id.value),
            display_name.value,
            bounds.value,
            tuple(sorted(set(capabilities))),
            artifact_roots.value,
            collection_roots.value,
            _extensions(value, known),
        )
    )


def _parse_named_values(
    value: JsonValue,
    code: DiagnosticCode,
    label: str,
    allowed: frozenset[str] | None,
    *,
    path: str,
    allow_empty: bool = False,
) -> Result[tuple[str, ...]]:
    parsed = _strings(value, code, label, path=path, allow_empty=allow_empty)
    if isinstance(parsed, Err):
        return parsed
    for item in parsed.value:
        if _SLUG_RE.fullmatch(item) is None or (allowed is not None and item not in allowed):
            return _error(code, f"unsupported {label} value {item!r}", path=path)
    return parsed


def _payload(
    value: JsonValue, artifact_type: CanonicalArtifactType, *, path: str
) -> Result[PayloadSpec]:
    parsed_object = _as_object(value, ARTIFACT_INVALID, "payload", path=path)
    if isinstance(parsed_object, Err):
        return parsed_object
    validated = validate_object_fields(
        parsed_object.value,
        required=frozenset({"root", "format"}),
        location=_location(path),
    )
    if isinstance(validated, Err):
        return validated
    root_raw = _string(_field(validated.value, "root"), ARTIFACT_INVALID, "payload.root", path=path)
    if isinstance(root_raw, Err):
        return root_raw
    root = parse_relative_path(root_raw.value, location=_location(path, "/payload/root"))
    if isinstance(root, Err):
        return root
    if str(root.value) != "payload":
        return _error(ARTIFACT_INVALID, "payload.root must be 'payload' in protocol v1", path=path)
    payload_format = _string(
        _field(validated.value, "format"), ARTIFACT_INVALID, "payload.format", path=path
    )
    if isinstance(payload_format, Err):
        return payload_format
    expected = PAYLOAD_FORMAT_BY_TYPE[artifact_type]
    if payload_format.value != expected:
        return _error(
            ARTIFACT_INVALID,
            f"{artifact_type} requires payload format {expected!r}",
            path=path,
        )
    return Ok(PayloadSpec(root.value, payload_format.value))


def _compatibility(value: JsonValue, *, path: str) -> Result[CompatibilitySpec]:
    parsed_object = _as_object(value, ARTIFACT_INVALID, "compatibility", path=path)
    if isinstance(parsed_object, Err):
        return parsed_object
    validated = validate_object_fields(
        parsed_object.value,
        required=frozenset({"profiles", "platforms"}),
        location=_location(path),
    )
    if isinstance(validated, Err):
        return validated
    profiles = _parse_named_values(
        _field(validated.value, "profiles"), ARTIFACT_INVALID, "profile", None, path=path
    )
    if isinstance(profiles, Err):
        return profiles
    platforms = _parse_named_values(
        _field(validated.value, "platforms"), ARTIFACT_INVALID, "platform", None, path=path
    )
    if isinstance(platforms, Err):
        return platforms
    return Ok(CompatibilitySpec(profiles.value, platforms.value))


def _install(value: JsonValue, *, path: str) -> Result[InstallSpec]:
    parsed_object = _as_object(value, ARTIFACT_INVALID, "install", path=path)
    if isinstance(parsed_object, Err):
        return parsed_object
    validated = validate_object_fields(
        parsed_object.value,
        required=frozenset({"scopes", "modes", "effects"}),
        location=_location(path),
    )
    if isinstance(validated, Err):
        return validated
    scopes = _parse_named_values(
        _field(validated.value, "scopes"), ARTIFACT_INVALID, "scope", _SCOPES, path=path
    )
    if isinstance(scopes, Err):
        return scopes
    modes = _parse_named_values(
        _field(validated.value, "modes"), ARTIFACT_INVALID, "mode", _MODES, path=path
    )
    if isinstance(modes, Err):
        return modes
    effects = _parse_named_values(
        _field(validated.value, "effects"), ARTIFACT_INVALID, "effect", _EFFECTS, path=path
    )
    if isinstance(effects, Err):
        return effects
    return Ok(
        InstallSpec(
            cast(tuple[InstallScope, ...], scopes.value),
            cast(tuple[InstallMode, ...], modes.value),
            cast(tuple[InstallEffect, ...], effects.value),
        )
    )


def _setup(
    value: JsonValue, compatibility: CompatibilitySpec, *, path: str
) -> Result[SetupReference]:
    parsed_object = _as_object(value, ARTIFACT_INVALID, "setup", path=path)
    if isinstance(parsed_object, Err):
        return parsed_object
    validated = validate_object_fields(
        parsed_object.value,
        required=frozenset({"recipe", "platforms"}),
        location=_location(path),
    )
    if isinstance(validated, Err):
        return validated
    recipe_raw = _string(
        _field(validated.value, "recipe"), ARTIFACT_INVALID, "setup.recipe", path=path
    )
    if isinstance(recipe_raw, Err):
        return recipe_raw
    recipe = parse_relative_path(recipe_raw.value, location=_location(path, "/setup/recipe"))
    if isinstance(recipe, Err):
        return recipe
    if recipe.value.parts[0] != "setup":
        return _error(ARTIFACT_INVALID, "setup recipe must be below setup/", path=path)
    platforms = _parse_named_values(
        _field(validated.value, "platforms"), ARTIFACT_INVALID, "setup platform", None, path=path
    )
    if isinstance(platforms, Err):
        return platforms
    if not set(platforms.value) <= set(compatibility.platforms):
        return _error(
            ARTIFACT_INVALID,
            "setup platforms must be a subset of artifact platforms",
            path=path,
        )
    return Ok(SetupReference(recipe.value, platforms.value))


def parse_artifact_manifest(
    data: bytes | str,
    *,
    path: str = "artifact.json",
) -> Result[ArtifactManifest]:
    document = _document(data, ARTIFACT_INVALID, path=path)
    if isinstance(document, Err):
        return document
    required = frozenset(
        {
            "schema_version",
            "type",
            "name",
            "version",
            "summary",
            "payload",
            "compatibility",
            "install",
        }
    )
    optional = frozenset({"setup", "authors", "license", "homepage", "requires_aart", "requires"})
    validated = validate_object_fields(
        document.value,
        required=required,
        optional=optional,
        allow_extensions=True,
        location=_location(path),
    )
    if isinstance(validated, Err):
        return validated
    value = validated.value
    schema_version = _check_schema_version(value, ARTIFACT_INVALID, path=path)
    if isinstance(schema_version, Err):
        return schema_version
    raw_type = _string(_field(value, "type"), ARTIFACT_INVALID, "type", path=path)
    if isinstance(raw_type, Err):
        return raw_type
    if raw_type.value not in _ARTIFACT_TYPES:
        return _error(ARTIFACT_INVALID, f"unsupported artifact type {raw_type.value!r}", path=path)
    artifact_type = raw_type.value
    name = _string(_field(value, "name"), ARTIFACT_INVALID, "name", path=path)
    if isinstance(name, Err):
        return name
    if _SLUG_RE.fullmatch(name.value) is None:
        return _error(ARTIFACT_INVALID, "artifact name must be a lowercase slug", path=path)
    raw_version = _string(_field(value, "version"), ARTIFACT_INVALID, "version", path=path)
    if isinstance(raw_version, Err):
        return raw_version
    parsed_version = parse_semver(raw_version.value, location=_location(path, "/version"))
    if isinstance(parsed_version, Err):
        return parsed_version
    summary = _string(
        _field(value, "summary"), ARTIFACT_INVALID, "summary", path=path, single_line=True
    )
    if isinstance(summary, Err):
        return summary
    payload = _payload(_field(value, "payload"), artifact_type, path=path)
    if isinstance(payload, Err):
        return payload
    compatibility = _compatibility(_field(value, "compatibility"), path=path)
    if isinstance(compatibility, Err):
        return compatibility
    install = _install(_field(value, "install"), path=path)
    if isinstance(install, Err):
        return install
    if not set(install.value.effects) <= INSTALL_EFFECTS_BY_TYPE[artifact_type]:
        return _error(
            ARTIFACT_INVALID,
            f"install effects are incompatible with artifact type {artifact_type!r}",
            path=path,
        )
    requires_aart = VersionBounds()
    if "requires_aart" in value.keys():
        parsed_bounds = _version_bounds(
            _field(value, "requires_aart"),
            ARTIFACT_INVALID,
            path=path,
        )
        if isinstance(parsed_bounds, Err):
            return parsed_bounds
        requires_aart = parsed_bounds.value
    requires: tuple[ArtifactSelector, ...] = ()
    if "requires" in value.keys():
        raw_requires = _field(value, "requires")
        if not isinstance(raw_requires, JsonArray):
            return _error(ARTIFACT_INVALID, "requires must be an array", path=path)
        parsed_requires: list[ArtifactSelector] = []
        for item in raw_requires.items:
            parsed_selector = _artifact_selector(item, path=path)
            if isinstance(parsed_selector, Err):
                return parsed_selector
            if parsed_selector.value.identity == ArtifactIdentity(artifact_type, name.value):
                return _error(ARTIFACT_INVALID, "artifact must not require itself", path=path)
            parsed_requires.append(parsed_selector.value)
        identities = tuple(item.identity for item in parsed_requires)
        if len(set(identities)) != len(identities):
            return _error(
                ARTIFACT_INVALID, "requires contains duplicate artifact selectors", path=path
            )
        requires = tuple(sorted(parsed_requires, key=lambda item: str(item.identity)))
    setup: SetupReference | None = None
    if "setup" in value.keys():
        parsed_setup = _setup(_field(value, "setup"), compatibility.value, path=path)
        if isinstance(parsed_setup, Err):
            return parsed_setup
        setup = parsed_setup.value
    authors: tuple[str, ...] = ()
    if "authors" in value.keys():
        parsed_authors = _strings(
            _field(value, "authors"), ARTIFACT_INVALID, "authors", path=path, allow_empty=True
        )
        if isinstance(parsed_authors, Err):
            return parsed_authors
        authors = parsed_authors.value
    license_value: str | None = None
    if "license" in value.keys():
        parsed_license = _string(
            _field(value, "license"), ARTIFACT_INVALID, "license", path=path, single_line=True
        )
        if isinstance(parsed_license, Err):
            return parsed_license
        license_value = parsed_license.value
    homepage: str | None = None
    if "homepage" in value.keys():
        parsed_homepage = _string(
            _field(value, "homepage"), ARTIFACT_INVALID, "homepage", path=path
        )
        if isinstance(parsed_homepage, Err):
            return parsed_homepage
        if not _safe_https_url(parsed_homepage.value):
            return _error(ARTIFACT_INVALID, "homepage must use credential-free HTTPS", path=path)
        homepage = parsed_homepage.value
    return Ok(
        ArtifactManifest(
            schema_version.value,
            ArtifactIdentity(artifact_type, name.value),
            parsed_version.value,
            summary.value,
            payload.value,
            compatibility.value,
            install.value,
            setup,
            authors,
            license_value,
            homepage,
            _extensions(value, required | optional),
            requires_aart,
            requires,
        )
    )


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


def parse_provenance(
    data: bytes | str,
    *,
    path: str = "provenance.json",
) -> Result[Provenance]:
    document = _document(data, PROVENANCE_INVALID, path=path)
    if isinstance(document, Err):
        return document
    required = frozenset({"schema_version", "origin", "importer", "warnings"})
    validated = validate_object_fields(
        document.value,
        required=required,
        allow_extensions=True,
        location=_location(path),
    )
    if isinstance(validated, Err):
        return validated
    value = validated.value
    schema_version = _check_schema_version(value, PROVENANCE_INVALID, path=path)
    if isinstance(schema_version, Err):
        return schema_version
    origin_object = _as_object(_field(value, "origin"), PROVENANCE_INVALID, "origin", path=path)
    if isinstance(origin_object, Err):
        return origin_object
    origin_fields = validate_object_fields(
        origin_object.value,
        required=frozenset({"kind", "url", "resolved_commit", "path", "input_digest"}),
        location=_location(path),
    )
    if isinstance(origin_fields, Err):
        return origin_fields
    origin = origin_fields.value
    kind = _string(_field(origin, "kind"), PROVENANCE_INVALID, "origin.kind", path=path)
    url = _string(_field(origin, "url"), PROVENANCE_INVALID, "origin.url", path=path)
    commit = _string(
        _field(origin, "resolved_commit"), PROVENANCE_INVALID, "resolved_commit", path=path
    )
    origin_path_raw = _string(_field(origin, "path"), PROVENANCE_INVALID, "origin.path", path=path)
    if isinstance(kind, Err):
        return kind
    if isinstance(url, Err):
        return url
    if isinstance(commit, Err):
        return commit
    if isinstance(origin_path_raw, Err):
        return origin_path_raw
    if (
        kind.value != "git"
        or not _safe_git_url(url.value)
        or _COMMIT_RE.fullmatch(commit.value) is None
    ):
        return _error(
            PROVENANCE_INVALID, "origin must be a pinned credential-free Git source", path=path
        )
    origin_path = parse_relative_path(
        origin_path_raw.value, location=_location(path, "/origin/path")
    )
    if isinstance(origin_path, Err):
        return _error(PROVENANCE_INVALID, "origin.path must be a safe relative path", path=path)
    input_digest_raw = _string(
        _field(origin, "input_digest"), PROVENANCE_INVALID, "input_digest", path=path
    )
    if isinstance(input_digest_raw, Err):
        return input_digest_raw
    input_digest = parse_sha256(input_digest_raw.value, location=_location(path))
    if isinstance(input_digest, Err):
        return _error(PROVENANCE_INVALID, "input_digest must be canonical SHA-256", path=path)

    importer_object = _as_object(
        _field(value, "importer"), PROVENANCE_INVALID, "importer", path=path
    )
    if isinstance(importer_object, Err):
        return importer_object
    importer_fields = validate_object_fields(
        importer_object.value,
        required=frozenset({"id", "version", "options_digest"}),
        location=_location(path),
    )
    if isinstance(importer_fields, Err):
        return importer_fields
    importer = importer_fields.value
    importer_id = _string(_field(importer, "id"), PROVENANCE_INVALID, "importer.id", path=path)
    importer_version_raw = _string(
        _field(importer, "version"), PROVENANCE_INVALID, "importer.version", path=path
    )
    options_digest_raw = _string(
        _field(importer, "options_digest"), PROVENANCE_INVALID, "options_digest", path=path
    )
    if isinstance(importer_id, Err):
        return importer_id
    if isinstance(importer_version_raw, Err):
        return importer_version_raw
    if isinstance(options_digest_raw, Err):
        return options_digest_raw
    if _SLUG_RE.fullmatch(importer_id.value) is None:
        return _error(PROVENANCE_INVALID, "importer.id must be a lowercase slug", path=path)
    importer_version = parse_semver(importer_version_raw.value, location=_location(path))
    if isinstance(importer_version, Err):
        return _error(PROVENANCE_INVALID, "importer.version must be SemVer", path=path)
    options_digest = parse_sha256(options_digest_raw.value, location=_location(path))
    if isinstance(options_digest, Err):
        return _error(PROVENANCE_INVALID, "options_digest must be canonical SHA-256", path=path)
    warnings = _strings(
        _field(value, "warnings"),
        PROVENANCE_INVALID,
        "warnings",
        path=path,
        allow_empty=True,
    )
    if isinstance(warnings, Err):
        return warnings
    return Ok(
        Provenance(
            schema_version.value,
            OriginProvenance("git", url.value, commit.value, origin_path.value, input_digest.value),
            ImporterProvenance(importer_id.value, importer_version.value, options_digest.value),
            warnings.value,
            _extensions(value, required),
        )
    )


def _artifact_selector(value: JsonValue, *, path: str) -> Result[ArtifactSelector]:
    parsed_object = _as_object(value, COLLECTION_INVALID, "artifact selector", path=path)
    if isinstance(parsed_object, Err):
        return parsed_object
    validated = validate_object_fields(
        parsed_object.value,
        required=frozenset({"type", "name"}),
        optional=frozenset({"version"}),
        location=_location(path),
    )
    if isinstance(validated, Err):
        return validated
    raw_type = _string(_field(validated.value, "type"), COLLECTION_INVALID, "type", path=path)
    name = _string(_field(validated.value, "name"), COLLECTION_INVALID, "name", path=path)
    if isinstance(raw_type, Err):
        return raw_type
    if isinstance(name, Err):
        return name
    if raw_type.value not in _ARTIFACT_TYPES or _SLUG_RE.fullmatch(name.value) is None:
        return _error(COLLECTION_INVALID, "selector identity is invalid", path=path)
    bounds: VersionBounds | None = None
    if "version" in validated.value.keys():
        parsed_bounds = _version_bounds(
            _field(validated.value, "version"), COLLECTION_INVALID, path=path
        )
        if isinstance(parsed_bounds, Err):
            return parsed_bounds
        bounds = parsed_bounds.value
    return Ok(
        ArtifactSelector(
            ArtifactIdentity(raw_type.value, name.value),
            bounds,
        )
    )


def parse_collection_manifest(
    data: bytes | str,
    *,
    path: str = "collection.json",
) -> Result[CollectionManifest]:
    document = _document(data, COLLECTION_INVALID, path=path)
    if isinstance(document, Err):
        return document
    required = frozenset({"schema_version", "name", "summary", "artifacts"})
    optional = frozenset({"collections"})
    validated = validate_object_fields(
        document.value,
        required=required,
        optional=optional,
        allow_extensions=True,
        location=_location(path),
    )
    if isinstance(validated, Err):
        return validated
    value = validated.value
    schema_version = _check_schema_version(value, COLLECTION_INVALID, path=path)
    if isinstance(schema_version, Err):
        return schema_version
    name = _string(_field(value, "name"), COLLECTION_INVALID, "name", path=path)
    summary = _string(
        _field(value, "summary"), COLLECTION_INVALID, "summary", path=path, single_line=True
    )
    if isinstance(name, Err):
        return name
    if isinstance(summary, Err):
        return summary
    if _SLUG_RE.fullmatch(name.value) is None:
        return _error(COLLECTION_INVALID, "collection name must be a lowercase slug", path=path)
    raw_artifacts = _field(value, "artifacts")
    if not isinstance(raw_artifacts, JsonArray):
        return _error(COLLECTION_INVALID, "artifacts must be an array", path=path)
    artifacts: list[ArtifactSelector] = []
    for item in raw_artifacts.items:
        parsed = _artifact_selector(item, path=path)
        if isinstance(parsed, Err):
            return parsed
        artifacts.append(parsed.value)
    identities = tuple(str(item.identity) for item in artifacts)
    if len(set(identities)) != len(identities):
        return _error(
            COLLECTION_INVALID, "collection contains duplicate artifact selectors", path=path
        )
    collections: tuple[str, ...] = ()
    if "collections" in value.keys():
        parsed_collections = _parse_named_values(
            _field(value, "collections"),
            COLLECTION_INVALID,
            "collection",
            None,
            path=path,
            allow_empty=True,
        )
        if isinstance(parsed_collections, Err):
            return parsed_collections
        collections = parsed_collections.value
    if name.value in collections:
        return _error(
            COLLECTION_INVALID, "collection must not directly reference itself", path=path
        )
    if not artifacts and not collections:
        return _error(COLLECTION_INVALID, "collection must contain at least one member", path=path)
    return Ok(
        CollectionManifest(
            schema_version.value,
            name.value,
            summary.value,
            tuple(sorted(artifacts, key=lambda item: str(item.identity))),
            collections,
            _extensions(value, required | optional),
        )
    )


def _object(entries: Iterable[tuple[str, JsonValue]]) -> JsonObject:
    return JsonObject(tuple(entries))


def _array(values: Iterable[str]) -> JsonArray:
    return JsonArray(tuple(values))


def _bounds_to_json(bounds: VersionBounds) -> JsonObject:
    entries: list[tuple[str, JsonValue]] = []
    if bounds.min_inclusive is not None:
        entries.append(("min_inclusive", str(bounds.min_inclusive)))
    if bounds.max_exclusive is not None:
        entries.append(("max_exclusive", str(bounds.max_exclusive)))
    return _object(entries)


def source_manifest_to_json(manifest: SourceManifest) -> JsonObject:
    entries: list[tuple[str, JsonValue]] = [
        ("schema_version", manifest.schema_version),
        ("protocol_version", manifest.protocol_version),
        ("source_id", str(manifest.source_id)),
        ("display_name", manifest.display_name),
        ("requires_aart", _bounds_to_json(manifest.requires_aart)),
        ("required_capabilities", _array(str(item) for item in manifest.required_capabilities)),
        ("artifact_roots", _array(str(item) for item in manifest.artifact_roots)),
    ]
    if manifest.collection_roots:
        entries.append(
            ("collection_roots", _array(str(item) for item in manifest.collection_roots))
        )
    entries.extend(manifest.extensions)
    return _object(entries)


def artifact_manifest_to_json(manifest: ArtifactManifest) -> JsonObject:
    entries: list[tuple[str, JsonValue]] = [
        ("schema_version", manifest.schema_version),
        ("type", manifest.identity.kind),
        ("name", manifest.identity.name),
        ("version", str(manifest.version)),
        ("summary", manifest.summary),
        (
            "payload",
            _object((("root", str(manifest.payload.root)), ("format", manifest.payload.format))),
        ),
        (
            "compatibility",
            _object(
                (
                    ("profiles", _array(manifest.compatibility.profiles)),
                    ("platforms", _array(manifest.compatibility.platforms)),
                )
            ),
        ),
        (
            "install",
            _object(
                (
                    ("scopes", _array(manifest.install.scopes)),
                    ("modes", _array(manifest.install.modes)),
                    ("effects", _array(manifest.install.effects)),
                )
            ),
        ),
    ]
    if manifest.setup is not None:
        entries.append(
            (
                "setup",
                _object(
                    (
                        ("recipe", str(manifest.setup.recipe)),
                        ("platforms", _array(manifest.setup.platforms)),
                    )
                ),
            )
        )
    if manifest.authors:
        entries.append(("authors", _array(manifest.authors)))
    if manifest.license is not None:
        entries.append(("license", manifest.license))
    if manifest.homepage is not None:
        entries.append(("homepage", manifest.homepage))
    if (
        manifest.requires_aart.min_inclusive is not None
        or manifest.requires_aart.max_exclusive is not None
    ):
        entries.append(("requires_aart", _bounds_to_json(manifest.requires_aart)))
    if manifest.requires:
        values: list[JsonObject] = []
        for selector in manifest.requires:
            selector_entries: list[tuple[str, JsonValue]] = [
                ("type", selector.identity.kind),
                ("name", selector.identity.name),
            ]
            if selector.version is not None:
                selector_entries.append(("version", _bounds_to_json(selector.version)))
            values.append(_object(selector_entries))
        entries.append(("requires", JsonArray(tuple(values))))
    entries.extend(manifest.extensions)
    return _object(entries)


def provenance_to_json(provenance: Provenance) -> JsonObject:
    entries: list[tuple[str, JsonValue]] = [
        (
            "importer",
            _object(
                (
                    ("id", provenance.importer.id),
                    ("options_digest", str(provenance.importer.options_digest)),
                    ("version", str(provenance.importer.version)),
                )
            ),
        ),
        (
            "origin",
            _object(
                (
                    ("input_digest", str(provenance.origin.input_digest)),
                    ("kind", provenance.origin.kind),
                    ("path", str(provenance.origin.path)),
                    ("resolved_commit", provenance.origin.resolved_commit),
                    ("url", provenance.origin.url),
                )
            ),
        ),
        ("schema_version", provenance.schema_version),
        ("warnings", _array(provenance.warnings)),
    ]
    entries.extend(provenance.extensions)
    return _object(entries)


def collection_manifest_to_json(manifest: CollectionManifest) -> JsonObject:
    artifacts: list[JsonValue] = []
    for selector in manifest.artifacts:
        selector_entries: list[tuple[str, JsonValue]] = [
            ("name", selector.identity.name),
            ("type", selector.identity.kind),
        ]
        if selector.version is not None:
            selector_entries.append(("version", _bounds_to_json(selector.version)))
        artifacts.append(_object(selector_entries))
    entries: list[tuple[str, JsonValue]] = [
        ("artifacts", JsonArray(tuple(artifacts))),
        ("name", manifest.name),
        ("schema_version", manifest.schema_version),
        ("summary", manifest.summary),
    ]
    if manifest.collections:
        entries.append(("collections", _array(manifest.collections)))
    entries.extend(manifest.extensions)
    return _object(entries)
