"""Source-aware canonical status, check, update, and uninstall services."""

from __future__ import annotations

import posixpath
from typing import Protocol

from agent_artifacts.configuration.model import SourceKind, git_location_parts
from agent_artifacts.configuration.policy import EffectiveConfiguration
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import ObjectDigest
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.install_state.model import EffectProof, InstallationRecord, InstallState
from agent_artifacts.install_state.paths import install_state_paths
from agent_artifacts.install_state.schema import install_state_bytes, parse_install_state
from agent_artifacts.installation.application import (
    InstallApplyPorts,
    InstallReadPorts,
    finalize_install,
    prepare_install,
)
from agent_artifacts.installation.model import (
    InstallLocation,
    InstallRequest,
    InstallStatus,
    LinkStatus,
    PathSnapshot,
    classify_link,
)
from agent_artifacts.marketplace.model import MarketplaceCatalog
from agent_artifacts.profiles.model import Profile
from agent_artifacts.protocol.hashing import json_digest, sha256_bytes
from agent_artifacts.protocol.json import (
    JsonArray,
    JsonObject,
    JsonValue,
    canonical_json_bytes,
    parse_json,
)
from agent_artifacts.store.model import (
    ObjectStorePaths,
    ReferenceIndex,
    ReferenceKind,
    ReferenceReadRequest,
)

from .model import (
    LifecycleEffect,
    LifecycleItem,
    LifecycleKey,
    LifecycleOutcome,
    LifecycleSelection,
    LifecycleStatus,
    UninstallOperation,
    UninstallPlan,
    UpdatePlan,
    absolute_effect_path,
    reference_owner,
    select_installations,
)

LIFECYCLE_INVALID = DiagnosticCode("lifecycle-invalid")
LIFECYCLE_REVIEW_MISMATCH = DiagnosticCode("lifecycle-review-mismatch")


def _error(code: DiagnosticCode, message: str) -> Err:
    return Err((Diagnostic(code, Severity.ERROR, message),))


class LifecycleReadPorts(InstallReadPorts, Protocol):
    def read_references(self, request: ReferenceReadRequest) -> Result[ReferenceIndex]: ...


class LifecycleApplyPorts(LifecycleReadPorts, InstallApplyPorts, Protocol):
    def apply_uninstall_plan(self, plan: UninstallPlan) -> Result[LifecycleItem]: ...


def _object_member(node: JsonObject, key: str) -> tuple[bool, JsonValue]:
    for candidate, value in node.entries:
        if candidate == key:
            return True, value
    return False, None


def _navigate_member(root: JsonValue, path: str) -> tuple[bool, JsonValue]:
    node = root
    if not path:
        return True, node
    for part in path.split("."):
        if not isinstance(node, JsonObject):
            return False, None
        found, node = _object_member(node, part)
        if not found:
            return False, None
    return True, node


def _navigate(root: JsonValue, path: str) -> JsonValue | None:
    found, node = _navigate_member(root, path)
    return node if found else None


def _identity_value(node: JsonValue, field: str) -> tuple[bool, JsonValue]:
    if isinstance(node, JsonObject):
        found_direct, direct = _object_member(node, field)
        if found_direct:
            return True, direct
        for _key, child in node.entries:
            found, value = _identity_value(child, field)
            if found:
                return True, value
    elif isinstance(node, JsonArray):
        for child in node.items:
            found, value = _identity_value(child, field)
            if found:
                return True, value
    return False, None


def _identity_projection(value: JsonValue, evidence: JsonObject) -> JsonObject | None:
    projected: list[tuple[str, JsonValue]] = []
    for field, expected in evidence.entries:
        found, actual = _identity_value(value, field)
        if not found or actual != expected:
            return None
        projected.append((field, actual))
    return JsonObject(tuple(projected))


def _merge_matches(
    effect: EffectProof, root: JsonValue
) -> tuple[tuple[str, int | str, JsonValue], ...]:
    evidence = effect.identity_evidence
    if effect.merge_mode == "key" and isinstance(evidence, JsonArray):
        if len(evidence.items) != 1 or not isinstance(evidence.items[0], str):
            return ()
        key = evidence.items[0]
        container_path = effect.json_path or ""
        container = _navigate(root, container_path)
        if not isinstance(container, JsonObject):
            return ()
        found, value = _object_member(container, key)
        return ((container_path, key, value),) if found else ()
    if effect.merge_mode == "list" and isinstance(evidence, JsonObject):
        current = _navigate(root, effect.json_path or "")
        if not isinstance(current, JsonArray):
            return ()
        return tuple(
            (effect.json_path or "", index, value)
            for index, value in enumerate(current.items)
            if _identity_projection(value, evidence) == evidence
        )
    return ()


