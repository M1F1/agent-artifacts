"""Immutable cache identities, attestations, indexes, freshness, and derived trust."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from agent_artifacts.domain.identifiers import ObjectDigest, SourceId
from agent_artifacts.marketplace.model import TrustClass
from agent_artifacts.protocol.hashing import json_digest
from agent_artifacts.protocol.json import JsonArray, JsonObject, JsonValue
from agent_artifacts.protocol.paths import SafeRelativePath

from .model import AssessmentStatus, SecurityAssessment, mark_assessment_stale_value
from .schema import assessment_value

_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
_SOURCE_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40,64}$")
_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_INDEX_ENTRIES = 100_000


def _valid_digest(value: object) -> bool:
    return (
        isinstance(value, ObjectDigest)
        and value.algorithm == "sha256"
        and _HEX_RE.fullmatch(value.value) is not None
    )


@dataclass(frozen=True, slots=True)
class AssessmentCacheKey:
    schema_version: int
    object_digest: ObjectDigest
    provider_id: str
    provider_version: str
    rules_digest: ObjectDigest
    options_digest: ObjectDigest
    policy_digest: ObjectDigest

    def __post_init__(self) -> None:
        if (
            self.schema_version != 1
            or not _valid_digest(self.object_digest)
            or not isinstance(self.provider_id, str)
            or _ID_RE.fullmatch(self.provider_id) is None
            or not isinstance(self.provider_version, str)
            or _VERSION_RE.fullmatch(self.provider_version) is None
            or not _valid_digest(self.rules_digest)
            or not _valid_digest(self.options_digest)
            or not _valid_digest(self.policy_digest)
        ):
            raise ValueError("assessment cache key is invalid")


def cache_key_value(value: AssessmentCacheKey) -> JsonObject:
    return JsonObject(
        (
            ("object_digest", str(value.object_digest)),
            ("options_digest", str(value.options_digest)),
            ("policy_digest", str(value.policy_digest)),
            ("provider_id", value.provider_id),
            ("provider_version", value.provider_version),
            ("rules_digest", str(value.rules_digest)),
            ("schema_version", value.schema_version),
        )
    )


def cache_key_digest(value: AssessmentCacheKey) -> ObjectDigest:
    return json_digest(cache_key_value(value))


class AttestationOriginKind(str, Enum):
    LOCAL = "local"
    REGISTRY_CI = "registry-ci"


@dataclass(frozen=True, slots=True)
class AttestationOrigin:
    kind: AttestationOriginKind
    source_id: SourceId | None = None
    resolved_revision: str | None = None
    registry_inputs_digest: ObjectDigest | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, AttestationOriginKind):
            raise ValueError("attestation origin kind is invalid")
        registry_values = (
            self.source_id,
            self.resolved_revision,
            self.registry_inputs_digest,
        )
        if self.kind is AttestationOriginKind.LOCAL:
            if any(value is not None for value in registry_values):
                raise ValueError("local attestation origin cannot claim a registry identity")
            return
        if (
            not isinstance(self.source_id, SourceId)
            or _SOURCE_RE.fullmatch(self.source_id.value) is None
            or not isinstance(self.resolved_revision, str)
            or _COMMIT_RE.fullmatch(self.resolved_revision) is None
            or not _valid_digest(self.registry_inputs_digest)
        ):
            raise ValueError("registry attestation origin is invalid")


def origin_value(value: AttestationOrigin) -> JsonObject:
    entries: list[tuple[str, JsonValue]] = [("kind", value.kind.value)]
    if value.kind is AttestationOriginKind.REGISTRY_CI:
        assert value.source_id is not None
        assert value.resolved_revision is not None
        assert value.registry_inputs_digest is not None
        entries.extend(
            (
                ("registry_inputs_digest", str(value.registry_inputs_digest)),
                ("resolved_revision", value.resolved_revision),
                ("source_id", value.source_id.value),
            )
        )
    return JsonObject(tuple(entries))


@dataclass(frozen=True, slots=True)
class SecurityAttestation:
    schema_version: int
    cache_key: AssessmentCacheKey
    origin: AttestationOrigin
    assessment: SecurityAssessment

    def __post_init__(self) -> None:
        providers = (
            self.assessment.providers if isinstance(self.assessment, SecurityAssessment) else ()
        )
        provider = providers[0] if len(providers) == 1 else None
        if (
            self.schema_version != 1
            or not isinstance(self.cache_key, AssessmentCacheKey)
            or not isinstance(self.origin, AttestationOrigin)
            or not isinstance(self.assessment, SecurityAssessment)
            or provider is None
            or self.assessment.status is AssessmentStatus.STALE
            or self.assessment.object_digest != self.cache_key.object_digest
            or provider.id != self.cache_key.provider_id
            or provider.version != self.cache_key.provider_version
            or provider.rules_digest != self.cache_key.rules_digest
        ):
            raise ValueError("security attestation does not bind its cache identity")


def attestation_value(value: SecurityAttestation) -> JsonObject:
    return JsonObject(
        (
            ("assessment", assessment_value(value.assessment)),
            ("cache_key", cache_key_value(value.cache_key)),
            ("origin", origin_value(value.origin)),
            ("schema_version", value.schema_version),
        )
    )


def attestation_digest(value: SecurityAttestation) -> ObjectDigest:
    return json_digest(attestation_value(value))


@dataclass(frozen=True, slots=True)
class SecurityIndexEntry:
    cache_key: AssessmentCacheKey
    attestation_digest: ObjectDigest
    path: SafeRelativePath

    def __post_init__(self) -> None:
        expected = f"security/attestations/{self.attestation_digest.value}.json"
        if (
            not isinstance(self.cache_key, AssessmentCacheKey)
            or not _valid_digest(self.attestation_digest)
            or not isinstance(self.path, SafeRelativePath)
            or str(self.path) != expected
        ):
            raise ValueError("security index entry is invalid")

    @property
    def identity_digest(self) -> ObjectDigest:
        return cache_key_digest(self.cache_key)


def index_entry_value(value: SecurityIndexEntry) -> JsonObject:
    return JsonObject(
        (
            ("attestation_digest", str(value.attestation_digest)),
            ("cache_key", cache_key_value(value.cache_key)),
            ("path", str(value.path)),
        )
    )


@dataclass(frozen=True, slots=True)
class SecurityIndex:
    schema_version: int
    registry_id: SourceId
    registry_inputs_digest: ObjectDigest
    entries: tuple[SecurityIndexEntry, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.entries, tuple) or any(
            not isinstance(item, SecurityIndexEntry) for item in self.entries
        ):
            raise ValueError("security index entries are invalid")
        entries = tuple(sorted(self.entries, key=lambda item: str(item.identity_digest)))
        identities = tuple(item.identity_digest for item in entries)
        paths = tuple(item.path for item in entries)
        if (
            self.schema_version != 1
            or not isinstance(self.registry_id, SourceId)
            or _SOURCE_RE.fullmatch(self.registry_id.value) is None
            or not _valid_digest(self.registry_inputs_digest)
            or len(entries) > _MAX_INDEX_ENTRIES
            or len(set(identities)) != len(identities)
            or len(set(paths)) != len(paths)
        ):
            raise ValueError("security index is invalid")
        object.__setattr__(self, "entries", entries)


@dataclass(frozen=True, slots=True)
class VerifiedSecurityIndex:
    index: SecurityIndex
    attestations: tuple[SecurityAttestation, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.index, SecurityIndex)
            or not isinstance(self.attestations, tuple)
            or len(self.attestations) != len(self.index.entries)
            or any(
                attestation.cache_key != entry.cache_key
                or attestation_digest(attestation) != entry.attestation_digest
                for entry, attestation in zip(self.index.entries, self.attestations, strict=True)
            )
        ):
            raise ValueError("verified security index is inconsistent")


def security_index_value(value: SecurityIndex) -> JsonObject:
    return JsonObject(
        (
            ("entries", JsonArray(tuple(index_entry_value(item) for item in value.entries))),
            ("registry_id", value.registry_id.value),
            ("registry_inputs_digest", str(value.registry_inputs_digest)),
            ("schema_version", value.schema_version),
        )
    )


class EvidenceFreshness(str, Enum):
    CURRENT = "current"
    STALE = "stale"


class AttestationTrust(str, Enum):
    UNVERIFIED = "unverified"
    LOCAL = "local"
    REGISTRY_REVIEWED = "registry-reviewed"
    COMPANY_REVIEWED = "company-reviewed"


@dataclass(frozen=True, slots=True)
class AttestationTrustContext:
    source_id: SourceId
    registry_inputs_digest: ObjectDigest
    trust: TrustClass

    def __post_init__(self) -> None:
        if (
            not isinstance(self.source_id, SourceId)
            or _SOURCE_RE.fullmatch(self.source_id.value) is None
            or not _valid_digest(self.registry_inputs_digest)
            or not isinstance(self.trust, TrustClass)
        ):
            raise ValueError("attestation trust context is invalid")


@dataclass(frozen=True, slots=True)
class ResolvedAttestation:
    attestation: SecurityAttestation
    freshness: EvidenceFreshness
    trust: AttestationTrust
    assessment: SecurityAssessment
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        reasons = tuple(sorted(set(self.reasons)))
        if (
            not isinstance(self.attestation, SecurityAttestation)
            or not isinstance(self.freshness, EvidenceFreshness)
            or not isinstance(self.trust, AttestationTrust)
            or not isinstance(self.assessment, SecurityAssessment)
            or not reasons
            or any(not reason or "\n" in reason or "\r" in reason for reason in reasons)
            or (
                self.freshness is EvidenceFreshness.CURRENT
                and self.assessment.status is AssessmentStatus.STALE
            )
            or (
                self.freshness is EvidenceFreshness.STALE
                and self.assessment.status is not AssessmentStatus.STALE
            )
        ):
            raise ValueError("resolved attestation is invalid")
        object.__setattr__(self, "reasons", reasons)


def _derived_trust(
    origin: AttestationOrigin,
    context: AttestationTrustContext | None,
) -> tuple[AttestationTrust, str]:
    if origin.kind is AttestationOriginKind.LOCAL:
        return AttestationTrust.LOCAL, "Evidence was produced locally."
    exact_context = (
        context is not None
        and context.source_id == origin.source_id
        and context.registry_inputs_digest == origin.registry_inputs_digest
    )
    if exact_context and context is not None:
        if context.trust is TrustClass.COMPANY_REVIEWED:
            return (
                AttestationTrust.COMPANY_REVIEWED,
                "Local policy trusts the exact publisher as company-reviewed.",
            )
        if context.trust is TrustClass.REGISTRY_REVIEWED:
            return (
                AttestationTrust.REGISTRY_REVIEWED,
                "Local policy trusts the exact publisher as registry-reviewed.",
            )
    return (
        AttestationTrust.UNVERIFIED,
        "Registry evidence has no matching reviewed local trust context.",
    )


def resolve_attestation(
    attestation: SecurityAttestation,
    expected_key: AssessmentCacheKey,
    *,
    trust_context: AttestationTrustContext | None,
) -> ResolvedAttestation:
    """Resolve freshness and trust without accepting self-authored trust from the document."""

    current = attestation.cache_key == expected_key
    assessment = (
        attestation.assessment if current else mark_assessment_stale_value(attestation.assessment)
    )
    trust, trust_reason = _derived_trust(attestation.origin, trust_context)
    freshness = EvidenceFreshness.CURRENT if current else EvidenceFreshness.STALE
    freshness_reason = (
        "Attestation cache identity matches current object, provider, rules, options, and policy."
        if current
        else "Attestation cache identity differs from current object, provider, rules, options, or policy."
    )
    return ResolvedAttestation(
        attestation,
        freshness,
        trust,
        assessment,
        (freshness_reason, trust_reason),
    )


__all__ = [
    "AssessmentCacheKey",
    "AttestationOrigin",
    "AttestationOriginKind",
    "AttestationTrust",
    "AttestationTrustContext",
    "EvidenceFreshness",
    "ResolvedAttestation",
    "SecurityAttestation",
    "SecurityIndex",
    "SecurityIndexEntry",
    "VerifiedSecurityIndex",
    "attestation_digest",
    "attestation_value",
    "cache_key_digest",
    "cache_key_value",
    "index_entry_value",
    "origin_value",
    "resolve_attestation",
    "security_index_value",
]
