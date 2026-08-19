"""Agent CLI surface for the configured canonical marketplace.

This module exposes the configured-source marketplace and its canonical lifecycle.

Two properties are load-bearing for automation safety and are asserted by the tests:

* **Review before Finalize.**  The TUI asks a human to confirm an exact reviewed plan.  The
  non-interactive equivalent is ``--yes``: without it every action stops after Review and reports
  the plan it *would* apply.  Finalize always passes the digest of the review computed in this same
  process, so a plan can never drift between Review and Finalize.  ``--expect DIGEST`` extends that
  guarantee across two commands: it binds the decision a human actually read to the plan being
  applied, and refuses — showing the new review — when they have stopped being the same plan.
* **Authorizations are never implied.**  Untrusted-source setup, custom entrypoints, and setup
  effect consent each need their own flag.  Omitting a flag denies; it never asks and never
  assumes.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from agent_artifacts import command_outcome as _common
from agent_artifacts.consumer.application import (
    CONSUMER_REVIEW_MISMATCH,
    ConsumerApplicationService,
)
from agent_artifacts.consumer.coordinates import CONSUMER_INVALID, parse_artifact_selectors
from agent_artifacts.consumer.model import (
    ConsumerAction,
    ConsumerActionRequest,
    ConsumerOutcome,
    ConsumerReview,
    ConsumerSetupQueue,
    ConsumerTerminalItem,
    consumer_review_value,
    render_consumer_outcome,
    render_consumer_review,
    review_source_freshness,
)
from agent_artifacts.consumer.resolution import resolve_selectors
from agent_artifacts.consumer.runtime import load_local_consumer_service, load_read_only_marketplace
from agent_artifacts.consumer.runtime_requirements import (
    RUNTIME_ENVIRONMENT_INVALID,
    RuntimeEnvironment,
    RuntimeRequirementStatus,
    evaluate_runtime_requirements,
    parse_runtime_environment,
    parse_runtime_requirements,
    runtime_capability_to_data,
    runtime_check_to_data,
)
from agent_artifacts.domain.diagnostics import Diagnostic, Severity, diagnostic_to_data
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.marketplace.catalog import marketplace_catalog_bytes, render_marketplace
from agent_artifacts.model import Request, SetupManualReference
from agent_artifacts.protocol.json import canonical_json_bytes
from agent_artifacts.protocol.native_schema import parse_artifact_manifest
from agent_artifacts.protocol.native_tree import SnapshotEntryKind
from agent_artifacts.receipt_service import (
    RECEIPT_ACTIONS,
    apply_undo,
    load_receipt,
    resolved_paths,
    show_view,
    undo_view,
    unsupported_action,
    verify_view,
)
from agent_artifacts.reporting.application import ReportingApplicationService
from agent_artifacts.reporting.model import ReportingPlan
from agent_artifacts.reporting.projection import (
    SetupReportState,
    usage_report_from_consumer,
    usage_reports_by_registry_from_consumer,
)
from agent_artifacts.reporting.runtime import load_local_reporting_service
from agent_artifacts.runtime_contract import EXECUTABLE_VERSION
from agent_artifacts.setup import (
    _command_strings,
    advisory_messages,
    project_setup_review,
    render_setup_review,
)
from agent_artifacts.setup_render import (
    render_receipt_payload,
    render_setup_payload,
    render_undo_payload,
    render_verification_payload,
)
from agent_artifacts.store.model import ObjectReadRequest

from ._configured_runtime import load_runtime_configuration

_LIST_OPERATION = "marketplace.list"
_HEALTH_OPERATION = "marketplace.health"
_MAX_ENVIRONMENT_BYTES = 1024 * 1024

# ``setup`` is not a domain action: it reaches a terminal payload state through ``install`` and then
# runs only the setup work that state left pending.
_LIFECYCLE_ACTIONS: dict[str, ConsumerAction] = {
    "install": "install",
    "update": "update",
    "uninstall": "uninstall",
    "status": "status",
    "setup": "install",
}
_REQUIRES_COORDINATES = frozenset({"install", "uninstall", "setup"})
_MUTATING = frozenset({"install", "update", "uninstall", "setup"})
# `RS-07`: the actions that read what the project already has. Neither fetches anything, so neither
# needs an enabled source to be answerable — an installed artifact is on disk whether or not the
# subscription that delivered it is still configured. `uninstall` was exempted in `2.2.0` because
# design §3 names it; `status` is the same kind of question and was left refusing, which meant the
# operator who followed `source remove` could no longer read their own project.
_PROJECT_LOCAL = frozenset({"uninstall", "status"})


@dataclass(frozen=True, slots=True)
class _CliReporting:
    service: ReportingApplicationService | None
    plans: tuple[ReportingPlan, ...] = ()
    notices: tuple[str, ...] = ()
    warning: str | None = None


def _setup_report_states(payload: dict | None) -> tuple[SetupReportState, ...]:
    """Recover the typed, privacy-bounded setup statuses from this command's own projection."""

    if payload is None:
        return ()
    states = []
    for item in payload.get("items", ()):  # populated only after a setup queue was attempted
        states.append(SetupReportState(item["key"], item["status"]))
    for failure in payload.get("planning_failures", ()):
        states.append(
            SetupReportState(
                failure["key"],
                "planning-failed",
                failure_phase="queue",
                failure_code="setup-planning-failed",
            )
        )
    return tuple(states)


