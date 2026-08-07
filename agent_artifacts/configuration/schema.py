"""Strict schema-v1 parsing and canonical serialization for configuration."""

from __future__ import annotations

import posixpath
import re
from typing import Callable, TypeVar

from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import SourceAlias
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.protocol.capabilities import Capability, parse_capability
from agent_artifacts.protocol.json import (
    JsonArray,
    JsonObject,
    JsonValue,
    canonical_json_bytes,
    parse_json,
)
from agent_artifacts.protocol.schema import validate_object_fields

from .model import (
    TRUST_CLASSES,
    ConfiguredSource,
    OrganizationPolicy,
    ReportingMode,
    ReportingPolicy,
    ReportingSettings,
    SourceKind,
    SyncMode,
    SyncSettings,
    UserConfiguration,
    git_location_parts,
)

CONFIG_INVALID = DiagnosticCode("config-invalid")
POLICY_INVALID = DiagnosticCode("policy-invalid")
_ALIAS_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_HOST_RE = re.compile(r"^(?:[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?)$")
T = TypeVar("T")


def _error(code: DiagnosticCode, message: str) -> Err:
    return Err((Diagnostic(code, Severity.ERROR, message),))


def _document(data: bytes | str, code: DiagnosticCode) -> Result[JsonObject]:
    parsed = parse_json(data)
    if isinstance(parsed, Err):
        return parsed
    if not isinstance(parsed.value, JsonObject):
        return _error(code, "configuration document must be a JSON object")
    return Ok(parsed.value)


def _validated(
    value: JsonObject,
    code: DiagnosticCode,
    *,
    required: frozenset[str] = frozenset(),
    optional: frozenset[str] = frozenset(),
) -> Result[dict[str, JsonValue]]:
    result = validate_object_fields(value, required=required, optional=optional)
    if isinstance(result, Err):
        return result
    return Ok(dict(result.value.entries))


def _object(value: JsonValue, code: DiagnosticCode, label: str) -> Result[JsonObject]:
    if not isinstance(value, JsonObject):
        return _error(code, f"{label} must be an object")
    return Ok(value)


def _string(value: JsonValue, code: DiagnosticCode, label: str) -> Result[str]:
    if not isinstance(value, str) or not value or value != value.strip():
        return _error(code, f"{label} must be a non-empty string without outer whitespace")
    if "\n" in value or "\r" in value:
        return _error(code, f"{label} must be one line")
    return Ok(value)


def _boolean(value: JsonValue, code: DiagnosticCode, label: str) -> Result[bool]:
    if not isinstance(value, bool):
        return _error(code, f"{label} must be a boolean")
    return Ok(value)


def _integer(value: JsonValue, code: DiagnosticCode, label: str) -> Result[int]:
    if not isinstance(value, int) or isinstance(value, bool):
        return _error(code, f"{label} must be an integer")
    return Ok(value)


def _enum(
    value: JsonValue,
    enum_type: Callable[[str], T],
    code: DiagnosticCode,
    label: str,
) -> Result[T]:
    parsed = _string(value, code, label)
    if isinstance(parsed, Err):
        return parsed
    try:
        return Ok(enum_type(parsed.value))
    except ValueError:
        return _error(code, f"{label} has an unsupported value")


def _alias(value: JsonValue, code: DiagnosticCode, label: str) -> Result[SourceAlias]:
    parsed = _string(value, code, label)
    if isinstance(parsed, Err):
        return parsed
    if _ALIAS_RE.fullmatch(parsed.value) is None:
        return _error(code, f"{label} must be a lowercase slug")
    return Ok(SourceAlias(parsed.value))


def _alias_array(
    value: JsonValue, code: DiagnosticCode, label: str
) -> Result[tuple[SourceAlias, ...]]:
    if not isinstance(value, JsonArray):
        return _error(code, f"{label} must be an array")
    aliases: list[SourceAlias] = []
    for item in value.items:
        parsed = _alias(item, code, f"{label} item")
        if isinstance(parsed, Err):
            return parsed
        aliases.append(parsed.value)
    if len(set(aliases)) != len(aliases):
        return _error(code, f"{label} must not contain duplicate aliases")
    return Ok(tuple(sorted(aliases)))


