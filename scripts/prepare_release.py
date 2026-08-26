#!/usr/bin/env python3
"""Everything a release needs locally, in one run, for a person or for an agent.

The release had a shape nobody could hold in their head: the version in six files, four documents
each with its section in a particular place, ten gates, eleven checks -- and doing them out of
order, or missing one, failed late with a message about the symptom rather than the omission.
`cut_release.py` fixed the half that runs in CI.  This is the half that runs on a laptop, and it
ends exactly where the button begins.

Two callers, one behaviour.  A person runs it bare and is asked what it needs:

    python scripts/prepare_release.py

An agent passes what a person would have typed and reads a receipt instead of prose:

    python scripts/prepare_release.py 2.8.6 --summary "..." --json

It never prompts when it was not given a terminal, and never guesses in place of a prompt: a
missing answer with nowhere to ask is a refusal, not a default.  Exit `3` is the one an agent
loops on -- the documents still hold placeholders, and the receipt lists them by file and line.
Write them, run again.

Every step is separately runnable and is run here in the only order that works.  Re-running is
safe: the version is set to what you asked for, document sections are kept where they exist, and
the gates hold no state.  So a stopped run is resumed by repeating it.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import release as release_module  # noqa: E402
import release_docs  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

EXIT_OK = 0
EXIT_STOPPED = 2
EXIT_DOCUMENTS_OPEN = 3  # the one an agent is expected to act on and retry


class Stopped(RuntimeError):
    """A step refused, in words that name the fix."""


class DocumentsOpen(RuntimeError):
    """The documents exist and still say TODO.  Separate because the answer is different."""

    def __init__(self, markers: tuple[str, ...]) -> None:
        super().__init__(f"{len(markers)} release document placeholder(s) still open")
        self.markers = markers


class Run:
    """Carries the receipt, and decides whether anything may be printed as prose."""

    def __init__(self, version: str, *, as_json: bool) -> None:
        self.version = version
        self.as_json = as_json
        self.steps: list[dict[str, object]] = []

    def say(self, line: str = "") -> None:
        if not self.as_json:
            print(line, flush=True)

    def step(self, name: str, status: str, **extra: object) -> None:
        self.steps.append({"name": name, "status": status, **extra})

    def receipt(self, status: str, **extra: object) -> dict[str, object]:
        return {"version": self.version, "status": status, "steps": self.steps, **extra}


def _shell(run: Run, name: str, *command: str) -> None:
    run.say(f"\n==> {name}")
    # Output goes to this process's own streams, so a person watches it happen.  Under --json it
    # goes to stderr, leaving stdout holding exactly one document.
    where = subprocess.DEVNULL if run.as_json else None
    completed = subprocess.run(
        (sys.executable, *command), cwd=ROOT, stdout=where, stderr=None if run.as_json else None
    )
    if completed.returncode:
        run.step(name, "failed")
        raise Stopped(f"{name} failed")
    run.step(name, "done")


def _checklist(run: Run, registry: Path | None) -> None:
    """The eleven checks, minus the two that cannot be true yet.

    A clean worktree and a commit already in `origin/main` are exactly what a release must prove
    and exactly what is false while you are still writing it.  Run as-is, every local run ends in
    two failures that mean nothing -- and two failures that mean nothing are how people learn to
    read past a red line.

    So they are deferred here and enforced where the answer is meaningful: `cut_release.py` proves
    both before it writes anything, from `main`, on a clean checkout.  Nothing is dropped.
    """

    run.say("\n==> run the release checklist")
    receipt = release_module.check_release(ROOT, registry, require_clean=False, require_main=False)
    for check in receipt["checks"]:
        state = "passed" if check["passed"] else ("skipped" if check["skipped"] else "failed")
        run.say(f"  {check['name']}: {state}")
    for diagnostic in receipt["diagnostics"]:
        run.say(f"  {diagnostic['code']}: {diagnostic['message']}")
    if receipt["status"] != "passed":
        run.step("release checklist", "failed", diagnostics=receipt["diagnostics"])
        raise Stopped("the release checklist failed")
    run.step("release checklist", "done")
    run.say(
        "  (the worktree being clean and the commit being in origin/main are checked by the\n"
        "   button, where they can be true; everything else is green here)"
    )


def prepare(run: Run, summary: str | None, registry: Path | None) -> None:
    version = run.version

    # The version, in the three files it lives in and the three that only quote it.
    _shell(run, f"set the version to {version}", "scripts/version.py", "set", version, "--write")

    # The four documents.  Headings written here; the prose is the part no command can write.
    arguments = ["scripts/release_docs.py", version]
    if summary is not None:
        arguments += ["--summary", summary]
    _shell(run, "put the release documents in place", *arguments)

    markers = release_docs.open_markers(version, ROOT)
    if markers:
        run.step("release documents", "open", placeholders=list(markers))
        raise DocumentsOpen(markers)
    run.step("release documents", "done")

    # Gates before checklist: a checklist run over code that does not import tells you about the
    # registry when the answer is a missing module.
    _shell(run, "run the ten quality gates", "scripts/quality.py")
    _checklist(run, registry)


def _ask(question: str) -> str:
    """Ask, but only where there is someone to ask."""

    if not sys.stdin.isatty():
        raise Stopped(f"{question}\nNothing to read an answer from: pass it as an argument.")
    print(f"\n{question}")
    try:
        return input("> ").strip()
    except EOFError:
        return ""


def _next_actions(version: str) -> tuple[str, ...]:
    return (
        f"git checkout -b release/{version} && git add -A && "
        f'git commit -m "AART {version}" && git push -u origin HEAD',
        "open the pull request and merge it to main",
        f"Actions -> cut release -> Run workflow -> {version}",
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version", nargs="?", help="the version to prepare; asked for if omitted")
    parser.add_argument("--summary", help="the one-line headline; given, it is not asked for")
    parser.add_argument("--registry", type=Path, help="checkout of the reference registry")
    parser.add_argument(
        "--json",
        action="store_true",
        help="print one receipt on stdout and nothing else; never prompts",
    )
    arguments = parser.parse_args(argv[1:])

    try:
        version = (arguments.version or _ask("Which version? (for example 2.8.6)")).strip()
        version = version.lstrip("v")
        if not version:
            raise Stopped("no version given")
        run = Run(version, as_json=arguments.json)
        prepare(run, arguments.summary, arguments.registry)
    except DocumentsOpen as error:
        run.say("\nStill to write:")
        for line in error.markers:
            run.say(f"  {line}")
        run.say(
            "\nThese are what someone reads to decide whether to upgrade, and the release refuses\n"
            f"to cut while one stands. Write them, then run this again:\n"
            f"  python scripts/prepare_release.py {version}"
        )
        if arguments.json:
            print(json.dumps(run.receipt("documents-open", placeholders=list(error.markers))))
        return EXIT_DOCUMENTS_OPEN
    except Stopped as error:
        if arguments.json:
            payload = run.receipt("stopped", reason=str(error)) if "run" in dir() else {}
            print(json.dumps(payload))
        else:
            print(f"\nstopped: {error}", file=sys.stderr)
            print("Nothing written was undone; fix it and run this again.", file=sys.stderr)
        return EXIT_STOPPED

    actions = _next_actions(version)
    if arguments.json:
        print(json.dumps(run.receipt("prepared", next_actions=list(actions))))
    else:
        print(f"\n{version} is prepared. Three things left, and none of them is a gate:")
        for number, action in enumerate(actions, start=1):
            print(f"  {number}. {action}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
