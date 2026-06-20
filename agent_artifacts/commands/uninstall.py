"""uninstall command (WP-14). Reverse files and merges; remove only our own entries (DESIGN.md §10)."""

from __future__ import annotations

from ..model import Request


def run(request: Request) -> int:
    raise NotImplementedError("WP-14: not implemented")
