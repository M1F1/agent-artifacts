#!/usr/bin/env python3
"""One authenticated call to a GitHub API, from the standard library alone.

Written after the release step failed twice on a company CI image -- first on `gh`, then on
`curl`. Neither is installed everywhere; git and a Python interpreter are, because nothing else
in a release would run without them. So the API is reached from here instead, and every caller
that needs GitHub goes through this module rather than shelling out to a tool.

Two things are read rather than guessed, both because an Enterprise instance answers differently
from github.com:

* the API root -- ``https://api.github.com`` in public, ``https://<host>/api/v3`` on an instance;
* the upload host, which is a hostname of its own again and is carried by the release object.

Inside Actions the runner sets ``GITHUB_API_URL`` and ``GITHUB_REPOSITORY`` and they are believed.
Outside it, both are derived from the ``origin`` remote, so the same script runs on a laptop.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from typing import Any

_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

# `https://host/owner/name(.git)` and `git@host:owner/name(.git)`, which are the two forms a
# checkout's origin actually takes.  Anything else is reported rather than half-parsed.
_HTTPS_REMOTE = re.compile(
    r"^https?://(?:[^@/]+@)?(?P<host>[^/]+)/(?P<repo>[^/]+/[^/]+?)(?:\.git)?$"
)
_SSH_REMOTE = re.compile(r"^(?:ssh://)?git@(?P<host>[^:/]+)[:/](?P<repo>[^/]+/[^/]+?)(?:\.git)?$")


class GitHubError(RuntimeError):
    """A refusal from the API, carrying the API's own explanation."""


def token() -> str:
    """The token, from the two names Actions and the CLI already use."""

    for name in ("GITHUB_TOKEN", "GH_TOKEN"):
        value = os.environ.get(name)
        if value:
            return value
    raise GitHubError("no token: set GITHUB_TOKEN (or GH_TOKEN) in the environment")


def origin(remote: str = "origin") -> tuple[str, str]:
    """Return ``(api_root, "owner/name")`` for the repository this call is about.

    The runner's own values win when they exist: inside a job they are authoritative, and a
    checkout's remote can legitimately point somewhere else.
    """

    api = os.environ.get("GITHUB_API_URL")
    repository = os.environ.get("GITHUB_REPOSITORY")
    if api and repository:
        return api.rstrip("/"), repository

    url = subprocess.run(
        ("git", "remote", "get-url", remote),
        capture_output=True,
        text=True,
    )
    if url.returncode:
        detail = url.stderr.strip() or "(git said nothing)"
        raise GitHubError(f"cannot read the '{remote}' remote\n{detail}")
    address = url.stdout.strip()

    match = _HTTPS_REMOTE.match(address) or _SSH_REMOTE.match(address)
    if match is None:
        raise GitHubError(f"cannot read an owner/name out of the '{remote}' remote: {address}")
    host, repository = match.group("host"), match.group("repo")
    # github.com is the exception, not the rule: every instance serves its API under /api/v3.
    root = (
        "https://api.github.com"
        if host in ("github.com", "www.github.com")
        else f"https://{host}/api/v3"
    )
    return root, repository


def repository_url(remote: str = "origin") -> str:
    """``https://host/owner/name`` for this checkout, whichever instance it lives on.

    The API root is the thing already derived from the remote, so the web address is derived back
    out of it rather than parsed a second time.  Callers use it to print install commands that
    name the reader's own instance -- a README cannot, because nothing interpolates a variable
    into a markdown file.
    """

    api, repository = origin(remote)
    host = "https://github.com" if api == "https://api.github.com" else api[: -len("/api/v3")]
    return f"{host}/{repository}"


def request(
    url: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    content_type: str | None = None,
    auth: str | None = None,
) -> bytes:
    """Call the API, and on refusal raise with what the API said.

    An HTTP error carries its explanation in the body -- ``Bad credentials``, ``Not Found``,
    ``already_exists``.  Raising the status alone throws that away and leaves a log reading
    ``HTTP Error 422``, which names no cause and suggests no fix.  Three failures in one
    Enterprise walk were unreadable for exactly this reason.
    """

    headers = {**_HEADERS, "Authorization": f"Bearer {auth or token()}"}
    if content_type:
        headers["Content-Type"] = content_type
    call = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(call) as response:  # noqa: S310 - https API host
            return response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace").strip() or "(no response body)"
        raise GitHubError(f"{method} {url} failed ({error.code})\n{detail}") from None
    except urllib.error.URLError as error:
        raise GitHubError(f"{method} {url} could not be reached: {error.reason}") from None


def json_request(url: str, **kwargs: Any) -> Any:
    payload = kwargs.pop("payload", None)
    if payload is not None:
        kwargs["body"] = json.dumps(payload).encode("utf-8")
        kwargs.setdefault("content_type", "application/json")
    return json.loads(request(url, **kwargs))
