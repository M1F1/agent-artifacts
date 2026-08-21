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
from .command_outcome import OK
from .commands import upgrade
from .curation.model import DEFAULT_MAXIMUM_AART, DEFAULT_MINIMUM_AART
from .model import Request
from .outcomes import CommandOutcome


def _run_registry(request: Request) -> int:
    from .commands import registry

    return registry.run(request)


def _run_security(request: Request) -> int:
    from .commands import security

    return security.run(request)


def _run_reporting(request: Request) -> int:
    from .commands import reporting

    return reporting.run(request)


def _run_source(request: Request) -> int:
    from .commands import source

    return source.run(request)


def _run_marketplace(request: Request) -> int:
    from .commands import marketplace

    return marketplace.run(request)


# Command name -> handler. Value-keyed dispatch, not a class hierarchy (docs/design/DESIGN.md §14).
DISPATCH: dict[str, Callable[[Request], int]] = {
    "upgrade": upgrade.run,
    "registry": _run_registry,
    "security": _run_security,
    "reporting": _run_reporting,
    "source": _run_source,
    "marketplace": _run_marketplace,
}

# Structured results used by interactive frontends. Flag mode retains ``DISPATCH`` and its
# integer contract; both paths execute the same command application service exactly once.
RESULT_DISPATCH: dict[str, Callable[[Request], CommandOutcome]] = {}

_ARTIFACT_TYPES = ("skill", "guideline", "mcp", "hook", "memory")
_INSTALL_SCOPES = ("project", "user")
_HELP_FORMATTER = argparse.RawDescriptionHelpFormatter