def _replace_at(root: JsonValue, path: str, replacement: JsonValue) -> JsonValue | None:
    if not path:
        return replacement
    if not isinstance(root, JsonObject):
        return None
    head, _, tail = path.partition(".")
    found, child = _object_member(root, head)
    if not found:
        return None
    updated = _replace_at(child, tail, replacement)
    if updated is None:
        return None
    return JsonObject(
        tuple((key, updated if key == head else value) for key, value in root.entries)
    )


def _remove_merge_identity(effect: EffectProof, root: JsonValue) -> tuple[JsonValue | None, str]:
    matches = _merge_matches(effect, root)
    if not matches:
        return root, "missing"
    if len(matches) != 1:
        return None, "ambiguous"
    path, identity, _value = matches[0]
    container = _navigate(root, path)
    if isinstance(identity, str) and isinstance(container, JsonObject):
        replacement: JsonValue = JsonObject(
            tuple((key, value) for key, value in container.entries if key != identity)
        )
    elif isinstance(identity, int) and isinstance(container, JsonArray):
        replacement = JsonArray(
            tuple(value for index, value in enumerate(container.items) if index != identity)
        )
    else:
        return None, "invalid"
    updated = _replace_at(root, path, replacement)
    return updated, "removed" if updated is not None else "invalid"


def _merge_effect_status(effect: EffectProof, snapshot: PathSnapshot) -> LifecycleStatus:
    if snapshot.kind == "absent":
        return LifecycleStatus.MISSING
    if snapshot.kind != "file" or effect.identity_evidence is None:
        return LifecycleStatus.DRIFTED
    parsed = parse_json(snapshot.content)
    if isinstance(parsed, Err):
        return LifecycleStatus.DRIFTED
    matches = _merge_matches(effect, parsed.value)
    if not matches:
        found, container = _navigate_member(parsed.value, effect.json_path or "")
        if not found:
            return LifecycleStatus.MISSING
        if effect.merge_mode == "list":
            if not isinstance(container, JsonArray):
                return LifecycleStatus.DRIFTED
            if container.items:
                return LifecycleStatus.DRIFTED
        elif not isinstance(container, JsonObject):
            return LifecycleStatus.DRIFTED
        return LifecycleStatus.MISSING
    if len(matches) != 1:
        return LifecycleStatus.DRIFTED
    return (
        LifecycleStatus.CURRENT
        if json_digest(matches[0][2]) == effect.installed_digest
        else LifecycleStatus.DRIFTED
    )


def _memory_markers(record: InstallationRecord) -> tuple[str, str]:
    name = record.artifact.identity.name
    return (
        f"<!-- >>> agent-artifacts memory:{name} >>> -->",
        f"<!-- <<< agent-artifacts memory:{name} <<< -->",
    )


def _managed_block_status(record: InstallationRecord, snapshot: PathSnapshot) -> LifecycleStatus:
    if snapshot.kind == "absent":
        return LifecycleStatus.MISSING
    if snapshot.kind != "file":
        return LifecycleStatus.DRIFTED
    try:
        text = snapshot.content.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return LifecycleStatus.DRIFTED
    begin, end = _memory_markers(record)
    if begin not in text and end not in text:
        return LifecycleStatus.MISSING
    if begin not in text or end not in text or text.index(end) < text.index(begin):
        return LifecycleStatus.DRIFTED
    return (
        LifecycleStatus.CURRENT
        if text.count(begin) == text.count(end) == 1
        else LifecycleStatus.DRIFTED
    )


