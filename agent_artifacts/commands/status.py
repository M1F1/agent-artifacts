"""status command (WP-15). LOCAL only — no network. Installed entries + on-disk drift (docs/design/DESIGN.md §8).

Invariant: this module must not import agent_artifacts.io.net (enforced by a test, docs/plan/PLAN.md §7).

Behaviour:
  1. Load the consumer manifest; corrupt → print message, return CORRUPT_MANIFEST (5).
  2. For each installed ManifestEntry, for each (path, base_hash) in entry.files:
     - If base_hash is "" (copy-tree directory entry), report "ok (tree)" if the directory
       exists on disk, "missing" otherwise. Hashing a directory is invalid.
     - Otherwise compute disk_hash = sha256_file(<project>/path) if the file exists, else None.
       Since status has no upstream source, treat new == base (we only detect LOCAL drift).
       Use policy.classify(disk, base, base) to decide:
         disk is None        → "missing"
         disk == base        → "ok"
         disk != base        → "drift"
  3. Print a per-entry report (human or --json).
  4. Exit code: OK (0) normally. Non-zero only for corrupt manifest. Drift is informational.
"""

from __future__ import annotations

import os
from typing import List, Optional

from .. import policy
from ..hashing import sha256_file
from ..io import fs
from ..model import Err, ManifestEntry, Request
from . import _common

# Exit codes (re-exported from _common for clarity).
OK = _common.OK
CORRUPT_MANIFEST = _common.CORRUPT_MANIFEST


# -- per-file state --------------------------------------------------------- #


def _file_state(project: str, rel_path: str, base_hash: str) -> str:
    """Determine the on-disk state of a single manifest-tracked path.

    For copy-tree entries (base_hash == ""), the path names a *directory* —
    we check existence rather than hashing (hashing a dir is invalid).

    For regular files we run policy.classify(disk, base, base) with new == base
    (status has no source) and translate the decision:
      - disk is None        → "missing"
      - disk == base (noop) → "ok"
      - disk != base        → "drift"  (covers "overwrite", "conflict", "keep-drift")
    """
    abs_path = os.path.join(project, rel_path)

    # Copy-tree directory entry: base_hash is the empty string.
    if base_hash == "":
        return "ok (tree)" if os.path.isdir(abs_path) else "missing"

    # Regular file.
    disk: Optional[str] = sha256_file(abs_path) if fs.exists(abs_path) else None
    base: Optional[str] = base_hash if base_hash else None

    decision = policy.classify(disk, base, base)  # new == base (no source)

    if decision == "noop":
        return "ok"
    if disk is None:
        return "missing"
    # Any other decision when disk exists but != base means local modification.
    return "drift"


# -- JSON output shape ------------------------------------------------------ #


def _entry_json(project: str, entry: ManifestEntry) -> dict:
    """Build the stable JSON dict for one installed entry."""
    files_report: List[dict] = []
    for path, base_hash in entry.files.items():
        state = _file_state(project, path, base_hash)
        files_report.append({"path": path, "state": state})
    return {
        "artifact": entry.artifact,
        "type": entry.type,
        "profile": entry.profile,
        "source": entry.source,
        "files": files_report,
    }


# -- human-readable output -------------------------------------------------- #


def _print_human(project: str, repo: str, entries: tuple) -> None:
    """Print a human-readable status report to stdout."""
    if not entries:
        print(f"No artifacts installed (repo: {repo}).")
        return

    print(f"repo: {repo}")
    print(f"{len(entries)} installed artifact(s):\n")

    for entry in entries:
        print(f"  {entry.type}/{entry.artifact}  profile={entry.profile}  source={entry.source}")
        for path, base_hash in entry.files.items():
            state = _file_state(project, path, base_hash)
            print(f"    {path}: {state}")
        print()


# -- entry point ------------------------------------------------------------- #


def run(request: Request) -> int:
    """Report installed entries and on-disk drift. Fully offline — no network access.

    Returns OK (0) normally. Returns CORRUPT_MANIFEST (5) only when the
    manifest file exists but cannot be parsed. Drift is informational, not
    an error exit.
    """
    result = _common.load_manifest(request)

    if isinstance(result, Err):
        print(result.reason)
        return CORRUPT_MANIFEST

    m = result.value
    project = _common.project_root(request)

    if request.json:
        report = {
            "repo": m.repo,
            "installed": [_entry_json(project, e) for e in m.installed],
        }
        _common.print_json(report)
    else:
        _print_human(project, m.repo, m.installed)

    return OK
