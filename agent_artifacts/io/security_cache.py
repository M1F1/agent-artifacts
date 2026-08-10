"""Symlink-safe atomic filesystem boundary for canonical security attestations."""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

from agent_artifacts.configuration.policy import redact_text
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.security.attestation_schema import attestation_bytes, parse_attestation
from agent_artifacts.security.attestations import (
    AssessmentCacheKey,
    SecurityAttestation,
    attestation_digest,
    cache_key_digest,
)
from agent_artifacts.security.cache import (
    CacheWriteReceipt,
    SecurityCachePaths,
    cached_attestation_path,
)

SECURITY_CACHE_INVALID = DiagnosticCode("security-cache-invalid")
SECURITY_CACHE_UNAVAILABLE = DiagnosticCode("security-cache-unavailable")
_MAX_ATTESTATION_BYTES = 2 * 1024 * 1024 + 16 * 1024


def _error(code: DiagnosticCode, message: str) -> Err:
    return Err((Diagnostic(code, Severity.ERROR, redact_text(message)),))


def _real_directory(path: Path) -> bool:
    try:
        return stat.S_ISDIR(os.stat(path, follow_symlinks=False).st_mode)
    except OSError:
        return False


def _managed_components(paths: SecurityCachePaths, prefix: Path | None = None) -> tuple[Path, ...]:
    root = Path(paths.root)
    components = (root, root / "attestations", Path(paths.attestations))
    return components if prefix is None else (*components, prefix)


def _existing_components_are_real(components: tuple[Path, ...]) -> bool:
    return all(not os.path.lexists(path) or _real_directory(path) for path in components)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _target(paths: SecurityCachePaths, key: AssessmentCacheKey) -> Path:
    return Path(cached_attestation_path(paths, key))


def read_cached_attestation(
    paths: SecurityCachePaths,
    key: AssessmentCacheKey,
) -> Result[SecurityAttestation | None]:
    target = _target(paths, key)
    prefix = target.parent
    if not _existing_components_are_real(_managed_components(paths, prefix)):
        return _error(SECURITY_CACHE_INVALID, "security cache path is not a real directory")
    if not os.path.lexists(target):
        return Ok(None)
    try:
        before = os.stat(target, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or before.st_size > _MAX_ATTESTATION_BYTES:
            return _error(SECURITY_CACHE_INVALID, "cached attestation is not a bounded real file")
        descriptor = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_dev != before.st_dev
                or opened.st_ino != before.st_ino
                or opened.st_size != before.st_size
            ):
                return _error(SECURITY_CACHE_INVALID, "cached attestation changed while opening")
            data = stream.read(_MAX_ATTESTATION_BYTES + 1)
    except OSError as error:
        return _error(SECURITY_CACHE_UNAVAILABLE, f"cannot read security cache: {error}")
    if len(data) != before.st_size:
        return _error(SECURITY_CACHE_INVALID, "cached attestation changed while reading")
    parsed = parse_attestation(data)
    if isinstance(parsed, Err) or parsed.value.cache_key != key:
        return _error(SECURITY_CACHE_INVALID, "cached attestation is corrupt or misaddressed")
    return parsed


def _prepare(paths: SecurityCachePaths, prefix: Path) -> Result[None]:
    components = _managed_components(paths, prefix)
    if not _existing_components_are_real(components):
        return _error(SECURITY_CACHE_INVALID, "security cache path is not a real directory")
    try:
        for component in components:
            component.mkdir(parents=True, exist_ok=True, mode=0o700)
            if not _real_directory(component):
                return _error(
                    SECURITY_CACHE_INVALID,
                    "security cache path is not a real directory",
                )
            os.chmod(component, 0o700, follow_symlinks=False)
        return Ok(None)
    except OSError as error:
        return _error(SECURITY_CACHE_UNAVAILABLE, f"cannot prepare security cache: {error}")


def _receipt(
    paths: SecurityCachePaths,
    attestation: SecurityAttestation,
    *,
    created: bool,
) -> CacheWriteReceipt:
    return CacheWriteReceipt(
        cached_attestation_path(paths, attestation.cache_key),
        cache_key_digest(attestation.cache_key),
        attestation_digest(attestation),
        created,
    )


def write_cached_attestation(
    paths: SecurityCachePaths,
    attestation: SecurityAttestation,
) -> Result[CacheWriteReceipt]:
    target = _target(paths, attestation.cache_key)
    prefix = target.parent
    prepared = _prepare(paths, prefix)
    if isinstance(prepared, Err):
        return prepared
    existing = read_cached_attestation(paths, attestation.cache_key)
    if isinstance(existing, Err):
        return existing
    if existing.value is not None:
        if existing.value != attestation:
            return _error(
                SECURITY_CACHE_INVALID,
                "cache identity already contains different attestation evidence",
            )
        return Ok(_receipt(paths, attestation, created=False))
    stage: Path | None = None
    try:
        descriptor, raw_stage = tempfile.mkstemp(prefix=".stage-", dir=prefix)
        stage = Path(raw_stage)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(attestation_bytes(attestation))
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(stage, target, follow_symlinks=False)
        except FileExistsError:
            raced = read_cached_attestation(paths, attestation.cache_key)
            if isinstance(raced, Ok) and raced.value == attestation:
                return Ok(_receipt(paths, attestation, created=False))
            if isinstance(raced, Err):
                return raced
            return _error(
                SECURITY_CACHE_INVALID,
                "concurrent cache write published different evidence",
            )
        _fsync_directory(prefix)
        return Ok(_receipt(paths, attestation, created=True))
    except OSError as error:
        return _error(SECURITY_CACHE_UNAVAILABLE, f"cannot publish security cache: {error}")
    finally:
        if stage is not None:
            try:
                stage.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass


__all__ = [
    "SECURITY_CACHE_INVALID",
    "SECURITY_CACHE_UNAVAILABLE",
    "read_cached_attestation",
    "write_cached_attestation",
]
