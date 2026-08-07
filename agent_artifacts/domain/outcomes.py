"""Terminal operation values and explicit JSON-shaped projections."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .diagnostics import Diagnostic, Severity, diagnostic_to_data, sort_diagnostics


class TerminalStatus(str, Enum):
    CHANGED = "changed"
    CURRENT = "current"
    SKIPPED = "skipped"
    CONFLICTED = "conflicted"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SessionStatus(str, Enum):
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class TerminalItem:
    key: str
    status: TerminalStatus
    diagnostics: tuple[Diagnostic, ...] = ()
    detail: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", sort_diagnostics(self.diagnostics))


@dataclass(frozen=True, slots=True)
class OperationOutcome:
    operation: str
    selected: int
    items: tuple[TerminalItem, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    remediation: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.selected < 0:
            raise ValueError("selected cannot be negative")
        object.__setattr__(
            self,
            "items",
            tuple(sorted(self.items, key=lambda item: (item.key, item.status.value))),
        )
        object.__setattr__(self, "diagnostics", sort_diagnostics(self.diagnostics))
        object.__setattr__(self, "remediation", tuple(sorted(set(self.remediation))))


def outcome_counts(outcome: OperationOutcome) -> tuple[tuple[str, int], ...]:
    counts: dict[str, int] = {}
    for item in outcome.items:
        counts[item.status.value] = counts.get(item.status.value, 0) + 1
    return tuple(sorted(counts.items()))


def changed_count(outcome: OperationOutcome) -> int:
    return sum(1 for item in outcome.items if item.status is TerminalStatus.CHANGED)


def session_status(outcome: OperationOutcome) -> SessionStatus:
    statuses = {item.status for item in outcome.items}
    unsuccessful = bool(statuses & {TerminalStatus.CONFLICTED, TerminalStatus.FAILED}) or any(
        diagnostic.severity is Severity.ERROR for diagnostic in outcome.diagnostics
    )
    successful = bool(statuses & {TerminalStatus.CHANGED, TerminalStatus.CURRENT})
    if unsuccessful and successful:
        return SessionStatus.PARTIAL
    if unsuccessful:
        return SessionStatus.FAILED
    if TerminalStatus.CANCELLED in statuses:
        return SessionStatus.PARTIAL if successful else SessionStatus.CANCELLED
    return SessionStatus.SUCCEEDED


def terminal_item_to_data(item: TerminalItem) -> dict[str, object]:
    return {
        "key": item.key,
        "status": item.status.value,
        "detail": item.detail,
        "diagnostics": [diagnostic_to_data(diagnostic) for diagnostic in item.diagnostics],
    }


def operation_outcome_to_data(outcome: OperationOutcome) -> dict[str, object]:
    return {
        "schema_version": 1,
        "operation": outcome.operation,
        "outcome": session_status(outcome).value,
        "selected": outcome.selected,
        "changed": changed_count(outcome),
        "counts": dict(outcome_counts(outcome)),
        "items": [terminal_item_to_data(item) for item in outcome.items],
        "diagnostics": [diagnostic_to_data(diagnostic) for diagnostic in outcome.diagnostics],
        "remediation": list(outcome.remediation),
    }
