"""Application mapping from verified immutable store objects to analyzer inputs."""

from __future__ import annotations

from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.protocol.hashing import sha256_bytes
from agent_artifacts.protocol.native_tree import SnapshotEntryKind
from agent_artifacts.protocol.paths import SafeRelativePath
from agent_artifacts.store.model import StoredObject

from .analyzers import AnalyzerInput
from .attestation_schema import parse_attestation
from .attestations import (
    AttestationOriginKind,
    SecurityIndex,
    VerifiedSecurityIndex,
)

SECURITY_INDEX_EVIDENCE_INVALID = DiagnosticCode("security-index-evidence-invalid")


def _error(message: str) -> Err:
    return Err((Diagnostic(SECURITY_INDEX_EVIDENCE_INVALID, Severity.ERROR, message),))


def analyzer_input_from_stored_object(
    stored: StoredObject,
    *,
    artifact_type: str,
) -> AnalyzerInput:
    """Bind an analyzer to the exact verified CAS object root and regular-file projection."""

    return AnalyzerInput(
        stored.candidate.digest,
        stored.root,
        artifact_type,
        tuple(
            (entry.path, len(entry.content))
            for entry in stored.candidate.entries
            if entry.kind is SnapshotEntryKind.FILE
        ),
        tuple(
            (entry.path, entry.content)
            for entry in stored.candidate.entries
            if entry.kind is SnapshotEntryKind.FILE
        ),
    )


def verify_security_index(
    index: SecurityIndex,
    documents: tuple[tuple[SafeRelativePath, bytes], ...],
) -> Result[VerifiedSecurityIndex]:
    """Verify exact indexed bytes and publisher identity without deriving publisher trust."""

    if not isinstance(documents, tuple) or any(
        not isinstance(item, tuple)
        or len(item) != 2
        or not isinstance(item[0], SafeRelativePath)
        or not isinstance(item[1], bytes)
        for item in documents
    ):
        return _error("security attestation documents are invalid")
    by_path = {path: data for path, data in documents}
    if len(by_path) != len(documents) or set(by_path) != {item.path for item in index.entries}:
        return _error("security index document paths are missing, extra, or duplicated")
    attestations = []
    for entry in index.entries:
        data = by_path[entry.path]
        if sha256_bytes(data) != entry.attestation_digest:
            return _error("security attestation bytes do not match the index digest")
        parsed = parse_attestation(data)
        if isinstance(parsed, Err):
            return _error("security attestation document is invalid")
        attestation = parsed.value
        origin = attestation.origin
        if (
            attestation.cache_key != entry.cache_key
            or origin.kind is not AttestationOriginKind.REGISTRY_CI
            or origin.source_id != index.registry_id
            or origin.registry_inputs_digest != index.registry_inputs_digest
        ):
            return _error("security attestation does not match its registry index identity")
        attestations.append(attestation)
    try:
        return Ok(VerifiedSecurityIndex(index, tuple(attestations)))
    except ValueError:
        return _error("verified security index is inconsistent")


__all__ = [
    "SECURITY_INDEX_EVIDENCE_INVALID",
    "analyzer_input_from_stored_object",
    "verify_security_index",
]