def _safe_ref(raw: str) -> bool:
    components = raw.split("/")
    forbidden = ("..", "@{", "\\", "~", "^", ":", "?", "*", "[")
    return (
        raw != "@"
        and not raw.startswith(("-", "/"))
        and not raw.endswith(("/", "."))
        and "//" not in raw
        and not any(part.startswith(".") or part.endswith(".lock") for part in components)
        and not any(value in raw for value in forbidden)
        and not any(character.isspace() or ord(character) < 32 for character in raw)
    )


def _source(value: JsonValue) -> Result[ConfiguredSource]:
    object_result = _object(value, CONFIG_INVALID, "source")
    if isinstance(object_result, Err):
        return object_result
    base = dict(object_result.value.entries)
    kind_result = _enum(base.get("kind"), SourceKind, CONFIG_INVALID, "source kind")
    if isinstance(kind_result, Err):
        return kind_result
    local = kind_result.value is SourceKind.SOURCE_LOCAL
    fields = _validated(
        object_result.value,
        CONFIG_INVALID,
        required=frozenset({"alias", "kind", "path" if local else "url", "enabled"}),
        optional=frozenset() if local else frozenset({"ref"}),
    )
    if isinstance(fields, Err):
        return fields
    alias = _alias(fields.value["alias"], CONFIG_INVALID, "source alias")
    enabled = _boolean(fields.value["enabled"], CONFIG_INVALID, "source enabled")
    if isinstance(alias, Err):
        return alias
    if isinstance(enabled, Err):
        return enabled
    if local:
        location = _string(fields.value["path"], CONFIG_INVALID, "source path")
        if isinstance(location, Err):
            return location
        if (
            not posixpath.isabs(location.value)
            or posixpath.normpath(location.value) != location.value
        ):
            return _error(CONFIG_INVALID, "local source path must be normalized and absolute")
        return Ok(
            ConfiguredSource(alias.value, kind_result.value, location.value, None, enabled.value)
        )
    location = _string(fields.value["url"], CONFIG_INVALID, "source URL")
    ref = _string(fields.value.get("ref", "main"), CONFIG_INVALID, "source ref")
    if isinstance(location, Err):
        return location
    if isinstance(ref, Err):
        return ref
    if git_location_parts(location.value) is None:
        return _error(CONFIG_INVALID, "source URL must be a safe credential-free Git location")
    if not _safe_ref(ref.value):
        return _error(CONFIG_INVALID, "source ref is unsafe")
    return Ok(
        ConfiguredSource(alias.value, kind_result.value, location.value, ref.value, enabled.value)
    )


def _sources(value: JsonValue) -> Result[tuple[ConfiguredSource, ...]]:
    if not isinstance(value, JsonArray):
        return _error(CONFIG_INVALID, "sources must be an array")
    sources: list[ConfiguredSource] = []
    for item in value.items:
        result = _source(item)
        if isinstance(result, Err):
            return result
        sources.append(result.value)
    aliases = tuple(source.alias for source in sources)
    if len(set(aliases)) != len(aliases):
        return _error(CONFIG_INVALID, "source aliases must be unique")
    return Ok(tuple(sources))


def _sync(value: JsonValue) -> Result[SyncSettings]:
    object_result = _object(value, CONFIG_INVALID, "sync")
    if isinstance(object_result, Err):
        return object_result
    fields = _validated(
        object_result.value,
        CONFIG_INVALID,
        optional=frozenset({"mode", "max_age_seconds"}),
    )
    if isinstance(fields, Err):
        return fields
    mode = _enum(fields.value.get("mode", "auto"), SyncMode, CONFIG_INVALID, "sync mode")
    age = _integer(fields.value.get("max_age_seconds", 900), CONFIG_INVALID, "sync max age")
    if isinstance(mode, Err):
        return mode
    if isinstance(age, Err):
        return age
    try:
        return Ok(SyncSettings(mode.value, age.value))
    except ValueError as error:
        return _error(CONFIG_INVALID, str(error))


