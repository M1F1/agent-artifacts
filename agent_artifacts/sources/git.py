"""Bare-mirror Git acquisition into bounded inert source snapshots."""

from __future__ import annotations

import os
import re
import tarfile
import tempfile
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from agent_artifacts.configuration.model import git_location_parts
from agent_artifacts.configuration.policy import redact_text
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.io.git import (
    GitProcessReceipt,
    GitProcessRequest,
    run_git_process,
)
from agent_artifacts.protocol.native_tree import (
    SnapshotEntry,
    SnapshotEntryKind,
    SnapshotOrigin,
    SourceSnapshot,
)
from agent_artifacts.protocol.paths import parse_relative_path

from .model import GitSnapshotRequest, SourceCandidate, make_source_candidate

SOURCE_INVALID = DiagnosticCode("source-invalid")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_HOOK_FREE = (
    "git",
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "credential.interactive=never",
)
GitRunner = Callable[[GitProcessRequest], Result[GitProcessReceipt]]


def _error(message: str) -> Err:
    return Err((Diagnostic(SOURCE_INVALID, Severity.ERROR, redact_text(message)),))


def _command(request: GitSnapshotRequest, *arguments: str) -> GitProcessRequest:
    return GitProcessRequest(
        (*_HOOK_FREE, *arguments),
        request.temporary_root,
        request.timeout_seconds,
    )


def _allowed_location(request: GitSnapshotRequest) -> bool:
    if git_location_parts(request.location) is not None:
        return True
    if not request.allow_local_transport:
        return False
    parsed = urlsplit(request.location)
    if parsed.scheme == "file":
        return (
            parsed.username is None
            and parsed.password is None
            and parsed.netloc in {"", "localhost"}
            and not parsed.query
            and not parsed.fragment
            and bool(parsed.path)
            and os.path.isabs(parsed.path)
            and os.path.normpath(parsed.path) == parsed.path
        )
    return (
        os.path.isabs(request.location) and os.path.normpath(request.location) == request.location
    )


def _run(runner: GitRunner, request: GitProcessRequest) -> Result[GitProcessReceipt]:
    return runner(request)


def _tree_listing(
    raw: bytes,
    request: GitSnapshotRequest,
) -> Result[dict[str, int]]:
    files: dict[str, int] = {}
    total = 0
    records = tuple(item for item in raw.split(b"\x00") if item)
    for record in records:
        try:
            metadata, encoded_path = record.split(b"\t", 1)
            mode, object_type, _object_id, raw_size = metadata.split(b" ", 3)
            path = encoded_path.decode("utf-8", errors="strict")
            size = int(raw_size)
        except (ValueError, UnicodeDecodeError):
            return _error("Git tree listing is malformed or contains non-UTF-8 paths")
        parsed = parse_relative_path(path)
        if (
            isinstance(parsed, Err)
            or object_type != b"blob"
            or mode not in {b"100644", b"100755"}
            or len(parsed.value.parts) > request.limits.max_depth
            or size < 0
        ):
            return _error(f"Git tree contains an unsafe entry: {path!r}")
        if path in files:
            return _error(f"Git tree contains a duplicate path: {path}")
        if len(files) + 1 > request.limits.max_files:
            return _error("Git tree exceeds the configured file-count limit")
        if size > request.limits.max_file_bytes:
            return _error(f"Git tree file exceeds the configured size limit: {path}")
        total += size
        if total > request.limits.max_total_bytes:
            return _error("Git tree exceeds the configured total-size limit")
        files[path] = size
    return Ok(files)


def _snapshot_from_archive(
    archive_path: str,
    expected_files: dict[str, int],
    request: GitSnapshotRequest,
) -> Result[SourceSnapshot]:
    entries: dict[str, SnapshotEntry] = {}
    archive_files: dict[str, int] = {}
    try:
        with tarfile.open(archive_path, mode="r:") as archive:
            for member in archive:
                raw_path = member.name.removesuffix("/")
                parsed = parse_relative_path(raw_path)
                if isinstance(parsed, Err) or len(parsed.value.parts) > request.limits.max_depth:
                    return _error(f"Git archive contains an unsafe path: {member.name!r}")
                if raw_path in entries:
                    return _error(f"Git archive contains a duplicate path: {raw_path}")
                if member.isdir():
                    entries[raw_path] = SnapshotEntry(
                        parsed.value,
                        SnapshotEntryKind.DIRECTORY,
                    )
                    continue
                if not member.isreg() or raw_path not in expected_files:
                    return _error(f"Git archive contains a forbidden entry: {raw_path}")
                if member.size != expected_files[raw_path]:
                    return _error(f"Git archive size does not match tree metadata: {raw_path}")
                stream = archive.extractfile(member)
                if stream is None:
                    return _error(f"Git archive file cannot be read: {raw_path}")
                content = stream.read(request.limits.max_file_bytes + 1)
                if len(content) != member.size:
                    return _error(f"Git archive file is truncated: {raw_path}")
                entries[raw_path] = SnapshotEntry(
                    parsed.value,
                    SnapshotEntryKind.FILE,
                    content,
                    bool(member.mode & 0o111),
                )
                archive_files[raw_path] = member.size
    except (OSError, tarfile.TarError) as error:
        return _error(f"cannot read Git archive: {error}")
    if archive_files != expected_files:
        return _error("Git archive files do not match the resolved tree")
    for path in sorted(archive_files):
        parts = path.split("/")
        for length in range(1, len(parts)):
            directory = "/".join(parts[:length])
            if directory in entries:
                continue
            parsed = parse_relative_path(directory)
            if isinstance(parsed, Err):
                return _error(f"Git archive directory is unsafe: {directory}")
            entries[directory] = SnapshotEntry(parsed.value, SnapshotEntryKind.DIRECTORY)
    return Ok(SourceSnapshot(SnapshotOrigin.IMMUTABLE_GIT, tuple(entries.values())))


