#!/usr/bin/env python3
"""Stamp the release this wheel is being built for into ``agent_artifacts/_build_origin.py``.

A build-time step beside ``inject_commit.py``.  ``inject_commit`` records *which source*; this
records *where that source lives and which release it is*, which is what ``registry init`` needs
to point a registry's CI at the right fork.

The values come from the release job's own context -- ``github.server_url``,
``github.repository`` and the tag -- so a fork stamps its own instance and its own repository with
no edit to this file, to the workflow, or to the code.  Outside a release the values are empty and
the wheel simply carries no origin, which is the honest answer for a development build.

Whenever a ref *is* stated, three things must agree or this refuses to write:

* the ref must be ``v`` + the source version, the same rule ``version.py check-tag`` enforces;
* the commit must be the one the ref points at -- checked here, and recorded by
  ``inject_commit.py`` rather than a second time here;
* the repository URL must name a host, because a path is not somewhere CI can fetch from.

A wheel that lies about its origin is worse than one that says nothing: the first sends every
registry built from it to the wrong repository, and the second says so out loud.
"""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "agent_artifacts" / "_build_origin.py"

DOCSTRING = '''"""Where the wheel this package came from was built (`docs/ci/enterprise-fork-v1.md` §3.1).

Generated at build time by ``scripts/inject_build_origin.py``, the same way ``_commit.py`` is.
The committed source keeps empty strings: a real value here would churn on every commit, and an
editable or development install has no release to name.

``registry init`` reads this to stamp the workflows it writes, so a wheel built by a company
fork's release CI sends every registry created from it to that fork.  That is what makes the
delivery route stop mattering -- a wheel carries its own origin whether it arrives from a release
URL, an internal index, ``pipx``, or a file on a laptop.

The commit is deliberately *not* here: ``_commit.py`` already records it, and two scripts
writing the same fact can disagree with nothing to catch them.  ``scripts/inject_build_origin.py``
still checks the ref against that commit before it writes -- verifying it and storing it twice are
different things.
"""'''

# Same shape the stamp accepts: a scheme with a host, or the ssh short form.  A path is refused.
_HOSTED = re.compile(
    r"^(?:[a-zA-Z][a-zA-Z0-9+.-]*://(?:[^/@]+@)?[^/@:]+(?::\d+)?/.+"
    r"|(?:[^@/\s]+@)?[^/@:\s]+:[^/\s]+/.+)$"
)


class OriginError(Exception):
    """The stated origin does not describe this source."""


def _git(*arguments: str, root: Path = ROOT) -> str:
    try:
        out = subprocess.run(
            ["git", *arguments], cwd=root, capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    return out.stdout.strip()


def _source_version(root: Path = ROOT) -> str:
    """Read the one canonical version, through the script that owns it."""

    path = root / "scripts" / "version.py"
    spec = importlib.util.spec_from_file_location("_aart_version", path)
    if spec is None or spec.loader is None:  # pragma: no cover - a broken checkout
        raise OriginError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return str(module.read_version(root))


def resolve(environ: dict[str, str] | None = None, *, root: Path = ROOT) -> tuple[str, str, str]:
    """Return the origin to stamp: repository URL, ref, commit, version.

    All four are empty for a development build.  Anything else is checked before it is returned.
    """

    env = os.environ if environ is None else environ
    url = (env.get("AART_BUILD_REPOSITORY_URL") or "").strip()
    ref = (env.get("AART_BUILD_REF") or "").strip()
    if not ref and not url:
        return ("", "", "")
    if not url or not ref:
        raise OriginError("a build origin needs both AART_BUILD_REPOSITORY_URL and AART_BUILD_REF")
    if _HOSTED.match(url) is None:
        raise OriginError(f"build origin {url!r} names no host, so CI could not fetch from it")
    version = _source_version(root)
    if ref != f"v{version}":
        raise OriginError(f"ref {ref!r} is not the source version tag {'v' + version!r}")
    commit = _git("rev-parse", "HEAD", root=root)
    if not commit:
        raise OriginError("a build origin needs a commit, and this is not a checkout")
    at_ref = _git("rev-parse", f"{ref}^{{commit}}", root=root)
    if at_ref and at_ref != commit:
        raise OriginError(f"ref {ref!r} points at {at_ref}, but this tree is at {commit}")
    return (url, ref, version)


def render(url: str, ref: str, version: str) -> str:
    return f'{DOCSTRING}\n\nREPOSITORY_URL = "{url}"\nREF = "{ref}"\nVERSION = "{version}"\n'


def main(argv: tuple[str, ...] | None = None) -> int:
    try:
        url, ref, version = resolve()
    except OriginError as error:
        print(f"inject_build_origin: {error}", file=sys.stderr)
        return 1
    TARGET.write_text(render(url, ref, version), encoding="utf-8")
    where = f"{url}@{ref}" if url else "no origin (development build)"
    print(f"inject_build_origin: wrote {where} to {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
