"""Maintainer-side upstream tracking command."""

from __future__ import annotations

import json
import os
import posixpath
from datetime import datetime, timezone
from typing import Dict, List, Mapping, Optional, Tuple, cast

from .. import catalog as catalog_mod
from .. import executor
from ..github_source import parse_github_url, resolve_github_location
from ..import_candidates import candidate_to_dict, render_scan, scan_to_dict
from ..import_planner import BundleMode, ImportPlan, plan_import
from ..import_scanner import ImportMode, scan_import_root
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
    UpstreamSource,
    UpstreamSync,
    dump_upstreams,
    format_upstream_key,
    parse_upstream_key,
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


def _github_token() -> Optional[str]:
    return os.environ.get("GITHUB_TOKEN")


def run(request: Request) -> int:
    if request.upstream_action == "add":
        return _run_add(request)
    if request.upstream_action == "scan":
        return _run_scan(request)
    if request.upstream_action == "import":
        return _run_import(request)
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
        executor.execute(update_plan.plan)
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


def _run_scan(request: Request) -> int:
    scan_res = _resolve_import_scan(request)
    if isinstance(scan_res, Err):
        print(scan_res.reason)
        return _common.exit_code(scan_res)
    _emit_scan(request, scan_res.value)
    return _common.OK


def _run_import(request: Request) -> int:
    scan_res = _resolve_import_scan(request)
    if isinstance(scan_res, Err):
        print(scan_res.reason)
        return _common.exit_code(scan_res)
    scan = scan_res.value

    names = request.names
    if request.interactive and not names:
        names = _interactive_selection(scan)

    if len(request.bundles) > 1:
        print("upstream import accepts at most one --bundle")
        return _common.USAGE
    bundle_name = request.bundles[0] if request.bundles else None
    bundle_mode = cast(BundleMode, request.bundle_mode or "append")
    catalog_root = os.path.abspath(_catalog_root(request))

    planned = plan_import(
        scan,
        catalog_root=catalog_root,
        names=names,
        bundle_name=bundle_name,
        bundle_description=request.bundle_description,
        bundle_mode=bundle_mode,
        force=request.force,
    )
    if isinstance(planned, Err):
        print(planned.reason)
        return _common.exit_code(planned)
    import_plan: ImportPlan = planned.value

    if request.dry_run:
        _emit_import_dry_run(request, scan, import_plan)
        return _common.CONFLICT if import_plan.selection.conflicts else _common.OK

    if import_plan.selection.conflicts:
        _emit_import_conflict(request, scan, import_plan)
        return _common.CONFLICT

    report = executor.execute(import_plan.plan)
    _emit_import_result(request, scan, import_plan, performed=report.performed)
    return _common.OK


def _resolve_import_scan(request: Request):
    if not request.url:
        return Err(f"upstream {request.upstream_action} requires a GitHub URL", code=_common.USAGE)
    url_res = parse_github_url(request.url)
    if isinstance(url_res, Err):
        return Err(f"invalid URL: {url_res.reason}", code=_common.USAGE)
    parts = url_res.value
    ref = request.ref or parts.ref or "main"
    path = request.path if request.path is not None else (parts.path or "")
    source = UpstreamSource(
        kind="github",
        repo=parts.repo,
        ref=ref,
        path=path,
        api_url=parts.api_url,
        web_url=parts.web_url if parts.api_url is not None else None,
    )
    entry = UpstreamEntry(key=UpstreamKey("skill", "__scan__"), source=source, last_synced=None)
    resolved = resolve_upstream_source(entry, token=_github_token())
    if isinstance(resolved, Err):
        return resolved

    scan_root = resolved.value.path
    scan_source_path = path
    if os.path.isfile(scan_root):
        scan_root = os.path.dirname(scan_root)
        scan_source_path = posixpath.dirname(path)
    scan_source = UpstreamSource(
        kind=source.kind,
        repo=source.repo,
        ref=source.ref,
        path="" if scan_source_path == "." else scan_source_path,
        api_url=source.api_url,
        web_url=source.web_url,
    )
    mode = cast(ImportMode, request.import_mode or "auto")
    return scan_import_root(
        scan_root,
        source=scan_source,
        sha=resolved.value.sha,
        mode=mode,
    )


def _interactive_selection(scan) -> Tuple[str, ...]:
    print(render_scan(scan))
    print("")
    answer = input("Select artifacts (comma-separated type/name, blank for defaults): ").strip()
    if not answer:
        return ()
    return tuple(part.strip() for part in answer.split(",") if part.strip())


def _emit_scan(request: Request, scan) -> None:
    if request.json:
        _common.print_json({"action": "scan", **scan_to_dict(scan)})
        return
    print(render_scan(scan))


