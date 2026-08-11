#!/usr/bin/env python3
"""Non-mutating Markdown and AART documentation consistency checks."""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
_LINK_RE = re.compile(r"!?\[[^]]*\]\(([^)]+)\)")
_TASK_RE = re.compile(r"^### ([A-Z][A-Z0-9]*\d+) — ", re.MULTILINE)
_LEDGER_RE = re.compile(r"^\| ([A-Z][A-Z0-9]*\d+) \|", re.MULTILINE)


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


def check_repository(root: Path = ROOT) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    for path in _repository_markdown(root):
        diagnostics.extend(validate_markdown(path, path.read_text(encoding="utf-8"), root))
    diagnostics.extend(_structure_diagnostics(root))
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
