"""Security evidence CLI over pure assessments and bounded filesystem adapters."""

from __future__ import annotations

import os
import stat
import sys

from agent_artifacts import command_outcome as _common
from agent_artifacts.domain.identifiers import ObjectDigest, SourceId
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.io.security_analyzers import resolve_executable
from agent_artifacts.io.security_cache import write_cached_attestation
from agent_artifacts.marketplace.model import TrustClass
from agent_artifacts.model import Request
from agent_artifacts.protocol.hashing import json_digest, parse_sha256
from agent_artifacts.protocol.json import JsonArray, JsonObject, canonical_json_bytes
from agent_artifacts.protocol.registry_schema import parse_registry_index, parse_registry_lock
from agent_artifacts.security.attestation_schema import parse_attestation
from agent_artifacts.security.attestations import (
    AssessmentCacheKey,
    AttestationOrigin,
    AttestationOriginKind,
    AttestationTrustContext,
    SecurityAttestation,
    attestation_digest,
    cache_key_digest,
    resolve_attestation,
)
from agent_artifacts.security.baseline import (
    BASELINE_RULES_DIGEST,
    BaselineScanRequest,
    assess_installation_risk,
)
from agent_artifacts.security.cache import security_cache_paths
from agent_artifacts.security.projections import assessment_security_value
from agent_artifacts.security.schema import parse_assessment
from agent_artifacts.security.suites import BUILTIN_ANALYZER_SUITES
from agent_artifacts.security.tool_adapters import (
    discover_tool_adapters,
)
from agent_artifacts.store.model import parse_object_candidate

_MAX_OBJECT_BYTES = 150 * 1024 * 1024
_MAX_EVIDENCE_BYTES = 16 * 1024 * 1024
_EMPTY_DIGEST = json_digest(JsonObject(()))


def _failure(message: str) -> int:
    print(f"security: {message}", file=sys.stderr)
    return _common.ERROR


def _read_bounded(path: str, maximum: int) -> bytes | None:
    try:
        before = os.stat(path, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
            return None
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino, opened.st_size) != (
                before.st_dev,
                before.st_ino,
                before.st_size,
            ):
                return None
            data = stream.read(maximum + 1)
        return data if len(data) == before.st_size else None
    except OSError:
        return None


def _emit_json(value: JsonObject) -> None:
    print(canonical_json_bytes(value).decode("utf-8"), end="")


def _show(request: Request) -> int:
    assert request.security_input is not None
    data = _read_bounded(request.security_input, _MAX_EVIDENCE_BYTES)
    if data is None:
        return _failure("cannot read a bounded real evidence file")
    parsed_attestation = parse_attestation(data)
    if isinstance(parsed_attestation, Ok):
        attestation = parsed_attestation.value
        value = JsonObject(
            (
                *assessment_security_value(attestation.assessment).entries,
                ("attestation_digest", str(attestation_digest(attestation))),
                ("attestation_origin", attestation.origin.kind.value),
                ("cache_key_digest", str(cache_key_digest(attestation.cache_key))),
                ("provider_id", attestation.cache_key.provider_id),
                ("provider_version", attestation.cache_key.provider_version),
            )
        )
    else:
        parsed_assessment = parse_assessment(data)
        if isinstance(parsed_assessment, Err):
            return _failure("file is not a canonical assessment or attestation")
        value = assessment_security_value(parsed_assessment.value)
    if request.json:
        _emit_json(value)
    else:
        fields = dict(value.entries)
        print(
            "security assessment: "
            f"installation risk {fields['installation_risk']}; "
            f"status {fields['assessment_status']}; "
            f"maximum finding severity {fields['max_finding_severity']}"
        )
    return _common.OK


def _analyzers(request: Request) -> int:
    discovered = discover_tool_adapters(resolver=resolve_executable)
    items = tuple(
        JsonObject(
            (
                ("available", item.available),
                ("capability", item.adapter.capability),
                ("executable", item.adapter.executable),
                ("file_extensions", JsonArray(item.adapter.file_extensions)),
                ("id", item.adapter.provider_id),
                ("network_required", item.adapter.network_required),
                ("rules_digest", str(item.adapter.rules_digest)),
            )
        )
        for item in discovered
    )
    value = JsonObject((("analyzers", JsonArray(items)), ("schema_version", 1)))
    if request.json:
        _emit_json(value)
    else:
        for item in discovered:
            availability = "available" if item.available else "not installed"
            network = "; network required" if item.adapter.network_required else ""
            print(f"{item.adapter.provider_id}: {availability}{network}")
    return _common.OK


def _suites(request: Request) -> int:
    items = tuple(
        JsonObject(
            (
                ("id", suite.id),
                ("optional_provider_ids", JsonArray(suite.optional_provider_ids)),
                ("required_provider_ids", JsonArray(suite.required_provider_ids)),
                ("summary", suite.summary),
            )
        )
        for suite in BUILTIN_ANALYZER_SUITES
    )
    value = JsonObject((("schema_version", 1), ("suites", JsonArray(items))))
    if request.json:
        _emit_json(value)
    else:
        for suite in BUILTIN_ANALYZER_SUITES:
            optional = ", ".join(suite.optional_provider_ids) or "none"
            print(f"{suite.id}: {suite.summary} Optional providers: {optional}.")
    return _common.OK


