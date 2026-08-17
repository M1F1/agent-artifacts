#!/usr/bin/env python3
"""Non-mutating Markdown and AART documentation consistency checks."""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
_LINK_RE = re.compile(r"!?\[[^]]*\]\(([^)]+)\)")
_TASK_RE = re.compile(r"^### ([A-Z][A-Z0-9]*\d+) — ", re.MULTILINE)
_LEDGER_RE = re.compile(r"^\| ([A-Z][A-Z0-9]*\d+) \|", re.MULTILINE)

# `RR-7` / cluster C6: the residue register is the single place that says what is open, and these
# expressions are what make it authoritative rather than aspirational.
_REGISTER_PATH = ("docs", "testing", "residue-register.md")
# The id families the register carries.  `LAF` is a live-acceptance finding, `RS` a residue of the
# `2026-08-15` stream, `AD` a finding raised while adopting AART inside a company.  A new stream
# adds its prefix here once, so its ids are held by every rule below rather than by none of them —
# a family the expressions do not know about is invisible to the gate, which is the failure the
# register exists to prevent.
_FINDING_PREFIXES = "LAF|RS|AD"
_FINDING_RE = re.compile(rf"\b((?:{_FINDING_PREFIXES})-\d+)\b")
_REGISTER_ROW_RE = re.compile(
    rf"^\| `((?:{_FINDING_PREFIXES})-\d+)` \| [^|]+ \| [^|]+ \| `(open|closed|visible|deferred)` \|",
    re.MULTILINE,
)
_OPEN_HEADING_RE = re.compile(r"^(#{2,6}) .*\bshipped open\b.*$", re.MULTILINE | re.IGNORECASE)
# `LAF-69`: the structured form in which a document may state a finding's state — one table cell
# holding one disposition and nothing else.  A cell that says anything more (*was `visible`*, *`open`
# again*) is prose about a history, and prose is what the register exists to stop documents deciding
# with.  So the gate reads the cell, never the sentence.
_CLAIM_CELL_RE = re.compile(r"^`(open|closed|visible|deferred)`$")
_HEADING_RE = re.compile(r"^#{1,6} ", re.MULTILINE)
_STREAM_GLOB = "docs/testing/residue-stream-*.md"
# Which documents must agree with the register, declared by the register itself. Released
# documents are dated records of what was open when they shipped and are deliberately not here:
# editing them to match today would destroy the evidence they exist to be.
_CHECKED_RE = re.compile(r"^- checked: `([^`]+)`\s*$", re.MULTILINE)


@dataclass(frozen=True, order=True)
class Diagnostic:
    path: str
    line: int
    code: str
    message: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.code} {self.message}"


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _link_path(raw_target: str) -> str | None:
    target = raw_target.strip()
    if target.startswith("<") and ">" in target:
        target = target[1 : target.index(">")]
    else:
        target = target.split(maxsplit=1)[0]
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or target.startswith(("#", "mailto:", "data:")):
        return None
    return unquote(parsed.path)


def validate_markdown(path: Path, text: str, root: Path) -> tuple[Diagnostic, ...]:
    """Return deterministic fence/link diagnostics for one Markdown document."""

    diagnostics: list[Diagnostic] = []
    active_marker: str | None = None
    active_line = 0
    for line_number, line in enumerate(text.splitlines(), 1):
        match = _FENCE_RE.match(line)
        if match is None:
            continue
        marker = match.group(1)[0]
        if active_marker is None:
            active_marker = marker
            active_line = line_number
        elif marker == active_marker:
            active_marker = None
            active_line = 0
    if active_marker is not None:
        diagnostics.append(
            Diagnostic(
                str(path.relative_to(root)),
                active_line,
                "DOC001",
                f"unclosed {active_marker * 3} fence",
            )
        )

    for match in _LINK_RE.finditer(text):
        local = _link_path(match.group(1))
        if not local:
            continue
        if local.startswith("/"):
            candidate = root / local.lstrip("/")
        else:
            candidate = path.parent / local
        if not candidate.resolve().exists():
            diagnostics.append(
                Diagnostic(
                    str(path.relative_to(root)),
                    _line_number(text, match.start()),
                    "DOC002",
                    f"missing relative link target: {local}",
                )
            )
    return tuple(sorted(diagnostics))


def _repository_markdown(root: Path) -> tuple[Path, ...]:
    result = subprocess.run(
        [
            "git",
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            "*.md",
        ],
        cwd=root,
        capture_output=True,
        check=True,
    )
    return tuple(
        path
        for raw in result.stdout.split(b"\0")
        if raw
        if (path := root / raw.decode("utf-8")).is_file()
    )


def _structure_diagnostics(root: Path) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    spec_path = root / "docs" / "design" / "SPEC-aart-1.0.md"
    plan_path = root / "PLAN.md"
    progress_path = root / "PROGRESS.md"
    if spec_path.exists():
        spec = spec_path.read_text(encoding="utf-8")
        numbers = [int(value) for value in re.findall(r"^## (\d+)\. ", spec, re.MULTILINE)]
        if numbers != list(range(1, len(numbers) + 1)):
            diagnostics.append(
                Diagnostic(
                    str(spec_path.relative_to(root)),
                    1,
                    "DOC003",
                    f"numbered sections are not sequential: {numbers}",
                )
            )
    if plan_path.exists() and progress_path.exists():
        plan = plan_path.read_text(encoding="utf-8")
        progress = progress_path.read_text(encoding="utf-8")
        ledger = progress.split("## Task ledger", 1)[-1].split("## Current-task template", 1)[0]
        plan_ids = _TASK_RE.findall(plan)
        ledger_ids = _LEDGER_RE.findall(ledger)
        if plan_ids != ledger_ids:
            diagnostics.append(
                Diagnostic(
                    str(progress_path.relative_to(root)),
                    1,
                    "DOC004",
                    "PLAN task IDs and PROGRESS ledger rows differ",
                )
            )
        if ledger.count("| in_progress |") > 1:
            diagnostics.append(
                Diagnostic(
                    str(progress_path.relative_to(root)),
                    1,
                    "DOC005",
                    "more than one task is in progress",
                )
            )
    return tuple(diagnostics)