def _effect_status(
    record: InstallationRecord, effect: EffectProof, snapshot: PathSnapshot
) -> LifecycleStatus:
    if effect.kind in {"symlink-file", "symlink-tree"}:
        if snapshot.kind == "absent":
            return LifecycleStatus.MISSING
        linked = classify_link(effect, snapshot)
        return {
            LinkStatus.CURRENT: LifecycleStatus.CURRENT,
            LinkStatus.MUTABLE_LOCAL: LifecycleStatus.CURRENT,
            LinkStatus.BROKEN: LifecycleStatus.BROKEN,
            LinkStatus.RETARGETED: LifecycleStatus.RETARGETED,
            LinkStatus.REPLACED: LifecycleStatus.REPLACED,
        }[linked]
    if effect.kind == "merge-json":
        return _merge_effect_status(effect, snapshot)
    if effect.kind == "managed-block":
        return _managed_block_status(record, snapshot)
    if snapshot.kind == "absent":
        return LifecycleStatus.MISSING
    expected_kind = "tree" if effect.kind == "copy-tree" else "file"
    return (
        LifecycleStatus.CURRENT
        if snapshot.kind == expected_kind and snapshot.digest == effect.installed_digest
        else LifecycleStatus.DRIFTED
    )


_STATUS_PRIORITY = {
    LifecycleStatus.CURRENT: 0,
    LifecycleStatus.MISSING: 1,
    LifecycleStatus.BROKEN: 2,
    LifecycleStatus.DRIFTED: 3,
    LifecycleStatus.RETARGETED: 4,
    LifecycleStatus.REPLACED: 5,
    LifecycleStatus.FAILED: 6,
}


def _aggregate_status(effects: tuple[LifecycleEffect, ...]) -> LifecycleStatus:
    return max((effect.status for effect in effects), key=_STATUS_PRIORITY.__getitem__)


def status_installations(
    state: InstallState,
    selection: LifecycleSelection,
    location: InstallLocation,
    ports: LifecycleReadPorts,
) -> Result[LifecycleOutcome]:
    """Inspect only recorded destinations; status performs no source/network work."""

    items: list[LifecycleItem] = []
    for record in select_installations(state, selection):
        effects: list[LifecycleEffect] = []
        for effect in record.effects:
            try:
                absolute = absolute_effect_path(effect, record.scope, location)
            except ValueError as error:
                return _error(LIFECYCLE_INVALID, str(error))
            observed = ports.inspect_path(absolute)
            if isinstance(observed, Err):
                effects.append(
                    LifecycleEffect(
                        effect.kind,
                        effect.destination,
                        LifecycleStatus.FAILED,
                        "; ".join(item.message for item in observed.diagnostics),
                    )
                )
                continue
            status = _effect_status(record, effect, observed.value)
            effects.append(LifecycleEffect(effect.kind, effect.destination, status))
        effect_tuple = tuple(effects)
        items.append(
            LifecycleItem(
                LifecycleKey.from_record(record),
                _aggregate_status(effect_tuple),
                effect_tuple,
            )
        )
    return Ok(LifecycleOutcome("status", len(items), tuple(items)))


def _recorded_source_current(
    record: InstallationRecord,
    catalog: MarketplaceCatalog,
    effective: EffectiveConfiguration,
) -> bool:
    configured = next(
        (
            source
            for source in effective.configuration.sources
            if source.alias == record.source.alias and source.enabled
        ),
        None,
    )
    source = next(
        (candidate for candidate in catalog.sources if candidate.alias == record.source.alias), None
    )
    configured_origin = None
    if configured is not None:
        if configured.kind is SourceKind.SOURCE_LOCAL:
            configured_origin = configured.location
        else:
            parts = git_location_parts(configured.location)
            if parts is not None:
                configured_origin = f"{parts[0]}/{parts[1]}"
    return bool(
        configured is not None
        and configured.kind is record.source.kind
        and configured_origin == record.source.origin
        and source is not None
        and source.source_id == record.source.declared_id
        and source.kind is record.source.kind
        and source.origin == record.source.origin
        and configured.ref == record.source.subscription_ref
        and source.resolved_revision is not None
        and source.snapshot_digest is not None
        and source.health.value in {"healthy", "stale", "degraded"}
    )


def _current_item(record: InstallationRecord, catalog: MarketplaceCatalog):
    return next(
        (
            item
            for item in catalog.items
            if item.coordinate.source == record.coordinate.source
            and item.coordinate.artifact == record.coordinate.artifact
        ),
        None,
    )