def _scan(request: Request) -> int:
    assert request.security_input is not None
    assert request.registry_index is not None
    assert request.security_artifact is not None
    object_data = _read_bounded(request.security_input, _MAX_OBJECT_BYTES)
    index_data = _read_bounded(request.registry_index, _MAX_EVIDENCE_BYTES)
    if object_data is None or index_data is None:
        return _failure("cannot read bounded real object and registry index files")
    candidate = parse_object_candidate(object_data)
    index = parse_registry_index(index_data)
    if isinstance(candidate, Err) or isinstance(index, Err):
        return _failure("object envelope or registry index is invalid")
    artifact = next(
        (item for item in index.value.artifacts if str(item.identity) == request.security_artifact),
        None,
    )
    if artifact is None:
        return _failure("selected artifact is absent from the registry index")
    lock = None
    if request.registry_lock is not None:
        lock_data = _read_bounded(request.registry_lock, _MAX_EVIDENCE_BYTES)
        parsed_lock = parse_registry_lock(lock_data) if lock_data is not None else None
        if parsed_lock is None or isinstance(parsed_lock, Err):
            return _failure("registry lock is invalid")
        lock = next(
            (item for identity, item in parsed_lock.value.entries if identity == artifact.identity),
            None,
        )
        if lock is None:
            return _failure("selected artifact is absent from the registry lock")
    assessment = assess_installation_risk(BaselineScanRequest(candidate.value, artifact, lock))
    cache_key = AssessmentCacheKey(
        1,
        candidate.value.digest,
        "aart-baseline",
        "1",
        BASELINE_RULES_DIGEST,
        _EMPTY_DIGEST,
        _EMPTY_DIGEST,
    )
    attestation = SecurityAttestation(
        1,
        cache_key,
        AttestationOrigin(AttestationOriginKind.LOCAL),
        assessment,
    )
    cache_path: str | None = None
    cache_created: bool | None = None
    if request.security_cache is not None:
        root = os.path.abspath(request.security_cache)
        try:
            paths = security_cache_paths(root)
        except ValueError:
            return _failure("security cache path is invalid")
        written = write_cached_attestation(paths, attestation)
        if isinstance(written, Err):
            return _failure("cannot publish canonical attestation cache")
        cache_path = written.value.path
        cache_created = written.value.created
    value = JsonObject(
        (
            *assessment_security_value(assessment).entries,
            ("attestation_digest", str(attestation_digest(attestation))),
            ("cache_created", cache_created),
            ("cache_path", cache_path),
        )
    )
    if request.json:
        _emit_json(value)
    else:
        print(
            f"security scan: installation risk {assessment.installation_risk.value}; "
            f"status {assessment.status.value}; {len(assessment.findings)} finding(s)"
        )
        if cache_path is not None:
            state = "created" if cache_created else "already current"
            print(f"attestation cache: {state}: {cache_path}")
    return _common.OK


def _override_digest(raw: str | None, current: ObjectDigest) -> ObjectDigest | None:
    if raw is None:
        return current
    parsed = parse_sha256(raw)
    return None if isinstance(parsed, Err) else parsed.value


def _verify(request: Request) -> int:
    assert request.security_input is not None
    data = _read_bounded(request.security_input, _MAX_EVIDENCE_BYTES)
    parsed = parse_attestation(data) if data is not None else None
    if parsed is None or isinstance(parsed, Err):
        return _failure("attestation is not bounded, canonical, and internally consistent")
    attestation = parsed.value
    key = attestation.cache_key
    object_digest = _override_digest(request.security_object_digest, key.object_digest)
    rules_digest = _override_digest(request.security_rules_digest, key.rules_digest)
    options_digest = _override_digest(request.security_options_digest, key.options_digest)
    policy_digest = _override_digest(request.security_policy_digest, key.policy_digest)
    if None in (object_digest, rules_digest, options_digest, policy_digest):
        return _failure("expected cache identity contains an invalid SHA-256 digest")
    assert object_digest is not None
    assert rules_digest is not None
    assert options_digest is not None
    assert policy_digest is not None
    try:
        expected = AssessmentCacheKey(
            1,
            object_digest,
            key.provider_id,
            request.security_provider_version or key.provider_version,
            rules_digest,
            options_digest,
            policy_digest,
        )
    except ValueError:
        return _failure("expected cache identity is invalid")
    context_values = (
        request.publisher_source_id,
        request.security_registry_inputs_digest,
        request.publisher_trust,
    )
    context = None
    if any(item is not None for item in context_values):
        if not all(item is not None for item in context_values):
            return _failure(
                "publisher source, registry digest, and trust must be provided together"
            )
        assert request.publisher_source_id is not None
        assert request.security_registry_inputs_digest is not None
        assert request.publisher_trust is not None
        registry_digest = parse_sha256(request.security_registry_inputs_digest)
        if isinstance(registry_digest, Err):
            return _failure("publisher registry inputs digest is invalid")
        try:
            context = AttestationTrustContext(
                SourceId(request.publisher_source_id),
                registry_digest.value,
                TrustClass(request.publisher_trust),
            )
        except ValueError:
            return _failure("publisher trust context is invalid")
    resolved = resolve_attestation(attestation, expected, trust_context=context)
    value = JsonObject(
        (
            ("attestation_digest", str(attestation_digest(attestation))),
            ("assessment_status", resolved.assessment.status.value),
            ("freshness", resolved.freshness.value),
            ("reasons", JsonArray(resolved.reasons)),
            ("trust", resolved.trust.value),
        )
    )
    if request.json:
        _emit_json(value)
    else:
        print(
            f"security attestation: {resolved.freshness.value}; trust {resolved.trust.value}; "
            f"assessment {resolved.assessment.status.value}"
        )
        for reason in resolved.reasons:
            print(f"  {reason}")
    return _common.OK if resolved.freshness.value == "current" else _common.ERROR


def run(request: Request) -> int:
    action = request.security_action
    if action == "scan":
        return _scan(request)
    if action == "show":
        return _show(request)
    if action == "verify":
        return _verify(request)
    if action == "analyzers":
        return _analyzers(request)
    if action == "suites":
        return _suites(request)
    return _common.USAGE


__all__ = ["run"]
