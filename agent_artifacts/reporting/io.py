"""Tokenless browser and authenticated GitHub CLI reporting adapters."""

from __future__ import annotations

import subprocess
import webbrowser
from dataclasses import dataclass
from typing import Callable, Protocol, Sequence

from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.result import Err, Ok, Result

from .application import ReportingProvider
from .model import ReportingPlan, ReportingSubmission

REPORTING_PROVIDER_FAILED = DiagnosticCode("reporting-provider-failed")


class ProcessRun(Protocol):
    def __call__(
        self,
        argv: Sequence[str],
        *,
        input: bytes,
        timeout: int,
        shell: bool,
        check: bool,
        capture_output: bool,
    ) -> subprocess.CompletedProcess[bytes]: ...


def _error(message: str) -> Err:
    return Err((Diagnostic(REPORTING_PROVIDER_FAILED, Severity.ERROR, message),))


def browser_provider(
    opener: Callable[[str], bool] = webbrowser.open,
) -> ReportingProvider:
    def submit(plan: ReportingPlan) -> Result[ReportingSubmission]:
        if plan.browser_url is None:
            return _error("the reporting plan has no browser URL")
        try:
            opened = opener(plan.browser_url)
        except (OSError, RuntimeError, webbrowser.Error):
            return _error("could not open the reporting issue in a browser")
        if not opened:
            return _error("the browser did not accept the reporting issue URL")
        return Ok(ReportingSubmission("browser-opened"))

    return submit


def _run_process(
    argv: Sequence[str],
    *,
    input: bytes,
    timeout: int,
    shell: bool,
    check: bool,
    capture_output: bool,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        argv,
        input=input,
        timeout=timeout,
        shell=shell,
        check=check,
        capture_output=capture_output,
    )


@dataclass(frozen=True, slots=True)
class GitHubIssueProvider:
    run: ProcessRun = _run_process
    timeout_seconds: int = 30

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0 or self.timeout_seconds > 120:
            raise ValueError("reporting provider timeout is invalid")

    def _execute(self, argv: tuple[str, ...], payload: bytes) -> bool:
        try:
            completed = self.run(
                argv,
                input=payload,
                timeout=self.timeout_seconds,
                shell=False,
                check=False,
                capture_output=True,
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            return False
        return completed.returncode == 0

    def __call__(self, plan: ReportingPlan) -> Result[ReportingSubmission]:
        host = plan.destination.host
        if not self._execute(("gh", "auth", "status", "--hostname", host), b""):
            return _error("GitHub CLI authentication is unavailable for the reporting host")
        target = f"{host}/{plan.destination.repository}"
        created = self._execute(
            (
                "gh",
                "issue",
                "create",
                "--repo",
                target,
                "--title",
                plan.title,
                "--body-file",
                "-",
            ),
            plan.body.encode("utf-8"),
        )
        if not created:
            return _error("GitHub CLI could not create the usage-report issue")
        return Ok(ReportingSubmission("submitted"))


__all__ = ["GitHubIssueProvider", "REPORTING_PROVIDER_FAILED", "browser_provider"]