# --------------------------------------------------------------------------- #
# Parser construction                                                          #
# --------------------------------------------------------------------------- #
def _add_json(p: argparse.ArgumentParser) -> None:
    p.add_argument("--json", action="store_true", help="emit machine-readable JSON")


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

    def _add_alias(p: argparse.ArgumentParser, help_text: str) -> None:
        p.add_argument("--alias", dest="source_alias", metavar="ALIAS", help=help_text)

    p_source_sync = source_sub.add_parser(
        "sync",
        formatter_class=_HELP_FORMATTER,
        help="refresh managed snapshots for configured sources",
        description=(
            "Re-synchronize already-configured sources. This never adds, renames, removes, or "
            "re-identifies a source, and never changes policy defaults - use it instead of "
            "re-adding an existing alias."
        ),
    )
    _add_alias(p_source_sync, "synchronize only this alias (default: every enabled source)")
    _add_json(p_source_sync)

    p_source_remove = source_sub.add_parser(
        "remove",
        formatter_class=_HELP_FORMATTER,
        help="forget one configured source and delete its managed snapshot",
        description=(
            "End one subscription: drop the configuration entry, clear the default registry if it "
            "named this alias, and delete the managed snapshot so the origin is free to be added "
            "again. No installed artifact and no file in any project is touched."
        ),
    )
    p_source_remove.add_argument(
        "--alias",
        dest="source_alias",
        required=True,
        metavar="ALIAS",
        help="configured source alias to remove",
    )
    p_source_remove.add_argument(
        "--yes",
        action="store_true",
        help="finalize the reviewed removal (without this the command only reviews)",
    )
    _add_json(p_source_remove)

    p_source_resubscribe = source_sub.add_parser(
        "resubscribe",
        formatter_class=_HELP_FORMATTER,
        help="adopt a changed declared identity at an unchanged origin and ref",
        description=(
            "Adopt the identity an already-configured origin now declares, keeping the alias, "
            "kind, location, ref, and default-registry flag. Without --yes it prints both "
            "identities and changes nothing; --yes adopts exactly the reviewed transition and "
            "refuses if the origin moved again in between. Use `source sync` when the identity "
            "did not change."
        ),
    )
    p_source_resubscribe.add_argument(
        "--alias",
        dest="source_alias",
        required=True,
        metavar="ALIAS",
        help="configured source alias whose declared identity changed",
    )
    p_source_resubscribe.add_argument(
        "--yes",
        action="store_true",
        help="adopt the reviewed identity change (without this the command only reviews)",
    )
    p_source_resubscribe.add_argument(
        "--expect",
        metavar="FROM:TO",
        help=(
            "adopt only this exact identity change, written as the two declared source IDs; "
            "otherwise refuse and show the transition that is actually offered"
        ),
    )
    _add_json(p_source_resubscribe)

    p_source_health = source_sub.add_parser(
        "health",
        formatter_class=_HELP_FORMATTER,
        help="report managed snapshot health for configured sources",
        description=(
            "Read-only per-source health: pointer presence, resolved revision, and snapshot age "
            "against the configured freshness window. Exits non-zero if an enabled source is not "
            "healthy."
        ),
    )
    _add_alias(p_source_health, "report only this alias (default: every configured source)")
    _add_json(p_source_health)

    # marketplace ------------------------------------------------------------- #
    p = sub.add_parser(
        "marketplace",
        formatter_class=_HELP_FORMATTER,
        help="browse the configured canonical marketplace",
        description=(
            "Read the local, already-validated configured source snapshots as one canonical "
            "marketplace. This is the one agent-facing consumer command family."
        ),
    )
    marketplace_sub = p.add_subparsers(dest="marketplace_action", metavar="ACTION", required=True)
    p_marketplace_list = marketplace_sub.add_parser(
        "list",
        help="emit all canonical marketplace sources and artifacts",
    )
    _add_json(p_marketplace_list)

    p_marketplace_health = marketplace_sub.add_parser(
        "health",
        formatter_class=_HELP_FORMATTER,
        help="compare advisory artifact requirements with a repository runtime inventory",
        description=(
            "Read advisory per-artifact runtime requirements and compare them with an explicit "
            "JSON environment description supplied by the consuming repository. AART does not "
            "probe or install runtimes, and health results never block artifact installation."
        ),
    )
    p_marketplace_health.add_argument(
        "names",
        nargs="*",
        metavar="COORDINATE",
        help=(
            "artifact or collection coordinate(s) to inspect; omit to inspect every marketplace "
            "artifact"
        ),
    )
    p_marketplace_health.add_argument(
        "--environment",
        dest="runtime_environment",
        required=True,
        metavar="PATH",
        help="repository-owned runtime environment description in JSON format",
    )
    _add_project(p_marketplace_health)
    _add_json(p_marketplace_health)

    def _add_lifecycle(
        action: str,
        help_text: str,
        *,
        coordinates: str,
        prune: bool = False,
        placement: bool = True,
        memory_mode: bool = False,
    ) -> argparse.ArgumentParser:
        """Declare one canonical lifecycle action over configured sources.

        Every mutating flag is opt-in: without ``--yes`` the command stops at Review.
        """

        lifecycle = marketplace_sub.add_parser(
            action,
            formatter_class=_HELP_FORMATTER,
            help=help_text,
            description=(
                f"{help_text.capitalize()}. Artifacts are addressed as "
                "<source>/<kind>/<name>[@<version>] and collections as "
                "<source>/collection/<name>; an unqualified <kind>/<name> is accepted only when "
                "exactly one configured source provides it. Without --yes the command prints the "
                "reviewed plan and exits without changing anything."
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
        if memory_mode:
            lifecycle.add_argument(
                "--memory-mode",
                dest="memory_mode",
                choices=("replace", "prepend", "append", "skip"),
                default=None,
                help=(
                    "how a memory artifact meets an existing instruction file (default: prepend)"
                ),
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
        lifecycle.add_argument(
            "--expect",
            metavar="DIGEST",
            help=(
                "finalize only if the recomputed review digest equals DIGEST; otherwise refuse "
                "and show the new review"
            ),
        )
        _add_json(lifecycle)
        return lifecycle

    _add_lifecycle(
        "install",
        "install configured-source artifacts for the selected harness profiles",
        coordinates="artifact or collection coordinate(s) to install",
        memory_mode=True,
    )
    _add_lifecycle(
        "update",
        "update installed artifacts against their configured sources",
        coordinates="artifact or collection coordinate(s) to update; omit for all installed",
        prune=True,
    )
    _add_lifecycle(
        "uninstall",
        "remove installed artifacts recorded for the selected profiles",
        coordinates="artifact or collection coordinate(s) to remove",
        placement=False,
    )
    _add_lifecycle(
        "status",
        "report installed artifact state against the configured sources",
        coordinates="artifact or collection coordinate(s) to inspect; omit for all installed",
        placement=False,
    )
    p_marketplace_setup = _add_lifecycle(
        "setup",
        "run declared post-install setup for installed artifacts",
        coordinates="artifact or collection coordinate(s) whose setup should run",
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

    # `receipt` lives under `marketplace` rather than under a top-level `setup` group, because
    # `marketplace setup` already owns that word: a second `aart setup` would name two different
    # operations.  A receipt is a read over one installation, which is this family's subject.
    p_marketplace_receipt = marketplace_sub.add_parser(
        "receipt",
        formatter_class=_HELP_FORMATTER,
        help="read what a setup run recorded for one installation",
        description=(
            "Read the persisted setup record AART writes for every setup run: plan hash, "
            "timings, exit status, and each step with its module, target and disposition. "
            "This is a read; it starts no run and locks nothing."
        ),
    )
    receipt_sub = p_marketplace_receipt.add_subparsers(
        dest="receipt_action", metavar="ACTION", required=True
    )
    p_receipt_show = receipt_sub.add_parser(
        "show",
        help="print the persisted setup record for one installed artifact",
    )
    p_receipt_show.add_argument(
        "names",
        nargs=1,
        metavar="COORDINATE",
        help="the installed artifact coordinate whose setup record should be printed",
    )
    _add_profile(p_receipt_show)
    _add_project(p_receipt_show)
    _add_scope(p_receipt_show)
    _add_json(p_receipt_show)

    p_receipt_verify = receipt_sub.add_parser(
        "verify",
        formatter_class=_HELP_FORMATTER,
        help="ask whether what the setup record claims is still true",
        description=(
            "Put each claim in a persisted setup record to the machine: does the image still "
            "exist, does the tag still resolve to the recorded id, does the Keychain item hold a "
            "value, is the managed block still in the file. Reports and never repairs; exits "
            "non-zero when any claim is false."
        ),
    )
    p_receipt_verify.add_argument(
        "names",
        nargs=1,
        metavar="COORDINATE",
        help="the installed artifact coordinate whose setup record should be checked",
    )
    _add_profile(p_receipt_verify)
    _add_project(p_receipt_verify)
    _add_scope(p_receipt_verify)
    _add_json(p_receipt_verify)

    p_receipt_undo = receipt_sub.add_parser(
        "undo",
        formatter_class=_HELP_FORMATTER,
        help="reverse the effects a setup run recorded",
        description=(
            "Replay a persisted setup receipt in reverse, with the ownership checks the run "
            "itself uses. The only mutating action in this family: without --yes it prints "
            "every effect it would reverse and every effect it would not, and changes nothing."
        ),
    )
    p_receipt_undo.add_argument(
        "names",
        nargs=1,
        metavar="COORDINATE",
        help="the installed artifact coordinate whose setup effects should be reversed",
    )
    _add_profile(p_receipt_undo)
    _add_project(p_receipt_undo)
    _add_scope(p_receipt_undo)
    p_receipt_undo.add_argument(
        "--yes",
        action="store_true",
        help="apply the reviewed undo (without this the command only reviews)",
    )
    p_receipt_undo.add_argument(
        "--expect",
        metavar="DIGEST",
        help=(
            "apply only if the recomputed undo digest equals DIGEST; otherwise refuse and show "
            "the undo that is actually offered"
        ),
    )
    _add_json(p_receipt_undo)

    # registry ---------------------------------------------------------------- #
    p = sub.add_parser(
        "registry",
        formatter_class=_HELP_FORMATTER,
        help="initialize, compile, and audit an AART registry",
        description=(
            "Maintain a writable AART registry checkout. Read/check commands never mutate it; "
            "mutation commands write only reviewed managed files. The explicit publish action "
            "also commits every listed Git change and never pushes. "
            "An artifact's requires resolves inside this one registry, against artifacts this "
            "registry owns: depend on foreign content by publishing it here, never by naming "
            "another registry's artifact."
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

    def _add_registry_finalize(target: argparse.ArgumentParser) -> None:
        target.add_argument(
            "--yes",
            action="store_true",
            help="finalize the reviewed registry mutation (without this only review)",
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
        "--usage-reporting-repository",
        metavar="OWNER/REPOSITORY",
        help=(
            "advertise this registry's GitHub Issues repository for optional prompt-only usage "
            "reports"
        ),
    )
    p_init.add_argument(
        # A registry initialised today cannot honestly claim an older AART can read it: the
        # scaffolded markers, manifests, and setup recipes are the current dialect.  The floor is
        # therefore the AART that wrote them, and an author who really supports more says so.
        "--minimum-version",
        default=DEFAULT_MINIMUM_AART,
        metavar="VERSION",
        help=f"minimum supported AART version (default: {DEFAULT_MINIMUM_AART})",
    )
    p_init.add_argument(
        # The ceiling is the next major after the running release, not a literal.  A default of
        # "2.0.0" was correct only while AART was 1.x; on 2.0.0 it collides with the floor above
        # and every `registry init` is refused as an invalid window.  Both bounds come from the
        # one place that derives them (`RS-02`), so a skin cannot drift from the boundary.
        "--maximum-version",
        default=DEFAULT_MAXIMUM_AART,
        metavar="VERSION",
        help=f"exclusive maximum AART version (default: {DEFAULT_MAXIMUM_AART})",
    )
    p_init.add_argument(
        # The workflows this command writes have to name a repository, and the shipped literal is
        # this project's.  A fork that edited the literal would carry a conflict on that line
        # through every later sync from upstream, so the tool stamps what it reads from its own
        # checkout instead and the fork stays identical to what it tracks.  These two flags are
        # the escape for the cases a checkout cannot answer: AART installed from a wheel, or a
        # fork whose CI should fetch a different repository than the one init was run from.
        "--aart-repository",
        metavar="OWNER/REPOSITORY",
        help="stamp this AART repository into the registry's CI (default: read from the checkout)",
    )
    p_init.add_argument(
        "--aart-ref",
        metavar="REF",
        help="stamp this AART tag, branch or commit into the registry's CI (default: the checkout's own ref)",
    )
    p_init.add_argument(
        "--no-aart-stamp",
        action="store_true",
        help="keep the shipped AART defaults and configure the registry with repository variables",
    )
    _add_registry_finalize(p_init)
    _add_json(p_init)

    p_scaffold = registry_sub.add_parser(
        "scaffold", help="create one canonical native artifact package"
    )
    _add_registry_source(p_scaffold)
    p_scaffold.add_argument("artifact_kind", choices=_ARTIFACT_TYPES, metavar="KIND")
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
    _add_registry_finalize(p_scaffold)
    _add_json(p_scaffold)

    p_collection = registry_sub.add_parser(
        "collection",
        help="author a collection from artifacts this registry already holds",
    )
    _add_registry_source(p_collection)
    p_collection.add_argument("names", nargs=1, metavar="NAME")
    p_collection.add_argument(
        "--summary",
        required=True,
        metavar="TEXT",
        help="one-line collection description",
    )
    p_collection.add_argument(
        "--include",
        action="append",
        required=True,
        dest="collection_members",
        metavar="KIND/NAME",
        help="artifact already held by this registry (repeatable)",
    )
    _add_registry_finalize(p_collection)
    _add_json(p_collection)

    p_discover = registry_sub.add_parser(
        "discover",
        help="scan a foreign checkout and emit a reviewable vendoring manifest",
        description=(
            "Recognize conservative conventional shapes in an inert local checkout. The output "
            "is a vendor-batch manifest: candidates are rejected by default so discovery never "
            "turns a guess into registry content. Edit each accept field, then review the one "
            "atomic `registry vendor-batch` plan."
        ),
    )
    p_discover.add_argument(
        "--checkout",
        required=True,
        dest="discovery_checkout",
        metavar="DIR",
        help="foreign repository checkout to scan without following symlinks",
    )
    p_discover.add_argument(
        "--url", dest="native_url", required=True, metavar="URL", help="credential-free Git URL"
    )
    p_discover.add_argument(
        "--ref", default="main", metavar="REF", help="Git ref the later vendoring resolves"
    )
    p_discover.add_argument(
        "--artifact-version",
        default="1.0.0",
        metavar="VERSION",
        help="version proposed for every candidate (default: 1.0.0)",
    )
    p_discover.add_argument(
        "--profile",
        action="append",
        required=True,
        metavar="P[,P...]",
        help="target harness profile(s); comma-separated or repeated",
    )
    p_discover.add_argument(
        "--platform",
        action="append",
        required=True,
        metavar="PLATFORM",
        help="supported platform (repeatable)",
    )
    p_discover.add_argument(
        "--install-scope",
        action="append",
        choices=_INSTALL_SCOPES,
        dest="registry_scopes",
        default=[],
        help="supported install scope (repeatable; default: project)",
    )
    p_discover.add_argument(
        "--install-mode",
        action="append",
        choices=("copy", "symlink"),
        dest="registry_modes",
        default=[],
        help="supported install mode (repeatable; default: copy)",
    )
    p_discover.add_argument(
        "--review-policy",
        default="manual-review-v1",
        metavar="POLICY",
        help="approved review policy identifier (default: manual-review-v1)",
    )
    p_discover.add_argument(
        "--accept-all",
        action="store_true",
        dest="discovery_accept_all",
        help="mark every candidate accepted in the manifest; the batch still requires review",
    )
    p_discover.add_argument(
        "--output",
        dest="discovery_output",
        metavar="FILE",
        help="write the manifest to a new file instead of standard output",
    )

    p_format = registry_sub.add_parser("format", help="canonicalize registry JSON files")
    _add_registry_source(p_format)
    _add_check(p_format)
    _add_registry_finalize(p_format)
    _add_json(p_format)

    p_promote = registry_sub.add_parser(
        "promote-native",
        help="reference a native package upstream keeps: consumers reach it, upstream owns it",
        description=(
            "Add a reviewed reference to a canonical AART package in another repository, pinned to "
            "a resolved commit. The bytes stay upstream and this registry ships none of them: a "
            "consumer installing it reaches that origin, and upstream owns the version. Use "
            "`vendor` instead when the upstream is not an AART package, or when consumers must "
            "reach this registry only."
        ),
    )
    _add_registry_source(p_promote)
    p_promote.add_argument("artifact_kind", choices=_ARTIFACT_TYPES, metavar="KIND")
    p_promote.add_argument("names", nargs=1, metavar="NAME")
    p_promote.add_argument(
        "--url", dest="native_url", required=True, metavar="URL", help="credential-free Git URL"
    )
    p_promote.add_argument(
        "--ref", default="main", metavar="REF", help="Git ref to resolve (default: main)"
    )
    p_promote.add_argument(
        "--path",
        dest="native_path",
        required=True,
        metavar="DIR",
        help="package path inside the Git snapshot",
    )
    p_promote.add_argument(
        "--review-policy",
        default="manual-review-v1",
        metavar="POLICY",
        help="approved review policy identifier (default: manual-review-v1)",
    )
    _add_registry_finalize(p_promote)
    _add_json(p_promote)

    p_vendor = registry_sub.add_parser(
        "vendor",
        help="copy a foreign subtree in: this registry ships the bytes and owns the version",
        description=(
            "Copy a subtree of any Git repository into this registry as an owned package pinned "
            "to a resolved commit, with provenance recording where the bytes came from. The "
            "upstream needs no AART markers. This registry then owns the copy: it declares the "
            "version, and upstream fixes reach consumers only when it is vendored again. A "
            "successful vendor reports what was copied; it is not a safety claim. Use "
            "`promote-native` instead to reference a native AART package without copying it. A "
            "repository containing a symlink anywhere cannot be acquired, and a symlink inside "
            "the subtree is refused."
        ),
    )
    _add_registry_source(p_vendor)
    p_vendor.add_argument("artifact_kind", choices=_ARTIFACT_TYPES, metavar="KIND")
    p_vendor.add_argument("names", nargs=1, metavar="NAME")
    p_vendor.add_argument(
        "--url", dest="native_url", required=True, metavar="URL", help="credential-free Git URL"
    )
    p_vendor.add_argument(
        "--ref", default="main", metavar="REF", help="Git ref to resolve (default: main)"
    )
    p_vendor.add_argument(
        "--path",
        dest="native_path",
        required=True,
        metavar="DIR",
        help="subtree to copy, relative to the repository root",
    )
    p_vendor.add_argument(
        # Upstream declares no version AART can trust, and deriving one would be a guess presented
        # as a fact.  The registry owns the version, so the maintainer states it.
        "--artifact-version",
        required=True,
        metavar="VERSION",
        help="version this registry publishes the copy under",
    )
    p_vendor.add_argument(
        "--summary", required=True, metavar="TEXT", help="one-line artifact description"
    )
    p_vendor.add_argument(
        # Discovery fills the silence; it never overrules the maintainer.  AART reads an upstream
        # licence file, it does not adjudicate the grant, so the registry states what it publishes.
        "--license",
        dest="artifact_license",
        metavar="SPDX",
        help="license this registry records for the copy (default: read from the taken subtree)",
    )
    p_vendor.add_argument(
        "--profile",
        action="append",
        required=True,
        metavar="P[,P...]",
        help="target harness profile(s); comma-separated or repeated",
    )
    p_vendor.add_argument(
        "--platform",
        action="append",
        required=True,
        metavar="PLATFORM",
        help="supported platform (repeatable)",
    )
    p_vendor.add_argument(
        "--install-scope",
        action="append",
        choices=_INSTALL_SCOPES,
        dest="registry_scopes",
        default=[],
        help="supported install scope (repeatable; default: project)",
    )
    p_vendor.add_argument(
        "--install-mode",
        action="append",
        choices=("copy", "symlink"),
        dest="registry_modes",
        default=[],
        help="supported install mode (repeatable; default: copy)",
    )
    p_vendor.add_argument(
        "--setup-recipe",
        metavar="PATH",
        help="package-relative setup recipe you have already authored beside the payload",
    )
    p_vendor.add_argument(
        "--review-policy",
        default="manual-review-v1",
        metavar="POLICY",
        help="approved review policy identifier (default: manual-review-v1)",
    )
    _add_registry_finalize(p_vendor)
    _add_json(p_vendor)

    p_vendor_batch = registry_sub.add_parser(
        "vendor-batch",
        help="vendor accepted manifest candidates in one acquisition and one atomic review",
    )
    _add_registry_source(p_vendor_batch)
    p_vendor_batch.add_argument(
        "--manifest",
        required=True,
        dest="vendor_manifest",
        metavar="FILE",
        help="reviewed discovery/vendor manifest whose accepted artifacts to vendor",
    )
    _add_registry_finalize(p_vendor_batch)
    _add_json(p_vendor_batch)

    p_revendor = registry_sub.add_parser(
        "revendor",
        help="re-resolve one vendored copy's upstream and report, or apply what moved",
        description=(
            "Re-resolve the ref this artifact was vendored at and compare the subtree with the "
            "copy this registry ships. Reports up-to-date, changed, or unreachable; an upstream "
            "that cannot be read is never reported as up-to-date. Upstream declares no version "
            "AART can trust, so applying a change requires the version you state for it. "
            "`refresh-native` is the equivalent for a reference, where re-pinning is the whole "
            "change; here the bytes this registry ships are replaced."
        ),
    )
    _add_registry_source(p_revendor)
    p_revendor.add_argument("artifact_kind", choices=_ARTIFACT_TYPES, metavar="KIND")
    p_revendor.add_argument("names", nargs=1, metavar="NAME")
    p_revendor.add_argument(
        "--artifact-version",
        metavar="VERSION",
        help="version this registry publishes the moved copy under; without it, nothing is planned",
    )
    p_revendor.add_argument(
        "--review-policy",
        default="manual-review-v1",
        metavar="POLICY",
        help="approved review policy identifier (default: manual-review-v1)",
    )
    _add_check(p_revendor)
    _add_registry_finalize(p_revendor)
    _add_json(p_revendor)

    p_refresh = registry_sub.add_parser(
        "refresh-native",
        help="re-pin one referenced package to upstream's current commit",
        description=(
            "Re-resolve one `entries/` native reference and review the new immutable snapshot. It "
            "moves a pin; the delivered bytes are upstream's either way. `revendor` is the "
            "equivalent for a copy this registry owns, and it requires the version to publish."
        ),
    )
    _add_registry_source(p_refresh)
    p_refresh.add_argument("artifact_kind", choices=_ARTIFACT_TYPES, metavar="KIND")
    p_refresh.add_argument("names", nargs=1, metavar="NAME")
    _add_registry_finalize(p_refresh)
    _add_json(p_refresh)

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
        _add_registry_finalize(target)
        _add_json(target)

    p_audit = registry_sub.add_parser(
        "audit", help="audit review, provenance, setup, and available security metadata"
    )
    _add_registry_source(p_audit)
    p_audit.add_argument(
        "--check-upstream",
        action="store_true",
        help=(
            "resolve each vendored artifact's origin and report the ones behind upstream; "
            "unreachable origins are reported as unknown, and neither finding fails the audit"
        ),
    )
    _add_json(p_audit)

    p_publish = registry_sub.add_parser(
        "publish",
        help="lock, build, validate, audit, and commit every listed registry change",
        description=(
            "Prepare lock and index in memory, run validate and audit over that exact snapshot, "
            "and list every path Git would commit. Without --yes this is review-only. With --yes "
            "it writes the reviewed generated files and creates one commit; it never pushes."
        ),
    )
    _add_registry_source(p_publish)
    p_publish.add_argument(
        "-m", "--message", dest="publish_message", metavar="TEXT", help="commit subject"
    )
    _add_registry_finalize(p_publish)
    _add_json(p_publish)

    p_test = registry_sub.add_parser("test", help="run a compatibility validation fixture")
    _add_registry_source(p_test)
    p_test.add_argument(
        "--compatibility",
        choices=("minimum", "latest", "all"),
        default="all",
        help="compatibility point to validate (default: all)",
    )
    p_test.add_argument(
        # The upper compatibility point is the AART doing the publishing, not a version frozen in
        # the parser: a default that never moves tests a phantom release, so a registry whose floor
        # sits above it fails as "incompatible" while one below it proves nothing about today.
        "--latest-version",
        default=__version__,
        metavar="VERSION",
        help=f"latest compatible AART version under test (default: {__version__})",
    )
    _add_json(p_test)

    p_diff = registry_sub.add_parser("diff", help="show deterministic managed-file drift")
    _add_registry_source(p_diff)
    _add_json(p_diff)

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
    return Request(
        command=args.command,
        names=tuple(getattr(args, "names", None) or ()),
        profiles=_split_csv(getattr(args, "profile", None)),
        source_dir=getattr(args, "source_dir", None),
        project=getattr(args, "project", None),
        scope=getattr(args, "scope", "project"),
        artifact_kind=getattr(args, "artifact_kind", None),
        yes=bool(getattr(args, "yes", False)),
        expect=getattr(args, "expect", None),
        force=bool(getattr(args, "force", False)),
        dry_run=bool(getattr(args, "dry_run", False)),
        json=bool(getattr(args, "json", False)),
        prune=bool(getattr(args, "prune", False)),
        install_mode=getattr(args, "install_mode", None) or "copy",
        memory_mode=getattr(args, "memory_mode", None),
        ref=getattr(args, "ref", None),
        native_url=getattr(args, "native_url", None),
        native_path=getattr(args, "native_path", None),
        setup_recipe=getattr(args, "setup_recipe", None),
        review_policy=getattr(args, "review_policy", None),
        registry_action=getattr(args, "registry_action", None),
        check=bool(getattr(args, "check", False)),
        check_upstream=bool(getattr(args, "check_upstream", False)),
        strict=bool(getattr(args, "strict", False)),
        frozen=bool(getattr(args, "frozen", False)),
        source_id=getattr(args, "source_id", None),
        display_name=getattr(args, "display_name", None),
        usage_reporting_repository=getattr(args, "usage_reporting_repository", None),
        aart_repository=getattr(args, "aart_repository", None),
        aart_ref=getattr(args, "aart_ref", None),
        no_aart_stamp=bool(getattr(args, "no_aart_stamp", False)),
        summary=getattr(args, "summary", None),
        collection_members=tuple(getattr(args, "collection_members", ()) or ()),
        discovery_checkout=getattr(args, "discovery_checkout", None),
        discovery_output=getattr(args, "discovery_output", None),
        discovery_accept_all=bool(getattr(args, "discovery_accept_all", False)),
        vendor_manifest=getattr(args, "vendor_manifest", None),
        publish_message=getattr(args, "publish_message", None),
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
        registry_platforms=tuple(getattr(args, "platform", ()) or ()),
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
        source_action=getattr(args, "source_action", None),
        source_alias=getattr(args, "source_alias", None),
        source_kind=getattr(args, "source_kind", None),
        source_location=getattr(args, "source_location", None),
        source_make_default=getattr(args, "source_make_default", None),
        marketplace_action=getattr(args, "marketplace_action", None),
        receipt_action=getattr(args, "receipt_action", None),
        runtime_environment=getattr(args, "runtime_environment", None),
        offline=bool(getattr(args, "offline", False)),
        authorize_untrusted_source=bool(getattr(args, "authorize_untrusted_source", False)),
        authorize_custom_entrypoint=bool(getattr(args, "authorize_custom_entrypoint", False)),
        approve_setup_effects=bool(getattr(args, "approve_setup_effects", False)),
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
        if args and getattr(args, "project", None):
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
    return DISPATCH[args.command](request)


if __name__ == "__main__":
    raise SystemExit(main())
