#!/usr/bin/env python3
"""Find vendoring candidates in a repository that knows nothing about AART.

Three steps, three commands, and a JSON manifest between them:

    scripts/vendor_scan.py scan https://ghe.example/team/tools.git --out candidates.json
    scripts/vendor_scan.py review candidates.json
    scripts/vendor_scan.py vendor candidates.json --source /path/to/registry

`scan` clones the repository read-only and reports what looks like an artifact. `review` asks about
each candidate one at a time and records your answer. `vendor` runs `aart registry vendor` for the
ones you kept — the real command, with its real review and its three checks, once per artifact.

This is `AD-08`'s stopgap, deliberately: an orchestration layer over `registry vendor`, never a
replacement for it, which is the only shape `DESIGN-registry-vendoring.md` §10 leaves open for batch
discovery. It decides nothing. It guesses no version. It holds no credentials — `git` and `aart` are
the only programs it runs, and the only dependencies it has.

**The repositories this is for do not speak AART**, so the scan reports two different things.

*Candidates* are directories `registry vendor` can take today, judged by the payload rules
`protocol/native_tree.py` enforces at compile time:

    skill      a directory holding SKILL.md
    guideline  a directory holding exactly one file, and that file is Markdown
    mcp        a directory holding mcp.json
    hook       a directory holding hook.json with non-empty name and command

*Hints* are the rest: material that is plainly an artifact to a human and cannot be vendored as it
stands, because `vendor --path` takes a directory and the payload rules are strict. A hint names the
work you would have to do, and the scan never turns one into a command that would fail. In a foreign
repository, hints are where MCP servers and hooks nearly always land: `mcp.json` and `hook.json` are
AART's own payload names, and nobody outside AART writes them.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
FRONT_MATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)
DESCRIPTION_RE = re.compile(r"^description\s*:\s*(.+?)\s*$", re.MULTILINE)
SKIP_DIRS = frozenset({".git", ".github", "node_modules", "__pycache__", ".venv", "venv", "dist"})
# Directory names that mean "guidance for an agent" in the wild. Deliberately short: a wider list
# turns every `docs/` tree into a wall of hints and buries the ones worth acting on.
GUIDANCE_DIRS = frozenset({"guideline", "guidelines", "rules", "conventions", "policies"})
MCP_FILES = frozenset({".mcp.json", "mcp_servers.json", "mcp-servers.json", "mcp.config.json"})
HOOK_SUFFIXES = frozenset({".sh", ".py", ".js", ".ts"})
# File stems that name a document's place rather than its subject, so they make poor artifact names.
GENERIC_STEMS = frozenset({"readme", "index", "guide", "notes", "overview", "contributing"})
DEFAULT_VERSION = "1.0.0"


@dataclass
class Candidate:
    """One directory that looks like an artifact, and what it would be vendored as."""

    type: str
    name: str
    path: str
    summary: str
    version: str = DEFAULT_VERSION
    # None until `review` has run: the manifest records that nobody has decided yet, which is not
    # the same as a no.
    selected: bool | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class Hint:
    """Material a human would call an artifact that `vendor` cannot take as it stands."""

    path: str
    looks_like: str
    why_not: str
    what_to_do: str


def run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True)


def die(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def slugify(raw: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    return re.sub(r"-{2,}", "-", slug)


def first_line(text: str, limit: int = 160) -> str:
    """A summary AART will accept: one line, collapsed whitespace, never empty."""

    line = " ".join(text.split())
    return line[: limit - 1] + "…" if len(line) > limit else line


def summarize(document: Path, fallback: str) -> str:
    """Read a one-line summary out of a Markdown document without inventing one.

    Front matter `description` first, because that is what a skill actually declares; then the first
    paragraph that is not a heading or a fence; then the fallback. The summary is a claim your
    registry publishes, so `review` shows it and lets you replace it before anything is written.
    """

    try:
        text = document.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return fallback
    front = FRONT_MATTER_RE.match(text)
    if front is not None:
        found = DESCRIPTION_RE.search(front.group(1))
        if found is not None:
            return first_line(found.group(1).strip().strip("\"'"))
        text = text[front.end() :]
    for block in text.split("\n\n"):
        stripped = block.strip()
        if stripped and not stripped.startswith(("#", "```", "---", "<!--")):
            return first_line(stripped)
    return fallback


def payload_files(directory: Path) -> list[Path]:
    return [path for path in sorted(directory.rglob("*")) if path.is_file()]


def artifact_name(directory: Path) -> tuple[str, list[str]]:
    raw = directory.name
    if SLUG_RE.match(raw):
        return raw, []
    proposed = slugify(raw)
    return proposed, [f"directory name {raw!r} is not a slug; proposing {proposed!r}"]


def classify(directory: Path, root: Path) -> Candidate | None:
    """Decide whether one directory is vendorable, by AART's own payload rules."""

    relative = directory.relative_to(root).as_posix()
    name, notes = artifact_name(directory)
    if not name:
        return None

    if (directory / "SKILL.md").is_file():
        summary = summarize(directory / "SKILL.md", f"Skill {name} vendored from upstream.")
        return Candidate("skill", name, relative, summary, notes=notes)

    if (directory / "mcp.json").is_file():
        return Candidate(
            "mcp", name, relative, f"MCP server {name} vendored from upstream.", notes=notes
        )

    if (directory / "hook.json").is_file():
        try:
            hook = json.loads((directory / "hook.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if isinstance(hook, dict) and hook.get("name") and hook.get("command"):
            return Candidate(
                "hook", name, relative, f"Hook {name} vendored from upstream.", notes=notes
            )
        return None

    files = payload_files(directory)
    markdown = [path for path in files if path.suffix == ".md"]
    if len(files) == 1 and len(markdown) == 1:
        # The directory holding a lone guideline is usually named for where it sits rather than for
        # what it says — `docs/windows/polyglot-hooks.md`, `guidelines/residuality-theory.md`. The
        # document names the subject, so it names the artifact better; `review` renames either way.
        stem = markdown[0].stem
        if SLUG_RE.match(stem) and stem not in GENERIC_STEMS:
            name, notes = stem, []
        summary = summarize(markdown[0], f"Guideline {name} vendored from upstream.")
        notes = notes + ["a `memory` artifact has the same payload shape; change the type by hand"]
        return Candidate("guideline", name, relative, summary, notes=notes)
    return None


def guidance_hints(directory: Path, root: Path) -> list[Hint]:
    """Loose Markdown under a guidance-shaped directory: real material, not vendorable as it is."""

    documents = [path for path in sorted(directory.glob("*.md")) if path.is_file()]
    if len(documents) < 2:
        return []
    return [
        Hint(
            path=document.relative_to(root).as_posix(),
            looks_like="guideline",
            why_not=(
                f"`vendor --path` takes a directory, and this document shares "
                f"{directory.name}/ with {len(documents) - 1} others; a guideline payload must be "
                "exactly one Markdown file"
            ),
            what_to_do=(
                "ask upstream to give each document its own directory, or author the guideline in "
                "your registry with `aart registry scaffold guideline` and lose the provenance link"
            ),
        )
        for document in documents
    ]


def foreign_mcp_hint(path: Path, root: Path) -> Hint:
    return Hint(
        path=path.relative_to(root).as_posix(),
        looks_like="mcp",
        why_not=(
            "an `mcp` payload must be a directory holding `mcp.json`; this is a harness "
            "configuration file in the upstream's own layout"
        ),
        what_to_do=(
            "vendor the server's own subtree if it has one, then author `payload/mcp.json` beside "
            "the copy — `vendor` reviews and assesses authored wrapper files with the package"
        ),
    )


def foreign_hook_hint(directory: Path, root: Path, scripts: int) -> Hint:
    return Hint(
        path=directory.relative_to(root).as_posix(),
        looks_like="hook",
        why_not=(
            f"a `hook` payload must be a directory holding `hook.json` with non-empty name and "
            f"command; this holds {scripts} script{'' if scripts == 1 else 's'} and no such file"
        ),
        what_to_do=(
            "vendor the directory with an authored `payload/hook.json` naming the script to run, "
            "one artifact per hook"
        ),
    )


def scan_tree(root: Path) -> tuple[list[Candidate], list[Hint]]:
    candidates: list[Candidate] = []
    hints: list[Hint] = []
    stack = [root]
    while stack:
        directory = stack.pop()
        if directory != root:
            candidate = classify(directory, root)
            if candidate is not None:
                candidates.append(candidate)
                continue  # an artifact is not searched for smaller artifacts inside it
            if directory.name.lower() in GUIDANCE_DIRS:
                hints.extend(guidance_hints(directory, root))
            if directory.name.lower() == "hooks":
                scripts = [
                    path
                    for path in directory.iterdir()
                    if path.is_file() and path.suffix in HOOK_SUFFIXES
                ]
                if scripts:
                    hints.append(foreign_hook_hint(directory, root, len(scripts)))
        for child in sorted(directory.iterdir()):
            if child.is_file() and child.name in MCP_FILES:
                hints.append(foreign_mcp_hint(child, root))
            if child.is_dir() and not child.is_symlink() and child.name not in SKIP_DIRS:
                stack.append(child)
    candidates.sort(key=lambda item: (item.type, item.name))
    hints.sort(key=lambda item: (item.looks_like, item.path))
    return candidates, hints


def acquire(location: str, ref: str, into: Path) -> Path:
    """Get a read-only copy of the repository. A path you already have is read where it is."""

    local = Path(location).expanduser()
    if local.is_dir():
        return local
    checkout = into / "upstream"
    print(f"cloning {location} at {ref} …", file=sys.stderr)
    cloned = run(
        ["git", "clone", "--quiet", "--depth", "1", "--branch", ref, location, str(checkout)]
    )
    if cloned.returncode != 0:
        die(f"git clone failed: {cloned.stderr.strip() or cloned.stdout.strip()}")
    return checkout


def vendor_url(location: str, override: str | None) -> str:
    """Work out the URL the vendoring will be pinned to, and refuse a local path early.

    `registry vendor --url` takes credential-free HTTPS or SSH only, so a scan of a checkout you
    already have on disk has to be told where that checkout came from. Asking here costs one flag;
    finding out later costs a failed run over every selected artifact.
    """

    if override:
        return override
    if not Path(location).expanduser().is_dir():
        return location
    remote = run(["git", "remote", "get-url", "origin"], cwd=Path(location).expanduser())
    if remote.returncode == 0 and remote.stdout.strip().startswith(("https://", "git@", "ssh://")):
        found = remote.stdout.strip()
        print(f"scanning a local checkout; vendoring will pin to its origin: {found}")
        print("  the scan reads your working tree, the vendoring copies --ref from the remote")
        return found
    die(
        f"{location} is a local path and its origin is not a usable Git URL; "
        "pass --url with the HTTPS or SSH address the vendoring should pin to"
    )
    raise AssertionError("unreachable")


def command_scan(args: argparse.Namespace) -> int:
    url = vendor_url(args.location, args.url)
    workspace = Path(tempfile.mkdtemp(prefix="vendor-scan-"))
    try:
        root = acquire(args.location, args.ref, workspace)
        candidates, hints = scan_tree(root)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    manifest = {
        "url": url,
        "ref": args.ref,
        "candidates": [asdict(item) for item in candidates],
        "hints": [asdict(item) for item in hints],
    }
    Path(args.out).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    by_type: dict[str, int] = {}
    for item in candidates:
        by_type[item.type] = by_type.get(item.type, 0) + 1
    counted = ", ".join(f"{count} {kind}" for kind, count in sorted(by_type.items())) or "nothing"
    print(f"vendorable now: {len(candidates)} ({counted})")

    if hints:
        by_kind: dict[str, int] = {}
        for hint in hints:
            by_kind[hint.looks_like] = by_kind.get(hint.looks_like, 0) + 1
        shape = ", ".join(f"{count} {kind}" for kind, count in sorted(by_kind.items()))
        print(f"needs work first: {len(hints)} ({shape})")
        for hint in hints[: args.show_hints]:
            print(f"  {hint.path} — looks like a {hint.looks_like}")
            print(f"      why not: {hint.why_not}")
            print(f"      to fix:  {hint.what_to_do}")
        if len(hints) > args.show_hints:
            print(f"  … and {len(hints) - args.show_hints} more, all of them in {args.out}")

    print(f"\nwrote {args.out}")
    print(f"next: {sys.argv[0]} review {args.out}")
    return 0


def load(path: str) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        die(f"cannot read manifest {path}: {error}")
    raise AssertionError("unreachable")


def save(path: str, manifest: dict) -> None:
    Path(path).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def command_review(args: argparse.Namespace) -> int:
    manifest = load(args.manifest)
    entries = manifest["candidates"]
    pending = [item for item in entries if item.get("selected") is None or args.again]
    if not pending:
        print("every candidate already has an answer; re-run with --again to revisit them")
        return 0

    print(
        f"{len(pending)} candidates. "
        "[y]es  [n]o  [r]ename  [e]dit summary  [v]ersion  [s]kip  [q]uit\n"
    )
    for position, item in enumerate(pending, 1):
        while True:
            print(f"({position}/{len(pending)}) {item['type']}/{item['name']}")
            print(f"    path:    {item['path']}")
            print(f"    summary: {item['summary']}")
            print(f"    version: {item['version']}")
            for note in item.get("notes", ()):
                print(f"    note:    {note}")
            answer = input("    vendor this? ").strip().lower()
            if answer in {"y", "yes"}:
                item["selected"] = True
                break
            if answer in {"n", "no"}:
                item["selected"] = False
                break
            if answer in {"s", "skip", ""}:
                break
            if answer in {"q", "quit"}:
                save(args.manifest, manifest)
                print(f"stopped; the answers so far are in {args.manifest}")
                return 0
            if answer in {"r", "rename"}:
                replacement = input("    name: ").strip()
                if replacement and SLUG_RE.match(replacement):
                    item["name"] = replacement
                elif replacement:
                    print("    a name must be lowercase words joined by single hyphens")
                continue
            if answer in {"e", "edit"}:
                replacement = input("    summary: ").strip()
                if replacement:
                    item["summary"] = first_line(replacement)
                continue
            if answer in {"v", "version"}:
                replacement = input("    version: ").strip()
                if replacement:
                    item["version"] = replacement
                continue
            print("    answer y, n, r, e, v, s or q")
        print()

    save(args.manifest, manifest)
    kept = sum(1 for item in entries if item.get("selected"))
    print(f"{kept} selected of {len(entries)}; wrote {args.manifest}")
    print(f"next: {sys.argv[0]} vendor {args.manifest} --source /path/to/registry")
    return 0


def command_vendor(args: argparse.Namespace) -> int:
    manifest = load(args.manifest)
    registry = Path(args.source).expanduser().resolve()
    if not (registry / "aart-registry.json").is_file():
        die(f"{registry} is not a registry checkout: no aart-registry.json")
    selected = [item for item in manifest["candidates"] if item.get("selected")]
    if not selected:
        die(f"nothing is selected in {args.manifest}; run `review` first")

    failures = 0
    for position, item in enumerate(selected, 1):
        label = f"({position}/{len(selected)}) {item['type']}/{item['name']}"
        target = registry / "artifacts" / item["type"] / item["name"]
        if target.exists() and not args.revendor:
            print(f"{label}: already in the registry, skipping — `aart registry revendor` moves it")
            continue
        command = [
            args.aart,
            "registry",
            "vendor",
            item["type"],
            item["name"],
            "--source",
            str(registry),
            "--url",
            manifest["url"],
            "--ref",
            manifest["ref"],
            "--path",
            item["path"],
            "--artifact-version",
            item["version"],
            "--summary",
            item["summary"],
            "--platform",
            args.platform,
            "--review-policy",
            args.review_policy,
        ]
        for profile in args.profile:
            command += ["--profile", profile]
        if args.license:
            command += ["--license", args.license]
        if args.yes:
            command.append("--yes")
        # `aart` writes straight to the terminal, so this must be flushed or every label arrives
        # after every report and no line of output belongs to any artifact.
        print(label, flush=True)
        completed = subprocess.run(command, text=True)
        if completed.returncode != 0:
            failures += 1
            print(f"    failed with exit {completed.returncode}; continuing", file=sys.stderr)

    if failures:
        print(f"\n{failures} of {len(selected)} failed", file=sys.stderr)
        return 1
    if not args.yes:
        print("\nReviewed only. Re-run with --yes to finalize every one of them.")
        return 0
    print(
        "\nnext: aart registry lock --source . --yes, commit the lock, "
        "then aart registry build --source . --yes"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="vendor_scan.py",
        description="Find vendoring candidates in a foreign repository, then vendor the keepers.",
    )
    actions = parser.add_subparsers(dest="action", required=True)

    scan = actions.add_parser("scan", help="clone a repository and list candidate artifacts")
    scan.add_argument("location", help="Git URL, or a path to a checkout you already have")
    scan.add_argument("--ref", default="main", help="Git ref to clone (default: main)")
    scan.add_argument("--url", default=None, help="URL to pin to, when scanning a local checkout")
    scan.add_argument("--out", default="candidates.json", help="manifest to write")
    scan.add_argument("--show-hints", type=int, default=5, metavar="N")
    scan.set_defaults(handler=command_scan)

    review = actions.add_parser("review", help="answer yes or no to each candidate")
    review.add_argument("manifest")
    review.add_argument("--again", action="store_true", help="revisit candidates already answered")
    review.set_defaults(handler=command_review)

    vendor = actions.add_parser("vendor", help="run `aart registry vendor` for each keeper")
    vendor.add_argument("manifest")
    vendor.add_argument("--source", required=True, help="registry checkout to vendor into")
    vendor.add_argument("--profile", action="append", default=None, metavar="P")
    vendor.add_argument("--platform", default="darwin")
    vendor.add_argument("--license", default=None, metavar="SPDX")
    vendor.add_argument("--review-policy", default="manual-review-v1")
    vendor.add_argument("--aart", default="aart", help="the aart executable to run")
    vendor.add_argument("--yes", action="store_true", help="finalize instead of reviewing")
    vendor.add_argument("--revendor", action="store_true", help="do not skip artifacts already in")
    vendor.set_defaults(handler=command_vendor)

    args = parser.parse_args(argv)
    if args.action == "vendor" and not args.profile:
        args.profile = ["tabnine"]
    handler = args.handler
    return int(handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