def _sections_under(text: str, heading: re.Match[str]) -> str:
    """The body of one heading's section: everything up to the next heading of any depth."""

    start = heading.end()
    following = _HEADING_RE.search(text, start)
    return text[start : following.start() if following else len(text)]


def _claim_diagnostics(
    path: Path, text: str, root: Path, rows: Mapping[str, str]
) -> tuple[Diagnostic, ...]:
    """`DOC010` — a checked document's disposition claims must equal the register's.

    `LAF-69`: `DOC009` fails a document that lists as *shipped open* something the register has
    closed, and nothing failed the opposite claim. The first is a stale worry; the second asserts a
    safety that is not there, which is the direction that misleads an operator — and it happened:
    the register moved `LAF-61` back to `open` while two release documents kept saying `visible`,
    and `docs-check` passed.

    A claim is a table row that names a finding and carries a cell that is *exactly* one
    disposition (`_CLAIM_CELL_RE`) — the shape `compatibility-v14.md` already uses. Released
    documents are outside the checked list in this direction too: a dated record is not edited to
    agree with today.
    """

    diagnostics: list[Diagnostic] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.lstrip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        claimed = [match.group(1) for cell in cells if (match := _CLAIM_CELL_RE.match(cell))]
        if not claimed:
            continue
        for identifier in dict.fromkeys(_FINDING_RE.findall(line)):
            recorded = rows.get(identifier)
            for claim in claimed:
                if recorded is not None and claim != recorded:
                    diagnostics.append(
                        Diagnostic(
                            str(path.relative_to(root)),
                            line_number,
                            "DOC010",
                            f"{identifier} is claimed `{claim}` and the register records "
                            f"`{recorded}`",
                        )
                    )
    return tuple(diagnostics)


def _register_diagnostics(root: Path) -> tuple[Diagnostic, ...]:
    """`RR-7`: the residue register is the only place a finding's state is recorded.

    Three rules, and the first is the one that answers cluster `C6`. A finding gathered into a
    stream and left out of the register is exactly how an item stops being trackable and gets
    re-discovered a release later; nothing else in this repository would notice.
    """

    register_path = root.joinpath(*_REGISTER_PATH)
    if not register_path.is_file():
        return ()
    register = register_path.read_text(encoding="utf-8")
    relative = str(register_path.relative_to(root))
    diagnostics: list[Diagnostic] = []

    rows: dict[str, str] = {}
    reproduction: dict[str, str] = {}
    for match in _REGISTER_ROW_RE.finditer(register):
        identifier, disposition = match.group(1), match.group(2)
        if identifier in rows:
            diagnostics.append(
                Diagnostic(
                    relative,
                    _line_number(register, match.start()),
                    "DOC006",
                    f"{identifier} has more than one register row",
                )
            )
            continue
        rows[identifier] = disposition
        tail = register[match.end() :].split("\n", 1)[0]
        reproduction[identifier] = tail.strip().strip("|").strip()

    # A closure claim without the reproduction that establishes it is prose again, which is the
    # form of record this register was written to replace.
    for identifier, disposition in sorted(rows.items()):
        established = reproduction[identifier].lstrip("—").strip()
        if disposition in ("closed", "visible") and not established:
            diagnostics.append(
                Diagnostic(
                    relative,
                    1,
                    "DOC007",
                    f"{identifier} is {disposition} and names no reproduction",
                )
            )

    for stream_path in sorted(root.glob(_STREAM_GLOB)):
        stream = stream_path.read_text(encoding="utf-8")
        for match in re.finditer(rf"^\| `((?:{_FINDING_PREFIXES})-\d+)` \|", stream, re.MULTILINE):
            if match.group(1) not in rows:
                diagnostics.append(
                    Diagnostic(
                        str(stream_path.relative_to(root)),
                        _line_number(stream, match.start()),
                        "DOC008",
                        f"{match.group(1)} is gathered into a stream and absent from the register",
                    )
                )

    for pattern in _CHECKED_RE.findall(register):
        for path in sorted(root.glob(pattern)):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            diagnostics.extend(_claim_diagnostics(path, text, root, rows))
            for heading in _OPEN_HEADING_RE.finditer(text):
                for found in _FINDING_RE.finditer(_sections_under(text, heading)):
                    if rows.get(found.group(1)) == "closed":
                        diagnostics.append(
                            Diagnostic(
                                str(path.relative_to(root)),
                                _line_number(text, heading.start()),
                                "DOC009",
                                f"{found.group(1)} is listed as shipped open "
                                "and is closed in the register",
                            )
                        )
    return tuple(diagnostics)


def check_repository(root: Path = ROOT) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    for path in _repository_markdown(root):
        diagnostics.extend(validate_markdown(path, path.read_text(encoding="utf-8"), root))
    diagnostics.extend(_structure_diagnostics(root))
    diagnostics.extend(_register_diagnostics(root))
    return tuple(sorted(diagnostics))


def main() -> int:
    diagnostics = check_repository()
    for diagnostic in diagnostics:
        print(diagnostic.render())
    if diagnostics:
        print(f"docs check FAILED: {len(diagnostics)} diagnostic(s)")
        return 1
    print("docs check OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