def check_installations(
    state: InstallState,
    selection: LifecycleSelection,
    catalog: MarketplaceCatalog,
    effective: EffectiveConfiguration,
) -> LifecycleOutcome:
    """Compare with an already-built snapshot; source fetch/sync is deliberately outside."""

    items: list[LifecycleItem] = []
    for record in select_installations(state, selection):
        key = LifecycleKey.from_record(record)
        if not _recorded_source_current(record, catalog, effective):
            items.append(
                LifecycleItem(
                    key, LifecycleStatus.SOURCE_UNAVAILABLE, detail="recorded source unavailable"
                )
            )
            continue
        current = _current_item(record, catalog)
        if current is None:
            items.append(
                LifecycleItem(
                    key, LifecycleStatus.REMOVED_UPSTREAM, detail="removed from recorded source"
                )
            )
            continue
        artifact = current.artifact.artifact
        status = (
            LifecycleStatus.CURRENT
            if (
                artifact.version == record.artifact.version
                and artifact.manifest_digest == record.artifact.manifest_digest
                and artifact.payload_digest == record.artifact.payload_digest
                and artifact.object_digest == record.artifact.object_digest
            )
            else LifecycleStatus.UPDATE_AVAILABLE
        )
        items.append(LifecycleItem(key, status))
    return LifecycleOutcome("check", len(items), tuple(items))


def reconcile_installations(
    state: InstallState,
    selection: LifecycleSelection,
    catalog: MarketplaceCatalog,
    effective: EffectiveConfiguration,
    location: InstallLocation,
    ports: LifecycleReadPorts,
) -> Result[LifecycleOutcome]:
    """Report one current answer for both installed bytes and their recorded origin.

    A local installation can be byte-for-byte current while its subscribed source has moved or
    withdrawn the artifact.  ``status`` therefore combines the local inspection with the
    already-refreshed marketplace snapshot; local damage remains the primary status because it
    needs intervention even when no update exists.
    """

    local = status_installations(state, selection, location, ports)
    if isinstance(local, Err):
        return local
    upstream = check_installations(state, selection, catalog, effective)
    remote_by_key = {item.key: item for item in upstream.items}
    items = []
    for item in local.value.items:
        remote = remote_by_key[item.key]
        if item.status is LifecycleStatus.CURRENT:
            items.append(LifecycleItem(item.key, remote.status, item.effects, detail=remote.detail))
        else:
            detail = item.detail
            if remote.status is not LifecycleStatus.CURRENT:
                suffix = remote.detail or remote.status.value
                detail = f"{detail}; upstream {suffix}" if detail else f"upstream {suffix}"
            items.append(LifecycleItem(item.key, item.status, item.effects, detail=detail))
    return Ok(LifecycleOutcome("status", len(items), tuple(items)))


def _strip_managed_block(record: InstallationRecord, content: bytes) -> bytes | None:
    try:
        text = content.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return None
    begin, end = _memory_markers(record)
    if begin not in text and end not in text:
        return content
    if text.count(begin) != 1 or text.count(end) != 1:
        return None
    start = text.index(begin)
    try:
        stop = text.index(end, start) + len(end)
    except ValueError:
        return None
    if stop < len(text) and text[stop] == "\n":
        stop += 1
    stripped = text[:start] + text[stop:]
    if stripped.endswith("\n\n"):
        stripped = stripped[:-1]
    if stripped.startswith("\n"):
        stripped = stripped[1:]
    return stripped.encode("utf-8")


