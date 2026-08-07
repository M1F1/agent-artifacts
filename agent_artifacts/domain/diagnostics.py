"""Typed, deterministic diagnostics for expected domain failures."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .identifiers import SourceAlias

INITIAL_ERROR_CODES = (
    "artifact-ambiguous",
    "artifact-incompatible",
    "artifact-not-found",
    "digest-mismatch",
    "import-lossy",
    "import-stale",
    "install-conflict",
    "lock-stale",
    "no-source-configured",
    "offline-object-missing",
    "setup-policy-denied",
    "source-auth-failed",
    "source-incompatible",
    "source-invalid",
    "source-policy-denied",
    "source-unavailable",
)


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True, order=True)
class DiagnosticCode:
    """Extensible nominal code; protocol validators define accepted code syntax."""

    value: str

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class SourceLocation:
    source: SourceAlias | None = None
    path: str | None = None
    pointer: str | None = None
    line: int | None = None
    column: int | None = None


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: DiagnosticCode
    severity: Severity
    message: str
    location: SourceLocation | None = None
    remediation: tuple[str, ...] = ()
    details: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "remediation", tuple(sorted(set(self.remediation))))
        object.__setattr__(self, "details", tuple(sorted(self.details)))


def _location_key(location: SourceLocation | None) -> tuple[str, str, int, int, str]:
    if location is None:
        return ("", "", -1, -1, "")
    return (
        "" if location.source is None else location.source.value,
        location.path or "",
        -1 if location.line is None else location.line,
        -1 if location.column is None else location.column,
        location.pointer or "",
    )


def diagnostic_sort_key(
    diagnostic: Diagnostic,
) -> tuple[str, str, int, int, str, str, str, str, tuple[str, ...], tuple[tuple[str, str], ...]]:
    location = _location_key(diagnostic.location)
    return (
        *location,
        diagnostic.severity.value,
        diagnostic.code.value,
        diagnostic.message,
        diagnostic.remediation,
        diagnostic.details,
    )


def sort_diagnostics(diagnostics: Iterable[Diagnostic]) -> tuple[Diagnostic, ...]:
    return tuple(sorted(diagnostics, key=diagnostic_sort_key))


def source_location_to_data(location: SourceLocation) -> dict[str, object]:
    return {
        "source": None if location.source is None else location.source.value,
        "path": location.path,
        "pointer": location.pointer,
        "line": location.line,
        "column": location.column,
    }


def diagnostic_to_data(diagnostic: Diagnostic) -> dict[str, object]:
    data: dict[str, object] = {
        "code": diagnostic.code.value,
        "severity": diagnostic.severity.value,
        "message": diagnostic.message,
        "location": (
            None if diagnostic.location is None else source_location_to_data(diagnostic.location)
        ),
        "remediation": list(diagnostic.remediation),
    }
    if diagnostic.details:
        data["details"] = dict(diagnostic.details)
    return data
