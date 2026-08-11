"""Non-interactive configuration and health commands for canonical source origins.

``source add`` is intentionally an agent-facing transactional boundary: raw input is parsed by
the strict configuration schema, policy is reviewed through the shared addition planner, a fresh
source snapshot is synchronized and validated, and only then is the user configuration written.
No interactive TUI code is invoked by this module.
"""

from __future__ import annotations

import json
import time

from agent_artifacts.application.configuration import save_user_configuration_for_source_management
from agent_artifacts.application.source_management import finalize_source_addition
from agent_artifacts.application.sources import SourceStatusRequest, source_status
from agent_artifacts.configuration.model import (
    ConfiguredSource,
    OrganizationPolicy,
    SourceKind,
    UserConfiguration,
)
from agent_artifacts.configuration.policy import redact_text
from agent_artifacts.configuration.schema import configured_source_from_input
from agent_artifacts.domain.diagnostics import (
    Diagnostic,
    DiagnosticCode,
    Severity,
    diagnostic_to_data,
)
from agent_artifacts.domain.identifiers import SourceAlias
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.io.source_migration import (
    apply_source_store_migration,
    existing_source_directories,
    stored_schema_version,
)
from agent_artifacts.io.source_store import read_current_source
from agent_artifacts.model import Request
from agent_artifacts.sources.migration import plan_source_store_migration
from agent_artifacts.sources.model import (
    CurrentSourceRequest,
    HealthStatus,
    SourceHealth,
    source_instance_id,
    source_store_paths,
)
from agent_artifacts.sources.runtime import sync_configured_source
from agent_artifacts.tui_sources import build_source_stage, plan_source_addition

from . import _common
from ._configured_runtime import ConfiguredRuntime, load_runtime_configuration

_SOURCE_OPERATION = "source.add"
_LIST_OPERATION = "source.list"
_SYNC_OPERATION = "source.sync"
_HEALTH_OPERATION = "source.health"
_DOCTOR_OPERATION = "source.doctor"


def _failure(code: str, message: str, *remediation: str) -> Err:
    return Err(
        (
            Diagnostic(
                DiagnosticCode(code),
                Severity.ERROR,
                redact_text(message),
                remediation=tuple(remediation),
            ),
        )
    )


def _emit_error(request: Request, operation: str, result: Err) -> int:
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


def _source_health(
    source: ConfiguredSource,
    runtime: ConfiguredRuntime,
    *,
    now: int,
) -> SourceHealth:
    paths = source_store_paths(runtime.paths.data_root, source_instance_id(source))
    return source_status(
        SourceStatusRequest(
            CurrentSourceRequest(paths, source.alias),
            now,
            runtime.loaded.user_configuration.sync.max_age_seconds,
        ),
        read_current_source,
    )


def _health_by_alias(runtime: ConfiguredRuntime, *, now: int) -> dict[SourceAlias, SourceHealth]:
    return {
        source.alias: _source_health(source, runtime, now=now)
        for source in runtime.loaded.user_configuration.sources
    }


def _source_data(
    source: ConfiguredSource,
    health: SourceHealth,
    *,
    default_registry,
) -> dict[str, object]:
    current = health.current
    return {
        "alias": source.alias.value,
        "kind": source.kind.value,
        "location": redact_text(source.location),
        "ref": None if source.ref is None else redact_text(source.ref),
        "enabled": source.enabled,
        "default": source.alias == default_registry,
        "health": health.status.value,
        "age_seconds": health.age_seconds,
        "source_id": None if current is None else current.declared_source_id.value,
        "resolved_revision": None if current is None else current.candidate.resolved_revision,
        "snapshot_digest": (None if current is None else str(current.candidate.snapshot_digest)),
        "diagnostics": [diagnostic_to_data(item) for item in health.diagnostics],
    }


def _parse_add_source(request: Request) -> Result[ConfiguredSource]:
    if (
        request.source_alias is None
        or request.source_kind is None
        or request.source_location is None
    ):
        return _failure("config-invalid", "source add requires alias, kind, and location")
    try:
        kind = SourceKind(request.source_kind)
    except ValueError:
        return _failure("config-invalid", "source kind has an unsupported value")
    return configured_source_from_input(
        request.source_alias,
        kind,
        request.source_location,
        request.ref,
    )


def _review_changed(
    runtime: ConfiguredRuntime,
    expected_before: UserConfiguration,
    expected_policy: OrganizationPolicy,
) -> Result[None]:
    if (
        runtime.loaded.user_configuration != expected_before
        or runtime.loaded.effective.policy != expected_policy
    ):
        return _failure(
            "source-selection-invalid",
            "source configuration or organization policy changed after Review",
            "retry source add and review the current configuration",
        )
    return Ok(None)


