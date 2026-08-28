#!/usr/bin/env python3
"""Build the pure-Python wheel with Poetry, under a sanitized environment.

Poetry is the builder; this script is the one place that invokes it correctly. It exists because
`poetry build -f wheel` on its own does not hold the promises this project publishes, and there
are eight callers who would each have to hold them instead:

  * **`SOURCE_DATE_EPOCH` moves the digest.** poetry-core consults it. A wheel whose digest depends
    on an environment variable cannot be verified against a published digest by anyone who did not
    happen to have the same variable set, so the variable is removed before the build rather than
    documented as a caveat.
  * **The builder's version is stamped into the archive.** `WHEEL` carries
    `Generator: poetry-core <version>`, so upgrading Poetry changes the digest of an unchanged
    commit. The version is pinned in `[build-system]` and checked here, so that upgrade fails a
    build instead of silently invalidating a published digest.
  * **Poetry ships whatever is in the package directory.** The allowlist below is a gate: a stray
    file dropped under `agent_artifacts/` fails the build rather than shipping inside it.

The archive is byte-reproducible (SI-8, design §7.1): see docs/release/wheel-reproducibility-v1.md
for what that now means and how to verify a published wheel.

Requires Python 3.11+ to build (stdlib ``tomllib``); the built wheel itself runs on Python 3.10+.
The result installs with no index at all:

    pip install --no-index dist/aart_cli-<v>-py3-none-any.whl
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_RESOURCE_ROOTS = frozenset({"schemas", "profiles", "importers", "templates"})
_PINNED_BACKEND_RE = re.compile(r"poetry-core==([0-9][^\"']*)")
_GENERATOR_RE = re.compile(r"^Generator:\s*poetry-core\s+(\S+)\s*$", re.MULTILINE)
# Removed rather than trusted.  poetry-core honours this, and a digest an environment can move is
# a digest no one can check.
_STEERING_VARIABLES = ("SOURCE_DATE_EPOCH",)


def load_project() -> dict:
    return _load_pyproject()["project"]


def _load_pyproject() -> dict:
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - build host is 3.11+
        sys.exit("build_wheel.py needs Python 3.11+ (stdlib tomllib).")
    with open(ROOT / "pyproject.toml", "rb") as f:
        return tomllib.load(f)


def normalize(name: str) -> str:
    return name.replace("-", "_")


def pinned_backend() -> str:
    """The exact poetry-core version `[build-system]` pins, which is the digest's other input."""

    requires = _load_pyproject().get("build-system", {}).get("requires", [])
    for entry in requires:
        match = _PINNED_BACKEND_RE.search(entry)
        if match:
            return match.group(1)
    raise ValueError(
        "pyproject.toml [build-system] must pin poetry-core exactly, as poetry-core==<version>.\n"
        "A range there lets two machines build one commit into two different digests."
    )


def _allowed_package_member(arcname: str) -> bool:
    parts = tuple(Path(arcname).parts)
    if len(parts) < 2 or parts[0] != "agent_artifacts":
        return False
    if arcname.endswith(".py"):
        return True
    return len(parts) >= 3 and parts[1] in _RESOURCE_ROOTS


def collect_package_files() -> dict[str, bytes]:
    """Every file the wheel is allowed to carry, keyed by archive name.

    Raises on anything outside the allowlist. This runs *before* Poetry, so an unexpected file
    stops the build, and again against the built archive, so an unexpected file Poetry added on
    its own stops it too.
    """

    files: dict[str, bytes] = {}
    for path in sorted((ROOT / "agent_artifacts").rglob("*")):
        arc = str(path.relative_to(ROOT)).replace(os.sep, "/")
        if path.is_symlink():
            raise ValueError(f"wheel resource allowlist rejects: {arc}")
        if path.is_dir() or path.suffix == ".pyc" or "__pycache__" in path.parts:
            continue
        if not path.is_file() or not _allowed_package_member(arc):
            raise ValueError(f"wheel resource allowlist rejects: {arc}")
        files[arc] = path.read_bytes()
    return files


def missing_poetry(name: str) -> str:
    return (
        f"Poetry is not installed, or is not on PATH as {name!r}.\n"
        "It builds the wheel, so a build without it cannot happen.\n"
        "Install it (https://python-poetry.org/docs/#installation), or name it:\n"
        "  AART_POETRY=/opt/poetry/bin/poetry python scripts/build_wheel.py\n"
        "In CI, set the AART_POETRY repository variable -- see docs/ci/enterprise-fork-v1.md."
    )


