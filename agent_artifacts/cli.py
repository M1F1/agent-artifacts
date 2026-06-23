"""CLI wiring (WP-19): argparse subcommands -> Request -> command dispatch -> exit code.

One core, two skins (DESIGN.md §13). This module is the flag-mode skin: it parses ``argv``
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
from .commands import check, install, status, uninstall, update, upgrade
from .commands import list as list_cmd
from .commands._common import OK
from .model import Request


def _run_upstream(request: Request) -> int:
    from .commands import upstream

    return upstream.run(request)


# Command name -> handler. Value-keyed dispatch, not a class hierarchy (DESIGN.md §14).
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


# --------------------------------------------------------------------------- #
# Parser construction                                                          #
# --------------------------------------------------------------------------- #
def _add_json(p: argparse.ArgumentParser) -> None:
    p.add_argument("--json", action="store_true", help="emit machine-readable JSON")


def _add_version(p: argparse.ArgumentParser) -> None:
    p.add_argument("--version", dest="version", metavar="REF",
                   help="source git ref (branch/tag/SHA); defaults to main")


def _add_selection(p: argparse.ArgumentParser, *, names: bool = True) -> None:
    """Artifact-selection flags shared by install/update/uninstall (and partly list)."""
    if names:
        p.add_argument("names", nargs="*", metavar="NAME", help="artifact name(s) to select")
    p.add_argument("--bundle", action="append", metavar="B",
                   help="select a bundle (repeatable)")
    p.add_argument("--all", action="store_true", help="select every catalog artifact")


def _add_profile(p: argparse.ArgumentParser) -> None:
    p.add_argument("--profile", action="append", metavar="P[,P...]",
                   help="target harness profile(s); comma-separated or repeated")


def build_parser() -> argparse.ArgumentParser:
    """Build the full argparse parser mirroring DESIGN.md §13."""
    parser = argparse.ArgumentParser(
        prog="agent-artifacts",
        description="Install a team's AI artifacts (skills, guidelines, MCP configs, hooks) "
                    "into agentic harnesses.",
    )
    parser.add_argument("--version", action="version",
                        version=f"agent-artifacts {__version__}")

    # Global options (DESIGN.md §13). Attached to every subcommand via parents= so they may
    # follow the verb, e.g. `agent-artifacts list --source ./checkout`.
    glob = argparse.ArgumentParser(add_help=False)
    glob.add_argument("--repo", metavar="OWNER/NAME", help="source-of-truth GitHub repo")
    glob.add_argument("--project", metavar="DIR",
                      help="consumer project directory (default: current dir)")
    glob.add_argument("--source", dest="source_dir", metavar="DIR",
                      help="install from a local checkout (offline / air-gapped)")

    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    # list -------------------------------------------------------------------- #
    p = sub.add_parser("list", parents=[glob], help="list catalog artifacts")
    p.add_argument("--bundle", action="append", metavar="B", help="restrict to a bundle")
    p.add_argument("--type", dest="type_filter", choices=_ARTIFACT_TYPES,
                   help="restrict to an artifact type")
    _add_version(p)
    _add_json(p)

    # install ----------------------------------------------------------------- #
    p = sub.add_parser("install", parents=[glob], help="install artifacts into profiles")
    _add_selection(p)
    _add_profile(p)
    _add_version(p)
    p.add_argument("--memory-mode", dest="memory_mode", choices=_MEMORY_MODES,
                   help="how an `memory` instruction file combines with an existing one "
                        "(default: prepend); see DESIGN-memory.md §3.2")
    p.add_argument("--dry-run", action="store_true", help="print the plan; touch nothing")
    p.add_argument("--yes", action="store_true", help="assume yes (agent mode, no prompts)")
    p.add_argument("--force", action="store_true",
                   help="authorize overwrites and merge-entry collisions")
    _add_json(p)

    # status ------------------------------------------------------------------ #
    p = sub.add_parser("status", parents=[glob],
                       help="show installed artifacts and on-disk drift (local, no network)")
    _add_json(p)

    # check ------------------------------------------------------------------- #
    p = sub.add_parser("check", parents=[glob],
                       help="compare installed/CLI commit against the source (remote)")
    _add_version(p)
    _add_json(p)

    # update ------------------------------------------------------------------ #
    p = sub.add_parser("update", parents=[glob],
                       help="re-pull and re-apply installed artifacts")
    p.add_argument("names", nargs="*", metavar="NAME", help="restrict to artifact name(s)")
    p.add_argument("--bundle", action="append", metavar="B", help="restrict to a bundle")
    _add_profile(p)
    p.add_argument("--prune", action="store_true",
                   help="remove installed entries no longer in the selection")
    p.add_argument("--dry-run", action="store_true", help="print the plan; touch nothing")
    p.add_argument("--force", action="store_true", help="overwrite drift / merge collisions")
    p.add_argument("--yes", action="store_true", help="assume yes (agent mode, no prompts)")
    _add_json(p)

    # uninstall --------------------------------------------------------------- #
    p = sub.add_parser("uninstall", parents=[glob],
                       help="reverse installed files and merges")
    _add_selection(p)
    _add_profile(p)
    p.add_argument("--dry-run", action="store_true", help="print the plan; touch nothing")
    p.add_argument("--yes", action="store_true", help="assume yes (agent mode, no prompts)")
    p.add_argument("--force", action="store_true",
                   help="remove merge entries even if locally modified")
    _add_json(p)

    # upgrade ----------------------------------------------------------------- #
    p = sub.add_parser("upgrade", parents=[glob],
                       help="reinstall the tool itself from the source (offline-capable)")
    _add_version(p)
    p.add_argument("--dry-run", action="store_true",
                   help="print the pip invocation; install nothing")

    # upstream ---------------------------------------------------------------- #
    p = sub.add_parser("upstream", help="maintain vendored artifact upstreams")
    up = p.add_subparsers(dest="upstream_action", metavar="ACTION", required=True)

    p_check = up.add_parser("check", parents=[glob], help="check tracked upstream artifacts")
    _add_selection(p_check)
    p_check.add_argument("--type", dest="type_filter", choices=_ARTIFACT_TYPES,
                         help="restrict to an artifact type")
    _add_json(p_check)

    p_update = up.add_parser("update", parents=[glob], help="update tracked upstream artifacts")
    _add_selection(p_update)
    p_update.add_argument("--type", dest="type_filter", choices=_ARTIFACT_TYPES,
                          help="restrict to an artifact type")
    p_update.add_argument("--dry-run", action="store_true", help="print the plan; touch nothing")
    p_update.add_argument("--force", action="store_true", help="overwrite local catalog drift")
    _add_json(p_update)

    p_add = up.add_parser("add", parents=[glob],
                          help="adopt an upstream artifact from a GitHub URL")
    p_add.add_argument("names", nargs=1, metavar="TYPE/NAME",
                       help="artifact key, e.g. skill/grill-me")
    p_add.add_argument("url", metavar="URL",
                       help="GitHub URL: a repo, or a /tree//blob deep link to the artifact")
    p_add.add_argument("--ref", dest="ref", metavar="REF",
                       help="override the ref (needed when a branch name contains slashes)")
    p_add.add_argument("--path", dest="path", metavar="PATH",
                       help="override the in-repo path to the artifact")
    p_add.add_argument("--force", action="store_true",
                       help="overwrite an existing catalog destination / re-adopt a tracked key")
    p_add.add_argument("--dry-run", action="store_true", help="print the plan; touch nothing")
    _add_json(p_add)

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
    return Request(
        command=args.command,
        names=tuple(getattr(args, "names", None) or ()),
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
        memory_mode=getattr(args, "memory_mode", None),
        upstream_action=getattr(args, "upstream_action", None),
        url=getattr(args, "url", None),
        ref=getattr(args, "ref", None),
        path=getattr(args, "path", None),
    )


# --------------------------------------------------------------------------- #
# Entry point                                                                  #
# --------------------------------------------------------------------------- #
def _run_bare(parser: argparse.ArgumentParser, args: Optional[argparse.Namespace] = None) -> int:
    """Bare invocation (DESIGN.md §13): launch the TUI on a TTY, else print help."""
    if sys.stdin.isatty() and sys.stdout.isatty():
        from . import tui  # WP-20: always present in the package.
        kwargs = {}
        if args:
            if getattr(args, "source_dir", None): kwargs["source_dir"] = args.source_dir
            if getattr(args, "repo", None): kwargs["repo"] = args.repo
            if getattr(args, "project", None): kwargs["project"] = args.project
        return int(tui.run(**kwargs))
    parser.print_help()
    return OK


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Parse ``argv``, dispatch to a command, and return its process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        return _run_bare(parser, args)
    return DISPATCH[args.command](_to_request(args))


if __name__ == "__main__":
    raise SystemExit(main())