def _plan_removal(
    record: InstallationRecord,
    effect: EffectProof,
    absolute: str,
    snapshot: PathSnapshot,
    *,
    force: bool,
) -> tuple[UninstallOperation | None, str | None]:
    if snapshot.kind == "special":
        return None, f"unsafe special destination: {effect.destination}"
    if effect.kind in {"symlink-file", "symlink-tree"}:
        status = _effect_status(record, effect, snapshot)
        if status is LifecycleStatus.MISSING:
            return UninstallOperation(effect, absolute, snapshot, "none"), None
        if status in {LifecycleStatus.CURRENT, LifecycleStatus.BROKEN}:
            return UninstallOperation(effect, absolute, snapshot, "remove"), None
        if not force:
            return None, f"managed link is {status.value}: {effect.destination}"
        return UninstallOperation(effect, absolute, snapshot, "remove"), None
    if effect.kind == "merge-json":
        if snapshot.kind == "absent":
            return UninstallOperation(effect, absolute, snapshot, "none"), None
        if snapshot.kind != "file" or effect.identity_evidence is None:
            return None, f"managed merge cannot be proven: {effect.destination}"
        parsed = parse_json(snapshot.content)
        if isinstance(parsed, Err):
            return None, f"managed merge JSON is invalid: {effect.destination}"
        matches = _merge_matches(effect, parsed.value)
        if not matches:
            found, container = _navigate_member(parsed.value, effect.json_path or "")
            expected = JsonArray if effect.merge_mode == "list" else JsonObject
            structural_drift = found and not isinstance(container, expected)
            identity_drift = (
                effect.merge_mode == "list"
                and isinstance(container, JsonArray)
                and bool(container.items)
            )
            if (structural_drift or identity_drift) and not force:
                return None, f"managed merge identity drifted: {effect.destination}"
            return UninstallOperation(effect, absolute, snapshot, "none"), None
        if len(matches) != 1:
            return None, f"managed merge identity is ambiguous: {effect.destination}"
        if json_digest(matches[0][2]) != effect.installed_digest and not force:
            return None, f"managed merge drifted: {effect.destination}"
        updated, result = _remove_merge_identity(effect, parsed.value)
        if result != "removed" or updated is None:
            return None, f"managed merge cannot be reversed: {effect.destination}"
        if effect.created_destination and isinstance(updated, JsonObject) and not updated.entries:
            return UninstallOperation(effect, absolute, snapshot, "remove"), None
        return UninstallOperation(
            effect,
            absolute,
            snapshot,
            "write",
            canonical_json_bytes(updated),
        ), None
    if effect.kind == "managed-block":
        if snapshot.kind == "absent":
            return UninstallOperation(effect, absolute, snapshot, "none"), None
        if snapshot.kind != "file":
            return None, f"managed block destination changed type: {effect.destination}"
        stripped = _strip_managed_block(record, snapshot.content)
        if stripped is None:
            return None, f"managed block markers drifted: {effect.destination}"
        if stripped == snapshot.content:
            return UninstallOperation(effect, absolute, snapshot, "none"), None
        if not stripped:
            return UninstallOperation(effect, absolute, snapshot, "remove"), None
        return UninstallOperation(effect, absolute, snapshot, "write", stripped), None
    if snapshot.kind == "absent":
        return UninstallOperation(effect, absolute, snapshot, "none"), None
    expected_kind = "tree" if effect.kind == "copy-tree" else "file"
    owned = snapshot.kind == expected_kind and snapshot.digest == effect.installed_digest
    if not owned and not force:
        return None, f"managed Copy destination drifted: {effect.destination}"
    return UninstallOperation(effect, absolute, snapshot, "remove"), None


def prepare_uninstall(
    record: InstallationRecord,
    state: InstallState,
    location: InstallLocation,
    store_paths: ObjectStorePaths,
    ports: LifecycleReadPorts,
    *,
    force: bool = False,
) -> Result[UninstallPlan]:
    if record not in state.installations:
        return _error(LIFECYCLE_INVALID, "uninstall record is not present in installation state")
    paths = install_state_paths(
        record.scope,
        project_root=location.project_root,
        user_home=location.user_home,
        data_root=location.data_root,
    )
    loaded = ports.read_state(paths.destination_path)
    if isinstance(loaded, Err):
        return loaded
    state_snapshot = ports.inspect_path(paths.destination_path)
    if isinstance(state_snapshot, Err):
        return state_snapshot
    if loaded.value != state or state_snapshot.value.kind != "file":
        return _error(LIFECYCLE_INVALID, "installation state changed before uninstall review")
    parsed = parse_install_state(state_snapshot.value.content, path=paths.destination_path)
    if isinstance(parsed, Err) or parsed.value != state:
        return _error(LIFECYCLE_INVALID, "installation state snapshot does not match parsed state")
    references = ports.read_references(ReferenceReadRequest(store_paths))
    if isinstance(references, Err):
        return references
    owner = reference_owner(record)
    replacement_references = ReferenceIndex(
        1,
        tuple(
            item
            for item in references.value.references
            if not (item.kind is ReferenceKind.INSTALLED and item.owner == owner)
        ),
    )
    operations: list[UninstallOperation] = []
    conflicts: list[str] = []
    for effect in record.effects:
        try:
            absolute = absolute_effect_path(effect, record.scope, location)
        except ValueError as error:
            return _error(LIFECYCLE_INVALID, str(error))
        observed = ports.inspect_path(absolute)
        if isinstance(observed, Err):
            return observed
        operation, conflict = _plan_removal(record, effect, absolute, observed.value, force=force)
        if conflict is not None:
            conflicts.append(conflict)
        elif operation is not None:
            operations.append(operation)
    replacement_state = InstallState(
        2, tuple(item for item in state.installations if item.key != record.key)
    )
    placeholder = sha256_bytes(b"unreviewed-uninstall-plan")
    try:
        return Ok(
            UninstallPlan(
                record,
                force,
                () if conflicts else tuple(operations),
                paths.destination_path,
                paths.lock_path,
                state_snapshot.value,
                replacement_state,
                sha256_bytes(install_state_bytes(replacement_state)),
                store_paths,
                owner,
                references.value,
                replacement_references,
                LifecycleStatus.CONFLICT if conflicts else None,
                "; ".join(conflicts),
                placeholder,
            )
        )
    except ValueError as error:
        return _error(LIFECYCLE_INVALID, f"uninstall plan is invalid: {error}")