def _reporting(value: JsonValue) -> Result[ReportingSettings]:
    object_result = _object(value, CONFIG_INVALID, "reporting")
    if isinstance(object_result, Err):
        return object_result
    fields = _validated(
        object_result.value,
        CONFIG_INVALID,
        optional=frozenset({"mode", "destination"}),
    )
    if isinstance(fields, Err):
        return fields
    mode = _enum(
        fields.value.get("mode", "disabled"), ReportingMode, CONFIG_INVALID, "reporting mode"
    )
    if isinstance(mode, Err):
        return mode
    destination: SourceAlias | None = None
    if "destination" in fields.value:
        parsed = _alias(fields.value["destination"], CONFIG_INVALID, "reporting destination")
        if isinstance(parsed, Err):
            return parsed
        destination = parsed.value
    try:
        return Ok(ReportingSettings(mode.value, destination))
    except ValueError as error:
        return _error(CONFIG_INVALID, str(error))


def parse_user_configuration(data: bytes | str) -> Result[UserConfiguration]:
    document = _document(data, CONFIG_INVALID)
    if isinstance(document, Err):
        return document
    fields = _validated(
        document.value,
        CONFIG_INVALID,
        required=frozenset({"schema_version"}),
        optional=frozenset({"sources", "default_registry", "sync", "reporting"}),
    )
    if isinstance(fields, Err):
        return fields
    version = _integer(fields.value["schema_version"], CONFIG_INVALID, "schema_version")
    if isinstance(version, Err):
        return version
    if version.value != 1:
        return _error(CONFIG_INVALID, f"unsupported schema_version {version.value}")
    sources = _sources(fields.value.get("sources", JsonArray(())))
    sync = _sync(fields.value.get("sync", JsonObject(())))
    reporting = _reporting(fields.value.get("reporting", JsonObject(())))
    if isinstance(sources, Err):
        return sources
    if isinstance(sync, Err):
        return sync
    if isinstance(reporting, Err):
        return reporting
    default_registry: SourceAlias | None = None
    if "default_registry" in fields.value and fields.value["default_registry"] is not None:
        parsed_default = _alias(
            fields.value["default_registry"], CONFIG_INVALID, "default registry"
        )
        if isinstance(parsed_default, Err):
            return parsed_default
        default_registry = parsed_default.value
    by_alias = {source.alias: source for source in sources.value}
    if default_registry is not None:
        default_source = by_alias.get(default_registry)
        if default_source is None or not default_source.enabled or not default_source.is_registry:
            return _error(CONFIG_INVALID, "default registry must name an enabled registry source")
    if reporting.value.destination is not None:
        target = by_alias.get(reporting.value.destination)
        if target is None or not target.enabled or not target.is_registry:
            return _error(CONFIG_INVALID, "reporting destination must name an enabled registry")
    return Ok(UserConfiguration(1, sources.value, default_registry, sync.value, reporting.value))


def _source_json(source: ConfiguredSource) -> JsonObject:
    entries: list[tuple[str, JsonValue]] = [
        ("alias", source.alias.value),
        ("enabled", source.enabled),
        ("kind", source.kind.value),
    ]
    if source.kind is SourceKind.SOURCE_LOCAL:
        entries.append(("path", source.location))
    else:
        assert source.ref is not None
        entries.extend((("ref", source.ref), ("url", source.location)))
    return JsonObject(tuple(entries))


def user_configuration_bytes(configuration: UserConfiguration) -> bytes:
    reporting_entries: list[tuple[str, JsonValue]] = [("mode", configuration.reporting.mode.value)]
    if configuration.reporting.destination is not None:
        reporting_entries.append(("destination", configuration.reporting.destination.value))
    entries: list[tuple[str, JsonValue]] = [
        ("reporting", JsonObject(tuple(reporting_entries))),
        ("schema_version", 1),
        ("sources", JsonArray(tuple(_source_json(source) for source in configuration.sources))),
        (
            "sync",
            JsonObject(
                (
                    ("max_age_seconds", configuration.sync.max_age_seconds),
                    ("mode", configuration.sync.mode.value),
                )
            ),
        ),
    ]
    if configuration.default_registry is not None:
        entries.append(("default_registry", configuration.default_registry.value))
    return canonical_json_bytes(JsonObject(tuple(entries)))


