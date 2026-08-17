#!/usr/bin/env python3
"""Author a collection in a registry you maintain, out of artifacts that are already in it.

    scripts/collection_new.py platform-baseline --source . --summary "What every repo here gets."

With no `--include`, it walks the registry's artifacts one at a time and asks about each. With
`--include`, it takes your list and asks nothing. Either way it writes `collections/<name>.json`,
has `aart` parse it without changing anything, and tells you the commands that publish it.

A collection is the shipped name for a group of artifacts a colleague installs in one command:

    aart marketplace install <source>/collection/<name> --profile tabnine --yes

Re-running with a name that already exists edits that collection: its current members come back
pre-selected, so adding one artifact is a run through with one answer changed.

This is `AD-07`'s stopgap. The real thing is a maintainer-mode verb in the CLI and a flow in the
TUI; a script in `scripts/` is what stands in until that exists. Its only dependency is `aart`,
and it only runs it to validate what it wrote.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)")
ARTIFACT_TYPES = ("skill", "guideline", "mcp", "hook", "memory")
SCHEMA_VERSION = 1


def die(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def read_json(path: Path) -> dict:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        die(f"cannot read {path}: {error}")
    if not isinstance(loaded, dict):
        die(f"{path} is not a JSON object")
    return loaded


def artifact_roots(registry: Path) -> tuple[list[str], str]:
    """Where this registry keeps artifacts and collections, as it declares them itself."""

    source = read_json(registry / "aart-source.json")
    roots = source.get("artifact_roots") or ["artifacts"]
    collections = source.get("collection_roots") or []
    if not collections:
        die(
            "this registry declares no `collection_roots` in aart-source.json; add "
            '`"collection_roots": ["collections"]` to it — a collection outside a declared root '
            "is a file the compiler never reads"
        )
    return list(roots), collections[0]


def installed_artifacts(registry: Path, roots: list[str]) -> list[dict]:
    """Every artifact the registry holds, read from the manifests rather than from the paths."""

    found: list[dict] = []
    for root in roots:
        for kind in ARTIFACT_TYPES:
            directory = registry / root / kind
            if not directory.is_dir():
                continue
            for package in sorted(path for path in directory.iterdir() if path.is_dir()):
                manifest = package / "artifact.json"
                if not manifest.is_file():
                    continue
                data = read_json(manifest)
                found.append(
                    {
                        "type": data.get("type", kind),
                        "name": data.get("name", package.name),
                        "version": data.get("version", ""),
                        "summary": data.get("summary", ""),
                        "vendored": (package / "provenance.json").is_file(),
                    }
                )
    found.sort(key=lambda item: (item["type"], item["name"]))
    return found


def next_major(version: str) -> str | None:
    found = SEMVER_RE.match(version)
    return f"{int(found.group(1)) + 1}.0.0" if found else None


def selector(item: dict, previous: dict | None, *, pin: bool) -> dict:
    """One member of a collection. A version bound is written only when you asked for one.

    Pinning says *this collection means these versions*, which is what you want when the collection
    is a company baseline. Leaving it out says *whatever the registry holds*, which is what you want
    when the collection is a topic. Neither is the safe default, so the flag has to be explicit.
    """

    entry: dict = {"type": item["type"], "name": item["name"]}
    if pin:
        ceiling = next_major(item["version"])
        if ceiling is not None:
            entry["version"] = {"min_inclusive": item["version"], "max_exclusive": ceiling}
    elif isinstance(previous, dict) and isinstance(previous.get("version"), dict):
        entry["version"] = previous["version"]
    return entry


def existing_members(path: Path) -> tuple[dict[str, dict], list[str], str]:
    """What the collection says today, keyed by coordinate, so an edit does not silently rewrite it.

    The selectors come back whole rather than as names. Re-running without `--pin` should leave a
    pinned member pinned: unpinning a company baseline is a decision, and a decision nobody made is
    not one the script gets to make on a re-run.
    """

    if not path.is_file():
        return {}, [], ""
    data = read_json(path)
    members = {
        f"{item.get('type')}/{item.get('name')}": item
        for item in data.get("artifacts", [])
        if isinstance(item, dict)
    }
    nested = [name for name in data.get("collections", []) if isinstance(name, str)]
    return members, nested, str(data.get("summary", ""))


def choose(artifacts: list[dict], preselected: dict[str, dict]) -> list[dict]:
    print(f"{len(artifacts)} artifacts in this registry. [y]es  [n]o  [q]uit\n")
    kept: list[dict] = []
    for position, item in enumerate(artifacts, 1):
        coordinate = f"{item['type']}/{item['name']}"
        already = " (already a member)" if coordinate in preselected else ""
        origin = "vendored" if item["vendored"] else "native"
        print(f"({position}/{len(artifacts)}) {coordinate} {item['version']} [{origin}]{already}")
        if item["summary"]:
            print(f"    {item['summary']}")
        default = "Y/n" if coordinate in preselected else "y/N"
        answer = input(f"    include? [{default}] ").strip().lower()
        if answer in {"q", "quit"}:
            break
        if answer in {"y", "yes"} or (answer == "" and coordinate in preselected):
            kept.append(item)
        print()
    return kept


def resolve_includes(artifacts: list[dict], includes: list[str]) -> list[dict]:
    known = {f"{item['type']}/{item['name']}": item for item in artifacts}
    chosen: list[dict] = []
    for coordinate in includes:
        if coordinate not in known:
            die(
                f"{coordinate} is not in this registry; available: "
                + ", ".join(sorted(known)[:8])
                + (" …" if len(known) > 8 else "")
            )
        chosen.append(known[coordinate])
    return chosen


def check(aart: str, registry: Path) -> tuple[bool, list[str]]:
    """Ask `aart` what it thinks of the file just written, and say which complaints matter.

    `registry validate` is the only command that rejects a bad collection at this point —
    `registry lock` accepts one it should not, which is `AD-10`. But validate also compares the
    compiled index against the sources, and a collection authored a second ago has deliberately
    invalidated exactly that. Those three complaints are the expected state, not a problem, so they
    are named here and separated out. Anything else validate says is about the collection.
    """

    expected = (
        "compiled index collections differ from source",
        "compiled index does not match registry inputs",
        "registry lock does not match deterministic registry inputs",
    )
    result = subprocess.run(
        [aart, "registry", "validate", "--source", str(registry)], text=True, capture_output=True
    )
    errors = [
        line.strip()[len("error: ") :]
        for line in (result.stdout + result.stderr).splitlines()
        if line.strip().startswith("error: ")
    ]
    real = [error for error in errors if error not in expected]
    if not real:
        return True, [
            "the collection parses and every member resolves",
            "the index is stale until you lock and build, which is what the next step is for",
        ]
    return False, [
        "the collection has a problem, and it was still written so you can fix it in place:",
        *(f"  {error}" for error in real),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="collection_new.py",
        description="Author a collection from artifacts already in a registry you maintain.",
    )
    parser.add_argument("name", help="collection name, a lowercase slug")
    parser.add_argument("--source", default=".", help="registry checkout (default: .)")
    parser.add_argument("--summary", default=None, help="one line; asked for if omitted")
    parser.add_argument(
        "--include",
        action="append",
        default=[],
        metavar="TYPE/NAME",
        help="member to include; repeatable. Given at all, nothing is asked",
    )
    parser.add_argument(
        "--nest",
        action="append",
        default=[],
        metavar="COLLECTION",
        help="another collection in this registry to include whole; repeatable",
    )
    parser.add_argument(
        "--pin",
        action="store_true",
        help="bound each member to its current version up to the next major",
    )
    parser.add_argument("--aart", default="aart", help="the aart executable used to validate")
    args = parser.parse_args(argv)

    if SLUG_RE.fullmatch(args.name) is None:
        die("a collection name must be lowercase words joined by single hyphens")
    registry = Path(args.source).expanduser().resolve()
    if not (registry / "aart-source.json").is_file():
        die(f"{registry} is not a registry checkout: no aart-source.json")

    roots, collection_root = artifact_roots(registry)
    artifacts = installed_artifacts(registry, roots)
    if not artifacts:
        die("this registry holds no artifacts yet; vendor or scaffold one first")

    target = registry / collection_root / f"{args.name}.json"
    preselected, nested_before, summary_before = existing_members(target)
    if preselected:
        print(f"{args.name} exists with {len(preselected)} members; they come back pre-selected.\n")

    chosen = (
        resolve_includes(artifacts, args.include)
        if args.include
        else choose(artifacts, preselected)
    )
    nested = args.nest or nested_before
    if args.name in nested:
        die("a collection must not reference itself")
    if not chosen and not nested:
        die("a collection must contain at least one member; nothing was selected")

    summary = args.summary or summary_before
    if not summary:
        summary = input("summary (one line): ").strip()
    if not summary:
        die("a collection needs a summary; it is what a colleague reads in `marketplace list`")

    document: dict = {
        "schema_version": SCHEMA_VERSION,
        "name": args.name,
        "summary": " ".join(summary.split()),
        "artifacts": [
            selector(item, preselected.get(f"{item['type']}/{item['name']}"), pin=args.pin)
            for item in chosen
        ],
    }
    if nested:
        document["collections"] = sorted(nested)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    plural = "" if len(chosen) == 1 else "s"
    print(f"\nwrote {target.relative_to(registry)} with {len(chosen)} artifact{plural}", end="")
    print(f" and {len(nested)} nested" if nested else "")

    print("\nchecking what was written:")
    ok, lines = check(args.aart, registry)
    for line in lines:
        print(f"  {line}")
    if not ok:
        return 1
    print("\nnext:")
    print(f"  aart registry lock --source {args.source} --yes")
    print("  git add -A && git commit -m 'add the collection'")
    print(f"  aart registry build --source {args.source} --yes")
    print("  git add -A && git commit -m 'rebuild the index'")
    print("\nthen a colleague installs the whole thing with one command:")
    source_id = read_json(registry / "aart-source.json").get("source_id", "<source>")
    print(f"  aart marketplace install {source_id}/collection/{args.name} --profile tabnine --yes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