def _emit_import_dry_run(request: Request, scan, import_plan: ImportPlan) -> None:
    if request.json:
        _common.print_json(_import_payload("import", request, scan, import_plan, dry_run=True))
        return
    _print_import_summary(import_plan, dry_run=True)
    rendered = executor.render_plan(import_plan.plan)
    if rendered:
        print(rendered)


def _emit_import_conflict(request: Request, scan, import_plan: ImportPlan) -> None:
    if request.json:
        _common.print_json(_import_payload("import", request, scan, import_plan, dry_run=False))
        return
    _print_import_summary(import_plan, dry_run=False)


def _emit_import_result(
    request: Request,
    scan,
    import_plan: ImportPlan,
    *,
    performed: Tuple[str, ...],
) -> None:
    if request.json:
        payload = _import_payload("import", request, scan, import_plan, dry_run=False)
        payload["performed"] = list(performed)
        _common.print_json(payload)
        return
    print(
        f"Imported {len(import_plan.selection.selected)} artifact"
        f"{'s' if len(import_plan.selection.selected) != 1 else ''}."
    )
    if import_plan.bundle_path:
        print(f"Bundle: {import_plan.bundle_path}")
    if import_plan.tracking_path:
        print(f"Tracked: {import_plan.tracking_path}")
    for warning in import_plan.selection.warnings:
        print(f"warning: {warning}")


def _import_payload(action: str, request: Request, scan, import_plan: ImportPlan, *, dry_run: bool):
    return {
        "action": action,
        "dry_run": dry_run,
        "mode": scan.mode,
        "repo": scan.repo,
        "ref": scan.ref,
        "sha": scan.sha,
        "selected": [candidate_to_dict(c) for c in import_plan.selection.selected],
        "skipped": [candidate_to_dict(c) for c in import_plan.selection.skipped],
        "conflicts": [
            {"key": f"{c.key.type}/{c.key.name}", "reason": c.reason, "path": c.path}
            for c in import_plan.selection.conflicts
        ],
        "warnings": list(import_plan.selection.warnings),
        "bundle": request.bundles[0] if request.bundles else None,
        "plan": json.loads(executor.plan_to_json(import_plan.plan)),
    }


def _print_import_summary(import_plan: ImportPlan, *, dry_run: bool) -> None:
    verb = "Would import" if dry_run else "Import blocked"
    print(
        f"{verb} {len(import_plan.selection.selected)} artifact"
        f"{'s' if len(import_plan.selection.selected) != 1 else ''}:"
    )
    for candidate in import_plan.selection.selected:
        print(f"  - {candidate.key.type:<9} {candidate.key.name} <- {candidate.source.path}")
    for candidate in import_plan.selection.skipped:
        if candidate.confidence == "ambiguous":
            print(f"warning: skipped ambiguous {candidate.key.type} {candidate.key.name!r}")
    for warning in import_plan.selection.warnings:
        print(f"warning: {warning}")
    for conflict in import_plan.selection.conflicts:
        print(f"conflict: {conflict.reason}")


