"""Maintainer-side upstream tracking command."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Mapping, Optional, Tuple

from .. import catalog as catalog_mod
from .. import executor
from ..io import fs
from ..model import Err, Ok, Request
from ..source import open_source
from ..upstream_planner import (
    UpstreamStatus,
    UpstreamUpdatePlan,
    plan_upstream_check,
    plan_upstream_update,
)
from ..upstream_source import ResolvedUpstream, hash_upstream_path, resolve_upstream_source
from ..upstreams import (
    UpstreamCatalog,
    UpstreamEntry,
    UpstreamKey,
    UpstreamSync,
    dump_upstreams,
    format_upstream_key,
    parse_upstreams,
    select_upstreams,
    validate_upstreams,
)
from . import _common

UPSTREAMS_FILE = "upstreams.json"


def _catalog_root(request: Request) -> str:
    return request.source_dir or "."


def _tracking_path(request: Request) -> str:
    return os.path.join(_catalog_root(request), UPSTREAMS_FILE)


def _has_selector(request: Request) -> bool:
    return bool(request.names or request.bundles or request.all or request.type_filter)


def run(request: Request) -> int:
    if request.upstream_action not in {"check", "update"}:
        return _common.USAGE
    if request.upstream_action == "update" and not _has_selector(request):
        print("upstream update requires a selector (NAME, --bundle, --type, or --all)")
        return _common.USAGE
    catalog_root = os.path.abspath(_catalog_root(request))
    tracking_path = os.path.join(catalog_root, UPSTREAMS_FILE)
    if not os.path.exists(tracking_path):
        print(f"missing {UPSTREAMS_FILE} in {catalog_root}")
        return _common.USAGE

    loaded = _load_catalog_and_upstreams(catalog_root, tracking_path)
    if isinstance(loaded, Err):
        print(loaded.reason)
        return _common.exit_code(loaded)
    catalog, upstreams = loaded.value
    metadata_errors = validate_upstreams(upstreams, catalog)
    if metadata_errors:
        print("; ".join(err.reason for err in metadata_errors))
        return _common.USAGE

    selection = select_upstreams(request, catalog, upstreams)
    if isinstance(selection, Err):
        print(selection.reason)
        return _common.exit_code(selection)

    resolved = _resolve_all(selection.value.entries)
    if isinstance(resolved, Err):
        print(resolved.reason)
        return _common.exit_code(resolved)

    local_hashes = _local_hashes(selection.value.entries, catalog_root)
    staged_validation_errors = _validation_errors(resolved.value)

    if request.upstream_action == "check":
        planned = plan_upstream_check(
            selection.value.entries,
            resolved.value,
            local_hashes=local_hashes,
            validation_errors=staged_validation_errors,
        )
        if isinstance(planned, Err):
            print(planned.reason)
            return _common.exit_code(planned)
        _emit_check(
            request,
            catalog_root=catalog_root,
            selected=selection.value.entries,
            statuses=planned.value,
            warnings=selection.value.warnings,
        )
        return _common.OK

    planned_update = plan_upstream_update(
        selection.value.entries,
        resolved.value,
        force=request.force,
        local_hashes=local_hashes,
        validation_errors=staged_validation_errors,
        catalog_root=catalog_root,
    )
    if isinstance(planned_update, Err):
        print(planned_update.reason)
        return _common.exit_code(planned_update)

    update_plan: UpstreamUpdatePlan = planned_update.value
    if request.dry_run:
        _emit_update_dry_run(request, update_plan, selection.value.warnings)
        return _common.CONFLICT if update_plan.conflict and not request.force else _common.OK

    if update_plan.conflict and not request.force:
        _emit_update_conflict(request, update_plan, selection.value.warnings)
        return _common.CONFLICT

    report = executor.execute(update_plan.plan)
    updated = _statuses_to_persist(update_plan.statuses)
    if updated:
        fs.write_atomic(
            tracking_path,
            dump_upstreams(_with_updated_sync(upstreams, updated)).encode("utf-8"),
        )

    _emit_update_result(
        request,
        catalog_root=catalog_root,
        selected=selection.value.entries,
        update_plan=update_plan,
        warnings=selection.value.warnings + report.warnings,
        performed=report.performed,
        updated_count=len(updated),
    )
    return _common.OK


def _load_catalog_and_upstreams(catalog_root: str, tracking_path: str):
    source_result = open_source(Request(command="list", source_dir=catalog_root))
    if isinstance(source_result, Err):
        return source_result

    catalog_result = source_result.value.catalog()
    if isinstance(catalog_result, Err):
        return catalog_result

    try:
        tracking_text = fs.read_text(tracking_path)
    except OSError as exc:
        return Err(f"cannot read {tracking_path}: {exc}", code=_common.ERROR)

    upstreams_result = parse_upstreams(tracking_text)
    if isinstance(upstreams_result, Err):
        return upstreams_result

    return Ok((catalog_result.value, upstreams_result.value))


def _resolve_all(entries: Tuple[UpstreamEntry, ...]):
    resolved: List[ResolvedUpstream] = []
    for entry in entries:
        result = resolve_upstream_source(entry)
        if isinstance(result, Err):
            if "missing_upstream" in result.reason:
                continue
            return result
        resolved.append(result.value)
    return Ok(tuple(resolved))


def _local_hashes(entries: Tuple[UpstreamEntry, ...], catalog_root: str) -> Mapping[object, str]:
    hashes: Dict[object, str] = {}
    for entry in entries:
        path = _catalog_destination(entry.key, catalog_root)
        if os.path.exists(path):
            hashes[entry.key] = hash_upstream_path(path)
    return hashes


def _validation_errors(resolved: Tuple[ResolvedUpstream, ...]) -> Mapping[object, str]:
    errors: Dict[object, str] = {}
    for item in resolved:
        problem = _validate_resolved(item)
        if problem is not None:
            errors[item.entry.key] = problem
    return errors


def _validate_resolved(resolved: ResolvedUpstream) -> Optional[str]:
    key = resolved.entry.key
    try:
        if key.type == "skill":
            text = fs.read_text(os.path.join(resolved.path, "SKILL.md"))
            result = catalog_mod.parse_skill(text, key.name)
        elif key.type == "hook":
            text = fs.read_text(os.path.join(resolved.path, "hook.json"))
            result = catalog_mod.parse_hook(text, key.name)
        elif key.type == "guideline":
            result = catalog_mod.parse_guideline(fs.read_text(resolved.path), key.name)
        elif key.type == "mcp":
            result = catalog_mod.parse_mcp(fs.read_text(resolved.path), key.name)
        elif key.type == "memory":
            result = catalog_mod.parse_memory(fs.read_text(resolved.path), key.name)
        else:
            return f"unknown artifact type {key.type!r}"
    except OSError as exc:
        return str(exc)

    if isinstance(result, Err):
        return result.reason
    return None


def _statuses_to_persist(statuses: Tuple[UpstreamStatus, ...]) -> Mapping[UpstreamKey, UpstreamSync]:
    synced_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out: Dict[UpstreamKey, UpstreamSync] = {}
    for status in statuses:
        if status.state != "changed":
            continue
        if status.head_sha is None or status.head_hash is None:
            continue
        out[status.key] = UpstreamSync(
            sha=status.head_sha,
            content_hash=status.head_hash,
            synced_at=synced_at,
        )
    return out


def _with_updated_sync(
    catalog: UpstreamCatalog, updates: Mapping[UpstreamKey, UpstreamSync]
) -> UpstreamCatalog:
    entries = {}
    for key, entry in catalog.entries.items():
        entries[key] = (
            UpstreamEntry(key=entry.key, source=entry.source, last_synced=updates[key])
            if key in updates
            else entry
        )
    return UpstreamCatalog(version=catalog.version, entries=entries)


def _emit_check(
    request: Request,
    *,
    catalog_root: str,
    selected: Tuple[UpstreamEntry, ...],
    statuses: Tuple[UpstreamStatus, ...],
    warnings: Tuple[str, ...],
) -> None:
    if request.json:
        _common.print_json(
            {
                "action": "check",
                "catalog": catalog_root,
                "selected": [format_upstream_key(entry.key) for entry in selected],
                "warnings": list(warnings),
                "statuses": [_status_to_dict(status) for status in statuses],
            }
        )
        return

    for warning in warnings:
        print(f"warning: {warning}")
    for status in statuses:
        print(_human_status_line(status))


def _emit_update_dry_run(
    request: Request,
    update_plan: UpstreamUpdatePlan,
    warnings: Tuple[str, ...],
) -> None:
    if request.json:
        _common.print_json(
            {
                "action": "update",
                "dry_run": True,
                "warnings": list(warnings),
                "conflict": update_plan.conflict,
                "statuses": [_status_to_dict(status) for status in update_plan.statuses],
                "plan": json.loads(executor.plan_to_json(update_plan.plan)),
            }
        )
        return

    for warning in warnings:
        print(f"warning: {warning}")
    rendered = executor.render_plan(update_plan.plan)
    print(rendered if rendered else "No upstream changes.")


def _emit_update_conflict(
    request: Request,
    update_plan: UpstreamUpdatePlan,
    warnings: Tuple[str, ...],
) -> None:
    if request.json:
        _common.print_json(
            {
                "action": "update",
                "warnings": list(warnings),
                "conflict": True,
                "statuses": [_status_to_dict(status) for status in update_plan.statuses],
                "plan": json.loads(executor.plan_to_json(update_plan.plan)),
            }
        )
        return

    for warning in warnings:
        print(f"warning: {warning}")
    for action in update_plan.plan:
        if hasattr(action, "message"):
            print(action.message)


def _emit_update_result(
    request: Request,
    *,
    catalog_root: str,
    selected: Tuple[UpstreamEntry, ...],
    update_plan: UpstreamUpdatePlan,
    warnings: Tuple[str, ...],
    performed: Tuple[str, ...],
    updated_count: int,
) -> None:
    if request.json:
        _common.print_json(
            {
                "action": "update",
                "catalog": catalog_root,
                "selected": [format_upstream_key(entry.key) for entry in selected],
                "warnings": list(warnings),
                "conflict": update_plan.conflict,
                "statuses": [_status_to_dict(status) for status in update_plan.statuses],
                "performed": list(performed),
                "updated": updated_count,
            }
        )
        return

    print(f"Updated {updated_count} upstream artifact{'s' if updated_count != 1 else ''}.")
    for warning in warnings:
        print(f"warning: {warning}")


def _status_to_dict(status: UpstreamStatus) -> dict:
    return {
        "key": format_upstream_key(status.key),
        "type": status.key.type,
        "name": status.key.name,
        "state": status.state,
        "base_sha": status.base_sha,
        "head_sha": status.head_sha,
        "base_hash": status.base_hash,
        "head_hash": status.head_hash,
        "message": status.message,
    }


def _human_status_line(status: UpstreamStatus) -> str:
    label = format_upstream_key(status.key)
    detail = f" {status.message}" if status.message else ""
    return f"{label}: {status.state}{detail}"


def _catalog_destination(key: UpstreamKey, catalog_root: str) -> str:
    if key.type == "skill":
        rel = os.path.join("skills", key.name)
    elif key.type == "hook":
        rel = os.path.join("hooks", key.name)
    elif key.type == "guideline":
        rel = os.path.join("guidelines", f"{key.name}.md")
    elif key.type == "mcp":
        rel = os.path.join("mcp", f"{key.name}.json")
    elif key.type == "memory":
        rel = os.path.join("memory", f"{key.name}.md")
    else:
        rel = os.path.join(str(key.type), key.name)
    return os.path.join(catalog_root, rel)
