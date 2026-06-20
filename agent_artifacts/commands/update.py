"""update command (WP-13). Re-pull from main/pin, apply update policy + merge, optional --prune."""

from __future__ import annotations

from ..model import Request


def run(request: Request) -> int:
    raise NotImplementedError("WP-13: not implemented")
