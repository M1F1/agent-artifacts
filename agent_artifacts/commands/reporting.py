"""Validate and aggregate registry-owned usage-report issue data."""

from __future__ import annotations

import os
import stat
import sys
import tempfile
from pathlib import Path

from agent_artifacts.domain.result import Err
from agent_artifacts.model import Request
from agent_artifacts.reporting.aggregation import aggregate_issue_export, dashboard_files
from agent_artifacts.reporting.schema import parse_issue_body, parse_usage_report

from agent_artifacts import command_outcome as _common

_MAX_INPUT_BYTES = 10 * 1024 * 1024


def _read(path: str | None) -> bytes | None:
    if path is None:
        return None
    try:
        if path == "-":
            data = sys.stdin.buffer.read(_MAX_INPUT_BYTES + 1)
        else:
            with open(path, "rb") as stream:
                data = stream.read(_MAX_INPUT_BYTES + 1)
    except OSError:
        return None
    return None if len(data) > _MAX_INPUT_BYTES else data


def _atomic_write(path: Path, content: bytes) -> bool:
    temporary: str | None = None
    try:
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
        return True
    except OSError:
        return False
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def _dashboard(output: str | None, json_bytes: bytes, html_bytes: bytes) -> bool:
    if output is None:
        return False
    root = Path(os.path.abspath(output))
    try:
        if root.exists() and (
            root.is_symlink() or not stat.S_ISDIR(os.stat(root, follow_symlinks=False).st_mode)
        ):
            return False
        root.mkdir(parents=True, exist_ok=True, mode=0o755)
        if root.is_symlink():
            return False
        for name in ("usage.json", "index.html"):
            target = root / name
            if target.is_symlink():
                return False
    except OSError:
        return False
    return _atomic_write(root / "usage.json", json_bytes) and _atomic_write(
        root / "index.html", html_bytes
    )


def run(request: Request) -> int:
    data = _read(request.reporting_input)
    if data is None:
        print("reporting input is missing, unreadable, or too large", file=sys.stderr)
        return _common.USAGE
    action = request.reporting_action
    if action == "validate-event":
        result = parse_usage_report(data)
    elif action == "validate-issue":
        try:
            result = parse_issue_body(data.decode("utf-8"))
        except UnicodeDecodeError:
            result = None
    elif action == "aggregate":
        aggregated = aggregate_issue_export(data)
        if isinstance(aggregated, Err):
            print("usage-report export is invalid", file=sys.stderr)
            return _common.ERROR
        files = dashboard_files(aggregated.value)
        if not _dashboard(request.reporting_output, files.json, files.html):
            print("reporting dashboard output is unavailable", file=sys.stderr)
            return _common.ERROR
        print(
            f"usage reports aggregated: accepted={aggregated.value.accepted}, "
            f"rejected={aggregated.value.rejected}"
        )
        return _common.OK
    else:
        return _common.USAGE
    if result is None or isinstance(result, Err):
        print("usage report is invalid", file=sys.stderr)
        return _common.ERROR
    print("usage report is valid")
    return _common.OK


__all__ = ["run"]