def _resolved_expressions(ref: str) -> tuple[str, ...]:
    if ref.startswith("refs/") or _COMMIT_RE.fullmatch(ref) is not None:
        return (f"{ref}^{{commit}}",)
    return (
        f"refs/remotes/origin/{ref}^{{commit}}",
        f"refs/tags/{ref}^{{commit}}",
    )


def acquire_git_snapshot(
    request: GitSnapshotRequest,
    *,
    runner: GitRunner = run_git_process,
) -> Result[SourceCandidate]:
    """Fetch a bare mirror and return bytes from one resolved commit without checkout hooks."""

    if not _allowed_location(request):
        return _error("Git source location must be credential-free HTTPS/SSH")
    try:
        Path(request.temporary_root).mkdir(parents=True, exist_ok=True, mode=0o700)
        Path(request.mirror_path).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError as error:
        return _error(f"cannot prepare Git source storage: {error}")
    new_mirror = not os.path.lexists(request.mirror_path)
    if not new_mirror and (
        Path(request.mirror_path).is_symlink() or not Path(request.mirror_path).is_dir()
    ):
        return _error("managed Git mirror must be a real directory")
    if new_mirror:
        initialized = _run(
            runner,
            _command(request, "init", "--bare", request.mirror_path),
        )
        if isinstance(initialized, Err):
            return initialized
    configured = _run(
        runner,
        _command(
            request,
            "-C",
            request.mirror_path,
            "remote",
            "add" if new_mirror else "set-url",
            "origin",
            request.location,
        ),
    )
    if isinstance(configured, Err) and not new_mirror:
        configured = _run(
            runner,
            _command(
                request,
                "-C",
                request.mirror_path,
                "remote",
                "add",
                "origin",
                request.location,
            ),
        )
    if isinstance(configured, Err):
        return configured
    fetched = _run(
        runner,
        _command(
            request,
            "-C",
            request.mirror_path,
            "fetch",
            "--force",
            "--prune",
            "--tags",
            "origin",
        ),
    )
    if isinstance(fetched, Err):
        return fetched
    resolved: Result[GitProcessReceipt] | None = None
    for expression in _resolved_expressions(request.ref):
        resolved = _run(
            runner,
            _command(
                request,
                "-C",
                request.mirror_path,
                "rev-parse",
                "--verify",
                "--end-of-options",
                expression,
            ),
        )
        if isinstance(resolved, Ok):
            break
    assert resolved is not None
    if isinstance(resolved, Err):
        return resolved
    commit = resolved.value.stdout.decode("ascii", errors="ignore").strip()
    if _COMMIT_RE.fullmatch(commit) is None:
        return _error("Git ref did not resolve to one canonical commit")
    listing = _run(
        runner,
        _command(
            request,
            "-C",
            request.mirror_path,
            "ls-tree",
            "-rlz",
            commit,
        ),
    )
    if isinstance(listing, Err):
        return listing
    expected_files = _tree_listing(listing.value.stdout, request)
    if isinstance(expected_files, Err):
        return expected_files
    descriptor, archive_path = tempfile.mkstemp(
        prefix="source-archive-",
        suffix=".tar",
        dir=request.temporary_root,
    )
    os.close(descriptor)
    try:
        archived = _run(
            runner,
            _command(
                request,
                "-C",
                request.mirror_path,
                "archive",
                "--format=tar",
                f"--output={archive_path}",
                commit,
            ),
        )
        if isinstance(archived, Err):
            return archived
        snapshot = _snapshot_from_archive(archive_path, expected_files.value, request)
        if isinstance(snapshot, Err):
            return snapshot
        return make_source_candidate(
            request.instance_id,
            request.alias,
            commit,
            snapshot.value,
        )
    finally:
        try:
            os.unlink(archive_path)
        except FileNotFoundError:
            pass
