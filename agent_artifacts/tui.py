"""Persistent interactive wizard. The second "skin" over the one command core.

docs/design/DESIGN.md §13 ("one core, two skins"): a bare ``agent-artifacts`` on a TTY launches this
selector; otherwise the CLI runs in flag mode. This module owns **no** consumer or upstream
mutation logic — it gathers role/action selections, assembles
:class:`~agent_artifacts.model.Request` values, and dispatches them through the exact same command
handlers the flag-mode CLI uses. The decision logic stays in the pure core / commands.

Two front-ends, one body:

* ``run()`` — the entry point ``cli._run_bare`` calls on a TTY. It prefers a ``curses``
  full-screen selector and **degrades to a plain ``input()``/``print()`` flow** when curses
  is unavailable or fails to initialise (no TTY, dumb terminal, ``curses`` import/`setupterm`
  error). Either way the *same* selection→Request→dispatch path runs.
* ``_run_text(read, write, ...)`` — the fallback flow, factored so I/O and source selection are
  injectable. Text and curses fold explicit input events into the same immutable
  :class:`~agent_artifacts.wizard.WizardSession`, then map only a finalized Review to the command
  core. This keeps the complete interaction headlessly testable without a real terminal.

Dispatch is resilient to integration order: it prefers ``cli.DISPATCH`` (WP-19) when present
and otherwise imports the command modules directly. Both routes call the *same* ``run``
functions, so no command logic is ever duplicated here.
"""

from __future__ import annotations

import functools
import os
import shutil
import sys
import traceback
from dataclasses import dataclass, replace
from typing import Callable, List, Literal, Mapping, Optional, Sequence, Tuple

from . import __version__
from .configuration.model import (
    OrganizationPolicy,
    SourceKind,
    UserConfiguration,
    default_user_configuration,
)
from .configuration.schema import configured_source_from_input
from .consumer import (
    ConsumerActionRequest,
    ConsumerApplicationService,
    ConsumerOutcome,
    ConsumerReview,
    render_consumer_outcome,
    render_consumer_review,
)
from .curation.model import (
    CurationAction,
    CurationRequest,
    render_curation_outcome,
    render_curation_review,
)
from .curation.runtime import CurationService, PreparedCuration
from .domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from .domain.identifiers import ArtifactCoordinate, SourceAlias
from .domain.result import Err as DomainErr
from .domain.result import Ok as DomainOk
from .domain.result import Result as DomainResult
from .marketplace.model import MarketplaceCatalog
from .model import (
    ArtifactType,
    Err,
    InstallMode,
    InstallScope,
    Request,
    Result,
    SetupQueueItem,
)
from .outcomes import ActionSummary, CommandOutcome, OutcomeItem, render_outcome
from .profiles.loader import load_profiles
from .profiles.model import Profile
from .profiles.scope import profile_for_scope
from .reporting.application import ReportingApplicationService
from .reporting.model import ReportingPlan, UsageReport
from .reporting.projection import (
    RegistryUsageReport,
    SetupReportState,
    usage_report_from_consumer,
    usage_reports_by_registry_from_consumer,
)
from .setup import (
    project_setup_review,
    recovery_messages,
    render_setup_outcome,
    render_setup_review,
)
from .sources.model import SourceSyncOutcome
from .tui_failures import (
    WizardOperation,
    WizardStageFailure,
    render_wizard_stage_failure,
    wizard_stage_failure,
)
from .tui_layout import (
    BOX_CHECKED,
    BOX_DISABLED,
    BOX_EMPTY,
    CHROME_ROWS,
    CONTENT_MEASURE,
    HINT_ORDER,
    READABLE_MEASURE,
    STAGE_CURRENT,
    columns,
    field_block,
    pane_budget,
    status_bar,
    wrap,
)
from .tui_marketplace import (
    MarketplaceArtifactRow,
    MarketplaceTarget,
    artifact_cells,
    render_artifact_detail,
    render_artifact_pane,
)
from .tui_sources import (
    SourceAdditionRequest,
    SourceManagementRequest,
    SourceRemovalRequest,
    SourceSelection,
    SourceStageRow,
    SourceStageView,
    build_source_stage,
    plan_source_addition,
    plan_source_management,
    plan_source_removal,
    render_source_addition_review,
    render_source_removal_review,
    render_source_row,
    render_source_sync_outcome,
    render_source_sync_review,
)
from .wizard import (
    BasketItem,
    WizardInput,
    WizardSession,
    WizardStage,
    can_finalize,
    initial_session,
    onboarding_lines,
    reconcile_basket,
    remember_position,
    render_header,
    request_quit,
    use_current_checkout,
)
from .wizard import (
    advance as wizard_advance,
)
from .wizard import (
    back as wizard_back,
)
from .wizard import (
    select as wizard_select,
)

# The three write actions the selector can drive; these are the verbs that build and dispatch a
# Request.
ACTIONS: Tuple[str, ...] = ("install", "update", "uninstall", "status")


@dataclass(frozen=True, slots=True)
class _RoleChoice:
    name: Literal["user", "maintainer"]
    label: str
    description: str


ROLES: Tuple[_RoleChoice, ...] = (
    _RoleChoice(
        "user",
        "User",
        "Install, update, or remove harness artifacts from configured registries.",
    ),
    _RoleChoice(
        "maintainer",
        "Maintainer",
        "Do the same, plus curate a canonical registry checkout.",
    ),
)

CANONICAL_MAINTAINER_ACTIONS: Tuple[Tuple[str, str], ...] = (
    ("validate", "Validate canonical registry protocol and generated evidence"),
    ("scaffold", "Scaffold one native artifact package for review"),
    ("promote-native", "Promote one reviewed native Git reference"),
    ("refresh-native", "Check and review one locked native reference update"),
    ("lock", "Resolve approved references into the committed lock"),
    ("build", "Build the payload-free marketplace index"),
    ("audit", "Audit review, provenance, setup, license, and security evidence"),
    ("diff", "Preview deterministic canonical-format diff without writing"),
    ("user", "Enter User workflows; AART never commits or pushes Maintainer changes"),
)

# Canonical artifact-type display order (matches commands.list / docs/design/DESIGN.md §4).
_TYPE_ORDER: Tuple[ArtifactType, ...] = ("skill", "guideline", "mcp", "hook", "memory")
_TYPE_ATTR = {
    "skill": "skills",
    "guideline": "guidelines",
    "mcp": "mcp",
    "hook": "hooks",
    "memory": "memory",
}

ReadFn = Callable[[str], str]
WriteFn = Callable[[str], None]
SourceFactory = Callable[[Request], Result]
DispatchFn = Callable[[Request], int]


def _unsupported_source_factory(_request: Request) -> Result:
    """Defend the removed direct-catalog seam for private legacy test callers."""

    raise RuntimeError("direct catalog sources have been removed")


SourceFinalizeFn = Callable[[SourceManagementRequest], DomainResult[object]]
SourceAdditionFinalizeFn = Callable[[SourceAdditionRequest], DomainResult[object]]
SourceRemovalFinalizeFn = Callable[[SourceRemovalRequest], DomainResult[object]]
SourceSyncRunFn = Callable[[SourceAlias], DomainResult[SourceSyncOutcome]]
ConsumerServiceFactory = Callable[[UserConfiguration], DomainResult[ConsumerApplicationService]]
ReportingServiceFactory = Callable[[UserConfiguration], DomainResult[ReportingApplicationService]]
CurationServiceFactory = Callable[[str], DomainResult[CurationService]]


@dataclass(frozen=True, slots=True)
class _RuntimeSourceStage:
    """The imperative source boundary injected into either human TUI frontend."""

    view: SourceStageView
    source_finalizer: SourceFinalizeFn | None
    source_addition_finalizer: SourceAdditionFinalizeFn | None
    source_removal_finalizer: SourceRemovalFinalizeFn | None = None
    source_sync_runner: SourceSyncRunFn | None = None


SourceStageLoader = Callable[[], DomainResult[_RuntimeSourceStage]]


@dataclass(frozen=True, slots=True)
class InstallModeChoice:
    """One user-facing installation-mode choice."""

    mode: InstallMode
    label: str
    description: str


