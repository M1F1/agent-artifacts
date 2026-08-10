"""Allowlisted projection from canonical consumer/setup outcomes to reporting events."""

from __future__ import annotations

from dataclasses import dataclass

from agent_artifacts.consumer.model import ConsumerOutcome, ConsumerReview
from agent_artifacts.domain.identifiers import ObjectDigest

from .model import ReportingFailure, UsageReport, UsageResult

_ARTIFACT_FAILURE_CATEGORY = {
    "source-unavailable": "network",
    "broken": "configuration",
    "conflict": "conflict",
    "failed": "unexpected",
    "interrupted": "user-cancelled",
}
_SETUP_FAILURE_CATEGORY = {
    "verification": "verification",
    "rollback": "configuration",
    "queue": "configuration",
    "setup-installer": "unexpected",
}


@dataclass(frozen=True, slots=True)
class SetupReportState:
    key: str
    status: str
    installer_digest: ObjectDigest | None = None
    failure_phase: str | None = None
    failure_code: str | None = None

    def __post_init__(self) -> None:
        if (
            not self.key
            or not self.status
            or (self.failure_phase is None) != (self.failure_code is None)
            or (
                self.failure_phase is not None and self.failure_phase not in _SETUP_FAILURE_CATEGORY
            )
        ):
            raise ValueError("setup report state is invalid")


def _artifact_failure(status: str) -> ReportingFailure | None:
    category = _ARTIFACT_FAILURE_CATEGORY.get(status)
    if category is None:
        return None
    return ReportingFailure(
        "artifact-install",
        category,
        f"artifact-{status}",
        interrupted=status == "interrupted",
        retryable=status in {"source-unavailable", "failed"},
    )


def _setup_failure(state: SetupReportState | None) -> ReportingFailure | None:
    if state is None or state.failure_phase is None or state.failure_code is None:
        return None
    if state.status in {"cancelled", "queue-declined"}:
        category = "user-cancelled"
    elif state.status == "unsupported":
        category = "unsupported"
    elif state.status == "prerequisite-missing":
        category = "dependency"
    elif state.status == "conflicted":
        category = "conflict"
    elif state.status == "verification-failed":
        category = "verification"
    else:
        category = _SETUP_FAILURE_CATEGORY[state.failure_phase]
    return ReportingFailure(
        state.failure_phase,
        category,
        state.failure_code,
        retryable=state.status not in {"cancelled", "queue-declined"},
    )


def usage_report_from_consumer(
    review: ConsumerReview,
    outcome: ConsumerOutcome,
    setup: tuple[SetupReportState, ...],
    *,
    aart_version: str,
    interface: str,
) -> UsageReport:
    """Project only enum-like facts; intentionally ignore paths, sources and detail strings."""

    review_by_key = {item.key: item for item in review.items}
    outcome_by_key = {item.key: item for item in outcome.items}
    setup_by_key = {item.key: item for item in setup}
    if (
        review.request.action != outcome.action
        or set(review_by_key) != set(outcome_by_key)
        or len(setup_by_key) != len(setup)
        or not set(setup_by_key) <= set(review_by_key)
    ):
        raise ValueError("consumer reporting projection identities do not match")
    results = []
    for key in sorted(review_by_key):
        item = review_by_key[key]
        terminal = outcome_by_key[key]
        setup_state = setup_by_key.get(key)
        modes = tuple(sorted({effect.actual_mode for effect in item.effects}))
        if not modes:
            modes = (review.request.mode,)
        setup_status = terminal.setup_status if setup_state is None else setup_state.status
        failure = _artifact_failure(terminal.status) or _setup_failure(setup_state)
        results.append(
            UsageResult(
                item.coordinate.artifact.kind,
                item.coordinate.artifact.name,
                item.profile,
                item.scope,
                review.request.mode,
                modes,
                terminal.status,
                setup_status,
                None if setup_state is None else setup_state.installer_digest,
                failure,
            )
        )
    return UsageReport(
        aart_version,
        interface,
        review.request.platform,
        review.request.action,
        tuple(results),
    )


__all__ = ["SetupReportState", "usage_report_from_consumer"]
