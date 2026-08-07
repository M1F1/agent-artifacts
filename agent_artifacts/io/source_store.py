"""Atomic managed source snapshots, current pointers, and per-source leases."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import socket
import stat
import tempfile
import time
from pathlib import Path
from typing import Callable

from agent_artifacts.configuration.policy import redact_text
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.protocol.native_tree import SnapshotEntryKind, SourceSnapshot
from agent_artifacts.sources.local import read_local_snapshot
from agent_artifacts.sources.model import (
    CurrentSource,
    CurrentSourceRequest,
    LocalSnapshotRequest,
    SnapshotLimits,
    SourceLockLease,
    SourceLockRequest,
    SourcePublishCommand,
    SourcePublishReceipt,
    make_source_candidate,
)
from agent_artifacts.sources.pointer import (
    CurrentPointer,
    current_pointer_bytes,
    parse_current_pointer,
)

SOURCE_INVALID = DiagnosticCode("source-invalid")
SOURCE_UNAVAILABLE = DiagnosticCode("source-unavailable")
SOURCE_LOCK_BUSY = DiagnosticCode("source-lock-busy")


def _error(code: DiagnosticCode, message: str, *remediation: str) -> Err:
    return Err(
        (
            Diagnostic(
                code,
                Severity.ERROR,
                redact_text(message),
                remediation=tuple(remediation),
            ),
        )
    )


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _is_real_directory(path: Path) -> bool:
    try:
        return stat.S_ISDIR(os.stat(path, follow_symlinks=False).st_mode)
    except OSError:
        return False


def _atomic_private_write(path: Path, content: bytes) -> Result[None]:
    stage: str | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, stage = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(stage, path)
        stage = None
        os.chmod(path, 0o600)
        _fsync_directory(path.parent)
        return Ok(None)
    except OSError as error:
        return _error(SOURCE_UNAVAILABLE, f"cannot write managed source state: {error}")
    finally:
        if stage is not None:
            try:
                os.unlink(stage)
            except OSError:
                pass


def _write_snapshot_tree(stage: Path, command: SourcePublishCommand) -> Result[None]:
    source_root = stage / "source"
    try:
        source_root.mkdir(mode=0o700)
        for entry in command.validated.candidate.snapshot.entries:
            target = source_root.joinpath(*entry.path.parts)
            if entry.kind is SnapshotEntryKind.DIRECTORY:
                target.mkdir(parents=True, exist_ok=True, mode=0o700)
                os.chmod(target, 0o700)
                continue
            if entry.kind is not SnapshotEntryKind.FILE:
                return _error(SOURCE_INVALID, f"cannot publish unsafe snapshot entry: {entry.path}")
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            descriptor = os.open(
                target,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o700 if entry.executable else 0o600,
            )
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(entry.content)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(target, 0o700 if entry.executable else 0o600)
        for directory, _children, _files in os.walk(source_root, topdown=False):
            _fsync_directory(Path(directory))
        _fsync_directory(stage)
        return Ok(None)
    except OSError as error:
        return _error(SOURCE_UNAVAILABLE, f"cannot stage managed source snapshot: {error}")


def _snapshot_root(command: SourcePublishCommand) -> Path:
    return Path(command.paths.snapshots) / command.validated.candidate.snapshot_digest.value


def _read_snapshot(
    request: CurrentSourceRequest,
    pointer: CurrentPointer,
    source_root: Path,
) -> Result[CurrentSource]:
    local = read_local_snapshot(
        LocalSnapshotRequest(
            pointer.instance_id,
            request.alias,
            str(source_root),
            SnapshotLimits(),
        )
    )
    if isinstance(local, Err):
        return local
    snapshot = SourceSnapshot(pointer.origin, local.value.snapshot.entries)
    candidate = make_source_candidate(
        pointer.instance_id,
        request.alias,
        pointer.resolved_revision,
        snapshot,
    )
    if isinstance(candidate, Err):
        return candidate
    if candidate.value.snapshot_digest != pointer.snapshot_digest:
        return _error(
            SOURCE_INVALID, "managed source snapshot digest does not match current pointer"
        )
    return Ok(
        CurrentSource(
            candidate.value,
            pointer.declared_source_id,
            pointer.published_at_epoch_seconds,
            str(source_root),
        )
    )


def read_current_source(request: CurrentSourceRequest) -> Result[CurrentSource | None]:
    path = Path(request.paths.current_file)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return Ok(None)
    except OSError as error:
        return _error(SOURCE_UNAVAILABLE, f"cannot read current source pointer: {error}")
    pointer = parse_current_pointer(raw)
    if isinstance(pointer, Err):
        return pointer
    expected_instance = Path(request.paths.root).name
    if pointer.value.instance_id.value != expected_instance:
        return _error(SOURCE_INVALID, "current source pointer belongs to another source instance")
    source_root = Path(request.paths.snapshots) / pointer.value.snapshot_digest.value / "source"
    snapshot_root = source_root.parent
    if not _is_real_directory(snapshot_root) or not _is_real_directory(source_root):
        return _error(SOURCE_INVALID, "current source snapshot directory is missing")
    loaded = _read_snapshot(request, pointer.value, source_root)
    if isinstance(loaded, Err):
        return loaded
    return Ok(loaded.value)


def publish_source_snapshot(command: SourcePublishCommand) -> Result[SourcePublishReceipt]:
    snapshots = Path(command.paths.snapshots)
    target = _snapshot_root(command)
    stage: Path | None = None
    created = False
    if Path(command.paths.root).name != command.validated.candidate.instance_id.value:
        return _error(SOURCE_INVALID, "source snapshot belongs to another managed source instance")
    try:
        snapshots.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not _is_real_directory(snapshots):
            return _error(SOURCE_INVALID, "managed source snapshots root is not a real directory")
        stage = Path(tempfile.mkdtemp(prefix=".stage-", dir=snapshots))
        os.chmod(stage, 0o700)
        staged = _write_snapshot_tree(stage, command)
        if isinstance(staged, Err):
            return staged
        try:
            os.rename(stage, target)
            stage = None
            created = True
            _fsync_directory(snapshots)
        except OSError as error:
            if not _is_real_directory(target):
                return _error(
                    SOURCE_UNAVAILABLE,
                    f"cannot publish managed source snapshot: {error}",
                )
        pointer = CurrentPointer(
            command.validated.candidate.instance_id,
            command.validated.candidate.resolved_revision,
            command.validated.candidate.snapshot_digest,
            command.validated.declared_source_id,
            command.validated.candidate.snapshot.origin,
            command.observed_at_epoch_seconds,
        )
        current = _read_snapshot(
            CurrentSourceRequest(command.paths, command.validated.candidate.alias),
            pointer,
            target / "source",
        )
        if isinstance(current, Err):
            return current
        current_written = _atomic_private_write(
            Path(command.paths.current_file),
            current_pointer_bytes(pointer),
        )
        if isinstance(current_written, Err):
            return current_written
        return Ok(SourcePublishReceipt(current.value, created))
    except OSError as error:
        return _error(SOURCE_UNAVAILABLE, f"cannot prepare managed source snapshot: {error}")
    finally:
        if stage is not None:
            shutil.rmtree(stage, ignore_errors=True)


def _owner_alive(hostname: str, pid: int) -> bool:
    if hostname != socket.gethostname():
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    return True


def _owner(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None
    if not isinstance(value, dict):
        return None
    return value


def _token_suffix(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


def _write_owner(path: Path, token: str, acquired_at: int) -> None:
    payload = (
        json.dumps(
            {
                "acquired_at_epoch_seconds": acquired_at,
                "hostname": socket.gethostname(),
                "pid": os.getpid(),
                "schema_version": 1,
                "token": token,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def acquire_source_lock(
    request: SourceLockRequest,
    *,
    token_factory: Callable[[], str] = lambda: secrets.token_hex(16),
    now: Callable[[], float] = time.time,
    monotonic: Callable[[], float] = time.monotonic,
    owner_alive: Callable[[str, int], bool] = _owner_alive,
    sleep: Callable[[float], None] = time.sleep,
) -> Result[SourceLockLease]:
    lock = Path(request.lock_directory)
    try:
        lock.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError as error:
        return _error(SOURCE_UNAVAILABLE, f"cannot prepare source lock: {error}")
    deadline = monotonic() + request.timeout_seconds
    token = token_factory()
    if not token or "\n" in token or "\r" in token:
        return _error(SOURCE_INVALID, "source lock token generator returned an invalid value")
    while True:
        try:
            os.mkdir(lock, 0o700)
            _write_owner(lock / "owner.json", token, int(now()))
            _fsync_directory(lock)
            _fsync_directory(lock.parent)
            return Ok(SourceLockLease(str(lock), token))
        except FileExistsError:
            owner = _owner(lock / "owner.json")
            acquired = None if owner is None else owner.get("acquired_at_epoch_seconds")
            hostname = None if owner is None else owner.get("hostname")
            pid = None if owner is None else owner.get("pid")
            observed_at = now()
            valid_owner = (
                isinstance(acquired, int)
                and not isinstance(acquired, bool)
                and isinstance(hostname, str)
                and isinstance(pid, int)
                and not isinstance(pid, bool)
            )
            if valid_owner:
                assert isinstance(acquired, int)
                assert isinstance(hostname, str)
                assert isinstance(pid, int)
                stale = observed_at - acquired > request.stale_after_seconds and not owner_alive(
                    hostname, pid
                )
            else:
                try:
                    lock_status = os.stat(lock, follow_symlinks=False)
                    stale = (
                        stat.S_ISDIR(lock_status.st_mode)
                        and observed_at - lock_status.st_mtime > request.stale_after_seconds
                    )
                except OSError:
                    stale = False
            if stale:
                abandoned = lock.with_name(f"{lock.name}.stale-{_token_suffix(token)}")
                try:
                    os.rename(lock, abandoned)
                    shutil.rmtree(abandoned, ignore_errors=True)
                    _fsync_directory(lock.parent)
                    continue
                except OSError:
                    pass
            if monotonic() >= deadline:
                return _error(
                    SOURCE_LOCK_BUSY,
                    "source synchronization is already running",
                    "retry after the active synchronization completes",
                )
            sleep(min(0.05, max(0.0, deadline - monotonic())))
        except OSError as error:
            try:
                shutil.rmtree(lock)
            except OSError:
                pass
            return _error(SOURCE_UNAVAILABLE, f"cannot acquire source lock: {error}")


def release_source_lock(lease: SourceLockLease) -> Result[None]:
    lock = Path(lease.lock_directory)
    if not _is_real_directory(lock):
        return _error(SOURCE_INVALID, "source lock is not a real directory")
    owner = _owner(lock / "owner.json")
    if owner is None or owner.get("token") != lease.token:
        return _error(SOURCE_INVALID, "source lock ownership changed before release")
    released = lock.with_name(f"{lock.name}.release-{_token_suffix(lease.token)}")
    try:
        os.rename(lock, released)
        shutil.rmtree(released)
        _fsync_directory(lock.parent)
        return Ok(None)
    except OSError as error:
        return _error(SOURCE_UNAVAILABLE, f"cannot release source lock: {error}")
