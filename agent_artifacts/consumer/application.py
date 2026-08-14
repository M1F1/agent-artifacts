"""Prepare and finalize one reviewed consumer basket through canonical application services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import ArtifactCoordinate, SourceAlias
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.install_state.model import InstallationRecord, InstallState
from agent_artifacts.install_state.paths import install_state_paths
from agent_artifacts.install_state.schema import install_state_bytes
from agent_artifacts.installation.application import finalize_install, prepare_install
from agent_artifacts.installation.model import (
    CopyTreeOperation,
    InstallPlan,
    InstallRequest,
    InstallStatus,
    LinkOperation,
    MergeJsonOperation,
    PathSnapshot,
    WriteFileOperation,
)
from agent_artifacts.lifecycle.application import (
    LifecycleApplyPorts,
    check_installations,
    finalize_uninstall,
    finalize_update,
    prepare_uninstall,
    prepare_update,
    reconcile_installations,
)
from agent_artifacts.lifecycle.model import (
    LifecycleItem,
    LifecycleKey,
    LifecycleSelection,
    LifecycleStatus,
    UninstallPlan,
    UpdatePlan,
    select_installations,
)
from agent_artifacts.marketplace.catalog import resolve_artifact
from agent_artifacts.marketplace.model import ArtifactQuery, MarketplaceItem
from agent_artifacts.protocol.hashing import sha256_bytes
from agent_artifacts.security.aggregation import ArtifactSecurityEvidence
from agent_artifacts.setup_engine.application import (
    Consent,
    SetupApplyPorts,
    SetupReadPorts,
    execute_setup_queue,
    prepare_setup_attempt,
)
from agent_artifacts.setup_engine.model import SetupQueueOutcome, SetupRequest
from agent_artifacts.setup_runtime import SetupRuntime, production_runtime
from agent_artifacts.store.model import ObjectReadRequest, ReferenceIndex, ReferenceReadRequest
from agent_artifacts.tui_marketplace import (
    MarketplaceArtifactRow,
    MarketplaceTarget,
    project_marketplace_rows,
)

from .coordinates import ArtifactSelector
from .model import (
    ConsumerActionRequest,
    ConsumerContext,
    ConsumerOutcome,
    ConsumerPlan,
    ConsumerReview,
    ConsumerReviewEffect,
    ConsumerReviewItem,
    ConsumerSetupDeclaration,
    ConsumerSetupFailure,
    ConsumerSetupQueue,
    ConsumerTerminalItem,
)
from .resolution import resolve_installed_selectors

CONSUMER_INVALID = DiagnosticCode("consumer-invalid")
CONSUMER_REVIEW_MISMATCH = DiagnosticCode("consumer-review-mismatch")


class ConsumerPorts(LifecycleApplyPorts, SetupApplyPorts, Protocol):
    """Effects required by the composed consumer install/lifecycle/setup boundary."""


ConsumerContentPort = Callable[[ConsumerActionRequest], Result[None]]


def _content_already_available(_request: ConsumerActionRequest) -> Result[None]:
    return Ok(None)


def _error(code: DiagnosticCode, message: str) -> Err:
    return Err((Diagnostic(code, Severity.ERROR, message),))


class _PlanningOverlay:
    """Project earlier reviewed plans so later basket items bind sequential preconditions."""

    def __init__(self, ports: LifecycleApplyPorts) -> None:
        self._ports = ports
        self._states: dict[str, InstallState] = {}
        self._paths: dict[str, PathSnapshot] = {}
        self._references: dict[str, ReferenceIndex] = {}

    def read_object(self, request: ObjectReadRequest):
        return self._ports.read_object(request)

    def read_state(self, path: str):
        if path in self._states:
            return Ok(self._states[path])
        return self._ports.read_state(path)

    def inspect_path(self, path: str):
        if path in self._paths:
            return Ok(self._paths[path])
        return self._ports.inspect_path(path)

    def inspect_link_target(self, path: str, boundary: str):
        return self._ports.inspect_link_target(path, boundary)

    def read_references(self, request: ReferenceReadRequest):
        if request.paths.root in self._references:
            return Ok(self._references[request.paths.root])
        return self._ports.read_references(request)

    def project_install(self, plan: InstallPlan) -> None:
        content = install_state_bytes(plan.replacement_state)
        self._states[plan.state_path] = plan.replacement_state
        self._paths[plan.state_path] = PathSnapshot.file(plan.state_path, content)
        for operation in plan.operations:
            if isinstance(operation, CopyTreeOperation):
                snapshot = PathSnapshot.tree(operation.absolute_destination, operation.members)
            elif isinstance(operation, (WriteFileOperation, MergeJsonOperation)):
                snapshot = PathSnapshot.file(operation.absolute_destination, operation.content)
            else:
                snapshot = PathSnapshot.symlink(
                    operation.absolute_destination,
                    operation.target,
                    target_exists=True,
                )
            self._paths[operation.absolute_destination] = snapshot

    def project_uninstall(self, plan: UninstallPlan) -> None:
        content = install_state_bytes(plan.replacement_state)
        self._states[plan.state_path] = plan.replacement_state
        self._paths[plan.state_path] = PathSnapshot.file(plan.state_path, content)
        self._references[plan.object_store_paths.root] = plan.reference_replacement
        for operation in plan.operations:
            if operation.mutation == "remove":
                snapshot = PathSnapshot.absent(operation.absolute_destination)
            elif operation.mutation == "write":
                snapshot = PathSnapshot.file(
                    operation.absolute_destination,
                    operation.replacement_content,
                )
            else:
                snapshot = operation.precondition
            self._paths[operation.absolute_destination] = snapshot

    def project_update(self, plan: UpdatePlan) -> None:
        if plan.install_plan is not None:
            self.project_install(plan.install_plan)
        elif plan.uninstall_plan is not None:
            self.project_uninstall(plan.uninstall_plan)


def _state(
    request: ConsumerActionRequest,
    context: ConsumerContext,
    ports: LifecycleApplyPorts,
) -> Result[InstallState]:
    paths = install_state_paths(
        request.scope,
        project_root=context.location.project_root,
        user_home=context.location.user_home,
        data_root=context.location.data_root,
    )
    loaded = ports.read_state(paths.destination_path)
    if isinstance(loaded, Err):
        return loaded
    return Ok(InstallState(2, ()) if loaded.value is None else loaded.value)


def browse_consumer_marketplace(
    target: MarketplaceTarget,
    context: ConsumerContext,
    ports: LifecycleApplyPorts,
    *,
    sources: tuple[SourceAlias, ...] = (),
) -> Result[tuple[MarketplaceArtifactRow, ...]]:
    """Join canonical browse, local status, and fetch-free update state for the TUI."""

    request = ConsumerActionRequest("status", (), target.profiles, target.scope, target.mode)
    current = _state(request, context, ports)
    if isinstance(current, Err):
        return current
    selection = LifecycleSelection(target.scope, profiles=target.profiles)
    reconciled = reconcile_installations(
        current.value,
        selection,
        context.catalog,
        context.effective,
        context.location,
        ports,
    )
    if isinstance(reconciled, Err):
        return reconciled
    allowed = frozenset(sources)
    rows = project_marketplace_rows(
        context.catalog,
        target,
        security=context.security,
        lifecycle=reconciled.value.items,
    )
    return Ok(tuple(row for row in rows if not allowed or row.source_alias in allowed))


def _unversioned(coordinate: ArtifactCoordinate) -> ArtifactCoordinate:
    return ArtifactCoordinate(coordinate.source, coordinate.artifact)


def _selected_records(
    state: InstallState,
    request: ConsumerActionRequest,
) -> Result[tuple[InstallationRecord, ...]]:
    requested = {_unversioned(item) for item in request.coordinates}
    selection = LifecycleSelection(
        request.scope,
        tuple(sorted(requested, key=str)),
        request.profiles,
    )
    records = select_installations(state, selection)
    if not requested:
        return Ok(records)
    expected = {(coordinate, profile) for coordinate in requested for profile in request.profiles}
    actual = {(record.coordinate, record.profile) for record in records}
    missing = tuple(sorted(f"{coordinate}#{profile}" for coordinate, profile in expected - actual))
    if missing:
        return _error(
            CONSUMER_INVALID,
            "selected canonical installations were not found: " + ", ".join(missing),
        )
    return Ok(records)


def _security(
    coordinate: ArtifactCoordinate,
    evidence: tuple[ArtifactSecurityEvidence, ...],
) -> tuple[str, str]:
    found = next((item for item in evidence if item.coordinate == coordinate), None)
    if found is None:
        return "not-scanned", "unknown"
    return found.assessment.status.value, found.assessment.installation_risk.value


def _setup(item: MarketplaceItem | None) -> ConsumerSetupDeclaration | None:
    indexed = None if item is None else item.artifact.artifact.setup
    if indexed is None:
        return None
    return ConsumerSetupDeclaration(
        str(indexed.recipe),
        indexed.platforms,
        tuple(str(capability) for capability in indexed.capabilities),
    )


def _effect_kind(operation) -> str:
    if isinstance(operation, CopyTreeOperation):
        return "copy-tree"
    if isinstance(operation, WriteFileOperation):
        return operation.effect_kind
    if isinstance(operation, MergeJsonOperation):
        return "merge-json"
    assert isinstance(operation, LinkOperation)
    return "symlink-tree" if operation.target_kind == "tree" else "symlink-file"


def _install_effects(plan: InstallPlan) -> tuple[ConsumerReviewEffect, ...]:
    return tuple(
        ConsumerReviewEffect(
            _effect_kind(operation),
            operation.absolute_destination,
            "symlink" if isinstance(operation, LinkOperation) else "copy",
        )
        for operation in plan.operations
    )


def _record_effects(
    record: InstallationRecord, context: ConsumerContext
) -> tuple[ConsumerReviewEffect, ...]:
    effects = []
    for effect in record.effects:
        destination = effect.destination
        if record.scope == "project":
            destination = f"{context.location.project_root}/{effect.destination}"
        effects.append(ConsumerReviewEffect(effect.kind, destination, effect.actual_mode))
    return tuple(effects)


def _marketplace_item(
    coordinate: ArtifactCoordinate,
    context: ConsumerContext,
) -> MarketplaceItem | None:
    result = resolve_artifact(
        context.catalog,
        ArtifactQuery(coordinate.artifact, coordinate.source, coordinate.version),
    )
    return result.value if isinstance(result, Ok) else None


def _review_item(
    action: str,
    coordinate: ArtifactCoordinate,
    profile: str,
    scope: str,
    plan: ConsumerPlan,
    context: ConsumerContext,
) -> ConsumerReviewItem:
    install: InstallPlan | None = None
    record: InstallationRecord | None = None
    if isinstance(plan, LifecycleItem):
        raise ValueError("lifecycle terminal items use the terminal Review projection")
    if isinstance(plan, InstallPlan):
        install = plan
    elif isinstance(plan, UpdatePlan):
        record = plan.record
        install = plan.install_plan
    elif isinstance(plan, UninstallPlan):
        record = plan.record

    item = _marketplace_item(coordinate, context)
    if install is not None:
        exact_coordinate = install.coordinate
        source_revision = install.source.resolved_commit
        trust = install.trust
        manifest_digest = str(install.artifact.manifest_digest)
        payload_digest = str(install.artifact.payload_digest)
        object_digest = str(install.object_digest)
        effects = _install_effects(install)
        if isinstance(plan, InstallPlan):
            plan_digest = install.review_digest
        else:
            assert isinstance(plan, UpdatePlan)
            plan_digest = plan.review_digest
    else:
        assert record is not None
        exact_coordinate = ArtifactCoordinate(
            record.coordinate.source,
            record.coordinate.artifact,
            str(record.artifact.version),
        )
        source_revision = record.source.resolved_commit
        trust = "recorded" if item is None else item.trust.kind.value
        manifest_digest = str(record.artifact.manifest_digest)
        payload_digest = str(record.artifact.payload_digest)
        object_digest = str(record.artifact.object_digest)
        effects = _record_effects(record, context)
        assert isinstance(plan, (UpdatePlan, UninstallPlan))
        plan_digest = plan.review_digest
    security_status, installation_risk = _security(exact_coordinate, context.security)
    # Only an update can rebind: install has no prior record, and uninstall builds no new one.
    identity_transition = None
    if record is not None and install is not None:
        installed_under = record.source.declared_id
        now_declares = install.source.declared_id
        if installed_under != now_declares:
            identity_transition = f"{installed_under}:{now_declares}"
    return ConsumerReviewItem(
        f"{exact_coordinate}#{profile}/{scope}",
        exact_coordinate,
        profile,
        scope,  # type: ignore[arg-type]
        action,  # type: ignore[arg-type]
        source_revision,
        trust,
        manifest_digest,
        payload_digest,
        object_digest,
        security_status,
        installation_risk,
        effects,
        _setup(item),
        plan_digest,
        plan,
        identity_transition,
    )


def _terminal_review_item(
    action: str,
    outcome: LifecycleItem,
    record: InstallationRecord,
    context: ConsumerContext,
) -> ConsumerReviewItem:
    coordinate = ArtifactCoordinate(
        record.coordinate.source,
        record.coordinate.artifact,
        str(record.artifact.version),
    )
    item = _marketplace_item(coordinate, context)
    security_status, installation_risk = _security(coordinate, context.security)
    digest = sha256_bytes(f"{outcome.key}:{outcome.status.value}:{outcome.detail}".encode())
    return ConsumerReviewItem(
        f"{coordinate}#{record.profile}/{record.scope}",
        coordinate,
        record.profile,
        record.scope,
        action,  # type: ignore[arg-type]
        record.source.resolved_commit,
        "recorded" if item is None else item.trust.kind.value,
        str(record.artifact.manifest_digest),
        str(record.artifact.payload_digest),
        str(record.artifact.object_digest),
        security_status,
        installation_risk,
        _record_effects(record, context),
        _setup(item),
        digest,
        outcome,
    )


def prepare_consumer_action(
    request: ConsumerActionRequest,
    context: ConsumerContext,
    ports: LifecycleApplyPorts,
) -> Result[ConsumerReview]:
    """Prepare one exact, sequentially composable Review for the complete selected basket."""

    missing_profiles = tuple(
        profile for profile in request.profiles if profile not in context.profiles
    )
    if missing_profiles:
        return _error(
            CONSUMER_INVALID,
            "selected harness profiles are unavailable: " + ", ".join(missing_profiles),
        )
    current = _state(request, context, ports)
    if isinstance(current, Err):
        return current
    overlay = _PlanningOverlay(ports)
    items: list[ConsumerReviewItem] = []

    if request.action == "install":
        for coordinate in request.coordinates:
            for profile in request.profiles:
                plan = prepare_install(
                    InstallRequest(
                        coordinate.artifact,
                        source=coordinate.source,
                        version=coordinate.version,
                        profile=profile,
                        platform=request.platform,
                        scope=request.scope,
                        mode=request.mode,
                        force=request.force,
                        offline=request.offline,
                        memory_mode=request.memory_mode,
                    ),
                    context.catalog,
                    context.effective,
                    context.profiles[profile],
                    context.location,
                    context.store_paths,
                    overlay,
                )
                if isinstance(plan, Err):
                    return plan
                items.append(
                    _review_item(
                        request.action,
                        coordinate,
                        profile,
                        request.scope,
                        plan.value,
                        context,
                    )
                )
                overlay.project_install(plan.value)
    else:
        records_result = _selected_records(current.value, request)
        if isinstance(records_result, Err):
            return records_result
        records = records_result.value
        selection = LifecycleSelection(
            request.scope,
            tuple(sorted({_unversioned(item) for item in request.coordinates}, key=str)),
            request.profiles,
        )
        if request.action == "status":
            status_result = reconcile_installations(
                current.value,
                selection,
                context.catalog,
                context.effective,
                context.location,
                ports,
            )
            if isinstance(status_result, Err):
                return status_result
            by_key = {LifecycleKey.from_record(record): record for record in records}
            items.extend(
                _terminal_review_item(request.action, item, by_key[item.key], context)
                for item in status_result.value.items
            )
        elif request.action == "check":
            check_outcome = check_installations(
                current.value,
                selection,
                context.catalog,
                context.effective,
            )
            by_key = {LifecycleKey.from_record(record): record for record in records}
            items.extend(
                _terminal_review_item(request.action, item, by_key[item.key], context)
                for item in check_outcome.items
            )
        else:
            for record in records:
                if request.action == "update":
                    update_result = prepare_update(
                        record,
                        context.catalog,
                        context.effective,
                        context.profiles[record.profile],
                        context.location,
                        context.store_paths,
                        overlay,
                        force=request.force,
                        prune=request.prune,
                        offline=request.offline,
                        platform=request.platform,
                    )
                    if isinstance(update_result, Err):
                        return update_result
                    coordinate = ArtifactCoordinate(
                        record.coordinate.source,
                        record.coordinate.artifact,
                        str(record.artifact.version),
                    )
                    items.append(
                        _review_item(
                            request.action,
                            coordinate,
                            record.profile,
                            record.scope,
                            update_result.value,
                            context,
                        )
                    )
                    overlay.project_update(update_result.value)
                else:
                    state_path = install_state_paths(
                        record.scope,
                        project_root=context.location.project_root,
                        user_home=context.location.user_home,
                        data_root=context.location.data_root,
                    ).destination_path
                    projected_state = overlay.read_state(state_path)
                    if isinstance(projected_state, Err) or projected_state.value is None:
                        return (
                            projected_state
                            if isinstance(projected_state, Err)
                            else _error(
                                CONSUMER_INVALID,
                                "installation state disappeared while planning the basket",
                            )
                        )
                    uninstall_result = prepare_uninstall(
                        record,
                        projected_state.value,
                        context.location,
                        context.store_paths,
                        overlay,
                        force=request.force,
                    )
                    if isinstance(uninstall_result, Err):
                        return uninstall_result
                    coordinate = ArtifactCoordinate(
                        record.coordinate.source,
                        record.coordinate.artifact,
                        str(record.artifact.version),
                    )
                    items.append(
                        _review_item(
                            request.action,
                            coordinate,
                            record.profile,
                            record.scope,
                            uninstall_result.value,
                            context,
                        )
                    )
                    overlay.project_uninstall(uninstall_result.value)
    try:
        return Ok(
            ConsumerReview(
                request,
                tuple(items),
                sha256_bytes(b"unreviewed-consumer-action"),
            )
        )
    except ValueError as error:
        return _error(CONSUMER_INVALID, f"consumer Review is invalid: {error}")


def _detail(diagnostics: tuple[Diagnostic, ...]) -> str:
    return "; ".join(item.message for item in diagnostics)


def _lifecycle_terminal(
    item: LifecycleItem, setup: bool, *, key: str | None = None
) -> ConsumerTerminalItem:
    return ConsumerTerminalItem(
        key or f"{item.key.coordinate}#{item.key.profile}/{item.key.scope}",
        item.status.value,
        item.detail,
        "pending"
        if setup and item.status in {LifecycleStatus.CHANGED, LifecycleStatus.CURRENT}
        else ("skipped" if setup else "not-required"),
    )


def finalize_consumer_action(
    review: ConsumerReview,
    reviewed_digest,
    context: ConsumerContext,
    ports: LifecycleApplyPorts,
) -> Result[ConsumerOutcome]:
    """Finalize every reviewed item sequentially and retain one terminal result per target."""

    if reviewed_digest != review.review_digest:
        return _error(
            CONSUMER_REVIEW_MISMATCH,
            "consumer Finalize digest does not match the reviewed basket",
        )
    terminal: list[ConsumerTerminalItem] = []
    for item in review.items:
        setup = item.setup is not None
        plan = item.plan
        if isinstance(plan, LifecycleItem):
            terminal.append(_lifecycle_terminal(plan, setup, key=item.key))
            continue
        if isinstance(plan, InstallPlan):
            result = finalize_install(
                plan,
                plan.review_digest,
                context.catalog,
                context.effective,
                ports,
            )
            if isinstance(result, Err):
                terminal.append(
                    ConsumerTerminalItem(
                        item.key,
                        "failed",
                        _detail(result.diagnostics),
                        "skipped" if setup else "not-required",
                    )
                )
                continue
            status = {
                InstallStatus.APPLIED: "changed",
                InstallStatus.CURRENT: "current",
                InstallStatus.CONFLICTED: "conflict",
                InstallStatus.FAILED: "failed",
            }[result.value.status]
            detail = "; ".join(
                effect.detail for effect in result.value.effects if effect.detail is not None
            )
            terminal.append(
                ConsumerTerminalItem(
                    item.key,
                    status,
                    detail,
                    "pending"
                    if setup and status in {"changed", "current"}
                    else ("skipped" if setup else "not-required"),
                )
            )
            continue
        if isinstance(plan, UpdatePlan):
            lifecycle_result = finalize_update(
                plan,
                plan.review_digest,
                context.catalog,
                context.effective,
                ports,
            )
        else:
            assert isinstance(plan, UninstallPlan)
            lifecycle_result = finalize_uninstall(plan, plan.review_digest, ports)
        if isinstance(lifecycle_result, Err):
            terminal.append(
                ConsumerTerminalItem(
                    item.key,
                    "failed",
                    _detail(lifecycle_result.diagnostics),
                )
            )
        else:
            terminal.append(_lifecycle_terminal(lifecycle_result.value, setup, key=item.key))
    return Ok(
        ConsumerOutcome(
            review.request.action,
            tuple(terminal),
            offline_last_known_good=review.request.offline,
        )
    )


def prepare_consumer_setup_queue(
    review: ConsumerReview,
    outcome: ConsumerOutcome,
    context: ConsumerContext,
    ports: SetupReadPorts,
    *,
    authorize_untrusted_source: bool = False,
    authorize_custom_entrypoint: bool = False,
) -> ConsumerSetupQueue:
    """Prepare a second, canonical Review for setup only after payload terminal states."""

    terminal = {item.key: item for item in outcome.items}
    plans = []
    failures = []
    for item in review.items:
        result = terminal.get(item.key)
        if item.setup is None or result is None or result.setup_status != "pending":
            continue
        request = SetupRequest(
            ArtifactCoordinate(item.coordinate.source, item.coordinate.artifact),
            item.profile,
            item.scope,
            authorize_untrusted_source=authorize_untrusted_source,
            authorize_custom_entrypoint=authorize_custom_entrypoint,
            platform=review.request.platform,
        )
        attempt = prepare_setup_attempt(
            request,
            context.catalog,
            context.effective,
            context.location,
            context.store_paths,
            ports,
        )
        if isinstance(attempt.result, Err):
            failures.append(
                ConsumerSetupFailure(item.key, _detail(attempt.result.diagnostics), attempt.manual)
            )
        else:
            plans.append(attempt.result.value)
    return ConsumerSetupQueue(tuple(plans), tuple(failures))


@dataclass(frozen=True, slots=True)
class ConsumerApplicationService:
    """Small typed facade injected into both terminal frontends."""

    context: ConsumerContext
    ports: ConsumerPorts
    ensure_content: ConsumerContentPort = _content_already_available

    def browse(
        self,
        target: MarketplaceTarget,
        *,
        sources: tuple[SourceAlias, ...] = (),
    ) -> Result[tuple[MarketplaceArtifactRow, ...]]:
        return browse_consumer_marketplace(target, self.context, self.ports, sources=sources)

    def resolve_uninstall(
        self,
        selectors: tuple[ArtifactSelector, ...],
        *,
        scope: str,
        profiles: tuple[str, ...],
    ) -> Result[tuple[ArtifactCoordinate, ...]]:
        """Bind an uninstall selection to what is recorded, without consulting any source."""

        # ``_state`` reads only the scope; an uninstall request cannot be built yet, because the
        # coordinates it requires are precisely what this call is resolving.
        request = ConsumerActionRequest("status", (), profiles, scope)  # type: ignore[arg-type]
        current = _state(request, self.context, self.ports)
        if isinstance(current, Err):
            return current
        # Exactly the records ``_selected_records`` will later consider, so a selector cannot resolve
        # here against a record the basket then refuses to see.
        records = select_installations(
            current.value,
            LifecycleSelection(scope, profiles=profiles),  # type: ignore[arg-type]
        )
        return resolve_installed_selectors(records, selectors, self.context.catalog)

    def prepare(self, request: ConsumerActionRequest) -> Result[ConsumerReview]:
        available = self.ensure_content(request)
        if isinstance(available, Err):
            return available
        return prepare_consumer_action(request, self.context, self.ports)

    def finalize(self, review: ConsumerReview, reviewed_digest) -> Result[ConsumerOutcome]:
        return finalize_consumer_action(
            review,
            reviewed_digest,
            self.context,
            self.ports,
        )

    def setup_queue(
        self,
        review: ConsumerReview,
        outcome: ConsumerOutcome,
        *,
        authorize_untrusted_source: bool = False,
        authorize_custom_entrypoint: bool = False,
    ) -> ConsumerSetupQueue:
        return prepare_consumer_setup_queue(
            review,
            outcome,
            self.context,
            self.ports,
            authorize_untrusted_source=authorize_untrusted_source,
            authorize_custom_entrypoint=authorize_custom_entrypoint,
        )

    def finalize_setup_queue(
        self,
        queue: ConsumerSetupQueue,
        *,
        consent: Consent,
        stop_on_failure: bool = False,
        runtime: SetupRuntime | None = None,
    ) -> SetupQueueOutcome:
        return execute_setup_queue(
            queue.plans,
            tuple(plan.review_digest for plan in queue.plans),
            self.context.catalog,
            self.context.effective,
            self.ports,
            production_runtime() if runtime is None else runtime,
            consent=consent,
            stop_on_failure=stop_on_failure,
        )


__all__ = [
    "CONSUMER_INVALID",
    "CONSUMER_REVIEW_MISMATCH",
    "ConsumerApplicationService",
    "ConsumerContentPort",
    "ConsumerPorts",
    "finalize_consumer_action",
    "prepare_consumer_setup_queue",
    "prepare_consumer_action",
]
