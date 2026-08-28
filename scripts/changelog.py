#!/usr/bin/env python3
"""The changelog decides the version, and the version is never typed by hand.

Semantic versioning says what a version number means: something was removed, something was added,
something was fixed.  A changelog says which of those happened.  So the number is a *consequence*
of the changelog, and typing it separately is how a release ends up called `2.9.0` over a section
that only fixes things -- or, worse, `2.8.6` over a section that removes one.

The prose stays written by hand.  Nobody can generate a sentence that says why something was
wrong.  What is generated is everything mechanical around it: which part of the version moves, the
heading, the date, and the order.

## How it is used

Changes accumulate under `## Unreleased` as they land, each under a heading that says what kind of
change it is.  At the release:

    python scripts/changelog.py next            # what the version would be, and why
    python scripts/changelog.py release --write # cut the section, stamp the heading and the date

`release` prints the version it cut.  `scripts/version.py set <that version> --write` then puts it
in the source, and the rest of the release runs as it always did.

## Which heading moves which part

    Removed, Breaking            -> major
    Added, Changed               -> minor
    Fixed, Security, Packaging,
    Documentation, Testing       -> patch

Any other heading is prose about the release rather than a change in it -- `Compatibility`,
`Known defects shipped open`, `Upgrading from 2.7.1` -- and is kept, printed, and ignored when
deciding the number.  A section made only of those cannot decide a version, and this refuses rather
than guessing: a wrong guess here is a number that will be wrong forever.
"""

from __future__ import annotations

import argparse
import datetime
import importlib.util
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = "CHANGELOG.md"
UNRELEASED = "Unreleased"

# `## 2.8.5 — 2026-08-21`, on an em dash, which is what every heading in this file already uses.
_RELEASE_HEADING_RE = re.compile(r"^## (\d+\.\d+\.\d+[a-z0-9]*) — (\d{4}-\d{2}-\d{2})\s*$")
_UNRELEASED_HEADING_RE = re.compile(rf"^## {UNRELEASED}\s*$")
_KIND_RE = re.compile(r"^### (.+?)\s*$")

# Which kind of change moves which part of the version.  This table is the whole of the mapping;
# there is no second place where a version part is decided.
_MAJOR = ("removed", "breaking")
_MINOR = ("added", "changed")
_PATCH = ("fixed", "security", "packaging", "documentation", "testing")
_PARTS = {
    **{kind: "major" for kind in _MAJOR},
    **{kind: "minor" for kind in _MINOR},
    **{kind: "patch" for kind in _PATCH},
}
_RANK = {"patch": 0, "minor": 1, "major": 2}


class ChangelogError(ValueError):
    pass


@dataclass(frozen=True)
class Section:
    """One `## ` block: a release, or the unreleased one that has no number yet."""

    version: str | None  # None for the unreleased section
    date: str | None
    kinds: tuple[str, ...]
    body: str  # everything under the heading, without the heading line
    line: int

    @property
    def released(self) -> bool:
        return self.version is not None


