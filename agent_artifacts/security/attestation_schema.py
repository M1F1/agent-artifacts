"""Strict canonical JSON schemas for security attestations and registry security indexes."""

from __future__ import annotations

from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import SourceId
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.protocol.hashing import parse_sha256
from agent_artifacts.protocol.json import (
    JsonArray,
    JsonObject,
    JsonValue,
    canonical_json_bytes,
    parse_json,
)
from agent_artifacts.protocol.paths import parse_relative_path

from .attestations import (
    AssessmentCacheKey,
    AttestationOrigin,
    AttestationOriginKind,
    SecurityAttestation,
    SecurityIndex,
    SecurityIndexEntry,
    attestation_value,
    security_index_value,
)
from .schema import parse_assessment

ATTESTATION_INVALID = DiagnosticCode("security-attestation-invalid")
SECURITY_INDEX_INVALID = DiagnosticCode("security-index-invalid")
_MAX_ATTESTATION_BYTES = 2 * 1024 * 1024 + 16 * 1024
_MAX_INDEX_BYTES = 16 * 1024 * 1024
_MAX_INDEX_ENTRIES = 100_000


def _error(code: DiagnosticCode, message: str) -> Err:
    return Err((Diagnostic(code, Severity.ERROR, message),))


def _fields(
    value: JsonValue,
    expected: frozenset[str],
    code: DiagnosticCode,
    label: str,
) -> Result[dict[str, JsonValue]]:
    if not isinstance(value, JsonObject):
        return _error(code, f"{label} must be an object")
    fields = dict(value.entries)
    if frozenset(fields) != expected:
        return _error(code, f"{label} fields are invalid")
    return Ok(fields)


def _document(data: bytes | str, code: DiagnosticCode, maximum: int) -> Result[bytes]:
    if not isinstance(data, (bytes, str)):
        return _error(code, "document must be UTF-8 bytes or text")
    try:
        encoded = data.encode("utf-8") if isinstance(data, str) else data
    except UnicodeEncodeError:
        return _error(code, "document is not UTF-8")
    if len(encoded) > maximum:
        return _error(code, "document exceeds its encoded size limit")
    return Ok(encoded)


def _digest(value: JsonValue, code: DiagnosticCode, label: str):
    if not isinstance(value, str):
        return _error(code, f"{label} must be a SHA-256 string")
    parsed = parse_sha256(value)
    if isinstance(parsed, Err):
        return _error(code, f"{label} is invalid")
    return parsed


def _cache_key(value: JsonValue, code: DiagnosticCode) -> Result[AssessmentCacheKey]:
    expected = frozenset(
        {
            "object_digest",
            "options_digest",
            "policy_digest",
            "provider_id",
            "provider_version",
            "rules_digest",
            "schema_version",
        }
    )
    fields = _fields(value, expected, code, "cache key")
    if isinstance(fields, Err):
        return fields
    raw = fields.value
    object_digest = _digest(raw["object_digest"], code, "object_digest")
    options_digest = _digest(raw["options_digest"], code, "options_digest")
    policy_digest = _digest(raw["policy_digest"], code, "policy_digest")
    rules_digest = _digest(raw["rules_digest"], code, "rules_digest")
    if any(
        isinstance(item, Err)
        for item in (object_digest, options_digest, policy_digest, rules_digest)
    ) or any(not isinstance(raw[name], str) for name in ("provider_id", "provider_version")):
        return _error(code, "cache key field types are invalid")
    assert isinstance(object_digest, Ok)
    assert isinstance(options_digest, Ok)
    assert isinstance(policy_digest, Ok)
    assert isinstance(rules_digest, Ok)
    try:
        return Ok(
            AssessmentCacheKey(
                raw["schema_version"],  # type: ignore[arg-type]
                object_digest.value,
                raw["provider_id"],  # type: ignore[arg-type]
                raw["provider_version"],  # type: ignore[arg-type]
                rules_digest.value,
                options_digest.value,
                policy_digest.value,
            )
        )
    except ValueError:
        return _error(code, "cache key values are invalid")


def _origin(value: JsonValue) -> Result[AttestationOrigin]:
    code = ATTESTATION_INVALID
    if not isinstance(value, JsonObject):
        return _error(code, "attestation origin must be an object")
    fields = dict(value.entries)
    kind = fields.get("kind")
    if kind == AttestationOriginKind.LOCAL.value and frozenset(fields) == {"kind"}:
        return Ok(AttestationOrigin(AttestationOriginKind.LOCAL))
    expected = frozenset({"kind", "registry_inputs_digest", "resolved_revision", "source_id"})
    if frozenset(fields) != expected or kind != AttestationOriginKind.REGISTRY_CI.value:
        return _error(code, "attestation origin fields are invalid")
    digest = _digest(fields["registry_inputs_digest"], code, "registry_inputs_digest")
    if (
        isinstance(digest, Err)
        or not isinstance(fields["resolved_revision"], str)
        or not isinstance(fields["source_id"], str)
    ):
        return _error(code, "registry attestation origin types are invalid")
    try:
        return Ok(
            AttestationOrigin(
                AttestationOriginKind.REGISTRY_CI,
                SourceId(fields["source_id"]),
                fields["resolved_revision"],
                digest.value,
            )
        )
    except ValueError:
        return _error(code, "registry attestation origin values are invalid")


