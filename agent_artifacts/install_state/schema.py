"""Strict canonical parser/writer for installation manifest schema v2."""

from __future__ import annotations

from agent_artifacts.configuration.model import SourceKind
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity, SourceLocation
from agent_artifacts.domain.identifiers import (
    ArtifactCoordinate,
    ArtifactIdentity,
    ObjectDigest,
    SourceAlias,
    SourceId,
)
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.protocol.hashing import parse_sha256
from agent_artifacts.protocol.json import (
    JsonArray,
    JsonObject,
    JsonValue,
    canonical_json_bytes,
    parse_json,
)
from agent_artifacts.protocol.schema import validate_object_fields
from agent_artifacts.protocol.semver import parse_semver

from .model import (
    ArtifactEvidence,
    EffectProof,
    InstallationRecord,
    InstallState,
    SourceEvidence,
)

STATE_INVALID = DiagnosticCode("install-state-invalid")


def _location(path: str, pointer: str | None = None) -> SourceLocation:
    return SourceLocation(path=path, pointer=pointer)


def _error(message: str, *, path: str, pointer: str | None = None) -> Err:
    return Err((Diagnostic(STATE_INVALID, Severity.ERROR, message, _location(path, pointer)),))


def _as_install_state_invalid(result: Err) -> Err:
    """Keep parser failures in the installation-state diagnostic family.

    The underlying JSON and protocol validators still provide the bounded message and precise
    location.  Their generic codes are not the public contract of this state parser.
    """

    return Err(
        tuple(
            Diagnostic(
                STATE_INVALID,
                diagnostic.severity,
                diagnostic.message,
                diagnostic.location,
                remediation=diagnostic.remediation,
                details=diagnostic.details,
            )
            for diagnostic in result.diagnostics
        )
    )


def _object(
    value: JsonValue,
    *,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
    path: str,
    pointer: str,
) -> Result[dict[str, JsonValue]]:
    if not isinstance(value, JsonObject):
        return _error("installation state value must be an object", path=path, pointer=pointer)
    fields = validate_object_fields(
        value,
        required=required,
        optional=optional,
        location=_location(path, pointer),
    )
    return fields if isinstance(fields, Err) else Ok(dict(fields.value.entries))


def _string(value: JsonValue, label: str, *, path: str, pointer: str) -> Result[str]:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\r" in value
        or "\n" in value
    ):
        return _error(f"{label} must be a non-empty single-line string", path=path, pointer=pointer)
    return Ok(value)


def _integer(value: JsonValue, label: str, *, path: str, pointer: str) -> Result[int]:
    if not isinstance(value, int) or isinstance(value, bool):
        return _error(f"{label} must be an integer", path=path, pointer=pointer)
    return Ok(value)


def _boolean(value: JsonValue, label: str, *, path: str, pointer: str) -> Result[bool]:
    if not isinstance(value, bool):
        return _error(f"{label} must be a boolean", path=path, pointer=pointer)
    return Ok(value)


def _digest(value: JsonValue, label: str, *, path: str, pointer: str) -> Result[ObjectDigest]:
    raw = _string(value, label, path=path, pointer=pointer)
    if isinstance(raw, Err):
        return raw
    parsed = parse_sha256(raw.value, location=_location(path, pointer))
    return parsed if isinstance(parsed, Err) else Ok(parsed.value)


def _source(value: JsonValue, *, path: str, pointer: str) -> Result[SourceEvidence]:
    fields = _object(
        value,
        required=frozenset({"alias", "declared_id", "kind", "origin", "resolved_commit"}),
        optional=frozenset({"subscription_ref"}),
        path=path,
        pointer=pointer,
    )
    if isinstance(fields, Err):
        return fields
    values: dict[str, str] = {}
    for name in ("alias", "declared_id", "kind", "origin", "resolved_commit"):
        item = _string(fields.value[name], f"source.{name}", path=path, pointer=f"{pointer}/{name}")
        if isinstance(item, Err):
            return item
        values[name] = item.value
    subscription_ref = None
    if "subscription_ref" in fields.value:
        parsed_ref = _string(
            fields.value["subscription_ref"],
            "source.subscription_ref",
            path=path,
            pointer=f"{pointer}/subscription_ref",
        )
        if isinstance(parsed_ref, Err):
            return parsed_ref
        subscription_ref = parsed_ref.value
    try:
        kind = SourceKind(values["kind"])
        return Ok(
            SourceEvidence(
                SourceAlias(values["alias"]),
                SourceId(values["declared_id"]),
                kind,
                values["origin"],
                values["resolved_commit"],
                subscription_ref,
            )
        )
    except ValueError as error:
        return _error(str(error), path=path, pointer=pointer)


