"""Setup application service: installed source -> plan -> consent -> apply -> state."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import replace
from typing import Callable, Mapping, Optional, Sequence

from ..io import fs
from ..model import (
    Artifact,
    Err,
    Ok,
    Request,
    SetupQueueItem,
    SetupState,
    SetupStateRecord,
)
from ..setup import (
    dump_setup_state,
    incomplete_records,
    mark_unstarted_skipped,
    parse_setup_state,
    plan_setup,
    recovery_messages,
    render_setup_review,
    setup_state_path,
    upsert_setup_record,
)
from ..setup_runtime import SetupRuntime, apply_setup_plan, production_runtime, rollback_record
from ..source import open_source
from ..subscriptions import request_for_subscription
from . import _common

ReadFn = Callable[[str], str]
WriteFn = Callable[[str], None]


def _load_state(root: str) -> SetupState | Err:
    path = setup_state_path(root)
    if not fs.exists(path):
        return SetupState()
    try:
        parsed = parse_setup_state(fs.read_text(path))
    except OSError as exc:
        return Err(f"cannot read setup state at {path}: {exc}", code=1)
    return parsed.value if isinstance(parsed, Ok) else parsed


def _save_state(root: str, state: SetupState) -> Optional[Err]:
    path = setup_state_path(root)
    try:
        fs.write_atomic(path, (dump_setup_state(state) + "\n").encode("utf-8"))
        os.chmod(path, 0o600)
        return None
    except OSError as exc:
        return Err(f"cannot write setup state at {path}: {exc}")


def _write_receipt(path: str, record: SetupStateRecord) -> None:
    fs.write_atomic(
        path,
        (dump_setup_state(SetupState((record,))) + "\n").encode("utf-8"),
    )
    os.chmod(path, 0o600)


def _compensate_persistence_failure(
    root: str,
    prior_state: SetupState,
    record: SetupStateRecord,
    runtime: SetupRuntime,
) -> tuple[SetupStateRecord, bool]:
    """Best-effort compensation plus a second, bounded attempt to persist recovery state."""

    recovered = (
        rollback_record(record, runtime)
        if record.status == "configured" and record.receipt
        else record
    )
    if recovered.receipt_path:
        try:
            _write_receipt(recovered.receipt_path, recovered)
        except OSError:
            pass
    recovery_state = upsert_setup_record(prior_state, recovered)
    persisted = _save_state(root, recovery_state) is None
    return recovered, persisted


def _record_payload(record: SetupStateRecord) -> dict:
    return {
        "artifact": f"{record.artifact_type}/{record.artifact_name}",
        "profile": record.profile,
        "scope": record.scope,
        "status": record.status,
        "detail": record.detail,
        "source": record.source_label,
        "installer_path": record.installer_path,
        "installer_hash": record.installer_hash,
        "custom_hash": record.custom_hash,
        "schema_version": record.schema_version,
        "protocol_version": record.protocol_version,
        "plan_hash": record.plan_hash,
        "retry_command": record.retry_command,
        "rollback_command": record.rollback_command,
        "receipt_path": record.receipt_path,
        "recovery": list(recovery_messages(record)),
    }


def _plan_payload(plan) -> dict:
    return {
        "artifact": f"{plan.item.artifact_type}/{plan.item.artifact_name}",
        "profile": plan.item.profile,
        "scope": plan.item.scope,
        "source": plan.item.source_label,
        "installer_path": plan.item.installer.descriptor_path,
        "installer_hash": plan.item.installer.descriptor_hash,
        "custom_hash": plan.item.installer.custom_hash,
        "plan_hash": plan.plan_hash,
        "preflight_status": plan.preflight_status,
        "effects": [
            {
                "step": effect.step_id,
                "module": effect.module,
                "capability": effect.capability,
                "summary": effect.summary,
                "target": effect.target,
                "argv": list(effect.argv),
                "reversible": effect.reversible,
            }
            for effect in plan.effects
        ],
    }


def _render_records(records: Sequence[SetupStateRecord], write: WriteFn) -> None:
    if not records:
        write("No setup records.")
        return
    for record in records:
        write(
            f"{record.artifact_type}/{record.artifact_name}@{record.profile}: "
            f"{record.status} — {record.detail}"
        )
        if record.retry_command:
            write(f"  Retry: {record.retry_command}")
        if record.rollback_command:
            write(f"  Rollback: {record.rollback_command}")
        for message in recovery_messages(record):
            write(f"  Recovery: {message}")


def _matches_name(record: SetupStateRecord, names: Sequence[str]) -> bool:
    if not names:
        return True
    key = f"{record.artifact_type}/{record.artifact_name}"
    return key in names or record.artifact_name in names


def _select_state_records(state: SetupState, request: Request) -> tuple[SetupStateRecord, ...]:
    records = state.records
    if request.setup_action == "retry":
        records = incomplete_records(records)
    return tuple(
        record
        for record in records
        if record.scope == request.scope
        and _matches_name(record, request.names)
        and (not request.profiles or record.profile in request.profiles)
    )


def _artifact_for_key(catalog, key: str) -> Artifact | Err:
    if "/" in key:
        artifact_type, name = key.split("/", 1)
        artifact = catalog.artifacts.get((artifact_type, name))
        if artifact is None:
            return Err(f"unknown setup artifact {key!r}", code=2)
        return artifact
    matches = [artifact for (_type, name), artifact in catalog.artifacts.items() if name == key]
    if len(matches) != 1:
        return Err(f"setup artifact {key!r} must resolve to exactly one TYPE/NAME", code=2)
    return matches[0]


def _queue_from_installed(
    request: Request, retry_records: Sequence[SetupStateRecord]
) -> tuple | Err:
    manifest_result = _common.load_manifest(request)
    if isinstance(manifest_result, Err):
        return manifest_result
    manifest = manifest_result.value
    names = request.names
    profiles = request.profiles
    if request.setup_action == "retry":
        if not names:
            names = tuple(
                dict.fromkeys(
                    f"{record.artifact_type}/{record.artifact_name}" for record in retry_records
                )
            )
        if not profiles:
            profiles = tuple(dict.fromkeys(record.profile for record in retry_records))
    if not names:
        return Err("no setup artifact selected", code=2)
    if not profiles:
        return Err("no profile selected (use --profile NAME[,NAME])", code=2)

    selected_entries = tuple(
        entry
        for entry in manifest.installed
        if entry.profile in profiles
        and any(name in (entry.artifact, f"{entry.type}/{entry.artifact}") for name in names)
    )
    if not selected_entries:
        return Err("setup can run only for matching installed artifact/profile entries", code=2)
    if request.setup_action == "retry":
        expected = {
            (record.artifact_name, record.profile)
            for record in retry_records
            if _matches_name(record, names) and record.profile in profiles
        }
    else:
        expected = {(name.split("/", 1)[-1], profile) for name in names for profile in profiles}
    present = {(entry.artifact, entry.profile) for entry in selected_entries}
    missing = expected - present
    if missing:
        rendered = ", ".join(f"{name}@{profile}" for name, profile in sorted(missing))
        return Err(f"setup requires installed artifact/profile entries: {rendered}", code=2)

    source_request = request
    if request.source_dir is None and request.repo is None and request.version is None:
        subscriptions = tuple(dict.fromkeys(entry.subscription for entry in selected_entries))
        if len(subscriptions) != 1 or subscriptions[0] is None:
            return Err(
                "selected installed entries must share a recorded catalog subscription; "
                "narrow the selection or provide --source/--repo",
                code=2,
            )
        source_request = request_for_subscription(request, subscriptions[0])
        if subscriptions[0].kind == "github":
            installed_sources = tuple(dict.fromkeys(entry.source for entry in selected_entries))
            if len(installed_sources) != 1 or ":" not in installed_sources[0]:
                return Err("installed GitHub source identity is missing its exact commit", code=5)
            _kind, installed_sha = installed_sources[0].split(":", 1)
            source_request = replace(source_request, version=installed_sha)
    source_result = open_source(source_request)
    if isinstance(source_result, Err):
        return source_result
    source = source_result.value
    catalog_result = source.catalog()
    if isinstance(catalog_result, Err):
        return catalog_result
    catalog = catalog_result.value

    artifacts = []
    for name in names:
        artifact = _artifact_for_key(catalog, name)
        if isinstance(artifact, Err):
            return artifact
        if artifact.setup is None:
            return Err(f"{artifact.type}/{artifact.name} does not declare setup", code=2)
        artifacts.append(artifact)
    queue = []
    queued = set()
    for artifact in artifacts:
        for profile in profiles:
            entry = next(
                (
                    candidate
                    for candidate in selected_entries
                    if candidate.type == artifact.type
                    and candidate.artifact == artifact.name
                    and candidate.profile == profile
                ),
                None,
            )
            if entry is None:
                continue
            pair = (artifact.type, artifact.name, profile, request.scope)
            if pair in queued or (
                request.setup_action == "retry" and (artifact.name, profile) not in expected
            ):
                continue
            queued.add(pair)
            installed_identity = entry.source.split(":", 1)[-1]
            resolved_identity = source.label().split(":", 1)[-1]
            if installed_identity != resolved_identity:
                return Err(
                    f"source identity changed for {artifact.type}/{artifact.name}@{profile}: "
                    f"installed {entry.source}, resolved {source.label()}",
                    code=4,
                )
            installer = artifact.setup
            assert installer is not None
            queue.append(
                SetupQueueItem(
                    artifact.type,
                    artifact.name,
                    profile,
                    request.scope,
                    entry.source,
                    source.root,
                    installer,
                )
            )
    return tuple(queue)


def _confirm_effect(effect, read: ReadFn, write: WriteFn) -> bool:
    write(
        f"Apply {effect.module}: {effect.summary} "
        f"[{'reversible' if effect.reversible else 'not automatically reversible'}]"
    )
    try:
        answer = read("Approve this exact effect? [y/N]: ").strip().lower()
    except EOFError:
        return False
    return answer in ("y", "yes")


def _receipt_matches_plan(receipt: Mapping[str, object], plan) -> bool:
    step_id = receipt.get("step_id")
    effect = next((candidate for candidate in plan.effects if candidate.step_id == step_id), None)
    if effect is None or receipt.get("module") != effect.module:
        return False
    if "path" in receipt and receipt.get("path") != effect.target:
        return False
    if effect.module == "macos-keychain.store@1":
        return receipt.get("service") == effect.config.get("service") and receipt.get(
            "account"
        ) == effect.config.get("account")
    if effect.module in ("shell.env-from-keychain@1", "file.managed-block@1"):
        return receipt.get("marker") == effect.config.get("marker")
    if effect.module == "json.managed-merge@1":
        configured_path = effect.config.get("path")
        return (
            receipt.get("json_path") == list(configured_path)
            if isinstance(configured_path, tuple)
            else False
        )
    if effect.module == "directory.create@1":
        return receipt.get("path") == effect.target
    if effect.module == "docker.pull@1":
        return receipt.get("image") == effect.target
    if effect.module == "custom.install@1":
        run_dir = str(receipt.get("run_dir", ""))
        expected_runs = os.path.join(plan.run_root, ".agent-artifacts", "setup-runs")
        try:
            inside_runs = os.path.commonpath((expected_runs, run_dir)) == expected_runs
        except ValueError:
            inside_runs = False
        return (
            receipt.get("script") == effect.target
            and receipt.get("script_hash") == effect.config.get("script_hash")
            and receipt.get("plan_hash") == plan.plan_hash
            and inside_runs
        )
    return effect.module in ("restart.notice@1", "command.verify@1")


def _validate_rollback_records(
    request: Request,
    records: Sequence[SetupStateRecord],
    runtime: SetupRuntime,
) -> Optional[Err]:
    root = _common.manifest_root(request)
    home = _common.user_root(request)
    for record in records:
        lookup = replace(
            request,
            setup_action="run",
            names=(f"{record.artifact_type}/{record.artifact_name}",),
            profiles=(record.profile,),
        )
        queue = _queue_from_installed(lookup, ())
        if isinstance(queue, Err) or len(queue) != 1:
            reason = queue.reason if isinstance(queue, Err) else "installed setup item is missing"
            return Err(f"cannot validate rollback receipt: {reason}", code=4)
        plan = plan_setup(
            queue[0],
            target_root=root,
            home_root=home,
            run_root=root,
            platform=runtime.platform,
        )
        if (
            record.source_label != plan.item.source_label
            or record.installer_hash != plan.item.installer.descriptor_hash
            or record.plan_hash != plan.plan_hash
            or not all(_receipt_matches_plan(receipt, plan) for receipt in record.receipt)
        ):
            return Err(
                f"rollback receipt no longer matches the reviewed plan for "
                f"{record.artifact_type}/{record.artifact_name}@{record.profile}",
                code=4,
            )
    return None


def run_queue(
    queue: Sequence[SetupQueueItem],
    *,
    scope_root: str,
    target_root: Optional[str] = None,
    request: Request,
    runtime: Optional[SetupRuntime] = None,
    read: ReadFn = input,
    write: WriteFn = print,
) -> tuple[SetupStateRecord, ...] | Err:
    """Run and durably record each item, continuing unless explicitly configured to stop."""

    state = _load_state(scope_root)
    if isinstance(state, Err):
        return state
    adapter = runtime or production_runtime()
    completed: list[SetupStateRecord] = []
    for index, item in enumerate(queue):
        prior_state = state
        plan = plan_setup(
            item,
            target_root=scope_root,
            home_root=target_root or scope_root,
            run_root=scope_root,
            platform=adapter.platform,
        )
        for line in render_setup_review(plan):
            write(line)
        consent = (
            (lambda _effect: True)
            if request.yes
            else (lambda effect: _confirm_effect(effect, read, write))
        )
        applied_record = apply_setup_plan(plan, adapter, consent=consent)
        record = applied_record
        if record.status == "already_configured":
            previous = next(
                (
                    existing
                    for existing in state.records
                    if (
                        existing.artifact_type,
                        existing.artifact_name,
                        existing.profile,
                        existing.scope,
                    )
                    == (item.artifact_type, item.artifact_name, item.profile, item.scope)
                ),
                None,
            )
            if previous is not None and previous.receipt:
                # An idempotent verification must not erase the ownership proof from the run
                # that actually created effects; rollback remains available and scoped.
                record = replace(
                    previous,
                    status="already_configured",
                    detail=record.detail,
                    started_at=record.started_at,
                    finished_at=record.finished_at,
                    exit_status=record.exit_status,
                )
        if record.receipt and not record.receipt_path:
            receipt_dir = os.path.join(
                scope_root,
                ".agent-artifacts",
                "setup-runs",
                plan.plan_hash[:16],
            )
            receipt_path = os.path.join(receipt_dir, "receipt.json")
            try:
                os.makedirs(receipt_dir, mode=0o700, exist_ok=True)
                os.chmod(receipt_dir, 0o700)
                record = replace(record, receipt_path=receipt_path)
                _write_receipt(receipt_path, record)
            except OSError as exc:
                recovered, persisted = _compensate_persistence_failure(
                    scope_root, prior_state, record, adapter
                )
                recovery = (
                    "rollback completed" if recovered.status == "skipped" else "rollback incomplete"
                )
                durability = (
                    "recovery state persisted" if persisted else "recovery state not persisted"
                )
                return Err(
                    f"cannot write setup receipt at {receipt_path}: {exc}; {recovery}; {durability}"
                )
        state = upsert_setup_record(state, record)
        save_error = _save_state(scope_root, state)
        if save_error is not None:
            recovered, persisted = _compensate_persistence_failure(
                scope_root, prior_state, record, adapter
            )
            recovery = (
                "rollback completed" if recovered.status == "skipped" else "rollback incomplete"
            )
            durability = "recovery state persisted" if persisted else "recovery state not persisted"
            return Err(f"{save_error.reason}; {recovery}; {durability}")
        completed.append(record)
        should_stop = request.stop_on_failure
        if (
            record.status not in ("configured", "already_configured")
            and not should_stop
            and not request.yes
            and index + 1 < len(queue)
        ):
            try:
                answer = read("Continue with the remaining setup installers? [Y/n]: ")
                should_stop = answer.strip().lower() in ("n", "no")
            except (EOFError, KeyboardInterrupt):
                should_stop = True
        if record.status not in ("configured", "already_configured") and should_stop:
            skipped = mark_unstarted_skipped(
                queue[index + 1 :], detail=f"Stopped after {record.status}"
            )
            for skipped_record in skipped:
                state = upsert_setup_record(state, skipped_record)
                completed.append(skipped_record)
            save_error = _save_state(scope_root, state)
            if save_error is not None:
                return save_error
            break
    return tuple(completed)


def _run_status(request: Request, *, write: WriteFn) -> int:
    state = _load_state(_common.manifest_root(request))
    if isinstance(state, Err):
        print(state.reason, file=sys.stderr)
        return state.code
    records = _select_state_records(state, request)
    if request.json:
        write(json.dumps({"records": [_record_payload(record) for record in records]}, indent=2))
    else:
        _render_records(records, write)
    return 0


def _run_rollback(
    request: Request,
    *,
    runtime: Optional[SetupRuntime],
    read: ReadFn,
    write: WriteFn,
) -> int:
    if not request.profiles:
        print("setup rollback requires --profile", file=sys.stderr)
        return 2
    root = _common.manifest_root(request)
    state = _load_state(root)
    if isinstance(state, Err):
        print(state.reason, file=sys.stderr)
        return state.code
    records = _select_state_records(state, request)
    if not records:
        print("no matching setup receipt", file=sys.stderr)
        return 2
    adapter = runtime or production_runtime()
    validation = _validate_rollback_records(request, records, adapter)
    if validation is not None:
        print(validation.reason, file=sys.stderr)
        return validation.code
    updated = []
    for record in records:
        if not record.receipt:
            print(
                f"no rollback receipt for {record.artifact_type}/{record.artifact_name}@{record.profile}",
                file=sys.stderr,
            )
            return 2
        if not request.yes:
            try:
                approved = read(
                    f"Rollback {record.artifact_type}/{record.artifact_name}@{record.profile}? [y/N]: "
                ).strip().lower() in ("y", "yes")
            except EOFError:
                approved = False
            if not approved:
                continue
        rolled = rollback_record(record, adapter)
        state = upsert_setup_record(state, rolled)
        updated.append(rolled)
        error = _save_state(root, state)
        if error is not None:
            print(error.reason, file=sys.stderr)
            return error.code
    if request.json:
        write(json.dumps({"records": [_record_payload(record) for record in updated]}, indent=2))
    else:
        _render_records(updated, write)
    return 0 if all(record.status != "rollback_incomplete" for record in updated) else 1


def execute(
    request: Request,
    *,
    runtime: Optional[SetupRuntime] = None,
    read: ReadFn = input,
    write: WriteFn = print,
) -> int:
    scope_error = _common.validate_scope(request)
    if scope_error is not None:
        print(scope_error.reason, file=sys.stderr)
        return scope_error.code
    if request.setup_action == "status":
        return _run_status(request, write=write)
    if request.setup_action == "rollback":
        return _run_rollback(request, runtime=runtime, read=read, write=write)
    if request.setup_action not in ("run", "retry"):
        print("unknown setup action", file=sys.stderr)
        return 2
    root = _common.manifest_root(request)
    state = _load_state(root)
    if isinstance(state, Err):
        print(state.reason, file=sys.stderr)
        return state.code
    retry_records = _select_state_records(state, request) if request.setup_action == "retry" else ()
    if request.setup_action == "retry" and not retry_records:
        write("No incomplete setup records matched.")
        return 0
    queue = _queue_from_installed(request, retry_records)
    if isinstance(queue, Err):
        print(queue.reason, file=sys.stderr)
        return queue.code
    adapter = runtime or production_runtime()
    plans = tuple(
        plan_setup(
            item,
            target_root=root,
            home_root=_common.user_root(request),
            run_root=root,
            platform=adapter.platform,
        )
        for item in queue
    )
    results = run_queue(
        queue,
        scope_root=root,
        target_root=_common.user_root(request),
        request=request,
        runtime=adapter,
        read=read,
        write=(lambda _line: None) if request.json else write,
    )
    if isinstance(results, Err):
        print(results.reason, file=sys.stderr)
        return results.code
    if request.json:
        write(
            json.dumps(
                {
                    "plans": [_plan_payload(plan) for plan in plans],
                    "records": [_record_payload(record) for record in results],
                },
                indent=2,
            )
        )
    else:
        _render_records(results, write)
    return (
        0 if all(record.status in ("configured", "already_configured") for record in results) else 1
    )


def run(request: Request) -> int:
    return execute(request)
