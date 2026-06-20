"""GitHub network IO — shell (WP-7). urllib + tarfile, no third-party deps (DESIGN.md §8).

The URL opener is injectable so tests drive a local ``http.server`` fixture (no live network).
"""

from __future__ import annotations

from typing import Optional

from ..model import Result

_TODO = "WP-7: not implemented"


def resolve_ref(repo: str, ref: str, token: Optional[str] = None, opener=None) -> Result:
    """Resolve a branch/tag/sha `ref` to a concrete SHA -> Ok[str] | Err."""
    raise NotImplementedError(_TODO)


def fetch_tarball(repo: str, sha: str, token: Optional[str] = None, opener=None) -> bytes:
    raise NotImplementedError(_TODO)


def compare(repo: str, base: str, head: str, token: Optional[str] = None, opener=None) -> Result:
    """``GET /compare/{base}...{head}`` -> Ok[dict] | Err (used by `check`, WP-16)."""
    raise NotImplementedError(_TODO)
