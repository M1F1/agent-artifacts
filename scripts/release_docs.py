#!/usr/bin/env python3
"""Put the release documents in place, so the only thing left is what to say.

A release needs four documents, and the checklist refuses without them.  Three already exist and
need a new section in a particular spot; one is new.  Working that out by hand each time is how a
release ends up with a `CHANGELOG` entry and no compatibility note, or with a heading that says
the right version over prose describing the last one.

So this writes the headings and leaves the prose.  Every gap it cannot fill is marked with a
visible `TODO(<version>)` line -- visible, not an HTML comment, because a placeholder that renders
invisibly is a placeholder that ships.  `--check` lists what is still open, and `cut_release.py`
refuses a release that still carries one.

Run it with no other arguments and it asks; give it `--summary` and it asks nothing, which is how
an agent or a script drives it.
"""

from __future__ import annotations

import argparse
import datetime
import importlib.util
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTRACT = re.compile(r"(?m)^RELEASE_CONTRACT_VERSION\s*=\s*(\d+)\s*$")
# `# AART v18 compatibility matrix — 2.8.0 through 2.8.5`
SPAN = re.compile(r"(?m)^(#\s.*\bthrough\s)(\d+\.\d+\.\d+)\s*$")


def _todo(version: str, what: str) -> str:
    return f"TODO({version}): {what}"


@dataclass(frozen=True)
class Document:
    path: Path
    relative: str  # named at plan time: the plan's root is not always this repository
    body: str
    where: str  # "create", "prepend-section", "append-section"


def contract_version(root: Path = ROOT) -> str:
    match = CONTRACT.search((root / "scripts" / "release.py").read_text(encoding="utf-8"))
    if match is None:
        raise SystemExit("cannot read RELEASE_CONTRACT_VERSION from scripts/release.py")
    return match.group(1)


def _unreleased_body(root: Path) -> str | None:
    """What `## Unreleased` already holds, or `None` — including when there is no such script."""

    path = root / "scripts" / "changelog.py"
    if not path.is_file():  # a plan root that is not this repository
        return None
    spec = importlib.util.spec_from_file_location("_aart_release_docs_changelog", path)
    if spec is None or spec.loader is None:  # pragma: no cover - only if the file is unreadable
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.section_body(root)


def plan(version: str, summary: str, root: Path = ROOT) -> tuple[Document, ...]:
    contract = contract_version(root)
    today = datetime.date.today().isoformat()
    headline = summary or _todo(version, "one line saying what this release does")

    notes = f"""# AART {version}

{headline}

## What {version} does

{_todo(version, "one bold sentence per change, then a line or two of explanation")}

## Compatibility

{_todo(version, "what does not move -- protocol versions, schemas, receipt fields, commands, flags -- and what does")}

Install or upgrade with the wheel attached to this release. AART installs with no runtime
dependencies: standard library only.

## Known defects shipped open

{_todo(version, "the list, or the word None -- but not silence")}
"""

    # Written as the changes landed, if anyone did.  Scaffolding a `### Fixed` TODO over entries
    # that already exist asks for the same prose twice, in two places, and one of the two then
    # becomes the real one by accident.  See scripts/changelog.py.
    waiting = _unreleased_body(root)
    body = (
        waiting
        or f"""{headline}

### Fixed

- {_todo(version, "a bold sentence of claim, then why it was wrong")}"""
    )
    changelog = f"""## {version} — {today}

{body}

"""

    compatibility = f"""
## {version} — {headline}

{_todo(version, "what moves at each boundary, or the sentence that nothing does")}

Schema freeze v{contract} for `{version}` differs from the previous freeze in `release_version`
{_todo(version, "and in which inputs, or delete this half of the sentence")}.
"""

    checklist = f"""
## {version} change gate

`{version}` ships under this same v{contract} contract.

- {_todo(version, "what is now true, and what establishes it")}
- {_todo(version, "confirm: no protocol version, persisted schema, receipt field, command, flag or recipe construct changes")}

Steps 1–8 above are repeated unchanged for `{version}`, with `v{version}` as the tag and
[`github-release-v{version}.md`](github-release-v{version}.md) as the release body.
"""

    def document(relative: str, body: str, where: str) -> Document:
        return Document(root / relative, relative, body, where)

    return (
        document(f"docs/release/github-release-v{version}.md", notes, "create"),
        document("CHANGELOG.md", changelog, "prepend-section"),
        document(f"docs/release/compatibility-v{contract}.md", compatibility, "append-section"),
        document(f"docs/release/release-checklist-v{contract}.md", checklist, "append-section"),
    )


def _widen_span(text: str, version: str) -> str:
    """`— 2.8.0 through 2.8.5` becomes `through 2.8.6`.

    Only the upper bound moves.  The lower one is the release the contract opened with and is not
    this release's to rewrite -- the same reason the dated sections below it are appended to rather
    than edited.
    """

    return SPAN.sub(lambda match: f"{match.group(1)}{version}", text, count=1)


def apply(document: Document, version: str) -> str:
    """Write one document.  Returns a line saying what happened."""

    relative = document.relative
    if document.where == "create":
        if document.path.exists():
            return f"kept {relative} (already written)"
        document.path.write_text(document.body, encoding="utf-8")
        return f"created {relative}"

    text = document.path.read_text(encoding="utf-8")
    if re.search(rf"(?m)^#+\s.*\b{re.escape(version)}\b", text):
        return f"kept {relative} ({version} already has a section)"

    if document.where == "prepend-section":
        # Above the newest entry, below the file's own preamble.
        first = re.search(r"(?m)^## ", text)
        cut = first.start() if first else len(text)
        text = text[:cut] + document.body + text[cut:]
    else:
        text = _widen_span(text, version) + document.body

    document.path.write_text(text, encoding="utf-8")
    return f"extended {relative}"


def open_markers(version: str, root: Path = ROOT) -> tuple[str, ...]:
    """Every place still carrying a placeholder for this version."""

    marker = _todo(version, "")
    found: list[str] = []
    for document in plan(version, "", root):
        if not document.path.exists():
            found.append(f"{document.relative}: missing")
            continue
        for number, line in enumerate(
            document.path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if marker in line:
                found.append(f"{document.relative}:{number}: {line.strip()}")
    return tuple(found)


def _ask(version: str) -> str:
    print(f"Release documents for {version}.  One question; the rest is left as TODO lines.\n")
    print("In one line: what does this release do?  (Enter to leave it as a TODO)")
    try:
        return input("> ").strip()
    except EOFError:  # a pipe with nothing in it is the same as an empty answer
        return ""


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version", help="the version being released, without the leading v")
    parser.add_argument("--summary", help="the one-line headline; given, nothing is asked")
    parser.add_argument(
        "--check",
        action="store_true",
        help="write nothing; list the placeholders still open for this version",
    )
    arguments = parser.parse_args(argv[1:])
    version = arguments.version.lstrip("v")

    if arguments.check:
        open_ones = open_markers(version)
        for line in open_ones:
            print(line)
        if open_ones:
            print(f"\n{len(open_ones)} place(s) still to write for {version}.", file=sys.stderr)
            return 2
        print(f"release documents for {version}: nothing left open")
        return 0

    summary = arguments.summary if arguments.summary is not None else _ask(version)
    for document in plan(version, summary):
        print(apply(document, version))

    remaining = open_markers(version)
    print(f"\n{len(remaining)} place(s) left to write. Find them with:")
    print(f"  grep -rn 'TODO({version})' CHANGELOG.md docs/release/")
    print("The release refuses to cut while any of them stands.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
