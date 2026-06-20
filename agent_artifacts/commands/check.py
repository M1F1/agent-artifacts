"""check command (WP-16). REMOTE, opt-in: installed/CLI commit vs main + what changed (DESIGN.md §8).

Fail-soft: any network error prints one line, exits non-zero, changes nothing.
"""

from __future__ import annotations

from ..model import Request


def run(request: Request) -> int:
    raise NotImplementedError("WP-16: not implemented")
