"""Canonical SHA-256 values and host-independent document/tree hashing."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from agent_artifacts.domain.diagnostics import Diagnostic, Severity, SourceLocation
from agent_artifacts.domain.identifiers import ObjectDigest
from agent_artifacts.domain.result import Err, Ok, Result

from .codes import DIGEST_INVALID, TREE_INVALID
from .json import JsonValue, canonical_json_bytes
from .paths import SafeRelativePath, parse_relative_path

_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class EntryKind(str, Enum):
    FILE = "file"
    DIRECTORY = "directory"


@dataclass(frozen=True, slots=True)
class TreeEntry:
    path: SafeRelativePath
    kind: EntryKind
    executable: bool = False
    size: int = 0
    content_digest: ObjectDigest | None = None


def sha256_bytes(data: bytes) -> ObjectDigest:
    return ObjectDigest("sha256", hashlib.sha256(data).hexdigest())


def parse_sha256(
    raw: str,
    *,
    location: SourceLocation | None = None,
) -> Result[ObjectDigest]:
    if _SHA256_RE.fullmatch(raw) is None:
        return Err(
            (
                Diagnostic(
                    DIGEST_INVALID,
                    Severity.ERROR,
                    f"invalid canonical SHA-256 digest: {raw!r}",
                    location,
                ),
            )
        )
    return Ok(ObjectDigest("sha256", raw.removeprefix("sha256:")))


def json_digest(value: JsonValue) -> ObjectDigest:
    return sha256_bytes(canonical_json_bytes(value))


def file_entry(path: SafeRelativePath, content: bytes, *, executable: bool = False) -> TreeEntry:
    return TreeEntry(
        path=path,
        kind=EntryKind.FILE,
        executable=executable,
        size=len(content),
        content_digest=sha256_bytes(content),
    )


def directory_entry(path: SafeRelativePath) -> TreeEntry:
    return TreeEntry(path=path, kind=EntryKind.DIRECTORY)


def _invalid_tree(message: str) -> Err:
    return Err((Diagnostic(TREE_INVALID, Severity.ERROR, message),))


def _frame(data: bytes) -> bytes:
    return len(data).to_bytes(8, "big") + data


def _tree_record(entry: TreeEntry) -> Result[bytes]:
    if not isinstance(entry.path, SafeRelativePath):
        return _invalid_tree("tree entry path is not a safe relative path")
    parsed_path = parse_relative_path(str(entry.path))
    if not isinstance(parsed_path, Ok) or parsed_path.value != entry.path:
        return _invalid_tree(f"tree entry path is not canonical: {entry.path}")
    if not isinstance(entry.kind, EntryKind):
        return _invalid_tree(f"tree entry has invalid kind: {entry.path}")
    if not isinstance(entry.executable, bool):
        return _invalid_tree(f"tree entry has invalid executable bit: {entry.path}")
    path = str(entry.path).encode("utf-8")
    if entry.kind is EntryKind.DIRECTORY:
        if entry.executable or entry.size != 0 or entry.content_digest is not None:
            return _invalid_tree(f"directory entry has file metadata: {entry.path}")
        return Ok(b"D" + _frame(path))
    if (
        not isinstance(entry.size, int)
        or isinstance(entry.size, bool)
        or entry.size < 0
        or entry.size > 2**64 - 1
        or not isinstance(entry.content_digest, ObjectDigest)
    ):
        return _invalid_tree(f"file entry has incomplete metadata: {entry.path}")
    digest = str(entry.content_digest)
    if _SHA256_RE.fullmatch(digest) is None:
        return _invalid_tree(f"file entry has invalid content digest: {entry.path}")
    return Ok(
        b"F"
        + _frame(path)
        + (b"\x01" if entry.executable else b"\x00")
        + entry.size.to_bytes(8, "big")
        + bytes.fromhex(entry.content_digest.value)
    )


def tree_digest(entries: Iterable[TreeEntry]) -> Result[ObjectDigest]:
    ordered = tuple(sorted(entries, key=lambda entry: str(entry.path)))
    seen_paths: set[str] = set()
    for entry in ordered:
        path = str(entry.path)
        if path in seen_paths:
            return _invalid_tree(f"duplicate tree path: {path}")
        seen_paths.add(path)
    records: list[bytes] = []
    for entry in ordered:
        record = _tree_record(entry)
        if isinstance(record, Err):
            return record
        records.append(record.value)
    payload = b"AART-TREE-V1\x00" + b"".join(_frame(record) for record in records)
    return Ok(sha256_bytes(payload))