def finalize_uninstall(
    plan: UninstallPlan,
    reviewed_digest: ObjectDigest,
    ports: LifecycleApplyPorts,
) -> Result[LifecycleItem]:
    if reviewed_digest != plan.review_digest:
        return _error(LIFECYCLE_REVIEW_MISMATCH, "uninstall digest does not match reviewed plan")
    if plan.terminal is not None:
        return Ok(
            LifecycleItem(
                LifecycleKey.from_record(plan.record),
                plan.terminal,
                detail=plan.detail,
            )
        )
    return ports.apply_uninstall_plan(plan)


def _mutable_payload_root(record: InstallationRecord) -> str | None:
    # A migrated package-era link can be retained as mutable-local evidence while its canonical
    # source is now Git-backed. Its next update must transition to an immutable CAS link rather
    # than treating the old package/environment path as a configured local source root.
    if record.source.kind is not SourceKind.SOURCE_LOCAL:
        return None
    roots: set[str] = set()
    for effect in record.effects:
        if effect.link_semantics != "mutable-local" or effect.link_target is None:
            continue
        source_path = effect.source_path or "payload"
        if source_path == "payload":
            roots.add(effect.link_target)
        elif source_path.startswith("payload/"):
            suffix = source_path.removeprefix("payload/")
            candidate = effect.link_target
            for _part in suffix.split("/"):
                candidate = posixpath.dirname(candidate)
            roots.add(candidate)
    return next(iter(roots)) if len(roots) == 1 else None


def _terminal_update(
    record: InstallationRecord,
    status: LifecycleStatus,
    detail: str,
    *,
    prune: bool = False,
) -> UpdatePlan:
    item = LifecycleItem(LifecycleKey.from_record(record), status, detail=detail)
    return UpdatePlan(
        record,
        prune,
        None,
        None,
        item,
        sha256_bytes(b"unreviewed-update-plan"),
    )