def _versioning():
    """`scripts/version.py`, loaded the way `release.py` loads it: scripts/ is not a package."""

    path = ROOT / "scripts" / "version.py"
    spec = importlib.util.spec_from_file_location("_aart_changelog_version", path)
    if spec is None or spec.loader is None:  # pragma: no cover - only if the file is gone
        raise RuntimeError("cannot load scripts/version.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def parse(text: str) -> tuple[Section, ...]:
    """Every `## ` section, in file order, with its kind headings and its body."""

    lines = text.splitlines()
    starts: list[tuple[int, str | None, str | None]] = []
    for index, line in enumerate(lines):
        if not line.startswith("## "):
            continue
        release = _RELEASE_HEADING_RE.match(line)
        if release is not None:
            starts.append((index, release.group(1), release.group(2)))
            continue
        if _UNRELEASED_HEADING_RE.match(line):
            starts.append((index, None, None))
            continue
        raise ChangelogError(
            f"{CHANGELOG}:{index + 1}: heading {line.strip()!r} is neither "
            f"`## {UNRELEASED}` nor `## X.Y.Z — YYYY-MM-DD`"
        )

    sections: list[Section] = []
    for position, (index, version, date) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        body_lines = lines[index + 1 : end]
        kinds = tuple(
            match.group(1) for line in body_lines if (match := _KIND_RE.match(line)) is not None
        )
        sections.append(Section(version, date, kinds, "\n".join(body_lines).strip("\n"), index + 1))
    return tuple(sections)


def _version_key(raw: str) -> tuple[int, int, int]:
    version = _versioning().parse_version(raw)
    return (version.major, version.minor, version.patch)


def check(text: str) -> tuple[str, ...]:
    """Everything about the file's shape that can be wrong without anyone noticing.

    Not checked here: whether the top section names the version being released.  That belongs to
    the release run, which knows what is being released; `scripts/release.py` already holds it.
    """

    try:
        sections = parse(text)
    except ChangelogError as error:
        return (str(error),)

    problems: list[str] = []
    for position, section in enumerate(sections):
        if not section.released and position != 0:
            problems.append(
                f"{CHANGELOG}:{section.line}: `## {UNRELEASED}` is not the first section. "
                "It holds what has not shipped, so it belongs above what has."
            )
        if not section.body.strip():
            name = section.version or UNRELEASED
            problems.append(f"{CHANGELOG}:{section.line}: section `{name}` is empty.")

    unreleased = [section for section in sections if not section.released]
    if len(unreleased) > 1:
        problems.append(
            f"{CHANGELOG}: {len(unreleased)} `## {UNRELEASED}` sections; there can be one."
        )

    released = [section for section in sections if section.released]
    seen: dict[str, int] = {}
    for section in released:
        assert section.version is not None
        if section.version in seen:
            problems.append(
                f"{CHANGELOG}:{section.line}: version {section.version} appears twice "
                f"(also at line {seen[section.version]})."
            )
        seen[section.version] = section.line
        try:
            datetime.date.fromisoformat(section.date or "")
        except ValueError:
            problems.append(
                f"{CHANGELOG}:{section.line}: {section.date!r} is not a date (YYYY-MM-DD)."
            )

    for earlier, later in zip(released, released[1:], strict=False):
        assert earlier.version is not None and later.version is not None
        try:
            if _version_key(earlier.version) <= _version_key(later.version):
                problems.append(
                    f"{CHANGELOG}:{later.line}: {later.version} is not below "
                    f"{earlier.version}. A changelog reads newest first."
                )
        except Exception as error:  # a version this project cannot parse
            problems.append(f"{CHANGELOG}:{later.line}: {error}")
    return tuple(problems)


def implied_part(kinds: Sequence[str]) -> str:
    """The part of the version these headings move: the largest one any of them asks for."""

    parts = [_PARTS[kind.strip().casefold()] for kind in kinds if kind.strip().casefold() in _PARTS]
    if not parts:
        raise ChangelogError(
            "no heading under `## "
            + UNRELEASED
            + "` says what kind of change this is, so the version cannot be decided.\n"
            "Use one of: " + ", ".join(sorted(_PARTS)) + ".\n"
            "Headings outside that list are prose about the release and are kept as they are."
        )
    return max(parts, key=lambda part: _RANK[part])


def unreleased(text: str) -> Section:
    sections = parse(text)
    if not sections or sections[0].released:
        raise ChangelogError(
            f"{CHANGELOG} has no `## {UNRELEASED}` section, so there is nothing to release.\n"
            "Write the change under it as the change lands, not at the release."
        )
    return sections[0]


_BELOW_ONE = {"major": "minor", "minor": "patch", "patch": "patch"}


def part_before_one(part: str) -> str:
    """While the major version is `0`, each part moves the one below it.

    `0.y.z` promises nothing, which is what a zero major version means, so a removal there is not
    the event that `1.0.0` announces.  Bumping to `1.0.0` on the first thing this project removes
    would declare a stability nobody decided on -- and that declaration cannot be taken back, since
    a published version number is permanent.  So below `1.0.0` a breaking change moves the minor
    and everything else moves the patch.  `changelog.py next` says when it has done this.
    """

    return _BELOW_ONE[part]


def next_version(text: str, current: str) -> tuple[str, str]:
    """`(part, version)` — what moves, and what it moves to."""

    versioning = _versioning()
    version = versioning.parse_version(current)
    part = implied_part(unreleased(text).kinds)
    if version.major == 0:
        part = part_before_one(part)
    return part, str(versioning.next_release(version, part))


def release(text: str, version: str, today: str) -> str:
    """Cut the unreleased section into a dated release, leaving nothing behind.

    No empty `## Unreleased` is left in its place: an empty section is a section that fails the
    check above, and a changelog with nothing unreleased should say nothing rather than say it
    with a heading.
    """

    section = unreleased(text)
    lines = text.splitlines()
    heading = f"## {version} — {today}"
    lines[section.line - 1] = heading
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def section_body(root: Path = ROOT) -> str | None:
    """The unreleased entries, for `release_docs.py`, or `None` when there are none.

    `release_docs.py` scaffolds a `### Fixed` block with a `TODO` in it when nothing is waiting.
    When something is waiting, that scaffold would ask someone to write again what they already
    wrote, in a second place, and one of the two would end up the real one.
    """

    text = (root / CHANGELOG).read_text(encoding="utf-8")
    try:
        return unreleased(text).body
    except ChangelogError:
        return None


def _read(root: Path) -> str:
    return (root / CHANGELOG).read_text(encoding="utf-8")


def main(argv: Sequence[str] | None = None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="the file's shape: headings, order, dates, empty sections")
    sub.add_parser("next", help="the version the unreleased section asks for, and why")
    cut = sub.add_parser("release", help="cut the unreleased section into a dated release")
    cut.add_argument("--write", action="store_true", help="write the file; otherwise print it")
    cut.add_argument("--date", default=datetime.date.today().isoformat())
    arguments = parser.parse_args(argv)

    text = _read(root)
    if arguments.command == "check":
        problems = check(text)
        for problem in problems:
            print(problem, file=sys.stderr)
        if problems:
            return 1
        print("changelog OK")
        return 0

    versioning = _versioning()
    current = str(versioning.read_version(root))
    try:
        part, version = next_version(text, current)
    except (ChangelogError, versioning.VersionError) as error:
        print(str(error), file=sys.stderr)
        return 1

    if arguments.command == "next":
        kinds = ", ".join(unreleased(text).kinds) or "(none)"
        print(f"{current} -> {version}  ({part}, from: {kinds})")
        if versioning.parse_version(current).major == 0:
            print(
                "  below 1.0.0, so each part moves the one below it: this project has not "
                "declared stability yet."
            )
        return 0

    cut_text = release(text, version, arguments.date)
    if not arguments.write:
        print(cut_text, end="")
        return 0
    (root / CHANGELOG).write_text(cut_text, encoding="utf-8")
    print(f"changelog cut: {version} — {arguments.date}")
    print(f"next:  {sys.executable} scripts/version.py set {version} --write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
