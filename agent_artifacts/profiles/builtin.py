"""Built-in harness profiles — data (WP-8). Adding a harness = adding a record here (DESIGN.md §11)."""

from __future__ import annotations

from typing import Mapping

from ..model import Profile

_TODO = "WP-8: not implemented"


def builtin() -> Mapping[str, Profile]:
    """Return the built-in profiles: opencode, claude, tabnine."""
    raise NotImplementedError(_TODO)