def attestation_bytes(value: SecurityAttestation) -> bytes:
    return canonical_json_bytes(attestation_value(value))


def parse_attestation(data: bytes | str) -> Result[SecurityAttestation]:
    document = _document(data, ATTESTATION_INVALID, _MAX_ATTESTATION_BYTES)
    if isinstance(document, Err):
        return document
    parsed = parse_json(document.value, max_depth=32, max_string_length=4096)
    if isinstance(parsed, Err):
        return _error(ATTESTATION_INVALID, "attestation is not strict JSON")
    fields = _fields(
        parsed.value,
        frozenset({"assessment", "cache_key", "origin", "schema_version"}),
        ATTESTATION_INVALID,
        "attestation",
    )
    if isinstance(fields, Err):
        return fields
    key = _cache_key(fields.value["cache_key"], ATTESTATION_INVALID)
    origin = _origin(fields.value["origin"])
    assessment = parse_assessment(canonical_json_bytes(fields.value["assessment"]))
    if isinstance(key, Err) or isinstance(origin, Err) or isinstance(assessment, Err):
        return _error(ATTESTATION_INVALID, "attestation nested evidence is invalid")
    try:
        result = SecurityAttestation(
            fields.value["schema_version"],  # type: ignore[arg-type]
            key.value,
            origin.value,
            assessment.value,
        )
    except ValueError:
        return _error(ATTESTATION_INVALID, "attestation values are inconsistent")
    if attestation_bytes(result) != document.value:
        return _error(ATTESTATION_INVALID, "attestation is not canonical")
    return Ok(result)


def security_index_bytes(value: SecurityIndex) -> bytes:
    return canonical_json_bytes(security_index_value(value))


def parse_security_index(data: bytes | str) -> Result[SecurityIndex]:
    document = _document(data, SECURITY_INDEX_INVALID, _MAX_INDEX_BYTES)
    if isinstance(document, Err):
        return document
    parsed = parse_json(document.value, max_depth=24, max_string_length=4096)
    if isinstance(parsed, Err):
        return _error(SECURITY_INDEX_INVALID, "security index is not strict JSON")
    fields = _fields(
        parsed.value,
        frozenset({"entries", "registry_id", "registry_inputs_digest", "schema_version"}),
        SECURITY_INDEX_INVALID,
        "security index",
    )
    if isinstance(fields, Err):
        return fields
    raw = fields.value
    registry_digest = _digest(
        raw["registry_inputs_digest"], SECURITY_INDEX_INVALID, "registry_inputs_digest"
    )
    if (
        not isinstance(raw["registry_id"], str)
        or not isinstance(raw["entries"], JsonArray)
        or len(raw["entries"].items) > _MAX_INDEX_ENTRIES
        or isinstance(registry_digest, Err)
    ):
        return _error(SECURITY_INDEX_INVALID, "security index field types are invalid")
    entries: list[SecurityIndexEntry] = []
    for value in raw["entries"].items:
        entry_fields = _fields(
            value,
            frozenset({"attestation_digest", "cache_key", "path"}),
            SECURITY_INDEX_INVALID,
            "security index entry",
        )
        if isinstance(entry_fields, Err):
            return entry_fields
        key = _cache_key(entry_fields.value["cache_key"], SECURITY_INDEX_INVALID)
        digest = _digest(
            entry_fields.value["attestation_digest"],
            SECURITY_INDEX_INVALID,
            "attestation_digest",
        )
        raw_path = entry_fields.value["path"]
        path = parse_relative_path(raw_path) if isinstance(raw_path, str) else None
        if isinstance(key, Err) or isinstance(digest, Err) or path is None or isinstance(path, Err):
            return _error(SECURITY_INDEX_INVALID, "security index entry is invalid")
        try:
            entries.append(SecurityIndexEntry(key.value, digest.value, path.value))
        except ValueError:
            return _error(SECURITY_INDEX_INVALID, "security index entry values are invalid")
    try:
        result = SecurityIndex(
            raw["schema_version"],  # type: ignore[arg-type]
            SourceId(raw["registry_id"]),
            registry_digest.value,
            tuple(entries),
        )
    except ValueError:
        return _error(SECURITY_INDEX_INVALID, "security index values are invalid")
    if security_index_bytes(result) != document.value:
        return _error(SECURITY_INDEX_INVALID, "security index is not canonical")
    return Ok(result)


__all__ = [
    "ATTESTATION_INVALID",
    "SECURITY_INDEX_INVALID",
    "attestation_bytes",
    "parse_attestation",
    "parse_security_index",
    "security_index_bytes",
]
