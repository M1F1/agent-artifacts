"""Source resolver — shell (WP-11). Unifies local ``--source DIR`` and remote ``repo@ref``.

Returns a `Source` handle exposing ``read(rel) -> bytes`` and ``catalog() -> Catalog`` so the
rest of the system is agnostic to where artifacts come from (DESIGN.md §7/§8).
"""

from __future__ import annotations

from .model import Request

_TODO = "WP-11: not implemented"


def open_source(request: Request):
    """Resolve a Request's source (local dir or remote snapshot) into a Source handle."""
    raise NotImplementedError(_TODO)