def _run_add(request: Request) -> int:
    """Adopt one upstream artifact from a GitHub URL: resolve, vendor, and track it."""
    if not request.names:
        print("upstream add requires <type/name> and a URL")
        return _common.USAGE
    key_res = parse_upstream_key(request.names[0])
    if isinstance(key_res, Err):
        print(key_res.reason)
        return _common.USAGE
    key = key_res.value

    if not request.url:
        print("upstream add requires a GitHub URL")
        return _common.USAGE
    url_res = parse_github_url(request.url)
    if isinstance(url_res, Err):
        print(f"invalid URL: {url_res.reason}")
        return _common.USAGE
    parts = url_res.value

    ref = request.ref or parts.ref
    path = request.path or parts.path
    if not ref:
        print("could not determine a ref from the URL; pass --ref")
        return _common.USAGE
    if not path:
        print("could not determine an in-repo path from the URL; pass --path")
        return _common.USAGE

    # When the URL declares a shape, it must match the artifact type. Skills/hooks are
    # directories; guidelines/memory are single files. MCP accepts either the legacy single
    # JSON file or a directory carrying mcp.json plus supporting docs such as SETUP.md.
    wants_dir = key.type in {"skill", "hook"}
    wants_file = key.type in {"guideline", "memory"}
    if parts.is_file is True and wants_dir:
        print(f"{key.type} {key.name!r} is a directory artifact; use a /tree/ URL, not /blob/")
        return _common.USAGE
    if parts.is_file is False and wants_file:
        print(f"{key.type} {key.name!r} is a single-file artifact; use a /blob/ URL, not /tree/")
        return _common.USAGE

    catalog_root = os.path.abspath(_catalog_root(request))
    tracking_path = os.path.join(catalog_root, UPSTREAMS_FILE)

    existing_catalog: Optional[UpstreamCatalog] = None
    if os.path.exists(tracking_path):
        try:
            loaded = parse_upstreams(fs.read_text(tracking_path))
        except OSError as exc:
            print(f"cannot read {tracking_path}: {exc}")
            return _common.ERROR
        if isinstance(loaded, Err):
            print(loaded.reason)
            return _common.exit_code(loaded)
        existing_catalog = loaded.value
        if key in existing_catalog.entries and not request.force:
            print(
                f"{format_upstream_key(key)} is already tracked; "
                "use 'aart upstream update' (or --force to re-adopt)"
            )
            return _common.USAGE

    # Public github.com stays compact (no host metadata); enterprise hosts carry api_url/web_url.
    web_url = parts.web_url if parts.api_url is not None else None
    source = UpstreamSource(
        kind="github", repo=parts.repo, ref=ref, path=path, api_url=parts.api_url, web_url=web_url
    )

    resolved = resolve_upstream_source(
        UpstreamEntry(key=key, source=source, last_synced=None),
        token=_github_token(),
    )
    if isinstance(resolved, Err):
        print(resolved.reason)
        return _common.exit_code(resolved)
    materialised = resolved.value

    problem = _validate_resolved(materialised)
    if problem is not None:
        print(f"resolved content is not a valid {key.type}: {problem}")
        return _common.USAGE

    dest = _catalog_destination(key, catalog_root, tree=os.path.isdir(materialised.path))
    dest_exists = os.path.exists(dest)
    if dest_exists and not request.force:
        print(f"{os.path.relpath(dest, catalog_root)} already exists; pass --force to overwrite")
        return _common.CONFLICT

    synced_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    new_entry = UpstreamEntry(
        key=key,
        source=source,
        last_synced=UpstreamSync(
            sha=materialised.sha, content_hash=materialised.content_hash, synced_at=synced_at
        ),
    )
    updated_catalog = _upsert_entry(existing_catalog, new_entry)

    if request.dry_run:
        _emit_add(
            request,
            key=key,
            dest=dest,
            catalog_root=catalog_root,
            sha=materialised.sha,
            source=source,
            dry_run=True,
        )
        return _common.OK

    # Vendor the content, then write the tracking file last so a failure never leaves a
    # vendored-but-untracked artifact behind.
    if os.path.isdir(materialised.path):
        if dest_exists:
            fs.remove_path(dest)
        fs.copy_tree(materialised.path, dest)
    else:
        fs.write_atomic(dest, fs.read_bytes(materialised.path))
    fs.write_atomic(tracking_path, dump_upstreams(updated_catalog).encode("utf-8"))

    _emit_add(
        request,
        key=key,
        dest=dest,
        catalog_root=catalog_root,
        sha=materialised.sha,
        source=source,
        dry_run=False,
    )
    return _common.OK


def _upsert_entry(catalog: Optional[UpstreamCatalog], entry: UpstreamEntry) -> UpstreamCatalog:
    entries = dict(catalog.entries) if catalog is not None else {}
    entries[entry.key] = entry
    version = catalog.version if catalog is not None else 1
    return UpstreamCatalog(version=version, entries=entries)


def _emit_add(
    request: Request,
    *,
    key: UpstreamKey,
    dest: str,
    catalog_root: str,
    sha: str,
    source: UpstreamSource,
    dry_run: bool,
) -> None:
    rel_dest = os.path.relpath(dest, catalog_root)
    if request.json:
        _common.print_json(
            {
                "action": "add",
                "dry_run": dry_run,
                "artifact": format_upstream_key(key),
                "type": key.type,
                "name": key.name,
                "repo": source.repo,
                "ref": source.ref,
                "path": source.path,
                "sha": sha,
                "destination": rel_dest,
            }
        )
        return
    print(f"Resolved {source.repo}@{sha} (ref {source.ref})")
    print(f"{'Would vendor' if dry_run else 'Vendored'} {rel_dest}")
    if not dry_run:
        print(f"Tracked  {format_upstream_key(key)} -> {UPSTREAMS_FILE}")


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
    token = _github_token()
    for entry in entries:
        result = resolve_upstream_source(entry, token=token)
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
            descriptor = _mcp_descriptor_path(resolved.path, key.name)
            if descriptor is None:
                return f"missing MCP descriptor mcp.json or {key.name}.json"
            result = catalog_mod.parse_mcp(fs.read_text(descriptor), key.name)
        elif key.type == "memory":
            result = catalog_mod.parse_memory(fs.read_text(resolved.path), key.name)
        else:
            return f"unknown artifact type {key.type!r}"
    except OSError as exc:
        return str(exc)

    if isinstance(result, Err):
        return result.reason
    return None