def _artifact(value: JsonValue, *, path: str, pointer: str) -> Result[ArtifactEvidence]:
    fields = _object(
        value,
        required=frozenset(
            {
                "type",
                "name",
                "version",
                "manifest_digest",
                "payload_digest",
                "object_digest",
            }
        ),
        path=path,
        pointer=pointer,
    )
    if isinstance(fields, Err):
        return fields
    strings: dict[str, str] = {}
    for name in ("type", "name", "version"):
        result = _string(
            fields.value[name], f"artifact.{name}", path=path, pointer=f"{pointer}/{name}"
        )
        if isinstance(result, Err):
            return result
        strings[name] = result.value
    version = parse_semver(strings["version"], location=_location(path, f"{pointer}/version"))
    if isinstance(version, Err):
        return version
    digests: dict[str, ObjectDigest] = {}
    for name in ("manifest_digest", "payload_digest", "object_digest"):
        digest_result = _digest(fields.value[name], name, path=path, pointer=f"{pointer}/{name}")
        if isinstance(digest_result, Err):
            return digest_result
        digests[name] = digest_result.value
    try:
        return Ok(
            ArtifactEvidence(
                ArtifactIdentity(strings["type"], strings["name"]),  # type: ignore[arg-type]
                version.value,
                digests["manifest_digest"],
                digests["payload_digest"],
                digests["object_digest"],
            )
        )
    except ValueError as error:
        return _error(str(error), path=path, pointer=pointer)


def _effect(value: JsonValue, *, path: str, pointer: str) -> Result[EffectProof]:
    optional = frozenset(
        {
            "source_path",
            "json_path",
            "merge_mode",
            "identity_digest",
            "identity_evidence",
            "link_target",
            "link_semantics",
            "created_destination",
            "overwrote",
        }
    )
    fields = _object(
        value,
        required=frozenset({"kind", "destination", "actual_mode", "installed_digest"}),
        optional=optional,
        path=path,
        pointer=pointer,
    )
    if isinstance(fields, Err):
        return fields
    strings: dict[str, str] = {}
    for name in ("kind", "destination", "actual_mode"):
        parsed = _string(fields.value[name], name, path=path, pointer=f"{pointer}/{name}")
        if isinstance(parsed, Err):
            return parsed
        strings[name] = parsed.value
    installed = _digest(
        fields.value["installed_digest"],
        "installed_digest",
        path=path,
        pointer=f"{pointer}/installed_digest",
    )
    if isinstance(installed, Err):
        return installed
    optional_strings: dict[str, str | None] = {}
    for name in ("source_path", "json_path", "merge_mode", "link_target", "link_semantics"):
        if name not in fields.value:
            optional_strings[name] = None
            continue
        parsed = _string(fields.value[name], name, path=path, pointer=f"{pointer}/{name}")
        if isinstance(parsed, Err):
            return parsed
        optional_strings[name] = parsed.value
    identity = None
    if "identity_digest" in fields.value:
        parsed_identity = _digest(
            fields.value["identity_digest"],
            "identity_digest",
            path=path,
            pointer=f"{pointer}/identity_digest",
        )
        if isinstance(parsed_identity, Err):
            return parsed_identity
        identity = parsed_identity.value
    flags: dict[str, bool] = {}
    for name in ("created_destination", "overwrote"):
        if name not in fields.value:
            flags[name] = False
            continue
        parsed_flag = _boolean(fields.value[name], name, path=path, pointer=f"{pointer}/{name}")
        if isinstance(parsed_flag, Err):
            return parsed_flag
        flags[name] = parsed_flag.value
    try:
        return Ok(
            EffectProof(
                kind=strings["kind"],  # type: ignore[arg-type]
                destination=strings["destination"],
                actual_mode=strings["actual_mode"],  # type: ignore[arg-type]
                installed_digest=installed.value,
                source_path=optional_strings["source_path"],
                json_path=optional_strings["json_path"],
                merge_mode=optional_strings["merge_mode"],  # type: ignore[arg-type]
                identity_digest=identity,
                identity_evidence=fields.value.get("identity_evidence"),
                link_target=optional_strings["link_target"],
                link_semantics=optional_strings["link_semantics"],  # type: ignore[arg-type]
                created_destination=flags["created_destination"],
                overwrote=flags["overwrote"],
            )
        )
    except ValueError as error:
        return _error(str(error), path=path, pointer=pointer)


