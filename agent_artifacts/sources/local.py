"""Bounded, non-following local filesystem snapshot acquisition."""

from __future__ import annotations

import os
import stat

from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.result import Err, Result
from agent_artifacts.protocol.native_tree import (
    SnapshotEntry,
    SnapshotEntryKind,
    SnapshotOrigin,
    SourceSnapshot,
)
from agent_artifacts.protocol.paths import parse_relative_path

from .model import (
    LocalSnapshotRequest,
    SourceCandidate,
    make_source_candidate,
    source_snapshot_digest,
)

SOURCE_INVALID = DiagnosticCode("source-invalid")


def _error(message: str) -> Err:
    return Err((Diagnostic(SOURCE_INVALID, Severity.ERROR, message),))


def read_local_snapshot(request: LocalSnapshotRequest) -> Result[SourceCandidate]:
    """Read one inert tree without following symlinks or opening special files."""

    root = request.root
    try:
        root_status = os.stat(root, follow_symlinks=False)
    except OSError as error:
        return _error(f"cannot inspect local source: {error}")
    if not stat.S_ISDIR(root_status.st_mode):
        return _error("local source root must be a directory")
    entries: list[SnapshotEntry] = []
    file_count = 0
    total_bytes = 0
    pending: list[tuple[str, str, int]] = [(root, "", 0)]
    while pending:
        directory, relative_directory, depth = pending.pop()
        if depth > request.limits.max_depth:
            return _error("local source exceeds the configured directory depth")
        try:
            with os.scandir(directory) as scan:
                children = tuple(sorted(scan, key=lambda item: item.name, reverse=True))
        except OSError as error:
            return _error(f"cannot read local source directory: {error}")
        for child in children:
            if not relative_directory and child.name == ".git":
                continue
            relative = (
                child.name if not relative_directory else f"{relative_directory}/{child.name}"
            )
            parsed = parse_relative_path(relative)
            if isinstance(parsed, Err):
                return _error(f"local source contains an unsafe path: {relative!r}")
            try:
                child_status = child.stat(follow_symlinks=False)
            except OSError as error:
                return _error(f"cannot inspect local source entry {relative!r}: {error}")
            if stat.S_ISLNK(child_status.st_mode):
                return _error(f"local source symlinks are forbidden: {relative}")
            if stat.S_ISDIR(child_status.st_mode):
                entries.append(SnapshotEntry(parsed.value, SnapshotEntryKind.DIRECTORY))
                pending.append((child.path, relative, depth + 1))
                continue
            if not stat.S_ISREG(child_status.st_mode):
                return _error(f"local source special files are forbidden: {relative}")
            file_count += 1
            if file_count > request.limits.max_files:
                return _error("local source exceeds the configured file-count limit")
            if child_status.st_size > request.limits.max_file_bytes:
                return _error(f"local source file exceeds the configured size limit: {relative}")
            total_bytes += child_status.st_size
            if total_bytes > request.limits.max_total_bytes:
                return _error("local source exceeds the configured total-size limit")
            try:
                flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                descriptor = os.open(child.path, flags)
                with os.fdopen(descriptor, "rb") as stream:
                    opened_status = os.fstat(stream.fileno())
                    if (
                        not stat.S_ISREG(opened_status.st_mode)
                        or opened_status.st_dev != child_status.st_dev
                        or opened_status.st_ino != child_status.st_ino
                        or opened_status.st_size != child_status.st_size
                    ):
                        return _error(f"local source changed while being opened: {relative}")
                    content = stream.read(request.limits.max_file_bytes + 1)
            except OSError as error:
                return _error(f"cannot read local source file {relative!r}: {error}")
            if len(content) != child_status.st_size or len(content) > request.limits.max_file_bytes:
                return _error(f"local source changed while being read: {relative}")
            entries.append(
                SnapshotEntry(
                    parsed.value,
                    SnapshotEntryKind.FILE,
                    content,
                    bool(child_status.st_mode & 0o111),
                )
            )
    snapshot = SourceSnapshot(SnapshotOrigin.LOCAL, tuple(entries))
    digest = source_snapshot_digest(snapshot)
    if isinstance(digest, Err):
        return digest
    return make_source_candidate(
        request.instance_id,
        request.alias,
        f"local:{digest.value.value}",
        snapshot,
    )
