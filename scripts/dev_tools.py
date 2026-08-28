#!/usr/bin/env python3
"""Install the developer tooling Poetry resolved, using pip.

Poetry owns what the tools *are*: the constraints live in `pyproject.toml` as semantic-version
ranges, and `poetry.lock` records the exact versions those ranges resolved to. This script only
reads that decision and carries it out.

**Why pip does the installing.** `poetry install` cannot reach a per-fork internal index. Poetry
takes an install source only from a `[[tool.poetry.source]]` block inside `pyproject.toml`; there
is no environment variable for it (`POETRY_PYPI_MIRROR_URL` is not honoured in Poetry 2.x, tested).
Adding the block at run time changes the file's content hash, and both `poetry check --lock` and
`poetry install` then refuse with "pyproject.toml changed significantly since poetry.lock was last
generated". Committing the block is worse: the URL differs per fork, so it would be the hand-edit
this project exists to avoid. pip, meanwhile, already reads `PIP_INDEX_URL`, which
`.github/actions/pip-index` sets from the fork's own variables.

So Poetry decides and pip installs, and the lock is what passes between them.

The lock is parsed here rather than with `tomllib`, because the gates run on Python 3.10 too and
`tomllib` arrived in 3.11. `tests/dev_tools_test.py` checks this parser against `tomllib` on the
interpreters that have it, so the shortcut cannot quietly drift from the format.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "poetry.lock"

_PACKAGE_HEADER = "[[package]]"
_SCALAR_RE = re.compile(r'^(name|version|markers)\s*=\s*"(.*)"\s*$')
_GROUPS_RE = re.compile(r"^groups\s*=\s*\[(.*)\]\s*$")
_QUOTED_RE = re.compile(r'"([^"]*)"')


class LockError(RuntimeError):
    pass


def _unescape(value: str) -> str:
    """Undo TOML's basic-string escapes, which markers carry: `!= \\"PyPy\\"`."""

    return value.replace('\\"', '"').replace("\\\\", "\\")


def _blocks(text: str) -> list[list[str]]:
    """Split the lock into its `[[package]]` blocks, keeping only each block's top level.

    A block ends at the next top-level table, so nested tables such as
    `[package.dependencies]` -- which carry names and versions of their own -- never reach the
    field parser.
    """

    blocks: list[list[str]] = []
    current: list[str] | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == _PACKAGE_HEADER:
            current = []
            blocks.append(current)
            continue
        if stripped.startswith("["):
            current = None
            continue
        if current is not None:
            current.append(stripped)
    return blocks


def packages(text: str) -> tuple[dict[str, str], ...]:
    """Every locked package, as `{name, version, markers, groups}` with plain string values."""

    parsed: list[dict[str, str]] = []
    for block in _blocks(text):
        record: dict[str, str] = {"markers": "", "groups": ""}
        for line in block:
            scalar = _SCALAR_RE.match(line)
            if scalar:
                record[scalar.group(1)] = _unescape(scalar.group(2))
                continue
            groups = _GROUPS_RE.match(line)
            if groups:
                record["groups"] = ",".join(_QUOTED_RE.findall(groups.group(1)))
        if "name" not in record or "version" not in record:
            raise LockError(f"a [[package]] block in {LOCK.name} has no name or no version")
        parsed.append(record)
    if not parsed:
        raise LockError(f"{LOCK.name} lists no packages; run `poetry lock`")
    return tuple(parsed)


def requirements(group: str = "dev") -> tuple[str, ...]:
    """The group's packages as exact pip requirements, markers included.

    The marker is carried through rather than resolved here: `tomli` is locked only for Python
    3.10, and pip is the thing that knows which interpreter it is installing into.
    """

    text = LOCK.read_text(encoding="utf-8")
    wanted = []
    for record in packages(text):
        if group not in record["groups"].split(","):
            continue
        pin = f"{record['name']}=={record['version']}"
        if record["markers"]:
            pin = f"{pin} ; {record['markers']}"
        wanted.append(pin)
    if not wanted:
        raise LockError(f"{LOCK.name} has no packages in group {group!r}")
    return tuple(sorted(wanted))


def install(python: str, group: str = "dev", editable: bool = True) -> int:
    command = [
        python,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        *requirements(group),
    ]
    if editable:
        # The gates import the package under test, so it goes in editable beside the tools.
        command += ["-e", str(ROOT)]
    print(" ".join(command[:5]) + f" ... ({len(requirements(group))} pinned tools)", flush=True)
    return subprocess.run(command, cwd=ROOT).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=("install", "pins"))
    parser.add_argument("--group", default="dev")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument(
        "--no-editable",
        action="store_true",
        help="install only the tools, leaving the package alone",
    )
    arguments = parser.parse_args(argv)

    try:
        if arguments.action == "pins":
            for pin in requirements(arguments.group):
                print(pin)
            return 0
        return install(arguments.python, arguments.group, editable=not arguments.no_editable)
    except LockError as error:
        print(f"{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
