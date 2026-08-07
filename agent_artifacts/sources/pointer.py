"""Strict canonical current-source pointer schema."""

from __future__ import annotations

import re
from dataclasses import dataclass

from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import ObjectDigest, SourceId
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.protocol.hashing import parse_sha256
from agent_artifacts.protocol.json import JsonObject, JsonValue, canonical_json_bytes, parse_json
from agent_artifacts.protocol.native_tree import SnapshotOrigin
from agent_artifacts.protocol.schema import validate_object_fields

from .model import SourceInstanceId

SOURCE_INVALID = DiagnosticCode("source-invalid")
_SOURCE_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True, slots=True)
class CurrentPointer:
    instance_id: SourceInstanceId
    resolved_revision: str
    snapshot_digest: ObjectDigest
    declared_source_id: SourceId
    origin: SnapshotOrigin
    published_at_epoch_seconds: int


def _error(message: str) -> Err:
    return Err((Diagnostic(SOURCE_INVALID, Severity.ERROR, message),))


def current_pointer_bytes(pointer: CurrentPointer) -> bytes:
    return canonical_json_bytes(
        JsonObject(
            (
                ("declared_source_id", pointer.declared_source_id.value),
                ("origin", pointer.origin.value),
                ("published_at_epoch_seconds", pointer.published_at_epoch_seconds),
                ("resolved_revision", pointer.resolved_revision),
                ("schema_version", 1),
                ("snapshot_digest", str(pointer.snapshot_digest)),
                ("source_instance_id", pointer.instance_id.value),
            )
        )
    )


def _string(fields: dict[str, JsonValue], name: str) -> Result[str]:
    value = fields[name]
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\n" in value
        or "\r" in value
    ):
        return _error(f"current source field {name!r} must be one non-empty string")
    return Ok(value)


def parse_current_pointer(data: bytes | str) -> Result[CurrentPointer]:
    parsed = parse_json(data)
    if isinstance(parsed, Err):
        return _error("current source pointer is not valid JSON")
    if not isinstance(parsed.value, JsonObject):
        return _error("current source pointer must be an object")
    required = frozenset(
        {
            "schema_version",
            "source_instance_id",
            "resolved_revision",
            "snapshot_digest",
            "declared_source_id",
            "origin",
            "published_at_epoch_seconds",
        }
    )
    validated = validate_object_fields(parsed.value, required=required)
    if isinstance(validated, Err):
        return _error("current source pointer fields are invalid")
    fields = dict(validated.value.entries)
    version = fields["schema_version"]
    published = fields["published_at_epoch_seconds"]
    if version != 1 or isinstance(version, bool):
        return _error("current source pointer schema version is unsupported")
    if not isinstance(published, int) or isinstance(published, bool) or published < 0:
        return _error("current source publication time is invalid")
    strings = {
        name: _string(fields, name)
        for name in (
            "source_instance_id",
            "resolved_revision",
            "snapshot_digest",
            "declared_source_id",
            "origin",
        )
    }
    for result in strings.values():
        if isinstance(result, Err):
            return result
    values = {name: result.value for name, result in strings.items() if isinstance(result, Ok)}
    digest = parse_sha256(values["snapshot_digest"])
    if isinstance(digest, Err):
        return _error("current source snapshot digest is invalid")
    if _SOURCE_ID_RE.fullmatch(values["declared_source_id"]) is None:
        return _error("current source declared identity is invalid")
    try:
        origin = SnapshotOrigin(values["origin"])
        instance_id = SourceInstanceId(values["source_instance_id"])
    except ValueError:
        return _error("current source pointer identity is invalid")
    resolved_revision = values["resolved_revision"]
    if origin is SnapshotOrigin.LOCAL:
        if resolved_revision != f"local:{digest.value.value}":
            return _error("current local source revision does not match its snapshot digest")
    elif _COMMIT_RE.fullmatch(resolved_revision) is None:
        return _error("current Git source revision is not a canonical commit")
    try:
        return Ok(
            CurrentPointer(
                instance_id,
                resolved_revision,
                digest.value,
                SourceId(values["declared_source_id"]),
                origin,
                published,
            )
        )
    except ValueError:
        return _error("current source pointer identity is invalid")
