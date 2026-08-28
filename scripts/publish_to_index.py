#!/usr/bin/env python3
"""Publish the built wheel to a PyPI-compatible package index, from the standard library alone.

`twine` is the usual answer and it is one more program a CI image has to carry. Three steps in
this repository have already been rewritten to stop assuming a tool was installed -- Make, then
`gh`, then `curl` -- each of them failing in an image that had git, an interpreter and nothing
else. Uploading a wheel is one HTTP POST, so it is one HTTP POST here.

The endpoint is the legacy upload API, which every private index in normal use speaks: Nexus's
`pypi-hosted` repositories, Artifactory's PyPI repositories, devpi, and PyPI itself. It takes a
`multipart/form-data` body with `:action=file_upload` and the distribution's own metadata as
fields, which are read out of the wheel rather than restated here -- a wheel that disagreed with
what was claimed about it would be worse than no upload at all.

Two things are deliberately not decided by this script:

* **where** to publish, which is `--url` (a repository variable in CI). There is no default: a
  default pointing at PyPI would make an accident out of a company's first mistake.
* **who** publishes, which is `AART_INDEX_PUBLISH_CREDENTIALS` in the environment, holding the
  two halves separated by a colon. It is never a command-line argument -- arguments are visible
  in a process list and land in shell history.
"""

from __future__ import annotations

import argparse
import base64
import email.parser
import os
import sys
import urllib.error
import urllib.request
import uuid
import zipfile
from hashlib import blake2b, md5, sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The fields the upload API names, and where each comes from.  Everything not listed is either
# derived (the digests) or a property of the file (`filetype`, `pyversion`).
_FROM_METADATA = (
    ("name", "Name"),
    ("version", "Version"),
    ("metadata_version", "Metadata-Version"),
    ("summary", "Summary"),
)


class PublishError(RuntimeError):
    """The index refused, carrying the index's own explanation."""


def wheel(root: Path = ROOT) -> Path:
    """The one wheel `build_wheel.py` produced."""

    built = sorted((root / "dist").glob("*.whl"))
    if len(built) != 1:
        found = ", ".join(path.name for path in built) or "nothing"
        raise PublishError(f"expected exactly one wheel under dist/, found {found}")
    return built[0]


def metadata(path: Path) -> dict[str, str]:
    """The wheel's own METADATA, parsed.  What is uploaded describes what is in the file."""

    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(names) != 1:
            raise PublishError(f"{path.name} carries {len(names)} METADATA files, expected one")
        raw = archive.read(names[0]).decode("utf-8")
    return dict(email.parser.Parser().parsestr(raw).items())


def form(path: Path) -> list[tuple[str, str]]:
    """The metadata fields for one wheel, in the shape the upload API asks for."""

    found = metadata(path)
    missing = [header for _, header in _FROM_METADATA if header not in found]
    if missing:
        raise PublishError(f"{path.name} METADATA has no {', '.join(missing)}")
    content = path.read_bytes()
    fields = [(field, found[header]) for field, header in _FROM_METADATA]
    fields.extend(
        (
            (":action", "file_upload"),
            ("protocol_version", "1"),
            ("filetype", "bdist_wheel"),
            # The interpreter tag out of the filename: `name-version-pyN-abi-platform.whl`.
            ("pyversion", path.stem.split("-")[2]),
            ("md5_digest", md5(content).hexdigest()),  # noqa: S324 - the API names this field
            ("sha256_digest", sha256(content).hexdigest()),
            ("blake2_256_digest", blake2b(content, digest_size=32).hexdigest()),
        )
    )
    return fields


def body(fields: list[tuple[str, str]], path: Path, boundary: str) -> bytes:
    """One `multipart/form-data` payload: the fields, then the file."""

    marker = f"--{boundary}".encode()
    parts: list[bytes] = []
    for name, value in fields:
        parts.append(
            marker
            + b"\r\n"
            + f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
            + value.encode("utf-8")
            + b"\r\n"
        )
    parts.append(
        marker
        + b"\r\n"
        + f'Content-Disposition: form-data; name="content"; filename="{path.name}"\r\n'.encode()
        + b"Content-Type: application/octet-stream\r\n\r\n"
        + path.read_bytes()
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts)


def credentials() -> str:
    """The two halves, from the environment, assembled into one header value.

    Never an argument: arguments are visible in a process list and kept in shell history.
    """

    held = os.environ.get("AART_INDEX_PUBLISH_CREDENTIALS", "")
    separator = ":"
    if separator not in held:
        raise PublishError(
            "AART_INDEX_PUBLISH_CREDENTIALS is unset or malformed.\n"
            "It holds the publishing account and its password or token, separated by a colon, "
            "and is read from the environment so it never reaches a command line."
        )
    return "Basic " + base64.b64encode(held.encode("utf-8")).decode("ascii")


def publish(url: str, path: Path) -> str:
    boundary = uuid.uuid4().hex
    payload = body(form(path), path, boundary)
    request = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(payload)),
            "Authorization": credentials(),
        },
    )
    try:
        with urllib.request.urlopen(request) as response:  # noqa: S310 - operator-supplied index
            response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace").strip() or "(no response body)"
        # An index refuses for reasons worth reading: a version that already exists, an account
        # without deploy rights, a repository that is a proxy rather than a hosted one.  Raising
        # the status alone throws all three away and leaves a log saying `HTTP Error 400`.
        raise PublishError(f"POST {url} refused ({error.code})\n{detail}") from None
    except urllib.error.URLError as error:
        raise PublishError(f"POST {url} could not be reached: {error.reason}") from None
    return f"published {path.name} ({path.stat().st_size} bytes) to {url}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", required=True, help="the index's upload endpoint")
    parser.add_argument("--wheel", type=Path, help="the file to publish; found under dist/ if not")
    parsed = parser.parse_args(argv)

    try:
        print(publish(parsed.url, parsed.wheel or wheel()))
    except PublishError as error:
        print(f"publish refused: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
