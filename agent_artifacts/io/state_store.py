"""Private, atomic adapter for installation state and reviewed legacy migration."""

from __future__ import annotations

import fcntl
import os
import posixpath
import re
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.install_state.model import (
    InstallState,
    InstallStatePaths,
    MigrationReceipt,
    RollbackReceipt,
    StateMigrationPlan,
)
from agent_artifacts.install_state.ports import StateMigrationPort
from agent_artifacts.install_state.schema import parse_install_state
from agent_artifacts.protocol.hashing import parse_sha256
from agent_artifacts.protocol.json import JsonObject, parse_json

STATE_IO_FAILED = DiagnosticCode("state-io-failed")
STATE_MIGRATION_STALE = DiagnosticCode("state-migration-stale")
STATE_MIGRATION_BUSY = DiagnosticCode("state-migration-busy")
_MAX_STATE_BYTES = 10 * 1024 * 1024
_JOURNAL_NAME_RE = re.compile(r"^manifest-v1-[0-9a-f]{64}(?:-[1-9][0-9]{0,3}|-10000)?\.json$")


def _error(code: DiagnosticCode, message: str) -> Err:
    return Err((Diagnostic(code, Severity.ERROR, message),))


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _safe_parent(directory: Path) -> None:
    probe = directory
    missing: list[Path] = []
    while not probe.exists():
        missing.append(probe)
        if probe == probe.parent:
            break
        probe = probe.parent
    if probe.exists() and probe.is_symlink():
        raise OSError(f"state parent is a symlink: {probe}")
    for item in reversed(missing):
        item.mkdir(mode=0o700)
    for item in (directory, *directory.parents):
        if not item.exists() or item == item.parent:
            continue
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise OSError(f"state parent is a symlink: {item}")
        if not stat.S_ISDIR(info.st_mode):
            raise OSError(f"state parent is not a directory: {item}")
        if item == probe:
            break


def _read_regular(path: Path) -> bytes | None:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise OSError(f"state path is not a regular file: {path}")
        if info.st_size > _MAX_STATE_BYTES:
            raise OSError(f"state file exceeds {_MAX_STATE_BYTES} bytes: {path}")
        chunks: list[bytes] = []
        remaining = _MAX_STATE_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        if len(content) > _MAX_STATE_BYTES:
            raise OSError(f"state file exceeds {_MAX_STATE_BYTES} bytes: {path}")
        return content
    finally:
        os.close(descriptor)


def _write_private_atomic(path: Path, content: bytes) -> None:
    directory = path.parent
    _safe_parent(directory)
    stage: str | None = None
    try:
        descriptor, stage = tempfile.mkstemp(prefix=".aart-state-", dir=directory)
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(stage, path)
        stage = None
        os.chmod(path, 0o600)
        _fsync_directory(directory)
    finally:
        if stage is not None:
            try:
                os.unlink(stage)
            except OSError:
                pass


def _unlink(path: Path) -> None:
    path.unlink()
    _fsync_directory(path.parent)


@contextmanager
def _exclusive_lock(path: Path) -> Iterator[None]:
    _safe_parent(path.parent)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("another state migration is active") from error
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _is_current(plan: StateMigrationPlan) -> bool:
    legacy = _read_regular(Path(plan.legacy_path))
    destination = _read_regular(Path(plan.destination_path))
    backup = _read_regular(Path(plan.backup_path))
    journal = _read_regular(Path(plan.journal_path))
    if plan.scope == "project":
        return (
            legacy == plan.replacement
            and backup == plan.legacy_content
            and journal == plan.journal_content
        )
    return (
        legacy is None
        and destination == plan.replacement
        and backup == plan.legacy_content
        and journal == plan.journal_content
    )