INSTALL_MODE_CHOICES: Tuple[InstallModeChoice, ...] = (
    InstallModeChoice(
        "copy",
        "Copy (recommended)",
        "Install an independent snapshot into the target harness.",
    ),
    InstallModeChoice(
        "symlink",
        "Symlink",
        (
            "Live-link supported skills and hooks to a local catalog; file and merged "
            "artifacts selected through bundles use copy semantics."
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class InstallScopeChoice:
    """One explicit consumer configuration/state boundary."""

    scope: InstallScope
    label: str
    description: str


INSTALL_SCOPE_CHOICES: Tuple[InstallScopeChoice, ...] = (
    InstallScopeChoice(
        "project",
        "Project (recommended)",
        "Configure only the current repository.",
    ),
    InstallScopeChoice(
        "user",
        "User",
        "Configure the selected harnesses for the current user across projects.",
    ),
)


@dataclass(frozen=True, slots=True)
class _Choice:
    """One selectable catalog row: either a single artifact or a whole bundle.

    ``kind`` is ``"artifact"`` or ``"bundle"``. ``label`` is the human row text. ``key`` is
    ``(type, name)`` for an artifact (so we can build ``Request.names`` + ``type_filter``-free
    selection) or the bundle name for a bundle.
    """

    kind: Literal["artifact", "bundle", "profile"]
    name: str
    type: Optional[ArtifactType]
    label: str
    description: str = ""
    hidden_count: int = 0
    complete: bool = True
    enabled: bool = True
    reason: str = ""
    linked_count: int = 0
    copied_count: int = 0
    qualified_key: str = ""
    cells: Tuple[str, ...] = ()
    row: Optional[MarketplaceArtifactRow] = None


def _type_rank(t: ArtifactType) -> int:
    return _TYPE_ORDER.index(t) if t in _TYPE_ORDER else len(_TYPE_ORDER)


def _profile_supports(profile: Profile, art_type: ArtifactType) -> bool:
    """True when a profile has a target for ``art_type``."""
    return getattr(profile, _TYPE_ATTR[art_type], None) is not None


def _choice_label(
    kind: Literal["artifact", "bundle", "profile"],
    name: str,
    art_type: Optional[ArtifactType],
    description: str,
    status: str = "",
) -> str:
    """Render a one-line choice label from structured choice data."""
    if kind == "artifact" and art_type is not None:
        label = f"[{art_type}] {name}"
    elif kind == "bundle":
        label = f"[bundle] {name}"
    else:
        label = name
    if description:
        label += f" — {description}"
    if status:
        label += f" ({status})"
    return label


def _dispatch(request: Request) -> int:
    """Route *request* through the same handlers the flag-mode CLI uses.

    Prefers ``cli.DISPATCH`` (WP-19) when it exists; otherwise imports the command module
    for ``request.command`` directly. Both paths call the identical ``run`` function — this
    module duplicates **no** command logic.
    """
    try:
        from . import cli

        dispatch = getattr(cli, "DISPATCH", None)
    except Exception:  # pragma: no cover - cli import is trivial
        dispatch = None

    if isinstance(dispatch, Mapping) and request.command in dispatch:
        return int(dispatch[request.command](request))

    # Fallback: import the specific command module on demand (avoids importing all of them
    # and keeps this independent of WP-19's merge state).
    from importlib import import_module

    module = import_module(f".commands.{request.command}", package=__package__)
    return int(module.run(request))


_ORIGINAL_DISPATCH = _dispatch


def _dispatch_result(request: Request) -> CommandOutcome:
    """Dispatch a command through its structured result contract."""

    # Preserve the long-standing injectable dispatch seam used by headless frontend tests and
    # embedders. Production keeps the original function and takes the structured path below.
    if _dispatch is not _ORIGINAL_DISPATCH:
        code = int(_dispatch(request))
        item = (
            OutcomeItem(f"{request.command}-request", "up_to_date")
            if code == 0
            else OutcomeItem(f"{request.command}-request", "failed")
        )
        return CommandOutcome(
            exit_code=code,
            summary=ActionSummary(action=request.command, items=(item,)),
        )

    try:
        from . import cli

        dispatch = getattr(cli, "RESULT_DISPATCH", None)
    except Exception:  # pragma: no cover - cli import is trivial
        dispatch = None

    if isinstance(dispatch, Mapping) and request.command in dispatch:
        return dispatch[request.command](request)

    from importlib import import_module

    module = import_module(f".commands.{request.command}", package=__package__)
    execute = getattr(module, "execute", None)
    if callable(execute):
        return execute(request)

    code = _dispatch(request)
    item = (
        OutcomeItem(f"{request.command}-request", "up_to_date")
        if code == 0
        else OutcomeItem(f"{request.command}-request", "failed")
    )
    return CommandOutcome(
        exit_code=code,
        summary=ActionSummary(
            action=request.command,
            items=(item,),
        ),
    )


def _legacy_setup_stage_failure(request: Request, result: Err) -> WizardStageFailure:
    """Name the sole 0.1 setup-run bridge into the shared stage record.

    The setup queue is owned by Review and always runs after the frontend closed, so the record
    offers the terminal recovery only: there is no live stage left to retry into.
    """

    return WizardStageFailure(
        stage="review",
        operation="setup",
        diagnostics=(
            Diagnostic(
                DiagnosticCode("legacy-setup-run-failed"),
                Severity.ERROR,
                result.reason,
                details=(("legacy_exit_code", str(result.code)),),
            ),
        ),
        action=request.command,
        scope=request.scope,
        project=None,
        recoverable=False,
        choices=("quit",),
    )


def _run_post_install_setup(
    queue: Sequence[SetupQueueItem],
    request: Request,
    *,
    scope_root: str,
    read: ReadFn,
    write: WriteFn,
) -> int:
    """Reject the removed catalog setup path.

    Canonical setup is prepared and finalized by ``ConsumerApplicationService`` above.  This
    private shim only protects embedders that still call the former post-install hook.
    """

    del queue, request, scope_root, read
    write("error: direct catalog setup has been removed; use the canonical consumer workflow.")
    return 2


@dataclass(frozen=True, slots=True)
class _CanonicalSetupRun:
    exit_code: int
    reporting: Tuple[SetupReportState, ...]


def _setup_reporting_failure(status: str) -> Tuple[str, str] | None:
    if status in {"configured", "already-configured", "not-required"}:
        return None
    if status == "verification-failed":
        return ("verification", "setup-verification-failed")
    if status in {"rollback-incomplete", "rolled-back"}:
        return ("rollback", f"setup-{status}")
    if status in {"queue-declined", "planning-failed"}:
        return ("queue", f"setup-{status}")
    return ("setup-installer", f"setup-{status}")


def _setup_reporting_key(
    review: ConsumerReview,
    coordinate: ArtifactCoordinate,
    profile: str,
    scope: str,
) -> str:
    """Bind an unversioned setup identity back to its exact consumer Review item."""

    matches = tuple(
        item.key
        for item in review.items
        if item.coordinate.source == coordinate.source
        and item.coordinate.artifact == coordinate.artifact
        and item.profile == profile
        and item.scope == scope
    )
    if len(matches) == 1:
        return matches[0]
    return f"{coordinate}#{profile}/{scope}"


def _canonical_setup_run(
    service: ConsumerApplicationService,
    review: ConsumerReview,
    outcome: ConsumerOutcome,
    *,
    read: ReadFn,
    write: WriteFn,
) -> _CanonicalSetupRun:
    """Prepare, separately review, and sequentially execute canonical post-payload setup."""

    if not any(item.setup_status == "pending" for item in outcome.items):
        return _CanonicalSetupRun(0, ())
    queue = service.setup_queue(review, outcome)
    if queue.failures and all("authoriz" in item.detail.casefold() for item in queue.failures):
        write("Setup needs explicit permission for untrusted/custom source capabilities.")
        answer = _read_line(read, "Authorize these reviewed setup capabilities? [y/N]: ")
        if answer is not None and answer.strip().lower() in ("y", "yes"):
            queue = service.setup_queue(
                review,
                outcome,
                authorize_untrusted_source=True,
                authorize_custom_entrypoint=True,
            )
    if queue.failures:
        write("Payload outcome: installed; setup planning did not change installed payloads.")
    for failure in queue.failures:
        key, _separator, selector = failure.key.partition("#")
        profile, _separator, scope = selector.partition("/")
        for line in render_setup_outcome(
            artifact=key,
            profile=profile or "selected profile",
            scope=scope or "selected scope",
            status="planning-failed",
            detail=failure.detail,
            retry_command=f"aart setup retry --artifact {key}",
            manual=failure.manual,
        ):
            write(line)
    if not queue.plans:
        plan_failures = tuple(
            SetupReportState(
                failure.key,
                "planning-failed",
                failure_phase="queue",
                failure_code="setup-planning-failed",
            )
            for failure in queue.failures
        )
        return _CanonicalSetupRun(1 if queue.failures else 0, plan_failures)
    write("Review setup queue (runs sequentially after installed payloads):")
    # Keyed by identity because one ``step_id`` is only unique inside its own plan, and every
    # plan stays referenced by ``queue.plans`` for the whole run.
    safe_effects = {}
    for plan in queue.plans:
        for line in render_setup_review(plan.legacy_plan):
            write(line)
        safe_effects.update(
            {
                id(effect): rendered
                for effect, rendered in zip(
                    plan.legacy_plan.effects,
                    project_setup_review(plan.legacy_plan).effects,
                    strict=True,
                )
            }
        )
    answer = _read_line(read, "Finalize this setup queue? [y/N]: ")
    if answer is None or answer.strip().lower() not in ("y", "yes"):
        write("Payload outcome: installed; installed payloads were not rolled back.")
        write("Setup remains pending.")
        for plan in queue.plans:
            for line in render_setup_outcome(
                artifact=str(plan.request.coordinate),
                profile=plan.request.profile,
                scope=plan.request.scope,
                status="declined",
                detail="setup was declined before any effect ran",
                manual=project_setup_review(plan.legacy_plan).manual,
            ):
                write(line)
        declined = tuple(
            SetupReportState(
                _setup_reporting_key(
                    review,
                    plan.request.coordinate,
                    plan.request.profile,
                    plan.request.scope,
                ),
                "queue-declined",
                plan.recipe_digest,
                "queue",
                "setup-queue-declined",
            )
            for plan in queue.plans
        )
        planning = tuple(
            SetupReportState(
                failure.key,
                "planning-failed",
                failure_phase="queue",
                failure_code="setup-planning-failed",
            )
            for failure in queue.failures
        )
        return _CanonicalSetupRun(1, (*declined, *planning))

    def consent(effect) -> bool:
        reviewed = safe_effects.get(id(effect))
        if reviewed is None:
            write("Approve this reviewed setup effect.")
        else:
            write(f"Approve {reviewed.index}. {reviewed.identity}. {reviewed.recovery}.")
        decision = _read_line(read, "Approve this exact effect? [y/N]: ")
        return decision is not None and decision.strip().lower() in ("y", "yes")

    setup_outcome = service.finalize_setup_queue(queue, consent=consent)
    plan_by_key = {
        f"{plan.request.coordinate}#{plan.request.profile}/{plan.request.scope}": plan
        for plan in queue.plans
    }
    write(
        f"Setup outcome: configured={setup_outcome.configured}, "
        f"incomplete={setup_outcome.incomplete}."
    )
    for item in setup_outcome.items:
        setup_plan = plan_by_key.get(f"{item.coordinate}#{item.profile}/{item.scope}")
        for line in render_setup_outcome(
            artifact=str(item.coordinate),
            profile=item.profile,
            scope=item.scope,
            status=item.setup_status.value,
            detail=item.detail,
            retry_command=(
                "" if item.successful else f"aart setup retry --artifact {item.coordinate}"
            ),
            recovery=() if item.record is None else recovery_messages(item.record),
            manual=None
            if setup_plan is None
            else project_setup_review(setup_plan.legacy_plan).manual,
        ):
            write(line)
    reported_states: List[SetupReportState] = []
    for item in setup_outcome.items:
        key = f"{item.coordinate}#{item.profile}/{item.scope}"
        reporting_key = _setup_reporting_key(
            review,
            item.coordinate,
            item.profile,
            item.scope,
        )
        status = item.setup_status.value
        failure_spec = _setup_reporting_failure(status)
        setup_plan = plan_by_key.get(key)
        reported_states.append(
            SetupReportState(
                reporting_key,
                status,
                None if setup_plan is None else setup_plan.recipe_digest,
                None if failure_spec is None else failure_spec[0],
                None if failure_spec is None else failure_spec[1],
            )
        )
    reported_states.extend(
        SetupReportState(
            queue_failure.key,
            "planning-failed",
            failure_phase="queue",
            failure_code="setup-planning-failed",
        )
        for queue_failure in queue.failures
    )
    return _CanonicalSetupRun(
        0 if setup_outcome.incomplete == 0 and not queue.failures else 1,
        tuple(reported_states),
    )


def _run_canonical_setup_queue(
    service: ConsumerApplicationService,
    review: ConsumerReview,
    outcome: ConsumerOutcome,
    *,
    read: ReadFn,
    write: WriteFn,
) -> int:
    return _canonical_setup_run(service, review, outcome, read=read, write=write).exit_code


def _offer_usage_report(
    service: ReportingApplicationService | None,
    event: UsageReport,
    *,
    read: ReadFn,
    write: WriteFn,
) -> None:
    """Offer/submit after terminal outcomes; every failure is warning-only."""

    if service is None:
        return
    prepared = service.prepare(event)
    if isinstance(prepared, DomainErr):
        write("warning: usage report could not be prepared; the artifact outcome is unchanged")
        return
    plan = prepared.value
    if plan is None:
        return
    _offer_prepared_usage_report(service, plan, read=read, write=write)


def _offer_prepared_usage_report(
    service: ReportingApplicationService,
    plan: ReportingPlan,
    *,
    read: ReadFn,
    write: WriteFn,
) -> None:
    target = f"{plan.destination.host}/{plan.destination.repository}"
    if plan.destination.mode.value == "prompt":
        answer = _read_line(read, f"Share this redacted usage report with {target}? [y/N]: ")
        if answer is None or answer.strip().lower() not in ("y", "yes"):
            write("Usage report was not submitted.")
            return
    write("Exact redacted usage report payload:")
    write(plan.payload.decode("utf-8").strip())
    if plan.destination.mode.value == "prompt":
        answer = _read_line(read, "Open the prefilled GitHub issue? [y/N]: ")
        if answer is None or answer.strip().lower() not in ("y", "yes"):
            write("Usage report was not submitted.")
            return
    submitted = service.submit(plan)
    if isinstance(submitted, DomainErr):
        write("warning: usage report submission failed; the artifact outcome is unchanged")
        return
    write(
        "Usage report opened in the browser."
        if submitted.value.status == "browser-opened"
        else "Usage report submitted."
    )


def _offer_routed_usage_reports(
    service: ReportingApplicationService | None,
    combined: UsageReport,
    routed: Tuple[RegistryUsageReport, ...],
    *,
    read: ReadFn,
    write: WriteFn,
) -> None:
    if service is None:
        return
    prepared = service.prepare_routed(combined, routed)
    if isinstance(prepared, DomainErr):
        write("warning: usage reports could not be prepared; the artifact outcome is unchanged")
        return
    if prepared.value:
        write("Optional redacted usage reports are available for these artifact registries:")
        for plan in prepared.value:
            write(f"  - {plan.destination.host}/{plan.destination.repository}")
    for plan in prepared.value:
        _offer_prepared_usage_report(service, plan, read=read, write=write)


def _complete_canonical_consumer_action(
    consumer: ConsumerApplicationService,
    review: ConsumerReview,
    outcome: ConsumerOutcome,
    reporting: ReportingApplicationService | None,
    *,
    read: ReadFn,
    write: WriteFn,
    failure_context: InternalFailureContext | None = None,
) -> int:
    if failure_context is not None:
        failure_context.capture_operation("setup")
    setup = _canonical_setup_run(consumer, review, outcome, read=read, write=write)
    if failure_context is not None:
        failure_context.capture_operation("reporting")
    try:
        event = usage_report_from_consumer(
            review,
            outcome,
            setup.reporting,
            aart_version=__version__,
            interface="tui",
        )
        routed = usage_reports_by_registry_from_consumer(
            review,
            outcome,
            setup.reporting,
            aart_version=__version__,
            interface="tui",
        )
    except ValueError:
        write("warning: usage report projection failed; the artifact outcome is unchanged")
        return setup.exit_code
    _offer_routed_usage_reports(reporting, event, routed, read=read, write=write)
    return setup.exit_code


def _render_result(result: CommandOutcome, write: WriteFn) -> int:
    for line in render_outcome(result):
        write(line)
    return result.exit_code


def _cancel(write: WriteFn, message: str = "Cancelled; no changes were made.") -> int:
    if message != "Cancelled; no changes were made.":
        write(message)
        return 0
    return _render_result(
        CommandOutcome(
            0,
            ActionSummary(
                action="cancelled",
                items=(OutcomeItem("selection", "cancelled"),),
            ),
        ),
        write,
    )


# --------------------------------------------------------------------------- #
# Text / fallback flow — fully injectable, headless-testable.                   #
# --------------------------------------------------------------------------- #


def _empty_source_stage_view() -> SourceStageView:
    """Return the real no-source state for private frontend tests without filesystem effects."""

    projected = build_source_stage(
        default_user_configuration(),
        OrganizationPolicy(1),
        {},
        first_run=True,
    )
    assert isinstance(projected, DomainOk)
    return projected.value


def _runtime_source_stage_context(
    *,
    source_dir: Optional[str],
    repo: Optional[str],
    user_home: Optional[str],
) -> DomainResult[_RuntimeSourceStage]:
    """Load configured sources and current managed health at the imperative TUI boundary."""

    if source_dir is not None or repo is not None:
        return DomainErr(
            (
                Diagnostic(
                    DiagnosticCode("legacy-source-rejected"),
                    Severity.ERROR,
                    "direct catalog directories and repository aliases are no longer supported",
                    remediation=("add a canonical registry in Sources instead",),
                ),
            )
        )

    import time

    from .application.configuration import (
        ConfigurationPorts,
        ConfigurationRequest,
        load_configuration,
        save_user_configuration_checked,
    )
    from .application.source_management import (
        finalize_source_addition,
        finalize_source_management,
        finalize_source_removal,
    )
    from .application.sources import SourceStatusRequest, source_status
    from .configuration.paths import Platform, resolve_config_paths
    from .configuration.policy import RuntimeOverrides
    from .io.config_cas import checked_config_writer
    from .io.config_store import (
        read_configuration,
        recover_configuration,
        write_configuration,
    )
    from .io.source_store import read_current_source
    from .sources.model import CurrentSourceRequest, source_instance_id, source_store_paths

    platform = Platform.DARWIN if sys.platform == "darwin" else Platform.LINUX
    home = os.path.abspath(user_home or os.path.expanduser("~"))
    paths = resolve_config_paths(
        platform,
        home=home,
        xdg_config_home=os.environ.get("XDG_CONFIG_HOME"),
        xdg_data_home=os.environ.get("XDG_DATA_HOME"),
        xdg_cache_home=os.environ.get("XDG_CACHE_HOME"),
    )
    ports = ConfigurationPorts(
        read_configuration,
        write_configuration,
        recover_configuration,
        checked_config_writer,
    )
    loaded = load_configuration(
        ConfigurationRequest(paths, RuntimeOverrides(), content_required=False),
        ports,
    )
    if isinstance(loaded, DomainErr):
        return loaded
    configuration = loaded.value.user_configuration
    policy = loaded.value.effective.policy
    now = int(time.time())
    health = {}
    for source in configuration.sources:
        store_paths = source_store_paths(paths.data_root, source_instance_id(source))
        health[source.alias] = source_status(
            SourceStatusRequest(
                CurrentSourceRequest(store_paths, source.alias),
                now,
                configuration.sync.max_age_seconds,
            ),
            read_current_source,
        )
    projected = build_source_stage(
        configuration,
        policy,
        health,
        first_run=loaded.value.first_run is not None,
    )
    if isinstance(projected, DomainErr):
        return projected

    def refreshed_configuration(
        expected_before: UserConfiguration, expected_policy: OrganizationPolicy
    ):
        refreshed = load_configuration(
            ConfigurationRequest(paths, RuntimeOverrides(), content_required=False),
            ports,
        )
        if isinstance(refreshed, DomainErr):
            return refreshed
        if refreshed.value.recovery is not None:
            return DomainErr(
                (
                    Diagnostic(
                        DiagnosticCode("config-invalid"),
                        Severity.ERROR,
                        "user configuration is invalid; recover it before changing sources",
                        remediation=("recover the configuration and retry",),
                    ),
                )
            )
        if (
            refreshed.value.user_configuration != expected_before
            or refreshed.value.effective.policy != expected_policy
        ):
            return DomainErr(
                (
                    Diagnostic(
                        DiagnosticCode("source-selection-invalid"),
                        Severity.ERROR,
                        "source configuration or organization policy changed after Review",
                        remediation=("return to Sources and review the latest values",),
                    ),
                )
            )
        return DomainOk(refreshed.value)

    def finalize(request: SourceManagementRequest) -> DomainResult[object]:
        refreshed = refreshed_configuration(request.before, request.policy)
        if isinstance(refreshed, DomainErr):
            return refreshed
        return finalize_source_management(
            request,
            # CFG02: name the exact state just revalidated, so a writer that lands between this
            # check and the replace is refused instead of silently overwritten.
            lambda desired, active_policy: save_user_configuration_checked(
                desired,
                active_policy,
                paths,
                ports,
                expected_digest=refreshed.value.observed_digest,
            ),
        )

    def finalize_addition(request: SourceAdditionRequest) -> DomainResult[object]:
        """Acquire a safe immutable snapshot before writing the new configured origin."""

        current = refreshed_configuration(request.before, request.policy)
        if isinstance(current, DomainErr):
            return current
        from .sources.runtime import sync_configured_source

        synchronized = sync_configured_source(request.source, data_root=paths.data_root)
        if isinstance(synchronized, DomainErr):
            return synchronized
        # Source fetching can take time; fail closed if config or policy changed before its write.
        after_sync = refreshed_configuration(request.before, request.policy)
        if isinstance(after_sync, DomainErr):
            return after_sync
        return finalize_source_addition(
            request,
            lambda desired, active_policy: save_user_configuration_checked(
                desired,
                active_policy,
                paths,
                ports,
                expected_digest=after_sync.value.observed_digest,
            ),
        )

    def finalize_removal(request: SourceRemovalRequest) -> DomainResult[object]:
        """Discard the managed snapshot first, then write the shortened configuration once."""

        current = refreshed_configuration(request.before, request.policy)
        if isinstance(current, DomainErr):
            return current
        from .sources.runtime import discard_configured_source

        discarded = discard_configured_source(request.source, data_root=paths.data_root)
        if isinstance(discarded, DomainErr):
            return discarded
        # Discarding takes a lock and touches the disk; refuse a stale write the same way the
        # addition path does rather than overwriting whatever landed meanwhile.
        after_discard = refreshed_configuration(request.before, request.policy)
        if isinstance(after_discard, DomainErr):
            return after_discard
        return finalize_source_removal(
            request,
            lambda desired, active_policy: save_user_configuration_checked(
                desired,
                active_policy,
                paths,
                ports,
                expected_digest=after_discard.value.observed_digest,
            ),
        )

    def run_sync(alias: SourceAlias) -> DomainResult[SourceSyncOutcome]:
        """Refresh one configured origin's snapshot; this never writes user configuration."""

        from .sources.runtime import sync_configured_source

        selected = tuple(source for source in configuration.sources if source.alias == alias)
        if not selected:
            return DomainErr(
                (
                    Diagnostic(
                        DiagnosticCode("source-selection-invalid"),
                        Severity.ERROR,
                        f"no configured source has alias {alias}",
                        remediation=("return to Sources and choose a configured source",),
                    ),
                )
            )
        return sync_configured_source(selected[0], data_root=paths.data_root)

    return DomainOk(
        _RuntimeSourceStage(
            projected.value,
            finalize,
            finalize_addition,
            finalize_removal,
            run_sync,
        )
    )


def _source_choice_rows(view: SourceStageView) -> Tuple[_Choice, ...]:
    rows = tuple(
        _Choice(
            "profile",
            row.source.alias.value,
            None,
            render_source_row(row),
            description=(
                "Use this source in the marketplace. "
                + (row.reason if row.reason else "Its health and policy facts are shown above.")
            ),
            enabled=row.selectable,
            reason=row.reason,
        )
        for row in view.rows
    )
    if view.allow_no_source:
        rows += (
            _Choice(
                "profile",
                "no-source",
                None,
                "Continue without sources — exit cleanly without installing artifacts.",
                description="Do not force a registry or direct source during this run.",
            ),
        )
    return rows


def _source_selection_from_indices(
    view: SourceStageView,
    indices: Sequence[int],
) -> DomainErr | SourceSelection:
    no_source_index = len(view.rows)
    no_source = view.allow_no_source and no_source_index in indices
    aliases = tuple(
        view.rows[index].source.alias for index in indices if 0 <= index < len(view.rows)
    )
    planned = plan_source_management(view, aliases, no_source=no_source)
    return planned if isinstance(planned, DomainErr) else planned.value


def _selected_source_row(
    view: SourceStageView,
    indices: Sequence[int],
) -> SourceStageRow | None:
    """Map a Sources cursor position back to a configured row, ignoring the no-source row."""

    for index in indices:
        if 0 <= index < len(view.rows):
            return view.rows[index]
    return None


def _domain_feedback(result: DomainErr) -> str:
    """Summarize a recoverable list-local diagnostic in the list's fixed feedback slot."""

    first, *remaining = result.diagnostics
    suffix = "" if not remaining else f" (+{len(remaining)} more)"
    return _ellipsize(
        f"{first.severity.value} [{first.code.value}]: {first.message}{suffix}",
        CONTENT_MEASURE,
    )


def _prompt_source_stage_text(
    session: WizardSession,
    view: SourceStageView,
    read: ReadFn,
    write: WriteFn,
) -> WizardInput | SourceSelection:
    write(
        "Choose enabled artifact sources. Registries are optional unless organization policy "
        "marks one as required."
    )
    choices = _source_choice_rows(view)
    for index, choice in enumerate(choices, start=1):
        write(f"  {index:>2}. {choice.label}")
    if not view.rows:
        write("No sources are configured. Enter 'a' to add a registry or compatible source.")
    else:
        write("Enter 'a' to add another registry or compatible source.")
        write(
            "Enter 's' to synchronize a configured source, or 'r' to remove one. Synchronizing "
            "refreshes what is available to install or update; removing forgets the source and "
            "its downloaded snapshot."
        )
    if view.unconfigured_recommended:
        write(
            "Organization-recommended aliases needing configuration: "
            + ", ".join(alias.value for alias in view.unconfigured_recommended)
        )
    if view.unconfigured_required:
        write(
            "Organization-required aliases needing configuration: "
            + ", ".join(alias.value for alias in view.unconfigured_required)
        )
    selected_aliases = (
        set() if session.source_selection is None else set(session.source_selection.enabled_aliases)
    )
    selected = tuple(
        index for index, row in enumerate(view.rows) if row.source.alias in selected_aliases
    )
    if session.source_selection is not None and session.source_selection.no_source:
        selected += (len(view.rows),)
    elif session.source_selection is None:
        selected = tuple(index for index, row in enumerate(view.rows) if row.source.enabled)
    write(f"Selected: {len(selected)} source option(s)")
    while True:
        event = _prompt_wizard_indices(
            read,
            write,
            (
                "Source(s) (a=add, s=sync, r=remove, b=back, q=quit): "
                if view.rows
                else "Source(s) (a=add, b=back, q=quit): "
            ),
            choices,
            selected=selected,
            allow_add=True,
            allow_source_maintenance=bool(view.rows),
        )
        if event.kind != "confirm":
            return event
        planned = _source_selection_from_indices(view, event.selected)
        if isinstance(planned, DomainErr):
            write(_domain_feedback(planned))
            continue
        return planned


def _source_kind_choices(view: SourceStageView) -> tuple[tuple[SourceKind, str], ...]:
    choices: tuple[tuple[SourceKind, str], ...] = (
        (
            SourceKind.REGISTRY_GIT,
            "Registry Git source — reviewed marketplace with compiled lock and index.",
        ),
    )
    if view.allow_direct_sources:
        choices += (
            (
                SourceKind.SOURCE_GIT,
                "Direct Git source — any compatible native artifact repository.",
            ),
            (
                SourceKind.SOURCE_LOCAL,
                "Local source — a compatible directory on this machine.",
            ),
        )
    return choices


def _prompt_source_value(
    read: ReadFn,
    prompt: str,
    *,
    default: str | None = None,
) -> str | WizardInput:
    """Read one source-setup field without leaking blank/quit/back ambiguity into callers."""

    line = _read_line(read, prompt)
    if line is None:
        return WizardInput("quit")
    answer = line.strip()
    if answer.lower() in ("q", "quit"):
        return WizardInput("quit")
    if answer.lower() in ("b", "back"):
        return WizardInput("back")
    if not answer and default is not None:
        return default
    return answer


def _prompt_source_addition_text(
    view: SourceStageView,
    read: ReadFn,
    write: WriteFn,
) -> WizardInput | SourceAdditionRequest:
    """Collect and review one source origin before its sync-and-save runtime boundary."""

    choices = _source_kind_choices(view)
    write("Add an artifact source:")
    for index, (_kind, label) in enumerate(choices, start=1):
        write(f"  {index:>2}. {label}")
    while True:
        raw_kind = _prompt_source_value(
            read,
            "Source type (b=back, q=quit): ",
        )
        if isinstance(raw_kind, WizardInput):
            return raw_kind
        if not raw_kind.isdigit() or not 1 <= int(raw_kind) <= len(choices):
            write(f"Please enter a number between 1 and {len(choices)}, 'b', or 'q'.")
            continue
        kind = choices[int(raw_kind) - 1][0]
        default_alias = {
            SourceKind.REGISTRY_GIT: "registry",
            SourceKind.SOURCE_GIT: "source",
            SourceKind.SOURCE_LOCAL: "local",
        }[kind]
        alias = _prompt_source_value(
            read,
            f"Source alias [{default_alias}] (b=back, q=quit): ",
            default=default_alias,
        )
        if isinstance(alias, WizardInput):
            return alias
        location_label = "Local directory" if kind is SourceKind.SOURCE_LOCAL else "Git URL"
        location = _prompt_source_value(read, f"{location_label} (b=back, q=quit): ")
        if isinstance(location, WizardInput):
            return location
        if not location:
            write(f"{location_label} is required.")
            continue
        ref: str | None = None
        if kind is not SourceKind.SOURCE_LOCAL:
            prompted_ref = _prompt_source_value(
                read,
                "Git ref [main] (b=back, q=quit): ",
                default="main",
            )
            if isinstance(prompted_ref, WizardInput):
                return prompted_ref
            ref = prompted_ref
        parsed = configured_source_from_input(alias, kind, location, ref)
        if isinstance(parsed, DomainErr):
            _write_domain_diagnostics(parsed, write)
            continue
        planned = plan_source_addition(
            view,
            parsed.value,
            make_default=not any(row.source.is_registry for row in view.rows),
        )
        if isinstance(planned, DomainErr):
            _write_domain_diagnostics(planned, write)
            continue
        for line in render_source_addition_review(planned.value):
            write(line)
        answer = _read_line(
            read,
            "Synchronize and save this source? [y/N] (b=back, q=quit): ",
        )
        choice = "q" if answer is None else answer.strip().lower()
        if choice in ("b", "back"):
            return WizardInput("back")
        if choice in ("q", "quit"):
            return WizardInput("quit")
        if choice in ("y", "yes", "f", "finalize"):
            return planned.value
        write("Source setup was not finalized; no source was synchronized or saved.")
        return WizardInput("back")


def _prompt_source_confirmation(read: ReadFn, prompt: str) -> bool | WizardInput:
    """Read one reviewed yes/no decision, keeping navigation distinct from a plain refusal."""

    answer = _read_line(read, prompt)
    choice = "q" if answer is None else answer.strip().lower()
    if choice in ("b", "back"):
        return WizardInput("back")
    if choice in ("q", "quit"):
        return WizardInput("quit")
    return choice in ("y", "yes", "f", "finalize")


def _prompt_source_row_text(
    view: SourceStageView,
    read: ReadFn,
    write: WriteFn,
    *,
    action: str,
) -> WizardInput | SourceStageRow:
    """Pick one configured source by the number shown in the Sources list, or by its alias."""

    write(f"Which source do you want to {action}?")
    for index, row in enumerate(view.rows, start=1):
        write(f"  {index:>2}. {render_source_row(row)}")
    while True:
        answer = _prompt_source_value(read, f"Source to {action} (b=back, q=quit): ")
        if isinstance(answer, WizardInput):
            return answer
        if answer.isdigit() and 1 <= int(answer) <= len(view.rows):
            return view.rows[int(answer) - 1]
        matched = tuple(row for row in view.rows if row.source.alias.value == answer)
        if matched:
            return matched[0]
        write(f"Please enter a number between 1 and {len(view.rows)}, an alias, 'b', or 'q'.")


def _prompt_source_sync_text(
    view: SourceStageView,
    read: ReadFn,
    write: WriteFn,
) -> WizardInput | SourceStageRow:
    """Review one configured origin before its snapshot is fetched again."""

    picked = _prompt_source_row_text(view, read, write, action="synchronize")
    if isinstance(picked, WizardInput):
        return picked
    for line in render_source_sync_review(picked):
        write(line)
    confirmed = _prompt_source_confirmation(
        read,
        "Synchronize this source now? [y/N] (b=back, q=quit): ",
    )
    if isinstance(confirmed, WizardInput):
        return confirmed
    if confirmed:
        return picked
    write("Source was not synchronized; its snapshot is unchanged.")
    return WizardInput("back")


def _prompt_source_removal_text(
    view: SourceStageView,
    read: ReadFn,
    write: WriteFn,
) -> WizardInput | SourceRemovalRequest:
    """Review one unsubscribe before the configuration entry and its snapshot are dropped."""

    while True:
        picked = _prompt_source_row_text(view, read, write, action="remove")
        if isinstance(picked, WizardInput):
            return picked
        planned = plan_source_removal(view, picked.source.alias)
        if isinstance(planned, DomainErr):
            _write_domain_diagnostics(planned, write)
            continue
        for line in render_source_removal_review(planned.value):
            write(line)
        confirmed = _prompt_source_confirmation(
            read,
            "Remove this source and delete its snapshot? [y/N] (b=back, q=quit): ",
        )
        if isinstance(confirmed, WizardInput):
            return confirmed
        if confirmed:
            return planned.value
        write("Source was not removed; nothing was deleted.")
        return WizardInput("back")


def _finalize_source_selection(
    session: WizardSession,
    source_finalizer: Optional[SourceFinalizeFn],
    write: WriteFn,
) -> DomainErr | None:
    """Persist the reviewed source selection, preserving expected failures for the frontend."""

    selected = session.source_selection
    if selected is None or not selected.request.operations:
        return None
    if source_finalizer is None:
        return DomainErr(
            (
                Diagnostic(
                    DiagnosticCode("source-unavailable"),
                    Severity.ERROR,
                    "source configuration cannot be saved by this TUI runtime",
                    remediation=("return to Sources and retry with an available TUI runtime",),
                ),
            )
        )
    finalized = source_finalizer(selected.request)
    if isinstance(finalized, DomainErr):
        return finalized
    count = len(selected.request.operations)
    write(f"Sources: applied {count} reviewed configuration change(s).")
    return None


@dataclass(frozen=True, slots=True)
class _UserWizardReadModel:
    choices: Tuple[_Choice, ...]
    profiles_map: Mapping[str, Profile]
    source_label: str = ""
    source_root: str = ""
    marketplace_rows: Tuple[MarketplaceArtifactRow, ...] = ()


def _basket_key(choice: _Choice) -> str:
    if choice.qualified_key:
        return choice.qualified_key
    return (
        f"{choice.type}/{choice.name}"
        if choice.kind == "artifact" and choice.type is not None
        else f"{choice.kind}/{choice.name}"
    )


def _basket_item(choice: _Choice) -> BasketItem:
    return BasketItem(
        "bundle" if choice.kind == "bundle" else "artifact",
        _basket_key(choice),
        choice.label,
        choice.description,
    )


def _canonical_choice(row: MarketplaceArtifactRow) -> _Choice:
    """One list row. Identity and summary here; every evidence field lives in the record (D6)."""

    return _Choice(
        "artifact",
        row.identity.name,
        row.identity.kind,  # type: ignore[arg-type]
        f"{row.key} — {row.summary}",
        description=row.summary,
        enabled=row.compatible,
        reason="; ".join(reason.message for reason in row.reasons),
        linked_count=sum(mode == "symlink" for mode in row.actual_modes),
        copied_count=sum(mode == "copy" for mode in row.actual_modes),
        qualified_key=row.key,
        cells=artifact_cells(row),
        row=row,
    )


def _canonical_collection_choices(
    catalog: MarketplaceCatalog,
    rows: Tuple[MarketplaceArtifactRow, ...],
    *,
    sources: Tuple[SourceAlias, ...] = (),
) -> Tuple[_Choice, ...]:
    by_coordinate = {row.coordinate: row for row in rows}
    selected_sources = frozenset(sources)
    choices = []
    for collection in catalog.collections:
        if selected_sources and collection.coordinate.source not in selected_sources:
            continue
        member_rows = tuple(by_coordinate.get(member) for member in collection.members)
        missing = sum(row is None for row in member_rows)
        available = tuple(row for row in member_rows if row is not None)
        reasons = tuple(sorted({reason.message for row in available for reason in row.reasons}))
        enabled = missing == 0 and all(row.compatible for row in available)
        reason_parts = []
        if missing:
            reason_parts.append(f"{missing} member(s) unavailable")
        reason_parts.extend(reasons)
        reason = "; ".join(reason_parts)
        status = "" if enabled else f" — unavailable: {reason}"
        members = ", ".join(str(member) for member in collection.members)
        choices.append(
            _Choice(
                "bundle",
                collection.coordinate.name,
                None,
                f"[collection] {collection.coordinate} — {collection.summary} "
                f"({len(collection.members)} members){status}",
                description=f"{collection.summary} Members: {members}.",
                enabled=enabled,
                reason=reason,
                linked_count=sum("symlink" in row.actual_modes for row in available),
                copied_count=sum("copy" in row.actual_modes for row in available),
                qualified_key=str(collection.coordinate),
                cells=(
                    f"[collection] {collection.coordinate}",
                    "available" if enabled else "unavailable",
                    f"{len(collection.members)} members",
                ),
            )
        )
    return tuple(choices)


def _write_wizard_header(session: WizardSession, write: WriteFn) -> None:
    width = shutil.get_terminal_size(fallback=(100, 24)).columns
    for line in render_header(session, width=max(width, 1), frontend="text"):
        write(line)


_NOTHING_SELECTED = (
    "Nothing is selected yet. Enter number(s) between 1 and {count}, or 'q' to quit."
)


def _prompt_wizard_indices(
    read: ReadFn,
    write: WriteFn,
    prompt: str,
    choices: Sequence[_Choice],
    *,
    selected: Sequence[int] = (),
    allow_add: bool = False,
    allow_source_maintenance: bool = False,
) -> WizardInput:
    selected_tuple = tuple(dict.fromkeys(selected))
    while True:
        line = _read_line(read, prompt)
        if line is None:
            return WizardInput("quit")
        answer = line.strip()
        low = answer.lower()
        if low in ("q", "quit"):
            return WizardInput("quit")
        if low in ("b", "back"):
            return WizardInput("back")
        if allow_add and low in ("a", "add"):
            return WizardInput("add")
        if allow_source_maintenance and low in ("s", "sync"):
            return WizardInput("sync")
        if allow_source_maintenance and low in ("r", "remove"):
            return WizardInput("remove")
        if not answer:
            if selected_tuple:
                return WizardInput("confirm", selected_tuple)
            # D5 has no cursor to fall back on here, so an empty confirm says why it did nothing
            # rather than ending the wizard (design section 5).
            write(_NOTHING_SELECTED.format(count=len(choices)))
            continue
        if answer.startswith("?"):
            number = answer[1:].strip()
            if number.isdigit() and 1 <= int(number) <= len(choices):
                for line in _choice_detail(choices, int(number) - 1):
                    write(line)
                continue
            write(f"Enter ?N with a number between 1 and {len(choices)}.")
            continue
        parsed = _parse_indices(answer, len(choices))
        if parsed:
            disabled = tuple(choices[index] for index in parsed if not choices[index].enabled)
            if disabled:
                for choice in disabled:
                    write(f"{choice.name}: {choice.reason or 'this item is unavailable'}.")
                continue
            return WizardInput("confirm", parsed)
        write(
            f"Please enter number(s) between 1 and {len(choices)}, 'b' to go back, or 'q' to quit."
        )


def _prompt_wizard_action(read: ReadFn, write: WriteFn) -> WizardInput | str:
    while True:
        line = _read_line(read, "Action (b=back, q=quit): ")
        if line is None:
            return WizardInput("quit")
        answer = line.strip().lower()
        if answer in ("q", "quit"):
            return WizardInput("quit")
        if answer in ("b", "back"):
            return WizardInput("back")
        if answer in ACTIONS:
            return answer
        if answer.isdigit() and 1 <= int(answer) <= len(ACTIONS):
            return ACTIONS[int(answer) - 1]
        write(f"Please enter 1-{len(ACTIONS)}, an action name, 'b', or 'q'.")


def _prompt_wizard_scope(read: ReadFn, write: WriteFn) -> WizardInput | InstallScope:
    while True:
        line = _read_line(read, "Installation scope [1] (b=back, q=quit): ")
        if line is None:
            return WizardInput("quit")
        answer = line.strip().lower()
        if answer in ("q", "quit"):
            return WizardInput("quit")
        if answer in ("b", "back"):
            return WizardInput("back")
        if answer in ("", "1", "project"):
            return "project"
        if answer in ("2", "user", "global"):
            return "user"
        write("Please enter 1 (Project), 2 (User), 'b' to go back, or 'q' to quit.")


def _load_user_wizard_read_model(
    session: WizardSession,
    *,
    source_factory: SourceFactory,
    source_dir: Optional[str],
    repo: Optional[str],
    project: Optional[str],
    user_home: Optional[str],
    consumer_service: Optional[ConsumerApplicationService] = None,
) -> DomainResult[_UserWizardReadModel]:
    del source_factory, source_dir, repo
    assert session.action is not None
    base_profiles = load_profiles(project)
    resolved_home = os.path.abspath(user_home or os.path.expanduser("~"))
    scope = session.scope
    profiles_map: Mapping[str, Profile] = (
        base_profiles
        if scope == "project"
        else {
            name: profile_for_scope(profile, "user", resolved_home)
            for name, profile in base_profiles.items()
        }
    )
    if consumer_service is None:
        return DomainErr(
            (
                Diagnostic(
                    DiagnosticCode("canonical-consumer-unavailable"),
                    Severity.ERROR,
                    "the canonical consumer service is unavailable",
                    remediation=("configure and synchronize a canonical registry source",),
                ),
            )
        )
    selected_sources = (
        () if session.source_selection is None else session.source_selection.enabled_aliases
    )
    projected = consumer_service.browse(
        MarketplaceTarget(
            tuple(sorted(session.profiles)),
            "darwin" if sys.platform == "darwin" else "linux",
            scope,  # type: ignore[arg-type]
            session.install_mode,  # type: ignore[arg-type]
        ),
        sources=selected_sources,
    )
    if isinstance(projected, DomainErr):
        return projected
    rows = projected.value
    if session.action in ("update", "uninstall"):
        rows = tuple(row for row in rows if row.installed)
    choices = tuple(_canonical_choice(row) for row in rows)
    if session.action == "install":
        choices += _canonical_collection_choices(
            consumer_service.context.catalog,
            rows,
            sources=selected_sources,
        )
    return DomainOk(
        _UserWizardReadModel(
            choices,
            profiles_map,
            "federated configured marketplace",
            consumer_service.context.store_paths.root,
            rows,
        )
    )


def _stage_failure_exit_code(_failure: WizardStageFailure) -> int:
    """All canonical TUI stage failures have the stable nonzero exit code 2."""

    return 2


def _confirm_wizard_quit(session: WizardSession, read: ReadFn, write: WriteFn) -> bool:
    if request_quit(session) == "quit":
        return True
    write(f"Discard {len(session.basket)} selected basket item(s)?")
    line = _read_line(read, f"Discard {len(session.basket)} selected basket item(s)? [y/N]: ")
    if line is None:
        write("Input ended; the basket was discarded and no changes were made.")
        return True
    if line.strip().lower() in ("y", "yes"):
        return True
    write("Returning to the wizard; no changes were made.")
    return False


def _failure_project_context(session: WizardSession, project: Optional[str]) -> str | None:
    """Expose the selected project root only for the project-scoped local diagnostic view."""

    return os.path.abspath(project or ".") if session.scope == "project" else None


def _prompt_stage_failure_recovery(
    failure: WizardStageFailure,
    read: ReadFn,
    write: WriteFn,
) -> WizardInput:
    """Render one record in text mode and return only one recovery the record advertised."""

    width = shutil.get_terminal_size(fallback=(100, 24)).columns
    for line in render_wizard_stage_failure(failure, width=max(width, 1)):
        write(line)
    shortcuts = {"retry": "r", "back": "b", "quit": "q"}
    allowed = ", ".join(f"{shortcuts[choice]}={choice}" for choice in failure.choices)
    while True:
        recovery_line = _read_line(read, f"Recovery ({allowed}): ")
        answer = "quit" if recovery_line is None else recovery_line.strip().lower()
        for choice, shortcut in shortcuts.items():
            if choice in failure.choices and answer in (choice, shortcut):
                return WizardInput(choice)
        write(f"Choose one available recovery: {allowed}.")


def _recover_text_stage_failure(
    failure: WizardStageFailure,
    session: WizardSession,
    read: ReadFn,
    write: WriteFn,
) -> WizardSession | int:
    """Render one blocking record and keep only the recovery events it declares."""

    recovery = _prompt_stage_failure_recovery(failure, read, write)
    if recovery.kind == "back":
        return wizard_back(session)
    if _confirm_wizard_quit(session, read, write):
        return _cancel(write)
    return session


def _source_stage_failure(session: WizardSession, result: DomainErr) -> WizardStageFailure:
    """Attach Sources ownership to a post-selection read boundary without altering diagnostics."""

    return wizard_stage_failure(
        session,
        "load",
        result,
        stage="source",
        recoverable=False,
    )


def _maintainer_action_failure(session: WizardSession, result: DomainErr) -> WizardStageFailure:
    """Keep a failed maintainer action loader attached to its owning stage."""

    return wizard_stage_failure(
        session,
        "load",
        result,
        stage="maintainer_action",
        recoverable=False,
    )


def _terminal_stage_failure(
    session: WizardSession,
    operation: WizardOperation,
    result: DomainErr,
) -> WizardStageFailure:
    """Render a post-curses expected failure without advertising a recovery no longer available."""

    return replace(
        wizard_stage_failure(session, operation, result, recoverable=False),
        choices=("quit",),
    )


def _run_user_text_wizard(
    session: WizardSession,
    read: ReadFn,
    write: WriteFn,
    *,
    source_factory: SourceFactory,
    source_dir: Optional[str],
    repo: Optional[str],
    project: Optional[str],
    user_home: Optional[str],
    source_finalizer: Optional[SourceFinalizeFn] = None,
    consumer_service: Optional[ConsumerApplicationService] = None,
    reporting_service: Optional[ReportingApplicationService] = None,
) -> int | WizardSession:
    read_model: Optional[_UserWizardReadModel] = None
    read_key: Optional[tuple] = None
    profile_names = tuple(sorted(load_profiles(project)))
    while True:
        if session.current in ("role", "source", "maintainer_action"):
            return session
        _write_wizard_header(session, write)
        if session.current == "profiles":
            write("Select profile(s):")
            choices = tuple(_Choice("profile", name, None, name) for name in profile_names)
            for index, choice in enumerate(choices, start=1):
                write(f"  {index:>2}. {choice.label}")
            selected = tuple(
                index for index, name in enumerate(profile_names) if name in session.profiles
            )
            write(f"Selected: {len(selected)} profile(s)")
            event = _prompt_wizard_indices(
                read,
                write,
                "Profile(s) (b=back, q=quit): ",
                choices,
                selected=selected,
            )
            if event.kind == "back":
                session = wizard_back(session)
                continue
            if event.kind == "quit":
                if _confirm_wizard_quit(session, read, write):
                    return _cancel(write)
                continue
            session = wizard_select(
                session, "profiles", tuple(profile_names[index] for index in event.selected)
            )
            session = wizard_advance(session)
            continue
        if session.current == "action":
            write("Action:")
            for index, action in enumerate(ACTIONS, start=1):
                write(f"  {index:>2}. {action}")
            selected_action = _prompt_wizard_action(read, write)
            if isinstance(selected_action, WizardInput):
                if selected_action.kind == "back":
                    session = wizard_back(session)
                elif _confirm_wizard_quit(session, read, write):
                    return _cancel(write)
                continue
            session = wizard_select(session, "action", selected_action)
            if selected_action == "status" and session.basket:
                session = reconcile_basket(
                    session,
                    {item.key: "not applicable to the Status action" for item in session.basket},
                )
            session = wizard_advance(session)
            read_model = None
            continue
        if session.current == "scope":
            write("Installation scope:")
            for index, scope_choice in enumerate(INSTALL_SCOPE_CHOICES, start=1):
                write(f"  {index:>2}. {scope_choice.label:<23} {scope_choice.description}")
            selected_scope = _prompt_wizard_scope(read, write)
            if isinstance(selected_scope, WizardInput):
                if selected_scope.kind == "back":
                    session = wizard_back(session)
                elif _confirm_wizard_quit(session, read, write):
                    return _cancel(write)
                continue
            session = wizard_select(session, "scope", selected_scope)
            session = wizard_advance(session)
            read_model = None
            continue
        if session.current == "mode":
            selected_mode = _prompt_install_mode(read, write)
            if selected_mode is None:
                if _confirm_wizard_quit(session, read, write):
                    return _cancel(write)
                continue
            if selected_mode == "back":
                session = wizard_back(session)
                continue
            session = wizard_select(session, "mode", selected_mode)
            session = wizard_advance(session)
            read_model = None
            continue
        if session.current == "artifacts":
            key = (
                session.action,
                session.profiles,
                session.scope,
                session.install_mode,
            )
            if read_model is None or read_key != key:
                loaded = _load_user_wizard_read_model(
                    session,
                    source_factory=source_factory,
                    source_dir=source_dir,
                    repo=repo,
                    project=project,
                    user_home=user_home,
                    consumer_service=consumer_service,
                )
                if isinstance(loaded, DomainErr):
                    failure = wizard_stage_failure(
                        session,
                        "load",
                        loaded,
                        project=_failure_project_context(session, project),
                    )
                    recovery = _prompt_stage_failure_recovery(failure, read, write)
                    if recovery.kind == "retry":
                        read_model = None
                        read_key = None
                        continue
                    if recovery.kind == "back":
                        session = wizard_back(session)
                        continue
                    if _confirm_wizard_quit(session, read, write):
                        return _cancel(write)
                    continue
                read_model = loaded.value
                read_key = key
            if not read_model.choices:
                write(_empty_choices_message(session.action or "", session.profiles))
                return _render_result(
                    CommandOutcome(0, ActionSummary(action=session.action or "selection")), write
                )
            availability = {
                _basket_key(choice): "" if choice.enabled else choice.reason
                for choice in read_model.choices
            }
            session = reconcile_basket(session, availability)
            write(f"Select artifact(s)/bundle(s) for {_profiles_label(session.profiles)}:")
            width = shutil.get_terminal_size(fallback=(200, 24)).columns
            for index, choice in enumerate(read_model.choices, start=1):
                write(_text_choice_line(index, choice, width))
            write("Enter ?N for details; blank keeps the current basket.")
            selected = tuple(
                index
                for index, choice in enumerate(read_model.choices)
                if _basket_key(choice) in {item.key for item in session.basket}
            )
            write(f"Selected: {len(selected)} basket item(s)")
            event = _prompt_wizard_indices(
                read,
                write,
                "Selection (b=back, q=quit): ",
                read_model.choices,
                selected=selected,
            )
            if event.kind == "back":
                session = wizard_back(session)
                continue
            if event.kind == "quit":
                if _confirm_wizard_quit(session, read, write):
                    return _cancel(write)
                continue
            if not event.selected:
                write("Select at least one artifact or bundle before continuing.")
                continue
            session = wizard_select(
                session,
                "artifacts",
                tuple(_basket_item(read_model.choices[index]) for index in event.selected),
            )
            session = wizard_advance(session)
            continue
        if session.current == "review":
            assert consumer_service is not None
            selected_keys = {item.key for item in session.basket}
            selected_coordinates = (
                set()
                if read_model is None
                else {
                    row.coordinate
                    for row in read_model.marketplace_rows
                    if row.key in selected_keys
                }
            )
            for collection in consumer_service.context.catalog.collections:
                if str(collection.coordinate) in selected_keys:
                    selected_coordinates.update(collection.members)
            prepared = consumer_service.prepare(
                ConsumerActionRequest(
                    session.action or "status",  # type: ignore[arg-type]
                    tuple(sorted(selected_coordinates, key=str)),
                    tuple(sorted(session.profiles)),
                    session.scope,  # type: ignore[arg-type]
                    session.install_mode,  # type: ignore[arg-type]
                )
            )
            if isinstance(prepared, DomainErr):
                recovered = _recover_text_stage_failure(
                    wizard_stage_failure(session, "review", prepared, recoverable=False),
                    session,
                    read,
                    write,
                )
                if isinstance(recovered, int):
                    return recovered
                session = recovered
                continue
            canonical_review = prepared.value
            for line in render_consumer_review(canonical_review):
                write(line)
            write("Finalize applies this reviewed action; Back edits without changes.")
            review_answer = _read_line(read, "Finalize? [y/N] (b=back, q=quit): ")
            answer = "q" if review_answer is None else review_answer.strip().lower()
            if answer in ("b", "back"):
                session = wizard_back(session)
                continue
            if answer in ("q", "quit"):
                if _confirm_wizard_quit(session, read, write):
                    return _cancel(write)
                continue
            if answer not in ("y", "yes", "f", "finalize"):
                write("Review not finalized; no changes were made.")
                continue
            if not can_finalize(session, revision=session.revision):
                write("Wizard state changed; review it again before Finalize.")
                continue
            source_failure = _finalize_source_selection(session, source_finalizer, write)
            if source_failure is not None:
                recovered = _recover_text_stage_failure(
                    wizard_stage_failure(session, "finalize", source_failure, recoverable=False),
                    session,
                    read,
                    write,
                )
                if isinstance(recovered, int):
                    return recovered
                session = recovered
                continue
            finalized = consumer_service.finalize(canonical_review, canonical_review.review_digest)
            if isinstance(finalized, DomainErr):
                recovered = _recover_text_stage_failure(
                    wizard_stage_failure(session, "finalize", finalized, recoverable=False),
                    session,
                    read,
                    write,
                )
                if isinstance(recovered, int):
                    return recovered
                session = recovered
                continue
            for line in render_consumer_outcome(finalized.value):
                write(line)
            return _complete_canonical_consumer_action(
                consumer_service,
                canonical_review,
                finalized.value,
                reporting_service,
                read=read,
                write=write,
            )


def _run_text(
    read: ReadFn = input,
    write: WriteFn = print,
    *,
    source_factory: SourceFactory = _unsupported_source_factory,
    source_dir: Optional[str] = None,
    repo: Optional[str] = None,
    project: Optional[str] = None,
    user_home: Optional[str] = None,
    source_stage_view: Optional[SourceStageView] = None,
    source_finalizer: Optional[SourceFinalizeFn] = None,
    source_addition_finalizer: Optional[SourceAdditionFinalizeFn] = None,
    source_removal_finalizer: Optional[SourceRemovalFinalizeFn] = None,
    source_sync_runner: Optional[SourceSyncRunFn] = None,
    source_stage_loader: Optional[SourceStageLoader] = None,
    consumer_service: Optional[ConsumerApplicationService] = None,
    consumer_service_factory: Optional[ConsumerServiceFactory] = None,
    reporting_service: Optional[ReportingApplicationService] = None,
    reporting_service_factory: Optional[ReportingServiceFactory] = None,
    curation_service_factory: Optional[CurationServiceFactory] = None,
) -> int:
    """Persistent onboarding/role wizard shared by the fallback and headless tests."""

    if repo is not None:
        write(
            "error: direct legacy repository selection is no longer supported; "
            "add a canonical registry in Sources instead."
        )
        return 2
    session = initial_session()
    buffered_role: Optional[str] = None
    stage_view = source_stage_view or _empty_source_stage_view()

    def reload_stage_view() -> DomainErr | None:
        """Re-read the source stage after a mutation so later screens never show stale facts."""

        nonlocal stage_view, source_finalizer, source_addition_finalizer
        nonlocal source_removal_finalizer, source_sync_runner
        if source_stage_loader is None:
            return None
        refreshed = source_stage_loader()
        if isinstance(refreshed, DomainErr):
            return refreshed
        stage_view = refreshed.value.view
        source_finalizer = refreshed.value.source_finalizer
        source_addition_finalizer = refreshed.value.source_addition_finalizer
        source_removal_finalizer = refreshed.value.source_removal_finalizer
        source_sync_runner = refreshed.value.source_sync_runner
        return None

    while True:
        if session.current == "onboarding":
            for line in onboarding_lines("text"):
                write(line)
            _write_wizard_header(session, write)
            onboarding_answer = _read_line(read, "Press Enter to start (q=quit): ")
            if onboarding_answer is None or onboarding_answer.strip().lower() in ("q", "quit"):
                return _cancel(write)
            buffered_role = onboarding_answer if onboarding_answer.strip() else None
            session = wizard_advance(session)
            continue
        if session.current == "role":
            _write_wizard_header(session, write)
            role = _prompt_role(read, write, initial_answer=buffered_role)
            buffered_role = None
            if role is None:
                return _cancel(write)
            if role == "back":
                session = wizard_back(session)
                continue
            session = wizard_select(session, "role", role)
            if (
                role == "maintainer"
                and repo is None
                and (
                    source_dir is None
                    or _is_canonical_maintainer_workspace(os.path.abspath(source_dir))
                )
            ):
                session = use_current_checkout(session)
            session = wizard_advance(session)
            continue
        if session.current == "source":
            _write_wizard_header(session, write)
            selected_source = _prompt_source_stage_text(session, stage_view, read, write)
            if isinstance(selected_source, WizardInput):
                if selected_source.kind == "back":
                    session = wizard_back(session)
                elif selected_source.kind == "add":
                    if source_addition_finalizer is None or source_stage_loader is None:
                        write("error: source setup is unavailable in this TUI runtime")
                        continue
                    addition = _prompt_source_addition_text(stage_view, read, write)
                    if isinstance(addition, WizardInput):
                        if addition.kind == "quit" and _confirm_wizard_quit(session, read, write):
                            return _cancel(write)
                        continue
                    finalized_addition = source_addition_finalizer(addition)
                    if isinstance(finalized_addition, DomainErr):
                        _write_domain_diagnostics(finalized_addition, write)
                        write("Source was not saved; choose another source or retry setup.")
                        continue
                    stale = reload_stage_view()
                    if stale is not None:
                        _write_domain_diagnostics(stale, write)
                        write("Source was saved but the Sources screen could not be refreshed.")
                        continue
                    session = replace(
                        session,
                        source_selection=None,
                        revision=session.revision + 1,
                    )
                    write(
                        f"Sources: synchronized and saved {addition.source.alias}. "
                        "Choose enabled source(s) to continue."
                    )
                elif selected_source.kind == "sync":
                    if source_sync_runner is None or source_stage_loader is None:
                        write("error: source synchronization is unavailable in this TUI runtime")
                        continue
                    picked = _prompt_source_sync_text(stage_view, read, write)
                    if isinstance(picked, WizardInput):
                        if picked.kind == "quit" and _confirm_wizard_quit(session, read, write):
                            return _cancel(write)
                        continue
                    synchronized = source_sync_runner(picked.source.alias)
                    if isinstance(synchronized, DomainErr):
                        _write_domain_diagnostics(synchronized, write)
                        write(
                            f"{picked.source.alias} was not synchronized; "
                            "its snapshot is unchanged."
                        )
                        write("In Sources: s retries, r removes this source, a adds one.")
                        continue
                    for line in render_source_sync_outcome(picked.source.alias, synchronized.value):
                        write(line)
                    stale = reload_stage_view()
                    if stale is not None:
                        _write_domain_diagnostics(stale, write)
                        write(
                            "The source was synchronized but the Sources screen could not be "
                            "refreshed."
                        )
                        continue
                    session = replace(
                        session,
                        source_selection=None,
                        revision=session.revision + 1,
                    )
                elif selected_source.kind == "remove":
                    if source_removal_finalizer is None or source_stage_loader is None:
                        write("error: source removal is unavailable in this TUI runtime")
                        continue
                    removal = _prompt_source_removal_text(stage_view, read, write)
                    if isinstance(removal, WizardInput):
                        if removal.kind == "quit" and _confirm_wizard_quit(session, read, write):
                            return _cancel(write)
                        continue
                    finalized_removal = source_removal_finalizer(removal)
                    if isinstance(finalized_removal, DomainErr):
                        _write_domain_diagnostics(finalized_removal, write)
                        write(f"{removal.source.alias} was not removed.")
                        write("In Sources: r retries the removal, s synchronizes instead.")
                        continue
                    cleared = (
                        "; the default registry was cleared" if removal.cleared_default else ""
                    )
                    write(
                        f"Sources: removed {removal.source.alias} and deleted its "
                        f"snapshot{cleared}."
                    )
                    stale = reload_stage_view()
                    if stale is not None:
                        _write_domain_diagnostics(stale, write)
                        write(
                            "The source was removed but the Sources screen could not be refreshed."
                        )
                        continue
                    session = replace(
                        session,
                        source_selection=None,
                        revision=session.revision + 1,
                    )
                elif _confirm_wizard_quit(session, read, write):
                    return _cancel(write)
                continue
            session = wizard_select(session, "source", selected_source)
            session = wizard_advance(session)
            if selected_source.no_source:
                return _cancel(
                    write,
                    "No sources selected; no registry was forced and no changes were made.",
                )
            active_consumer_service = consumer_service
            active_reporting_service = reporting_service
            if consumer_service_factory is not None and session.role == "user":
                loaded_consumer = consumer_service_factory(selected_source.request.after)
                if isinstance(loaded_consumer, DomainErr):
                    recovered = _recover_text_stage_failure(
                        _source_stage_failure(session, loaded_consumer),
                        session,
                        read,
                        write,
                    )
                    if isinstance(recovered, int):
                        return recovered
                    session = recovered
                    continue
                active_consumer_service = loaded_consumer.value
            if reporting_service_factory is not None and session.role == "user":
                loaded_reporting = reporting_service_factory(selected_source.request.after)
                if isinstance(loaded_reporting, DomainErr):
                    write(
                        "warning: usage reporting is unavailable; artifact installation remains "
                        "available"
                    )
                    active_reporting_service = None
                else:
                    active_reporting_service = loaded_reporting.value
            if session.role == "user":
                if active_consumer_service is None:
                    write(
                        "error: canonical consumer services are unavailable; "
                        "restart after configuring a registry source."
                    )
                    return 2
                result = _run_user_text_wizard(
                    session,
                    read,
                    write,
                    source_factory=source_factory,
                    source_dir=source_dir,
                    repo=repo,
                    project=project,
                    user_home=user_home,
                    source_finalizer=source_finalizer,
                    consumer_service=active_consumer_service,
                    reporting_service=active_reporting_service,
                )
                if isinstance(result, WizardSession):
                    session = result
                    continue
                return result
            result = _run_maintainer_text(
                session,
                read,
                write,
                source_factory=source_factory,
                source_dir=source_dir,
                repo=repo,
                project=project,
                user_home=user_home,
                source_finalizer=source_finalizer,
                consumer_service_factory=consumer_service_factory,
                reporting_service_factory=reporting_service_factory,
                consumer_configuration=selected_source.request.after,
                curation_service_factory=curation_service_factory,
            )
            if isinstance(result, WizardSession):
                session = result
                continue
            return result
        if session.current == "maintainer_action":
            result = _run_maintainer_text(
                session,
                read,
                write,
                source_factory=source_factory,
                source_dir=(
                    os.path.abspath(source_dir or os.getcwd())
                    if session.maintainer_checkout
                    else source_dir
                ),
                repo=None,
                project=project,
                user_home=user_home,
                source_finalizer=source_finalizer,
                consumer_service_factory=consumer_service_factory,
                reporting_service_factory=reporting_service_factory,
                consumer_configuration=(
                    stage_view.configuration if session.maintainer_checkout else None
                ),
                curation_service_factory=curation_service_factory,
            )
            if isinstance(result, WizardSession):
                session = result
                continue
            return result


def _prompt_role(
    read: ReadFn, write: WriteFn, *, initial_answer: Optional[str] = None
) -> Optional[str]:
    write("Choose how you want to use aart:")
    for index, role in enumerate(ROLES, start=1):
        write(f"  {index:>2}. {role.label:<10} {role.description}")
    while True:
        line = initial_answer
        initial_answer = None
        if line is None:
            line = _read_line(read, "Role (1=User, 2=Maintainer, b=back, q=quit): ")
        if line is None:
            return None
        answer = line.strip().lower()
        if answer in ("", "q"):
            return None
        if answer in ("b", "back"):
            return "back"
        if answer in ("1", "user"):
            return "user"
        if answer in ("2", "maintainer"):
            return "maintainer"
        write("Please enter 1 (User), 2 (Maintainer), or 'q' to quit.")


def _is_canonical_maintainer_workspace(root: str) -> bool:
    """Classify only an explicit current registry marker as a maintainer workspace."""

    return os.path.isfile(os.path.join(root, "aart-registry.json"))


def _default_curation_service_factory(root: str) -> DomainResult[CurationService]:
    from .curation.runtime import load_local_curation_service

    return load_local_curation_service(root)


def _write_domain_diagnostics(result: DomainErr, write: WriteFn) -> None:
    for diagnostic in result.diagnostics:
        for line in wrap(
            f"{diagnostic.severity.value} [{diagnostic.code.value}]: {diagnostic.message}",
            width=CONTENT_MEASURE,
        ):
            write(line)
        for remediation in diagnostic.remediation:
            prefix = "  remediation: "
            lines = wrap(remediation, width=CONTENT_MEASURE - len(prefix))
            write(prefix + lines[0])
            for line in lines[1:]:
                write(" " * len(prefix) + line)


def _prompt_wizard_csv(
    read: ReadFn,
    write: WriteFn,
    prompt: str,
    *,
    current: Tuple[str, ...] = (),
    default: Tuple[str, ...] = (),
) -> Tuple[str, ...] | WizardInput:
    while True:
        line = _read_line(read, prompt)
        if line is None:
            return WizardInput("quit")
        answer = line.strip()
        if answer.lower() in ("q", "quit"):
            return WizardInput("quit")
        if answer.lower() in ("b", "back"):
            return WizardInput("back")
        if not answer:
            return current or default
        values = tuple(item.strip() for item in answer.split(",") if item.strip())
        if values:
            return values
        write("Enter one or more comma-separated values, 'b' to go back, or 'q' to quit.")


def _prompt_curation_request(
    action: CurationAction,
    workspace: str,
    read: ReadFn,
    write: WriteFn,
    *,
    existing: Optional[CurationRequest],
) -> CurationRequest | WizardInput:
    def value(
        prompt: str,
        field: str,
        *,
        required: bool = True,
        default: Optional[str] = None,
    ) -> str | None | WizardInput:
        current = getattr(existing, field) if existing is not None else default
        return _prompt_wizard_value(
            read,
            write,
            prompt,
            current=current,
            required=required,
        )

    if action is CurationAction.INIT:
        source_id = value("Registry/source ID: ", "source_id")
        if isinstance(source_id, WizardInput):
            return source_id
        display_name = value("Registry display name: ", "display_name")
        if isinstance(display_name, WizardInput):
            return display_name
        minimum = value("Minimum AART version [1.0.0]: ", "minimum_version", default="1.0.0")
        if isinstance(minimum, WizardInput):
            return minimum
        maximum = value(
            "Maximum AART version (exclusive) [2.0.0]: ", "maximum_version", default="2.0.0"
        )
        if isinstance(maximum, WizardInput):
            return maximum
        return CurationRequest(
            action,
            workspace,
            source_id=source_id,
            display_name=display_name,
            minimum_version=minimum or "1.0.0",
            maximum_version=maximum or "2.0.0",
        )

    if action is CurationAction.SCAFFOLD:
        kind = value("Artifact kind (skill/guideline/mcp/hook/memory): ", "kind")
        if isinstance(kind, WizardInput):
            return kind
        name = value("Artifact name: ", "name")
        if isinstance(name, WizardInput):
            return name
        summary = value("One-line value description: ", "summary")
        if isinstance(summary, WizardInput):
            return summary
        version = value("Artifact version [1.0.0]: ", "artifact_version", default="1.0.0")
        if isinstance(version, WizardInput):
            return version
        profiles = _prompt_wizard_csv(
            read,
            write,
            "Harness profiles (comma-separated): ",
            current=existing.profiles if existing else (),
        )
        if isinstance(profiles, WizardInput):
            return profiles
        platforms = _prompt_wizard_csv(
            read,
            write,
            "Platforms (comma-separated): ",
            current=existing.platforms if existing else (),
        )
        if isinstance(platforms, WizardInput):
            return platforms
        scopes = _prompt_wizard_csv(
            read,
            write,
            "Install scopes [project]: ",
            current=existing.scopes if existing else (),
            default=("project",),
        )
        if isinstance(scopes, WizardInput):
            return scopes
        modes = _prompt_wizard_csv(
            read,
            write,
            "Install modes [copy]: ",
            current=existing.modes if existing else (),
            default=("copy",),
        )
        if isinstance(modes, WizardInput):
            return modes
        return CurationRequest(
            action,
            workspace,
            kind=kind,
            name=name,
            summary=summary,
            artifact_version=version or "1.0.0",
            profiles=profiles,
            platforms=platforms,
            scopes=scopes,
            modes=modes,
        )

    if action is CurationAction.PROMOTE_NATIVE:
        kind = value("Artifact kind: ", "kind")
        if isinstance(kind, WizardInput):
            return kind
        name = value("Artifact name: ", "name")
        if isinstance(name, WizardInput):
            return name
        url = value("Credential-free Git URL: ", "url")
        if isinstance(url, WizardInput):
            return url
        ref = value("Git ref [main]: ", "ref", default="main")
        if isinstance(ref, WizardInput):
            return ref
        path = value("Canonical package path: ", "path")
        if isinstance(path, WizardInput):
            return path
        policy = value(
            "Review policy [manual-review-v1]: ",
            "review_policy",
            default="manual-review-v1",
        )
        if isinstance(policy, WizardInput):
            return policy
        return CurationRequest(
            action,
            workspace,
            kind=kind,
            name=name,
            url=url,
            ref=ref or "main",
            path=path,
            review_policy=policy or "manual-review-v1",
        )

    if action is CurationAction.REFRESH_NATIVE:
        kind = value("Locked artifact kind: ", "kind")
        if isinstance(kind, WizardInput):
            return kind
        name = value("Locked artifact name: ", "name")
        if isinstance(name, WizardInput):
            return name
        return CurationRequest(action, workspace, kind=kind, name=name)

    return CurationRequest(action, workspace)


def _run_canonical_maintainer_text(
    session: WizardSession,
    read: ReadFn,
    write: WriteFn,
    *,
    workspace: str,
    project: Optional[str],
    user_home: Optional[str],
    source_finalizer: Optional[SourceFinalizeFn],
    consumer_service_factory: Optional[ConsumerServiceFactory],
    reporting_service_factory: Optional[ReportingServiceFactory],
    consumer_configuration: Optional[UserConfiguration],
    curation_service_factory: Optional[CurationServiceFactory],
) -> int | WizardSession:
    factory = curation_service_factory or _default_curation_service_factory
    loaded = factory(workspace)
    if isinstance(loaded, DomainErr):
        recovered = _recover_text_stage_failure(
            _maintainer_action_failure(session, loaded),
            session,
            read,
            write,
        )
        return recovered
    service = loaded.value
    request: Optional[CurationRequest] = None
    prepared: Optional[PreparedCuration] = None
    while True:
        if session.current == "role":
            return session
        _write_wizard_header(session, write)
        if session.current == "maintainer_action":
            write(f"Canonical registry checkout: {workspace}")
            write("Maintainer action:")
            for index, (_action, label) in enumerate(CANONICAL_MAINTAINER_ACTIONS, start=1):
                write(f"  {index:>2}. {label}")
            selected = _prompt_maintainer_action_wizard(
                read,
                write,
                CANONICAL_MAINTAINER_ACTIONS,
            )
            if isinstance(selected, WizardInput):
                if selected.kind == "back":
                    return wizard_back(session)
                return _cancel(write)
            session = replace(session, basket=(), notices=())
            session = wizard_select(session, "maintainer_action", selected)
            session = wizard_advance(session)
            request = None
            prepared = None
            if selected == "user":
                consumer_service: Optional[ConsumerApplicationService] = None
                reporting_service: Optional[ReportingApplicationService] = None
                active_consumer_factory = consumer_service_factory
                if active_consumer_factory is None and consumer_configuration is not None:
                    from .consumer.runtime import load_local_consumer_service

                    def active_consumer_factory(
                        configuration: UserConfiguration,
                    ) -> DomainResult[ConsumerApplicationService]:
                        return load_local_consumer_service(
                            project=project,
                            user_home=user_home,
                            configuration=configuration,
                        )

                if active_consumer_factory is not None and consumer_configuration is not None:
                    loaded_consumer = active_consumer_factory(consumer_configuration)
                    if isinstance(loaded_consumer, DomainErr):
                        recovered = _recover_text_stage_failure(
                            _maintainer_action_failure(session, loaded_consumer),
                            session,
                            read,
                            write,
                        )
                        if isinstance(recovered, int):
                            return recovered
                        session = recovered
                        continue
                    consumer_service = loaded_consumer.value
                if reporting_service_factory is not None and consumer_configuration is not None:
                    loaded_reporting = reporting_service_factory(consumer_configuration)
                    if isinstance(loaded_reporting, DomainErr):
                        write(
                            "warning: usage reporting is unavailable; artifact installation "
                            "remains available"
                        )
                    else:
                        reporting_service = loaded_reporting.value
                result = _run_user_text_wizard(
                    session,
                    read,
                    write,
                    source_factory=_unsupported_source_factory,
                    source_dir=workspace,
                    repo=None,
                    project=project,
                    user_home=user_home,
                    source_finalizer=source_finalizer,
                    consumer_service=consumer_service,
                    reporting_service=reporting_service,
                )
                if isinstance(result, WizardSession):
                    session = result
                    continue
                return result
            continue

        action_name = session.maintainer_action
        assert action_name is not None and action_name != "user"
        action = CurationAction(action_name)
        if session.current == "native_details":
            previous_request = request
            try:
                prompted = _prompt_curation_request(
                    action,
                    workspace,
                    read,
                    write,
                    existing=request,
                )
            except ValueError as error:
                write(f"error: {error}")
                continue
            if isinstance(prompted, WizardInput):
                if prompted.kind == "back":
                    session = wizard_back(session)
                    continue
                if _confirm_wizard_quit(session, read, write):
                    return _cancel(write)
                continue
            request = prompted
            label = (
                f"{request.kind}/{request.name}"
                if request.kind is not None and request.name is not None
                else action.value
            )
            session = replace(
                session,
                basket=(BasketItem("reference", label, label),),
                revision=session.revision + 1,
            )
            session = wizard_advance(session)
            if request != previous_request:
                prepared = None
            continue

        if session.current != "review":
            return 2
        if request is None:
            request = CurationRequest(action, workspace)
        if prepared is None:
            planned = service.prepare(request)
            if isinstance(planned, DomainErr):
                recovered = _recover_text_stage_failure(
                    wizard_stage_failure(session, "review", planned, recoverable=False),
                    session,
                    read,
                    write,
                )
                if isinstance(recovered, int):
                    return recovered
                session = recovered
                continue
            prepared = planned.value
        for line in render_curation_review(prepared.review):
            write(line)
        finalized_line = _read_line(
            read, "Finalize exact reviewed action? [y/N] (b=back, q=quit): "
        )
        answer = "q" if finalized_line is None else finalized_line.strip().lower()
        if answer in ("b", "back"):
            session = wizard_back(session)
            continue
        if answer in ("q", "quit"):
            if _confirm_wizard_quit(session, read, write):
                return _cancel(write)
            continue
        if answer not in ("y", "yes", "f", "finalize"):
            write("Review not finalized; no changes were made.")
            continue
        if not can_finalize(session, revision=session.revision):
            write("Wizard state changed; review it again before Finalize.")
            continue
        source_failure = _finalize_source_selection(session, source_finalizer, write)
        if source_failure is not None:
            recovered = _recover_text_stage_failure(
                wizard_stage_failure(session, "finalize", source_failure, recoverable=False),
                session,
                read,
                write,
            )
            if isinstance(recovered, int):
                return recovered
            session = recovered
            continue
        finalized = service.finalize(prepared, prepared.review.review_digest)
        if isinstance(finalized, DomainErr):
            recovered = _recover_text_stage_failure(
                wizard_stage_failure(session, "finalize", finalized, recoverable=False),
                session,
                read,
                write,
            )
            if isinstance(recovered, int):
                return recovered
            session = recovered
            continue
        for rendered in render_curation_outcome(finalized.value):
            write(rendered)
        return 2 if finalized.value.status == "failed" else 0


def _run_maintainer_text(
    session: WizardSession,
    read: ReadFn,
    write: WriteFn,
    *,
    source_factory: SourceFactory,
    source_dir: Optional[str],
    repo: Optional[str],
    project: Optional[str],
    user_home: Optional[str] = None,
    source_finalizer: Optional[SourceFinalizeFn] = None,
    consumer_service_factory: Optional[ConsumerServiceFactory] = None,
    reporting_service_factory: Optional[ReportingServiceFactory] = None,
    consumer_configuration: Optional[UserConfiguration] = None,
    curation_service_factory: Optional[CurationServiceFactory] = None,
) -> int | WizardSession:
    """Drive Maintainer stages and expose apply only at the Review Finalize boundary."""
    del source_factory, repo
    workspace = os.path.abspath(source_dir or os.getcwd())
    if not _is_canonical_maintainer_workspace(workspace):
        write(
            "error: maintainer mode accepts only a canonical registry checkout; "
            "initialize one with `aart registry init`."
        )
        return 2
    return _run_canonical_maintainer_text(
        session,
        read,
        write,
        workspace=workspace,
        project=project,
        user_home=user_home,
        source_finalizer=source_finalizer,
        consumer_service_factory=consumer_service_factory,
        reporting_service_factory=reporting_service_factory,
        consumer_configuration=consumer_configuration,
        curation_service_factory=curation_service_factory,
    )


def _prompt_maintainer_action_wizard(
    read: ReadFn,
    write: WriteFn,
    actions: Tuple[Tuple[str, str], ...] = CANONICAL_MAINTAINER_ACTIONS,
) -> str | WizardInput:
    while True:
        line = _read_line(read, "Maintainer action (b=back, q=quit): ")
        if line is None:
            return WizardInput("quit")
        answer = line.strip().lower()
        if answer in ("q", "quit"):
            return WizardInput("quit")
        if answer in ("b", "back"):
            return WizardInput("back")
        by_name = {name: name for name, _label in actions}
        if answer in by_name:
            return by_name[answer]
        if answer.isdigit() and 1 <= int(answer) <= len(actions):
            return actions[int(answer) - 1][0]
        write(f"Please enter 1-{len(actions)}, 'b', or 'q'.")


def _prompt_wizard_value(
    read: ReadFn,
    write: WriteFn,
    prompt: str,
    *,
    current: Optional[str] = None,
    required: bool,
) -> str | None | WizardInput:
    while True:
        line = _read_line(read, prompt)
        if line is None:
            return WizardInput("quit")
        answer = line.strip()
        lower = answer.lower()
        if lower in ("q", "quit"):
            return WizardInput("quit")
        if lower in ("b", "back"):
            return WizardInput("back")
        if answer:
            return answer
        if current is not None:
            return current
        if not required:
            return None
        write("A value is required (or enter 'b' to go back, 'q' to quit).")


def _profiles_label(profile_names: Sequence[str]) -> str:
    return ", ".join(profile_names)


def _empty_choices_message(action: str, profile_names: Sequence[str]) -> str:
    profiles = _profiles_label(profile_names)
    if action == "install":
        return f"No installable artifacts or bundles for profile(s): {profiles}."
    if action == "update":
        return f"No installed artifacts to update for profile(s): {profiles}."
    if action == "uninstall":
        return f"No installed artifacts to uninstall for profile(s): {profiles}."
    return f"No choices for profile(s): {profiles}."


def _read_line(read: ReadFn, prompt: str) -> Optional[str]:
    """Read one line; map EOF (``input`` raising ``EOFError``) to ``None`` (= quit)."""
    try:
        return read(prompt)
    except EOFError:
        return None


def _prompt_indices(
    read: ReadFn, write: WriteFn, prompt: str, choices: Sequence[_Choice]
) -> Tuple[int, ...]:
    """Prompt for a comma/space-separated 1-based selection; return 0-based indices.

    Blank or ``q`` -> empty tuple (quit). Out-of-range / non-numeric tokens re-prompt with a
    short message rather than crashing. Duplicates are de-duplicated, original order kept.
    """
    while True:
        line = _read_line(read, prompt)
        if line is None:
            return ()
        line = line.strip()
        if line.lower() == "q":
            return ()
        if line == "":
            write(_NOTHING_SELECTED.format(count=len(choices)))
            continue
        if line.startswith("?"):
            number = line[1:].strip()
            if number.isdigit() and 1 <= int(number) <= len(choices):
                for record_line in _choice_detail(choices, int(number) - 1):
                    write(record_line)
                continue
            write(f"Enter ?N with a number between 1 and {len(choices)}.")
            continue
        parsed = _parse_indices(line, len(choices))
        if parsed:
            disabled = tuple(choices[index] for index in parsed if not choices[index].enabled)
            if disabled:
                for choice in disabled:
                    reason = choice.reason or "this item is unavailable"
                    write(f"{choice.name}: {reason}.")
                continue
            return parsed
        write(f"Please enter number(s) between 1 and {len(choices)} (or 'q' to quit).")


def _parse_indices(line: str, choice_count: int) -> Tuple[int, ...]:
    """Pure 1-based comma/space selection parser used by both text menus."""
    tokens = [token for token in line.replace(",", " ").split() if token]
    out: List[int] = []
    seen = set()
    for token in tokens:
        if not token.isdigit():
            return ()
        number = int(token)
        if not (1 <= number <= choice_count):
            return ()
        index = number - 1
        if index not in seen:
            seen.add(index)
            out.append(index)
    return tuple(out)


def _text_choice_line(index: int, choice: _Choice, width: int) -> str:
    """Render one numbered text-frontend row within the terminal width."""
    prefix = f"  {index:>2}. "
    if width <= len(prefix):
        return _ellipsize(prefix, width)
    return prefix + _ellipsize(choice.label, max(width - len(prefix), 0))


def _prompt_install_scope(read: ReadFn, write: WriteFn) -> Optional[InstallScope]:
    """Select the state/destination boundary; blank keeps the project default."""

    write("Installation scope:")
    for index, choice in enumerate(INSTALL_SCOPE_CHOICES, start=1):
        write(f"  {index:>2}. {choice.label:<23} {choice.description}")
    while True:
        line = _read_line(read, "Installation scope [1] (q=quit): ")
        if line is None:
            return None
        answer = line.strip().lower()
        if answer in ("q", "quit"):
            return None
        if answer in ("", "1", "project"):
            return "project"
        if answer in ("2", "user", "global"):
            return "user"
        write("Please enter 1 (Project), 2 (User), or 'q' to quit.")


def _prompt_install_mode(
    read: ReadFn,
    write: WriteFn,
) -> Optional[Literal["copy", "symlink", "back"]]:
    """Select the Install-only mode; blank is Copy and back returns to Action."""

    write("Installation mode:")
    for index, choice in enumerate(INSTALL_MODE_CHOICES, start=1):
        write(f"  {index:>2}. {choice.label:<20} {choice.description}")
    while True:
        line = _read_line(read, "Installation mode [1] (b=back, q=quit): ")
        if line is None:
            return None
        answer = line.strip().lower()
        if answer in ("q", "quit"):
            return None
        if answer in ("b", "back"):
            return "back"
        if answer in ("", "1", "copy"):
            return "copy"
        if answer in ("2", "symlink", "link"):
            return "symlink"
        write("Please enter 1 (Copy), 2 (Symlink), 'b' to go back, or 'q' to quit.")


def _prompt_install_confirmation(read: ReadFn) -> bool:
    """Return true only for an explicit affirmative Install confirmation."""

    line = _read_line(read, "Proceed with installation? [y/N]: ")
    return line is not None and line.strip().lower() in ("y", "yes")


def _prompt_action(read: ReadFn, write: WriteFn) -> Optional[str]:
    """Prompt for one action by number or name. Blank/``q`` -> ``None`` (quit)."""
    while True:
        line = _read_line(read, "Action (e.g. 1): ")
        if line is None:
            return None
        line = line.strip()
        if line == "" or line.lower() == "q":
            return None
        low = line.lower()
        if low in ACTIONS:
            return low
        if line.isdigit():
            n = int(line)
            if 1 <= n <= len(ACTIONS):
                return ACTIONS[n - 1]
        write(f"Please enter 1-{len(ACTIONS)} or one of: {', '.join(ACTIONS)}.")


# --------------------------------------------------------------------------- #
# curses front-end — gather an immutable session, dispatch only after teardown. #
# --------------------------------------------------------------------------- #
def _curses_header(stdscr, session: WizardSession) -> Tuple[str, ...]:
    width = _width(stdscr) if hasattr(stdscr, "getmaxyx") else 80
    return render_header(session, width=max(width - 1, 1), frontend="curses")


def _position(session: WizardSession, stage: str) -> Tuple[int, int]:
    for position in session.positions:
        if position.stage == stage:
            return position.cursor, position.scroll
    return 0, 0


def _curses_single_event(curses, stdscr, title, labels, session: WizardSession) -> WizardInput:
    cursor, scroll = _position(session, session.current)
    try:
        result = _curses_singleselect(
            curses,
            stdscr,
            title,
            labels,
            wizard=True,
            initial_cursor=cursor,
            initial_scroll=scroll,
            header=_curses_header(stdscr, session),
        )
    except TypeError as error:
        if "unexpected keyword argument" not in str(error):
            raise
        result = _curses_singleselect(curses, stdscr, title, labels)
    if isinstance(result, WizardInput):
        return result
    if result is None:
        return WizardInput("quit", cursor=cursor, scroll=scroll)
    selected = int(result)
    return WizardInput("confirm", (selected,), selected, scroll)


def _curses_multi_event(
    curses,
    stdscr,
    title,
    labels,
    session: WizardSession,
    *,
    selected: Sequence[int] = (),
    details: Optional[Sequence[str]] = None,
    disabled: Optional[Sequence[bool]] = None,
    allow_add: bool = False,
    allow_source_maintenance: bool = False,
    cells: Optional[Sequence[Sequence[str]]] = None,
    pane_for: Optional[Callable[[int, int], Sequence[str]]] = None,
    reasons: Optional[Sequence[str]] = None,
    detail_for: Optional[Callable[[int], Sequence[str]]] = None,
    notice: str = "",
) -> WizardInput:
    cursor, scroll = _position(session, session.current)
    try:
        result = _curses_multiselect(
            curses,
            stdscr,
            title,
            labels,
            details=details,
            disabled=disabled,
            wizard=True,
            allow_add=allow_add,
            allow_source_maintenance=allow_source_maintenance,
            initial_checked=selected,
            initial_cursor=cursor,
            initial_scroll=scroll,
            header=_curses_header(stdscr, session),
            cells=cells,
            pane_for=pane_for,
            reasons=reasons,
            detail_for=detail_for,
            notice=notice,
        )
    except TypeError as error:
        if "unexpected keyword argument" not in str(error):
            raise
        result = _curses_multiselect(curses, stdscr, title, labels, details, disabled)
    if isinstance(result, WizardInput):
        return result
    if result is None:
        return WizardInput("quit", cursor=cursor, scroll=scroll)
    picked = tuple(int(index) for index in result)
    return WizardInput("confirm", picked, cursor, scroll)


def _curses_empty_source_event(curses, stdscr, session: WizardSession) -> WizardInput:
    """Keep source onboarding navigable when policy leaves no selectable source rows.

    A required source may be named by policy before the user has configured its origin.  There
    is deliberately no synthetic, untrusted row to toggle in that case; ``a`` remains the only
    productive action.  This has a dedicated screen rather than relying on the generic checkbox
    widget, whose empty-list result is a confirmation with no selection.
    """

    required = ("clear", "addstr", "refresh", "getch")
    if not all(hasattr(stdscr, name) for name in required):
        return WizardInput("quit")
    backspace = {getattr(curses, "KEY_BACKSPACE", -1), 127, 8}
    lines = _curses_header(stdscr, session) + (
        "Sources",
        "No sources are configured.",
        "Press a to add a source, Backspace to return, or q to quit.",
    )
    while True:
        stdscr.clear()
        available = max(_width(stdscr) - 1, 0)
        for row, line in enumerate(lines[: _height(stdscr)]):
            stdscr.addstr(row, 0, _ellipsize(line, available))
        stdscr.refresh()
        key = stdscr.getch()
        if key in (ord("a"), ord("A")):
            return WizardInput("add")
        if key in (ord("q"), 27):
            return WizardInput("quit")
        if key in backspace:
            return WizardInput("back")


def _curses_source_event(
    curses,
    stdscr,
    session: WizardSession,
    view: SourceStageView,
) -> Tuple[WizardInput, Optional[SourceSelection], Optional[DomainErr]]:
    choices = _source_choice_rows(view)
    if not choices:
        return _curses_empty_source_event(curses, stdscr, session), None, None
    selected_aliases = (
        set() if session.source_selection is None else set(session.source_selection.enabled_aliases)
    )
    selected = tuple(
        index for index, row in enumerate(view.rows) if row.source.alias in selected_aliases
    )
    if session.source_selection is not None and session.source_selection.no_source:
        selected += (len(view.rows),)
    elif session.source_selection is None:
        selected = tuple(index for index, row in enumerate(view.rows) if row.source.enabled)
    missing = view.unconfigured_required or view.unconfigured_recommended
    suffix = "" if not missing else " — configure: " + ", ".join(item.value for item in missing)
    notice = ""
    while True:
        event = _curses_multi_event(
            curses,
            stdscr,
            f"Sources{suffix}",
            tuple(choice.label for choice in choices),
            session,
            selected=selected,
            details=tuple(choice.description for choice in choices),
            disabled=tuple(not choice.enabled for choice in choices),
            reasons=tuple(choice.reason for choice in choices),
            allow_add=True,
            allow_source_maintenance=bool(view.rows),
            notice=notice,
        )
        if event.kind != "confirm":
            return event, None, None
        planned = _source_selection_from_indices(view, event.selected)
        if isinstance(planned, DomainErr):
            notice = _domain_feedback(planned)
            continue
        return event, planned, None


def _curses_text_input(
    curses,
    stdscr,
    session: WizardSession,
    prompt: str,
    *,
    default: str | None = None,
    maximum_length: int = 512,
) -> str | WizardInput:
    """Collect one bounded printable source field without leaving the full-screen wizard."""

    required = ("clear", "addstr", "refresh", "getch")
    if not all(hasattr(stdscr, name) for name in required):
        return WizardInput("quit")
    buffer = ""
    backspace = {getattr(curses, "KEY_BACKSPACE", -1), 127, 8}
    enter = {getattr(curses, "KEY_ENTER", -1), 10, 13}
    while True:
        stdscr.clear()
        available = max(_width(stdscr) - 1, 1)
        lines = _curses_header(stdscr, session) + (prompt,)
        for row, line in enumerate(lines):
            if row >= max(_height(stdscr) - 2, 0):
                break
            stdscr.addstr(row, 0, _ellipsize(line, available))
        input_row = min(len(lines) + 1, max(_height(stdscr) - 2, 0))
        shown = buffer or ("" if default is None else f"[{default}]")
        stdscr.addstr(input_row, 0, _ellipsize(f"> {shown}", available))
        if _height(stdscr) > 0:
            stdscr.addstr(
                _height(stdscr) - 1,
                0,
                status_bar(
                    (
                        ("enter", "continue"),
                        ("backspace", "back when empty"),
                        ("q", "quit when empty"),
                    ),
                    width=available,
                ),
            )
        stdscr.refresh()
        key = stdscr.getch()
        if key in enter:
            return buffer or (default or "")
        if key in backspace:
            if buffer:
                buffer = buffer[:-1]
            else:
                return WizardInput("back")
            continue
        if key in (27,) or (key in (ord("q"), ord("Q")) and not buffer):
            return WizardInput("quit")
        if 32 <= key <= 126 and len(buffer) < maximum_length:
            buffer += chr(key)


def _curses_notice(
    stdscr,
    session: WizardSession,
    title: str,
    lines: Sequence[str],
) -> None:
    """Show one bounded source-flow outcome before returning to the Sources stage.

    Curses has no scrollback after a form closes.  A short acknowledgement keeps parser,
    policy, sync, and success outcomes observable instead of silently dropping the user back at
    the checkbox list.
    """

    required = ("clear", "addstr", "refresh", "getch")
    if not all(hasattr(stdscr, name) for name in required):
        return
    content = _curses_header(stdscr, session) + (title, *lines)
    available = max(_width(stdscr) - 1, 1)
    content_width = min(available, CONTENT_MEASURE)
    stdscr.clear()
    for row, line in enumerate(content[: max(_height(stdscr) - 1, 0)]):
        stdscr.addstr(row, 0, _ellipsize(line, content_width))
    if _height(stdscr) > 0:
        stdscr.addstr(_height(stdscr) - 1, 0, _ellipsize("Press any key to continue.", available))
    stdscr.refresh()
    stdscr.getch()


def _source_flow_diagnostics(result: DomainErr) -> tuple[str, ...]:
    """Render a refused source operation, remediation included.

    Curses has no scrollback, so a notice that drops remediation leaves the user looking at a
    refusal with no stated way out — which is the whole failure this stage exists to end. Lines
    are wrapped rather than ellipsized, because the way out is usually the longest line.
    """

    lines: tuple[str, ...] = ()
    for diagnostic in result.diagnostics:
        lines += tuple(
            wrap(
                f"{diagnostic.severity.value} [{diagnostic.code.value}]: {diagnostic.message}",
                width=CONTENT_MEASURE,
            )
        )
        for remediation in diagnostic.remediation:
            prefix = "  next: "
            wrapped = wrap(remediation, width=CONTENT_MEASURE - len(prefix))
            lines += (prefix + wrapped[0],)
            lines += tuple(" " * len(prefix) + line for line in wrapped[1:])
    return lines


def _curses_source_review(
    curses,
    stdscr,
    session: WizardSession,
    review: Sequence[str],
    *,
    confirm_label: str,
) -> bool | WizardInput:
    """Show one bounded source review and collect the single yes/no decision it asks for."""

    required = ("clear", "addstr", "refresh", "getch")
    if not all(hasattr(stdscr, name) for name in required):
        return WizardInput("quit")
    lines = _curses_header(stdscr, session) + tuple(review)
    available = max(_width(stdscr) - 1, 1)
    backspace = {getattr(curses, "KEY_BACKSPACE", -1), 127, 8}
    enter = {getattr(curses, "KEY_ENTER", -1), 10, 13}
    while True:
        stdscr.clear()
        for row, line in enumerate(lines[: max(_height(stdscr) - 1, 0)]):
            stdscr.addstr(row, 0, _ellipsize(line, available))
        if _height(stdscr) > 0:
            stdscr.addstr(
                _height(stdscr) - 1,
                0,
                status_bar(
                    (("enter", confirm_label), ("b", "back"), ("q", "quit")),
                    width=available,
                ),
            )
        stdscr.refresh()
        key = stdscr.getch()
        if key in enter or key in (ord("y"), ord("Y")):
            return True
        if key in backspace or key in (ord("n"), ord("N"), ord("b")):
            return WizardInput("back")
        if key in (ord("q"), 27):
            return WizardInput("quit")


def _curses_source_addition_review(
    curses,
    stdscr,
    session: WizardSession,
    request: SourceAdditionRequest,
) -> bool | WizardInput:
    """Confirm the exact source-only effect before network acquisition and config persistence."""

    return _curses_source_review(
        curses,
        stdscr,
        session,
        render_source_addition_review(request),
        confirm_label="save",
    )


def _curses_source_sync(
    curses,
    stdscr,
    session: WizardSession,
    row: SourceStageRow,
) -> WizardInput | SourceStageRow:
    """Review one configured origin in curses before its snapshot is fetched again."""

    reviewed = _curses_source_review(
        curses,
        stdscr,
        session,
        render_source_sync_review(row),
        confirm_label="sync",
    )
    if isinstance(reviewed, WizardInput):
        return reviewed
    return row if reviewed else WizardInput("back")


def _curses_source_removal(
    curses,
    stdscr,
    session: WizardSession,
    view: SourceStageView,
    row: SourceStageRow,
) -> WizardInput | SourceRemovalRequest:
    """Plan and review one unsubscribe in curses through the planner the CLI also uses."""

    planned = plan_source_removal(view, row.source.alias)
    if isinstance(planned, DomainErr):
        _curses_notice(
            stdscr,
            session,
            "Source removal error",
            (*_source_flow_diagnostics(planned), "Choose another source or press b."),
        )
        return WizardInput("back")
    reviewed = _curses_source_review(
        curses,
        stdscr,
        session,
        render_source_removal_review(planned.value),
        confirm_label="remove",
    )
    if isinstance(reviewed, WizardInput):
        return reviewed
    return planned.value if reviewed else WizardInput("back")


def _curses_source_addition(
    curses,
    stdscr,
    session: WizardSession,
    view: SourceStageView,
) -> WizardInput | SourceAdditionRequest:
    """Curses counterpart of the text source setup form with the same parser and planner."""

    choices = _source_kind_choices(view)
    kind_event = _curses_single_event(
        curses,
        stdscr,
        "Add source",
        tuple(label for _kind, label in choices),
        session,
    )
    if kind_event.kind != "confirm":
        return kind_event
    kind = choices[kind_event.selected[0]][0]
    default_alias = {
        SourceKind.REGISTRY_GIT: "registry",
        SourceKind.SOURCE_GIT: "source",
        SourceKind.SOURCE_LOCAL: "local",
    }[kind]
    alias = _curses_text_input(
        curses,
        stdscr,
        session,
        "Source alias:",
        default=default_alias,
    )
    if isinstance(alias, WizardInput):
        return alias
    location = _curses_text_input(
        curses,
        stdscr,
        session,
        "Local directory:" if kind is SourceKind.SOURCE_LOCAL else "Git URL:",
    )
    if isinstance(location, WizardInput):
        return location
    if not location:
        _curses_notice(
            stdscr,
            session,
            "Source setup error",
            ("A local directory or Git URL is required. Choose Add to retry.",),
        )
        return WizardInput("back")
    ref: str | None = None
    if kind is not SourceKind.SOURCE_LOCAL:
        prompted_ref = _curses_text_input(
            curses,
            stdscr,
            session,
            "Git ref:",
            default="main",
        )
        if isinstance(prompted_ref, WizardInput):
            return prompted_ref
        ref = prompted_ref
    parsed = configured_source_from_input(alias, kind, location, ref)
    if isinstance(parsed, DomainErr):
        _curses_notice(
            stdscr,
            session,
            "Source setup error",
            (*_source_flow_diagnostics(parsed), "Choose Add to retry."),
        )
        return WizardInput("back")
    planned = plan_source_addition(
        view,
        parsed.value,
        make_default=not any(row.source.is_registry for row in view.rows),
    )
    if isinstance(planned, DomainErr):
        _curses_notice(
            stdscr,
            session,
            "Source setup error",
            (*_source_flow_diagnostics(planned), "Choose Add to retry."),
        )
        return WizardInput("back")
    reviewed = _curses_source_addition_review(curses, stdscr, session, planned.value)
    if isinstance(reviewed, WizardInput):
        return reviewed
    if reviewed:
        return planned.value
    return WizardInput("back")


def _curses_confirm_discard(curses, stdscr, session: WizardSession) -> bool:
    if request_quit(session) == "quit":
        return True
    if not all(hasattr(stdscr, name) for name in ("clear", "addstr", "refresh", "getch")):
        return True
    lines = _curses_header(stdscr, session) + (
        f"Discard {len(session.basket)} selected basket item(s)?",
    )
    while True:
        stdscr.clear()
        available = max(_width(stdscr) - 1, 0)
        height = _height(stdscr)
        for row, line in enumerate(lines[: max(height - 1, 1)]):
            stdscr.addstr(row, 0, _ellipsize(line, available))
        if height:
            stdscr.addstr(
                height - 1,
                0,
                status_bar((("y", "discard"), ("n", "return")), width=available),
            )
        stdscr.refresh()
        key = stdscr.getch()
        if key in (ord("y"), ord("Y")):
            return True
        if key in (
            ord("n"),
            ord("N"),
            getattr(curses, "KEY_BACKSPACE", -1),
            127,
            8,
        ):
            return False


def _curses_review(curses, stdscr, session: WizardSession, lines: Sequence[str]):
    if not all(hasattr(stdscr, name) for name in ("clear", "addstr", "refresh", "getch")):
        return False
    content = _curses_header(stdscr, session) + tuple(lines)
    offset = 0
    while True:
        stdscr.clear()
        available = max(_width(stdscr) - 1, 0)
        height = _height(stdscr)
        body_height = max(height - 1, 1)
        max_offset = max(len(content) - body_height, 0)
        offset = min(offset, max_offset)
        for row, line in enumerate(content[offset : offset + body_height]):
            stdscr.addstr(row, 0, _ellipsize(line, available))
        if height:
            stdscr.addstr(
                height - 1,
                0,
                status_bar(
                    (("enter", "finalize"), ("b", "back"), ("q", "quit")),
                    width=available,
                ),
            )
        stdscr.refresh()
        key = stdscr.getch()
        if key in (curses.KEY_ENTER, 10, 13, ord("y"), ord("Y")):
            return True
        if key in (getattr(curses, "KEY_BACKSPACE", -1), 127, 8, ord("b")):
            return "back"
        if key in (ord("q"), 27):
            return "quit"
        if key in (ord("n"), ord("N")):
            return False
        if key in (curses.KEY_DOWN, ord("j")) and offset < max_offset:
            offset += 1
        elif key in (curses.KEY_UP, ord("k")) and offset > 0:
            offset -= 1
        elif key == getattr(curses, "KEY_NPAGE", -1) and offset < max_offset:
            offset = min(offset + body_height, max_offset)
        elif key == getattr(curses, "KEY_PPAGE", -1) and offset > 0:
            offset = max(offset - body_height, 0)


def _run_user_curses_wizard(
    curses,
    stdscr,
    session: WizardSession,
    selection: dict,
    *,
    source_dir: Optional[str],
    repo: Optional[str],
    project: Optional[str],
    user_home: Optional[str],
    consumer_service: Optional[ConsumerApplicationService] = None,
    failure_context: InternalFailureContext | None = None,
) -> WizardSession:
    context = failure_context or InternalFailureContext()
    profile_names = tuple(sorted(load_profiles(project)))
    read_model: Optional[_UserWizardReadModel] = None
    read_key: Optional[tuple] = None
    while session.current not in ("role", "source", "maintainer_action"):
        context.capture(session)
        if session.current == "profiles":
            selected = tuple(
                index for index, name in enumerate(profile_names) if name in session.profiles
            )
            event = _curses_multi_event(
                curses,
                stdscr,
                "Select profiles",
                profile_names,
                session,
                selected=selected,
            )
            session = remember_position(
                session, "profiles", cursor=event.cursor, scroll=event.scroll
            )
            if event.kind == "back":
                session = wizard_back(session)
                continue
            if event.kind == "quit":
                if _curses_confirm_discard(curses, stdscr, session):
                    selection["cancelled"] = True
                    return session
                continue
            if not event.selected:
                selection["empty_selection"] = True
                return session
            session = wizard_select(
                session,
                "profiles",
                tuple(profile_names[index] for index in event.selected),
            )
            session = wizard_advance(session)
            continue

        if session.current == "action":
            event = _curses_single_event(
                curses,
                stdscr,
                "Action",
                ACTIONS,
                session,
            )
            session = remember_position(session, "action", cursor=event.cursor, scroll=event.scroll)
            if event.kind == "back":
                session = wizard_back(session)
                continue
            if event.kind == "quit":
                if _curses_confirm_discard(curses, stdscr, session):
                    selection["cancelled"] = True
                    return session
                continue
            action = ACTIONS[event.selected[0]]
            session = wizard_select(session, "action", action)
            if action == "status" and session.basket:
                session = reconcile_basket(
                    session,
                    {item.key: "not applicable to the Status action" for item in session.basket},
                )
            session = wizard_advance(session)
            read_model = None
            continue

        if session.current == "scope":
            cursor, scroll = _position(session, "scope")
            try:
                result = _curses_install_scope(
                    curses,
                    stdscr,
                    wizard=True,
                    initial_cursor=cursor,
                    initial_scroll=scroll,
                    header=_curses_header(stdscr, session),
                )
            except TypeError as error:
                if "unexpected keyword argument" not in str(error):
                    raise
                result = _curses_install_scope(curses, stdscr)
            if isinstance(result, WizardInput):
                event = result
                scope = INSTALL_SCOPE_CHOICES[event.selected[0]].scope if event.selected else None
            else:
                scope = result
                event = (
                    WizardInput("quit", cursor=cursor, scroll=scroll)
                    if scope is None
                    else WizardInput(
                        "confirm",
                        (0 if scope == "project" else 1,),
                        0 if scope == "project" else 1,
                        scroll,
                    )
                )
            session = remember_position(session, "scope", cursor=event.cursor, scroll=event.scroll)
            if event.kind == "back":
                session = wizard_back(session)
                continue
            if event.kind == "quit":
                if _curses_confirm_discard(curses, stdscr, session):
                    selection["cancelled"] = True
                    return session
                continue
            assert scope is not None
            session = wizard_select(session, "scope", scope)
            session = wizard_advance(session)
            read_model = None
            continue

        if session.current == "mode":
            cursor, scroll = _position(session, "mode")
            try:
                result = _curses_install_mode(
                    curses,
                    stdscr,
                    wizard=True,
                    initial_cursor=cursor,
                    initial_scroll=scroll,
                    header=_curses_header(stdscr, session),
                )
            except TypeError as error:
                if "unexpected keyword argument" not in str(error):
                    raise
                result = _curses_install_mode(curses, stdscr)
            if isinstance(result, WizardInput):
                event = result
                mode = INSTALL_MODE_CHOICES[event.selected[0]].mode if event.selected else None
            else:
                mode = result
                if result == "back":
                    event = WizardInput("back", cursor=cursor, scroll=scroll)
                elif result is None:
                    event = WizardInput("quit", cursor=cursor, scroll=scroll)
                else:
                    index = 0 if result == "copy" else 1
                    event = WizardInput("confirm", (index,), index, scroll)
            session = remember_position(session, "mode", cursor=event.cursor, scroll=event.scroll)
            if event.kind == "back":
                session = wizard_back(session)
                continue
            if event.kind == "quit":
                if _curses_confirm_discard(curses, stdscr, session):
                    selection["cancelled"] = True
                    return session
                continue
            assert mode is not None
            session = wizard_select(session, "mode", mode)
            session = wizard_advance(session)
            read_model = None
            continue

        if session.current == "artifacts":
            key = (session.action, session.profiles, session.scope, session.install_mode)
            if read_model is None or read_key != key:
                loaded = _load_user_wizard_read_model(
                    session,
                    source_factory=_unsupported_source_factory,
                    source_dir=source_dir,
                    repo=repo,
                    project=project,
                    user_home=user_home,
                    consumer_service=consumer_service,
                )
                if isinstance(loaded, DomainErr):
                    failure = wizard_stage_failure(
                        session,
                        "load",
                        loaded,
                        project=_failure_project_context(session, project),
                    )
                    recovery = _curses_stage_failure_recovery(curses, stdscr, failure)
                    if recovery.kind == "retry":
                        read_model = None
                        read_key = None
                        continue
                    if recovery.kind == "back":
                        session = wizard_back(session)
                        continue
                    if _curses_confirm_discard(curses, stdscr, session):
                        selection["cancelled"] = True
                        return session
                    continue
                read_model = loaded.value
                read_key = key
            if not read_model.choices:
                selection["empty"] = (session.action or "selection", session.profiles)
                return session
            availability = {
                _basket_key(choice): "" if choice.enabled else choice.reason
                for choice in read_model.choices
            }
            session = reconcile_basket(session, availability)
            basket_keys = {item.key for item in session.basket}
            selected = tuple(
                index
                for index, choice in enumerate(read_model.choices)
                if _basket_key(choice) in basket_keys
            )
            event = _curses_multi_event(
                curses,
                stdscr,
                "Select artifacts and bundles",
                tuple(choice.label for choice in read_model.choices),
                session,
                selected=selected,
                details=tuple(choice.description for choice in read_model.choices),
                disabled=tuple(not choice.enabled for choice in read_model.choices),
                reasons=tuple(choice.reason for choice in read_model.choices),
                cells=tuple(choice.cells or (choice.label,) for choice in read_model.choices),
                pane_for=functools.partial(_choice_pane, read_model.choices),
                detail_for=functools.partial(_choice_detail, read_model.choices),
            )
            session = remember_position(
                session, "artifacts", cursor=event.cursor, scroll=event.scroll
            )
            if event.kind == "back":
                session = wizard_back(session)
                continue
            if event.kind == "quit":
                if _curses_confirm_discard(curses, stdscr, session):
                    selection["cancelled"] = True
                    return session
                continue
            if not event.selected:
                selection["empty_selection"] = True
                return session
            disabled_picks = tuple(
                index for index in event.selected if not read_model.choices[index].enabled
            )
            if disabled_picks:
                choice = read_model.choices[disabled_picks[0]]
                selection["error"] = (f"{choice.name}: {choice.reason}", 2)
                return session
            session = wizard_select(
                session,
                "artifacts",
                tuple(_basket_item(read_model.choices[index]) for index in event.selected),
            )
            session = wizard_advance(session)
            continue

        if session.current == "review":
            context.capture(session, "review")
            assert consumer_service is not None
            selected_keys = {item.key for item in session.basket}
            selected_coordinates = (
                set()
                if read_model is None
                else {
                    row.coordinate
                    for row in read_model.marketplace_rows
                    if row.key in selected_keys
                }
            )
            for collection in consumer_service.context.catalog.collections:
                if str(collection.coordinate) in selected_keys:
                    selected_coordinates.update(collection.members)
            prepared = consumer_service.prepare(
                ConsumerActionRequest(
                    session.action or "status",  # type: ignore[arg-type]
                    tuple(sorted(selected_coordinates, key=str)),
                    tuple(sorted(session.profiles)),
                    session.scope,  # type: ignore[arg-type]
                    session.install_mode,  # type: ignore[arg-type]
                )
            )
            if isinstance(prepared, DomainErr):
                failure = wizard_stage_failure(session, "review", prepared, recoverable=False)
                recovery = _curses_stage_failure_recovery(curses, stdscr, failure)
                if recovery.kind == "back":
                    session = wizard_back(session)
                    continue
                if _curses_confirm_discard(curses, stdscr, session):
                    selection["cancelled"] = True
                    return session
                continue
            canonical_review = prepared.value
            review = _curses_review(
                curses,
                stdscr,
                session,
                render_consumer_review(canonical_review),
            )
            if review == "back":
                session = wizard_back(session)
                continue
            if review == "quit":
                if _curses_confirm_discard(curses, stdscr, session):
                    selection["cancelled"] = True
                    return session
                continue
            if not review:
                selection["cancelled"] = True
                return session
            if not can_finalize(session, revision=session.revision):
                selection["error"] = ("Wizard state changed; review it again before Finalize.", 2)
                return session
            selection["consumer_review"] = canonical_review
            selection["wizard_session"] = session
            return session

    return session


class CursesUnavailable(Exception):
    """The terminal cannot host the curses wizard.

    Raised only for import, TTY, or curses initialisation failure detected **before** the wizard
    interacts with the user. It is the sole condition under which the text wizard may start as a
    fallback. Any failure after interaction begins propagates instead, so a defect is never
    mistaken for a missing terminal and never silently restarts the wizard at onboarding with the
    user's selections discarded.
    """


INTERNAL_FAILURE_CODE = "tui-stage-internal"


@dataclass(slots=True)
class InternalFailureContext:
    """The last safe frontend boundary, kept outside the persistent wizard session."""

    stage: WizardStage = "onboarding"
    operation: WizardOperation = "load"

    def capture(self, session: WizardSession, operation: WizardOperation = "load") -> None:
        self.stage = session.current
        self.operation = operation

    def capture_operation(self, operation: WizardOperation) -> None:
        """Mark a shell operation while retaining the stage captured at its boundary."""

        self.operation = operation


def internal_failure_lines(
    error: BaseException,
    context: InternalFailureContext | None = None,
) -> Tuple[str, ...]:
    """Project a defect into stable, redacted terminal lines.

    Only the exception *type* is disclosed. Messages can carry filesystem paths, subprocess
    output, or setup input, so they are withheld by default. Context contains only the last safe
    stage and operation; it never owns terminal, service, or domain-state objects.
    """

    failure_context = context or InternalFailureContext()
    return (
        f"internal error: {INTERNAL_FAILURE_CODE}",
        f"  stage: {failure_context.stage}",
        f"  operation: {failure_context.operation}",
        f"  type: {type(error).__name__}",
        "next: rerun the command; if it repeats, report it with the steps that reached this screen.",
    )


def _debug_traceback_enabled() -> bool:
    """Enable an explicitly local traceback channel without changing normal terminal output."""

    return os.environ.get("AART_DEBUG") == "1"


def _render_internal_failure(
    error: BaseException,
    context: InternalFailureContext | None = None,
) -> int:
    for line in internal_failure_lines(error, context):
        print(line)
    if _debug_traceback_enabled():
        traceback.print_exception(error, file=sys.stderr)
    return 2


def _run_curses(
    *,
    source_dir: Optional[str] = None,
    repo: Optional[str] = None,
    project: Optional[str] = None,
    user_home: Optional[str] = None,
    source_stage_view: Optional[SourceStageView] = None,
    source_finalizer: Optional[SourceFinalizeFn] = None,
    source_addition_finalizer: Optional[SourceAdditionFinalizeFn] = None,
    source_removal_finalizer: Optional[SourceRemovalFinalizeFn] = None,
    source_sync_runner: Optional[SourceSyncRunFn] = None,
    source_stage_loader: Optional[SourceStageLoader] = None,
    consumer_service: Optional[ConsumerApplicationService] = None,
    consumer_service_factory: Optional[ConsumerServiceFactory] = None,
    reporting_service: Optional[ReportingApplicationService] = None,
    reporting_service_factory: Optional[ReportingServiceFactory] = None,
    curation_service_factory: Optional[CurationServiceFactory] = None,
    failure_context: InternalFailureContext | None = None,
) -> int:
    """Collect a persistent wizard session and dispatch only after curses teardown."""
    try:
        import curses  # stdlib; imported lazily so the text path needs no terminal at all.
    except ImportError as error:
        raise CursesUnavailable("the curses wizard could not start") from error

    context = failure_context or InternalFailureContext()
    if not load_profiles(project):  # pragma: no cover - built-ins always present
        print("No profiles available.")
        return 0
    selection: dict = {}
    interacted = False
    if repo is not None:
        print(
            "error: direct legacy repository selection is no longer supported; "
            "add a canonical registry in Sources instead."
        )
        return 2
    stage_view = source_stage_view or _empty_source_stage_view()

    def _ui(stdscr) -> None:
        nonlocal stage_view, source_stage_view, source_finalizer, source_addition_finalizer
        nonlocal source_removal_finalizer, source_sync_runner
        nonlocal interacted

        def reload_stage() -> DomainErr | None:
            """Re-read the Sources stage after a mutation, keeping the fallback view in step.

            The text fallback below receives ``source_stage_view``.  Keeping it identical to the
            live curses value means a later terminal exception cannot make a source that was
            really added, synchronized, or removed look untouched.
            """

            nonlocal stage_view, source_stage_view, source_finalizer
            nonlocal source_addition_finalizer, source_removal_finalizer, source_sync_runner
            if source_stage_loader is None:
                return None
            refreshed = source_stage_loader()
            if isinstance(refreshed, DomainErr):
                return refreshed
            stage_view = refreshed.value.view
            source_stage_view = stage_view
            source_finalizer = refreshed.value.source_finalizer
            source_addition_finalizer = refreshed.value.source_addition_finalizer
            source_removal_finalizer = refreshed.value.source_removal_finalizer
            source_sync_runner = refreshed.value.source_sync_runner
            return None

        curses.curs_set(0)
        # Past this point curses is initialised and the screen is ours: any later failure is a
        # defect in the wizard, not a terminal that cannot host it.
        interacted = True
        session = initial_session()
        context.capture(session)
        onboarding = _curses_onboarding(curses, stdscr)
        if onboarding.kind == "quit":
            selection["cancelled"] = True
            return
        session = wizard_advance(session)
        while session.current in ("role", "source"):
            context.capture(session)
            if session.current == "role":
                event = _curses_single_event(
                    curses,
                    stdscr,
                    "Choose how you want to use aart",
                    tuple(f"{role.label} - {role.description}" for role in ROLES),
                    session,
                )
                session = remember_position(
                    session, "role", cursor=event.cursor, scroll=event.scroll
                )
                if event.kind == "back":
                    onboarding = _curses_onboarding(curses, stdscr)
                    if onboarding.kind == "quit":
                        selection["cancelled"] = True
                        return
                    continue
                if event.kind == "quit":
                    selection["cancelled"] = True
                    return
                role = ROLES[event.selected[0]].name
                session = wizard_select(session, "role", role)
                if (
                    role == "maintainer"
                    and repo is None
                    and (
                        source_dir is None
                        or _is_canonical_maintainer_workspace(os.path.abspath(source_dir))
                    )
                ):
                    session = use_current_checkout(session)
                session = wizard_advance(session)

            if session.current == "maintainer_action" and session.maintainer_checkout:
                catalog_root = os.path.abspath(source_dir or os.getcwd())
                canonical_curation = _is_canonical_maintainer_workspace(catalog_root)
                maintainer_actions = CANONICAL_MAINTAINER_ACTIONS
                if not canonical_curation:
                    selection["error"] = (
                        "maintainer mode accepts only a canonical registry checkout; "
                        "initialize one with `aart registry init`.",
                        2,
                    )
                    return
                event = _curses_single_event(
                    curses,
                    stdscr,
                    f"Maintainer - {catalog_root}",
                    tuple(label for _action, label in maintainer_actions),
                    session,
                )
                if event.kind == "back":
                    session = wizard_back(session)
                    continue
                if event.kind == "quit":
                    selection["cancelled"] = True
                    return
                action = maintainer_actions[event.selected[0]][0]
                session = wizard_select(session, "maintainer_action", action)
                session = wizard_advance(session)
                if action == "user":
                    maintainer_consumer_service = consumer_service
                    maintainer_reporting_service = reporting_service
                    maintainer_reporting_failed = False
                    active_consumer_factory = consumer_service_factory
                    if active_consumer_factory is None and canonical_curation:
                        from .consumer.runtime import load_local_consumer_service

                        def active_consumer_factory(
                            configuration: UserConfiguration,
                        ) -> DomainResult[ConsumerApplicationService]:
                            return load_local_consumer_service(
                                project=project,
                                user_home=user_home,
                                configuration=configuration,
                            )

                    if active_consumer_factory is not None:
                        loaded_consumer = active_consumer_factory(stage_view.configuration)
                        if isinstance(loaded_consumer, DomainErr):
                            failure = _maintainer_action_failure(session, loaded_consumer)
                            recovery = _curses_stage_failure_recovery(curses, stdscr, failure)
                            if recovery.kind == "back":
                                session = wizard_back(session)
                                continue
                            if _curses_confirm_discard(curses, stdscr, session):
                                selection["cancelled"] = True
                                return
                            continue
                        maintainer_consumer_service = loaded_consumer.value
                    if reporting_service_factory is not None:
                        loaded_reporting = reporting_service_factory(stage_view.configuration)
                        if isinstance(loaded_reporting, DomainErr):
                            maintainer_reporting_service = None
                            maintainer_reporting_failed = True
                        else:
                            maintainer_reporting_service = loaded_reporting.value
                    session = _run_user_curses_wizard(
                        curses,
                        stdscr,
                        session,
                        selection,
                        source_dir=catalog_root,
                        repo=None,
                        project=project,
                        user_home=user_home,
                        consumer_service=maintainer_consumer_service,
                        failure_context=context,
                    )
                    if selection.get("consumer_review") is not None:
                        selection["active_consumer_service"] = maintainer_consumer_service
                        selection["active_reporting_service"] = maintainer_reporting_service
                        if maintainer_reporting_failed:
                            selection["reporting_warning"] = True
                    return
                selection["maintainer_action"] = action
                selection["maintainer_session"] = session
                selection["source_arguments"] = (catalog_root, None)
                selection["consumer_configuration"] = stage_view.configuration
                return

            assert session.current == "source"
            event, maybe_selected_source, source_error = _curses_source_event(
                curses,
                stdscr,
                session,
                stage_view,
            )
            session = remember_position(session, "source", cursor=event.cursor, scroll=event.scroll)
            if event.kind == "back":
                session = wizard_back(session)
                continue
            if event.kind == "quit":
                selection["cancelled"] = True
                return
            if event.kind == "add":
                if source_addition_finalizer is None or source_stage_loader is None:
                    selection["error"] = ("source setup is unavailable in this TUI runtime", 2)
                    return
                addition = _curses_source_addition(curses, stdscr, session, stage_view)
                if isinstance(addition, WizardInput):
                    if addition.kind == "quit":
                        selection["cancelled"] = True
                        return
                    continue
                if all(hasattr(stdscr, name) for name in ("clear", "addstr", "refresh")):
                    stdscr.clear()
                    stdscr.addstr(0, 0, "Synchronizing and validating the source…")
                    stdscr.refresh()
                context.capture(session, "finalize")
                finalized_addition = source_addition_finalizer(addition)
                if isinstance(finalized_addition, DomainErr):
                    _curses_notice(
                        stdscr,
                        session,
                        "Source setup failed",
                        (
                            *_source_flow_diagnostics(finalized_addition),
                            "The source was not saved. Choose Add to retry.",
                        ),
                    )
                    continue
                context.capture(session)
                stale = reload_stage()
                if stale is not None:
                    _curses_notice(
                        stdscr,
                        session,
                        "Source setup incomplete",
                        (
                            *_source_flow_diagnostics(stale),
                            "The source was saved, but restart aart to reload Sources.",
                        ),
                    )
                    continue
                session = replace(
                    session,
                    source_selection=None,
                    revision=session.revision + 1,
                )
                _curses_notice(
                    stdscr,
                    session,
                    "Source setup complete",
                    (
                        f"Sources: synchronized and saved {addition.source.alias}.",
                        "Choose enabled source(s) to continue.",
                    ),
                )
                continue
            if event.kind == "sync":
                if source_sync_runner is None or source_stage_loader is None:
                    selection["error"] = (
                        "source synchronization is unavailable in this TUI runtime",
                        2,
                    )
                    return
                row = _selected_source_row(stage_view, event.selected)
                if row is None:
                    _curses_notice(
                        stdscr,
                        session,
                        "Synchronize source",
                        ("Move the cursor onto a configured source, then press s.",),
                    )
                    continue
                reviewed = _curses_source_sync(curses, stdscr, session, row)
                if isinstance(reviewed, WizardInput):
                    if reviewed.kind == "quit":
                        selection["cancelled"] = True
                        return
                    continue
                if all(hasattr(stdscr, name) for name in ("clear", "addstr", "refresh")):
                    stdscr.clear()
                    stdscr.addstr(0, 0, "Synchronizing and validating the source…")
                    stdscr.refresh()
                context.capture(session, "finalize")
                synchronized = source_sync_runner(row.source.alias)
                if isinstance(synchronized, DomainErr):
                    _curses_notice(
                        stdscr,
                        session,
                        "Source sync failed",
                        (
                            *_source_flow_diagnostics(synchronized),
                            f"{row.source.alias} was not synchronized; its snapshot is unchanged.",
                            "In Sources: s retries, r removes this source, a adds one.",
                        ),
                    )
                    continue
                context.capture(session)
                outcome_lines = render_source_sync_outcome(row.source.alias, synchronized.value)
                stale = reload_stage()
                if stale is not None:
                    _curses_notice(
                        stdscr,
                        session,
                        "Source sync incomplete",
                        (
                            *outcome_lines,
                            *_source_flow_diagnostics(stale),
                            "Restart aart to reload Sources.",
                        ),
                    )
                    continue
                session = replace(
                    session,
                    source_selection=None,
                    revision=session.revision + 1,
                )
                _curses_notice(
                    stdscr,
                    session,
                    "Source sync complete",
                    (*outcome_lines, "Choose enabled source(s) to continue."),
                )
                continue
            if event.kind == "remove":
                if source_removal_finalizer is None or source_stage_loader is None:
                    selection["error"] = ("source removal is unavailable in this TUI runtime", 2)
                    return
                row = _selected_source_row(stage_view, event.selected)
                if row is None:
                    _curses_notice(
                        stdscr,
                        session,
                        "Remove source",
                        ("Move the cursor onto a configured source, then press r.",),
                    )
                    continue
                removal = _curses_source_removal(curses, stdscr, session, stage_view, row)
                if isinstance(removal, WizardInput):
                    if removal.kind == "quit":
                        selection["cancelled"] = True
                        return
                    continue
                if all(hasattr(stdscr, name) for name in ("clear", "addstr", "refresh")):
                    stdscr.clear()
                    stdscr.addstr(0, 0, "Removing the source and deleting its snapshot…")
                    stdscr.refresh()
                context.capture(session, "finalize")
                finalized_removal = source_removal_finalizer(removal)
                if isinstance(finalized_removal, DomainErr):
                    _curses_notice(
                        stdscr,
                        session,
                        "Source removal failed",
                        (
                            *_source_flow_diagnostics(finalized_removal),
                            f"{removal.source.alias} was not removed.",
                            "In Sources: r retries the removal, s synchronizes instead.",
                        ),
                    )
                    continue
                context.capture(session)
                cleared = ("The default registry was cleared.",) if removal.cleared_default else ()
                stale = reload_stage()
                if stale is not None:
                    _curses_notice(
                        stdscr,
                        session,
                        "Source removal incomplete",
                        (
                            f"Sources: removed {removal.source.alias}.",
                            *cleared,
                            *_source_flow_diagnostics(stale),
                            "Restart aart to reload Sources.",
                        ),
                    )
                    continue
                session = replace(
                    session,
                    source_selection=None,
                    revision=session.revision + 1,
                )
                _curses_notice(
                    stdscr,
                    session,
                    "Source removed",
                    (
                        f"Sources: removed {removal.source.alias} and deleted its snapshot.",
                        *cleared,
                        "Choose enabled source(s) to continue.",
                    ),
                )
                continue
            if source_error is not None:
                failure = _source_stage_failure(session, source_error)
                recovery = _curses_stage_failure_recovery(curses, stdscr, failure)
                if recovery.kind == "back":
                    continue
                if _curses_confirm_discard(curses, stdscr, session):
                    selection["cancelled"] = True
                    return
                continue
            assert maybe_selected_source is not None
            selected_source_value = maybe_selected_source
            session = wizard_select(session, "source", selected_source_value)
            session = wizard_advance(session)
            if selected_source_value.no_source:
                selection["no_source"] = True
                return
            selected_role = session.role
            assert selected_role is not None
            active_consumer_service = consumer_service
            active_reporting_service = reporting_service
            active_reporting_failed = False
            if consumer_service_factory is not None and selected_role == "user":
                loaded_consumer = consumer_service_factory(selected_source_value.request.after)
                if isinstance(loaded_consumer, DomainErr):
                    failure = _source_stage_failure(session, loaded_consumer)
                    recovery = _curses_stage_failure_recovery(curses, stdscr, failure)
                    if recovery.kind == "back":
                        session = wizard_back(session)
                        continue
                    if _curses_confirm_discard(curses, stdscr, session):
                        selection["cancelled"] = True
                        return
                    continue
                active_consumer_service = loaded_consumer.value
            if reporting_service_factory is not None and selected_role == "user":
                loaded_reporting = reporting_service_factory(selected_source_value.request.after)
                if isinstance(loaded_reporting, DomainErr):
                    active_reporting_service = None
                    active_reporting_failed = True
                else:
                    active_reporting_service = loaded_reporting.value
            if selected_role == "user":
                if active_consumer_service is None:
                    selection["error"] = (
                        "canonical consumer services are unavailable; "
                        "restart after configuring a registry source.",
                        2,
                    )
                    return
                session = _run_user_curses_wizard(
                    curses,
                    stdscr,
                    session,
                    selection,
                    source_dir=None,
                    repo=None,
                    project=project,
                    user_home=user_home,
                    consumer_service=active_consumer_service,
                    failure_context=context,
                )
                if selection.get("consumer_review") is not None:
                    selection["active_consumer_service"] = active_consumer_service
                    selection["active_reporting_service"] = active_reporting_service
                    if active_reporting_failed:
                        selection["reporting_warning"] = True
                if selection:
                    return
                if session.current in ("role", "source"):
                    continue
                return

            catalog_root = os.path.abspath(source_dir or os.getcwd())
            canonical_curation = _is_canonical_maintainer_workspace(catalog_root)
            maintainer_actions = CANONICAL_MAINTAINER_ACTIONS
            if not canonical_curation:
                selection["error"] = (
                    "maintainer mode accepts only a canonical registry checkout; "
                    "initialize one with `aart registry init`.",
                    2,
                )
                return
            while session.current == "maintainer_action":
                context.capture(session)
                event = _curses_single_event(
                    curses,
                    stdscr,
                    f"Maintainer - {catalog_root}",
                    tuple(label for _action, label in maintainer_actions),
                    session,
                )
                if event.kind == "back":
                    session = wizard_back(session)
                    break
                if event.kind == "quit":
                    selection["cancelled"] = True
                    return
                action = maintainer_actions[event.selected[0]][0]
                session = wizard_select(session, "maintainer_action", action)
                session = wizard_advance(session)
                if action == "user":
                    maintainer_consumer_service = consumer_service
                    maintainer_reporting_service = reporting_service
                    maintainer_reporting_failed = False
                    active_consumer_factory = consumer_service_factory
                    if active_consumer_factory is None and canonical_curation:
                        from .consumer.runtime import load_local_consumer_service

                        def active_consumer_factory(
                            configuration: UserConfiguration,
                        ) -> DomainResult[ConsumerApplicationService]:
                            return load_local_consumer_service(
                                project=project,
                                user_home=user_home,
                                configuration=configuration,
                            )

                    if active_consumer_factory is not None:
                        loaded_consumer = active_consumer_factory(
                            selected_source_value.request.after
                        )
                        if isinstance(loaded_consumer, DomainErr):
                            failure = wizard_stage_failure(
                                session,
                                "load",
                                loaded_consumer,
                                stage="maintainer_action",
                                recoverable=False,
                            )
                            recovery = _curses_stage_failure_recovery(curses, stdscr, failure)
                            if recovery.kind == "back":
                                session = wizard_back(session)
                                continue
                            if _curses_confirm_discard(curses, stdscr, session):
                                selection["cancelled"] = True
                                return
                            continue
                        maintainer_consumer_service = loaded_consumer.value
                    if reporting_service_factory is not None:
                        loaded_reporting = reporting_service_factory(
                            selected_source_value.request.after
                        )
                        if isinstance(loaded_reporting, DomainErr):
                            maintainer_reporting_service = None
                            maintainer_reporting_failed = True
                        else:
                            maintainer_reporting_service = loaded_reporting.value
                    session = _run_user_curses_wizard(
                        curses,
                        stdscr,
                        session,
                        selection,
                        source_dir=None,
                        repo=None,
                        project=project,
                        user_home=user_home,
                        consumer_service=maintainer_consumer_service,
                        failure_context=context,
                    )
                    if selection.get("consumer_review") is not None:
                        selection["active_consumer_service"] = maintainer_consumer_service
                        selection["active_reporting_service"] = maintainer_reporting_service
                        if maintainer_reporting_failed:
                            selection["reporting_warning"] = True
                    if selection or session.current != "maintainer_action":
                        return
                    continue
                selection["maintainer_action"] = action
                selection["maintainer_session"] = session
                selection["source_arguments"] = (catalog_root, None)
                selection["consumer_configuration"] = selected_source_value.request.after
                return

    try:
        curses.wrapper(_ui)
    except Exception as error:
        if interacted:
            # The wizard was live; this is a defect. Let it reach the crash boundary in ``run``
            # rather than discarding the session behind a second wizard.
            raise
        raise CursesUnavailable("the curses wizard could not start") from error

    if "error" in selection:
        failure_or_error = selection["error"]
        if isinstance(failure_or_error, WizardStageFailure):
            for line in render_wizard_stage_failure(failure_or_error):
                print(line)
            return _stage_failure_exit_code(failure_or_error)
        reason, code = failure_or_error
        print(f"error: {reason}")
        return code
    if "empty" in selection:
        action, profiles = selection["empty"]
        print(_empty_choices_message(action, profiles))
        return _render_result(CommandOutcome(0, ActionSummary(action=action)), print)
    if "no_source" in selection:
        return _cancel(
            print,
            "No sources selected; no registry was forced and no changes were made.",
        )
    if "maintainer_action" in selection:
        active_source_dir, active_repo = selection.get(
            "source_arguments",
            (source_dir, repo),
        )
        result = _run_maintainer_text(
            selection["maintainer_session"],
            input,
            print,
            source_factory=_unsupported_source_factory,
            source_dir=active_source_dir,
            repo=active_repo,
            project=project,
            user_home=user_home,
            source_finalizer=source_finalizer,
            consumer_service_factory=consumer_service_factory,
            reporting_service_factory=reporting_service_factory,
            consumer_configuration=selection.get("consumer_configuration"),
            curation_service_factory=curation_service_factory,
        )
        return _cancel(print) if isinstance(result, WizardSession) else result
    if "consumer_review" not in selection:
        if "empty_selection" in selection:
            return _cancel(print, "No artifacts selected; no changes were made.")
        return _cancel(print)

    context.capture(selection["wizard_session"], "finalize")
    source_failure = _finalize_source_selection(
        selection["wizard_session"],
        source_finalizer,
        print,
    )
    if source_failure is not None:
        failure = _terminal_stage_failure(
            selection["wizard_session"],
            "finalize",
            source_failure,
        )
        for line in render_wizard_stage_failure(failure):
            print(line)
        return _stage_failure_exit_code(failure)
    consumer_review = selection["consumer_review"]
    active_consumer_service = selection.get("active_consumer_service", consumer_service)
    assert active_consumer_service is not None
    finalized = active_consumer_service.finalize(
        consumer_review,
        consumer_review.review_digest,
    )
    if isinstance(finalized, DomainErr):
        failure = _terminal_stage_failure(
            selection["wizard_session"],
            "finalize",
            finalized,
        )
        for line in render_wizard_stage_failure(failure):
            print(line)
        return _stage_failure_exit_code(failure)
    for line in render_consumer_outcome(finalized.value):
        print(line)
    if selection.get("reporting_warning"):
        print("warning: usage reporting is unavailable; artifact installation remains available")
    context.capture(selection["wizard_session"], "setup")
    return _complete_canonical_consumer_action(
        active_consumer_service,
        consumer_review,
        finalized.value,
        selection.get("active_reporting_service", reporting_service),
        read=input,
        write=print,
        failure_context=context,
    )


def _curses_multiselect(
    curses,
    stdscr,
    title: str,
    labels: Sequence[str],
    details: Optional[Sequence[str]] = None,
    disabled: Optional[Sequence[bool]] = None,
    *,
    wizard: bool = False,
    allow_add: bool = False,
    allow_source_maintenance: bool = False,
    initial_checked: Sequence[int] = (),
    initial_cursor: int = 0,
    initial_scroll: int = 0,
    header: Sequence[str] = (),
    cells: Optional[Sequence[Sequence[str]]] = None,
    pane_for: Optional[Callable[[int, int], Sequence[str]]] = None,
    reasons: Optional[Sequence[str]] = None,
    detail_for: Optional[Callable[[int], Sequence[str]]] = None,
    notice: str = "",
):
    """A checkbox list, optionally returning explicit wizard navigation and position.

    Enter confirms the ticked rows. With nothing ticked it confirms the row under the cursor,
    because moving the cursor onto a row and pressing Enter is the most natural gesture on a list
    and it used to end the session silently (D5). A disabled cursor row refuses and says why
    instead of leaving; only a list with no selectable row at all still returns nothing.
    """
    if not labels:
        return WizardInput("confirm") if wizard else ()
    cursor = min(max(initial_cursor, 0), len(labels) - 1)
    scroll = max(initial_scroll, 0)
    checked = [False] * len(labels)
    for index in initial_checked:
        if 0 <= index < len(checked) and (disabled is None or not disabled[index]):
            checked[index] = True
    back_keys = {getattr(curses, "KEY_BACKSPACE", -1), 127, 8, ord("b")}
    hints = _list_hints(
        toggle=True,
        back=wizard,
        details=details is not None,
        add=wizard and allow_add,
        maintain=wizard and allow_source_maintenance,
    )
    selectable = disabled is None or not all(disabled)
    while True:
        scroll = _draw_list(
            curses,
            stdscr,
            title,
            labels,
            cursor,
            checked,
            disabled=disabled,
            header=header,
            scroll=scroll,
            hints=hints,
            cells=cells,
            pane_for=pane_for,
            notice=notice,
        )
        notice = ""
        ch = stdscr.getch()
        if ch in (ord("q"), 27):  # q / ESC
            return WizardInput("quit", cursor=cursor, scroll=scroll) if wizard else None
        elif wizard and ch in back_keys:
            return WizardInput("back", cursor=cursor, scroll=scroll)
        elif wizard and allow_add and ch in (ord("a"), ord("A")):
            return WizardInput("add", cursor=cursor, scroll=scroll)
        elif wizard and allow_source_maintenance and ch in (ord("s"), ord("S")):
            # The cursor row, not the ticked rows: maintenance acts on exactly one source.
            return WizardInput("sync", (cursor,), cursor=cursor, scroll=scroll)
        elif wizard and allow_source_maintenance and ch in (ord("r"), ord("R")):
            return WizardInput("remove", (cursor,), cursor=cursor, scroll=scroll)
        elif ch in (curses.KEY_UP, ord("k")):
            cursor = (cursor - 1) % len(labels)
        elif ch in (curses.KEY_DOWN, ord("j")):
            cursor = (cursor + 1) % len(labels)
        elif ch == ord(" "):
            if disabled is None or not disabled[cursor]:
                checked[cursor] = not checked[cursor]
        elif ch == ord("?") and detail_for is not None:
            _draw_detail(curses, stdscr, labels[cursor], record=tuple(detail_for(cursor)))
        elif ch == ord("?") and details is not None and cursor < len(details):
            _draw_detail(curses, stdscr, labels[cursor], details[cursor])
        elif ch in (curses.KEY_ENTER, 10, 13):
            selected = tuple(i for i, on in enumerate(checked) if on)
            if not selected and selectable:
                if disabled is not None and disabled[cursor]:
                    notice = _refusal(reasons, cursor)
                    continue
                selected = (cursor,)
            return (
                WizardInput("confirm", selected, cursor=cursor, scroll=scroll)
                if wizard
                else selected
            )


def _curses_singleselect(
    curses,
    stdscr,
    title: str,
    labels: Sequence[str],
    *,
    wizard: bool = False,
    initial_cursor: int = 0,
    initial_scroll: int = 0,
    header: Sequence[str] = (),
):
    """A single-choice list, optionally returning explicit wizard navigation."""
    cursor = min(max(initial_cursor, 0), max(len(labels) - 1, 0))
    scroll = max(initial_scroll, 0)
    back_keys = {getattr(curses, "KEY_BACKSPACE", -1), 127, 8, ord("b")}
    hints = _list_hints(toggle=False, back=wizard, details=False, add=False)
    while True:
        scroll = _draw_list(
            curses,
            stdscr,
            title,
            labels,
            cursor,
            None,
            header=header,
            scroll=scroll,
            hints=hints,
        )
        ch = stdscr.getch()
        if ch in (ord("q"), 27):
            return WizardInput("quit", cursor=cursor, scroll=scroll) if wizard else None
        elif wizard and ch in back_keys:
            return WizardInput("back", cursor=cursor, scroll=scroll)
        elif ch in (curses.KEY_UP, ord("k")):
            cursor = (cursor - 1) % len(labels)
        elif ch in (curses.KEY_DOWN, ord("j")):
            cursor = (cursor + 1) % len(labels)
        elif ch in (curses.KEY_ENTER, 10, 13):
            return WizardInput("confirm", (cursor,), cursor, scroll) if wizard else cursor


PANE_ROWS = 8
"""Rows the artifact pane asks for: one rule, identity, a summary line, and the field block."""


def _fitting_cells(cells: Sequence[Sequence[str]], width: int) -> Tuple[Tuple[str, ...], ...]:
    """Keep the leading columns that still fit, and drop the rest whole.

    ``columns`` shrinks a column toward one character rather than dropping it, which turns
    ``registry-reviewed`` into ``regist…`` — the same width, none of the meaning. The projections
    order their cells by importance precisely so this can cut from the right instead.
    """

    if not cells:
        return ()
    count = max(len(row) for row in cells)
    widths = [
        max((len(row[index]) for row in cells if index < len(row)), default=0)
        for index in range(count)
    ]
    keep = 1
    while keep < count and sum(widths[: keep + 1]) + 2 * keep <= width:
        keep += 1
    return tuple(tuple(row[:keep]) for row in cells)


def _choice_detail(choices: Sequence[_Choice], index: int) -> Tuple[str, ...]:
    """The complete record behind ``?``, in whichever frontend asked for it (D8)."""

    choice = choices[index]
    if choice.row is not None:
        return render_artifact_detail(choice.row)
    identity = _choice_label(choice.kind, choice.name, choice.type, "")
    description = choice.description or "No catalog description is available."
    return (identity, *wrap(description, width=READABLE_MEASURE))


def _choice_pane(choices: Sequence[_Choice], index: int, width: int) -> Tuple[str, ...]:
    """The pane body for the cursor row, whatever kind of row it is.

    An artifact has a projection of its own; a collection has no security record, so it gets the
    same shape assembled from what the choice already knows. Both keep the pane the same height,
    which is what stops the list from moving under the cursor.
    """

    choice = choices[index]
    if choice.row is not None:
        return render_artifact_pane(choice.row, width=width)
    status = "available" if choice.enabled else f"unavailable: {choice.reason}"
    return (
        f"  {choice.cells[0] if choice.cells else choice.label}",
        *(f"  {line}" for line in wrap(choice.description, width=max(width - 2, 1))),
        *field_block((("status", status),), indent=4, width=width),
    )


def _refusal(reasons: Optional[Sequence[str]], cursor: int) -> str:
    """What to say when Enter lands on a row that cannot be chosen."""

    reason = reasons[cursor] if reasons is not None and cursor < len(reasons) else ""
    return f"cannot select this row: {reason}" if reason else "this row cannot be selected"


def _list_hints(
    *, toggle: bool, back: bool, details: bool, add: bool, maintain: bool = False
) -> Tuple[Tuple[str, str], ...]:
    """The canonical hint table filtered down to the keys this screen actually accepts (D2)."""

    enabled = {
        "space": toggle,
        "enter": True,
        "b": back,
        "?": details,
        "a": add,
        "s": maintain,
        "r": maintain,
        "q": True,
    }
    return tuple(hint for hint in HINT_ORDER if enabled[hint[0]])


def _draw_list(
    curses,
    stdscr,
    title: str,
    labels,
    cursor: int,
    checked,
    *,
    disabled: Optional[Sequence[bool]] = None,
    header: Sequence[str] = (),
    scroll: int = 0,
    hints: Sequence[Tuple[str, str]] = (),
    cells: Optional[Sequence[Sequence[str]]] = None,
    pane_for: Optional[Callable[[int, int], Sequence[str]]] = None,
    notice: str = "",
) -> int:
    """Render *title* + the labels, marking the cursor row and any checked rows.

    The last row belongs to the status bar and to nothing else (D2). Everything above it — header,
    title and the list viewport — is laid out inside ``height - 1``, the same reservation
    ``_curses_onboarding`` already makes for its footer.

    ``cells`` replaces the flat label with a shared column grid computed across every row at once,
    so a column starts at the same offset on all of them. ``pane_for`` supplies the detail pane for
    the cursor row; it is reserved out of the viewport at a height fixed for the whole frame, which
    is what keeps the list from reflowing under a moving cursor (D6). One item is still one row.
    """
    stdscr.clear()
    available = max(_width(stdscr) - 1, 0)
    height = _height(stdscr)
    body_height = max(height - 1, 1)
    header_budget = max(body_height - CHROME_ROWS, 1)
    if len(header) > header_budget:
        # Keep whatever says where the user is before anything else. These match the marker
        # vocabulary in tui_layout, not prose, so they survive wording changes.
        priorities = (
            lambda line: STAGE_CURRENT in line,
            lambda line: line.startswith("Basket:"),
            lambda line: line.startswith("Removed "),
        )
        picked: List[int] = []
        for predicate in priorities:
            picked.extend(
                index
                for index, line in enumerate(header)
                if predicate(line) and index not in picked
            )
        picked.extend(index for index in range(len(header)) if index not in picked)
        visible_indices = set(picked[:header_budget])
        header = tuple(line for index, line in enumerate(header) if index in visible_indices)
    row = 0
    for line in header:
        if row >= body_height:
            break
        stdscr.addstr(row, 0, _ellipsize(line, available))
        row += 1
    if row < body_height:
        stdscr.addstr(row, 0, _ellipsize(title, available))
    if notice and row + 1 < body_height:
        # The separator row is already reserved and already blank, so a notice costs no geometry.
        stdscr.addstr(row + 1, 0, _ellipsize(notice, available))
    list_start = row + 2
    pane_height = 0 if pane_for is None else pane_budget(height=height, requested=PANE_ROWS)
    visible_rows = max(body_height - list_start - pane_height, 1)
    max_scroll = max(len(labels) - visible_rows, 0)
    scroll = min(max(scroll, 0), max_scroll)
    if cursor < scroll:
        scroll = cursor
    elif cursor >= scroll + visible_rows:
        scroll = cursor - visible_rows + 1
    gutter = 2 + (4 if checked is not None else 0)
    row_width = max(min(available, CONTENT_MEASURE) - gutter, 1)
    texts = labels if cells is None else columns(_fitting_cells(cells, row_width), width=row_width)
    for display_row, i in enumerate(range(scroll, min(len(labels), scroll + visible_rows))):
        prefix = "> " if i == cursor else "  "
        box = ""
        if checked is not None:
            if disabled is not None and disabled[i]:
                box = f"{BOX_DISABLED} "
            else:
                box = f"{BOX_CHECKED} " if checked[i] else f"{BOX_EMPTY} "
        line = f"{prefix}{box}{texts[i]}"
        target_row = list_start + display_row
        if target_row < body_height:
            stdscr.addstr(target_row, 0, _ellipsize(line, available))
    if pane_height and pane_for is not None:
        # Directly under the last row when the list is short, otherwise just above the bar. Both
        # depend only on frame constants, so the pane never moves while the cursor does.
        pane_top = min(list_start + min(len(labels), visible_rows) + 1, body_height - pane_height)
        pane_lines = (
            "─" * min(available, CONTENT_MEASURE),
            *pane_for(cursor, min(available, CONTENT_MEASURE)),
        )
        for offset, line in enumerate(pane_lines[:pane_height]):
            stdscr.addstr(pane_top + offset, 0, _ellipsize(line, available))
    if height:
        stdscr.addstr(
            height - 1,
            0,
            status_bar(
                hints,
                counters=_list_counters(labels, checked, disabled, scroll, visible_rows),
                width=available,
            ),
        )
    stdscr.refresh()
    return scroll


def _list_counters(
    labels,
    checked,
    disabled: Optional[Sequence[bool]],
    scroll: int,
    visible_rows: int,
) -> Tuple[str, ...]:
    """The bar's right-hand counters, cheapest to lose last (D2)."""

    counters = []
    if checked is not None:
        selected = sum(
            1
            for index, value in enumerate(checked)
            if value and (disabled is None or not disabled[index])
        )
        counters.append(f"{selected} selected")
    if len(labels) > visible_rows:
        last = min(len(labels), scroll + visible_rows)
        counters.append(f"{scroll + 1}-{last} of {len(labels)}")
    return tuple(counters)


def _curses_onboarding(curses, stdscr) -> WizardInput:
    """Render the first-screen controls; test doubles without a screen auto-confirm."""

    if not all(hasattr(stdscr, name) for name in ("clear", "addstr", "refresh", "getch")):
        return WizardInput("confirm")
    session = initial_session()
    offset = 0
    while True:
        stdscr.clear()
        available = max(_width(stdscr) - 1, 0)
        lines = onboarding_lines("curses") + render_header(
            session, width=max(available, 1), frontend="curses"
        )
        height = _height(stdscr)
        body_height = max(height - 1, 1)
        max_offset = max(len(lines) - body_height, 0)
        offset = min(offset, max_offset)
        for row, line in enumerate(lines[offset : offset + body_height]):
            stdscr.addstr(row, 0, _ellipsize(line, available))
        if height:
            stdscr.addstr(
                height - 1,
                0,
                status_bar((("enter", "start"), ("q", "quit")), width=available),
            )
        stdscr.refresh()
        ch = stdscr.getch()
        if ch in (curses.KEY_ENTER, 10, 13):
            return WizardInput("confirm")
        if ch in (ord("q"), 27):
            return WizardInput("quit")
        if ch in (curses.KEY_DOWN, ord("j")) and offset < max_offset:
            offset += 1
        elif ch in (curses.KEY_UP, ord("k")) and offset > 0:
            offset -= 1
        elif ch == getattr(curses, "KEY_NPAGE", -1) and offset < max_offset:
            offset = min(offset + body_height, max_offset)
        elif ch == getattr(curses, "KEY_PPAGE", -1) and offset > 0:
            offset = max(offset - body_height, 0)


def _curses_install_scope(
    curses,
    stdscr,
    *,
    wizard: bool = False,
    initial_cursor: int = 0,
    initial_scroll: int = 0,
    header: Sequence[str] = (),
):
    """Scope selector with Project under the initial cursor."""

    labels = [f"{choice.label} — {choice.description}" for choice in INSTALL_SCOPE_CHOICES]
    selected = _curses_singleselect(
        curses,
        stdscr,
        "Installation scope",
        labels,
        wizard=wizard,
        initial_cursor=initial_cursor,
        initial_scroll=initial_scroll,
        header=header,
    )
    if isinstance(selected, WizardInput):
        return selected
    if selected is None:
        return None
    return INSTALL_SCOPE_CHOICES[selected].scope


def _curses_install_mode(
    curses,
    stdscr,
    *,
    wizard: bool = False,
    initial_cursor: int = 0,
    initial_scroll: int = 0,
    header: Sequence[str] = (),
):
    """Install-only mode selector with Copy under the initial cursor."""

    labels = [f"{choice.label} — {choice.description}" for choice in INSTALL_MODE_CHOICES]
    cursor = min(max(initial_cursor, 0), len(labels) - 1)
    scroll = max(initial_scroll, 0)
    back_keys = {getattr(curses, "KEY_BACKSPACE", -1), 127, 8, ord("b")}
    hints = _list_hints(toggle=False, back=True, details=False, add=False)
    while True:
        scroll = _draw_list(
            curses,
            stdscr,
            "Installation mode",
            labels,
            cursor,
            None,
            header=header,
            scroll=scroll,
            hints=hints,
        )
        ch = stdscr.getch()
        if ch in (ord("q"), 27):
            return WizardInput("quit", cursor=cursor, scroll=scroll) if wizard else None
        if ch in back_keys:
            return WizardInput("back", cursor=cursor, scroll=scroll) if wizard else "back"
        if ch in (curses.KEY_UP, ord("k")):
            cursor = (cursor - 1) % len(labels)
        elif ch in (curses.KEY_DOWN, ord("j")):
            cursor = (cursor + 1) % len(labels)
        elif ch in (curses.KEY_ENTER, 10, 13):
            return (
                WizardInput("confirm", (cursor,), cursor, scroll)
                if wizard
                else INSTALL_MODE_CHOICES[cursor].mode
            )


def _ellipsize(text: str, width: int) -> str:
    """Return one visual line no wider than ``width``, marking truncation with ``…``."""
    one_line = text.replace("\r", " ").replace("\n", " ")
    if width <= 0:
        return ""
    if len(one_line) <= width:
        return one_line
    if width == 1:
        return "…"
    return one_line[: width - 1] + "…"


def _draw_detail(
    curses,
    stdscr,
    label: str,
    description: str = "",
    *,
    record: Sequence[str] = (),
) -> None:
    """Show the complete evidence in a scrollable curses detail view.

    A record is rendered as it comes: it is already bounded and its digest lines are deliberately
    exempt from the measure, because a wrapped hash can be neither read nor copied (D8). Plain
    prose is wrapped at the readable measure rather than at the terminal width (D7).
    """
    available = max(_width(stdscr) - 1, 1)
    height = _height(stdscr)
    # A record leads with its own identity line, so repeating the label above it would state the
    # same fact twice on adjacent rows.
    titles = ("Artifact details",) if record else ("Artifact details", label)
    content_top = len(titles) + 1
    content_height = max(height - content_top - 1, 1)
    wrapped = list(record) or list(
        wrap(description or "No catalog description is available.", width=available)
    )
    max_offset = max(len(wrapped) - content_height, 0)
    offset = 0

    while True:
        stdscr.clear()
        for index, title in enumerate(titles):
            if index < height:
                stdscr.addstr(index, 0, _ellipsize(title, available))
        for relative_row, line in enumerate(wrapped[offset : offset + content_height]):
            row = content_top + relative_row
            if row >= max(height - 1, 0):
                break
            stdscr.addstr(row, 0, _ellipsize(line, available))
        if height > 0:
            hints = (("↑/↓", "scroll"), ("q", "return")) if max_offset else (("q", "return"),)
            stdscr.addstr(height - 1, 0, status_bar(hints, width=available))
        stdscr.refresh()

        ch = stdscr.getch()
        if ch in (curses.KEY_DOWN, ord("j")) and offset < max_offset:
            offset += 1
        elif ch in (curses.KEY_UP, ord("k")) and offset > 0:
            offset -= 1
        elif ch == curses.KEY_NPAGE and offset < max_offset:
            offset = min(offset + content_height, max_offset)
        elif ch == curses.KEY_PPAGE and offset > 0:
            offset = max(offset - content_height, 0)
        else:
            return


def _curses_stage_failure_recovery(
    curses,
    stdscr,
    failure: WizardStageFailure,
) -> WizardInput:
    """Show a blocking stage record and accept only its declared recovery events."""

    required = ("clear", "addstr", "refresh", "getch", "getmaxyx")
    if not all(hasattr(stdscr, name) for name in required):
        return WizardInput("quit")
    shortcuts = {"retry": "r", "back": "b", "quit": "q"}
    available = max(_width(stdscr) - 1, 1)
    height = _height(stdscr)
    body_height = max(height - 1, 1)
    record = render_wizard_stage_failure(failure, width=available)
    max_offset = max(len(record) - body_height, 0)
    offset = 0
    hints = tuple((shortcuts[choice], choice) for choice in failure.choices)
    while True:
        stdscr.clear()
        for row, line in enumerate(record[offset : offset + body_height]):
            stdscr.addstr(row, 0, _ellipsize(line, available))
        if height > 0:
            stdscr.addstr(height - 1, 0, status_bar(hints, width=available))
        stdscr.refresh()
        key = stdscr.getch()
        for choice, shortcut in shortcuts.items():
            if choice in failure.choices and key in (ord(shortcut), ord(shortcut.upper())):
                return WizardInput(choice)
        if key in (getattr(curses, "KEY_DOWN", -1), ord("j")) and offset < max_offset:
            offset += 1
        elif key in (getattr(curses, "KEY_UP", -1), ord("k")) and offset > 0:
            offset -= 1
        elif key == getattr(curses, "KEY_NPAGE", -1) and offset < max_offset:
            offset = min(offset + body_height, max_offset)
        elif key == getattr(curses, "KEY_PPAGE", -1) and offset > 0:
            offset = max(offset - body_height, 0)


def _height(stdscr) -> int:
    return stdscr.getmaxyx()[0]


def _width(stdscr) -> int:
    return stdscr.getmaxyx()[1]


def _curses_supported() -> bool:
    """Return false only for expected pre-interaction terminal capability failures."""

    try:
        import curses  # noqa: F401  (presence check only)
    except ImportError:
        return False
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except OSError:
        return False


# --------------------------------------------------------------------------- #
# Entry point — chooses curses vs text and delegates.                           #
# --------------------------------------------------------------------------- #
def run(
    *,
    source_dir: Optional[str] = None,
    repo: Optional[str] = None,
    project: Optional[str] = None,
    user_home: Optional[str] = None,
) -> int:
    """Launch the interactive selector; return a process exit code.

    Called by ``cli._run_bare`` on a bare TTY invocation. Tries the ``curses`` selector and
    **degrades to the ``input()`` flow** if curses cannot be imported or initialised. A clean
    quit (no selection) returns 0. Sources are loaded only from canonical user configuration.
    """
    if source_dir is not None or repo is not None:
        print(
            "error: direct catalog directories and repository aliases are no longer supported; "
            "add a canonical registry in Sources instead."
        )
        return 2
    source_context = _runtime_source_stage_context(
        source_dir=source_dir,
        repo=repo,
        user_home=user_home,
    )
    if isinstance(source_context, DomainErr):
        failure = _terminal_stage_failure(
            WizardSession(current="source"),
            "load",
            source_context,
        )
        for line in render_wizard_stage_failure(failure):
            print(line)
        return _stage_failure_exit_code(failure)
    source_runtime = source_context.value
    source_stage_view = source_runtime.view
    source_finalizer = source_runtime.source_finalizer
    source_addition_finalizer = source_runtime.source_addition_finalizer
    source_removal_finalizer = source_runtime.source_removal_finalizer
    source_sync_runner = source_runtime.source_sync_runner

    def reload_source_stage() -> DomainResult[_RuntimeSourceStage]:
        return _runtime_source_stage_context(
            source_dir=source_dir,
            repo=repo,
            user_home=user_home,
        )

    consumer_service: Optional[ConsumerApplicationService] = None
    consumer_service_factory: Optional[ConsumerServiceFactory] = None
    reporting_service: Optional[ReportingApplicationService] = None
    reporting_service_factory: Optional[ReportingServiceFactory] = None
    if source_dir is None and repo is None:
        from .consumer.runtime import load_local_consumer_service
        from .reporting.runtime import load_local_reporting_service

        def runtime_consumer_service(
            configuration: UserConfiguration,
        ) -> DomainResult[ConsumerApplicationService]:
            return load_local_consumer_service(
                project=project,
                user_home=user_home,
                configuration=configuration,
            )

        consumer_service_factory = runtime_consumer_service

        def runtime_reporting_service(
            configuration: UserConfiguration,
        ) -> DomainResult[ReportingApplicationService]:
            return load_local_reporting_service(
                user_home=user_home,
                configuration=configuration,
            )

        reporting_service_factory = runtime_reporting_service
    failure_context = InternalFailureContext()
    try:
        curses_supported = _curses_supported()
    except Exception as error:
        return _render_internal_failure(error, failure_context)
    if not curses_supported:
        return _run_text(
            source_dir=source_dir,
            repo=repo,
            project=project,
            user_home=user_home,
            source_stage_view=source_stage_view,
            source_finalizer=source_finalizer,
            source_addition_finalizer=source_addition_finalizer,
            source_removal_finalizer=source_removal_finalizer,
            source_sync_runner=source_sync_runner,
            source_stage_loader=reload_source_stage,
            consumer_service=consumer_service,
            consumer_service_factory=consumer_service_factory,
            reporting_service=reporting_service,
            reporting_service_factory=reporting_service_factory,
        )

    try:
        return _run_curses(
            source_dir=source_dir,
            repo=repo,
            project=project,
            user_home=user_home,
            source_stage_view=source_stage_view,
            source_finalizer=source_finalizer,
            source_addition_finalizer=source_addition_finalizer,
            source_removal_finalizer=source_removal_finalizer,
            source_sync_runner=source_sync_runner,
            source_stage_loader=reload_source_stage,
            consumer_service=consumer_service,
            consumer_service_factory=consumer_service_factory,
            reporting_service=reporting_service,
            reporting_service_factory=reporting_service_factory,
            failure_context=failure_context,
        )
    except CursesUnavailable:
        return _run_text(
            source_dir=source_dir,
            repo=repo,
            project=project,
            user_home=user_home,
            source_stage_view=source_stage_view,
            source_finalizer=source_finalizer,
            source_addition_finalizer=source_addition_finalizer,
            source_removal_finalizer=source_removal_finalizer,
            source_sync_runner=source_sync_runner,
            source_stage_loader=reload_source_stage,
            consumer_service=consumer_service,
            consumer_service_factory=consumer_service_factory,
            reporting_service=reporting_service,
            reporting_service_factory=reporting_service_factory,
        )
    except Exception as error:
        # The outermost crash boundary. ``curses.wrapper`` has already restored the terminal.
        # Broad catching is permitted here for rendering only, never to start a second wizard.
        return _render_internal_failure(error, failure_context)