def _prepare_cli_reporting(
    request: Request,
    service: ConsumerApplicationService,
    review: ConsumerReview,
    outcome: ConsumerOutcome,
    setup_payload: dict | None,
) -> _CliReporting | None:
    """Prepare optional reporting after the artifact outcome; every failure remains advisory."""

    effective = getattr(service.context, "effective", None)
    if effective is None:  # narrow test adapters need not implement the production runtime context
        return None
    loaded = load_local_reporting_service(
        user_home=request.user_home,
        configuration=effective.configuration,
    )
    if isinstance(loaded, Err):
        return _CliReporting(
            None,
            warning="usage reporting is unavailable; the marketplace outcome is unchanged",
        )
    try:
        states = _setup_report_states(setup_payload)
        event = usage_report_from_consumer(
            review,
            outcome,
            states,
            aart_version=str(EXECUTABLE_VERSION),
            interface="cli",
        )
        routed = usage_reports_by_registry_from_consumer(
            review,
            outcome,
            states,
            aart_version=str(EXECUTABLE_VERSION),
            interface="cli",
        )
    except (KeyError, TypeError, ValueError):
        return _CliReporting(
            loaded.value,
            warning="usage report projection failed; the marketplace outcome is unchanged",
        )
    aliases = {item.source_alias for item in routed}
    notices = tuple(
        f"Usage report not offered for registry {notice.source_alias}: {notice.reason}."
        for notice in loaded.value.notices
        if notice.source_alias in aliases
    )
    prepared = loaded.value.prepare_routed(event, routed)
    if isinstance(prepared, Err):
        return _CliReporting(
            loaded.value,
            notices=notices,
            warning="usage reports could not be prepared; the marketplace outcome is unchanged",
        )
    return _CliReporting(loaded.value, prepared.value, notices)


def _reporting_plan_data(plan: ReportingPlan) -> dict[str, object]:
    return {
        "destination": f"{plan.destination.host}/{plan.destination.repository}",
        "mode": plan.destination.mode.value,
        "payload": json.loads(plan.payload.decode("utf-8")),
        "browser_url": plan.browser_url,
    }


def _json_reporting_data(reporting: _CliReporting | None) -> dict[str, object] | None:
    if reporting is None:
        return None
    if reporting.warning is not None:
        return {
            "status": "unavailable",
            "warning": reporting.warning,
            "notices": reporting.notices,
        }
    if not reporting.plans and not reporting.notices:
        return None
    submissions = []
    for plan in reporting.plans:
        status = "offered"
        if plan.destination.mode.value == "automatic" and reporting.service is not None:
            submitted = reporting.service.submit(plan)
            status = "failed" if isinstance(submitted, Err) else submitted.value.status
        submissions.append({**_reporting_plan_data(plan), "status": status})
    return {
        "status": "offered" if submissions else "unavailable",
        "notices": reporting.notices,
        "plans": submissions,
    }


def _read_reporting_consent(prompt: str) -> bool:
    try:
        return input(prompt).strip().lower() in {"y", "yes"}
    except EOFError:
        return False