def _validate_resumable(plan: StateMigrationPlan) -> Result[None]:
    replacement = parse_install_state(plan.replacement, path=plan.destination_path)
    if isinstance(replacement, Err):
        return _error(
            STATE_MIGRATION_STALE,
            "reviewed migration replacement is not valid installation manifest v2",
        )
    legacy = _read_regular(Path(plan.legacy_path))
    destination = _read_regular(Path(plan.destination_path))
    backup = _read_regular(Path(plan.backup_path))
    journal = _read_regular(Path(plan.journal_path))
    if backup not in {None, plan.legacy_content} or journal not in {
        None,
        plan.journal_content,
    }:
        return _error(
            STATE_MIGRATION_STALE,
            "migration backup or journal contains a different operation",
        )
    if plan.scope == "project":
        valid = legacy in {plan.legacy_content, plan.replacement}
        partial_requires_backup = legacy == plan.replacement or journal is not None
    else:
        valid = legacy in {None, plan.legacy_content} and destination in {
            None,
            plan.replacement,
        }
        partial_requires_backup = (
            legacy is None or destination == plan.replacement or journal is not None
        )
    if not valid or (partial_requires_backup and backup != plan.legacy_content):
        return _error(
            STATE_MIGRATION_STALE,
            "state changed after migration review; refusing an unsafe apply/resume",
        )
    return Ok(None)


def _recover_failed_apply(plan: StateMigrationPlan) -> tuple[str, ...]:
    """Best-effort compensation that always prioritizes a usable legacy manifest."""

    errors: list[str] = []
    legacy_path = Path(plan.legacy_path)
    destination = Path(plan.destination_path)
    journal = Path(plan.journal_path)
    try:
        legacy = _read_regular(legacy_path)
        if plan.scope == "project":
            if legacy != plan.legacy_content:
                if legacy in {None, plan.replacement}:
                    _write_private_atomic(legacy_path, plan.legacy_content)
                else:
                    errors.append("project state contains unexpected concurrent content")
        elif legacy is None:
            _write_private_atomic(legacy_path, plan.legacy_content)
        elif legacy != plan.legacy_content:
            errors.append("legacy state contains unexpected concurrent content")
    except OSError as error:
        errors.append(f"could not restore legacy state: {error}")
    if plan.scope == "user":
        try:
            migrated = _read_regular(destination)
            if migrated == plan.replacement:
                _unlink(destination)
            elif migrated is not None:
                errors.append("destination contains unexpected concurrent content")
        except OSError as error:
            errors.append(f"could not remove partial destination: {error}")
    try:
        journal_content = _read_regular(journal)
        if journal_content == plan.journal_content:
            _unlink(journal)
        elif journal_content is not None:
            errors.append("journal contains unexpected concurrent content")
    except OSError as error:
        errors.append(f"could not remove partial journal: {error}")
    return tuple(errors)


def _restore_migrated_state(plan: StateMigrationPlan) -> tuple[str, ...]:
    """Best-effort compensation for a failed rollback."""

    errors: list[str] = []
    legacy_path = Path(plan.legacy_path)
    destination = Path(plan.destination_path)
    journal = Path(plan.journal_path)
    try:
        if plan.scope == "user":
            legacy = _read_regular(legacy_path)
            if legacy == plan.legacy_content:
                _unlink(legacy_path)
            elif legacy is not None:
                errors.append("legacy path contains unexpected concurrent content")
        current = _read_regular(destination)
        if current != plan.replacement:
            if current in {None, plan.legacy_content}:
                _write_private_atomic(destination, plan.replacement)
            else:
                errors.append("destination contains unexpected concurrent content")
        current_journal = _read_regular(journal)
        if current_journal != plan.journal_content:
            if current_journal is None:
                _write_private_atomic(journal, plan.journal_content)
            else:
                errors.append("journal contains unexpected concurrent content")
    except OSError as error:
        errors.append(f"could not restore migrated state: {error}")
    return tuple(errors)


