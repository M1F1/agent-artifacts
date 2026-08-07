"""Strict canonical object-reference index schema."""

from __future__ import annotations

from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.protocol.hashing import parse_sha256
from agent_artifacts.protocol.json import JsonArray, JsonObject, canonical_json_bytes, parse_json

from .model import ObjectReference, ReferenceIndex, ReferenceKind

REFERENCE_INVALID = DiagnosticCode("store-reference-invalid")


def _error(message: str) -> Err:
    return Err((Diagnostic(REFERENCE_INVALID, Severity.ERROR, message),))


def reference_index_bytes(index: ReferenceIndex) -> bytes:
    return canonical_json_bytes(
        JsonObject(
            (
                (
                    "references",
                    JsonArray(
                        tuple(
                            JsonObject(
                                (
                                    ("digest", str(reference.digest)),
                                    ("kind", reference.kind.value),
                                    ("owner", reference.owner),
                                )
                            )
                            for reference in index.references
                        )
                    ),
                ),
                ("schema_version", index.schema_version),
            )
        )
    )


def parse_reference_index(data: bytes | str) -> Result[ReferenceIndex]:
    parsed = parse_json(data)
    if isinstance(parsed, Err) or not isinstance(parsed.value, JsonObject):
        return _error("object reference index is not strict JSON")
    fields = dict(parsed.value.entries)
    if frozenset(fields) != frozenset({"schema_version", "references"}):
        return _error("object reference index fields are invalid")
    if fields["schema_version"] != 1 or isinstance(fields["schema_version"], bool):
        return _error("object reference index schema version is unsupported")
    values = fields["references"]
    if not isinstance(values, JsonArray):
        return _error("object references must be an array")
    references: list[ObjectReference] = []
    for value in values.items:
        if not isinstance(value, JsonObject):
            return _error("object reference must be an object")
        item = dict(value.entries)
        if frozenset(item) != frozenset({"kind", "owner", "digest"}):
            return _error("object reference fields are invalid")
        if not isinstance(item["kind"], str) or not isinstance(item["owner"], str):
            return _error("object reference identity types are invalid")
        if not isinstance(item["digest"], str):
            return _error("object reference digest must be a string")
        digest = parse_sha256(item["digest"])
        if isinstance(digest, Err):
            return _error("object reference digest is invalid")
        try:
            references.append(
                ObjectReference(ReferenceKind(item["kind"]), item["owner"], digest.value)
            )
        except ValueError:
            return _error("object reference identity is invalid")
    try:
        index = ReferenceIndex(1, tuple(references))
    except ValueError:
        return _error("object reference index contains duplicates")
    if reference_index_bytes(index) != (data.encode("utf-8") if isinstance(data, str) else data):
        return _error("object reference index is not canonical")
    return Ok(index)
