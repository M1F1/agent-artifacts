"""status command (WP-15). LOCAL only — no network. Installed entries + on-disk drift (DESIGN.md §8).

Invariant: this module must not import agent_artifacts.io.net (enforced by a test, PLAN.md §7).
"""

from __future__ import annotations

from ..model import Request


def run(request: Request) -> int:
    raise NotImplementedError("WP-15: not implemented")
