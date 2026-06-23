"""upgrade command (WP-17). Reinstall the tool itself from main via ``pip install --no-index`` (DESIGN.md §15).

Index-free by construction: the pip argv always includes ``--no-index`` and never adds
``--index-url`` or ``--extra-index-url``. Self-update is explicit, never automatic (§16).
"""

from __future__ import annotations

import glob
import os
import subprocess
import sys
from typing import Callable, List, Optional

from ..io.cache import ensure_snapshot
from ..io.net import fetch_tarball, resolve_ref
from ..model import Err, Request
from ._common import ERROR, NETWORK, OK, repo_of


def _default_runner(argv: List[str]) -> int:
    """Run *argv* via subprocess and return its exit code."""
    return subprocess.run(argv, check=False).returncode


def _find_local_wheel(dist_dir: str) -> Optional[str]:
    """Return the first ``agent_artifacts-*.whl`` path under *dist_dir*, or ``None``."""
    pattern = os.path.join(dist_dir, "agent_artifacts-*.whl")
    matches = sorted(glob.glob(pattern))
    return matches[-1] if matches else None


def _upgrade(
    request: Request,
    *,
    runner: Optional[Callable[[List[str]], int]] = None,
    opener=None,
    dist_dir: Optional[str] = None,
) -> int:
    """Core upgrade logic, injectable for testing.

    Parameters
    ----------
    runner:
        Command executor ``(argv) -> exit_code``. Defaults to a thin wrapper over
        ``subprocess.run``. Tests inject a fake that records the invocation.
    opener:
        Threaded into ``resolve_ref`` / ``fetch_tarball`` so tests avoid the network.
    dist_dir:
        Override the directory to search for a prebuilt wheel. Defaults to ``dist/``
        relative to the repo root of *this* package.
    """
    if runner is None:
        runner = _default_runner

    # --- 1. Determine the install source and pip argv ----------------------- #
    # Try the local prebuilt wheel first.
    if dist_dir is None:
        # Default: dist/ next to the repo root (two levels up from this file).
        dist_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "dist",
        )

    wheel = _find_local_wheel(dist_dir)

    if wheel is not None:
        # Local wheel path — no network needed.
        argv: List[str] = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-index",
            "--force-reinstall",
            wheel,
        ]
    else:
        # Remote: resolve ref → SHA → snapshot → pip install from snapshot dir.
        repo = repo_of(request)
        token = os.environ.get("GITHUB_TOKEN")
        ref = request.version or "main"

        result = resolve_ref(repo, ref, token, opener)
        if isinstance(result, Err):
            print(result.reason)
            return NETWORK

        sha: str = result.value
        snapshot_dir = ensure_snapshot(
            repo,
            sha,
            fetch=lambda: fetch_tarball(repo, sha, token, opener),
        )

        argv = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-index",
            "--no-build-isolation",
            "--force-reinstall",
            snapshot_dir,
        ]

    # --- 2. Print the pip invocation and optionally execute ------------------ #
    print(" ".join(argv))

    if request.dry_run:
        return OK

    rc = runner(argv)
    return OK if rc == 0 else ERROR


def run(request: Request) -> int:
    """Entry point for ``agent-artifacts upgrade``."""
    return _upgrade(request)
