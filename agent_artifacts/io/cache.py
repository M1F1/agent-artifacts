"""Immutable snapshot cache — shell (WP-7). ``~/.cache/agent-artifacts/<repo>/<sha>/`` (DESIGN.md §8)."""

from __future__ import annotations

from typing import Callable

_TODO = "WP-7: not implemented"


def cache_dir(repo: str, sha: str) -> str:
    raise NotImplementedError(_TODO)


def ensure_snapshot(repo: str, sha: str, fetch: Callable[[], bytes]) -> str:
    """Return the path to an extracted snapshot, downloading+extracting once (immutable)."""
    raise NotImplementedError(_TODO)