def _poetry_module_runs() -> bool:
    """Whether `python -m poetry` would start the Poetry CLI.

    Asked rather than assumed, because `import poetry` succeeds without it. `poetry-core` -- the
    build backend, which the dev group installs and which is therefore present wherever the gates
    run -- occupies the same `poetry` namespace and ships no `__main__`. Running the module
    blindly would fail with "'poetry' is a package and cannot be directly executed", which names
    nothing a reader can act on, in place of the message below, which names the variable that
    fixes it. A real Enterprise image is exactly this shape: the tools installed, the CLI absent.
    """

    try:
        return importlib.util.find_spec("poetry.__main__") is not None
    except (ImportError, ValueError):
        return False


def poetry_command() -> list[str]:
    """How to invoke Poetry here.

    `AART_POETRY` names it outright, for an image that installs Poetry somewhere off `PATH` --
    a company CI image commonly does, as `/opt/poetry/bin/poetry`.
    """

    override = os.environ.get("AART_POETRY", "").strip()
    if override:
        return [override]
    found = shutil.which("poetry")
    if found:
        return [found]
    if _poetry_module_runs():
        return [sys.executable, "-m", "poetry"]
    raise SystemExit(missing_poetry("poetry"))


def build_environment() -> dict[str, str]:
    env = dict(os.environ)
    for name in _STEERING_VARIABLES:
        env.pop(name, None)
    # Building a wheel installs nothing, so it needs no virtual environment.  Left to itself
    # Poetry creates one per project copy -- and the packaging gates build in a throwaway copy
    # each time, so a full test run would leave a directory behind in the user's cache for every
    # build it made, and would need an index reachable to populate them.
    env["POETRY_VIRTUALENVS_CREATE"] = "false"
    return env


def run_poetry(dist_dir: Path) -> Path:
    command = poetry_command()
    try:
        subprocess.run(
            [*command, "build", "--format", "wheel", "--no-interaction"],
            cwd=ROOT,
            env=build_environment(),
            check=True,
        )
    except FileNotFoundError:
        raise SystemExit(missing_poetry(command[0])) from None
    except subprocess.CalledProcessError as error:
        raise SystemExit(f"poetry build failed with exit status {error.returncode}") from None

    built = sorted(dist_dir.glob("*-py3-none-any.whl"))
    if len(built) != 1:
        raise SystemExit(f"expected exactly one wheel in {dist_dir}, found {len(built)}")
    return built[0]


def verify(wheel_path: Path, expected: dict[str, bytes], info: str) -> None:
    """Check the built archive against the allowlist and against the pinned builder."""

    with zipfile.ZipFile(wheel_path) as archive:
        names = set(archive.namelist())
        wheel_metadata = archive.read(f"{info}/WHEEL").decode("utf-8")

    carried = {name for name in names if not name.startswith(f"{info}/")}
    unexpected = sorted(carried - set(expected))
    if unexpected:
        raise SystemExit(
            "the built wheel carries files the allowlist rejects:\n  "
            + "\n  ".join(unexpected)
            + "\nRemove them, or widen the allowlist in scripts/build_wheel.py deliberately."
        )
    missing = sorted(set(expected) - carried)
    if missing:
        raise SystemExit(
            "the built wheel is missing files the source has:\n  "
            + "\n  ".join(missing)
            + "\nCheck the `include` entries under [tool.poetry] in pyproject.toml."
        )

    match = _GENERATOR_RE.search(wheel_metadata)
    generator = match.group(1) if match else "(none)"
    pin = pinned_backend()
    if generator != pin:
        raise SystemExit(
            f"built by poetry-core {generator}, but [build-system] pins {pin}.\n"
            "These build one commit into two different digests, so the published digest would\n"
            "stop describing a rebuild.  Install the pinned Poetry, or change the pin and say so\n"
            "in docs/release/wheel-reproducibility-v1.md."
        )


def main() -> int:
    project = load_project()
    name, version = project["name"], project["version"]
    info = f"{normalize(name)}-{version}.dist-info"

    expected = collect_package_files()

    dist_dir = ROOT / "dist"
    dist_dir.mkdir(exist_ok=True)
    for stale in dist_dir.glob("*-py3-none-any.whl"):
        stale.unlink()

    wheel_path = run_poetry(dist_dir)
    verify(wheel_path, expected, info)

    print(f"built {wheel_path.relative_to(ROOT)}  ({wheel_path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
