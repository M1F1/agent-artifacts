"""Global store lease adapter over the hardened filesystem lease primitive."""

from __future__ import annotations

from dataclasses import replace

from agent_artifacts.domain.diagnostics import DiagnosticCode
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.io.source_store import acquire_source_lock, release_source_lock
from agent_artifacts.sources.model import SourceLockLease, SourceLockRequest
from agent_artifacts.store.model import StoreLockLease, StoreLockRequest

_CODES = {
    "source-lock-busy": ("store-lock-busy", "store operation is already running"),
    "source-invalid": ("store-invalid", "store lease is invalid"),
    "source-unavailable": ("store-unavailable", "store lease is unavailable"),
}


def _translated(error: Err) -> Err:
    diagnostics = []
    for diagnostic in error.diagnostics:
        code, message = _CODES.get(
            diagnostic.code.value,
            (diagnostic.code.value, diagnostic.message),
        )
        diagnostics.append(replace(diagnostic, code=DiagnosticCode(code), message=message))
    return Err(tuple(diagnostics))


def acquire_store_lock(request: StoreLockRequest) -> Result[StoreLockLease]:
    acquired = acquire_source_lock(
        SourceLockRequest(
            request.lock_directory,
            request.timeout_seconds,
            request.stale_after_seconds,
        )
    )
    if isinstance(acquired, Err):
        return _translated(acquired)
    return Ok(StoreLockLease(acquired.value.lock_directory, acquired.value.token))


def release_store_lock(lease: StoreLockLease) -> Result[None]:
    released = release_source_lock(SourceLockLease(lease.lock_directory, lease.token))
    return _translated(released) if isinstance(released, Err) else released
