#!/usr/bin/env python3
"""Run a registry through lock, build, validate and audit, then commit what changed.

    scripts/registry_publish.py --source /path/to/registry          # show what would happen
    scripts/registry_publish.py --source /path/to/registry --yes    # do it and commit

Four `aart` commands in a fixed order, then one Git commit. The order is not arbitrary: `lock`
resolves the authored entries, `build` compiles the index from that lock, `validate` checks the
compiled output against the sources, and `audit` reports review, provenance and setup evidence.
Running them out of order produces errors that read like defects and are not.

Without `--yes` nothing is written and nothing is committed: `lock` and `build` run in their own
review mode, `validate` and `audit` are read-only anyway, and the files that *would* be committed
are listed. With `--yes` the same four run for real and the working tree is committed.

**It commits and it never pushes.** AART itself does neither — every maintainer command ends by
telling you to review the diff yourself — so a script that commits is a convenience the tool
deliberately withholds, and the file list printed before the commit is what makes it honest. Pushing
stays yours: it is the step that makes the change other people's problem.

This is `AD-14`'s stopgap. The real thing is a maintainer verb in the CLI and a flow in the TUI, and
`git` and `aart` remain the only programs run.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# In the order they must run. The flag says whether `--yes` turns the step into a mutation; the two
# read-only steps take no `--yes` at all and are run identically in both modes.
STEPS = (
    ("lock", True, "resolve the authored entries into aart.lock.json"),
    ("build", True, "compile aart.index.json from that lock"),
    ("validate", False, "check the compiled output against the sources"),
    ("audit", False, "report review, provenance, setup and security evidence"),
)


def die(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def git(registry: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(registry), *arguments], text=True, capture_output=True)


def pending(registry: Path) -> list[tuple[str, str]]:
    """Everything `git add -A` would stage, as (status, path), ignored files excluded."""

    # `--untracked-files=all` matters: the default collapses a new directory to one line, so a first
    # publish would print `artifacts/` where the maintainer asked to see every file being committed.
    result = git(registry, "status", "--porcelain", "--untracked-files=all")
    if result.returncode != 0:
        die(f"git status failed: {result.stderr.strip()}")
    changes: list[tuple[str, str]] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        status, _, path = line[:2], line[2], line[3:]
        changes.append((status.strip() or "??", path.strip('"')))
    return changes


def describe(registry: Path) -> str:
    """A commit subject that says what the registry now holds, read from the compiled index."""

    index = registry / "aart.index.json"
    if not index.is_file():
        return "Publish registry"
    try:
        data = json.loads(index.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "Publish registry"
    artifacts = len(data.get("artifacts", []))
    collections = len(data.get("collections", []))
    parts = [f"{artifacts} artifact{'' if artifacts == 1 else 's'}"]
    if collections:
        parts.append(f"{collections} collection{'' if collections == 1 else 's'}")
    return f"Publish registry: {', '.join(parts)}"


def run_step(aart: str, action: str, registry: Path, *, finalize: bool) -> int:
    command = [aart, "registry", action, "--source", str(registry)]
    if finalize:
        command.append("--yes")
    print(f"\n=== aart registry {action}{' --yes' if finalize else ''}", flush=True)
    return subprocess.run(command, text=True).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="registry_publish.py",
        description="lock, build, validate, audit, then commit — in that order.",
    )
    parser.add_argument("--source", default=".", help="registry checkout (default: .)")
    parser.add_argument("-m", "--message", default=None, help="commit subject; one is derived")
    parser.add_argument("--aart", default="aart", help="the aart executable to run")
    parser.add_argument("--yes", action="store_true", help="write and commit instead of previewing")
    parser.add_argument(
        "--allow-audit-failure",
        action="store_true",
        help="commit even when audit reports a finding; validate must still pass",
    )
    args = parser.parse_args(argv)

    registry = Path(args.source).expanduser().resolve()
    if not (registry / "aart-registry.json").is_file():
        die(f"{registry} is not a registry checkout: no aart-registry.json")
    if git(registry, "rev-parse", "--git-dir").returncode != 0:
        die(f"{registry} is not a Git repository; `git init` first")

    before = pending(registry)
    if before:
        print(f"{len(before)} paths are already modified before anything runs:")
        for status, path in before[:10]:
            print(f"  {status:>2}  {path}")
        if len(before) > 10:
            print(f"  … and {len(before) - 10} more")
        print("They will be part of the same commit. Stash anything unrelated first.\n")

    for action, mutating, why in STEPS:
        code = run_step(args.aart, action, registry, finalize=mutating and args.yes)
        if code == 0:
            continue
        if action == "build" and not args.yes:
            # In preview mode the lock on disk is whatever the last real run left, so `build` may
            # legitimately have nothing consistent to compile. That is not a failure of the
            # registry, and reporting it as one would train a maintainer to ignore this script.
            print("\n  build cannot be previewed until the lock is written; re-run with --yes")
            continue
        if action == "audit" and args.allow_audit_failure:
            print(
                "\n  audit reported a finding; continuing because --allow-audit-failure was given"
            )
            continue
        die(f"`aart registry {action}` failed with exit {code} — it was meant to {why}")

    changes = pending(registry)
    if not changes:
        print("\nnothing changed; there is nothing to commit")
        return 0

    print(
        f"\n=== {len(changes)} paths would be committed"
        if not args.yes
        else f"\n=== committing {len(changes)} paths"
    )
    for status, path in changes:
        print(f"  {status:>2}  {path}")

    subject = args.message or describe(registry)
    if not args.yes:
        print(f"\nsubject would be: {subject}")
        print("Reviewed only. Re-run with --yes to write the lock and index and commit them.")
        return 0

    if git(registry, "add", "-A").returncode != 0:
        die("git add failed")
    committed = git(registry, "commit", "-m", subject)
    if committed.returncode != 0:
        die(f"git commit failed: {committed.stderr.strip() or committed.stdout.strip()}")
    revision = git(registry, "rev-parse", "--short", "HEAD").stdout.strip()
    print(f"\ncommitted {revision}: {subject}")
    print("Not pushed — that step is yours.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
