"""Application mapping from verified immutable store objects to analyzer inputs."""

from __future__ import annotations

from agent_artifacts.protocol.native_tree import SnapshotEntryKind
from agent_artifacts.store.model import StoredObject

from .analyzers import AnalyzerInput


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


__all__ = ["analyzer_input_from_stored_object"]
