"""Minimal-environment subprocess boundary for optional security analyzers."""

from __future__ import annotations

import os
import posixpath
import shutil
import subprocess
import threading
import time
from typing import BinaryIO, Mapping

from agent_artifacts.security.analyzers import (
    AnalyzerProcessKind,
    AnalyzerProcessOutcome,
    AnalyzerProcessRequest,
)

_ALLOWED_ENVIRONMENT = ("LANG", "LC_CTYPE", "PATH", "SYSTEMROOT")


def resolve_executable(name: str) -> str | None:
    """Resolve an already-installed command; this function never installs anything."""

    if not isinstance(name, str) or not name or "/" in name or "\\" in name:
        return None
    resolved = shutil.which(name)
    if (
        resolved is None
        or not posixpath.isabs(resolved)
        or posixpath.normpath(resolved) != resolved
        or posixpath.basename(resolved) != name
    ):
        return None
    return resolved


def _minimal_environment(environ: Mapping[str, str]) -> dict[str, str]:
    environment = {name: environ[name] for name in _ALLOWED_ENVIRONMENT if name in environ}
    environment.setdefault("PATH", os.defpath)
    environment["LC_ALL"] = "C"
    return environment


def run_analyzer_process(
    request: AnalyzerProcessRequest,
    *,
    environ: Mapping[str, str] | None = None,
) -> AnalyzerProcessOutcome:
    """Run trusted optional code with fixed argv and resource bounds, but without claiming a sandbox."""

    environment = os.environ if environ is None else environ
    try:
        process = subprocess.Popen(
            request.argv,
            cwd=request.cwd,
            env=_minimal_environment(environment),
            shell=False,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        return AnalyzerProcessOutcome(AnalyzerProcessKind.UNAVAILABLE)
    except subprocess.TimeoutExpired:
        return AnalyzerProcessOutcome(AnalyzerProcessKind.TIMED_OUT)
    except OSError:
        return AnalyzerProcessOutcome(AnalyzerProcessKind.FAILED_TO_START)

    if process.stdin is None or process.stdout is None or process.stderr is None:
        try:
            process.kill()
        except OSError:
            pass
        return AnalyzerProcessOutcome(AnalyzerProcessKind.FAILED_TO_START)

    lock = threading.Lock()
    exceeded = threading.Event()
    io_failed = threading.Event()
    total = [0]
    stdout_buffer = bytearray()
    stderr_buffer = bytearray()

    def stop_process() -> None:
        try:
            process.kill()
        except OSError:
            pass

    def read_stream(stream: BinaryIO, target: bytearray) -> None:
        try:
            while True:
                chunk = stream.read(64 * 1024)
                if not chunk:
                    break
                should_stop = False
                with lock:
                    remaining = max(0, request.max_output_bytes - total[0])
                    target.extend(chunk[:remaining])
                    total[0] += len(chunk)
                    if total[0] > request.max_output_bytes:
                        exceeded.set()
                        should_stop = True
                if should_stop:
                    stop_process()
                    break
        except OSError:
            io_failed.set()
            stop_process()
        finally:
            stream.close()

    def write_input(stream: BinaryIO) -> None:
        try:
            stream.write(request.stdin)
            stream.flush()
        except (BrokenPipeError, OSError):
            pass
        finally:
            stream.close()

    threads = (
        threading.Thread(target=read_stream, args=(process.stdout, stdout_buffer), daemon=True),
        threading.Thread(target=read_stream, args=(process.stderr, stderr_buffer), daemon=True),
        threading.Thread(target=write_input, args=(process.stdin,), daemon=True),
    )
    for thread in threads:
        thread.start()
    timed_out = False
    try:
        process.wait(timeout=request.timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        stop_process()
        process.wait()
    join_deadline = time.monotonic() + 0.25
    for thread in threads:
        thread.join(timeout=max(0.0, join_deadline - time.monotonic()))
    if any(thread.is_alive() for thread in threads):
        io_failed.set()
        stop_process()
        for stream in (process.stdin, process.stdout, process.stderr):
            try:
                stream.close()
            except OSError:
                pass

    if timed_out:
        return AnalyzerProcessOutcome(AnalyzerProcessKind.TIMED_OUT)
    if exceeded.is_set():
        return AnalyzerProcessOutcome(AnalyzerProcessKind.OUTPUT_LIMIT)
    if io_failed.is_set() or not isinstance(process.returncode, int):
        return AnalyzerProcessOutcome(AnalyzerProcessKind.FAILED_TO_START)
    return AnalyzerProcessOutcome(
        AnalyzerProcessKind.COMPLETED,
        process.returncode,
        bytes(stdout_buffer),
        bytes(stderr_buffer),
    )


__all__ = ["resolve_executable", "run_analyzer_process"]
