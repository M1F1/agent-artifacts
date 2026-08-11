"""Locked, compare-and-swap configuration writes.

``write_configuration`` replaces the configuration unconditionally.  That is safe on its own, but
source management does not write immediately: it reads the configuration, performs a slow network
synchronization, re-reads to detect drift, and only then writes.  A writer that lands between that
re-read and the replace is silently overwritten — CB01 recorded that residual risk as ``CFG02``
rather than hiding it behind the pre-write re-read.

This module closes it.  A write names the exact state it expects to replace, and the compare happens
*inside* a configuration-scoped lock, immediately before the atomic replace, so no window remains in
which another writer can land unnoticed.  A losing writer is refused with a deterministic retry
diagnostic; it never wins by being second.
"""

from __future__ import annotations

import os
import posixpath
import secrets
import shutil
import stat
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.io.config_store import ConfigWriteReceipt, _fsync_directory
from agent_artifacts.io.source_store import _owner, _owner_alive, _token_suffix, _write_owner
from agent_artifacts.protocol.hashing import sha256_bytes

CONFIG_UNAVAILABLE = DiagnosticCode("config-unavailable")
CONFIG_WRITE_CONFLICT = DiagnosticCode("config-write-conflict")
CONFIG_LOCK_BUSY = DiagnosticCode("config-lock-busy")


@dataclass(frozen=True, slots=True)
class ConfigCasDocument:
    """One configuration write and the exact prior state it is allowed to replace.

    ``expected_digest`` of ``None`` means "this file must not exist yet", which is what first-run
    onboarding reviewed.  Any other value must match the bytes currently on disk.
    """

    path: str
    content: bytes
    expected_digest: object | None
    lock_directory: str

    def __post_init__(self) -> None:
        for value in (self.path, self.lock_directory):
            if not posixpath.isabs(value) or posixpath.normpath(value) != value:
                raise ValueError("configuration write paths must be normalized and absolute")
        if not isinstance(self.content, bytes):
            raise ValueError("configuration content must be bytes")


def _error(code: DiagnosticCode, message: str, *remediation: str) -> Err:
    return Err((Diagnostic(code, Severity.ERROR, message, remediation=remediation),))


def _conflict(detail: str) -> Err:
    return _error(
        CONFIG_WRITE_CONFLICT,
        f"configuration changed after it was reviewed: {detail}",
        "re-read the current configuration, review the change, and retry",
    )


def _acquire(
    lock: Path,
    *,
    timeout_seconds: float,
    stale_after_seconds: int,
    token: str,
    now: Callable[[], float],
    monotonic: Callable[[], float],
    sleep: Callable[[float], None],
) -> Result[None]:
    try:
        lock.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError as error:
        return _error(CONFIG_UNAVAILABLE, f"cannot prepare configuration lock: {error}")
    deadline = monotonic() + timeout_seconds
    while True:
        try:
            os.mkdir(lock, 0o700)
            _write_owner(lock / "owner.json", token, int(now()))
            _fsync_directory(lock)
            return Ok(None)
        except FileExistsError:
            owner = _owner(lock / "owner.json")
            acquired = None if owner is None else owner.get("acquired_at_epoch_seconds")
            hostname = None if owner is None else owner.get("hostname")
            pid = None if owner is None else owner.get("pid")
            observed_at = now()
            if (
                isinstance(acquired, int)
                and not isinstance(acquired, bool)
                and isinstance(hostname, str)
                and isinstance(pid, int)
                and not isinstance(pid, bool)
            ):
                # Only reclaim a lock whose holder is both old and provably gone: a live writer
                # performing a slow sync must never have its lock stolen.
                stale = observed_at - acquired > stale_after_seconds and not _owner_alive(
                    hostname, pid
                )
            else:
                stale = False
            if stale:
                abandoned = lock.with_name(f"{lock.name}.stale-{_token_suffix(token)}")
                try:
                    os.rename(lock, abandoned)
                    shutil.rmtree(abandoned, ignore_errors=True)
                    continue
                except OSError:
                    pass
            if monotonic() >= deadline:
                return _error(
                    CONFIG_LOCK_BUSY,
                    "another configuration write is already running",
                    "retry after the active configuration write completes",
                )
            sleep(min(0.05, max(0.0, deadline - monotonic())))
        except OSError as error:
            return _error(CONFIG_UNAVAILABLE, f"cannot acquire configuration lock: {error}")


def _release(lock: Path) -> None:
    try:
        if stat.S_ISDIR(os.stat(lock, follow_symlinks=False).st_mode):
            shutil.rmtree(lock, ignore_errors=True)
    except OSError:
        pass


def _current_digest(path: Path) -> Result[object | None]:
    try:
        return Ok(sha256_bytes(path.read_bytes()))
    except FileNotFoundError:
        return Ok(None)
    except OSError as error:
        return _error(CONFIG_UNAVAILABLE, f"cannot read configuration: {error}")


def _replace(path: Path, content: bytes) -> Result[ConfigWriteReceipt]:
    stage: str | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, stage = tempfile.mkstemp(prefix=".aart-config-", dir=path.parent)
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(stage, path)
        stage = None
        os.chmod(path, 0o600)
        _fsync_directory(path.parent)
        return Ok(ConfigWriteReceipt(str(path), sha256_bytes(content)))
    except OSError as error:
        return _error(CONFIG_UNAVAILABLE, f"cannot write configuration: {error}")
    finally:
        if stage is not None:
            try:
                os.unlink(stage)
            except OSError:
                pass


def write_configuration_checked(
    document: ConfigCasDocument,
    *,
    timeout_seconds: float = 10.0,
    stale_after_seconds: int = 600,
    token_factory: Callable[[], str] = lambda: secrets.token_hex(16),
    now: Callable[[], float] = time.time,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> Result[ConfigWriteReceipt]:
    """Replace the configuration only if it still holds the exact reviewed state."""

    lock = Path(document.lock_directory)
    token = token_factory()
    acquired = _acquire(
        lock,
        timeout_seconds=timeout_seconds,
        stale_after_seconds=stale_after_seconds,
        token=token,
        now=now,
        monotonic=monotonic,
        sleep=sleep,
    )
    if isinstance(acquired, Err):
        return acquired
    try:
        # Compare under the lock and immediately before the replace: this is the whole point, and
        # the reason a caller's earlier read cannot be trusted on its own.
        observed = _current_digest(Path(document.path))
        if isinstance(observed, Err):
            return observed
        if observed.value != document.expected_digest:
            if document.expected_digest is None:
                return _conflict("a configuration already exists")
            if observed.value is None:
                return _conflict("the configuration was removed")
            return _conflict("its contents no longer match the reviewed state")
        return _replace(Path(document.path), document.content)
    finally:
        _release(lock)


# How long a reviewed write waits for a competing writer to finish before giving up. Generous
# enough to outlast an ordinary write, short enough that a wedged process does not hang a CLI.
DEFAULT_LOCK_TIMEOUT_SECONDS = 10.0


def checked_config_writer(document) -> Result[ConfigWriteReceipt]:
    """Adapt the application-layer ``CheckedConfigDocument`` port to this implementation."""

    return write_configuration_checked(
        ConfigCasDocument(
            document.path,
            document.content,
            document.expected_digest,
            document.lock_directory,
        ),
        timeout_seconds=DEFAULT_LOCK_TIMEOUT_SECONDS,
    )


__all__ = [
    "CONFIG_LOCK_BUSY",
    "CONFIG_UNAVAILABLE",
    "CONFIG_WRITE_CONFLICT",
    "ConfigCasDocument",
    "checked_config_writer",
    "write_configuration_checked",
]
