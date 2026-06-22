"""Built-in harness profiles — data (WP-8). Adding a harness = adding a record here (DESIGN.md §11)."""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

from ..model import (
    MemoryTarget,
    CopyTarget,
    GuidelineTarget,
    HookTarget,
    MergeSpec,
    Profile,
)

# --------------------------------------------------------------------------- #
# Claude Code                                                                  #
# --------------------------------------------------------------------------- #
_CLAUDE = Profile(
    name="claude",
    skills=CopyTarget(dir=".claude/skills/<name>/"),
    # Guidelines are standalone reference docs in the worktree, NOT merged into the memory
    # file (CLAUDE.md) — so a guideline and the memory artifact never share/clobber a file.
    guidelines=GuidelineTarget(dest=".claude/guidelines/"),
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
    memory=MemoryTarget(kind="file", dest="CLAUDE.md"),
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
    guidelines=GuidelineTarget(dest=".opencode/guidelines/"),
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
    memory=MemoryTarget(kind="file", dest="AGENTS.md"),
)

# --------------------------------------------------------------------------- #
# Tabnine                                                                      #
# --------------------------------------------------------------------------- #
# Paths corrected against the official Tabnine CLI docs (DESIGN-memory.md §6).
# Skills (.tabnine/agent/skills/) and guidelines (copy → .tabnine/guidelines/)
# were already correct and are kept; MCP and hooks are corrected below.
_TABNINE = Profile(
    name="tabnine",
    skills=CopyTarget(dir=".tabnine/agent/skills/<name>/"),
    guidelines=GuidelineTarget(dest=".tabnine/guidelines/"),
    # MCP target set to .tabnine/agent/settings.json · mcpServers per directive
    # (DESIGN-memory.md §6.1). DOC CAVEAT: the published docs put server
    # *definitions* in the standalone .tabnine/mcp_servers.json (key
    # "mcpServers"); settings.json documents a different "mcp" key (governance
    # only). Verify in-environment — switching the file later is a one-line
    # record change since this is a single MergeSpec.
    mcp=MergeSpec(
        file=".tabnine/agent/settings.json",
        json_path="mcpServers",
        mode="key",
    ),
    # Hooks live in settings.json under hooks.<event>; abstract events map to
    # Tabnine's BeforeTool/AfterTool/SessionEnd (DESIGN-memory.md §6.2).
    hooks=HookTarget(
        scripts_dir=".tabnine/agent/hooks/<name>/",
        events=MappingProxyType({
            "PreToolUse": "hooks.BeforeTool",
            "PostToolUse": "hooks.AfterTool",
            "Stop": "hooks.SessionEnd",
        }),
        merge=MergeSpec(
            file=".tabnine/agent/settings.json",
            json_path="hooks.BeforeTool",
            mode="list",
            identity=("matcher", "command"),
            entry_template=MappingProxyType({
                "matcher": "${matcher}",
                "command": "${command}",
            }),
        ),
    ),
    memory=MemoryTarget(kind="file", dest="TABNINE.md"),
)

# --------------------------------------------------------------------------- #
# Mistral Vibe                                                                 #
# --------------------------------------------------------------------------- #
# Partial profile (DESIGN-memory.md §7): memory/skills/guidelines are supported;
# mcp and hooks are intentionally None. Vibe stores MCP under [[mcp_servers]] in
# config.toml and hooks in .vibe/hooks.toml — both TOML. The merge engine emits
# JSON only and the stdlib has no TOML writer, so honoring the zero-dep rule
# they are deferred to a future MergeSpec.format="toml" (§7.2).
_VIBE = Profile(
    name="vibe",
    skills=CopyTarget(dir=".vibe/skills/<name>/"),
    guidelines=GuidelineTarget(dest=".vibe/guidelines/"),
    mcp=None,
    hooks=None,
    memory=MemoryTarget(kind="file", dest="AGENTS.md"),
)

# --------------------------------------------------------------------------- #
# Public API                                                                   #
# --------------------------------------------------------------------------- #
_BUILTINS: Mapping[str, Profile] = MappingProxyType({
    "claude": _CLAUDE,
    "opencode": _OPENCODE,
    "tabnine": _TABNINE,
    "vibe": _VIBE,
})


def builtin() -> Mapping[str, Profile]:
    """Return the built-in profiles: claude, opencode, tabnine, vibe."""
    return _BUILTINS
