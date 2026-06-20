"""install command (WP-12). Gather configs -> plan_install -> execute/render -> manifest upsert."""

from __future__ import annotations

from ..model import Request


def run(request: Request) -> int:
    raise NotImplementedError("WP-12: not implemented")
