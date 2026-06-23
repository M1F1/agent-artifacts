"""GitHub network IO — shell (WP-7). urllib + tarfile, no third-party deps (DESIGN.md §8).

The URL opener is injectable so tests drive a local ``http.server`` fixture (no live network).

Opener contract
---------------
``opener`` is a callable ``(urllib.request.Request) -> file-like``. The returned object
must support ``.read() -> bytes`` and be usable as a context manager (``with opener(req)
as resp:``) — exactly like ``urllib.request.urlopen``. When ``opener`` is ``None`` we
default to ``urllib.request.urlopen``. All requests are built via ``urllib.request.Request``
so headers (Accept / Authorization) attach before the opener sees them.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Optional

from ..model import Err, Ok, Result

_DEFAULT_API = "https://api.github.com"
_ACCEPT = "application/vnd.github+json"


def _build_request(url: str, token: Optional[str], accept: str = _ACCEPT) -> urllib.request.Request:
    """Build a GET ``Request`` with the GitHub Accept header and optional bearer token."""
    headers = {"Accept": accept}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return urllib.request.Request(url, headers=headers)


def _open(request: urllib.request.Request, opener) -> bytes:
    """Run ``request`` through ``opener`` (or ``urlopen``) and return the raw response body."""
    use = opener if opener is not None else urllib.request.urlopen
    with use(request) as response:
        return response.read()


def default_api_url() -> str:
    return os.environ.get("GITHUB_API_URL", _DEFAULT_API).rstrip("/")


def _api_root(api_url: Optional[str]) -> str:
    return (api_url or default_api_url()).rstrip("/")


def resolve_ref(
    repo: str,
    ref: str,
    token: Optional[str] = None,
    opener=None,
    api_url: Optional[str] = None,
) -> Result:
    """Resolve a branch/tag/sha ``ref`` to a concrete SHA -> Ok[str] | Err (code 3).

    ``GET /repos/{repo}/commits/{ref}`` -> JSON ``{"sha": "..."}``. Fail-soft: any
    network / HTTP / decode error becomes an ``Err`` (DESIGN.md §8, ``check`` is fail-soft).
    """
    url = f"{_api_root(api_url)}/repos/{repo}/commits/{ref}"
    try:
        body = _open(_build_request(url, token), opener)
        data = json.loads(body)
        sha = data["sha"]
    except urllib.error.HTTPError as exc:
        msg = f"failed to resolve {repo}@{ref}: {exc}"
        if exc.code == 404:
            msg += " (Is the repository private? Make sure GITHUB_TOKEN is set)"
        return Err(msg, code=3)
    except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError) as exc:
        return Err(f"failed to resolve {repo}@{ref}: {exc}", code=3)
    return Ok(sha)


def fetch_tarball(
    repo: str,
    sha: str,
    token: Optional[str] = None,
    opener=None,
    api_url: Optional[str] = None,
) -> bytes:
    """``GET /repos/{repo}/tarball/{sha}`` -> raw ``.tar.gz`` bytes.

    Returns bytes directly (not a ``Result``); the cache layer wraps the call so a fetch
    failure surfaces where extraction happens. Caller passes this as the ``fetch`` callable
    to :func:`agent_artifacts.io.cache.ensure_snapshot`.
    """
    url = f"{_api_root(api_url)}/repos/{repo}/tarball/{sha}"
    return _open(_build_request(url, token), opener)


def compare(
    repo: str,
    base: str,
    head: str,
    token: Optional[str] = None,
    opener=None,
    api_url: Optional[str] = None,
) -> Result:
    """``GET /compare/{base}...{head}`` -> Ok[dict] | Err (code 3) — used by ``check`` (WP-16)."""
    url = f"{_api_root(api_url)}/repos/{repo}/compare/{base}...{head}"
    try:
        body = _open(_build_request(url, token), opener)
        data = json.loads(body)
    except urllib.error.HTTPError as exc:
        msg = f"failed to compare {repo} {base}...{head}: {exc}"
        if exc.code == 404:
            msg += " (Is the repository private? Make sure GITHUB_TOKEN is set)"
        return Err(msg, code=3)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return Err(f"failed to compare {repo} {base}...{head}: {exc}", code=3)
    return Ok(data)
