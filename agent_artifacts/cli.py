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
from .commands import check, install, setup, status, uninstall, update, upgrade
from .commands import list as list_cmd
from .commands._common import OK
from .model import Request
from .outcomes import CommandOutcome


def _run_upstream(request: Request) -> int:
    from .commands import upstream

    return upstream.run(request)


def _run_registry(request: Request) -> int:
    from .commands import registry

    return registry.run(request)


def _run_security(request: Request) -> int:
    from .commands import security

    return security.run(request)


def _run_reporting(request: Request) -> int:
    from .commands import reporting

    return reporting.run(request)


def _run_migrate(request: Request) -> int:
    from .commands import migrate

    return migrate.run(request)


def _run_source(request: Request) -> int:
    from .commands import source

    return source.run(request)


def _run_marketplace(request: Request) -> int:
    from .commands import marketplace

    return marketplace.run(request)


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
    "setup": setup.run,
    "registry": _run_registry,
    "security": _run_security,
    "reporting": _run_reporting,
    "migrate": _run_migrate,
    "source": _run_source,
    "marketplace": _run_marketplace,
}

# Structured results used by interactive frontends. Flag mode retains ``DISPATCH`` and its
# integer contract; both paths execute the same command application service exactly once.
RESULT_DISPATCH: dict[str, Callable[[Request], CommandOutcome]] = {
    "install": install.execute,
    "update": update.execute,
    "uninstall": uninstall.execute,
}

