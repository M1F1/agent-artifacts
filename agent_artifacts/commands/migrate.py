"""Public 0.1 consumer-state migration command."""

from __future__ import annotations

import json
import os
import sys

from agent_artifacts.application.legacy_state_migration import (
    LegacyStateMigrationRequest,
    build_legacy_migration_candidates,
    parse_source_mappings,
)
from agent_artifacts.application.state_migration import StateMigrationService
from agent_artifacts.configuration.paths import Platform, resolve_config_paths
from agent_artifacts.consumer.runtime import load_local_consumer_service
from agent_artifacts.domain.diagnostics import diagnostic_to_data
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.install_state.paths import install_state_paths
from agent_artifacts.install_state.schema import parse_install_state
from agent_artifacts.io.state_store import LocalStateStore
from agent_artifacts.model import Request

from . import _common


def _error(request: Request, operation: str, result: Err) -> int:
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


def _simple_error(request: Request, message: str) -> int:
    if request.json:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "ok": False,
                    "operation": "migrate.state",
                    "message": message,
                },
                indent=2,
            )
        )
    else:
        print(f"error: {message}")
    return _common.ERROR


def _emit(
    request: Request,
    *,
    status: str,
    changed: bool,
    review_digest: str,
    backup_path: str,
) -> None:
    data = {
        "schema_version": 1,
        "ok": True,
        "operation": "migrate.state",
        "status": status,
        "changed": changed,
        "scope": request.scope,
        "review_digest": review_digest,
        "backup_path": backup_path,
    }
    if request.json:
        print(json.dumps(data, indent=2))
    else:
        print(
            f"state migration: {status}; {'changed' if changed else 'no changes'}; "
            f"backup {backup_path}"
        )
        print(f"review digest: {review_digest}")


def run(request: Request) -> int:
    if request.migration_action != "state" or request.migration_from != "0.1":
        return _simple_error(request, "only explicit state migration from 0.1 is supported")
    scope_problem = _common.validate_scope(request)
    if scope_problem is not None:
        return _simple_error(request, scope_problem.reason)
    mappings = parse_source_mappings(request.source_mappings)
    if isinstance(mappings, Err):
        return _error(request, "migrate.state", mappings)
    project = os.path.abspath(request.project or os.getcwd())
    home = os.path.abspath(request.user_home or os.path.expanduser("~"))
    platform = Platform.DARWIN if sys.platform == "darwin" else Platform.LINUX
    config_paths = resolve_config_paths(
        platform,
        home=home,
        xdg_config_home=os.environ.get("XDG_CONFIG_HOME"),
        xdg_data_home=os.environ.get("XDG_DATA_HOME"),
        xdg_cache_home=os.environ.get("XDG_CACHE_HOME"),
    )
    paths = install_state_paths(
        request.scope,
        project_root=project,
        user_home=home,
        data_root=config_paths.data_root,
    )
    service = StateMigrationService(LocalStateStore())
    current = service.current_receipt(paths)
    if isinstance(current, Err):
        return _error(request, "migrate.state", current)
    if request.rollback:
        if current.value is None:
            return _simple_error(
                request, "no completed 0.1 state migration is available to roll back"
            )
        rolled_back = service.rollback(current.value)
        if isinstance(rolled_back, Err):
            return _error(request, "migrate.state.rollback", rolled_back)
        _emit(
            request,
            status="rolled-back",
            changed=rolled_back.value.changed,
            review_digest=str(rolled_back.value.review_digest),
            backup_path=current.value.plan.backup_path,
        )
        return _common.OK
    if current.value is not None:
        _emit(
            request,
            status="already-migrated",
            changed=False,
            review_digest=str(current.value.plan.review_digest),
            backup_path=current.value.plan.backup_path,
        )
        return _common.OK
    loaded = load_local_consumer_service(project=project, user_home=home)
    if isinstance(loaded, Err):
        return _error(request, "migrate.state", loaded)
    consumer = loaded.value
    legacy = service.store.read(paths.legacy_path)
    if isinstance(legacy, Err):
        return _error(request, "migrate.state", legacy)
    if legacy.value is None:
        return _simple_error(
            request, f"legacy installation state does not exist at {paths.legacy_path}"
        )
    if isinstance(parse_install_state(legacy.value, path=paths.legacy_path), Ok):
        return _simple_error(
            request,
            "installation state is already v2 but has no matching migration receipt; "
            "refusing to invent rollback evidence",
        )
    candidates = build_legacy_migration_candidates(
        LegacyStateMigrationRequest(legacy.value, request.scope, mappings.value),
        consumer.context,
        consumer.ports,
    )
    if isinstance(candidates, Err):
        return _error(request, "migrate.state", candidates)
    prepared = service.prepare(paths, candidates.value)
    if isinstance(prepared, Err):
        return _error(request, "migrate.state", prepared)
    if request.dry_run:
        _emit(
            request,
            status="planned",
            changed=True,
            review_digest=str(prepared.value.review_digest),
            backup_path=prepared.value.backup_path,
        )
        return _common.OK
    applied = service.apply(prepared.value)
    if isinstance(applied, Err):
        return _error(request, "migrate.state", applied)
    _emit(
        request,
        status="applied" if applied.value.changed else "already-migrated",
        changed=applied.value.changed,
        review_digest=str(applied.value.plan.review_digest),
        backup_path=applied.value.plan.backup_path,
    )
    return _common.OK


__all__ = ["run"]
