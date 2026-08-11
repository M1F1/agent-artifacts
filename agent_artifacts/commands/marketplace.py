"""Agent CLI surface for the configured canonical marketplace.

The legacy ``list``/``install``/``update`` commands remain bounded 0.1 compatibility commands.
This module exposes the configured-source marketplace and its canonical lifecycle without
silently changing that legacy contract.

Two properties are load-bearing for automation safety and are asserted by the tests:

* **Review before Finalize.**  The TUI asks a human to confirm an exact reviewed plan.  The
  non-interactive equivalent is ``--yes``: without it every action stops after Review and reports
  the plan it *would* apply.  Finalize always passes the digest of the review computed in this same
  process, so a plan can never drift between Review and Finalize.
* **Authorizations are never implied.**  Untrusted-source setup, custom entrypoints, and setup
  effect consent each need their own flag.  Omitting a flag denies; it never asks and never
  assumes.
"""

from __future__ import annotations

import json

from agent_artifacts.consumer.application import ConsumerApplicationService
from agent_artifacts.consumer.coordinates import CONSUMER_INVALID, parse_artifact_selectors
from agent_artifacts.consumer.model import (
    ConsumerAction,
    ConsumerActionRequest,
    ConsumerOutcome,
    ConsumerReview,
    ConsumerSetupQueue,
    consumer_review_value,
    render_consumer_outcome,
    render_consumer_review,
)
from agent_artifacts.consumer.resolution import resolve_selectors
from agent_artifacts.consumer.runtime import load_local_consumer_service, load_read_only_marketplace
from agent_artifacts.domain.diagnostics import Diagnostic, Severity, diagnostic_to_data
from agent_artifacts.domain.result import Err, Result
from agent_artifacts.marketplace.catalog import marketplace_catalog_bytes, render_marketplace
from agent_artifacts.model import Request
from agent_artifacts.protocol.json import canonical_json_bytes
from agent_artifacts.runtime_contract import EXECUTABLE_VERSION

from . import _common
from ._configured_runtime import load_runtime_configuration

_LIST_OPERATION = "marketplace.list"

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
    )


def _setup_payload(queue: ConsumerSetupQueue, outcome=None) -> dict:
    payload: dict = {
        "planned": [
            {
                "key": (f"{plan.request.coordinate}#{plan.request.profile}/{plan.request.scope}"),
                "trust": plan.trust,
                "recipe": str(plan.recipe_path),
                "review_digest": str(plan.review_digest),
                "effects": [
                    {
                        "module": effect.module,
                        "summary": effect.summary,
                        "reversible": effect.reversible,
                    }
                    for effect in plan.legacy_plan.effects
                ],
            }
            for plan in queue.plans
        ],
        "planning_failures": [
            {"key": failure.key, "detail": failure.detail} for failure in queue.failures
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
    )
    if isinstance(service, Err):
        return _emit_error(request, service, operation)
    coordinates = resolve_selectors(service.value.context.catalog, selection.value)
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
        }
        if action == "setup":
            payload["setup"] = _setup_payload(
                service.value.setup_queue(
                    review,
                    ConsumerOutcome(_LIFECYCLE_ACTIONS[action], ()),
                    authorize_untrusted_source=request.authorize_untrusted_source,
                    authorize_custom_entrypoint=request.authorize_custom_entrypoint,
                )
            )
        _emit(
            request,
            operation,
            payload,
            render_consumer_review(review)
            + ("Reviewed only; re-run with --yes to apply this exact plan.",),
        )
        return _common.OK

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
    if action == "setup" or any(item.setup_status == "pending" for item in outcome.items):
        setup_payload, setup_ok = _run_setup_queue(request, service.value, review, outcome)
        payload["setup"] = setup_payload
        lines += (
            f"Setup: planned={len(setup_payload['planned'])}, "
            f"failures={len(setup_payload['planning_failures'])}",
        )
    payload["ok"] = outcome.session_status != "failed" and setup_ok
    _emit(request, operation, payload, lines)
    if outcome.session_status in {"failed", "partial"} or not setup_ok:
        return _common.ERROR
    return _common.OK


def run(request: Request) -> int:
    """Run one canonical marketplace command."""

    if request.marketplace_action == "list":
        return _list(request)
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
