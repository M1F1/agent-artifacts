"""Atomic private filesystem persistence for object references."""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

from agent_artifacts.configuration.policy import redact_text
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.store.model import (
    ReferenceIndex,
    ReferenceReadRequest,
    ReferenceWriteCommand,
)
from agent_artifacts.store.references import parse_reference_index, reference_index_bytes

STORE_UNAVAILABLE = DiagnosticCode("store-unavailable")
STORE_UNSAFE_ENTRY = DiagnosticCode("store-unsafe-entry")
_MAX_REFERENCE_BYTES = 10 * 1024 * 1024


def _error(message: str, *, code: DiagnosticCode = STORE_UNAVAILABLE) -> Err:
    return Err((Diagnostic(code, Severity.ERROR, redact_text(message)),))


def _real_directory(path: Path) -> bool:
    try:
        return stat.S_ISDIR(os.stat(path, follow_symlinks=False).st_mode)
    except OSError:
        return False


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _managed_components(path: Path, root: str) -> tuple[Path, ...]:
    managed_root = Path(root)
    return managed_root, managed_root / "state", path.parent


def _existing_components_are_real(components: tuple[Path, ...]) -> bool:
    return all(not os.path.lexists(path) or _real_directory(path) for path in components)


def read_references(request: ReferenceReadRequest) -> Result[ReferenceIndex]:
    path = Path(request.paths.references_file)
    if not _existing_components_are_real(_managed_components(path, request.paths.root)):
        return _error(
            "object reference state directory is unsafe",
            code=STORE_UNSAFE_ENTRY,
        )
    if not os.path.lexists(path):
        return Ok(ReferenceIndex(1, ()))
    try:
        expected = os.stat(path, follow_symlinks=False)
        if not stat.S_ISREG(expected.st_mode) or expected.st_size > _MAX_REFERENCE_BYTES:
            return _error(
                "object reference state is not a bounded regular file",
                code=STORE_UNSAFE_ENTRY,
            )
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if opened.st_dev != expected.st_dev or opened.st_ino != expected.st_ino:
                return _error(
                    "object reference state changed while opening",
                    code=STORE_UNSAFE_ENTRY,
                )
            content = stream.read(_MAX_REFERENCE_BYTES + 1)
        if len(content) != expected.st_size:
            return _error(
                "object reference state changed while reading",
                code=STORE_UNSAFE_ENTRY,
            )
    except OSError as error:
        return _error(f"cannot read object references: {error}")
    return parse_reference_index(content)


def write_references(command: ReferenceWriteCommand) -> Result[ReferenceIndex]:
    path = Path(command.paths.references_file)
    stage: str | None = None
    components = _managed_components(path, command.paths.root)
    if not _existing_components_are_real(components):
        return _error(
            "object reference state directory is unsafe",
            code=STORE_UNSAFE_ENTRY,
        )
    try:
        for component in components:
            component.mkdir(parents=True, exist_ok=True, mode=0o700)
            if not _real_directory(component):
                return _error(
                    "object reference state directory is unsafe",
                    code=STORE_UNSAFE_ENTRY,
                )
        descriptor, stage = tempfile.mkstemp(prefix=".object-references-", dir=path.parent)
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(reference_index_bytes(command.index))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(stage, path)
        stage = None
        os.chmod(path, 0o600)
        _fsync_directory(path.parent)
        return Ok(command.index)
    except OSError as error:
        return _error(f"cannot write object references: {error}")
    finally:
        if stage is not None:
            try:
                os.unlink(stage)
            except OSError:
                pass
