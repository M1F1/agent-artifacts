"""Immutable snapshot cache — shell (WP-7). ``~/.cache/agent-artifacts/<repo>/<sha>/`` (DESIGN.md §8).

A commit SHA is immutable, so a snapshot is downloaded + extracted exactly once and reused
forever. GitHub tarballs nest everything under a single ``<owner>-<repo>-<sha>/`` top-level
directory; we strip that so the snapshot root holds ``skills/ guidelines/ ...`` directly.
"""

from __future__ import annotations

import io
import os
import shutil
import tarfile
import tempfile
from typing import Callable


def cache_dir(repo: str, sha: str) -> str:
    """``~/.cache/agent-artifacts/<repo with '/' -> '_'>/<sha>/`` (expanded; not created)."""
    safe_repo = repo.replace("/", "_")
    return os.path.expanduser(os.path.join("~", ".cache", "agent-artifacts", safe_repo, sha))


def ensure_snapshot(repo: str, sha: str, fetch: Callable[[], bytes]) -> str:
    """Return the path to an extracted snapshot, downloading + extracting once (immutable).

    If the cache dir already exists and is non-empty, it is reused as-is (``fetch`` is never
    called). Otherwise ``fetch()`` yields tarball bytes which are extracted into a temp dir
    (with the GitHub top-level ``<owner>-<repo>-<sha>/`` component stripped) and atomically
    moved into place via ``os.replace``.
    """
    dest = cache_dir(repo, sha)
    if os.path.isdir(dest) and os.listdir(dest):
        return dest

    raw = fetch()

    parent = os.path.dirname(dest)
    os.makedirs(parent, exist_ok=True)

    staging = tempfile.mkdtemp(prefix=".snapshot-", dir=parent)
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:*") as tar:
            _extract_stripped(tar, staging)
        # Atomic publish. If a concurrent run won the race, keep theirs.
        try:
            os.replace(staging, dest)
        except OSError:
            if os.path.isdir(dest) and os.listdir(dest):
                shutil.rmtree(staging, ignore_errors=True)
                return dest
            raise
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    return dest


def _extract_stripped(tar: tarfile.TarFile, dest: str) -> None:
    """Extract ``tar`` into ``dest``, stripping the single GitHub top-level directory.

    GitHub codeload tarballs wrap content in one ``<owner>-<repo>-<sha>/`` directory. We drop
    that leading path component so the destination root contains the repo tree directly.
    Members are validated to stay within ``dest`` (no path traversal).
    """
    dest_abs = os.path.abspath(dest)
    for member in tar.getmembers():
        name = member.name
        # Strip the single leading top-level component.
        parts = name.split("/", 1)
        if len(parts) == 1:
            # The top-level dir entry itself; nothing to place at the root.
            continue
        stripped = parts[1]
        if not stripped:
            continue

        target = os.path.abspath(os.path.join(dest_abs, stripped))
        if target != dest_abs and not target.startswith(dest_abs + os.sep):
            raise tarfile.TarError(f"unsafe path in tarball: {name!r}")

        if member.isdir():
            os.makedirs(target, exist_ok=True)
        elif member.isfile():
            os.makedirs(os.path.dirname(target), exist_ok=True)
            src = tar.extractfile(member)
            if src is None:
                continue
            with src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
        elif member.issym() or member.islnk():
            # Skip links; snapshots are plain content (avoids escaping the cache dir).
            continue
