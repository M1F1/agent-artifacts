"""Sanitized fixed-argv system Git process adapter."""

from __future__ import annotations

import os
import posixpath
import subprocess
from dataclasses import dataclass
from typing import Mapping

from agent_artifacts.configuration.policy import redact_text
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.result import Err, Ok, Result

SOURCE_AUTH_FAILED = DiagnosticCode("source-auth-failed")
SOURCE_UNAVAILABLE = DiagnosticCode("source-unavailable")
_ALLOWED_ENVIRONMENT = (
    "HOME",
    "PATH",
    "SSH_AUTH_SOCK",
    "XDG_CONFIG_HOME",
    "SYSTEMROOT",
)
_AUTH_MARKERS = (
    "authentication failed",
    "permission denied",
    "could not read username",
    "repository not found",
    "access denied",
)


@dataclass(frozen=True, slots=True)
class GitProcessRequest:
    argv: tuple[str, ...]
    cwd: str
    timeout_seconds: float
    max_output_bytes: int = 1024 * 1024

    def __post_init__(self) -> None:
        if (
            not isinstance(self.argv, tuple)
            or not self.argv
            or self.argv[0] != "git"
            or any(
                not isinstance(item, str)
                or not item
                or "\x00" in item
                or "\n" in item
                or "\r" in item
                for item in self.argv
            )
            or not posixpath.isabs(self.cwd)
            or posixpath.normpath(self.cwd) != self.cwd
            or not isinstance(self.timeout_seconds, (int, float))
            or isinstance(self.timeout_seconds, bool)
            or self.timeout_seconds <= 0
            or not isinstance(self.max_output_bytes, int)
            or isinstance(self.max_output_bytes, bool)
            or self.max_output_bytes <= 0
        ):
            raise ValueError("Git process request requires safe fixed argv and positive bounds")
        if len(self.argv) >= 2 and self.argv[1] in {"sh", "shell"}:
            raise ValueError("Git process request cannot invoke a shell")


@dataclass(frozen=True, slots=True)
class GitProcessReceipt:
    stdout: bytes
    stderr: bytes


def _diagnostic(
    code: DiagnosticCode,
    message: str,
    *,
    remediation: tuple[str, ...] = (),
) -> Err:
    return Err(
        (
            Diagnostic(
                code,
                Severity.ERROR,
                redact_text(message),
                remediation=remediation,
            ),
        )
    )


def _safe_environment(environ: Mapping[str, str]) -> dict[str, str]:
    result = {name: environ[name] for name in _ALLOWED_ENVIRONMENT if name in environ}
    result.update(
        {
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
        }
    )
    return result


def _bounded(value: bytes | str | None, limit: int) -> bytes:
    if value is None:
        return b""
    encoded = value.encode("utf-8", errors="replace") if isinstance(value, str) else value
    return encoded[:limit]


def _message(request: GitProcessRequest, output: bytes, label: str) -> str:
    command = " ".join(request.argv)
    detail = output.decode("utf-8", errors="replace").strip()
    suffix = "" if not detail else f": {detail}"
    return f"{label} for Git command {command}{suffix}"


def run_git_process(
    request: GitProcessRequest,
    *,
    environ: Mapping[str, str] | None = None,
) -> Result[GitProcessReceipt]:
    """Run system Git without a shell, hooks, ambient secrets, or unbounded diagnostics."""

    environment = os.environ if environ is None else environ
    try:
        completed = subprocess.run(
            request.argv,
            cwd=request.cwd,
            env=_safe_environment(environment),
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=request.timeout_seconds,
            check=False,
        )
    except FileNotFoundError:
        return _diagnostic(
            SOURCE_UNAVAILABLE,
            "system Git executable is unavailable",
            remediation=("install Git",),
        )
    except subprocess.TimeoutExpired as error:
        output = _bounded(error.stderr or error.output, request.max_output_bytes)
        return _diagnostic(
            SOURCE_UNAVAILABLE,
            _message(request, output, "timed out"),
            remediation=("retry source synchronization",),
        )
    except OSError as error:
        return _diagnostic(
            SOURCE_UNAVAILABLE,
            f"failed to start system Git: {error}",
            remediation=("check Git and filesystem access",),
        )
    stdout = _bounded(completed.stdout, request.max_output_bytes)
    stderr = _bounded(completed.stderr, request.max_output_bytes)
    if completed.returncode != 0:
        combined = (stdout + b"\n" + stderr).decode("utf-8", errors="replace").casefold()
        code = (
            SOURCE_AUTH_FAILED
            if any(marker in combined for marker in _AUTH_MARKERS)
            else SOURCE_UNAVAILABLE
        )
        remediation = (
            ("check Git credentials and repository access",)
            if code == SOURCE_AUTH_FAILED
            else ("retry source synchronization",)
        )
        return _diagnostic(
            code,
            _message(request, stderr or stdout, "Git command failed"),
            remediation=remediation,
        )
    return Ok(GitProcessReceipt(stdout, stderr))
