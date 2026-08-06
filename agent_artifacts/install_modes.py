"""Pure install-mode capabilities shared by command and interactive adapters."""

from __future__ import annotations

from .model import ArtifactType

LINKABLE_ARTIFACT_TYPES = frozenset({"skill", "hook"})


def supports_symlink(artifact_type: ArtifactType) -> bool:
    """Whether an artifact type has a directory payload the core can live-link."""

    return artifact_type in LINKABLE_ARTIFACT_TYPES