class LocalStateStore(StateMigrationPort):
    """Local stdlib adapter; domain planning stays in ``install_state.migration``."""

    def read(self, path: str) -> Result[bytes | None]:
        try:
            return Ok(_read_regular(Path(path)))
        except OSError as error:
            return _error(STATE_IO_FAILED, f"cannot read installation state at {path}: {error}")

    def read_state(self, path: str) -> Result[InstallState | None]:
        content = self.read(path)
        if isinstance(content, Err):
            return content
        if content.value is None:
            return Ok(None)
        return parse_install_state(content.value, path=path)

    def apply(self, plan: StateMigrationPlan) -> Result[MigrationReceipt]:
        try:
            with _exclusive_lock(Path(plan.lock_path)):
                if _is_current(plan):
                    return Ok(MigrationReceipt(plan, False))
                fresh = _validate_resumable(plan)
                if isinstance(fresh, Err):
                    return fresh
                backup = Path(plan.backup_path)
                destination = Path(plan.destination_path)
                journal = Path(plan.journal_path)
                try:
                    if _read_regular(backup) is None:
                        _write_private_atomic(backup, plan.legacy_content)
                    if _read_regular(journal) is None:
                        _write_private_atomic(journal, plan.journal_content)
                    if _read_regular(destination) != plan.replacement:
                        _write_private_atomic(destination, plan.replacement)
                    if plan.scope == "user" and _read_regular(Path(plan.legacy_path)) is not None:
                        _unlink(Path(plan.legacy_path))
                except OSError as error:
                    recovery_errors = _recover_failed_apply(plan)
                    suffix = (
                        ""
                        if not recovery_errors
                        else "; recovery incomplete: " + "; ".join(recovery_errors)
                    )
                    return _error(STATE_IO_FAILED, f"state migration failed: {error}{suffix}")
                return Ok(MigrationReceipt(plan, True))
        except RuntimeError as error:
            return _error(STATE_MIGRATION_BUSY, str(error))
        except OSError as error:
            return _error(STATE_IO_FAILED, f"state migration failed: {error}")

    def rollback(self, receipt: MigrationReceipt) -> Result[RollbackReceipt]:
        plan = receipt.plan
        try:
            with _exclusive_lock(Path(plan.lock_path)):
                legacy_path = Path(plan.legacy_path)
                destination = Path(plan.destination_path)
                journal = Path(plan.journal_path)
                backup = _read_regular(Path(plan.backup_path))
                current_legacy = _read_regular(legacy_path)
                current_destination = _read_regular(destination)
                current_journal = _read_regular(journal)
                if (
                    plan.scope == "project"
                    and current_legacy == plan.legacy_content
                    and current_journal is None
                ):
                    return Ok(RollbackReceipt(plan.review_digest, False))
                if (
                    plan.scope == "user"
                    and current_legacy == plan.legacy_content
                    and current_destination is None
                    and current_journal is None
                ):
                    return Ok(RollbackReceipt(plan.review_digest, False))
                if (
                    backup != plan.legacy_content
                    or current_destination != plan.replacement
                    or current_journal != plan.journal_content
                    or (plan.scope == "user" and current_legacy is not None)
                ):
                    return _error(
                        STATE_MIGRATION_STALE,
                        "migration state changed after apply; refusing unsafe rollback",
                    )
                if plan.scope == "project":
                    try:
                        _write_private_atomic(destination, plan.legacy_content)
                        _unlink(journal)
                    except OSError as error:
                        recovery_errors = _restore_migrated_state(plan)
                        suffix = (
                            ""
                            if not recovery_errors
                            else "; recovery incomplete: " + "; ".join(recovery_errors)
                        )
                        return _error(
                            STATE_IO_FAILED,
                            f"state migration rollback failed: {error}{suffix}",
                        )
                else:
                    try:
                        _write_private_atomic(legacy_path, plan.legacy_content)
                        _unlink(destination)
                        _unlink(journal)
                    except OSError as error:
                        recovery_errors = _restore_migrated_state(plan)
                        suffix = (
                            ""
                            if not recovery_errors
                            else "; recovery incomplete: " + "; ".join(recovery_errors)
                        )
                        return _error(
                            STATE_IO_FAILED,
                            f"state migration rollback failed: {error}{suffix}",
                        )
                return Ok(RollbackReceipt(plan.review_digest, True))
        except RuntimeError as error:
            return _error(STATE_MIGRATION_BUSY, str(error))
        except OSError as error:
            return _error(STATE_IO_FAILED, f"state migration rollback failed: {error}")

    def current_receipt(self, paths: InstallStatePaths) -> Result[MigrationReceipt | None]:
        """Reconstruct one completed receipt without trusting filenames or following links."""

        directory = Path(paths.journal_directory)
        try:
            if not directory.exists():
                return Ok(None)
            info = directory.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                return _error(STATE_IO_FAILED, "migration journal directory is unsafe")
            candidates: list[MigrationReceipt] = []
            with os.scandir(directory) as scanned:
                entries = sorted(scanned, key=lambda item: item.name)
            if len(entries) > 10_001:
                return _error(STATE_IO_FAILED, "migration journal directory exceeds safe bounds")
            suspicious = False
            for entry in entries:
                if _JOURNAL_NAME_RE.fullmatch(entry.name) is None or not entry.is_file(
                    follow_symlinks=False
                ):
                    continue
                content = _read_regular(Path(entry.path))
                if content is None:
                    continue
                parsed = parse_json(content)
                if isinstance(parsed, Err) or not isinstance(parsed.value, JsonObject):
                    suspicious = True
                    continue
                fields = dict(parsed.value.entries)
                required = {
                    "schema_version",
                    "review_digest",
                    "scope",
                    "legacy_path",
                    "destination_path",
                    "backup_path",
                    "legacy_digest",
                    "replacement_digest",
                }
                if set(fields) != required or fields["schema_version"] != 1:
                    suspicious = True
                    continue
                if not all(isinstance(fields[name], str) for name in required - {"schema_version"}):
                    suspicious = True
                    continue
                if (
                    fields["scope"] != paths.scope
                    or fields["legacy_path"] != paths.legacy_path
                    or fields["destination_path"] != paths.destination_path
                    or posixpath.dirname(str(fields["backup_path"])) != paths.backup_directory
                ):
                    suspicious = True
                    continue
                legacy_digest = parse_sha256(str(fields["legacy_digest"]))
                replacement_digest = parse_sha256(str(fields["replacement_digest"]))
                review_digest = parse_sha256(str(fields["review_digest"]))
                if (
                    isinstance(legacy_digest, Err)
                    or isinstance(replacement_digest, Err)
                    or isinstance(review_digest, Err)
                ):
                    suspicious = True
                    continue
                backup = _read_regular(Path(str(fields["backup_path"])))
                replacement = _read_regular(Path(paths.destination_path))
                if backup is None or replacement is None:
                    continue
                try:
                    plan = StateMigrationPlan(
                        paths.scope,
                        paths.legacy_path,
                        paths.destination_path,
                        str(fields["backup_path"]),
                        str(Path(entry.path)),
                        paths.lock_path,
                        legacy_digest.value,
                        replacement_digest.value,
                        backup,
                        replacement,
                        content,
                        review_digest.value,
                    )
                except ValueError:
                    suspicious = True
                    continue
                if _is_current(plan):
                    candidates.append(MigrationReceipt(plan, False))
            if len(candidates) > 1:
                return _error(
                    STATE_MIGRATION_STALE, "multiple active migration receipts were found"
                )
            if candidates:
                return Ok(candidates[0])
            if suspicious:
                destination = _read_regular(Path(paths.destination_path))
                if destination is not None and isinstance(
                    parse_install_state(destination, path=paths.destination_path), Ok
                ):
                    return _error(
                        STATE_MIGRATION_STALE,
                        "migration journal evidence is inconsistent with current v2 state",
                    )
            return Ok(None)
        except OSError as error:
            return _error(STATE_IO_FAILED, f"cannot load migration receipt: {error}")
