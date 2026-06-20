"""upgrade command (WP-17). Reinstall the tool itself from main via ``pip install --no-index`` (DESIGN.md §15)."""

from __future__ import annotations

from ..model import Request


def run(request: Request) -> int:
    raise NotImplementedError("WP-17: not implemented")