def _recovery_error() -> Err:
    return _failure(
        "config-invalid",
        "user configuration is invalid and must be recovered before adding a source",
        "recover the configuration, then retry source add",
    )


def _add(request: Request) -> int:
    parsed = _parse_add_source(request)
    if isinstance(parsed, Err):
        return _emit_error(request, _SOURCE_OPERATION, parsed)
    runtime = load_runtime_configuration(request, content_required=False)
    if isinstance(runtime, Err):
        return _emit_error(request, _SOURCE_OPERATION, runtime)
    if runtime.value.loaded.recovery is not None:
        return _emit_error(request, _SOURCE_OPERATION, _recovery_error())
    now = int(time.time())
    view = build_source_stage(
        runtime.value.loaded.user_configuration,
        runtime.value.loaded.effective.policy,
        _health_by_alias(runtime.value, now=now),
        first_run=runtime.value.loaded.first_run is not None,
    )
    if isinstance(view, Err):
        return _emit_error(request, _SOURCE_OPERATION, view)
    planned = plan_source_addition(
        view.value,
        parsed.value,
        make_default=(
            request.source_make_default
            if request.source_make_default is not None
            else (
                parsed.value.is_registry
                and not any(
                    configured.is_registry
                    for configured in runtime.value.loaded.user_configuration.sources
                )
            )
        ),
    )
    if isinstance(planned, Err):
        return _emit_error(request, _SOURCE_OPERATION, planned)

    # No configuration write is reachable until a fresh immutable snapshot validates.
    synchronized = sync_configured_source(parsed.value, data_root=runtime.value.paths.data_root)
    if isinstance(synchronized, Err):
        return _emit_error(request, _SOURCE_OPERATION, synchronized)

    # Fetching may take time.  Fail closed if an actor changed config or policy after Review.
    current = load_runtime_configuration(request, content_required=False)
    if isinstance(current, Err):
        return _emit_error(request, _SOURCE_OPERATION, current)
    if current.value.loaded.recovery is not None:
        return _emit_error(request, _SOURCE_OPERATION, _recovery_error())
    unchanged = _review_changed(current.value, planned.value.before, planned.value.policy)
    if isinstance(unchanged, Err):
        return _emit_error(request, _SOURCE_OPERATION, unchanged)
    finalized = finalize_source_addition(
        planned.value,
        lambda desired, policy: save_user_configuration_for_source_management(
            desired,
            policy,
            current.value.paths,
            current.value.ports,
        ),
    )
    if isinstance(finalized, Err):
        return _emit_error(request, _SOURCE_OPERATION, finalized)

    payload = {
        "schema_version": 1,
        "ok": True,
        "operation": _SOURCE_OPERATION,
        "changed": finalized.value.changed,
        "source": _source_data(
            parsed.value,
            SourceHealth(
                # A just-published current snapshot is necessarily current at the command's
                # observation point; preserve diagnostics emitted by synchronization.
                status=HealthStatus.HEALTHY,
                age_seconds=0,
                current=synchronized.value.current,
                diagnostics=synchronized.value.diagnostics,
            ),
            default_registry=planned.value.after.default_registry,
        ),
        "sync": {
            "disposition": synchronized.value.disposition.value,
            "source_id": synchronized.value.current.declared_source_id.value,
            "resolved_revision": synchronized.value.current.candidate.resolved_revision,
            "snapshot_digest": str(synchronized.value.current.candidate.snapshot_digest),
        },
    }
    if request.json:
        print(json.dumps(payload, indent=2))
    else:
        print(
            f"source added: {parsed.value.alias.value}; "
            f"snapshot {synchronized.value.disposition.value}; "
            f"default={'yes' if planned.value.after.default_registry == parsed.value.alias else 'no'}"
        )
    return _common.OK