def _statuses_to_persist(
    statuses: Tuple[UpstreamStatus, ...],
) -> Mapping[UpstreamKey, UpstreamSync]:
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
                "checked": _automation_statuses(statuses, selected),
                "statuses": _status_dicts(statuses, selected),
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
                "updates": _automation_statuses(update_plan.statuses, update_plan.entries),
                "statuses": _status_dicts(update_plan.statuses, update_plan.entries),
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
                "updates": _automation_statuses(update_plan.statuses, update_plan.entries),
                "statuses": _status_dicts(update_plan.statuses, update_plan.entries),
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
                "updates": _automation_statuses(update_plan.statuses, update_plan.entries),
                "statuses": _status_dicts(update_plan.statuses, update_plan.entries),
                "performed": list(performed),
                "updated": updated_count,
                "updated_count": updated_count,
            }
        )
        return

    print(f"Updated {updated_count} upstream artifact{'s' if updated_count != 1 else ''}.")
    for warning in warnings:
        print(f"warning: {warning}")


def _status_dicts(
    statuses: Tuple[UpstreamStatus, ...],
    entries: Tuple[UpstreamEntry, ...],
) -> List[dict]:
    by_key = {entry.key: entry for entry in entries}
    return [_status_to_dict(status, by_key.get(status.key)) for status in statuses]


def _automation_statuses(
    statuses: Tuple[UpstreamStatus, ...],
    entries: Tuple[UpstreamEntry, ...],
) -> List[dict]:
    by_key = {entry.key: entry for entry in entries}
    return [_automation_status_to_dict(status, by_key.get(status.key)) for status in statuses]


def _status_to_dict(status: UpstreamStatus, entry: Optional[UpstreamEntry]) -> dict:
    data = _automation_status_to_dict(status, entry)
    return {
        "key": format_upstream_key(status.key),
        **data,
    }


def _automation_status_to_dict(status: UpstreamStatus, entry: Optional[UpstreamEntry]) -> dict:
    source = entry.source if entry is not None else None
    source_fields = _source_fields(source)
    return {
        "artifact": format_upstream_key(status.key),
        "type": status.key.type,
        "name": status.key.name,
        "state": status.state,
        **source_fields,
        "base_sha": status.base_sha,
        "head_sha": status.head_sha,
        "base_hash": status.base_hash,
        "head_hash": status.head_hash,
        "message": status.message,
    }


def _source_fields(source) -> dict:
    if source is None:
        return {"repo": None, "ref": None, "path": None}

    data = {
        "repo": source.repo,
        "ref": source.ref,
        "path": source.path,
    }
    include_host_fields = (
        source.api_url is not None or source.web_url is not None or "://" in source.repo
    )
    if not include_host_fields:
        return data

    location = resolve_github_location(source)
    if isinstance(location, Err):
        if source.api_url is not None:
            data["api_url"] = source.api_url
        if source.web_url is not None:
            data["web_url"] = source.web_url
        return data

    data["repo"] = location.value.repo
    data["api_url"] = location.value.api_url
    data["web_url"] = location.value.web_url
    return data


def _human_status_line(status: UpstreamStatus) -> str:
    label = format_upstream_key(status.key)
    detail = f" {status.message}" if status.message else ""
    return f"{label}: {status.state}{detail}"


def _mcp_descriptor_path(path: str, name: str) -> Optional[str]:
    if not os.path.isdir(path):
        return path
    candidates = (
        os.path.join(path, "mcp.json"),
        os.path.join(path, f"{name}.json"),
    )
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return None


def _catalog_destination(key: UpstreamKey, catalog_root: str, *, tree: Optional[bool] = None) -> str:
    if key.type == "skill":
        rel = os.path.join("skills", key.name)
    elif key.type == "hook":
        rel = os.path.join("hooks", key.name)
    elif key.type == "guideline":
        rel = os.path.join("guidelines", f"{key.name}.md")
    elif key.type == "mcp":
        if tree is None:
            tree = os.path.isdir(os.path.join(catalog_root, "mcp", key.name))
        rel = os.path.join("mcp", key.name if tree else f"{key.name}.json")
    elif key.type == "memory":
        rel = os.path.join("memory", f"{key.name}.md")
    else:
        rel = os.path.join(str(key.type), key.name)
    return os.path.join(catalog_root, rel)
