"""Atomic private filesystem adapter for configuration application ports."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from agent_artifacts.application.configuration import (
    ConfigDocument,
    ConfigReadRequest,
    ConfigRecoveryPlan,
    ConfigRecoveryReceipt,
    ConfigWriteReceipt,
)
from agent_artifacts.configuration.policy import redact_text
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.protocol.hashing import sha256_bytes

_CONFIG_IO = DiagnosticCode("config-io-failed")


def _error(action: str, path: str, error: OSError | str) -> Err:
    return Err(
        (
            Diagnostic(
                _CONFIG_IO,
                Severity.ERROR,
                redact_text(f"failed to {action} configuration at {path}: {error}"),
            ),
        )
    )


def read_configuration(request: ConfigReadRequest) -> Result[bytes | None]:
    try:
        return Ok(Path(request.path).read_bytes())
    except FileNotFoundError:
        return Ok(None)
    except OSError as error:
        return _error("read", request.path, error)


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_configuration(document: ConfigDocument) -> Result[ConfigWriteReceipt]:
    target = Path(document.path)
    directory = target.parent
    stage: str | None = None
    try:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, stage = tempfile.mkstemp(prefix=".aart-config-", dir=directory)
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(document.content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(stage, target)
        stage = None
        os.chmod(target, 0o600)
        _fsync_directory(directory)
        return Ok(ConfigWriteReceipt(document.path, sha256_bytes(document.content)))
    except OSError as error:
        return _error("write", document.path, error)
    finally:
        if stage is not None:
            try:
                os.unlink(stage)
            except OSError:
                pass


def recover_configuration(plan: ConfigRecoveryPlan) -> Result[ConfigRecoveryReceipt]:
    current = read_configuration(ConfigReadRequest(plan.path))
    if isinstance(current, Err):
        return current
    if current.value is None:
        return _error("recover", plan.path, "configuration disappeared before recovery")
    digest = sha256_bytes(current.value)
    if digest != plan.expected_digest:
        return _error("recover", plan.path, "configuration changed after recovery was planned")
    backup_path = Path(plan.backup_path)
    try:
        existing_backup = backup_path.read_bytes()
    except FileNotFoundError:
        backed_up = write_configuration(ConfigDocument(plan.backup_path, current.value))
        if isinstance(backed_up, Err):
            return backed_up
    except OSError as error:
        return _error("read recovery backup", plan.backup_path, error)
    else:
        if existing_backup != current.value:
            return _error(
                "recover", plan.backup_path, "recovery backup already contains other data"
            )
    replacement = write_configuration(ConfigDocument(plan.path, plan.replacement))
    if isinstance(replacement, Err):
        return replacement
    return Ok(
        ConfigRecoveryReceipt(
            plan.path,
            plan.backup_path,
            digest,
            replacement.value.digest,
        )
    )
