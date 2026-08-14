"""IO-free allowlisted reporting values and canonical projections."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlencode

from agent_artifacts.configuration.model import ReportingMode
from agent_artifacts.domain.identifiers import ObjectDigest
from agent_artifacts.protocol.json import JsonArray, JsonObject, JsonValue, canonical_json_bytes

_SLUG_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_PROFILE_RE = _SLUG_RE
_HOST_RE = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$")
_REPOSITORY_SEGMENT_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,98}[A-Za-z0-9])?$")
_VERSION_RE = re.compile(r"^[0-9A-Za-z](?:[0-9A-Za-z.+-]{0,63})$")
_CODE_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
_KINDS = frozenset({"skill", "guideline", "mcp", "hook", "memory"})
_SCOPES = frozenset({"project", "user"})
_MODES = frozenset({"copy", "symlink"})
_ACTIONS = frozenset({"install", "update", "uninstall", "status", "check"})
_ARTIFACT_OUTCOMES = frozenset(
    {
        "changed",
        "current",
        "update-available",
        "removed",
        "removed-upstream",
        "source-unavailable",
        "identity-changed",
        "missing",
        "drifted",
        "broken",
        "retargeted",
        "replaced",
        "conflict",
        "failed",
        "skipped",
        "cancelled",
        "interrupted",
        "unsupported",
    }
)
_SETUP_OUTCOMES = frozenset(
    {
        "not-required",
        "pending",
        "configured",
        "already-configured",
        "cancelled",
        "skipped",
        "unsupported",
        "prerequisite-missing",
        "apply-failed-rolled-back",
        "rollback-incomplete",
        "verification-failed",
        "conflicted",
        "failed",
        "rolled-back",
        "planning-failed",
        "queue-declined",
    }
)
_FAILURE_PHASES = frozenset(
    {"artifact-install", "setup-installer", "verification", "rollback", "queue"}
)
_FAILURE_CATEGORIES = frozenset(
    {
        "dependency",
        "network",
        "permission",
        "credential-store",
        "configuration",
        "verification",
        "user-cancelled",
        "unsupported",
        "conflict",
        "unexpected",
    }
)
_ARTIFACT_FAILURES = frozenset(
    {"source-unavailable", "broken", "conflict", "failed", "interrupted"}
)
_ARTIFACT_CANCELLED = frozenset({"cancelled"})
_ARTIFACT_NOOP = frozenset(
    {"current", "update-available", "missing", "drifted", "skipped", "unsupported"}
)
_SETUP_SUCCESS = frozenset({"not-required", "configured", "already-configured"})
_SETUP_CANCELLED = frozenset({"cancelled", "queue-declined"})
_MAX_RESULTS = 1_024
_MAX_BROWSER_URL = 32_768
MAX_USAGE_REPORT_BYTES = 60 * 1024
_MAX_SLUG_LENGTH = 64
_MAX_CODE_LENGTH = 64

SessionOutcome = Literal["succeeded", "no-op", "partial", "failed", "cancelled"]
SubmissionStatus = Literal["browser-opened", "submitted"]


def _digest(value: ObjectDigest | None) -> bool:
    return value is None or (
        value.algorithm == "sha256" and _HEX_RE.fullmatch(value.value) is not None
    )


@dataclass(frozen=True, slots=True)
class ReportingFailure:
    phase: str
    category: str
    code: str
    exit_code: int | None = None
    interrupted: bool = False
    retryable: bool = False
    fingerprint: str | None = None

    def __post_init__(self) -> None:
        if (
            self.phase not in _FAILURE_PHASES
            or self.category not in _FAILURE_CATEGORIES
            or _CODE_RE.fullmatch(self.code) is None
            or len(self.code) > _MAX_CODE_LENGTH
            or (
                self.exit_code is not None
                and (
                    not isinstance(self.exit_code, int)
                    or isinstance(self.exit_code, bool)
                    or not -1 <= self.exit_code <= 255
                )
            )
            or not isinstance(self.interrupted, bool)
            or not isinstance(self.retryable, bool)
            or (
                self.fingerprint is not None
                and re.fullmatch(r"sha256:[0-9a-f]{64}", self.fingerprint) is None
            )
        ):
            raise ValueError("reporting failure is invalid")


@dataclass(frozen=True, slots=True)
class UsageResult:
    artifact_type: str
    artifact_name: str
    profile: str
    scope: str
    requested_mode: str
    actual_modes: tuple[str, ...]
    artifact_outcome: str
    setup_outcome: str
    installer_digest: ObjectDigest | None = None
    failure: ReportingFailure | None = None

    def __post_init__(self) -> None:
        modes = tuple(sorted(set(self.actual_modes)))
        if (
            self.artifact_type not in _KINDS
            or _SLUG_RE.fullmatch(self.artifact_name) is None
            or len(self.artifact_name) > _MAX_SLUG_LENGTH
            or _PROFILE_RE.fullmatch(self.profile) is None
            or len(self.profile) > _MAX_SLUG_LENGTH
            or self.scope not in _SCOPES
            or self.requested_mode not in _MODES
            or not modes
            or modes != self.actual_modes
            or not set(modes) <= _MODES
            or self.artifact_outcome not in _ARTIFACT_OUTCOMES
            or self.setup_outcome not in _SETUP_OUTCOMES
            or not _digest(self.installer_digest)
            or (self.failure is not None and not isinstance(self.failure, ReportingFailure))
        ):
            raise ValueError("usage result is invalid")


def _session_outcome(results: tuple[UsageResult, ...]) -> SessionOutcome:
    failures = sum(
        item.artifact_outcome in _ARTIFACT_FAILURES
        or (
            item.setup_outcome not in _SETUP_SUCCESS
            and item.setup_outcome not in _SETUP_CANCELLED
            and item.artifact_outcome not in _ARTIFACT_FAILURES
        )
        for item in results
    )
    cancelled = sum(
        item.artifact_outcome in _ARTIFACT_CANCELLED or item.setup_outcome in _SETUP_CANCELLED
        for item in results
    )
    successful = len(results) - failures - cancelled
    if failures:
        return "partial" if successful or cancelled else "failed"
    if cancelled:
        return "partial" if successful else "cancelled"
    if results and all(item.artifact_outcome in _ARTIFACT_NOOP for item in results):
        return "no-op"
    return "succeeded"


def _summary(results: tuple[UsageResult, ...]) -> tuple[tuple[str, int], ...]:
    counts: dict[str, int] = {"selected": len(results)}
    for item in results:
        artifact_key = f"artifact_{item.artifact_outcome.replace('-', '_')}"
        setup_key = f"setup_{item.setup_outcome.replace('-', '_')}"
        counts[artifact_key] = counts.get(artifact_key, 0) + 1
        counts[setup_key] = counts.get(setup_key, 0) + 1
    counts["artifact_failed"] = sum(item.artifact_outcome in _ARTIFACT_FAILURES for item in results)
    counts["setup_incomplete"] = sum(item.setup_outcome not in _SETUP_SUCCESS for item in results)
    return tuple(sorted(counts.items()))


@dataclass(frozen=True, slots=True)
class UsageReport:
    aart_version: str
    interface: str
    platform: str
    action: str
    results: tuple[UsageResult, ...]

    def __post_init__(self) -> None:
        if (
            _VERSION_RE.fullmatch(self.aart_version) is None
            or self.interface not in {"tui", "cli"}
            or _SLUG_RE.fullmatch(self.platform) is None
            or len(self.platform) > _MAX_SLUG_LENGTH
            or self.action not in _ACTIONS
            or not self.results
            or len(self.results) > _MAX_RESULTS
            or any(not isinstance(item, UsageResult) for item in self.results)
        ):
            raise ValueError("usage report is invalid")

    @property
    def session_outcome(self) -> SessionOutcome:
        return _session_outcome(self.results)

    @property
    def summary(self) -> tuple[tuple[str, int], ...]:
        return _summary(self.results)


@dataclass(frozen=True, slots=True)
class ReportingDestination:
    mode: ReportingMode
    host: str
    repository: str

    def __post_init__(self) -> None:
        host = self.host.casefold()
        repository_segments = self.repository.split("/")
        if (
            self.mode not in {ReportingMode.PROMPT, ReportingMode.AUTOMATIC}
            or _HOST_RE.fullmatch(host) is None
            or len(repository_segments) != 2
            or any(
                _REPOSITORY_SEGMENT_RE.fullmatch(segment) is None for segment in repository_segments
            )
            or ".." in host
        ):
            raise ValueError("reporting destination is invalid")
        object.__setattr__(self, "host", host)


@dataclass(frozen=True, slots=True)
class ReportingPlan:
    destination: ReportingDestination
    event: UsageReport
    title: str
    body: str
    payload: bytes
    browser_url: str | None

    def __post_init__(self) -> None:
        expected_url = (
            reporting_browser_url(self.destination, self.event)
            if self.destination.mode is ReportingMode.PROMPT
            else None
        )
        if (
            self.payload != usage_report_bytes(self.event)
            or self.body != reporting_issue_body(self.event)
            or self.browser_url != expected_url
            or not self.title
            or "\n" in self.title
            or "\r" in self.title
        ):
            raise ValueError("reporting plan is invalid")


@dataclass(frozen=True, slots=True)
class ReportingSubmission:
    status: SubmissionStatus

    def __post_init__(self) -> None:
        if self.status not in {"browser-opened", "submitted"}:
            raise ValueError("reporting submission is invalid")


def _failure_json(failure: ReportingFailure) -> JsonObject:
    entries: list[tuple[str, JsonValue]] = [
        ("category", failure.category),
        ("code", failure.code),
        ("interrupted", failure.interrupted),
        ("phase", failure.phase),
        ("retryable", failure.retryable),
    ]
    if failure.exit_code is not None:
        entries.append(("exit_code", failure.exit_code))
    if failure.fingerprint is not None:
        entries.append(("fingerprint", failure.fingerprint))
    return JsonObject(tuple(entries))


def _result_json(result: UsageResult) -> JsonObject:
    entries: list[tuple[str, JsonValue]] = [
        ("actual_modes", JsonArray(result.actual_modes)),
        ("artifact_name", result.artifact_name),
        ("artifact_outcome", result.artifact_outcome),
        ("artifact_type", result.artifact_type),
        ("profile", result.profile),
        ("requested_mode", result.requested_mode),
        ("scope", result.scope),
        ("setup_outcome", result.setup_outcome),
    ]
    if result.installer_digest is not None:
        entries.append(("installer_digest", str(result.installer_digest)))
    if result.failure is not None:
        entries.append(("failure", _failure_json(result.failure)))
    return JsonObject(tuple(entries))


def usage_report_json(report: UsageReport) -> JsonObject:
    return JsonObject(
        (
            ("aart_version", report.aart_version),
            ("action", report.action),
            ("interface", report.interface),
            ("platform", report.platform),
            ("report_type", "aart-usage-session"),
            ("results", JsonArray(tuple(_result_json(item) for item in report.results))),
            ("schema_version", 1),
            ("session_outcome", report.session_outcome),
            ("summary", JsonObject(tuple(report.summary))),
        )
    )


def usage_report_bytes(report: UsageReport) -> bytes:
    payload = canonical_json_bytes(usage_report_json(report))
    if len(payload) > MAX_USAGE_REPORT_BYTES:
        raise ValueError("usage report exceeds the maximum size")
    return payload


def reporting_issue_body(report: UsageReport) -> str:
    return f"```json\n{usage_report_bytes(report).decode('utf-8').strip()}\n```\n"


def reporting_browser_url(destination: ReportingDestination, report: UsageReport) -> str:
    title = f"AART usage report: {report.action} / {report.session_outcome}"
    query = urlencode(
        {
            "template": "usage-report.yml",
            "title": title,
            "report": usage_report_bytes(report).decode("utf-8").strip(),
        }
    )
    url = f"https://{destination.host}/{destination.repository}/issues/new?{query}"
    if len(url) > _MAX_BROWSER_URL:
        raise ValueError("reporting browser URL exceeds the safe prefill bound")
    return url