def _list(request: Request) -> int:
    runtime = load_runtime_configuration(request, content_required=False)
    if isinstance(runtime, Err):
        return _emit_error(request, _LIST_OPERATION, runtime)
    if runtime.value.loaded.recovery is not None:
        return _emit_error(
            request,
            _LIST_OPERATION,
            _failure(
                "config-invalid",
                "user configuration is invalid; source health cannot be reported safely",
                "recover the configuration, then retry source list",
            ),
        )
    now = int(time.time())
    items = tuple(
        _source_data(
            source,
            _source_health(source, runtime.value, now=now),
            default_registry=runtime.value.loaded.user_configuration.default_registry,
        )
        for source in runtime.value.loaded.user_configuration.sources
    )
    payload = {
        "schema_version": 1,
        "ok": True,
        "operation": _LIST_OPERATION,
        "sources": items,
    }
    if request.json:
        print(json.dumps(payload, indent=2))
    elif not items:
        print("No configured sources. Add one with `aart source add --help`.")
    else:
        for item in items:
            state = "default" if item["default"] else "configured"
            print(f"{item['alias']} [{item['kind']}] {item['health']}; {state}; {item['location']}")
    return _common.OK


def _selected_sources(
    runtime: ConfiguredRuntime, alias: str | None
) -> Result[tuple[ConfiguredSource, ...]]:
    """Resolve the requested aliases without ever creating or renaming a source."""

    sources = runtime.loaded.user_configuration.sources
    if alias is None:
        return Ok(tuple(source for source in sources if source.enabled))
    selected = tuple(source for source in sources if source.alias.value == alias)
    if not selected:
        return _failure(
            "source-not-configured",
            f"no configured source has alias {alias}",
            "run `aart source list --json` to see configured aliases",
        )
    return Ok(selected)


def _sync(request: Request) -> int:
    runtime = load_runtime_configuration(request, content_required=False)
    if isinstance(runtime, Err):
        return _emit_error(request, _SYNC_OPERATION, runtime)
    if runtime.value.loaded.recovery is not None:
        return _emit_error(request, _SYNC_OPERATION, _recovery_error())
    selected = _selected_sources(runtime.value, request.source_alias)
    if isinstance(selected, Err):
        return _emit_error(request, _SYNC_OPERATION, selected)

    results: list[dict] = []
    # Human rendering reads these typed locals rather than the heterogeneous JSON payload.
    lines: list[str] = []
    failed = False
    for source in selected.value:
        # Synchronizing never writes user configuration and never changes source identity: it
        # refreshes the managed snapshot for an already-configured origin and ref.
        synchronized = sync_configured_source(source, data_root=runtime.value.paths.data_root)
        if isinstance(synchronized, Err):
            failed = True
            results.append(
                {
                    "alias": source.alias.value,
                    "ok": False,
                    "diagnostics": [diagnostic_to_data(item) for item in synchronized.diagnostics],
                }
            )
            lines.append(f"{source.alias.value}: failed")
            lines.extend(
                f"  {item.severity.value}: {item.message}" for item in synchronized.diagnostics
            )
            continue
        current = synchronized.value.current
        results.append(
            {
                "alias": source.alias.value,
                "ok": True,
                "disposition": synchronized.value.disposition.value,
                "source_id": current.declared_source_id.value,
                "resolved_revision": current.candidate.resolved_revision,
                "snapshot_digest": str(current.candidate.snapshot_digest),
            }
        )
        lines.append(
            f"{source.alias.value}: {synchronized.value.disposition.value} "
            f"({current.candidate.resolved_revision})"
        )
    payload = {
        "schema_version": 1,
        "ok": not failed,
        "operation": _SYNC_OPERATION,
        "sources": results,
    }
    if request.json:
        print(json.dumps(payload, indent=2))
    elif not results:
        print("No enabled sources to synchronize.")
    else:
        for line in lines:
            print(line)
    return _common.ERROR if failed else _common.OK


def _pending_store_migration(runtime: ConfiguredRuntime) -> bool:
    """Whether a legacy source directory is still waiting to be rebound.

    Reported, never acted on: migrating moves user data and stays an explicit `doctor --apply`.
    """

    data_root = runtime.paths.data_root
    planned = plan_source_store_migration(
        runtime.loaded.user_configuration,
        existing=existing_source_directories(data_root),
        stored_schema_version=stored_schema_version(data_root),
    )
    # A conflicting or ambiguous store is also unmigrated; `doctor` explains which.
    return True if isinstance(planned, Err) else bool(planned.value.rebinds)


