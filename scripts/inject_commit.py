#!/usr/bin/env python3
"""Stamp the current git commit into ``agent_artifacts/_commit.py`` (WP-21).

A build-time step: it overwrites ``agent_artifacts/_commit.py`` with the full git ``HEAD``
sha (via ``git rev-parse HEAD``) so the built wheel records exactly which source it came
from (DESIGN.md §15, consumed by ``check`` / ``upgrade``). When git is unavailable or this
is not a checkout, it falls back to ``"unknown"``.

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
DOCSTRING = '''"""Source commit the package was built from (DESIGN.md §15).

Generated at build time by ``scripts/inject_commit.py`` (WP-21). The ``"unknown"`` default
is used for editable/dev installs and is only consulted by ``check`` / ``upgrade`` (WP-16/17).
"""'''


def current_commit() -> str:
    """Return the full ``HEAD`` sha, or ``"unknown"`` if git can't tell us."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    sha = out.stdout.strip()
    return sha if sha else "unknown"


def render(commit: str) -> str:
    return f'{DOCSTRING}\n\nCOMMIT = "{commit}"\n'


def main() -> int:
    commit = current_commit()
    TARGET.write_text(render(commit), encoding="utf-8")
    print(f"inject_commit: wrote COMMIT = {commit!r} to {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
