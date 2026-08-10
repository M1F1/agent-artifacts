#!/usr/bin/env python3
"""Explicit, fail-closed AART version and release-tag management."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_VERSION_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)\."
    r"(?P<minor>0|[1-9]\d*)\."
    r"(?P<patch>0|[1-9]\d*)"
    r"(?:(?P<phase>a|b|rc)(?P<number>0|[1-9]\d*))?$"
)
_INIT_RE = re.compile(r'(?m)^__version__\s*=\s*"([^"]+)"\s*$')
_PROJECT_RE = re.compile(r'(?m)^version\s*=\s*"([^"]+)"\s*$')
_RUNTIME_CONTRACT_RE = re.compile(
    r"(?m)^EXECUTABLE_VERSION\s*=\s*SemVer\("
    r"(?P<major>0|[1-9]\d*),\s*"
    r"(?P<minor>0|[1-9]\d*),\s*"
    r"(?P<patch>0|[1-9]\d*)"
    r'(?:,\s*\("(?P<phase>a|b|rc)",\s*(?P<number>0|[1-9]\d*)\))?'
    r"\)\s*$"
)
_TASK_ID_RE = re.compile(r"^[A-Z][A-Z0-9]*\d+$")


class VersionError(ValueError):
    pass


@dataclass(frozen=True)
class Version:
    major: int
    minor: int
    patch: int
    phase: str | None = None
    phase_number: int | None = None

    @property
    def stable(self) -> bool:
        return self.phase is None

    def __str__(self) -> str:
        suffix = "" if self.phase is None else f"{self.phase}{self.phase_number}"
        return f"{self.major}.{self.minor}.{self.patch}{suffix}"


def parse_version(raw: str) -> Version:
    match = _VERSION_RE.fullmatch(raw)
    if match is None:
        raise VersionError(
            f"invalid version {raw!r}; expected canonical X.Y.Z, X.Y.ZaN, X.Y.ZbN, or X.Y.ZrcN"
        )
    phase = match.group("phase")
    number = match.group("number")
    return Version(
        major=int(match.group("major")),
        minor=int(match.group("minor")),
        patch=int(match.group("patch")),
        phase=phase,
        phase_number=None if number is None else int(number),
    )


def next_alpha(version: Version) -> Version:
    if version.phase != "a" or version.phase_number is None:
        raise VersionError("next-alpha requires an existing X.Y.ZaN development version")
    return Version(version.major, version.minor, version.patch, "a", version.phase_number + 1)


def finalize_candidate(version: Version) -> Version:
    if version.stable:
        raise VersionError("finalize requires an existing alpha, beta, or release candidate")
    return Version(version.major, version.minor, version.patch)


def _extract(pattern: re.Pattern[str], text: str, label: str) -> str:
    matches = pattern.findall(text)
    if len(matches) != 1:
        raise VersionError(f"expected exactly one {label} version assignment, found {len(matches)}")
    return matches[0]


def _runtime_contract_version(text: str) -> str:
    matches = tuple(_RUNTIME_CONTRACT_RE.finditer(text))
    if len(matches) != 1:
        raise VersionError(
            f"expected exactly one runtime executable-version assignment, found {len(matches)}"
        )
    match = matches[0]
    suffix = (
        "" if match.group("phase") is None else f"{match.group('phase')}{match.group('number')}"
    )
    return f"{match.group('major')}.{match.group('minor')}.{match.group('patch')}{suffix}"


def _version_strings(root: Path) -> tuple[str, str, str]:
    init = (root / "agent_artifacts" / "__init__.py").read_text(encoding="utf-8")
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    runtime_contract = (root / "agent_artifacts" / "runtime_contract.py").read_text(
        encoding="utf-8"
    )
    return (
        _extract(_INIT_RE, init, "agent_artifacts.__version__"),
        _extract(_PROJECT_RE, pyproject, "pyproject project"),
        _runtime_contract_version(runtime_contract),
    )


def read_version(root: Path = ROOT) -> Version:
    init_version, project_version, runtime_contract_version = _version_strings(root)
    if len({init_version, project_version, runtime_contract_version}) != 1:
        raise VersionError(
            "version mismatch: "
            f"agent_artifacts={init_version}, pyproject={project_version}, "
            f"runtime_contract={runtime_contract_version}"
        )
    return parse_version(init_version)


def task_states(progress: str) -> tuple[tuple[str, str], ...]:
    if "## Task ledger" not in progress or "## Current-task template" not in progress:
        raise VersionError("PROGRESS.md has no bounded task ledger")
    ledger = progress.split("## Task ledger", 1)[1].split("## Current-task template", 1)[0]
    states: list[tuple[str, str]] = []
    for line in ledger.splitlines():
        if not line.startswith("|"):
            continue
        cells = tuple(cell.strip() for cell in line.split("|"))
        if len(cells) < 6 or _TASK_ID_RE.fullmatch(cells[1]) is None:
            continue
        status = cells[4]
        if status not in {"pending", "in_progress", "blocked", "complete"}:
            raise VersionError(f"unknown task status for {cells[1]}: {status}")
        states.append((cells[1], status))
    if not states or "REL01" not in {task for task, _status in states}:
        raise VersionError("PROGRESS.md task ledger has no REL01")
    return tuple(states)


def release_ready(root: Path = ROOT) -> bool:
    progress = (root / "PROGRESS.md").read_text(encoding="utf-8")
    return all(status == "complete" for _task, status in task_states(progress))


def ensure_allowed(root: Path, version: Version) -> None:
    if version.major >= 1 and version.stable and not release_ready(root):
        raise VersionError(
            f"stable {version} is blocked until every PROGRESS.md task through REL01 is complete"
        )


def check_version(root: Path = ROOT) -> tuple[str, ...]:
    try:
        version = read_version(root)
        ensure_allowed(root, version)
    except (OSError, VersionError) as error:
        return (str(error),)
    return ()


def _replace_one(pattern: re.Pattern[str], text: str, replacement: str, label: str) -> str:
    updated, count = pattern.subn(replacement, text)
    if count != 1:
        raise VersionError(f"expected exactly one {label} assignment, replaced {count}")
    return updated


def _runtime_contract_assignment(version: Version) -> str:
    prerelease = "" if version.phase is None else f', ("{version.phase}", {version.phase_number})'
    return f"EXECUTABLE_VERSION = SemVer({version.major}, {version.minor}, {version.patch}{prerelease})"


def write_version(root: Path, version: Version) -> None:
    ensure_allowed(root, version)
    init_path = root / "agent_artifacts" / "__init__.py"
    runtime_contract_path = root / "agent_artifacts" / "runtime_contract.py"
    project_path = root / "pyproject.toml"
    init = init_path.read_text(encoding="utf-8")
    runtime_contract = runtime_contract_path.read_text(encoding="utf-8")
    project = project_path.read_text(encoding="utf-8")
    updated_init = _replace_one(
        _INIT_RE, init, f'__version__ = "{version}"', "agent_artifacts.__version__"
    )
    updated_project = _replace_one(
        _PROJECT_RE, project, f'version = "{version}"', "pyproject project version"
    )
    updated_runtime_contract = _replace_one(
        _RUNTIME_CONTRACT_RE,
        runtime_contract,
        _runtime_contract_assignment(version),
        "runtime executable-version",
    )
    init_path.write_text(updated_init, encoding="utf-8")
    project_path.write_text(updated_project, encoding="utf-8")
    runtime_contract_path.write_text(updated_runtime_contract, encoding="utf-8")


def validate_tag(root: Path, tag: str, expected: Version | None = None) -> None:
    diagnostics = check_version(root)
    if diagnostics:
        raise VersionError("; ".join(diagnostics))
    current = read_version(root)
    if expected is not None and expected != current:
        raise VersionError(f"tag version {expected} does not match source version {current}")
    expected_tag = f"v{current}"
    if tag != expected_tag:
        raise VersionError(f"tag {tag!r} does not match source version tag {expected_tag!r}")
    ensure_allowed(root, current)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="validate synchronized version files and release policy")
    commands.add_parser("show", help="print the current canonical version")
    commands.add_parser("next-alpha", help="print the next alpha without writing files")
    bump = commands.add_parser("bump-alpha", help="explicitly advance X.Y.ZaN")
    bump.add_argument("--write", action="store_true", help="required acknowledgement to write")
    finalize = commands.add_parser("finalize", help="finalize the current prerelease core version")
    finalize.add_argument("--write", action="store_true", help="required acknowledgement to write")
    set_command = commands.add_parser("set", help="explicitly set a validated version")
    set_command.add_argument("version")
    set_command.add_argument("--write", action="store_true", help="required acknowledgement")
    tag = commands.add_parser("check-tag", help="validate a release tag against source/policy")
    tag.add_argument("tag")
    return parser


def main(argv: tuple[str, ...] | None = None, root: Path = ROOT) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "check":
            diagnostics = check_version(root)
            if diagnostics:
                raise VersionError("; ".join(diagnostics))
            print(f"version check OK: {read_version(root)}")
        elif args.command == "show":
            print(read_version(root))
        elif args.command == "next-alpha":
            print(next_alpha(read_version(root)))
        elif args.command == "bump-alpha":
            candidate = next_alpha(read_version(root))
            if not args.write:
                raise VersionError(f"refusing to write {candidate} without --write")
            write_version(root, candidate)
            print(f"version set: {candidate}")
        elif args.command == "finalize":
            candidate = finalize_candidate(read_version(root))
            if not args.write:
                raise VersionError(f"refusing to write {candidate} without --write")
            write_version(root, candidate)
            print(f"version finalized: {candidate}")
        elif args.command == "set":
            candidate = parse_version(args.version)
            if not args.write:
                raise VersionError(f"refusing to write {candidate} without --write")
            write_version(root, candidate)
            print(f"version set: {candidate}")
        elif args.command == "check-tag":
            validate_tag(root, args.tag)
            print(f"release tag check OK: {args.tag}")
        else:  # pragma: no cover - argparse owns command selection
            raise VersionError(f"unsupported command: {args.command}")
    except (OSError, VersionError) as error:
        print(f"version error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
