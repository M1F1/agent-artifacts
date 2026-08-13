"""Pure project/user profile projection and support decisions (issue #19)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from agent_artifacts.install_state.model import InstallScope

from .model import (
    ArtifactKind,
    CopyTarget,
    GuidelineTarget,
    HookTarget,
    MemoryTarget,
    MergeSpec,
    Profile,
    ProfileTargets,
)

_TYPE_ATTR: Mapping[ArtifactKind, str] = {
    "skill": "skills",
    "guideline": "guidelines",
    "mcp": "mcp",
    "hook": "hooks",
    "memory": "memory",
}


@dataclass(frozen=True, slots=True)
class ScopeSupport:
    supported: bool
    reason: str = ""


def _user_path(path: str, home: str) -> str:
    """Resolve one explicit user target without consulting process-global HOME."""

    normalized_home = os.path.abspath(home)
    trailing_slash = path.endswith("/")
    if path == "~":
        resolved = normalized_home
    elif path.startswith("~/"):
        resolved = os.path.normpath(os.path.join(normalized_home, path[2:]))
    elif os.path.isabs(path):
        resolved = os.path.normpath(path)
    else:
        # Custom records may use home-relative paths, but built-ins always spell the boundary
        # explicitly with ``~/`` so they cannot accidentally mirror a project path.
        resolved = os.path.normpath(os.path.join(normalized_home, path))
    return resolved + os.sep if trailing_slash and not resolved.endswith(os.sep) else resolved


def _merge(spec: MergeSpec, home: str) -> MergeSpec:
    return MergeSpec(
        file=_user_path(spec.file, home),
        json_path=spec.json_path,
        mode=spec.mode,
        identity=spec.identity,
        entry_template=spec.entry_template,
    )


def _hook(target: HookTarget, home: str) -> HookTarget:
    return HookTarget(
        scripts_dir=_user_path(target.scripts_dir, home),
        events=target.events,
        merge=_merge(target.merge, home),
    )


def profile_for_scope(profile: Profile, scope: InstallScope, user_home: str) -> Profile:
    """Project is identity; user returns a planner-compatible profile with absolute targets."""

    if scope == "project":
        return profile
    targets = profile.user or ProfileTargets(
        unsupported={
            artifact_type: f"profile {profile.name!r} has no user-scope configuration"
            for artifact_type in _TYPE_ATTR
        }
    )
    return Profile(
        name=profile.name,
        skills=(
            CopyTarget(dir=_user_path(targets.skills.dir, user_home))
            if targets.skills is not None
            else None
        ),
        guidelines=(
            GuidelineTarget(dest=_user_path(targets.guidelines.dest, user_home))
            if targets.guidelines is not None
            else None
        ),
        mcp=_merge(targets.mcp, user_home) if targets.mcp is not None else None,
        hooks=_hook(targets.hooks, user_home) if targets.hooks is not None else None,
        memory=(
            MemoryTarget(
                kind=targets.memory.kind,
                dest=_user_path(targets.memory.dest, user_home),
            )
            if targets.memory is not None
            else None
        ),
        unsupported=targets.unsupported,
        user=targets,
    )


def support_for(profile: Profile, scope: InstallScope, artifact_type: ArtifactKind) -> ScopeSupport:
    """Return scope support without resolving a home path."""

    if scope == "project":
        supported = getattr(profile, _TYPE_ATTR[artifact_type]) is not None
        reason = profile.unsupported.get(artifact_type, "") if not supported else ""
        return ScopeSupport(supported, reason)

    targets = profile.user
    if targets is None:
        return ScopeSupport(False, f"profile {profile.name!r} has no user-scope configuration")
    supported = getattr(targets, _TYPE_ATTR[artifact_type]) is not None
    reason = targets.unsupported.get(artifact_type, "") if not supported else ""
    return ScopeSupport(supported, reason)