def _optional_strings(
    fields: dict[str, JsonValue],
    name: str,
    validator: Callable[[str], bool],
) -> Result[tuple[str, ...] | None]:
    if name not in fields:
        return Ok(None)
    value = fields[name]
    if not isinstance(value, JsonArray):
        return _error(POLICY_INVALID, f"{name} must be an array")
    values: list[str] = []
    for item in value.items:
        parsed = _string(item, POLICY_INVALID, f"{name} item")
        if isinstance(parsed, Err):
            return parsed
        normalized = parsed.value.casefold() if name == "allowed_git_hosts" else parsed.value
        if not validator(normalized):
            return _error(POLICY_INVALID, f"{name} contains an unsafe value")
        values.append(normalized)
    return Ok(tuple(sorted(set(values))))


def _policy_reporting(value: JsonValue) -> Result[ReportingPolicy]:
    object_result = _object(value, POLICY_INVALID, "policy reporting")
    if isinstance(object_result, Err):
        return object_result
    fields = _validated(
        object_result.value,
        POLICY_INVALID,
        optional=frozenset({"mode", "destination", "deny_public_destinations"}),
    )
    if isinstance(fields, Err):
        return fields
    mode: ReportingMode | None = None
    destination: SourceAlias | None = None
    deny = False
    if "mode" in fields.value:
        parsed_mode = _enum(
            fields.value["mode"], ReportingMode, POLICY_INVALID, "policy reporting mode"
        )
        if isinstance(parsed_mode, Err):
            return parsed_mode
        mode = parsed_mode.value
    if "destination" in fields.value:
        parsed_destination = _alias(
            fields.value["destination"], POLICY_INVALID, "policy reporting destination"
        )
        if isinstance(parsed_destination, Err):
            return parsed_destination
        destination = parsed_destination.value
    if "deny_public_destinations" in fields.value:
        parsed_deny = _boolean(
            fields.value["deny_public_destinations"],
            POLICY_INVALID,
            "deny_public_destinations",
        )
        if isinstance(parsed_deny, Err):
            return parsed_deny
        deny = parsed_deny.value
    return Ok(ReportingPolicy(mode, destination, deny))


