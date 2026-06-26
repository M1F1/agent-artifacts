"""Pure-ish planning helpers for batch upstream import."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Optional, Tuple

from . import catalog as catalog_mod
from .import_candidates import (
    ImportCandidate,
    ImportConflict,
    ImportScan,
    ImportSelection,
    candidate_label,
)
from .model import Action, CopyTree, Err, Ok, Plan, RemovePath, Result, Warn, WriteFile
from .upstream_source import hash_upstream_path
from .upstreams import (
    UpstreamCatalog,
    UpstreamEntry,
    UpstreamKey,
    UpstreamSync,
    dump_upstreams,
    parse_upstream_key,
    parse_upstreams,
)

BundleMode = Literal["append", "replace", "fail"]

UPSTREAMS_FILE = "upstreams.json"


@dataclass(frozen=True, slots=True)
class ImportPlan:
    selection: ImportSelection
    plan: Plan
    bundle_path: Optional[str] = None
    tracking_path: Optional[str] = None


def select_candidates(candidates: Tuple[ImportCandidate, ...], names: Tuple[str, ...]) -> Result:
    if names:
        wanted = []
        errors = []
        for name in names:
            parsed = parse_upstream_key(name)
            if isinstance(parsed, Err):
                errors.append(parsed.reason)
            else:
                wanted.append(parsed.value)
        if errors:
            return Err("; ".join(errors), code=2)
        wanted_set = set(wanted)
        by_key = {candidate.key: candidate for candidate in candidates}
        missing = [key for key in wanted if key not in by_key]
        if missing:
            return Err(
                "unknown import candidate(s): "
                + ", ".join(f"{key.type}/{key.name}" for key in missing),
                code=2,
            )
        selected = tuple(by_key[key] for key in wanted)
        skipped = tuple(candidate for candidate in candidates if candidate.key not in wanted_set)
        return Ok(ImportSelection(selected=selected, skipped=skipped))

    selected = tuple(candidate for candidate in candidates if candidate.selected_by_default)
    skipped = tuple(candidate for candidate in candidates if not candidate.selected_by_default)
    warnings = tuple(
        f"skipped {candidate_label(candidate)}: not selected by default"
        for candidate in skipped
        if candidate.confidence == "ambiguous"
    )
    return Ok(ImportSelection(selected=selected, skipped=skipped, warnings=warnings))


def plan_import(
    scan: ImportScan,
    *,
    catalog_root: str,
    names: Tuple[str, ...] = (),
    bundle_name: Optional[str] = None,
    bundle_description: Optional[str] = None,
    bundle_mode: BundleMode = "append",
    force: bool = False,
) -> Result:
    selection_res = select_candidates(scan.candidates, names)
    if isinstance(selection_res, Err):
        return selection_res
    selection = selection_res.value

    conflicts = _conflicts(selection.selected, catalog_root, bundle_name, bundle_mode, force=force)
    if conflicts:
        warnings: Tuple[Action, ...] = tuple(Warn(c.reason) for c in conflicts)
        return Ok(
            ImportPlan(
                selection=ImportSelection(
                    selected=selection.selected,
                    skipped=selection.skipped,
                    conflicts=conflicts,
                    warnings=selection.warnings,
                ),
                plan=warnings,
            )
        )

    actions: Tuple[Action, ...] = ()
    for candidate in selection.selected:
        dest = os.path.join(catalog_root, candidate.local_destination)
        if candidate.upstream_kind == "tree":
            if force and os.path.exists(dest):
                actions += (RemovePath(path=dest),)
            actions += (CopyTree(src=candidate.absolute_path, dst=dest),)
        else:
            actions += (WriteFile(path=dest, content=_read_bytes(candidate.absolute_path)),)

    bundle_path = None
    if bundle_name and selection.selected:
        bundle_path = os.path.join(catalog_root, "bundles", f"{bundle_name}.json")
        bundle_res = _bundle_bytes(
            bundle_path,
            bundle_name,
            selection.selected,
            description=bundle_description,
            mode=bundle_mode,
        )
        if isinstance(bundle_res, Err):
            return bundle_res
        actions += (WriteFile(path=bundle_path, content=bundle_res.value),)

    tracking_path = None
    if selection.selected:
        tracking_path = os.path.join(catalog_root, UPSTREAMS_FILE)
        tracking_res = _tracking_bytes(
            tracking_path,
            selection.selected,
            sha=scan.sha,
            synced_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        if isinstance(tracking_res, Err):
            return tracking_res
        actions += (WriteFile(path=tracking_path, content=tracking_res.value),)

    return Ok(
        ImportPlan(
            selection=selection,
            plan=actions,
            bundle_path=bundle_path,
            tracking_path=tracking_path,
        )
    )


def _conflicts(
    candidates: Tuple[ImportCandidate, ...],
    catalog_root: str,
    bundle_name: Optional[str],
    bundle_mode: BundleMode,
    *,
    force: bool,
) -> Tuple[ImportConflict, ...]:
    if force:
        return ()
    out = []
    tracking = _load_tracking(os.path.join(catalog_root, UPSTREAMS_FILE))
    tracked = tracking.entries if isinstance(tracking, UpstreamCatalog) else {}
    for candidate in candidates:
        dest = os.path.join(catalog_root, candidate.local_destination)
        if os.path.exists(dest):
            out.append(
                ImportConflict(
                    key=candidate.key,
                    reason=f"{candidate.local_destination} already exists; pass --force",
                    path=dest,
                )
            )
        if candidate.key in tracked:
            out.append(
                ImportConflict(
                    key=candidate.key,
                    reason=f"{candidate_label(candidate)} is already tracked; pass --force",
                    path=os.path.join(catalog_root, UPSTREAMS_FILE),
                )
            )
    if bundle_name and bundle_mode == "fail":
        bundle_path = os.path.join(catalog_root, "bundles", f"{bundle_name}.json")
        if os.path.exists(bundle_path):
            out.append(
                ImportConflict(
                    key=UpstreamKey("skill", bundle_name),
                    reason=f"bundle {bundle_name!r} already exists",
                    path=bundle_path,
                )
            )
    return tuple(out)


def _tracking_bytes(
    path: str,
    candidates: Tuple[ImportCandidate, ...],
    *,
    sha: str,
    synced_at: str,
) -> Result:
    catalog = _load_tracking(path)
    if isinstance(catalog, Err):
        return catalog
    entries = dict(catalog.entries)
    for candidate in candidates:
        try:
            content_hash = hash_upstream_path(candidate.absolute_path)
        except OSError as exc:
            return Err(f"could not hash {candidate.source.path}: {exc}", code=1)
        entries[candidate.key] = UpstreamEntry(
            key=candidate.key,
            source=candidate.source,
            last_synced=UpstreamSync(
                sha=sha,
                content_hash=content_hash,
                synced_at=synced_at,
            ),
        )
    return Ok(dump_upstreams(UpstreamCatalog(version=catalog.version, entries=entries)).encode())


def _load_tracking(path: str):
    if not os.path.exists(path):
        return UpstreamCatalog(version=1, entries={})
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        return Err(f"cannot read {path}: {exc}", code=1)
    parsed = parse_upstreams(text)
    return parsed.value if isinstance(parsed, Ok) else parsed


def _bundle_bytes(
    path: str,
    name: str,
    candidates: Tuple[ImportCandidate, ...],
    *,
    description: Optional[str],
    mode: BundleMode,
) -> Result:
    existing = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                existing = json.load(fh)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            return Err(f"cannot read bundle {name!r}: {exc}", code=1)
        if not isinstance(existing, dict):
            return Err(f"bundle {name!r}: expected a JSON object", code=2)
        if mode == "fail":
            return Err(f"bundle {name!r} already exists", code=4)

    if mode == "replace" or not existing:
        payload = {
            "name": name,
            "description": description or existing.get("description", "") or "",
            "includes": _includes_for(candidates),
        }
        if existing.get("extends"):
            payload["extends"] = existing["extends"]
        if existing.get("pins"):
            payload["pins"] = existing["pins"]
    else:
        payload = dict(existing)
        payload.setdefault("name", name)
        if description is not None:
            payload["description"] = description
        payload["includes"] = _merge_includes(payload.get("includes", {}), candidates)

    text = json.dumps(payload, indent=2) + "\n"
    parsed = catalog_mod.parse_bundle(text, name)
    if isinstance(parsed, Err):
        return parsed
    return Ok(text.encode("utf-8"))


def _includes_for(candidates: Tuple[ImportCandidate, ...]) -> dict:
    includes: dict[str, list[str]] = {}
    for candidate in candidates:
        section = _section(candidate.key.type)
        includes.setdefault(section, [])
        if candidate.key.name not in includes[section]:
            includes[section].append(candidate.key.name)
    return includes


def _merge_includes(raw, candidates: Tuple[ImportCandidate, ...]) -> dict:
    includes = {}
    if isinstance(raw, dict):
        for section, values in raw.items():
            if isinstance(values, list):
                includes[section] = [v for v in values if isinstance(v, str)]
    for section, values in _includes_for(candidates).items():
        bucket = includes.setdefault(section, [])
        for value in values:
            if value not in bucket:
                bucket.append(value)
    return includes


def _section(artifact_type: str) -> str:
    return {
        "skill": "skills",
        "guideline": "guidelines",
        "mcp": "mcp",
        "hook": "hooks",
        "memory": "memory",
    }.get(artifact_type, artifact_type)


def _read_bytes(path: str) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()
