"""Shared records and render helpers for batch upstream import."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Tuple

from .model import ArtifactType
from .upstreams import UpstreamKey, UpstreamSource, format_upstream_key

DetectedBy = Literal["manifest", "heuristic"]
Confidence = Literal["explicit", "high", "medium", "ambiguous"]
UpstreamKind = Literal["file", "tree"]
SelectionState = Literal["selected", "skipped", "conflict"]


@dataclass(frozen=True, slots=True)
class ImportCandidate:
    key: UpstreamKey
    source: UpstreamSource
    detected_by: DetectedBy
    confidence: Confidence
    upstream_kind: UpstreamKind
    local_destination: str
    absolute_path: str
    descriptor_path: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    warnings: Tuple[str, ...] = ()
    selected_by_default: bool = True


@dataclass(frozen=True, slots=True)
class ImportScan:
    mode: DetectedBy
    repo: str
    ref: str
    scan_root: str
    sha: str
    root: str
    candidates: Tuple[ImportCandidate, ...]
    warnings: Tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ImportConflict:
    key: UpstreamKey
    reason: str
    path: str = ""


@dataclass(frozen=True, slots=True)
class ImportSelection:
    selected: Tuple[ImportCandidate, ...]
    skipped: Tuple[ImportCandidate, ...]
    conflicts: Tuple[ImportConflict, ...] = ()
    warnings: Tuple[str, ...] = ()


def candidate_label(candidate: ImportCandidate) -> str:
    return format_upstream_key(candidate.key)


def candidate_to_dict(candidate: ImportCandidate) -> dict:
    return {
        "key": candidate_label(candidate),
        "type": candidate.key.type,
        "name": candidate.key.name,
        "path": candidate.source.path,
        "detected_by": candidate.detected_by,
        "confidence": candidate.confidence,
        "upstream_kind": candidate.upstream_kind,
        "local_destination": candidate.local_destination,
        "descriptor_path": candidate.descriptor_path,
        "title": candidate.title,
        "description": candidate.description,
        "selected_by_default": candidate.selected_by_default,
        "warnings": list(candidate.warnings),
    }


def scan_to_dict(scan: ImportScan) -> dict:
    return {
        "mode": scan.mode,
        "repo": scan.repo,
        "ref": scan.ref,
        "scan_root": scan.scan_root,
        "sha": scan.sha,
        "candidates": [candidate_to_dict(c) for c in scan.candidates],
        "warnings": list(scan.warnings),
    }


def render_scan(scan: ImportScan) -> str:
    lines = [
        f"Scan {scan.repo}@{scan.sha} (ref {scan.ref}, mode {scan.mode})",
    ]
    if scan.warnings:
        lines.extend(f"warning: {w}" for w in scan.warnings)

    grouped: dict[ArtifactType, list[ImportCandidate]] = {
        "skill": [],
        "guideline": [],
        "mcp": [],
        "hook": [],
        "memory": [],
    }
    for candidate in scan.candidates:
        grouped[candidate.key.type].append(candidate)

    for artifact_type in ("skill", "guideline", "mcp", "hook", "memory"):
        items = grouped[artifact_type]
        if not items:
            continue
        lines.append("")
        lines.append(artifact_type)
        for candidate in items:
            marker = "*" if candidate.selected_by_default else "-"
            lines.append(
                f"  [{candidate.confidence:<9}] {marker} "
                f"{candidate.key.name:<24} {candidate.source.path}"
            )
            for warning in candidate.warnings:
                lines.append(f"      warning: {warning}")
    return "\n".join(lines)


def destination_for(
    artifact_type: ArtifactType,
    name: str,
    *,
    tree: bool = False,
) -> str:
    if artifact_type == "skill":
        return f"skills/{name}"
    if artifact_type == "hook":
        return f"hooks/{name}"
    if artifact_type == "guideline":
        return f"guidelines/{name}.md"
    if artifact_type == "mcp":
        return f"mcp/{name}" if tree else f"mcp/{name}.json"
    if artifact_type == "memory":
        return f"memory/{name}.md"
    return f"{artifact_type}/{name}"