def _health(request: Request) -> int:
    runtime = load_runtime_configuration(request, content_required=False)
    if isinstance(runtime, Err):
        return _emit_error(request, _HEALTH_OPERATION, runtime)
    if runtime.value.loaded.recovery is not None:
        return _emit_error(request, _HEALTH_OPERATION, _recovery_error())
    selected = _selected_sources(runtime.value, request.source_alias)
    if isinstance(selected, Err):
        return _emit_error(request, _HEALTH_OPERATION, selected)
    now = int(time.time())
    items = []
    degraded = False
    for source in runtime.value.loaded.user_configuration.sources:
        if source not in selected.value and request.source_alias is not None:
            continue
        health = _source_health(source, runtime.value, now=now)
        current = health.current
        if health.status is not HealthStatus.HEALTHY and source.enabled:
            degraded = True
        items.append(
            {
                "alias": source.alias.value,
                "kind": source.kind.value,
                "ref": source.ref,
                "enabled": source.enabled,
                "health": health.status.value,
                "instance_id": source_instance_id(source).value,
                "resolved_revision": (
                    None if current is None else current.candidate.resolved_revision
                ),
                "published_at": (None if current is None else current.published_at_epoch_seconds),
                "age_seconds": (
                    None if current is None else max(0, now - current.published_at_epoch_seconds)
                ),
            }
        )
    # After upgrading to ref-aware storage a source resolves to a directory that does not exist
    # yet, so it reads as "missing" for no visible reason.  Say so here, where someone diagnosing
    # exactly that will look, instead of leaving them with an unexplained empty marketplace.
    pending_migration = _pending_store_migration(runtime.value)
    payload = {
        "schema_version": 1,
        "ok": not degraded,
        "operation": _HEALTH_OPERATION,
        "max_age_seconds": runtime.value.loaded.effective.configuration.sync.max_age_seconds,
        "pending_store_migration": pending_migration,
        "sources": items,
    }
    if request.json:
        print(json.dumps(payload, indent=2))
    elif not items:
        print("No configured sources. Add one with `aart source add --help`.")
    else:
        for item in items:
            age = "never synchronized" if item["age_seconds"] is None else f"{item['age_seconds']}s"
            print(
                f"{item['alias']} [{item['kind']}@{item['ref'] or 'local'}] {item['health']}; {age}"
            )
        if pending_migration:
            print(
                "note: this store still uses the pre-ref-aware layout; "
                "run `aart source doctor` to review the migration."
            )
    return _common.ERROR if degraded else _common.OK


def _doctor(request: Request) -> int:
    runtime = load_runtime_configuration(request, content_required=False)
    if isinstance(runtime, Err):
        return _emit_error(request, _DOCTOR_OPERATION, runtime)
    if runtime.value.loaded.recovery is not None:
        return _emit_error(request, _DOCTOR_OPERATION, _recovery_error())
    data_root = runtime.value.paths.data_root
    existing = existing_source_directories(data_root)
    version = stored_schema_version(data_root)
    planned = plan_source_store_migration(
        runtime.value.loaded.user_configuration,
        existing=existing,
        stored_schema_version=version,
    )
    if isinstance(planned, Err):
        return _emit_error(request, _DOCTOR_OPERATION, planned)
    plan = planned.value
    payload = {
        "schema_version": 1,
        "ok": True,
        "operation": _DOCTOR_OPERATION,
        "store_schema_version": version,
        "target_schema_version": plan.schema_version,
        "migration_required": plan.required,
        "applied": False,
        "rebinds": [
            {
                "alias": rebind.alias.value,
                "action": rebind.action.value,
                "from": rebind.source_directory,
                "to": rebind.target_directory,
            }
            for rebind in plan.rebinds
        ],
    }
    if request.apply and plan.required:
        applied = apply_source_store_migration(plan, data_root=data_root)
        if isinstance(applied, Err):
            return _emit_error(request, _DOCTOR_OPERATION, applied)
        payload["applied"] = True
        payload["rebound"] = list(applied.value)
    if request.json:
        print(json.dumps(payload, indent=2))
    elif not plan.required:
        print("Source store layout is current; no migration is needed.")
    elif not request.apply:
        print(f"Source store migration required (v{version or 1} -> v{plan.schema_version}).")
        for rebind in plan.rebinds:
            print(
                f"  - {rebind.alias.value}: {rebind.source_directory} -> {rebind.target_directory}"
            )
        print("Re-run with --apply to perform this exact migration.")
    else:
        print(f"Source store migrated to v{plan.schema_version}.")
    return _common.OK


def run(request: Request) -> int:
    """Run one non-interactive configured-source command."""

    if request.source_action == "add":
        return _add(request)
    if request.source_action == "list":
        return _list(request)
    if request.source_action == "sync":
        return _sync(request)
    if request.source_action == "health":
        return _health(request)
    if request.source_action == "doctor":
        return _doctor(request)
    return _emit_error(
        request,
        "source",
        _failure("config-invalid", "unsupported source command action"),
    )


__all__ = ["run"]
