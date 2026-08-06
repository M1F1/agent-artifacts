"""Immutable action outcomes and pure human/JSON projections.

Commands translate planner and executor records into these values.  Frontends render the values;
they never parse command output to reconstruct selected/changed counts or item status.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping, Optional, Tuple

from .model import ArtifactType, InstallMode

OutcomeStatus = Literal[
    "installed",
    "reinstalled",
    "changed",
    "up_to_date",
    "removed",
    "already_absent",
    "skipped",
    "conflict",
    "failed",
    "preserved",
    "scanned",
    "imported",
    "checked",
    "updated",
    "cancelled",
]

_CHANGED_STATUSES = frozenset(
    {
        "installed",
        "reinstalled",
        "changed",
        "removed",
        "imported",
        "updated",
    }
)


@dataclass(frozen=True, slots=True)
class OutcomeItem:
    """One domain target and its terminal status for a completed action."""

    key: str
    status: OutcomeStatus
    artifact: Optional[str] = None
    artifact_type: Optional[ArtifactType] = None
    profile: Optional[str] = None
    mode: Optional[InstallMode] = None
    detail: Optional[str] = None


@dataclass(frozen=True, slots=True)
class ActionSummary:
    """Canonical, frontend-independent summary for one dispatched action."""

    action: str
    selected: int = 0
    items: Tuple[OutcomeItem, ...] = ()
    warnings: Tuple[str, ...] = ()
    recovery: Tuple[str, ...] = ()
    dry_run: bool = False


@dataclass(frozen=True, slots=True)
class CommandOutcome:
    """Process result plus canonical summary and compatibility payload."""

    exit_code: int
    summary: ActionSummary
    details: Tuple[str, ...] = ()
    payload: Mapping[str, object] = field(default_factory=dict)


def outcome_key(artifact_type: str, artifact: str, profile: Optional[str] = None) -> str:
    """Build a stable machine-readable identity for an artifact outcome."""

    base = f"{artifact_type}/{artifact}"
    return f"{base}@{profile}" if profile else base


def summary_counts(summary: ActionSummary) -> Mapping[str, int]:
    """Fold item statuses into insertion-ordered counts."""

    counts: dict[str, int] = {}
    for item in summary.items:
        counts[item.status] = counts.get(item.status, 0) + 1
    return counts


def changed_count(summary: ActionSummary) -> int:
    """Number of items whose status represents a durable domain change."""

    return sum(1 for item in summary.items if item.status in _CHANGED_STATUSES)


def mode_counts(summary: ActionSummary) -> Mapping[str, int]:
    """Fold actual install modes from item data, excluding non-artifact details."""

    counts: dict[str, int] = {}
    for item in summary.items:
        if item.mode is None:
            continue
        counts[item.mode] = counts.get(item.mode, 0) + 1
    return counts


def outcome_item_to_dict(item: OutcomeItem) -> dict:
    """Project one outcome item to stable JSON-shaped data."""

    return {
        "key": item.key,
        "status": item.status,
        "artifact": item.artifact,
        "type": item.artifact_type,
        "profile": item.profile,
        "mode": item.mode,
        "detail": item.detail,
    }


def summary_to_dict(summary: ActionSummary) -> dict:
    """Project a summary to the canonical machine-readable shape."""

    changed = changed_count(summary)
    return {
        "action": summary.action,
        "selected": summary.selected,
        "changed": changed,
        "no_changes": changed == 0,
        "counts": dict(summary_counts(summary)),
        "modes": dict(mode_counts(summary)),
        "items": [outcome_item_to_dict(item) for item in summary.items],
        "warnings": list(summary.warnings),
        "recovery": list(summary.recovery),
        "dry_run": summary.dry_run,
    }


def _plural(count: int, singular: str, plural: Optional[str] = None) -> str:
    return singular if count == 1 else (plural or f"{singular}s")


def _headline(summary: ActionSummary) -> str:
    counts = summary_counts(summary)
    changed = changed_count(summary)

    if summary.action == "cancelled":
        return "Cancelled; no changes were made."

    if summary.action == "install":
        installed = counts.get("installed", 0) + counts.get("reinstalled", 0)
        if summary.selected == 0:
            return (
                "Would install 0 artifacts; no files would change."
                if summary.dry_run
                else "Installed 0 artifacts; no files were changed."
            )
        if summary.dry_run:
            return (
                f"Would install {installed} {_plural(installed, 'artifact')}; "
                f"{summary.selected} selected."
            )
        return (
            f"Installed {installed} {_plural(installed, 'artifact')}; {summary.selected} selected."
        )

    if summary.action == "update":
        if summary.selected == 0:
            return "No installed artifacts matched the selected harness and filters."
        current = counts.get("up_to_date", 0)
        if summary.dry_run:
            return (
                f"Would update {changed} {_plural(changed, 'artifact')} of "
                f"{summary.selected} selected."
            )
        if changed == 0 and current == summary.selected:
            return (
                f"Updated 0 artifacts; all {summary.selected} selected artifacts are already "
                "up to date."
            )
        return f"Updated {changed} {_plural(changed, 'artifact')} of {summary.selected} selected."

    if summary.action == "uninstall":
        removed = counts.get("removed", 0)
        if summary.selected == 0:
            return "Removed 0 artifacts; no files were changed."
        if summary.dry_run:
            return (
                f"Would remove {removed} {_plural(removed, 'artifact')}; "
                f"{summary.selected} selected."
            )
        return (
            f"Removed {removed} {_plural(removed, 'artifact')}; "
            f"{removed} manifest {_plural(removed, 'entry', 'entries')} removed."
        )

    if summary.action == "upstream.update":
        updated = counts.get("updated", 0)
        if summary.selected == 0:
            return "Updated 0 upstream artifacts; no upstream changes were required."
        if summary.dry_run:
            return (
                f"Would update {updated} upstream {_plural(updated, 'artifact')}; "
                f"{summary.selected} selected."
            )
        return (
            f"Updated {updated} upstream {_plural(updated, 'artifact')}; "
            f"{summary.selected} selected."
        )

    if summary.action == "upstream.validate":
        failed = counts.get("failed", 0) + counts.get("conflict", 0)
        state = "valid" if failed == 0 else f"invalid ({failed} errors)"
        return f"Validated {summary.selected} {_plural(summary.selected, 'artifact')}; catalog is {state}."

    if summary.action == "upstream.health":
        attention = (
            counts.get("changed", 0)
            + counts.get("conflict", 0)
            + counts.get("skipped", 0)
            + counts.get("failed", 0)
        )
        return (
            f"Checked catalog health for {summary.selected} {_plural(summary.selected, 'artifact')}; "
            f"{attention} require attention."
        )

    if summary.action == "upstream.scan":
        scanned = counts.get("scanned", 0)
        return f"Scanned {scanned} {_plural(scanned, 'candidate')}."

    if summary.action in {"upstream.import", "upstream.add"}:
        imported = counts.get("imported", 0)
        verb = "Imported" if summary.action == "upstream.import" else "Added"
        return f"{verb} {imported} {_plural(imported, 'artifact')}; {summary.selected} selected."

    if summary.action == "upstream.check":
        available = counts.get("changed", 0)
        return (
            f"Checked {summary.selected} upstream {_plural(summary.selected, 'artifact')}; "
            f"{available} updates available."
        )

    verb = summary.action.replace("upstream.", "").replace("_", " ").capitalize()
    return (
        f"{verb}: {changed} changed of {summary.selected} selected."
        if summary.selected
        else f"{verb}: no matching items; no changes were made."
    )


def render_summary(summary: ActionSummary) -> Tuple[str, ...]:
    """Render the canonical human summary without performing I/O."""

    lines = [_headline(summary)]
    modes = mode_counts(summary)
    if summary.action == "install" and modes:
        copied = modes.get("copy", 0)
        linked = modes.get("symlink", 0)
        lines.append(f"Modes: {copied} copied, {linked} symlinked.")
    for item in summary.items:
        facts = []
        if item.mode is not None:
            facts.append(f"mode={item.mode}")
        if item.detail:
            facts.append(item.detail)
        suffix = f" ({'; '.join(facts)})" if facts else ""
        lines.append(f"  - {item.status}: {item.key}{suffix}")
    lines.extend(f"warning: {warning}" for warning in summary.warnings)
    lines.extend(f"next: {instruction}" for instruction in summary.recovery)
    return tuple(lines)


def render_outcome(outcome: CommandOutcome) -> Tuple[str, ...]:
    """Render command-specific detail followed by the canonical final summary."""

    return outcome.details + render_summary(outcome.summary)


def outcome_payload(outcome: CommandOutcome) -> dict:
    """Merge legacy command detail with the required canonical summary object."""

    payload = dict(outcome.payload)
    payload["summary"] = summary_to_dict(outcome.summary)
    return payload