def prepare_update(
    record: InstallationRecord,
    catalog: MarketplaceCatalog,
    effective: EffectiveConfiguration,
    profile: Profile,
    location: InstallLocation,
    store_paths: ObjectStorePaths,
    ports: LifecycleReadPorts,
    *,
    force: bool = False,
    prune: bool = False,
    offline: bool = False,
    platform: str = "darwin",
) -> Result[UpdatePlan]:
    if profile.name != record.profile:
        return _error(LIFECYCLE_INVALID, "lifecycle profile does not match the recorded profile")
    if not _recorded_source_current(record, catalog, effective):
        return Ok(
            _terminal_update(
                record,
                LifecycleStatus.SOURCE_UNAVAILABLE,
                "recorded source is missing, disabled, unhealthy, or changed identity/ref",
            )
        )
    if _current_item(record, catalog) is None:
        if not prune:
            return Ok(
                _terminal_update(
                    record,
                    LifecycleStatus.REMOVED_UPSTREAM,
                    "artifact was removed from the recorded source; rerun with prune to uninstall",
                )
            )
        current_state = _state_for_record(record, location, ports)
        if isinstance(current_state, Err):
            return current_state
        uninstall = prepare_uninstall(
            record,
            current_state.value,
            location,
            store_paths,
            ports,
            force=force,
        )
        if isinstance(uninstall, Err):
            return uninstall
        return Ok(
            UpdatePlan(
                record,
                True,
                None,
                uninstall.value,
                None,
                sha256_bytes(b"unreviewed-update-plan"),
            )
        )
    request = InstallRequest(
        record.artifact.identity,
        source=record.source.alias,
        profile=record.profile,
        profile_version=record.profile_version,
        platform=platform,
        scope=record.scope,
        mode=record.requested_mode,
        force=force,
        offline=offline,
        memory_mode=record.memory_mode or "prepend",
        mutable_local_payload_root=_mutable_payload_root(record),
    )
    install = prepare_install(
        request,
        catalog,
        effective,
        profile,
        location,
        store_paths,
        ports,
    )
    if isinstance(install, Err):
        diagnostics = install.diagnostics
        status = (
            LifecycleStatus.CONFLICT
            if any(item.code.value == "install-conflict" for item in diagnostics)
            else LifecycleStatus.FAILED
        )
        detail = "; ".join(item.message for item in diagnostics)
        return Ok(_terminal_update(record, status, detail))
    return Ok(
        UpdatePlan(
            record,
            False,
            install.value,
            None,
            None,
            sha256_bytes(b"unreviewed-update-plan"),
        )
    )


def _state_for_record(
    record: InstallationRecord, location: InstallLocation, ports: LifecycleReadPorts
) -> Result[InstallState]:
    paths = install_state_paths(
        record.scope,
        project_root=location.project_root,
        user_home=location.user_home,
        data_root=location.data_root,
    )
    loaded = ports.read_state(paths.destination_path)
    if isinstance(loaded, Err):
        return loaded
    if loaded.value is None or record not in loaded.value.installations:
        return _error(LIFECYCLE_INVALID, "recorded installation state is unavailable")
    return Ok(loaded.value)


def finalize_update(
    plan: UpdatePlan,
    reviewed_digest: ObjectDigest,
    catalog: MarketplaceCatalog,
    effective: EffectiveConfiguration,
    ports: LifecycleApplyPorts,
) -> Result[LifecycleItem]:
    if reviewed_digest != plan.review_digest:
        return _error(LIFECYCLE_REVIEW_MISMATCH, "update digest does not match reviewed plan")
    if plan.terminal is not None:
        return Ok(plan.terminal)
    if plan.uninstall_plan is not None:
        if (
            not _recorded_source_current(plan.record, catalog, effective)
            or _current_item(plan.record, catalog) is not None
        ):
            return Ok(
                LifecycleItem(
                    LifecycleKey.from_record(plan.record),
                    LifecycleStatus.CONFLICT,
                    detail="recorded source or upstream-removal evidence changed after Review",
                )
            )
        return finalize_uninstall(plan.uninstall_plan, plan.uninstall_plan.review_digest, ports)
    assert plan.install_plan is not None
    applied = finalize_install(
        plan.install_plan,
        plan.install_plan.review_digest,
        catalog,
        effective,
        ports,
    )
    if isinstance(applied, Err):
        return applied
    status = {
        InstallStatus.APPLIED: LifecycleStatus.CHANGED,
        InstallStatus.CURRENT: LifecycleStatus.CURRENT,
        InstallStatus.CONFLICTED: LifecycleStatus.CONFLICT,
        InstallStatus.FAILED: LifecycleStatus.FAILED,
    }[applied.value.status]
    effects = tuple(
        LifecycleEffect(
            effect.kind,
            effect.destination,
            {
                "changed": LifecycleStatus.CHANGED,
                "current": LifecycleStatus.CURRENT,
                "skipped": LifecycleStatus.SKIPPED,
                "failed": LifecycleStatus.FAILED,
                "rolled-back": LifecycleStatus.FAILED,
            }[effect.status],
            effect.detail or "",
        )
        for effect in applied.value.effects
    )
    return Ok(LifecycleItem(LifecycleKey.from_record(plan.record), status, effects))
