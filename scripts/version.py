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
# Trailing horizontal whitespace only: ``\s*$`` would consume the line's newline, so writing the
# replacement back stripped the file's final newline and left every version bump failing
# format-check.
_INIT_RE = re.compile(r'(?m)^__version__\s*=\s*"([^"]+)"[ \t]*$')
_PROJECT_RE = re.compile(r'(?m)^version\s*=\s*"([^"]+)"[ \t]*$')
_RUNTIME_CONTRACT_RE = re.compile(
    r"(?m)^EXECUTABLE_VERSION\s*=\s*SemVer\("
    r"(?P<major>0|[1-9]\d*),\s*"
    r"(?P<minor>0|[1-9]\d*),\s*"
    r"(?P<patch>0|[1-9]\d*)"
    r'(?:,\s*\("(?P<phase>a|b|rc)",\s*(?P<number>0|[1-9]\d*)\))?'
    r"\)[ \t]*$"
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
    return mirror_diagnostics(root, str(version))


def _replace_one(pattern: re.Pattern[str], text: str, replacement: str, label: str) -> str:
    updated, count = pattern.subn(replacement, text)
    if count != 1:
        raise VersionError(f"expected exactly one {label} assignment, replaced {count}")
    return updated


def _runtime_contract_assignment(version: Version) -> str:
    prerelease = "" if version.phase is None else f', ("{version.phase}", {version.phase_number})'
    return f"EXECUTABLE_VERSION = SemVer({version.major}, {version.minor}, {version.patch}{prerelease})"


def write_version(root: Path, version: Version) -> tuple[str, ...]:
    ensure_allowed(root, version)
    previous = _version_strings(root)[0]
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
    return mirror_version(root, previous, str(version))


# The three files above are the version's home and must agree, which `read_version` enforces.
# These only quote it, and a quotation that disagrees is just as broken: the release checklist is
# pinned to a literal in `scripts/release.py`, the README publishes install commands naming an
# exact wheel, and the schema freeze records the release it was taken for.  Bumping by hand meant
# editing more than twenty of them, and a bump that missed one failed the gates with a message
# about a wheel name rather than about a missed edit.
#
# The freeze is here for a second reason, and it is the more important one.  It exists to notice
# when a normative schema changes without anyone deciding to change it -- the digests are a
# tripwire.  But it also carried the release version, so a plain version bump made it stale and
# the fix was to regenerate it, every release, unread.  A tripwire reset by routine catches
# nothing.  Moving the version leaves `schema-freeze-stale` meaning what it says: a schema moved.
#
# Written only where they exist.  A version fixture in a temporary directory is not a repository,
# and a missing README is not a version error.
#
# Each mirror names, in one place, the version it currently records.  Reading that anchor is what
# makes the rewrite repair-capable: keying only on the previous canonical version meant a tree
# whose three home files had already moved -- bumped by hand, or by a run that stopped before the
# mirrors -- could never be repaired, because re-running `set` on the version already there did
# nothing at all.  The state the tool most needs to fix was the one state it refused to touch.
@dataclass(frozen=True)
class _Mirror:
    relative: str
    anchor: re.Pattern[str]


_MIRRORS = (
    _Mirror("scripts/release.py", re.compile(r'^EXPECTED_VERSION = "([^"]+)"', re.MULTILINE)),
    _Mirror("README.md", re.compile(r"aart_cli-([0-9][^\s-]*)-py3-none-any\.whl")),
    _Mirror(
        "docs/release/schema-freeze-v18.json",
        re.compile(r'"release_version"\s*:\s*"([^"]+)"'),
    ),
)


def _recorded(root: Path, mirror: _Mirror) -> tuple[str, str] | None:
    """The text of the mirror and the version it quotes, or None where the file is absent."""

    path = root / mirror.relative
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    match = mirror.anchor.search(text)
    return (text, match.group(1)) if match else (text, "")


def mirror_version(root: Path, previous: str, version: str) -> tuple[str, ...]:
    touched: list[str] = []
    for mirror in _MIRRORS:
        found = _recorded(root, mirror)
        if found is None:
            continue
        text, recorded = found
        stale = recorded or previous
        if stale == version or stale not in text:
            continue
        (root / mirror.relative).write_text(text.replace(stale, version), encoding="utf-8")
        touched.append(mirror.relative)
    return tuple(touched)


def mirror_diagnostics(root: Path, version: str) -> tuple[str, ...]:
    """Name every mirror that disagrees, and the one command that fixes all of them.

    Without this the disagreement surfaces as unit-test failures about a wheel name, a README
    table and a freeze document -- seven of them, in three files, none of which says that a
    version bump missed its mirrors or what to run about it.
    """

    diagnostics: list[str] = []
    for mirror in _MIRRORS:
        found = _recorded(root, mirror)
        if found is None:
            continue
        recorded = found[1]
        if not recorded:
            diagnostics.append(f"{mirror.relative} no longer quotes the version where expected")
        elif recorded != version:
            diagnostics.append(f"{mirror.relative} records {recorded}, the version is {version}")
    if diagnostics:
        diagnostics.append(f"repair them with: python scripts/version.py set {version} --write")
    return tuple(diagnostics)


def _report(mirrors: tuple[str, ...], line: str) -> None:
    """Say what else moved.  A silent edit to a file the operator did not name is a surprise."""

    print(line)
    for relative in mirrors:
        print(f"  also rewritten: {relative}")


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
            _report(write_version(root, candidate), f"version set: {candidate}")
        elif args.command == "finalize":
            candidate = finalize_candidate(read_version(root))
            if not args.write:
                raise VersionError(f"refusing to write {candidate} without --write")
            _report(write_version(root, candidate), f"version finalized: {candidate}")
        elif args.command == "set":
            candidate = parse_version(args.version)
            if not args.write:
                raise VersionError(f"refusing to write {candidate} without --write")
            _report(write_version(root, candidate), f"version set: {candidate}")
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
