"""Filesystem performers — shell (WP-6). Atomic, idempotent (docs/design/DESIGN.md §9)."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from typing import Tuple


def read_bytes(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def read_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_atomic(path: str, content: bytes) -> None:
    """Write via a staging file + atomic rename, creating parent dirs."""
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=parent)
    try:
        os.write(fd, content)
        os.close(fd)
        os.replace(tmp, path)
    except BaseException:
        os.close(fd) if not _is_closed(fd) else None
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _is_closed(fd: int) -> bool:
    """Check whether a file descriptor has already been closed."""
    try:
        os.fstat(fd)
        return False
    except OSError:
        return True


def copy_tree(src: str, dst: str) -> None:
    """Recursively copy a directory tree; idempotent (dirs_exist_ok)."""
    dst_parent = os.path.dirname(os.path.abspath(dst))
    os.makedirs(dst_parent, exist_ok=True)
    shutil.copytree(src, dst, dirs_exist_ok=True)


def remove_path(path: str) -> None:
    """Remove a file or directory tree; missing path is a no-op (idempotent)."""
    try:
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.unlink(path)
    except FileNotFoundError:
        pass


def exists(path: str) -> bool:
    return os.path.exists(path)


def listdir(path: str) -> Tuple[str, ...]:
    """Sorted tuple of entry names; missing dir -> empty tuple."""
    try:
        return tuple(sorted(os.listdir(path)))
    except FileNotFoundError:
        return ()
