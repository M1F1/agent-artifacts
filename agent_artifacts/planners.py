"""Type planners — pure (WP-5). Compose policy (WP-2) + merge (WP-3) into a `Plan`.

Each `plan_<type>` takes the resolved artifact plus the bytes/values read from the source
and the current on-disk state, and returns ``Result[Plan]``. The hook planner emits both
copy actions (scripts) and a `MergeJson` action (registration) — the hybrid of DESIGN.md §5.4.
``plan_install`` is the top-level aggregator that accumulates errors across artifacts.
"""

from __future__ import annotations

from typing import Callable, Mapping

from .model import ArtifactType, Result

_TODO = "WP-5: not implemented"


def plan_skill(*args, **kwargs) -> Result:
    raise NotImplementedError(_TODO)


def plan_guideline(*args, **kwargs) -> Result:
    raise NotImplementedError(_TODO)


def plan_mcp(*args, **kwargs) -> Result:
    raise NotImplementedError(_TODO)


def plan_hook(*args, **kwargs) -> Result:
    raise NotImplementedError(_TODO)


PLANNERS: Mapping[ArtifactType, Callable[..., Result]] = {
    "skill": plan_skill,
    "guideline": plan_guideline,
    "mcp": plan_mcp,
    "hook": plan_hook,
}


def plan_install(request, catalog, files, profiles, manifest, configs) -> Result:
    """Top-level pure aggregator: resolve targets, dispatch via PLANNERS, accumulate errors."""
    raise NotImplementedError(_TODO)