def _render_cli_reporting(reporting: _CliReporting | None) -> None:
    if reporting is None:
        return
    for notice in reporting.notices:
        print(notice)
    if reporting.warning is not None:
        print(f"warning: {reporting.warning}", file=sys.stderr)
        return
    if not reporting.plans:
        return
    print("Optional redacted usage reports are available for these artifact registries:")
    for plan in reporting.plans:
        print(f"  - {plan.destination.host}/{plan.destination.repository}")
    for plan in reporting.plans:
        target = f"{plan.destination.host}/{plan.destination.repository}"
        if plan.destination.mode.value == "prompt":
            if not sys.stdin.isatty():
                print(
                    f"Usage report for {target} was not submitted because stdin is not interactive."
                )
                continue
            if not _read_reporting_consent(
                f"Share this redacted usage report with {target}? [y/N]: "
            ):
                print("Usage report was not submitted.")
                continue
        print("Exact redacted usage report payload:")
        print(plan.payload.decode("utf-8").strip())
        if plan.destination.mode.value == "prompt" and not _read_reporting_consent(
            "Open the prefilled GitHub issue? [y/N]: "
        ):
            print("Usage report was not submitted.")
            continue
        if reporting.service is None:
            print("warning: usage reporting is unavailable; the marketplace outcome is unchanged")
            continue
        submitted = reporting.service.submit(plan)
        if isinstance(submitted, Err):
            print("warning: usage report submission failed; the marketplace outcome is unchanged")
        else:
            print(
                "Usage report opened in the browser."
                if submitted.value.status == "browser-opened"
                else "Usage report submitted."
            )


def _emit_error(request: Request, result: Err, operation: str = _LIST_OPERATION) -> int:
    if request.json:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "ok": False,
                    "operation": operation,
                    "diagnostics": [diagnostic_to_data(item) for item in result.diagnostics],
                },
                indent=2,
            )
        )
    else:
        for diagnostic in result.diagnostics:
            print(f"{diagnostic.severity.value}: {diagnostic.message}")
            for remediation in diagnostic.remediation:
                print(f"  remediation: {remediation}")
    return _common.ERROR


def _list(request: Request) -> int:
    # Enforce the canonical content-operation no-source contract before building a marketplace.
    runtime = load_runtime_configuration(request, content_required=True)
    if isinstance(runtime, Err):
        return _emit_error(request, runtime)
    catalog = load_read_only_marketplace(
        runtime.value.loaded.effective,
        data_root=runtime.value.paths.data_root,
        observe_freshness=not request.offline,
    )
    if isinstance(catalog, Err):
        return _emit_error(request, catalog)
    if request.json:
        payload = json.loads(
            marketplace_catalog_bytes(
                catalog.value,
                executable_version=EXECUTABLE_VERSION,
            ).decode("utf-8")
        )
        payload["aart_version"] = str(EXECUTABLE_VERSION)
        payload["ok"] = True
        payload["operation"] = _LIST_OPERATION
        print(json.dumps(payload, indent=2))
    else:
        rendered = render_marketplace(catalog.value, executable_version=EXECUTABLE_VERSION)
        print(rendered, end="") if rendered else print("No marketplace artifacts are available.")
    return _common.OK


def _invalid(message: str, *remediation: str) -> Err:
    return Err((Diagnostic(CONSUMER_INVALID, Severity.ERROR, message, remediation=remediation),))


def _runtime_environment_error(message: str) -> Err:
    return Err((Diagnostic(RUNTIME_ENVIRONMENT_INVALID, Severity.ERROR, message),))


def _load_runtime_environment(request: Request) -> Result[RuntimeEnvironment]:
    raw_path = request.runtime_environment
    if raw_path is None:
        return _runtime_environment_error(
            "marketplace health requires a repository runtime environment description"
        )
    path = os.path.abspath(raw_path)
    try:
        if os.path.getsize(path) > _MAX_ENVIRONMENT_BYTES:
            return _runtime_environment_error(
                f"runtime environment description exceeds {_MAX_ENVIRONMENT_BYTES} bytes"
            )
        data = Path(path).read_bytes()
    except (OSError, ValueError) as error:
        return _runtime_environment_error(
            f"cannot read runtime environment description {path}: {error}"
        )
    if len(data) > _MAX_ENVIRONMENT_BYTES:
        return _runtime_environment_error(
            f"runtime environment description exceeds {_MAX_ENVIRONMENT_BYTES} bytes"
        )
    return parse_runtime_environment(data, path=path)


