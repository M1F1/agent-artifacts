"""Managed local/Git source acquisition bounded context."""

from .model import (
    CurrentSource,
    HealthStatus,
    SnapshotLimits,
    SourceCandidate,
    SourceInstanceId,
    SourceStorePaths,
    SyncDisposition,
    SyncFallback,
    ValidatedSourceCandidate,
    assess_source_health,
    make_source_candidate,
    source_instance_id,
    source_store_paths,
)

__all__ = [
    "CurrentSource",
    "HealthStatus",
    "SnapshotLimits",
    "SourceCandidate",
    "SourceInstanceId",
    "SourceStorePaths",
    "SyncDisposition",
    "SyncFallback",
    "ValidatedSourceCandidate",
    "assess_source_health",
    "make_source_candidate",
    "source_instance_id",
    "source_store_paths",
]
