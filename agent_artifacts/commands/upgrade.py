"""Explicit local AART executable replacement; index publication remains out of scope."""

from __future__ import annotations

import os
import re
import shlex
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.model import Request

from agent_artifacts.command_outcome import ERROR, OK

UPGRADE_INVALID = DiagnosticCode("upgrade-invalid")
_WHEEL_NAME_RE = re.compile(
    r"^agent_artifacts-[0-9]+\.[0-9]+\.[0-9]+(?:(?:a|b|rc)[0-9]+)?-py3-none-any\.whl$"
)


@dataclass(frozen=True, slots=True)
class UpgradePlan:
    source_kind: Literal["wheel", "editable"]
    source_path: str
    argv: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            self.source_kind not in {"wheel", "editable"}
            or not os.path.isabs(self.source_path)
            or os.path.normpath(self.source_path) != self.source_path
            or len(self.argv) < 8
            or self.argv[0] != os.path.abspath(sys.executable)
            or self.argv[1:4] != ("-m", "pip", "install")
            or "--no-index" not in self.argv
            or "--no-deps" not in self.argv
            or any(option in self.argv for option in ("--index-url", "--extra-index-url"))
            or self.argv[-1] != self.source_path
        ):
            raise ValueError("upgrade plan is not an explicit index-free local install")


UpgradeRunner = Callable[[tuple[str, ...]], int]


def _error(message: str, *remediation: str) -> Err:
    return Err(
        (
            Diagnostic(
                UPGRADE_INVALID,
                Severity.ERROR,
                message,
                remediation=remediation,
            ),
        )
    )


def _real_regular_file(path: str) -> bool:
    try:
        return stat.S_ISREG(os.lstat(path).st_mode)
    except OSError:
        return False


def _real_directory(path: str) -> bool:
    try:
        return stat.S_ISDIR(os.lstat(path).st_mode)
    except OSError:
        return False


def plan_upgrade(
    executable: str,
    *,
    wheel: str | None,
    source_checkout: str | None,
) -> Result[UpgradePlan]:
    """Validate one explicit local candidate and return fixed, index-free pip argv."""

    if (wheel is None) == (source_checkout is None):
        return _error(
            "choose exactly one local AART upgrade source",
            "pass --wheel FILE or --source-checkout DIR",
        )
    python = os.path.abspath(executable)
    if executable != sys.executable or not os.path.isfile(python):
        return _error("current Python executable is not a regular file")
    argv: tuple[str, ...]
    if wheel is not None:
        path = os.path.abspath(wheel)
        if not _real_regular_file(path) or _WHEEL_NAME_RE.fullmatch(Path(path).name) is None:
            return _error(
                "local wheel must be a real agent_artifacts-<version>-py3-none-any.whl file",
                "build one with make wheel, then pass its exact path",
            )
        argv = (
            python,
            "-m",
            "pip",
            "install",
            "--no-index",
            "--no-deps",
            "--force-reinstall",
            path,
        )
        try:
            return Ok(UpgradePlan("wheel", path, argv))
        except ValueError as error:
            return _error(str(error))
    assert source_checkout is not None
    path = os.path.abspath(source_checkout)
    if (
        not _real_directory(path)
        or not _real_directory(os.path.join(path, "agent_artifacts"))
        or not _real_regular_file(os.path.join(path, "pyproject.toml"))
    ):
        return _error(
            "editable upgrade source must be a real AART checkout",
            "pass a directory containing pyproject.toml and agent_artifacts/",
        )
    argv = (
        python,
        "-m",
        "pip",
        "install",
        "--no-index",
        "--no-deps",
        "--no-build-isolation",
        "--force-reinstall",
        "--editable",
        path,
    )
    try:
        return Ok(UpgradePlan("editable", path, argv))
    except ValueError as error:
        return _error(str(error))


def _default_runner(argv: tuple[str, ...]) -> int:
    return subprocess.run(argv, check=False).returncode


def run(request: Request, *, runner: UpgradeRunner | None = None) -> int:
    """Review or apply an explicit local replacement; never discover or contact an index."""

    planned = plan_upgrade(
        sys.executable,
        wheel=request.upgrade_wheel,
        source_checkout=request.upgrade_source_checkout,
    )
    if isinstance(planned, Err):
        for diagnostic in planned.diagnostics:
            print(f"error: {diagnostic.message}")
            for remediation in diagnostic.remediation:
                print(f"  remediation: {remediation}")
        return ERROR
    print(shlex.join(planned.value.argv))
    if request.dry_run:
        return OK
    execute = _default_runner if runner is None else runner
    return OK if execute(planned.value.argv) == 0 else ERROR


__all__ = ["UpgradePlan", "plan_upgrade", "run"]