def _coordinate(raw: str, *, path: str, pointer: str) -> Result[ArtifactCoordinate]:
    parts = raw.split("/")
    if len(parts) != 3:
        return _error("coordinate must be <source>/<type>/<name>", path=path, pointer=pointer)
    try:
        return Ok(
            ArtifactCoordinate(
                SourceAlias(parts[0]),
                ArtifactIdentity(parts[1], parts[2]),  # type: ignore[arg-type]
            )
        )
    except ValueError as error:
        return _error(str(error), path=path, pointer=pointer)


def _record(value: JsonValue, *, path: str, index: int) -> Result[InstallationRecord]:
    pointer = f"/installations/{index}"
    fields = _object(
        value,
        required=frozenset(
            {
                "coordinate",
                "source",
                "artifact",
                "profile",
                "profile_version",
                "scope",
                "requested_mode",
                "effects",
            }
        ),
        optional=frozenset({"memory_mode", "setup_state_ref"}),
        path=path,
        pointer=pointer,
    )
    if isinstance(fields, Err):
        return fields
    simple: dict[str, str] = {}
    for name in ("coordinate", "profile", "scope", "requested_mode"):
        parsed = _string(fields.value[name], name, path=path, pointer=f"{pointer}/{name}")
        if isinstance(parsed, Err):
            return parsed
        simple[name] = parsed.value
    coordinate = _coordinate(simple["coordinate"], path=path, pointer=f"{pointer}/coordinate")
    source = _source(fields.value["source"], path=path, pointer=f"{pointer}/source")
    artifact = _artifact(fields.value["artifact"], path=path, pointer=f"{pointer}/artifact")
    profile_version = _integer(
        fields.value["profile_version"],
        "profile_version",
        path=path,
        pointer=f"{pointer}/profile_version",
    )
    if isinstance(coordinate, Err):
        return coordinate
    if isinstance(source, Err):
        return source
    if isinstance(artifact, Err):
        return artifact
    if isinstance(profile_version, Err):
        return profile_version
    effects_value = fields.value["effects"]
    if not isinstance(effects_value, JsonArray) or not effects_value.items:
        return _error("effects must be a non-empty array", path=path, pointer=f"{pointer}/effects")
    effects = []
    for effect_index, value_item in enumerate(effects_value.items):
        parsed_effect = _effect(
            value_item,
            path=path,
            pointer=f"{pointer}/effects/{effect_index}",
        )
        if isinstance(parsed_effect, Err):
            return parsed_effect
        effects.append(parsed_effect.value)
    setup_ref = None
    if "setup_state_ref" in fields.value:
        parsed_setup = _string(
            fields.value["setup_state_ref"],
            "setup_state_ref",
            path=path,
            pointer=f"{pointer}/setup_state_ref",
        )
        if isinstance(parsed_setup, Err):
            return parsed_setup
        setup_ref = parsed_setup.value
    memory_mode = None
    if "memory_mode" in fields.value:
        parsed_memory_mode = _string(
            fields.value["memory_mode"],
            "memory_mode",
            path=path,
            pointer=f"{pointer}/memory_mode",
        )
        if isinstance(parsed_memory_mode, Err):
            return parsed_memory_mode
        memory_mode = parsed_memory_mode.value
    try:
        return Ok(
            InstallationRecord(
                coordinate=coordinate.value,
                source=source.value,
                artifact=artifact.value,
                profile=simple["profile"],
                profile_version=profile_version.value,
                scope=simple["scope"],  # type: ignore[arg-type]
                requested_mode=simple["requested_mode"],  # type: ignore[arg-type]
                effects=tuple(effects),
                memory_mode=memory_mode,  # type: ignore[arg-type]
                setup_state_ref=setup_ref,
            )
        )
    except ValueError as error:
        return _error(str(error), path=path, pointer=pointer)


