"""Profile loader — WP-8. Built-ins overlaid by ``<project>/.agent-artifacts/profiles.json``."""

from __future__ import annotations

import json
import os
from types import MappingProxyType
from typing import Any, Mapping, Optional

from ..model import CopyTarget, GuidelineTarget, HookTarget, MergeSpec, Profile
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


def _profile_from_dict(record: Mapping[str, Any]) -> Profile:
    """Build a ``Profile`` from a JSON-parsed dict (the §11 record shape).

    Expected JSON shape (matching DESIGN.md §11)::

        {
          "name": "antigravity",
          "skills":     { "dir": ".antigravity/skills/<name>/" },
          "guidelines": { "mode": "append-sentinel", "dest": "AGENTS.md" },
          "mcp":        { "file": ".antigravity/config.json", "json_path": "mcp.servers", "mode": "key" },
          "hooks": {
            "scripts_dir": ".antigravity/hooks/<name>/",
            "events": { "PreToolUse": "hooks.PreToolUse" },
            "merge": { "file": "...", "json_path": "...", "mode": "list", ... }
          }
        }
    """
    skills_d = record["skills"]
    guide_d = record["guidelines"]
    mcp_d = record["mcp"]
    hooks_d = record["hooks"]

    return Profile(
        name=record["name"],
        skills=CopyTarget(dir=skills_d["dir"]),
        guidelines=GuidelineTarget(mode=guide_d["mode"], dest=guide_d["dest"]),
        mcp=_merge_spec_from_dict(mcp_d),
        hooks=HookTarget(
            scripts_dir=hooks_d["scripts_dir"],
            events=MappingProxyType(hooks_d["events"]),
            merge=_merge_spec_from_dict(hooks_d["merge"]),
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