_ARTIFACT_TYPES = ("skill", "guideline", "mcp", "hook", "memory")
_MEMORY_MODES = ("replace", "prepend", "append", "skip")
_IMPORT_MODES = ("auto", "manifest", "heuristic")
_BUNDLE_MODES = ("append", "replace", "fail")
_INSTALL_SCOPES = ("project", "user")
_HELP_FORMATTER = argparse.RawDescriptionHelpFormatter


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
        formatter_class=_HELP_FORMATTER,
        description="Install a team's AI artifacts (skills, guidelines, MCP configs, hooks) "
        "into agentic harnesses.",
    )
    parser.add_argument("--version", action="version", version=f"agent-artifacts {__version__}")

    def _add_repo(p: argparse.ArgumentParser) -> None:
        p.add_argument("--repo", metavar="OWNER/NAME", help="source-of-truth GitHub repo")

    def _add_project(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--project",
            metavar="DIR",
            help="project-scope consumer directory (default: current dir)",
        )

    def _add_scope(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--scope",
            choices=_INSTALL_SCOPES,
            default="project",
            help="target Project or User configuration/state (default: project)",
        )

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
    p = sub.add_parser(
        "install",
        formatter_class=_HELP_FORMATTER,
        help="install artifacts (Copy by default; --link enables local Symlink mode)",
        description=(
            "Install artifacts into Project or User harness configuration.\n\n"
            "Scopes:\n"
            "  Project (recommended) configures only the current repository.\n"
            "  User configures the selected harness for the current user.\n\n"
            "Installation modes:\n"
            "  Copy (recommended) installs an independent snapshot.\n"
            "  Symlink (--link) keeps supported directory artifacts live-linked to a local "
            "catalog.\n"
            "This legacy flag path requires an explicit --source DIR or --repo OWNER/NAME."
        ),
        epilog=(
            "Symlink mode:\n"
            "  agent-artifacts install code-review --profile tabnine --source DIR --link\n\n"
            "  Symlink (--link) is local-only and requires an explicit local --source DIR.\n"
            "  Changes propagate only when that local source changes, for example after you edit it\n"
            "  or pull upstream updates into it.\n"
            "  Supported directory artifacts are linked; unsupported explicit selections fail.\n"
            "  Unsupported entries selected by --all or --bundle are copied and reported.\n"
            "  Manifest metadata records install.mode, requested_mode, and link targets so agents\n"
            "  can inspect status/update/uninstall behavior without guessing."
        ),
    )
    _add_repo(p)
    _add_project(p)
    _add_scope(p)
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
        help=(
            "select Symlink mode for supported directory artifacts from a local catalog; "
            "Copy remains the default"
        ),
    )
    _add_json(p)

    # status ------------------------------------------------------------------ #
    p = sub.add_parser(
        "status",
        formatter_class=_HELP_FORMATTER,
        help="show installed artifacts, drift, and symlink link state",
        description="Show installed artifacts and on-disk drift in the selected scope. This command is local-only and uses no network.",
        epilog=(
            "For symlink installs, status reports install.mode plus each link target and state.\n"
            "Use --json to inspect install.links[].target, target_exists, and file states such as\n"
            "ok (symlink), broken symlink, retargeted symlink, replaced, or missing."
        ),
    )
    _add_repo(p)
    _add_project(p)
    _add_scope(p)
    _add_json(p)

    # check ------------------------------------------------------------------- #
    p = sub.add_parser(
        "check",
        formatter_class=_HELP_FORMATTER,
        help="compare installed/CLI commit against source and report live links",
        description="Compare artifacts installed in the selected scope and the CLI commit against the selected remote source.",
        epilog=(
            "Symlink installs are reported separately as live-linked entries.\n"
            "Remote upstream changes do not flow through a symlink by themselves; linked installs\n"
            "change when the local checkout target changes."
        ),
    )
    _add_repo(p)
    _add_project(p)
    _add_scope(p)
    _add_version(p)
    _add_json(p)

    # update ------------------------------------------------------------------ #
    p = sub.add_parser(
        "update",
        formatter_class=_HELP_FORMATTER,
        help="re-pull and re-apply installed artifacts; linked entries stay live",
        description="Update artifacts in the selected scope while preserving each entry's recorded install mode.",
        epilog=(
            "For symlink installs, update keeps the recorded link mode.\n"
            "A correct existing link is reported as live-linked and does not need a copy.\n"
            "Missing links are recreated. Replaced, retargeted, or broken links require --force\n"
            "before they are relinked."
        ),
    )
    _add_repo(p)
    _add_project(p)
    _add_scope(p)
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
    p = sub.add_parser(
        "uninstall",
        formatter_class=_HELP_FORMATTER,
        help="reverse installed files, merges, and symlink paths",
        description="Uninstall selected manifest entries from the selected Project or User scope.",
        epilog=(
            "For symlink installs, uninstall removes the symlink path in the project, not the\n"
            "target directory in the local source checkout. If a managed link was replaced or\n"
            "retargeted, use --force to confirm removal."
        ),
    )
    _add_project(p)
    _add_scope(p)
    _add_selection(p)
    _add_profile(p)
    p.add_argument("--dry-run", action="store_true", help="print the plan; touch nothing")
    p.add_argument("--yes", action="store_true", help="assume yes (agent mode, no prompts)")
    p.add_argument(
        "--force",
        action="store_true",
        help="remove merge entries or changed symlink paths even if locally modified",
    )
    _add_json(p)

    # upgrade ----------------------------------------------------------------- #
    p = sub.add_parser(
        "upgrade",
        help="reinstall AART from one explicit local wheel or checkout",
        description=(
            "Replace this AART executable from one reviewed local input. "
            "AART 1.0 never discovers an index or source repository implicitly."
        ),
    )
    upgrade_source = p.add_mutually_exclusive_group(required=True)
    upgrade_source.add_argument(
        "--wheel",
        dest="upgrade_wheel",
        metavar="FILE",
        help="install an exact local agent_artifacts wheel without an index",
    )
    upgrade_source.add_argument(
        "--source-checkout",
        dest="upgrade_source_checkout",
        metavar="DIR",
        help="reinstall editable from an exact local AART checkout without an index",
    )
    p.add_argument(
        "--dry-run", action="store_true", help="print the pip invocation; install nothing"
    )

    # setup ------------------------------------------------------------------- #
    p = sub.add_parser(
        "setup",
        formatter_class=_HELP_FORMATTER,
        help="review, run, retry, inspect, or roll back artifact setup",
        description=(
            "Run reviewed declarative setup after artifact installation. "
            "State and receipts contain no credential values."
        ),
    )
    setup_sub = p.add_subparsers(dest="setup_action", metavar="ACTION", required=True)

    def _add_setup_scope(target: argparse.ArgumentParser) -> None:
        _add_project(target)
        _add_scope(target)

    def _add_setup_selection(target: argparse.ArgumentParser, *, optional: bool = False) -> None:
        target.add_argument(
            "names",
            nargs="*" if optional else "+",
            metavar="TYPE/NAME",
            help="installed setup-capable artifact key(s)",
        )
        _add_profile(target)

    p_run = setup_sub.add_parser("run", help="review and run setup for installed artifacts")
    _add_setup_selection(p_run)
    _add_setup_scope(p_run)
    _add_repo(p_run)
    _add_source(p_run, "use an explicit installed local catalog")
    _add_version(p_run)
    p_run.add_argument("--yes", action="store_true", help="approve the exact rendered plan")
    p_run.add_argument(
        "--stop-on-failure",
        action="store_true",
        help="stop after an incomplete item and mark unstarted items skipped",
    )
    _add_json(p_run)

    p_retry = setup_sub.add_parser("retry", help="retry incomplete setup records")
    _add_setup_selection(p_retry, optional=True)
    _add_setup_scope(p_retry)
    _add_repo(p_retry)
    _add_source(p_retry, "use an explicit installed local catalog")
    _add_version(p_retry)
    p_retry.add_argument("--yes", action="store_true", help="approve the exact rendered plan")
    p_retry.add_argument(
        "--stop-on-failure",
        action="store_true",
        help="stop after an incomplete retry and mark unstarted items skipped",
    )
    _add_json(p_retry)

    p_setup_status = setup_sub.add_parser("status", help="show local setup state")
    _add_setup_scope(p_setup_status)
    _add_json(p_setup_status)

    p_rollback = setup_sub.add_parser("rollback", help="roll back owned effects from a receipt")
    _add_setup_selection(p_rollback)
    _add_setup_scope(p_rollback)
    p_rollback.add_argument("--yes", action="store_true", help="confirm rollback")
    _add_json(p_rollback)

    # migrate ------------------------------------------------------------------ #
    p = sub.add_parser(
        "migrate",
        help="migrate legacy AART consumer state",
        description=(
            "Review, apply, or roll back an explicit 0.1.x installation-state migration. "
            "Migration never guesses between duplicate marketplace artifacts."
        ),
    )
    migration_sub = p.add_subparsers(dest="migration_action", metavar="ACTION", required=True)
    p_state = migration_sub.add_parser("state", help="migrate 0.1.x installation state to v2")
    p_state.add_argument(
        "--from",
        dest="migration_from",
        required=True,
        choices=("0.1",),
        help="legacy state family (currently: 0.1)",
    )
    _add_project(p_state)
    _add_scope(p_state)
    p_state.add_argument(
        "--source-map",
        action="append",
        default=[],
        metavar="TYPE/NAME@PROFILE=ALIAS",
        help="resolve one ambiguous legacy artifact to an enabled canonical source",
    )
    operation = p_state.add_mutually_exclusive_group(required=True)
    operation.add_argument("--dry-run", action="store_true", help="review the exact migration")
    operation.add_argument("--apply", action="store_true", help="apply the reviewed migration")
    operation.add_argument("--rollback", action="store_true", help="restore exact 0.1 state")
    _add_json(p_state)

    # source ------------------------------------------------------------------ #
    p = sub.add_parser(
        "source",
        formatter_class=_HELP_FORMATTER,
        help="add and inspect configured canonical source origins",
        description=(
            "Manage configured registry/direct/local origins for the canonical marketplace. "
            "`source add` validates and snapshots the exact source before saving it, so it is "
            "safe for non-interactive agent use."
        ),
    )
    source_sub = p.add_subparsers(dest="source_action", metavar="ACTION", required=True)
    p_add_source = source_sub.add_parser(
        "add",
        help="synchronize, validate, then persist one source origin",
        description=(
            "Parse one exact source, validate a fresh immutable snapshot, then atomically save "
            "the source configuration. No interactive confirmation is required because all "
            "origin/default choices are explicit command arguments."
        ),
    )
    p_add_source.add_argument(
        "--alias", dest="source_alias", required=True, metavar="ALIAS", help="source alias slug"
    )
    p_add_source.add_argument(
        "--kind",
        dest="source_kind",
        choices=("registry-git", "source-git", "source-local"),
        required=True,
        help="registry-git, source-git, or source-local",
    )
    p_add_source.add_argument(
        "--location",
        dest="source_location",
        required=True,
        metavar="URL_OR_PATH",
        help="credential-free Git URL or normalized absolute local path",
    )
    p_add_source.add_argument(
        "--ref",
        metavar="REF",
        help="Git ref (defaults to main; not valid for source-local)",
    )
    source_default = p_add_source.add_mutually_exclusive_group()
    source_default.add_argument(
        "--default",
        dest="source_make_default",
        action="store_const",
        const=True,
        help="make this registry the default registry",
    )
    source_default.add_argument(
        "--no-default",
        dest="source_make_default",
        action="store_const",
        const=False,
        help="preserve the current default registry",
    )
    _add_json(p_add_source)

    p_source_list = source_sub.add_parser(
        "list",
        help="show configured origins and managed snapshot health",
    )
    _add_json(p_source_list)

    # marketplace ------------------------------------------------------------- #
    p = sub.add_parser(
        "marketplace",
        formatter_class=_HELP_FORMATTER,
        help="browse the configured canonical marketplace",
        description=(
            "Read the local, already-validated configured source snapshots as one canonical "
            "marketplace. This is the agent-facing browse command; legacy list/install/update "
            "commands retain their explicit legacy source compatibility contract."
        ),
    )
    marketplace_sub = p.add_subparsers(dest="marketplace_action", metavar="ACTION", required=True)
    p_marketplace_list = marketplace_sub.add_parser(
        "list",
        help="emit all canonical marketplace sources and artifacts",
    )
    _add_json(p_marketplace_list)

    def _add_lifecycle(
        action: str,
        help_text: str,
        *,
        coordinates: str,
        prune: bool = False,
        placement: bool = True,
    ) -> argparse.ArgumentParser:
        """Declare one canonical lifecycle action over configured sources.

        Every mutating flag is opt-in: without ``--yes`` the command stops at Review, and no
        legacy ``--source``/``--repo`` flag is accepted here, so a caller cannot mix the
        compatibility catalog path into a canonical configured-source operation.
        """

        lifecycle = marketplace_sub.add_parser(
            action,
            formatter_class=_HELP_FORMATTER,
            help=help_text,
            description=(
                f"{help_text.capitalize()}. Artifacts are addressed as "
                "<source>/<kind>/<name>[@<version>]; an unqualified <kind>/<name> is accepted "
                "only when exactly one configured source provides it. Without --yes the command "
                "prints the reviewed plan and exits without changing anything."
            ),
        )
        lifecycle.add_argument(
            "names",
            nargs="*",
            metavar="COORDINATE",
            help=coordinates,
        )
        _add_profile(lifecycle)
        _add_project(lifecycle)
        _add_scope(lifecycle)
        if placement:
            lifecycle.add_argument(
                "--mode",
                dest="install_mode",
                choices=("copy", "symlink"),
                default=None,
                help="install placement mode (default: copy)",
            )
        lifecycle.add_argument(
            "--offline",
            action="store_true",
            help="use last-known-good snapshots and cached objects only",
        )
        lifecycle.add_argument(
            "--force",
            action="store_true",
            help="authorize overwrites and merge-entry collisions",
        )
        if prune:
            lifecycle.add_argument(
                "--prune",
                action="store_true",
                help="remove installed entries no longer in the selection",
            )
        lifecycle.add_argument(
            "--yes",
            action="store_true",
            help="finalize the reviewed plan (without this the command only reviews)",
        )
        _add_json(lifecycle)
        return lifecycle

    _add_lifecycle(
        "install",
        "install configured-source artifacts for the selected harness profiles",
        coordinates="artifact coordinate(s) to install",
    )
    _add_lifecycle(
        "update",
        "update installed artifacts against their configured sources",
        coordinates="artifact coordinate(s) to update; omit to consider every installed artifact",
        prune=True,
    )
    _add_lifecycle(
        "uninstall",
        "remove installed artifacts recorded for the selected profiles",
        coordinates="artifact coordinate(s) to remove",
        placement=False,
    )
    _add_lifecycle(
        "status",
        "report installed artifact state against the configured sources",
        coordinates="artifact coordinate(s) to inspect; omit to report every installed artifact",
        placement=False,
    )
    p_marketplace_setup = _add_lifecycle(
        "setup",
        "run declared post-install setup for installed artifacts",
        coordinates="artifact coordinate(s) whose setup should run",
        placement=False,
    )
    p_marketplace_setup.add_argument(
        "--authorize-untrusted-source",
        action="store_true",
        help="authorize setup declared by a source that is not company-reviewed",
    )
    p_marketplace_setup.add_argument(
        "--authorize-custom-entrypoint",
        action="store_true",
        help="authorize a setup recipe that declares a non-standard entrypoint",
    )
    p_marketplace_setup.add_argument(
        "--approve-setup-effects",
        action="store_true",
        help="approve every reviewed setup effect; without it each effect is declined",
    )

    # upstream ---------------------------------------------------------------- #
    p = sub.add_parser("upstream", help="maintain vendored artifact upstreams")
    up = p.add_subparsers(dest="upstream_action", metavar="ACTION", required=True)

    p_validate = up.add_parser("validate", help="validate a local catalog and upstream metadata")
    _add_source(p_validate, "catalog repository directory to validate (default: current dir)")
    _add_json(p_validate)

    p_health = up.add_parser("health", help="show local catalog and upstream health")
    _add_source(p_health, "catalog repository directory to inspect (default: current dir)")
    _add_json(p_health)

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

    p_add = up.add_parser("add", help="adopt an upstream artifact from a GitHub URL")
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
    p_import.add_argument(
        "--interactive", action="store_true", help="prompt for candidate selection"
    )
    p_import.add_argument("--dry-run", action="store_true", help="print the plan; touch nothing")
    p_import.add_argument("--force", action="store_true", help="replace existing catalog entries")
    _add_json(p_import)

    # registry ---------------------------------------------------------------- #
    p = sub.add_parser(
        "registry",
        formatter_class=_HELP_FORMATTER,
        help="initialize, compile, audit, and migrate an AART registry",
        description=(
            "Maintain a writable AART registry checkout. Read/check commands never mutate it; "
            "mutation commands only write reviewed managed files and never commit or push."
        ),
    )
    registry_sub = p.add_subparsers(dest="registry_action", metavar="ACTION", required=True)

    def _add_registry_source(target: argparse.ArgumentParser) -> None:
        _add_source(target, "registry checkout or read-only registry snapshot")

    def _add_check(target: argparse.ArgumentParser) -> None:
        target.add_argument(
            "--check",
            action="store_true",
            help="report drift without writing; return non-zero when generated files differ",
        )

    p_init = registry_sub.add_parser("init", help="initialize a canonical registry checkout")
    _add_registry_source(p_init)
    p_init.add_argument(
        "--source-id", required=True, metavar="SLUG", help="stable registry/source identity"
    )
    p_init.add_argument(
        "--display-name", required=True, metavar="TEXT", help="human-readable registry name"
    )
    p_init.add_argument(
        "--minimum-version",
        default="1.0.0",
        metavar="VERSION",
        help="minimum supported AART version (default: 1.0.0)",
    )
    p_init.add_argument(
        "--maximum-version",
        default="2.0.0",
        metavar="VERSION",
        help="exclusive maximum AART version (default: 2.0.0)",
    )
    _add_json(p_init)

    p_scaffold = registry_sub.add_parser(
        "scaffold", help="create one canonical native artifact package"
    )
    _add_registry_source(p_scaffold)
    p_scaffold.add_argument("type_filter", choices=_ARTIFACT_TYPES, metavar="KIND")
    p_scaffold.add_argument("names", nargs=1, metavar="NAME")
    p_scaffold.add_argument(
        "--summary", required=True, metavar="TEXT", help="one-line artifact description"
    )
    p_scaffold.add_argument(
        "--artifact-version",
        default="1.0.0",
        metavar="VERSION",
        help="initial artifact version (default: 1.0.0)",
    )
    p_scaffold.add_argument(
        "--profile",
        action="append",
        required=True,
        metavar="P[,P...]",
        help="target harness profile(s); comma-separated or repeated",
    )
    p_scaffold.add_argument(
        "--platform",
        action="append",
        required=True,
        metavar="PLATFORM",
        help="supported platform (repeatable)",
    )
    p_scaffold.add_argument(
        "--install-scope",
        action="append",
        choices=_INSTALL_SCOPES,
        dest="registry_scopes",
        default=[],
        help="supported install scope (repeatable; default: project)",
    )
    p_scaffold.add_argument(
        "--install-mode",
        action="append",
        choices=("copy", "symlink"),
        dest="registry_modes",
        default=[],
        help="supported install mode (repeatable; default: copy)",
    )
    _add_json(p_scaffold)

    p_format = registry_sub.add_parser("format", help="canonicalize registry JSON files")
    _add_registry_source(p_format)
    _add_check(p_format)
    _add_json(p_format)

    p_validate = registry_sub.add_parser("validate", help="validate registry protocol content")
    _add_registry_source(p_validate)
    p_validate.add_argument(
        "--strict", action="store_true", help="require committed generated outputs"
    )
    p_validate.add_argument(
        "--frozen", action="store_true", help="reject a missing or stale lock/index pair"
    )
    _add_json(p_validate)

    for action in ("lock", "build"):
        target = registry_sub.add_parser(
            action,
            help=f"{'resolve authored references' if action == 'lock' else 'compile the index'}",
        )
        _add_registry_source(target)
        _add_check(target)
        _add_json(target)

    p_audit = registry_sub.add_parser(
        "audit", help="audit review, provenance, setup, and available security metadata"
    )
    _add_registry_source(p_audit)
    _add_json(p_audit)

    p_test = registry_sub.add_parser("test", help="run a compatibility validation fixture")
    _add_registry_source(p_test)
    p_test.add_argument(
        "--compatibility",
        choices=("minimum", "latest", "all"),
        default="all",
        help="compatibility point to validate (default: all)",
    )
    p_test.add_argument(
        "--latest-version",
        default="1.0.0",
        metavar="VERSION",
        help="latest compatible AART version under test (default: 1.0.0)",
    )
    _add_json(p_test)

    p_diff = registry_sub.add_parser("diff", help="show deterministic managed-file drift")
    _add_registry_source(p_diff)
    _add_json(p_diff)

    p_migrate = registry_sub.add_parser(
        "migrate", help="preview or apply migration from an immutable legacy catalog"
    )
    _add_registry_source(p_migrate)
    p_migrate.add_argument(
        "--legacy-source",
        required=True,
        metavar="GIT-URL-OR-DIR",
        help="immutable legacy catalog Git source",
    )
    p_migrate.add_argument(
        "--origin-url",
        metavar="HTTPS-GIT-URL",
        help="recorded origin when --legacy-source is a local Git checkout",
    )
    p_migrate.add_argument(
        "--ref", default="HEAD", metavar="REF", help="legacy source Git ref (default: HEAD)"
    )
    p_migrate.add_argument(
        "--source-id", required=True, metavar="SLUG", help="identity for the migrated registry"
    )
    p_migrate.add_argument(
        "--display-name", required=True, metavar="TEXT", help="migrated registry display name"
    )
    p_migrate.add_argument(
        "--artifact-version",
        default="1.0.0",
        metavar="VERSION",
        help="version assigned to imported artifacts (default: 1.0.0)",
    )
    p_migrate.add_argument(
        "--license",
        dest="artifact_license",
        metavar="SPDX",
        help="license declared by every imported artifact (for example: MIT)",
    )
    p_migrate.add_argument(
        "--profile",
        action="append",
        required=True,
        metavar="P[,P...]",
        help="target harness profile(s); comma-separated or repeated",
    )
    p_migrate.add_argument(
        "--platform",
        action="append",
        default=[],
        help="supported platform (repeatable; default: darwin)",
    )
    p_migrate.add_argument("--apply", action="store_true", help="apply the reviewed migration")
    _add_json(p_migrate)

    # security --------------------------------------------------------------- #
    p = sub.add_parser(
        "security",
        help="inspect explainable installation-risk evidence",
        description=(
            "Scan immutable artifacts, inspect assessment evidence, and discover optional "
            "analyzers. Assessments reduce uncertainty; they are not safety guarantees."
        ),
    )
    security_sub = p.add_subparsers(dest="security_action", metavar="ACTION", required=True)

    p_security = security_sub.add_parser(
        "scan", help="run the zero-dependency baseline over an immutable object envelope"
    )
    p_security.add_argument("security_input", metavar="OBJECT")
    p_security.add_argument(
        "--index",
        dest="registry_index",
        required=True,
        metavar="FILE",
        help="canonical registry index that binds the selected artifact object",
    )
    p_security.add_argument(
        "--artifact",
        dest="security_artifact",
        required=True,
        metavar="KIND/NAME",
        help="exact artifact identity from the registry index",
    )
    p_security.add_argument(
        "--lock",
        dest="registry_lock",
        metavar="FILE",
        help="optional canonical registry lock for external provenance evidence",
    )
    p_security.add_argument(
        "--cache", dest="security_cache", metavar="DIR", help="publish canonical local attestation"
    )
    _add_json(p_security)

    p_security = security_sub.add_parser("show", help="show a canonical assessment or attestation")
    p_security.add_argument("security_input", metavar="EVIDENCE")
    _add_json(p_security)

    p_security = security_sub.add_parser(
        "verify", help="verify canonical attestation identity, freshness, and locally derived trust"
    )
    p_security.add_argument("security_input", metavar="ATTESTATION")
    p_security.add_argument(
        "--object-digest",
        dest="security_object_digest",
        metavar="SHA256",
        help="expected immutable object digest; a mismatch marks evidence stale",
    )
    p_security.add_argument(
        "--rules-digest",
        dest="security_rules_digest",
        metavar="SHA256",
        help="expected analyzer rules digest; a mismatch marks evidence stale",
    )
    p_security.add_argument(
        "--options-digest",
        dest="security_options_digest",
        metavar="SHA256",
        help="expected analyzer options digest; a mismatch marks evidence stale",
    )
    p_security.add_argument(
        "--policy-digest",
        dest="security_policy_digest",
        metavar="SHA256",
        help="expected effective policy digest; a mismatch marks evidence stale",
    )
    p_security.add_argument(
        "--provider-version",
        dest="security_provider_version",
        metavar="VERSION",
        help="expected provider version; a mismatch marks evidence stale",
    )
    p_security.add_argument(
        "--publisher-source-id",
        metavar="SLUG",
        help="locally configured publisher identity used to derive trust",
    )
    p_security.add_argument(
        "--registry-inputs-digest",
        dest="security_registry_inputs_digest",
        metavar="SHA256",
        help="exact locally resolved registry inputs digest used to derive trust",
    )
    p_security.add_argument(
        "--publisher-trust",
        choices=("unverified", "registry-reviewed", "company-reviewed"),
        help="local trust classification for the exact publisher and registry inputs",
    )
    _add_json(p_security)

    p_security = security_sub.add_parser(
        "analyzers", help="list reviewed optional analyzer adapters and local availability"
    )
    _add_json(p_security)
    p_security = security_sub.add_parser("suites", help="list built-in analyzer suites")
    _add_json(p_security)

    # reporting -------------------------------------------------------------- #
    p = sub.add_parser(
        "reporting",
        help="validate and aggregate registry-owned redacted usage reports",
    )
    reporting_sub = p.add_subparsers(dest="reporting_action", metavar="ACTION", required=True)
    for action in ("validate-event", "validate-issue"):
        target = reporting_sub.add_parser(
            action, help=f"validate one {action.removeprefix('validate-')}"
        )
        target.add_argument("reporting_input", metavar="FILE", help="input path or - for stdin")
    target = reporting_sub.add_parser("aggregate", help="build a static dashboard from gh JSON")
    target.add_argument("reporting_input", metavar="FILE", help="issue export path or - for stdin")
    target.add_argument(
        "--output",
        dest="reporting_output",
        required=True,
        metavar="DIR",
        help="directory for index.html and usage.json",
    )

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
        names=_split_csv(select)
        if select is not None
        else tuple(getattr(args, "names", None) or ()),
        bundles=tuple(getattr(args, "bundle", None) or ()),
        profiles=_split_csv(getattr(args, "profile", None)),
        all=bool(getattr(args, "all", False)),
        version=getattr(args, "version", None),
        source_dir=getattr(args, "source_dir", None),
        repo=getattr(args, "repo", None),
        project=getattr(args, "project", None),
        scope=getattr(args, "scope", "project"),
        type_filter=getattr(args, "type_filter", None),
        yes=bool(getattr(args, "yes", False)),
        force=bool(getattr(args, "force", False)),
        dry_run=bool(getattr(args, "dry_run", False)),
        json=bool(getattr(args, "json", False)),
        prune=bool(getattr(args, "prune", False)),
        # The canonical lifecycle names the mode explicitly; legacy commands keep boolean --link.
        install_mode=(
            getattr(args, "install_mode", None)
            or ("symlink" if bool(getattr(args, "link", False)) else "copy")
        ),
        memory_mode=getattr(args, "memory_mode", None),
        upstream_action=getattr(args, "upstream_action", None),
        url=getattr(args, "url", None),
        ref=getattr(args, "ref", None),
        path=getattr(args, "path", None),
        import_mode=getattr(args, "import_mode", None),
        bundle_mode=getattr(args, "bundle_mode", None),
        bundle_description=getattr(args, "bundle_description", None),
        interactive=bool(getattr(args, "interactive", False)),
        setup_action=getattr(args, "setup_action", None),
        stop_on_failure=bool(getattr(args, "stop_on_failure", False)),
        registry_action=getattr(args, "registry_action", None),
        check=bool(getattr(args, "check", False)),
        apply=bool(getattr(args, "apply", False)),
        strict=bool(getattr(args, "strict", False)),
        frozen=bool(getattr(args, "frozen", False)),
        legacy_source=getattr(args, "legacy_source", None),
        origin_url=getattr(args, "origin_url", None),
        source_id=getattr(args, "source_id", None),
        display_name=getattr(args, "display_name", None),
        summary=getattr(args, "summary", None),
        artifact_version=getattr(args, "artifact_version", None),
        artifact_license=getattr(args, "artifact_license", None),
        minimum_version=getattr(args, "minimum_version", None),
        maximum_version=getattr(args, "maximum_version", None),
        latest_version=getattr(args, "latest_version", None),
        compatibility=getattr(args, "compatibility", None),
        registry_scopes=tuple(
            getattr(args, "registry_scopes", ())
            or (("project",) if getattr(args, "registry_action", None) == "scaffold" else ())
        ),
        registry_modes=tuple(
            getattr(args, "registry_modes", ())
            or (("copy",) if getattr(args, "registry_action", None) == "scaffold" else ())
        ),
        registry_platforms=tuple(
            getattr(args, "platform", ())
            or (("darwin",) if getattr(args, "registry_action", None) == "migrate" else ())
        ),
        security_action=getattr(args, "security_action", None),
        security_input=getattr(args, "security_input", None),
        security_artifact=getattr(args, "security_artifact", None),
        registry_index=getattr(args, "registry_index", None),
        registry_lock=getattr(args, "registry_lock", None),
        security_cache=getattr(args, "security_cache", None),
        security_object_digest=getattr(args, "security_object_digest", None),
        security_rules_digest=getattr(args, "security_rules_digest", None),
        security_options_digest=getattr(args, "security_options_digest", None),
        security_policy_digest=getattr(args, "security_policy_digest", None),
        security_provider_version=getattr(args, "security_provider_version", None),
        publisher_source_id=getattr(args, "publisher_source_id", None),
        security_registry_inputs_digest=getattr(args, "security_registry_inputs_digest", None),
        publisher_trust=getattr(args, "publisher_trust", None),
        reporting_action=getattr(args, "reporting_action", None),
        reporting_input=getattr(args, "reporting_input", None),
        reporting_output=getattr(args, "reporting_output", None),
        migration_action=getattr(args, "migration_action", None),
        migration_from=getattr(args, "migration_from", None),
        source_mappings=tuple(getattr(args, "source_map", ()) or ()),
        source_action=getattr(args, "source_action", None),
        source_alias=getattr(args, "source_alias", None),
        source_kind=getattr(args, "source_kind", None),
        source_location=getattr(args, "source_location", None),
        source_make_default=getattr(args, "source_make_default", None),
        marketplace_action=getattr(args, "marketplace_action", None),
        offline=bool(getattr(args, "offline", False)),
        authorize_untrusted_source=bool(getattr(args, "authorize_untrusted_source", False)),
        authorize_custom_entrypoint=bool(getattr(args, "authorize_custom_entrypoint", False)),
        approve_setup_effects=bool(getattr(args, "approve_setup_effects", False)),
        rollback=bool(getattr(args, "rollback", False)),
        upgrade_wheel=getattr(args, "upgrade_wheel", None),
        upgrade_source_checkout=getattr(args, "upgrade_source_checkout", None),
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
    if args.command in {"list", "install", "update", "setup"} and (
        request.source_dir is not None or request.repo is not None
    ):
        print(
            "warning: --source/--repo use the legacy 0.1 compatibility path; "
            "prefer the configured marketplace in the TUI before this compatibility window ends",
            file=sys.stderr,
        )
    return DISPATCH[args.command](request)


if __name__ == "__main__":
    raise SystemExit(main())
