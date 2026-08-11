"""Discover and apply the ref-aware source-store migration.

Planning lives in :mod:`agent_artifacts.sources.migration` and is pure.  This module supplies the
two IO halves: reading what is actually on disk, and applying an already-reviewed plan.

Applying is deliberately made of individually durable steps.  Each rebind is one ``os.rename``,
which is atomic within a filesystem, and the layout-version file is written only after every rebind
has succeeded.  A process killed midway therefore leaves a directory that is either fully at its old
name or fully at its new one, with the version file still absent — so a re-run replans from reality
and finishes the job.  Nothing is ever renamed onto an existing path, so no pointer is destroyed.
"""

from __future__ import annotations

import json
import os
import posixpath
from pathlib import Path

from agent_artifacts.domain.diagnostics import DiagnosticCode
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.sources.migration import (
    SOURCE_STORE_SCHEMA_VERSION,
    SOURCE_STORE_VERSION_FILE,
    SourceStoreMigrationPlan,
)

from .source_store import SOURCE_UNAVAILABLE, _atomic_private_write, _error

SOURCE_STORE_INVALID = DiagnosticCode("source-store-invalid")


def _sources_root(data_root: str) -> Path:
    if not posixpath.isabs(data_root) or posixpath.normpath(data_root) != data_root:
        raise ValueError("source data root must be normalized and absolute")
    return Path(data_root) / "sources"


def existing_source_directories(data_root: str) -> tuple[str, ...]:
    """Return the directory names currently present in the source store, sorted."""

    root = _sources_root(data_root)
    try:
        return tuple(sorted(entry.name for entry in os.scandir(root) if entry.is_dir()))
    except FileNotFoundError:
        return ()
    except OSError:
        return ()


def stored_schema_version(data_root: str) -> int | None:
    """Return the recorded store layout version, or ``None`` for an unmarked (v1) layout."""

    path = _sources_root(data_root) / SOURCE_STORE_VERSION_FILE
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError:
        return None
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    version = value.get("schema_version") if isinstance(value, dict) else None
    return version if isinstance(version, int) and not isinstance(version, bool) else None


def apply_source_store_migration(
    plan: SourceStoreMigrationPlan,
    *,
    data_root: str,
) -> Result[tuple[str, ...]]:
    """Apply a reviewed migration plan and record the new layout version.

    Returns the aliases whose stored directory was rebound.
    """

    root = _sources_root(data_root)
    rebound: list[str] = []
    for rebind in plan.rebinds:
        source = root / rebind.source_directory
        target = root / rebind.target_directory
        if not source.is_dir():
            # Already applied by an interrupted earlier run; replanning would agree.
            continue
        if target.exists():
            return _error(
                SOURCE_STORE_INVALID,
                f"refusing to rebind {rebind.source_directory}: {rebind.target_directory} exists",
                "inspect both directories and remove the one that is no longer current",
            )
        try:
            os.rename(source, target)
        except OSError as error:
            return _error(
                SOURCE_UNAVAILABLE,
                f"cannot rebind managed source directory: {error}",
            )
        rebound.append(rebind.alias.value)
    try:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError as error:
        return _error(SOURCE_UNAVAILABLE, f"cannot create managed source root: {error}")
    written = _atomic_private_write(
        root / SOURCE_STORE_VERSION_FILE,
        json.dumps({"schema_version": SOURCE_STORE_SCHEMA_VERSION}).encode("utf-8"),
    )
    if isinstance(written, Err):
        return written
    return Ok(tuple(rebound))


__all__ = [
    "SOURCE_STORE_INVALID",
    "apply_source_store_migration",
    "existing_source_directories",
    "stored_schema_version",
]
