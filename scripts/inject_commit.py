#!/usr/bin/env python3
"""Stamp the current git commit into ``agent_artifacts/_commit.py`` (WP-21).

A build-time step: it overwrites ``agent_artifacts/_commit.py`` with the full git ``HEAD``
sha (via ``git rev-parse HEAD``) so the built wheel records exactly which source it came
from (docs/design/DESIGN.md §15, consumed by ``check`` / ``upgrade``). When git is unavailable or this
is not a checkout, it falls back to ``"unknown"``.

It also stamps that commit's committer date as ``COMMIT_EPOCH``.  The wheel builder dates every
archive member from it, so the published wheel reproduces from the tag instead of from the clock
(SI-8); ``0`` means "no commit date known" and the builder falls back to a fixed epoch.

Idempotent and re-runnable: it always rewrites the file from scratch and preserves the
module docstring. Keep the committed source as ``COMMIT = "unknown"`` — only the wheel
should ever embed a real sha (committing one would churn on every commit).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "agent_artifacts" / "_commit.py"

# Kept verbatim so the rewritten module reads the same as the version-controlled one.
DOCSTRING = '''"""Source commit the package was built from (docs/design/DESIGN.md §15).

Generated at build time by ``scripts/inject_commit.py`` (WP-21). The ``"unknown"`` default
is used for editable/dev installs and is only consulted by ``check`` / ``upgrade`` (WP-16/17).
``COMMIT_EPOCH`` is that commit's committer date, and is what dates every member of the built
wheel so the archive reproduces from the tag rather than from the clock (SI-8).
"""'''


def _git(*arguments: str) -> str:
    try:
        out = subprocess.run(
            ["git", *arguments],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    return out.stdout.strip()


def current_commit() -> str:
    """Return the full ``HEAD`` sha, or ``"unknown"`` if git can't tell us."""
    sha = _git("rev-parse", "HEAD")
    return sha if sha else "unknown"


def current_commit_epoch() -> int:
    """Return ``HEAD``'s committer date as a Unix epoch, or ``0`` if git can't tell us."""
    raw = _git("log", "-1", "--format=%ct", "HEAD")
    return int(raw) if raw.isdigit() else 0


def render(commit: str, epoch: int = 0) -> str:
    return f'{DOCSTRING}\n\nCOMMIT = "{commit}"\nCOMMIT_EPOCH = {epoch}\n'


def main() -> int:
    commit = current_commit()
    epoch = current_commit_epoch()
    TARGET.write_text(render(commit, epoch), encoding="utf-8")
    print(
        f"inject_commit: wrote COMMIT = {commit!r}, COMMIT_EPOCH = {epoch} "
        f"to {TARGET.relative_to(ROOT)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
