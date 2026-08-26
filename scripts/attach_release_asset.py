#!/usr/bin/env python3
"""Attach the built wheel to an existing release, using nothing but the standard library.

This step has been written three times, and each rewrite removed a tool the CI image was assumed
to carry.  It began as ``gh release upload``; a company GitHub Enterprise Server image had no
``gh``.  It became ``curl`` against the REST API; the same image had no ``curl`` either.  What
that image does have is git and a Python interpreter -- it has to, or nothing else in the release
would run -- so the third version asks for nothing beyond them.  The API call itself now lives in
``scripts/github_api.py``, where the rest of the release can reach it.

``--clobber`` had one behaviour worth keeping: replace an asset of the same name instead of
failing on it, so a re-run is not a dead end.  That is what the delete below is for.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import github_api  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def _wheel() -> Path:
    """The one wheel `build_wheel.py` just produced."""

    built = sorted((ROOT / "dist").glob("*.whl"))
    if len(built) != 1:
        found = ", ".join(path.name for path in built) or "nothing"
        raise SystemExit(f"expected exactly one wheel under dist/, found {found}")
    return built[0]


def attach(tag: str) -> None:
    api, repository = github_api.origin()
    token = github_api.token()
    wheel = _wheel()

    release = github_api.json_request(f"{api}/repos/{repository}/releases/tags/{tag}", auth=token)
    existing = next(
        (asset["id"] for asset in release.get("assets", ()) if asset.get("name") == wheel.name),
        None,
    )
    if existing is not None:
        github_api.request(
            f"{api}/repos/{repository}/releases/assets/{existing}", method="DELETE", auth=token
        )
        print(f"replaced the existing {wheel.name}")

    # Uploads do not go to the API host.  On an Enterprise instance that is a hostname of its own,
    # so it is taken from the release; `{?name,label}` is the URI template suffix and is dropped.
    upload = release["upload_url"].split("{")[0]
    github_api.request(
        f"{upload}?name={wheel.name}",
        method="POST",
        body=wheel.read_bytes(),
        content_type="application/octet-stream",
        auth=token,
    )
    print(f"attached {wheel.name} ({wheel.stat().st_size} bytes) to {tag}")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit("usage: attach_release_asset.py <tag>")
    try:
        attach(argv[1])
    except github_api.GitHubError as error:
        raise SystemExit(str(error)) from None
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
