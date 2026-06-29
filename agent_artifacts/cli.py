"""CLI wiring (WP-19): argparse subcommands -> Request -> command dispatch -> exit code.

One core, two skins (docs/design/DESIGN.md §13). This module is the flag-mode skin: it parses ``argv``
into the frozen :class:`~agent_artifacts.model.Request`, dispatches to the matching command's
``run(request) -> int`` (the commands already map their `Result`s to the §7 exit-code
vocabulary via ``commands._common.exit_code``), and returns that code. A bare invocation on a
TTY launches the TUI (WP-20); otherwise it prints help.

WP-19 owns only the *wiring*: no decision logic lives here. argparse handles usage errors with
its own exit code ``2`` (== ``_common.USAGE``); ``--help`` exits ``0``.

Contract with WP-20: the TUI module exposes ``tui.run() -> int``. It is imported lazily so the
CLI works before that module exists.
"""

from __future__ import annotations

import argparse
import sys
from typing import Callable, Optional, Sequence, Tuple

from . import __version__
from .cli_rules import validate_flags
from .commands import check, install, status, uninstall, update, upgrade
from .commands import list as list_cmd
from .commands._common import OK
from .model import Request


def _run_upstream(request: Request) -> int:
    from .commands import upstream

    return upstream.run(request)


# Command name -> handler. Value-keyed dispatch, not a class hierarchy (docs/design/DESIGN.md §14).
DISPATCH: dict[str, Callable[[Request], int]] = {
    "list": list_cmd.run,
    "install": install.run,
    "status": status.run,
    "check": check.run,
    "update": update.run,
    "uninstall": uninstall.run,
    "upgrade": upgrade.run,
    "upstream": _run_upstream,
}

_ARTIFACT_TYPES = ("skill", "guideline", "mcp", "hook", "memory")
_MEMORY_MODES = ("replace", "prepend", "append", "skip")
_IMPORT_MODES = ("auto", "manifest", "heuristic")
_BUNDLE_MODES = ("append", "replace", "fail")


# --------------------------------------------------------------------------- #
# Parser construction                                                          #
# --------------------------------------------------------------------------- #
def _add_json(p: argparse.ArgumentParser) -> None:
    p.add_argument("--json", action="store_true", help="emit machine-readable JSON")


def _add_version(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--version",
        dest="version",
        metavar="REF",
        help="source git ref (branch/tag/SHA); defaults to main",
    )


def _add_selection(p: argparse.ArgumentParser, *, names: bool = True) -> None:
    """Artifact-selection flags shared by install/update/uninstall (and partly list)."""
    if names:
        p.add_argument("names", nargs="*", metavar="NAME", help="artifact name(s) to select")
    p.add_argument("--bundle", action="append", metavar="B", help="select a bundle (repeatable)")
    p.add_argument("--all", action="store_true", help="select every catalog artifact")


