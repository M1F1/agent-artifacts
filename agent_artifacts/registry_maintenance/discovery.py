"""Conservative discovery of foreign repository shapes worth reviewing for vendoring.

Discovery is intentionally a suggestion layer.  It neither parses foreign content as trusted
metadata nor writes registry packages; it emits paths and stable proposed identities for the
existing vendoring planner to judge later.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from agent_artifacts.protocol.native_tree import SnapshotEntryKind, SourceSnapshot

_MEMORY_DOCUMENTS = frozenset({"AGENTS.md", "CLAUDE.md", "CONTEXT.md", "GEMINI.md", "TABNINE.md"})
_MCP_DOCUMENTS = frozenset({".mcp.json", "mcp.json", "mcp-servers.json", "mcp_servers.json"})
_GUIDELINE_DIRECTORIES = frozenset({"guideline", "guidelines", "rules"})


@dataclass(frozen=True, slots=True, order=True)
class VendorCandidate:
    kind: str
    name: str
    path: str
    reason: str


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not slug:
        slug = "artifact"
    if not slug[0].isalpha():
        slug = f"artifact-{slug}"
    return slug


def _proposed_name(kind: str, path: str) -> str:
    parts = path.split("/")
    filename = parts[-1]
    if kind == "skill" and len(parts) > 1:
        return _slug(parts[-2])
    if kind == "hook" and len(parts) > 1:
        return _slug(parts[-2])
    if kind == "memory":
        parent = "-".join(parts[:-1])
        stem = filename.removesuffix(".md")
        return _slug(f"{parent}-{stem}" if parent else stem)
    stem = filename.rsplit(".", 1)[0]
    parent = "-".join(parts[:-1])
    return _slug(f"{parent}-{stem}" if parent else stem)


def discover_vendor_candidates(snapshot: SourceSnapshot) -> tuple[VendorCandidate, ...]:
    """Return deterministic, review-only candidates from conventional foreign file shapes."""

    found: list[tuple[str, str, str]] = []
    for entry in snapshot.entries:
        if entry.kind is not SnapshotEntryKind.FILE:
            continue
        path = str(entry.path)
        parts = path.split("/")
        filename = parts[-1]
        parents = frozenset(part.lower() for part in parts[:-1])
        if filename == "SKILL.md":
            # A skill is a directory package when possible; root-level SKILL.md is a supported
            # single-file subtree and keeps the same conservative boundary.
            candidate_path = "/".join(parts[:-1]) or path
            found.append(("skill", candidate_path, "contains SKILL.md"))
        elif filename in _MEMORY_DOCUMENTS:
            found.append(("memory", path, f"conventional harness memory document {filename}"))
        elif filename.lower() in _MCP_DOCUMENTS:
            found.append(("mcp", path, f"conventional MCP descriptor {filename}"))
        elif filename == "hook.json" and "hooks" in parents:
            candidate_path = "/".join(parts[:-1]) or path
            found.append(("hook", candidate_path, "hook.json below a hooks directory"))
        elif filename.lower().endswith(".md") and parents & _GUIDELINE_DIRECTORIES:
            found.append(("guideline", path, "Markdown document below a rules directory"))

    candidates: list[VendorCandidate] = []
    used: set[tuple[str, str]] = set()
    for kind, path, reason in sorted(set(found)):
        name = _proposed_name(kind, path)
        if (kind, name) in used:
            name = _slug(f"{path}-{name}")
        suffix = 2
        base = name
        while (kind, name) in used:
            name = f"{base}-{suffix}"
            suffix += 1
        used.add((kind, name))
        candidates.append(VendorCandidate(kind, name, path, reason))
    return tuple(sorted(candidates))
