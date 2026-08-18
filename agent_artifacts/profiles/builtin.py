"""Built-in harness profiles — data (WP-8). Adding a harness = adding a record here (docs/design/DESIGN.md §11)."""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

from .model import (
    CopyTarget,
    GuidelineTarget,
    HookTarget,
    MemoryTarget,
    MergeSpec,
    Profile,
    ProfileTargets,
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
        events=MappingProxyType(
            {
                "PreToolUse": "hooks.PreToolUse",
                "PostToolUse": "hooks.PostToolUse",
                "Stop": "hooks.Stop",
            }
        ),
        merge=MergeSpec(
            file=".claude/settings.json",
            json_path="hooks.PreToolUse",
            mode="list",
            identity=("matcher", "command"),
            entry_template=MappingProxyType(
                {
                    "matcher": "${matcher}",
                    "hooks": [{"type": "command", "command": "${command}"}],
                }
            ),
        ),
    ),
    memory=MemoryTarget(kind="file", dest="CLAUDE.md"),
    user=ProfileTargets(
        skills=CopyTarget(dir="~/.claude/skills/<name>/"),
        guidelines=GuidelineTarget(dest="~/.claude/rules/"),
        mcp=MergeSpec(file="~/.claude.json", json_path="mcpServers", mode="key"),
        hooks=HookTarget(
            scripts_dir="~/.claude/hooks/<name>/",
            events=MappingProxyType(
                {
                    "PreToolUse": "hooks.PreToolUse",
                    "PostToolUse": "hooks.PostToolUse",
                    "Stop": "hooks.Stop",
                }
            ),
            merge=MergeSpec(
                file="~/.claude/settings.json",
                json_path="hooks.PreToolUse",
                mode="list",
                identity=("matcher", "command"),
                entry_template=MappingProxyType(
                    {
                        "matcher": "${matcher}",
                        "hooks": [{"type": "command", "command": "${command}"}],
                    }
                ),
            ),
        ),
        memory=MemoryTarget(kind="file", dest="~/.claude/CLAUDE.md"),
    ),
)

# --------------------------------------------------------------------------- #
# OpenCode                                                                     #
# --------------------------------------------------------------------------- #
# NOTE: OpenCode paths are best-effort defaults (docs/design/DESIGN.md §19). The exact MCP
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
        events=MappingProxyType(
            {
                "PreToolUse": "hooks.PreToolUse",
                "PostToolUse": "hooks.PostToolUse",
                "Stop": "hooks.Stop",
            }
        ),
        merge=MergeSpec(
            file="opencode.json",
            json_path="hooks",
            mode="list",
            identity=("matcher", "command"),
            entry_template=MappingProxyType(
                {
                    "matcher": "${matcher}",
                    "command": "${command}",
                }
            ),
        ),
    ),
    memory=MemoryTarget(kind="file", dest="AGENTS.md"),
    user=ProfileTargets(
        skills=CopyTarget(dir="~/.config/opencode/skills/<name>/"),
        mcp=MergeSpec(
            file="~/.config/opencode/opencode.json",
            json_path="mcp",
            mode="key",
        ),
        memory=MemoryTarget(kind="file", dest="~/.config/opencode/AGENTS.md"),
        unsupported=MappingProxyType(
            {
                "guideline": "OpenCode has no standalone user-global guideline discovery target; use global AGENTS.md",
                "hook": "catalog hook descriptors are not OpenCode plugin modules",
            }
        ),
    ),
)

# --------------------------------------------------------------------------- #
# Tabnine                                                                      #
# --------------------------------------------------------------------------- #
# Paths corrected against the official Tabnine CLI docs (docs/design/DESIGN-memory.md §6).
# Skills (.tabnine/agent/skills/) and guidelines (copy → .tabnine/guidelines/)
# were already correct and are kept; MCP and hooks are corrected below.
_TABNINE = Profile(
    name="tabnine",
    skills=CopyTarget(dir=".tabnine/agent/skills/<name>/"),
    guidelines=GuidelineTarget(dest=".tabnine/guidelines/"),
    # Tabnine's MCP contract is the standalone mcp_servers.json at project or home scope.
    # settings.json is the hierarchical CLI settings document, not the documented server store.
    mcp=MergeSpec(
        file=".tabnine/mcp_servers.json",
        json_path="mcpServers",
        mode="key",
    ),
    # Hooks live in settings.json under hooks.<event>; abstract events map to
    # Tabnine's BeforeTool/AfterTool/SessionEnd (docs/design/DESIGN-memory.md §6.2).
    hooks=HookTarget(
        scripts_dir=".tabnine/agent/hooks/<name>/",
        events=MappingProxyType(
            {
                "PreToolUse": "hooks.BeforeTool",
                "PostToolUse": "hooks.AfterTool",
                "Stop": "hooks.SessionEnd",
            }
        ),
        merge=MergeSpec(
            file=".tabnine/agent/settings.json",
            json_path="hooks.BeforeTool",
            mode="list",
            identity=("matcher", "command"),
            entry_template=MappingProxyType(
                {
                    "matcher": "${matcher}",
                    "command": "${command}",
                }
            ),
        ),
    ),
    memory=MemoryTarget(kind="file", dest="TABNINE.md"),
    user=ProfileTargets(
        guidelines=GuidelineTarget(dest="~/.tabnine/guidelines/"),
        mcp=MergeSpec(
            file="~/.tabnine/mcp_servers.json",
            json_path="mcpServers",
            mode="key",
        ),
        unsupported=MappingProxyType(
            {
                "skill": "Tabnine does not document an Agent Skills discovery location",
                "hook": "Tabnine CLI does not document a user-global hook discovery target",
                "memory": "Tabnine CLI documents project-root TABNINE.md, not a global memory file",
            }
        ),
    ),
)

# --------------------------------------------------------------------------- #
# Mistral Vibe                                                                 #
# --------------------------------------------------------------------------- #
# Partial profile (docs/design/DESIGN-memory.md §7): memory/skills/guidelines are supported;
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
    user=ProfileTargets(
        skills=CopyTarget(dir="~/.vibe/skills/<name>/"),
        unsupported=MappingProxyType(
            {
                "guideline": "Vibe does not document a user-global standalone guideline target",
                "mcp": "Vibe user MCP configuration is TOML; the zero-dependency merge core is JSON-only",
                "hook": "Vibe user hooks are TOML; the zero-dependency merge core is JSON-only",
                "memory": "Vibe has no documented always-loaded global instruction file",
            }
        ),
    ),
)

# --------------------------------------------------------------------------- #
# Public API                                                                   #
# --------------------------------------------------------------------------- #
_BUILTINS: Mapping[str, Profile] = MappingProxyType(
    {
        "claude": _CLAUDE,
        "opencode": _OPENCODE,
        "tabnine": _TABNINE,
        "vibe": _VIBE,
    }
)


def builtin() -> Mapping[str, Profile]:
    """Return the built-in profiles: claude, opencode, tabnine, vibe."""
    return _BUILTINS
