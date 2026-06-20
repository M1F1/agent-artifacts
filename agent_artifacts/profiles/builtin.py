"""Built-in harness profiles — data (WP-8). Adding a harness = adding a record here (DESIGN.md §11)."""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

from ..model import CopyTarget, GuidelineTarget, HookTarget, MergeSpec, Profile

# --------------------------------------------------------------------------- #
# Claude Code                                                                  #
# --------------------------------------------------------------------------- #
_CLAUDE = Profile(
    name="claude",
    skills=CopyTarget(dir=".claude/skills/<name>/"),
    guidelines=GuidelineTarget(mode="append-sentinel", dest="CLAUDE.md"),
    mcp=MergeSpec(file=".mcp.json", json_path="mcpServers", mode="key"),
    hooks=HookTarget(
        scripts_dir=".claude/hooks/<name>/",
        events=MappingProxyType({
            "PreToolUse": "hooks.PreToolUse",
            "PostToolUse": "hooks.PostToolUse",
            "Stop": "hooks.Stop",
        }),
        merge=MergeSpec(
            file=".claude/settings.json",
            json_path="hooks.PreToolUse",
            mode="list",
            identity=("matcher", "command"),
            entry_template=MappingProxyType({
                "matcher": "${matcher}",
                "hooks": [{"type": "command", "command": "${command}"}],
            }),
        ),
    ),
)

# --------------------------------------------------------------------------- #
# OpenCode                                                                     #
# --------------------------------------------------------------------------- #
# NOTE: OpenCode paths are best-effort defaults (DESIGN.md §19). The exact MCP
# key in opencode.json ("mcp") and hook/plugin event model need verification
# against a live OpenCode environment.
_OPENCODE = Profile(
    name="opencode",
    skills=CopyTarget(dir=".opencode/skills/<name>/"),
    guidelines=GuidelineTarget(mode="append-sentinel", dest="AGENTS.md"),
    mcp=MergeSpec(file="opencode.json", json_path="mcp", mode="key"),
    hooks=HookTarget(
        scripts_dir=".opencode/hooks/<name>/",
        # Best-effort event mapping — OpenCode's hook event model is unverified (§19).
        events=MappingProxyType({
            "PreToolUse": "hooks.PreToolUse",
            "PostToolUse": "hooks.PostToolUse",
            "Stop": "hooks.Stop",
        }),
        merge=MergeSpec(
            file="opencode.json",
            json_path="hooks",
            mode="list",
            identity=("matcher", "command"),
            entry_template=MappingProxyType({
                "matcher": "${matcher}",
                "command": "${command}",
            }),
        ),
    ),
)

# --------------------------------------------------------------------------- #
# Tabnine                                                                      #
# --------------------------------------------------------------------------- #
# NOTE: Tabnine MCP and hooks paths are best-effort defaults that need
# verification against a live Tabnine environment (DESIGN.md §19). The skills
# path (.tabnine/agent/skills/) and guidelines mode (copy) are from the §11
# table; MCP and hooks config locations are unverified.
_TABNINE = Profile(
    name="tabnine",
    skills=CopyTarget(dir=".tabnine/agent/skills/<name>/"),
    guidelines=GuidelineTarget(mode="copy", dest=".tabnine/guidelines/"),
    # MCP config location for Tabnine is unverified — best-effort default.
    mcp=MergeSpec(
        file=".tabnine/config.json",
        json_path="mcpServers",
        mode="key",
    ),
    # Hooks for Tabnine are unverified — best-effort default.
    hooks=HookTarget(
        scripts_dir=".tabnine/hooks/<name>/",
        events=MappingProxyType({
            "PreToolUse": "hooks.PreToolUse",
        }),
        merge=MergeSpec(
            file=".tabnine/config.json",
            json_path="hooks",
            mode="list",
            identity=("matcher", "command"),
            entry_template=MappingProxyType({
                "matcher": "${matcher}",
                "command": "${command}",
            }),
        ),
    ),
)

# --------------------------------------------------------------------------- #
# Public API                                                                   #
# --------------------------------------------------------------------------- #
_BUILTINS: Mapping[str, Profile] = MappingProxyType({
    "claude": _CLAUDE,
    "opencode": _OPENCODE,
    "tabnine": _TABNINE,
})


def builtin() -> Mapping[str, Profile]:
    """Return the built-in profiles: opencode, claude, tabnine."""
    return _BUILTINS
