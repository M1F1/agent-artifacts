"""The imperative edge of `RR-3`: the questions, actually asked.

Kept apart from `setup_verify` so the decision of *what to ask* stays testable without a docker
daemon or a Keychain, and so this file can be read on its own for what it touches.

The Keychain probe is the one that needs stating plainly.  `security find-generic-password -w`
prints the stored password, and that is the only way macOS will answer "does this item hold a
non-empty value".  The value is measured for length and discarded: it is never returned to the
caller, never rendered, never persisted, and never logged.  The probe answers a yes/no question
and nothing else.
"""

from __future__ import annotations

import contextlib
import io
import os
import shlex
import subprocess
from typing import Tuple

from agent_artifacts.setup_verify import VerificationProbes

_SECURITY = "/usr/bin/security"
_TIMEOUT = 30


def _probe_env() -> dict[str, str]:
    """The environment `setup_runtime._minimal_env` gives a run, so verify asks the same machine.

    Measured on 2026-08-15: hardcoding the fallback `PATH` instead of inheriting it made every
    docker claim report `unknown` on a host whose daemon was running and whose setup had just
    succeeded — `docker` lives in `/usr/local/bin` there. A probe stricter than the runtime
    reports "I could not ask" about a tool the run used, which is a false answer with a
    reassuring shape.
    """

    allowed = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "HOME")
    env = {name: os.environ[name] for name in allowed if name in os.environ}
    env.setdefault("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
    return env


def _run(argv: tuple[str, ...]) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(  # noqa: S603 - fixed argv, no shell, no caller-supplied binary
            argv,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
            check=False,
            env=_probe_env(),
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _image_present(image: str) -> bool | None:
    completed = _run(("docker", "image", "inspect", image))
    if completed is None:
        return None
    if completed.returncode == 0:
        return True
    # Distinguish "docker answered: no such image" from "docker is not there to answer".
    noise = (completed.stderr or "").lower()
    if "cannot connect" in noise or "daemon" in noise or "not found: docker" in noise:
        return None
    return False


def _image_id(tag: str) -> str | None:
    completed = _run(("docker", "image", "inspect", "--format", "{{.Id}}", tag))
    if completed is None:
        return None
    if completed.returncode != 0:
        noise = (completed.stderr or "").lower()
        if "cannot connect" in noise or "daemon" in noise:
            return None
        return ""
    return completed.stdout.strip()


def _keychain_value_present(service: str, account: str) -> bool | None:
    if not os.path.exists(_SECURITY):
        return None
    completed = _run((_SECURITY, "find-generic-password", "-s", service, "-a", account, "-w"))
    if completed is None:
        return None
    if completed.returncode != 0:
        return False
    # Length only. The value itself goes no further than this expression.
    return bool(completed.stdout.strip())


def _read_text(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as stream:
            return stream.read()
    except OSError:
        return None


def _path_present(path: str) -> bool | None:
    try:
        return os.path.exists(path)
    except OSError:
        return None


def command_accepted(command: str) -> bool | None:
    """Does this executable's own CLI accept the command a record recorded? (`LAF-73`)

    The parser is the shipped surface, so this cannot answer `True` for a command the executable
    does not define — which is the whole point: a record written before `2.6.0` instructs the
    operator to undo a setup by hand, and only the parser knows that instruction is now wrong.

    ``parse_args`` writes to stderr and raises `SystemExit` rather than returning a verdict, so
    both streams are captured and the exit is read as the answer. Nothing is executed.
    """

    try:
        from agent_artifacts import cli  # imported here: `cli` reaches this module in a cycle
    except ImportError:  # pragma: no cover - the CLI is part of the package
        return None

    try:
        arguments = shlex.split(command)
    except ValueError:
        return False
    if arguments[:1] != ["aart"]:
        return False

    with (
        contextlib.redirect_stdout(io.StringIO()),
        contextlib.redirect_stderr(io.StringIO()),
    ):
        try:
            cli.build_parser().parse_args(arguments[1:])
        except SystemExit as exited:
            return exited.code == 0
    return True


def orphan_run_directories(run_root: str, plan_hash: str) -> Tuple[str, ...] | None:
    """Working copies an interrupted run left behind under the run root (`LAF-61`).

    The root is the one the run itself used, handed in rather than derived here.  This probe used
    to compose `<project_root>/.agent-artifacts/setup-runs`, while `new_run_directory` composes
    `<plan.run_root>/...` and `setup_engine/application.py` passes `run_root=location.data_root`.
    The two are never the same directory, so the claim answered `true` in every scope without ever
    looking at the place runs are created (`LAF-66`).

    Deriving the path in two places is what allowed them to disagree, so there is now one source
    for it and the caller supplies it.
    """

    if not run_root:
        return None
    runs_root = os.path.join(run_root, ".agent-artifacts", "setup-runs")
    prefix = f"{plan_hash[:16]}-"
    try:
        entries = sorted(os.listdir(runs_root))
    except FileNotFoundError:
        return ()
    except OSError:
        return None
    return tuple(
        os.path.join(runs_root, entry)
        for entry in entries
        if entry.startswith(prefix) and os.path.isdir(os.path.join(runs_root, entry))
    )


def local_probes(*, project_root: str, run_root: str) -> VerificationProbes:
    """The probe set a real machine answers.

    `project_root` resolves the paths a recipe wrote into the project.  `run_root` is where the
    engine creates run directories, which is the data root and not the project.  They are separate
    arguments because collapsing them is exactly the mistake `LAF-66` was.
    """

    return VerificationProbes(
        image_present=_image_present,
        image_id=_image_id,
        keychain_value_present=_keychain_value_present,
        read_text=_read_text,
        path_present=_path_present,
        orphan_run_directories=lambda plan_hash: orphan_run_directories(run_root, plan_hash),
        command_accepted=command_accepted,
    )


__all__ = ["command_accepted", "local_probes", "orphan_run_directories"]
