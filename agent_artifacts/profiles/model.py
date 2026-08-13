"""Canonical, data-only mapping from artifact kinds to harness destinations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping, Optional, Tuple

ArtifactKind = Literal["skill", "guideline", "mcp", "hook", "memory"]


@dataclass(frozen=True, slots=True)
class CopyTarget:
    """A directory target, optionally containing the literal ``<name>`` marker."""

    dir: str


@dataclass(frozen=True, slots=True)
class GuidelineTarget:
    """A directory where a guideline is copied as ``<artifact-name>.md``."""

    dest: str


@dataclass(frozen=True, slots=True)
class MergeSpec:
    """One JSON destination and its deterministic key- or list-merge rule."""

    file: str
    json_path: str
    mode: Literal["key", "list"]
    identity: Tuple[str, ...] = ()
    entry_template: Optional[Mapping[str, object]] = None


@dataclass(frozen=True, slots=True)
class HookTarget:
    scripts_dir: str
    events: Mapping[str, str]
    merge: MergeSpec


@dataclass(frozen=True, slots=True)
class MemoryTarget:
    """A shared instruction file or a directory of independent memory files."""

    kind: Literal["file", "dir"]
    dest: str


@dataclass(frozen=True, slots=True)
class ProfileTargets:
    """Explicit targets for a scope and reasons for unsupported artifact kinds."""

    skills: Optional[CopyTarget] = None
    guidelines: Optional[GuidelineTarget] = None
    mcp: Optional[MergeSpec] = None
    hooks: Optional[HookTarget] = None
    memory: Optional[MemoryTarget] = None
    unsupported: Mapping[ArtifactKind, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Profile:
    """A complete profile; the user projection is explicit rather than inferred."""

    name: str
    skills: Optional[CopyTarget] = None
    guidelines: Optional[GuidelineTarget] = None
    mcp: Optional[MergeSpec] = None
    hooks: Optional[HookTarget] = None
    memory: Optional[MemoryTarget] = None
    unsupported: Mapping[ArtifactKind, str] = field(default_factory=dict)
    user: Optional[ProfileTargets] = None