def parse_organization_policy(data: bytes | str) -> Result[OrganizationPolicy]:
    document = _document(data, POLICY_INVALID)
    if isinstance(document, Err):
        return document
    fields = _validated(
        document.value,
        POLICY_INVALID,
        required=frozenset({"schema_version"}),
        optional=frozenset(
            {
                "recommended_sources",
                "required_sources",
                "allowed_git_hosts",
                "allowed_repository_prefixes",
                "allow_direct_sources",
                "minimum_trust_for_user_scope",
                "allowed_setup_capabilities",
                "allow_custom_setup_entrypoints",
                "reporting",
            }
        ),
    )
    if isinstance(fields, Err):
        return fields
    version = _integer(fields.value["schema_version"], POLICY_INVALID, "schema_version")
    if isinstance(version, Err):
        return version
    if version.value != 1:
        return _error(POLICY_INVALID, f"unsupported schema_version {version.value}")
    recommended = _alias_array(
        fields.value.get("recommended_sources", JsonArray(())),
        POLICY_INVALID,
        "recommended_sources",
    )
    required = _alias_array(
        fields.value.get("required_sources", JsonArray(())), POLICY_INVALID, "required_sources"
    )
    hosts = _optional_strings(
        fields.value, "allowed_git_hosts", lambda raw: bool(_HOST_RE.fullmatch(raw))
    )
    prefixes = _optional_strings(
        fields.value,
        "allowed_repository_prefixes",
        lambda raw: (
            raw.endswith("/")
            and not raw.startswith("/")
            and posixpath.normpath(raw.removesuffix("/")) == raw.removesuffix("/")
            and all(part not in {"", ".", ".."} for part in raw.removesuffix("/").split("/"))
        ),
    )
    if isinstance(recommended, Err):
        return recommended
    if isinstance(required, Err):
        return required
    if isinstance(hosts, Err):
        return hosts
    if isinstance(prefixes, Err):
        return prefixes
    allow_direct: bool | None = None
    allow_custom: bool | None = None
    minimum_trust: str | None = None
    capabilities: tuple[Capability, ...] | None = None
    if "allow_direct_sources" in fields.value:
        parsed_direct = _boolean(
            fields.value["allow_direct_sources"], POLICY_INVALID, "allow_direct_sources"
        )
        if isinstance(parsed_direct, Err):
            return parsed_direct
        allow_direct = parsed_direct.value
    if "allow_custom_setup_entrypoints" in fields.value:
        parsed_custom = _boolean(
            fields.value["allow_custom_setup_entrypoints"],
            POLICY_INVALID,
            "allow_custom_setup_entrypoints",
        )
        if isinstance(parsed_custom, Err):
            return parsed_custom
        allow_custom = parsed_custom.value
    if "minimum_trust_for_user_scope" in fields.value:
        parsed_trust = _string(
            fields.value["minimum_trust_for_user_scope"],
            POLICY_INVALID,
            "minimum_trust_for_user_scope",
        )
        if isinstance(parsed_trust, Err):
            return parsed_trust
        if parsed_trust.value not in TRUST_CLASSES:
            return _error(POLICY_INVALID, "minimum trust value is unsupported")
        minimum_trust = parsed_trust.value
    if "allowed_setup_capabilities" in fields.value:
        raw_capabilities = fields.value["allowed_setup_capabilities"]
        if not isinstance(raw_capabilities, JsonArray):
            return _error(POLICY_INVALID, "allowed_setup_capabilities must be an array")
        parsed_capabilities: list[Capability] = []
        for item in raw_capabilities.items:
            raw = _string(item, POLICY_INVALID, "allowed setup capability")
            if isinstance(raw, Err):
                return raw
            parsed_capability = parse_capability(raw.value)
            if isinstance(parsed_capability, Err):
                return parsed_capability
            parsed_capabilities.append(parsed_capability.value)
        capabilities = tuple(sorted(set(parsed_capabilities)))
    reporting = _policy_reporting(fields.value.get("reporting", JsonObject(())))
    if isinstance(reporting, Err):
        return reporting
    try:
        return Ok(
            OrganizationPolicy(
                1,
                recommended.value,
                required.value,
                hosts.value,
                prefixes.value,
                allow_direct,
                minimum_trust,
                capabilities,
                allow_custom,
                reporting.value,
            )
        )
    except ValueError as error:
        return _error(POLICY_INVALID, str(error))


def organization_policy_bytes(policy: OrganizationPolicy) -> bytes:
    entries: list[tuple[str, JsonValue]] = [
        (
            "recommended_sources",
            JsonArray(tuple(item.value for item in policy.recommended_sources)),
        ),
        ("required_sources", JsonArray(tuple(item.value for item in policy.required_sources))),
        ("schema_version", 1),
    ]
    optional_arrays = (
        ("allowed_git_hosts", policy.allowed_git_hosts),
        ("allowed_repository_prefixes", policy.allowed_repository_prefixes),
        ("allowed_setup_capabilities", policy.allowed_setup_capabilities),
    )
    for name, values in optional_arrays:
        if values is not None:
            entries.append((name, JsonArray(tuple(str(item) for item in values))))
    for name, value in (
        ("allow_direct_sources", policy.allow_direct_sources),
        ("minimum_trust_for_user_scope", policy.minimum_trust_for_user_scope),
        ("allow_custom_setup_entrypoints", policy.allow_custom_setup_entrypoints),
    ):
        if value is not None:
            entries.append((name, value))
    reporting_entries: list[tuple[str, JsonValue]] = [
        ("deny_public_destinations", policy.reporting.deny_public_destinations)
    ]
    if policy.reporting.mode is not None:
        reporting_entries.append(("mode", policy.reporting.mode.value))
    if policy.reporting.destination is not None:
        reporting_entries.append(("destination", policy.reporting.destination.value))
    entries.append(("reporting", JsonObject(tuple(reporting_entries))))
    return canonical_json_bytes(JsonObject(tuple(entries)))
