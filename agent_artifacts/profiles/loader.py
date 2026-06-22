"""Profile loader — WP-8. Built-ins overlaid by ``<project>/.agent-artifacts/profiles.json``."""

from __future__ import annotations

import json
import os
from types import MappingProxyType
from typing import Any, Mapping, Optional

from ..model import (
    AgentsTarget,
    CopyTarget,
    GuidelineTarget,
    HookTarget,
    MergeSpec,
    Profile,
)
from .builtin import builtin


def _merge_spec_from_dict(d: Mapping[str, Any]) -> MergeSpec:
    """Build a ``MergeSpec`` from a JSON-parsed dict."""
    return MergeSpec(
        file=d["file"],
        json_path=d["json_path"],
        mode=d["mode"],
        identity=tuple(d.get("identity", ())),
        entry_template=(
            MappingProxyType(d["entry_template"])
            if d.get("entry_template") is not None
            else None
        ),
    )


def _hook_target_from_dict(d: Mapping[str, Any]) -> HookTarget:
    """Build a ``HookTarget`` from a JSON-parsed dict."""
    return HookTarget(
        scripts_dir=d["scripts_dir"],
        events=MappingProxyType(d["events"]),
        merge=_merge_spec_from_dict(d["merge"]),
    )


def _profile_from_dict(record: Mapping[str, Any]) -> Profile:
    """Build a ``Profile`` from a JSON-parsed dict (the §11 record shape).

    Every artifact-type section is **optional**: a missing key yields ``None``
    (this harness does not support that type — DESIGN-agents.md §5), so partial
    profiles load without a ``KeyError``.

    Expected JSON shape (a partial ``vibe``-style profile + an ``agents`` target)::

        {
          "name": "vibe",
          "skills":     { "dir": ".vibe/skills/<name>/" },
          "guidelines": { "mode": "append-sentinel", "dest": "AGENTS.md" },
          "agents":     { "kind": "file", "dest": "AGENTS.md" }
          # no "mcp" / "hooks" keys -> mcp=None, hooks=None
        }
    """
    skills_d = record.get("skills")
    guide_d = record.get("guidelines")
    mcp_d = record.get("mcp")
    hooks_d = record.get("hooks")
    agents_d = record.get("agents")

    return Profile(
        name=record["name"],
        skills=CopyTarget(dir=skills_d["dir"]) if skills_d is not None else None,
        guidelines=(
            GuidelineTarget(mode=guide_d["mode"], dest=guide_d["dest"])
            if guide_d is not None
            else None
        ),
        mcp=_merge_spec_from_dict(mcp_d) if mcp_d is not None else None,
        hooks=_hook_target_from_dict(hooks_d) if hooks_d is not None else None,
        agents=(
            AgentsTarget(kind=agents_d["kind"], dest=agents_d["dest"])
            if agents_d is not None
            else None
        ),
    )


def load_profiles(project: Optional[str] = None) -> Mapping[str, Profile]:
    """Built-in profiles merged with the project's override file (pure merge over data).

    If *project* is given and ``<project>/.agent-artifacts/profiles.json`` exists,
    parse it and overlay/add those profiles over the built-ins. User records
    replace or add by name.  Missing project or file -> just the built-ins.
    """
    base = dict(builtin())  # mutable copy for merging

    if project is not None:
        override_path = os.path.join(project, ".agent-artifacts", "profiles.json")
        if os.path.isfile(override_path):
            with open(override_path, encoding="utf-8") as fh:
                overrides: Mapping[str, Any] = json.load(fh)
            for name, record in overrides.items():
                base[name] = _profile_from_dict(record)

    return MappingProxyType(base)
