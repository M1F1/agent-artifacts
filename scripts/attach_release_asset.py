#!/usr/bin/env python3
"""Attach the built wheel to an existing release, using nothing but the standard library.

This step has now been written three times, and each rewrite removed a tool the CI image was
assumed to carry.  It began as ``gh release upload``; a company GitHub Enterprise Server image
had no ``gh``.  It became ``curl`` against the REST API; the same image had no ``curl`` either.
What that image does have is git and a Python interpreter -- it has to, or nothing else in the
release would run -- so the third version asks for nothing beyond them.

That is the same rule the project applies to itself: a zero-dependency tool whose CI needs four
other programs installed is not zero-dependency, it has just moved the dependency somewhere the
lockfile cannot see.

Two details are Enterprise-specific and both are read rather than guessed:

* ``GITHUB_API_URL`` is set by the runner and always names the instance the job runs on.  Its
  public value is ``https://api.github.com``; on an instance it is ``https://<host>/api/v3``.
* Uploads do not go to the API host.  The release object carries its own ``upload_url``, and on
  an Enterprise instance that is a different hostname again, so it is taken from the response.

``--clobber`` had one behaviour worth keeping: replace an asset of the same name instead of
failing on it, so a re-run is not a dead end.  That is what the delete below is for.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The API version header is what keeps a response shape stable across instance upgrades.  Older
# Enterprise releases ignore it, which is why it is safe to send unconditionally.
_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


def _request(url: str, token: str, *, method: str, body: bytes | None = None) -> bytes:
    """Call the API, and on refusal say what the API said.

    An HTTP error carries its explanation in the response body -- ``Bad credentials``, ``Not
    Found``, ``already_exists``.  Raising the status alone throws that away and leaves a log
    reading ``HTTP Error 422``, which names no cause and suggests no fix.
    """

    headers = {**_HEADERS, "Authorization": f"Bearer {token}"}
    if body is not None:
        headers["Content-Type"] = "application/octet-stream"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request) as response:  # noqa: S310 - fixed https API host
            return response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace").strip() or "(no response body)"
        raise SystemExit(f"{method} {url} failed ({error.code})\n{detail}") from None
    except urllib.error.URLError as error:
        raise SystemExit(f"{method} {url} could not be reached: {error.reason}") from None


def _wheel() -> Path:
    """The one wheel `build_wheel.py` just produced."""

    built = sorted((ROOT / "dist").glob("*.whl"))
    if len(built) != 1:
        found = ", ".join(path.name for path in built) or "nothing"
        raise SystemExit(f"expected exactly one wheel under dist/, found {found}")
    return built[0]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit("usage: attach_release_asset.py <tag>")
    tag = argv[1]

    missing = [
        name
        for name in ("GITHUB_API_URL", "GITHUB_REPOSITORY", "GITHUB_TOKEN")
        if not os.environ.get(name)
    ]
    if missing:
        raise SystemExit(f"not set in the environment: {', '.join(missing)}")
    api = os.environ["GITHUB_API_URL"].rstrip("/")
    repository = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GITHUB_TOKEN"]

    wheel = _wheel()
    release = json.loads(
        _request(f"{api}/repos/{repository}/releases/tags/{tag}", token, method="GET")
    )

    existing = next(
        (asset["id"] for asset in release.get("assets", ()) if asset.get("name") == wheel.name),
        None,
    )
    if existing is not None:
        _request(f"{api}/repos/{repository}/releases/assets/{existing}", token, method="DELETE")
        print(f"replaced the existing {wheel.name}")

    # `{?name,label}` is the URI template suffix the API appends; the name goes on as a query.
    upload = release["upload_url"].split("{")[0]
    _request(f"{upload}?name={wheel.name}", token, method="POST", body=wheel.read_bytes())
    print(f"attached {wheel.name} ({wheel.stat().st_size} bytes) to {tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
