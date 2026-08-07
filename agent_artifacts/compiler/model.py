"""Frozen type-state values for deterministic compiler orchestration."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Generic, TypeVar

from agent_artifacts.domain.diagnostics import Diagnostic, Severity, sort_diagnostics
from agent_artifacts.domain.identifiers import ObjectDigest, SourceAlias
from agent_artifacts.protocol.hashing import json_digest, sha256_bytes
from agent_artifacts.protocol.json import JsonArray, JsonObject
from agent_artifacts.protocol.native_tree import SourceSnapshot

_HEX_64 = re.compile(r"^[0-9a-f]{64}$")


class CompilerMode(str, Enum):
    CONSUMER = "consumer"
    MAINTAINER = "maintainer"


class CompilerPhase(str, Enum):
    ACQUIRE = "acquire"
    PARSE = "parse"
    HANDSHAKE = "handshake"
    RESOLVE = "resolve"
    NORMALIZE = "normalize"
    VALIDATE = "validate"
    INDEX = "index"
    MATERIALIZE = "materialize"
    PUBLISH = "publish"


class PhaseStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


def _valid_digest(digest: ObjectDigest) -> bool:
    return digest.algorithm == "sha256" and _HEX_64.fullmatch(digest.value) is not None


def _require_digest(digest: ObjectDigest, label: str) -> None:
    if not _valid_digest(digest):
        raise ValueError(f"{label} must be a canonical SHA-256 digest")


@dataclass(frozen=True, slots=True)
class SourceRequest:
    alias: SourceAlias
    locator: str
    locked_revision: str | None = None
    expected_snapshot_digest: ObjectDigest | None = None

    def __post_init__(self) -> None:
        if not self.alias.value or not self.locator:
            raise ValueError("source alias and locator must be non-empty")
        if self.locked_revision is not None and (
            not self.locked_revision or "\n" in self.locked_revision or "\r" in self.locked_revision
        ):
            raise ValueError("locked revision must be one non-empty line")
        if self.expected_snapshot_digest is not None:
            _require_digest(self.expected_snapshot_digest, "expected snapshot digest")


@dataclass(frozen=True, slots=True)
class CompilerRequest:
    build_key: str
    mode: CompilerMode
    sources: tuple[SourceRequest, ...]
    options_digest: ObjectDigest

    def __post_init__(self) -> None:
        if not self.build_key or "\n" in self.build_key or "\r" in self.build_key:
            raise ValueError("build key must be one non-empty line")
        if not isinstance(self.mode, CompilerMode):
            raise ValueError("compiler mode is invalid")
        _require_digest(self.options_digest, "options digest")
        ordered = tuple(sorted(self.sources, key=lambda source: source.alias.value))
        aliases = tuple(source.alias.value for source in ordered)
        if len(set(aliases)) != len(aliases):
            raise ValueError("compiler source aliases must be unique")
        object.__setattr__(self, "sources", ordered)


@dataclass(frozen=True, slots=True)
class AcquiredSource:
    alias: SourceAlias
    resolved_revision: str
    snapshot_digest: ObjectDigest
    snapshot: SourceSnapshot

    def __post_init__(self) -> None:
        if (
            not self.alias.value
            or not self.resolved_revision
            or "\n" in self.resolved_revision
            or "\r" in self.resolved_revision
        ):
            raise ValueError("acquired source identity must be non-empty")
        _require_digest(self.snapshot_digest, "snapshot digest")
        if not isinstance(self.snapshot, SourceSnapshot):
            raise ValueError("acquired source requires a SourceSnapshot")


@dataclass(frozen=True, slots=True)
class AcquiredCompilation:
    sources: tuple[AcquiredSource, ...]
    input_digest: ObjectDigest

    def __post_init__(self) -> None:
        _require_digest(self.input_digest, "compiler input digest")
        ordered = tuple(sorted(self.sources, key=lambda source: source.alias.value))
        aliases = tuple(source.alias.value for source in ordered)
        if len(set(aliases)) != len(aliases):
            raise ValueError("acquired source aliases must be unique")
        object.__setattr__(self, "sources", ordered)


@dataclass(frozen=True, slots=True)
class CompilerContext:
    build_key: str
    mode: CompilerMode
    options_digest: ObjectDigest
    input_digest: ObjectDigest

    def __post_init__(self) -> None:
        if not self.build_key or "\n" in self.build_key or "\r" in self.build_key:
            raise ValueError("compiler context build key must be one non-empty line")
        if not isinstance(self.mode, CompilerMode):
            raise ValueError("compiler context mode is invalid")
        _require_digest(self.options_digest, "compiler options digest")
        _require_digest(self.input_digest, "compiler input digest")


T_co = TypeVar("T_co", covariant=True)
T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class PhaseOutput(Generic[T_co]):
    value: T_co
    digest: ObjectDigest
    diagnostics: tuple[Diagnostic, ...] = ()

    def __post_init__(self) -> None:
        _require_digest(self.digest, "phase output digest")
        object.__setattr__(self, "diagnostics", sort_diagnostics(self.diagnostics))


@dataclass(frozen=True, slots=True)
class ResolvedCompilation(Generic[T_co]):
    value: T_co
    frozen: bool


@dataclass(frozen=True, slots=True)
class ObjectPlan:
    digest: ObjectDigest
    content: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.content, bytes) or sha256_bytes(self.content) != self.digest:
            raise ValueError("object plan digest must bind its exact bytes")


@dataclass(frozen=True, slots=True)
class ObjectReceipt:
    digest: ObjectDigest

    def __post_init__(self) -> None:
        _require_digest(self.digest, "object receipt digest")


@dataclass(frozen=True, slots=True)
class CompilationCandidate:
    input_digest: ObjectDigest
    index_bytes: bytes
    index_digest: ObjectDigest
    objects: tuple[ObjectPlan, ...]

    def __post_init__(self) -> None:
        _require_digest(self.input_digest, "candidate input digest")
        if (
            not isinstance(self.index_bytes, bytes)
            or sha256_bytes(self.index_bytes) != self.index_digest
        ):
            raise ValueError("candidate index digest must bind its exact bytes")
        ordered = tuple(sorted(self.objects, key=lambda item: str(item.digest)))
        digests = tuple(item.digest for item in ordered)
        if len(set(digests)) != len(digests):
            raise ValueError("candidate object digests must be unique")
        object.__setattr__(self, "objects", ordered)


@dataclass(frozen=True, slots=True)
class PublishRequest:
    build_key: str
    input_digest: ObjectDigest
    index_bytes: bytes
    index_digest: ObjectDigest
    object_digests: tuple[ObjectDigest, ...]
    snapshot_digest: ObjectDigest

    def __post_init__(self) -> None:
        if not self.build_key:
            raise ValueError("publish build key must be non-empty")
        _require_digest(self.input_digest, "publish input digest")
        _require_digest(self.index_digest, "publish index digest")
        _require_digest(self.snapshot_digest, "publish snapshot digest")
        if sha256_bytes(self.index_bytes) != self.index_digest:
            raise ValueError("publish index digest must bind its exact bytes")
        ordered = tuple(sorted(self.object_digests, key=str))
        for digest in ordered:
            _require_digest(digest, "publish object digest")
        if len(set(ordered)) != len(ordered):
            raise ValueError("publish object digests must be unique")
        object.__setattr__(self, "object_digests", ordered)
        expected = _snapshot_digest(
            self.build_key,
            self.input_digest,
            self.index_digest,
            ordered,
        )
        if expected != self.snapshot_digest:
            raise ValueError("publish snapshot digest must bind all publication inputs")


@dataclass(frozen=True, slots=True)
class PublishReceipt:
    snapshot_digest: ObjectDigest

    def __post_init__(self) -> None:
        _require_digest(self.snapshot_digest, "publish receipt digest")


@dataclass(frozen=True, slots=True)
class PhaseReport:
    phase: CompilerPhase
    status: PhaseStatus
    input_digest: ObjectDigest | None = None
    output_digest: ObjectDigest | None = None
    diagnostics: tuple[Diagnostic, ...] = ()

    def __post_init__(self) -> None:
        if self.input_digest is not None:
            _require_digest(self.input_digest, "phase input digest")
        if self.output_digest is not None:
            _require_digest(self.output_digest, "phase output digest")
        object.__setattr__(self, "diagnostics", sort_diagnostics(self.diagnostics))


@dataclass(frozen=True, slots=True)
class CompilerRun:
    reports: tuple[PhaseReport, ...]
    candidate: CompilationCandidate | None = None
    publication: PublishReceipt | None = None
    diagnostics: tuple[Diagnostic, ...] = field(init=False)

    def __post_init__(self) -> None:
        positions = {phase: index for index, phase in enumerate(CompilerPhase)}
        ordered = tuple(sorted(self.reports, key=lambda report: positions[report.phase]))
        if tuple(report.phase for report in ordered) != tuple(CompilerPhase):
            raise ValueError("compiler run must contain exactly one report for every phase")
        if self.publication is not None and self.candidate is None:
            raise ValueError("publication requires a compilation candidate")
        object.__setattr__(self, "reports", ordered)
        object.__setattr__(
            self,
            "diagnostics",
            sort_diagnostics(diagnostic for report in ordered for diagnostic in report.diagnostics),
        )

    @property
    def succeeded(self) -> bool:
        return self.publication is not None and not any(
            diagnostic.severity is Severity.ERROR for diagnostic in self.diagnostics
        )


def phase_output(
    value: T,
    canonical_bytes: bytes,
    *,
    diagnostics: tuple[Diagnostic, ...] = (),
) -> PhaseOutput[T]:
    return PhaseOutput(value, sha256_bytes(canonical_bytes), diagnostics)


def object_plan(content: bytes) -> ObjectPlan:
    return ObjectPlan(sha256_bytes(content), content)


def acquired_compilation(
    sources: tuple[AcquiredSource, ...],
    options_digest: ObjectDigest,
) -> AcquiredCompilation:
    _require_digest(options_digest, "compiler options digest")
    ordered = tuple(sorted(sources, key=lambda source: source.alias.value))
    source_values = JsonArray(
        tuple(
            JsonObject(
                (
                    ("alias", source.alias.value),
                    ("resolved_revision", source.resolved_revision),
                    ("snapshot_digest", str(source.snapshot_digest)),
                )
            )
            for source in ordered
        )
    )
    digest = json_digest(
        JsonObject(
            (
                ("options_digest", str(options_digest)),
                ("sources", source_values),
            )
        )
    )
    return AcquiredCompilation(ordered, digest)


def compilation_candidate(
    *,
    input_digest: ObjectDigest,
    index_bytes: bytes,
    objects: tuple[ObjectPlan, ...],
) -> CompilationCandidate:
    return CompilationCandidate(input_digest, index_bytes, sha256_bytes(index_bytes), objects)


def materialization_digest(receipts: tuple[ObjectReceipt, ...]) -> ObjectDigest:
    return json_digest(
        JsonArray(
            tuple(
                str(receipt.digest)
                for receipt in sorted(receipts, key=lambda item: str(item.digest))
            )
        )
    )


def _snapshot_digest(
    build_key: str,
    input_digest: ObjectDigest,
    index_digest: ObjectDigest,
    object_digests: tuple[ObjectDigest, ...],
) -> ObjectDigest:
    return json_digest(
        JsonObject(
            (
                ("build_key", build_key),
                ("input_digest", str(input_digest)),
                ("index_digest", str(index_digest)),
                ("object_digests", JsonArray(tuple(str(item) for item in object_digests))),
            )
        )
    )


def publication_request(candidate: CompilationCandidate, build_key: str) -> PublishRequest:
    object_digests = tuple(item.digest for item in candidate.objects)
    return PublishRequest(
        build_key,
        candidate.input_digest,
        candidate.index_bytes,
        candidate.index_digest,
        object_digests,
        _snapshot_digest(
            build_key,
            candidate.input_digest,
            candidate.index_digest,
            object_digests,
        ),
    )