def _health_coordinates(request: Request, service: ConsumerApplicationService) -> Result[tuple]:
    if not request.names:
        return Ok(tuple(item.coordinate for item in service.context.catalog.items))
    parsed = parse_artifact_selectors(tuple(request.names))
    if isinstance(parsed, Err):
        return parsed
    return resolve_selectors(service.context.catalog, parsed.value)


def _health_item(service: ConsumerApplicationService, coordinate, environment) -> dict:
    item = next(
        candidate
        for candidate in service.context.catalog.items
        if candidate.coordinate == coordinate
    )
    loaded = service.ports.read_object(
        ObjectReadRequest(service.context.store_paths, item.artifact.artifact.object_digest)
    )
    if isinstance(loaded, Err):
        return {
            "coordinate": str(coordinate),
            "status": "unavailable",
            "requirements": [],
            "diagnostics": [diagnostic_to_data(value) for value in loaded.diagnostics],
        }
    if loaded.value is None:
        return {
            "coordinate": str(coordinate),
            "status": "unavailable",
            "requirements": [],
            "detail": (
                "verified artifact content is not available locally; synchronize or install it "
                "before inspecting advisory requirements"
            ),
        }
    manifest_entry = next(
        (
            entry
            for entry in loaded.value.candidate.entries
            if str(entry.path) == "artifact.json" and entry.kind is SnapshotEntryKind.FILE
        ),
        None,
    )
    if manifest_entry is None:
        return {
            "coordinate": str(coordinate),
            "status": "invalid",
            "requirements": [],
            "detail": "verified artifact content has no artifact.json file",
        }
    parsed_manifest = parse_artifact_manifest(manifest_entry.content, path="artifact.json")
    if isinstance(parsed_manifest, Err):
        return {
            "coordinate": str(coordinate),
            "status": "invalid",
            "requirements": [],
            "diagnostics": [diagnostic_to_data(value) for value in parsed_manifest.diagnostics],
        }
    parsed_requirements = parse_runtime_requirements(parsed_manifest.value)
    if isinstance(parsed_requirements, Err):
        return {
            "coordinate": str(coordinate),
            "status": "invalid",
            "requirements": [],
            "diagnostics": [diagnostic_to_data(value) for value in parsed_requirements.diagnostics],
        }
    if not parsed_requirements.value:
        return {
            "coordinate": str(coordinate),
            "status": "not-declared",
            "requirements": [],
        }
    checks = evaluate_runtime_requirements(parsed_requirements.value, environment)
    statuses = {check.status for check in checks}
    status = (
        RuntimeRequirementStatus.UNSATISFIED.value
        if RuntimeRequirementStatus.UNSATISFIED in statuses
        else (
            RuntimeRequirementStatus.UNKNOWN.value
            if RuntimeRequirementStatus.UNKNOWN in statuses
            else RuntimeRequirementStatus.SATISFIED.value
        )
    )
    return {
        "coordinate": str(coordinate),
        "status": status,
        "requirements": [runtime_check_to_data(check) for check in checks],
    }