def parse_install_state(
    data: bytes | str,
    *,
    path: str = "manifest.json",
) -> Result[InstallState]:
    parsed = parse_json(data, location=_location(path))
    if isinstance(parsed, Err):
        return _as_install_state_invalid(parsed)
    parsed_v2 = _parse_v2_install_state(parsed.value, path=path)
    return parsed_v2 if isinstance(parsed_v2, Ok) else _as_install_state_invalid(parsed_v2)


def _parse_v2_install_state(value: JsonValue, *, path: str) -> Result[InstallState]:
    fields = _object(
        value,
        required=frozenset({"schema_version", "installations"}),
        path=path,
        pointer="",
    )
    if isinstance(fields, Err):
        return fields
    schema_version = _integer(
        fields.value["schema_version"], "schema_version", path=path, pointer="/schema_version"
    )
    if isinstance(schema_version, Err):
        return schema_version
    if schema_version.value != 2:
        return _error("schema_version must be 2", path=path, pointer="/schema_version")
    raw_installations = fields.value["installations"]
    if not isinstance(raw_installations, JsonArray):
        return _error("installations must be an array", path=path, pointer="/installations")
    installations = []
    for index, value in enumerate(raw_installations.items):
        record = _record(value, path=path, index=index)
        if isinstance(record, Err):
            return record
        installations.append(record.value)
    try:
        return Ok(InstallState(2, tuple(installations)))
    except ValueError as error:
        return _error(str(error), path=path)


def _effect_json(effect: EffectProof) -> JsonObject:
    fields: list[tuple[str, JsonValue]] = [
        ("kind", effect.kind),
        ("destination", effect.destination),
        ("actual_mode", effect.actual_mode),
        ("installed_digest", str(effect.installed_digest)),
    ]
    if effect.source_path is not None:
        fields.append(("source_path", effect.source_path))
    if effect.json_path is not None:
        fields.append(("json_path", effect.json_path))
    if effect.merge_mode is not None:
        fields.append(("merge_mode", effect.merge_mode))
    if effect.identity_digest is not None:
        fields.append(("identity_digest", str(effect.identity_digest)))
    if effect.identity_evidence is not None:
        fields.append(("identity_evidence", effect.identity_evidence))
    if effect.link_target is not None:
        fields.append(("link_target", effect.link_target))
    if effect.link_semantics is not None:
        fields.append(("link_semantics", effect.link_semantics))
    fields.extend(
        (
            ("created_destination", effect.created_destination),
            ("overwrote", effect.overwrote),
        )
    )
    return JsonObject(tuple(fields))


def install_state_to_json(state: InstallState) -> JsonObject:
    records = []
    for record in state.installations:
        source = JsonObject(
            tuple(
                [
                    ("alias", record.source.alias.value),
                    ("declared_id", record.source.declared_id.value),
                    ("kind", record.source.kind.value),
                    ("origin", record.source.origin),
                    ("resolved_commit", record.source.resolved_commit),
                ]
                + (
                    [("subscription_ref", record.source.subscription_ref)]
                    if record.source.subscription_ref is not None
                    else []
                )
            )
        )
        artifact = JsonObject(
            (
                ("type", record.artifact.identity.kind),
                ("name", record.artifact.identity.name),
                ("version", str(record.artifact.version)),
                ("manifest_digest", str(record.artifact.manifest_digest)),
                ("payload_digest", str(record.artifact.payload_digest)),
                ("object_digest", str(record.artifact.object_digest)),
            )
        )
        fields: list[tuple[str, JsonValue]] = [
            ("coordinate", str(record.coordinate)),
            ("source", source),
            ("artifact", artifact),
            ("profile", record.profile),
            ("profile_version", record.profile_version),
            ("scope", record.scope),
            ("requested_mode", record.requested_mode),
            ("effects", JsonArray(tuple(_effect_json(effect) for effect in record.effects))),
        ]
        if record.memory_mode is not None:
            fields.append(("memory_mode", record.memory_mode))
        if record.setup_state_ref is not None:
            fields.append(("setup_state_ref", record.setup_state_ref))
        records.append(JsonObject(tuple(fields)))
    return JsonObject(
        (
            ("schema_version", state.schema_version),
            ("installations", JsonArray(tuple(records))),
        )
    )


def install_state_bytes(state: InstallState) -> bytes:
    return canonical_json_bytes(install_state_to_json(state))
