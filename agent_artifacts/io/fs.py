"""Filesystem performers — shell (WP-6). Atomic, idempotent (DESIGN.md §9)."""

from __future__ import annotations

from typing import Tuple

_TODO = "WP-6: not implemented"


def read_bytes(path: str) -> bytes:
    raise NotImplementedError(_TODO)


def read_text(path: str) -> str:
    raise NotImplementedError(_TODO)


def read_json(path: str):
    raise NotImplementedError(_TODO)


def write_atomic(path: str, content: bytes) -> None:
    """Write via a staging file + atomic rename, creating parent dirs."""
    raise NotImplementedError(_TODO)


def copy_tree(src: str, dst: str) -> None:
    raise NotImplementedError(_TODO)


def remove_path(path: str) -> None:
    raise NotImplementedError(_TODO)


def exists(path: str) -> bool:
    raise NotImplementedError(_TODO)


def listdir(path: str) -> Tuple[str, ...]:
    raise NotImplementedError(_TODO)