def _health(request: Request) -> int:
    environment = _load_runtime_environment(request)
    if isinstance(environment, Err):
        return _emit_error(request, environment, _HEALTH_OPERATION)
    service = load_local_consumer_service(
        project=request.project,
        user_home=request.user_home,
        observe_freshness=True,
        refresh_sources=True,
        offline=request.offline,
    )
    if isinstance(service, Err):
        return _emit_error(request, service, _HEALTH_OPERATION)
    coordinates = _health_coordinates(request, service.value)
    if isinstance(coordinates, Err):
        return _emit_error(request, coordinates, _HEALTH_OPERATION)
    items = [
        _health_item(service.value, coordinate, environment.value)
        for coordinate in coordinates.value
    ]
    statuses = (
        "satisfied",
        "unsatisfied",
        "unknown",
        "not-declared",
        "unavailable",
        "invalid",
    )
    summary = {status: sum(item["status"] == status for item in items) for status in statuses}
    payload = {
        "schema_version": 1,
        "ok": True,
        "operation": _HEALTH_OPERATION,
        "advisory": True,
        "installation_blocking": False,
        "environment": {
            "path": os.path.abspath(request.runtime_environment or ""),
            "name": environment.value.name,
            "capabilities": [
                runtime_capability_to_data(item) for item in environment.value.capabilities
            ],
        },
        "summary": summary,
        "items": items,
    }
    lines = (
        f"Runtime requirement health: {len(items)} artifact(s)",
        *tuple(f"{item['coordinate']}: {item['status']}" for item in items),
        "Advisory only: these results never block artifact installation.",
    )
    _emit(request, _HEALTH_OPERATION, payload, lines)
    return _common.OK


def _selection(request: Request, action: str) -> Result[tuple]:
    """Parse and validate the requested selection without touching any source."""

    if not request.profiles:
        return _invalid(
            f"marketplace {action} requires at least one harness profile",
            "pass --profile <name> (repeatable, or comma-separated)",
        )
    if action in _REQUIRES_COORDINATES and not request.names:
        return _invalid(
            f"marketplace {action} requires at least one artifact or collection coordinate",
            "pass <source>/<kind>/<name>[@<version>] or <source>/collection/<name>",
            "run `aart marketplace list --json` to see available coordinates",
        )
    return parse_artifact_selectors(tuple(request.names))


def _action_request(
    request: Request,
    action: str,
    coordinates: tuple,
) -> ConsumerActionRequest:
    return ConsumerActionRequest(
        _LIFECYCLE_ACTIONS[action],
        coordinates,
        tuple(request.profiles),
        scope=request.scope,
        mode=request.install_mode,
        force=request.force,
        offline=request.offline,
        prune=request.prune,
        memory_mode=request.memory_mode or "prepend",
    )


def _manual_payload(reference: SetupManualReference | None) -> dict | None:
    if reference is None:
        return None
    return {
        "relative_path": reference.relative_path,
        "source": reference.source,
    }


def _setup_plan_payload(plan) -> dict:
    projected = project_setup_review(plan.legacy_plan)
    return {
        "key": f"{plan.request.coordinate}#{plan.request.profile}/{plan.request.scope}",
        "trust": plan.trust,
        "recipe": str(plan.recipe_path),
        "review_digest": str(plan.review_digest),
        "manual": _manual_payload(projected.manual),
        "effects": [
            {
                "index": effect.index,
                "identity": effect.identity,
                "target": effect.target,
                "capability": effect.capability,
                "recovery": effect.recovery,
                "details": effect.details,
            }
            for effect in projected.effects
        ],
    }


def _setup_warnings(outcome) -> list[dict]:
    """Advisory findings a completed run recorded, carried to the surface the operator reads.

    A secret that is wrong — truncated at the prompt, or simply the one stored months ago and
    rotated since — configures cleanly and fails much later, at the server, as one word in a
    harness UI (`AD-34`, `AD-35`). The receipt knows; nothing read it until here.

    The reading itself is `advisory_messages`, shared with the wizard, because this command was
    the only surface that did it and the wizard is the one people use (`AD-36`).
    """

    warnings: list[dict] = []
    for item in outcome.items:
        record = item.record
        if record is None:
            continue
        for advisory in advisory_messages(record):
            warnings.append(
                {
                    "key": f"{item.coordinate}#{item.profile}/{item.scope}",
                    "detail": str(advisory.get("detail", "")),
                    "commands": list(_command_strings(advisory.get("commands"))),
                }
            )
    return warnings


def _setup_payload(queue: ConsumerSetupQueue, outcome=None) -> dict:
    payload: dict = {
        "planned": [_setup_plan_payload(plan) for plan in queue.plans],
        "planning_failures": [
            {
                "key": failure.key,
                "detail": failure.detail,
                "manual": _manual_payload(failure.manual),
            }
            for failure in queue.failures
        ],
    }
    if outcome is not None:
        payload["configured"] = outcome.configured
        payload["incomplete"] = outcome.incomplete
        payload["items"] = [
            {
                "key": f"{item.coordinate}#{item.profile}/{item.scope}",
                "status": item.setup_status.value,
                "detail": item.detail,
            }
            for item in outcome.items
        ]
        warnings = _setup_warnings(outcome)
        if warnings:
            payload["warnings"] = warnings
    return payload