def _add_profile(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--profile",
        action="append",
        metavar="P[,P...]",
        help="target harness profile(s); comma-separated or repeated",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the full argparse parser mirroring docs/design/DESIGN.md §13."""
    parser = argparse.ArgumentParser(
        prog="agent-artifacts",
        description="Install a team's AI artifacts (skills, guidelines, MCP configs, hooks) "
        "into agentic harnesses.",
    )
    parser.add_argument("--version", action="version", version=f"agent-artifacts {__version__}")

    def _add_repo(p: argparse.ArgumentParser) -> None:
        p.add_argument("--repo", metavar="OWNER/NAME", help="source-of-truth GitHub repo")

    def _add_project(p: argparse.ArgumentParser) -> None:
        p.add_argument("--project", metavar="DIR", help="consumer project directory (default: current dir)")

    def _add_source(p: argparse.ArgumentParser, help_text: str) -> None:
        p.add_argument("--source", dest="source_dir", metavar="DIR", help=help_text)

    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    # list -------------------------------------------------------------------- #
    p = sub.add_parser("list", help="list catalog artifacts")
    _add_repo(p)
    _add_source(p, "read catalog from a local checkout (offline / air-gapped)")
    p.add_argument("--bundle", action="append", metavar="B", help="restrict to a bundle")
    p.add_argument(
        "--type", dest="type_filter", choices=_ARTIFACT_TYPES, help="restrict to an artifact type"
    )
    _add_version(p)
    _add_json(p)

    # install ----------------------------------------------------------------- #
    p = sub.add_parser("install", help="install artifacts into profiles")
    _add_repo(p)
    _add_project(p)
    _add_source(p, "install from a local checkout (offline / air-gapped)")
    _add_selection(p)
    _add_profile(p)
    _add_version(p)
    p.add_argument(
        "--memory-mode",
        dest="memory_mode",
        choices=_MEMORY_MODES,
        help="how an `memory` instruction file combines with an existing one "
        "(default: prepend); see docs/design/DESIGN-memory.md §3.2",
    )
    p.add_argument("--dry-run", action="store_true", help="print the plan; touch nothing")
    p.add_argument("--yes", action="store_true", help="assume yes (agent mode, no prompts)")
    p.add_argument(
        "--force", action="store_true", help="authorize overwrites and merge-entry collisions"
    )
    p.add_argument(
        "--link",
        action="store_true",
        help="symlink supported directory artifacts from a local source instead of copying",
    )
    _add_json(p)

    # status ------------------------------------------------------------------ #
    p = sub.add_parser(
        "status",
        help="show installed artifacts and on-disk drift (local, no network)",
    )
    _add_repo(p)
    _add_project(p)
    _add_json(p)

    # check ------------------------------------------------------------------- #
    p = sub.add_parser(
        "check", help="compare installed/CLI commit against the source (remote)"
    )
    _add_repo(p)
    _add_project(p)
    _add_version(p)
    _add_json(p)

    # update ------------------------------------------------------------------ #
    p = sub.add_parser("update", help="re-pull and re-apply installed artifacts")
    _add_repo(p)
    _add_project(p)
    _add_source(p, "update from a local checkout (offline / air-gapped)")
    p.add_argument("names", nargs="*", metavar="NAME", help="restrict to artifact name(s)")
    p.add_argument("--bundle", action="append", metavar="B", help="restrict to a bundle")
    _add_profile(p)
    p.add_argument(
        "--prune", action="store_true", help="remove installed entries no longer in the selection"
    )
    p.add_argument("--dry-run", action="store_true", help="print the plan; touch nothing")
    p.add_argument("--force", action="store_true", help="overwrite drift / merge collisions")
    p.add_argument("--yes", action="store_true", help="assume yes (agent mode, no prompts)")
    _add_json(p)

    # uninstall --------------------------------------------------------------- #
    p = sub.add_parser("uninstall", help="reverse installed files and merges")
    _add_project(p)
    _add_selection(p)
    _add_profile(p)
    p.add_argument("--dry-run", action="store_true", help="print the plan; touch nothing")
    p.add_argument("--yes", action="store_true", help="assume yes (agent mode, no prompts)")
    p.add_argument(
        "--force", action="store_true", help="remove merge entries even if locally modified"
    )
    _add_json(p)

    # upgrade ----------------------------------------------------------------- #
    p = sub.add_parser(
        "upgrade",
        help="reinstall the tool itself from the source (offline-capable)",
    )
    _add_repo(p)
    _add_version(p)
    p.add_argument(
        "--dry-run", action="store_true", help="print the pip invocation; install nothing"
    )

    # upstream ---------------------------------------------------------------- #
    p = sub.add_parser("upstream", help="maintain vendored artifact upstreams")
    up = p.add_subparsers(dest="upstream_action", metavar="ACTION", required=True)

    p_check = up.add_parser("check", help="check tracked upstream artifacts")
    _add_source(p_check, "catalog repository directory to maintain (default: current dir)")
    _add_selection(p_check)
    p_check.add_argument(
        "--type", dest="type_filter", choices=_ARTIFACT_TYPES, help="restrict to an artifact type"
    )
    _add_json(p_check)

    p_update = up.add_parser("update", help="update tracked upstream artifacts")
    _add_source(p_update, "catalog repository directory to maintain (default: current dir)")
    _add_selection(p_update)
    p_update.add_argument(
        "--type", dest="type_filter", choices=_ARTIFACT_TYPES, help="restrict to an artifact type"
    )
    p_update.add_argument("--dry-run", action="store_true", help="print the plan; touch nothing")
    p_update.add_argument("--force", action="store_true", help="overwrite local catalog drift")
    _add_json(p_update)

    p_add = up.add_parser(
        "add", help="adopt an upstream artifact from a GitHub URL"
    )
    _add_source(p_add, "catalog repository directory to maintain (default: current dir)")
    p_add.add_argument(
        "names", nargs=1, metavar="TYPE/NAME", help="artifact key, e.g. skill/grill-me"
    )
    p_add.add_argument(
        "url", metavar="URL", help="GitHub URL: a repo, or a /tree//blob deep link to the artifact"
    )
    p_add.add_argument(
        "--ref",
        dest="ref",
        metavar="REF",
        help="override the ref (needed when a branch name contains slashes)",
    )
    p_add.add_argument(
        "--path", dest="path", metavar="PATH", help="override the in-repo path to the artifact"
    )
    p_add.add_argument(
        "--force",
        action="store_true",
        help="overwrite an existing catalog destination / re-adopt a tracked key",
    )
    p_add.add_argument("--dry-run", action="store_true", help="print the plan; touch nothing")
    _add_json(p_add)

    p_scan = up.add_parser("scan", help="scan a GitHub repo for importable artifacts")
    _add_source(p_scan, "catalog repository directory to maintain (default: current dir)")
    p_scan.add_argument("url", metavar="URL", help="GitHub repo or /tree URL to scan")
    p_scan.add_argument(
        "--mode",
        dest="import_mode",
        choices=_IMPORT_MODES,
        default="auto",
        help="candidate discovery mode",
    )
    p_scan.add_argument("--ref", dest="ref", metavar="REF", help="override the ref to scan")
    p_scan.add_argument(
        "--path", dest="path", metavar="PATH", help="override the in-repo path to scan"
    )
    _add_json(p_scan)

    p_import = up.add_parser("import", help="batch-import artifacts from a GitHub repo")
    _add_source(p_import, "catalog repository directory to maintain (default: current dir)")
    p_import.add_argument("url", metavar="URL", help="GitHub repo or /tree URL to import from")
    p_import.add_argument(
        "--mode",
        dest="import_mode",
        choices=_IMPORT_MODES,
        default="auto",
        help="candidate discovery mode",
    )
    p_import.add_argument(
        "--select",
        action="append",
        metavar="TYPE/NAME[,TYPE/NAME...]",
        help="candidate(s) to import; defaults to non-ambiguous candidates",
    )
    p_import.add_argument("--bundle", action="append", metavar="B", help="create/update a bundle")
    p_import.add_argument(
        "--bundle-description",
        metavar="TEXT",
        help="description for a created/replaced import bundle",
    )
    p_import.add_argument(
        "--bundle-mode",
        choices=_BUNDLE_MODES,
        default="append",
        help="how to handle an existing bundle",
    )
    p_import.add_argument("--ref", dest="ref", metavar="REF", help="override the ref to import")
    p_import.add_argument(
        "--path", dest="path", metavar="PATH", help="override the in-repo path to import"
    )
    p_import.add_argument("--interactive", action="store_true", help="prompt for candidate selection")
    p_import.add_argument("--dry-run", action="store_true", help="print the plan; touch nothing")
    p_import.add_argument("--force", action="store_true", help="replace existing catalog entries")
    _add_json(p_import)

    return parser


# --------------------------------------------------------------------------- #
# argparse Namespace -> Request                                                #
# --------------------------------------------------------------------------- #
def _split_csv(values) -> Tuple[str, ...]:
    """Flatten a repeated, optionally comma-separated option into an ordered tuple.

    Accepts ``--profile a,b --profile c`` and ``--profile a --profile b`` alike.
    """
    if not values:
        return ()
    items = values if isinstance(values, list) else [values]
    out: list[str] = []
    for chunk in items:
        out.extend(part.strip() for part in str(chunk).split(",") if part.strip())
    return tuple(out)


def _to_request(args: argparse.Namespace) -> Request:
    """Map a parsed namespace to a frozen :class:`Request`.

    Uses ``getattr`` with defaults because each subparser defines only its own flags.
    """
    select = getattr(args, "select", None)
    return Request(
        command=args.command,
        names=_split_csv(select) if select is not None else tuple(getattr(args, "names", None) or ()),
        bundles=tuple(getattr(args, "bundle", None) or ()),
        profiles=_split_csv(getattr(args, "profile", None)),
        all=bool(getattr(args, "all", False)),
        version=getattr(args, "version", None),
        source_dir=getattr(args, "source_dir", None),
        repo=getattr(args, "repo", None),
        project=getattr(args, "project", None),
        type_filter=getattr(args, "type_filter", None),
        yes=bool(getattr(args, "yes", False)),
        force=bool(getattr(args, "force", False)),
        dry_run=bool(getattr(args, "dry_run", False)),
        json=bool(getattr(args, "json", False)),
        prune=bool(getattr(args, "prune", False)),
        install_mode="symlink" if bool(getattr(args, "link", False)) else "copy",
        memory_mode=getattr(args, "memory_mode", None),
        upstream_action=getattr(args, "upstream_action", None),
        url=getattr(args, "url", None),
        ref=getattr(args, "ref", None),
        path=getattr(args, "path", None),
        import_mode=getattr(args, "import_mode", None),
        bundle_mode=getattr(args, "bundle_mode", None),
        bundle_description=getattr(args, "bundle_description", None),
        interactive=bool(getattr(args, "interactive", False)),
    )


# --------------------------------------------------------------------------- #
# Entry point                                                                  #
# --------------------------------------------------------------------------- #
def _run_bare(parser: argparse.ArgumentParser, args: Optional[argparse.Namespace] = None) -> int:
    """Bare invocation (docs/design/DESIGN.md §13): launch the TUI on a TTY, else print help."""
    if sys.stdin.isatty() and sys.stdout.isatty():
        from . import tui  # WP-20: always present in the package.

        kwargs = {}
        if args:
            if getattr(args, "source_dir", None):
                kwargs["source_dir"] = args.source_dir
            if getattr(args, "repo", None):
                kwargs["repo"] = args.repo
            if getattr(args, "project", None):
                kwargs["project"] = args.project
        return int(tui.run(**kwargs))
    parser.print_help()
    return OK


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Parse ``argv``, dispatch to a command, and return its process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        return _run_bare(parser, args)
    request = _to_request(args)
    # Semantic flag-combination check (issue #4): argparse validates syntax; this rejects
    # combinations that argparse accepts but the core would silently mishandle (USAGE == 2).
    problem = validate_flags(request)
    if problem is not None:
        print(problem.reason, file=sys.stderr)
        return problem.code
    return DISPATCH[args.command](request)


if __name__ == "__main__":
    raise SystemExit(main())