def _run_setup_queue(
    request: Request,
    service: ConsumerApplicationService,
    review: ConsumerReview,
    outcome: ConsumerOutcome,
) -> tuple[dict, bool]:
    """Prepare and, only when explicitly authorized, execute the declared setup queue."""

    queue = service.setup_queue(
        review,
        outcome,
        authorize_untrusted_source=request.authorize_untrusted_source,
        authorize_custom_entrypoint=request.authorize_custom_entrypoint,
    )
    if not request.yes or not queue.plans:
        return _setup_payload(queue), not queue.failures
    # Consent is a decision, not a prompt: each reviewed effect is approved only when the caller
    # passed --approve-setup-effects.  A declined effect leaves installed payloads untouched.
    approved = request.approve_setup_effects
    setup_outcome = service.finalize_setup_queue(queue, consent=lambda _effect: approved)
    return (
        _setup_payload(queue, setup_outcome),
        not queue.failures and setup_outcome.incomplete == 0,
    )


def _setup_review_outcome(review: ConsumerReview) -> ConsumerOutcome:
    """Project setup-eligible Review items without finalizing their payload plans.

    ``prepare_consumer_setup_queue`` intentionally accepts only terminal payload outcomes.  The
    setup command's read-only branch has no real outcome because Review must not mutate, but an
    already-installed artifact still needs its canonical setup plan rendered.  This projection
    supplies only the bounded identity and pending/not-required status needed for that second
    Review; ``prepare_setup`` remains responsible for proving the installed record exists and
    matches the immutable marketplace object.
    """

    return ConsumerOutcome(
        _LIFECYCLE_ACTIONS["setup"],
        tuple(
            ConsumerTerminalItem(
                item.key,
                "current",
                setup_status="pending" if item.setup is not None else "not-required",
            )
            for item in review.items
        ),
    )


def _emit(
    request: Request,
    operation: str,
    payload: dict,
    lines: tuple[str, ...],
) -> None:
    if request.json:
        print(json.dumps(payload, indent=2))
        return
    for line in lines:
        print(line)


def _lifecycle(request: Request, action: str) -> int:
    operation = f"marketplace.{action}"
    selection = _selection(request, action)
    if isinstance(selection, Err):
        return _emit_error(request, selection, operation)
    service = load_local_consumer_service(
        project=request.project,
        user_home=request.user_home,
        observe_freshness=True,
        offline=request.offline,
        # Neither of these is a content operation: one removes what the manifest records, the other
        # reports it.  Requiring an enabled source here would refuse the exact exit `source remove`
        # tells operators to take.
        content_required=action not in _PROJECT_LOCAL,
    )
    if isinstance(service, Err):
        return _emit_error(request, service, operation)
    if action == "uninstall":
        # Uninstall resolves against the manifest, never through the source: the project has a
        # complete record of what it installed, and removing a subscription must not strand it.
        coordinates = service.value.resolve_uninstall(
            selection.value,
            scope=request.scope,
            profiles=tuple(request.profiles),
        )
    else:
        coordinates = resolve_selectors(
            service.value.context.catalog, selection.value, offline=request.offline
        )
    if isinstance(coordinates, Err):
        return _emit_error(request, coordinates, operation)
    prepared = service.value.prepare(_action_request(request, action, coordinates.value))
    if isinstance(prepared, Err):
        return _emit_error(request, prepared, operation)
    review = prepared.value
    review_data = json.loads(canonical_json_bytes(consumer_review_value(review)).decode("utf-8"))

    if not request.yes and action in _MUTATING:
        payload = {
            "schema_version": 1,
            "ok": True,
            "operation": operation,
            "finalized": False,
            "review_digest": str(review.review_digest),
            "review": review_data,
            # A sibling of ``review``, never a member of it: ``review`` is the exact value the
            # digest is computed over, and freshness is a clock reading.
            "source_freshness": [
                {"alias": alias, "health": health, "age_seconds": age}
                for alias, health, age in review_source_freshness(review)
            ],
        }
        setup_lines: tuple[str, ...] = ()
        if action == "setup":
            setup_queue = service.value.setup_queue(
                review,
                _setup_review_outcome(review),
                authorize_untrusted_source=request.authorize_untrusted_source,
                authorize_custom_entrypoint=request.authorize_custom_entrypoint,
            )
            setup_data = _setup_payload(setup_queue)
            payload["setup"] = setup_data
            # `LAF-54`: the plan renderer alone emits nothing when planning failed, so the
            # operator approving effects was shown a setup queue and never told it will not run.
            setup_lines = tuple(
                line for plan in setup_queue.plans for line in render_setup_review(plan.legacy_plan)
            ) + render_setup_payload(setup_data, planned_effects=False)
        _emit(
            request,
            operation,
            payload,
            render_consumer_review(review)
            + setup_lines
            + ("Reviewed only; re-run with --yes to apply this exact plan.",),
        )
        return _common.OK

    if request.expect is not None and request.expect != str(review.review_digest):
        # The reviewed decision did not survive to this command.  Refuse, and render the plan that
        # would actually run — an operator who cannot see the new plan cannot re-authorize it.
        refusal = Diagnostic(
            CONSUMER_REVIEW_MISMATCH,
            Severity.ERROR,
            (
                f"the plan changed since it was reviewed: expected {request.expect}, "
                f"recomputed {review.review_digest}"
            ),
            remediation=("re-read the review below, then re-run --expect with its review_digest",),
        )
        _emit(
            request,
            operation,
            {
                "schema_version": 1,
                "ok": False,
                "operation": operation,
                "finalized": False,
                "diagnostics": [diagnostic_to_data(refusal)],
                "expected_review_digest": request.expect,
                "review_digest": str(review.review_digest),
                "review": review_data,
            },
            (
                f"{refusal.severity.value}: {refusal.message}",
                *(f"  remediation: {item}" for item in refusal.remediation),
                *render_consumer_review(review),
            ),
        )
        return _common.ERROR

    finalized = service.value.finalize(review, review.review_digest)
    if isinstance(finalized, Err):
        return _emit_error(request, finalized, operation)
    outcome = finalized.value
    payload = {
        "schema_version": 1,
        "ok": True,
        "operation": operation,
        "finalized": True,
        "review_digest": str(review.review_digest),
        "session_status": outcome.session_status,
        "offline_last_known_good": outcome.offline_last_known_good,
        "items": [
            {
                "key": item.key,
                "status": item.status,
                "detail": item.detail,
                "setup_status": item.setup_status,
            }
            for item in outcome.items
        ],
    }
    lines = render_consumer_outcome(outcome)
    setup_ok = True
    setup_payload: dict | None = None
    if action == "setup" or any(item.setup_status == "pending" for item in outcome.items):
        setup_payload, setup_ok = _run_setup_queue(request, service.value, review, outcome)
        payload["setup"] = setup_payload
        # `LAF-52`: the counts stay, at the end, after the content they used to replace.
        lines += render_setup_payload(setup_payload)
    # Install and update report the payload transaction they were asked to perform. Their
    # parsers intentionally carry none of the flags that can authorize a setup queue, so a
    # planning refusal here is pending follow-up work rather than a retroactive payload failure.
    # The explicit setup command still owns (and reports) the queue's terminal verdict.
    setup_controls_exit = action == "setup"
    payload["ok"] = outcome.session_status != "failed" and (setup_ok or not setup_controls_exit)
    reporting = _prepare_cli_reporting(
        request,
        service.value,
        review,
        outcome,
        setup_payload,
    )
    reporting_data = _json_reporting_data(reporting) if request.json else None
    if reporting_data is not None:
        payload["reporting"] = reporting_data
    _emit(request, operation, payload, lines)
    if not request.json:
        _render_cli_reporting(reporting)
    if outcome.session_status in {"failed", "partial"} or (setup_controls_exit and not setup_ok):
        return _common.ERROR
    return _common.OK


def _undo(request: Request, loaded, operation: str) -> int:
    """Review-first, exactly as every other mutating action: `--yes` finalizes, nothing else."""

    payload, digest = undo_view(loaded)

    if not request.yes:
        _emit(
            request,
            operation,
            {
                "schema_version": 1,
                "ok": True,
                "operation": operation,
                "finalized": False,
                "undo_digest": digest,
                "undo": payload,
            },
            render_undo_payload(payload)
            + ("Reviewed only; re-run with --yes to apply this exact undo.",),
        )
        return _common.OK

    if request.expect is not None and request.expect != digest:
        refusal = Diagnostic(
            CONSUMER_REVIEW_MISMATCH,
            Severity.ERROR,
            f"the undo changed since it was reviewed: expected {request.expect}, "
            f"recomputed {digest}",
            remediation=("re-read the undo below, then re-run --expect with its undo_digest",),
        )
        _emit(
            request,
            operation,
            {
                "schema_version": 1,
                "ok": False,
                "operation": operation,
                "finalized": False,
                "diagnostics": [diagnostic_to_data(refusal)],
                "expected_undo_digest": request.expect,
                "undo_digest": digest,
                "undo": payload,
            },
            (
                f"{refusal.severity.value}: {refusal.message}",
                *(f"  remediation: {item}" for item in refusal.remediation),
                *render_undo_payload(payload),
            ),
        )
        return _common.ERROR

    rolled = apply_undo(loaded)
    complete = rolled.status == "skipped"
    _emit(
        request,
        operation,
        {
            "schema_version": 1,
            "ok": complete,
            "operation": operation,
            "finalized": True,
            "undo_digest": digest,
            "status": rolled.status,
            "detail": rolled.detail,
            "undo": payload,
        },
        render_undo_payload(payload, applied=True)
        + (f"Undo outcome: {rolled.status} \u2014 {rolled.detail}",),
    )
    return _common.OK if complete else _common.ERROR


def _receipt(request: Request) -> int:
    operation = f"marketplace.receipt.{request.receipt_action or 'show'}"
    if request.receipt_action not in RECEIPT_ACTIONS:
        return _emit_error(request, unsupported_action(request.receipt_action), operation)

    runtime = load_runtime_configuration(request, content_required=False)
    if isinstance(runtime, Err):
        return _emit_error(request, runtime, operation)
    data_root = runtime.value.paths.data_root
    project_root, home = resolved_paths(
        data_root=data_root, project=request.project, user_home=request.user_home
    )
    loaded = load_receipt(
        data_root=data_root,
        project_root=project_root,
        user_home=home,
        scope=request.scope,
        selector=request.names[0],
        profiles=tuple(request.profiles),
    )
    if isinstance(loaded, Err):
        return _emit_error(request, loaded, operation)

    if request.receipt_action == "undo":
        return _undo(request, loaded.value, operation)

    if request.receipt_action == "verify":
        verification = verify_view(loaded.value)
        _emit(
            request,
            operation,
            {
                "schema_version": 1,
                # A false claim is a finding, and a finding must not report success to CI.
                "ok": verification["false"] == 0,
                "operation": operation,
                "coordinate": loaded.value.location.coordinate,
                "verification": verification,
            },
            render_verification_payload(verification),
        )
        return _common.OK if verification["false"] == 0 else _common.ERROR

    payload = show_view(loaded.value)
    _emit(
        request,
        operation,
        {
            "schema_version": 1,
            "ok": True,
            "operation": operation,
            "receipt": payload,
        },
        render_receipt_payload(payload),
    )
    return _common.OK


def run(request: Request) -> int:
    """Run one canonical marketplace command."""

    if request.marketplace_action == "receipt":
        return _receipt(request)
    if request.marketplace_action == "list":
        return _list(request)
    if request.marketplace_action == "health":
        return _health(request)
    if request.marketplace_action in _LIFECYCLE_ACTIONS:
        return _lifecycle(request, request.marketplace_action)
    if request.json:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "ok": False,
                    "operation": "marketplace",
                    "diagnostics": [
                        {
                            "code": "consumer-invalid",
                            "severity": "error",
                            "message": "unsupported marketplace command action",
                            "location": None,
                            "remediation": [],
                        }
                    ],
                },
                indent=2,
            )
        )
    else:
        print("error: unsupported marketplace command action")
    return _common.ERROR


__all__ = ["run"]
