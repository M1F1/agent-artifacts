"""Prepare/review/finalize orchestration for canonical post-install setup."""

from __future__ import annotations

import posixpath
from dataclasses import dataclass, replace
from typing import Callable, Protocol, Sequence, cast

from agent_artifacts.configuration.model import SourceKind, git_location_parts
from agent_artifacts.configuration.policy import (
    EffectiveConfiguration,
)
from agent_artifacts.configuration.schema import organization_policy_bytes
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import ArtifactIdentity, ObjectDigest
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.install_state.model import (
    ArtifactEvidence,
    InstallationRecord,
    InstallStatePaths,
    SourceEvidence,
)
from agent_artifacts.install_state.paths import install_state_paths
from agent_artifacts.installation.application import InstallReadPorts
from agent_artifacts.installation.model import InstallLocation, PathSnapshot
from agent_artifacts.marketplace.catalog import resolve_artifact
from agent_artifacts.marketplace.model import (
    ArtifactQuery,
    MarketplaceCatalog,
    MarketplaceItem,
    TrustClass,
)
from agent_artifacts.model import (
    ArtifactType,
    SetupEffect,
    SetupInstaller,
    SetupQueueItem,
    SetupStateRecord,
)
from agent_artifacts.model import (
    Err as LegacyErr,
)
from agent_artifacts.protocol.capabilities import Capability
from agent_artifacts.protocol.hashing import json_digest, sha256_bytes
from agent_artifacts.protocol.json import JsonArray, JsonObject
from agent_artifacts.protocol.native_models import ArtifactManifest
from agent_artifacts.protocol.native_tree import (
    SnapshotEntry,
    SnapshotEntryKind,
    compile_native_package,
)
from agent_artifacts.protocol.paths import SafeRelativePath, parse_relative_path
from agent_artifacts.redaction import redact_text
from agent_artifacts.setup import (
    manual_reference,
    parse_setup_state,
    plan_setup,
    planned_capabilities,
    receipt_matches_plan,
)
from agent_artifacts.setup_runtime import SetupRuntime, apply_setup_plan, rollback_record
from agent_artifacts.store.model import (
    ObjectReadRequest,
    ObjectStorePaths,
    ReferenceIndex,
    ReferenceKind,
    ReferenceReadRequest,
    StoredObject,
)

from .model import (
    CanonicalSetupAttempt,
    CanonicalSetupPlan,
    PayloadStatus,
    SetupExecutionStatus,
    SetupOutcome,
    SetupQueueOutcome,
    SetupRequest,
    setup_review_value,
)

SETUP_INVALID = DiagnosticCode("setup-invalid")
SETUP_OBJECT_UNAVAILABLE = DiagnosticCode("setup-object-unavailable")
SETUP_POLICY_DENIED = DiagnosticCode("setup-policy-denied")
SETUP_REVIEW_MISMATCH = DiagnosticCode("setup-review-mismatch")

Consent = Callable[[SetupEffect], bool]


class SetupReadPorts(InstallReadPorts, Protocol):
    def read_references(self, request: ReferenceReadRequest) -> Result[ReferenceIndex]: ...


class SetupApplyPorts(SetupReadPorts, Protocol):
    def persist_setup(
        self,
        plan: CanonicalSetupPlan,
        record: SetupStateRecord,
        *,
        expected_record: SetupStateRecord | None,
    ) -> Result[None]: ...


def _error(
    code: DiagnosticCode,
    message: str,
    remediation: tuple[str, ...] = (),
) -> Err:
    return Err(
        (
            Diagnostic(
                code,
                Severity.ERROR,
                _redact(message),
                remediation=tuple(_redact(item) for item in remediation),
            ),
        )
    )


def _redact(value: str) -> str:
    # One redactor, applied once.  This used to compose the configuration redactor with the setup
    # redactor because they had different rules and neither was a superset of the other — which is
    # precisely the arrangement that let `LAF-72` through, since the weaker of the two was the one
    # on the write-to-disk path.  `RR-10A` left a single function; composing it with itself would
    # only preserve the shape of the bug.
    return " ".join(redact_text(value).split())[:512]


def _configured_source(effective: EffectiveConfiguration, alias):
    return next(
        (
            source
            for source in effective.configuration.sources
            if source.enabled and source.alias == alias
        ),
        None,
    )


def _marketplace_evidence(item, effective: EffectiveConfiguration):
    configured = _configured_source(effective, item.source.alias)
    if configured is None or item.source.source_id is None or item.source.resolved_revision is None:
        return None
    try:
        source = SourceEvidence(
            item.source.alias,
            item.source.source_id,
            item.source.kind,
            item.source.origin,
            item.source.resolved_revision,
            configured.ref,
        )
        indexed = item.artifact.artifact
        artifact = ArtifactEvidence(
            indexed.identity,
            indexed.version,
            indexed.manifest_digest,
            indexed.payload_digest,
            indexed.object_digest,
        )
    except ValueError:
        return None
    return source, artifact


def _resolve_installed_item(
    record: InstallationRecord,
    catalog: MarketplaceCatalog,
    effective: EffectiveConfiguration,
):
    resolved = resolve_artifact(
        catalog,
        ArtifactQuery(
            record.artifact.identity,
            record.coordinate.source,
            str(record.artifact.version),
        ),
    )
    if isinstance(resolved, Err):
        return resolved
    evidence = _marketplace_evidence(resolved.value, effective)
    if evidence is None or evidence != (record.source, record.artifact):
        return _error(
            SETUP_INVALID,
            "installed artifact source or object evidence no longer matches the marketplace",
        )
    return resolved


def _selected_record(state, request: SetupRequest) -> InstallationRecord | None:
    return next(
        (
            record
            for record in state.installations
            if record.coordinate == request.coordinate
            and record.profile == request.profile
            and record.scope == request.scope
        ),
        None,
    )


def _setup_recipe(
    stored: StoredObject,
    record: InstallationRecord,
):
    compiled = compile_native_package(
        stored.candidate.entries,
        expected_identity=record.artifact.identity,
    )
    if isinstance(compiled, Err):
        detail = compiled.diagnostics[0].message if compiled.diagnostics else "invalid package"
        return _error(SETUP_INVALID, f"canonical setup package is invalid: {detail}")
    package = compiled.value
    manifest = package.manifest
    by_path = {str(entry.path): entry for entry in stored.candidate.entries}
    if (
        manifest.version != record.artifact.version
        or package.manifest_digest != record.artifact.manifest_digest
        or manifest.setup is None
    ):
        return _error(
            SETUP_INVALID,
            "installed object manifest identity, digest, or setup declaration is invalid",
        )
    recipe_entry = by_path.get(str(manifest.setup.recipe))
    if recipe_entry is None or recipe_entry.kind is not SnapshotEntryKind.FILE:
        return _error(SETUP_INVALID, "declared setup recipe is not a regular object file")
    installer = package.setup_installer
    if installer is None:
        return _error(SETUP_INVALID, "declared setup recipe did not compile")
    custom_path = None
    custom_entry = None
    if installer.custom_entrypoint is not None:
        parent = posixpath.dirname(str(manifest.setup.recipe))
        parsed_path = parse_relative_path(posixpath.join(parent, installer.custom_entrypoint))
        if isinstance(parsed_path, Err):
            return _error(SETUP_INVALID, "custom setup entrypoint path is invalid")
        custom_path = parsed_path.value
        custom_entry = by_path.get(str(custom_path))
        if (
            custom_entry is None
            or custom_entry.kind is not SnapshotEntryKind.FILE
            or not custom_entry.executable
        ):
            return _error(
                SETUP_INVALID,
                "custom setup entrypoint must be an executable regular object file",
            )
    return (
        manifest,
        recipe_entry,
        installer,
        custom_path,
        custom_entry,
    )


def _manual_source_url(source: SourceEvidence, identity: ArtifactIdentity) -> str:
    """Build a safe immutable web root from installation provenance when one exists."""

    if source.kind is SourceKind.SOURCE_LOCAL:
        return ""
    parts = git_location_parts(source.origin) or git_location_parts(f"https://{source.origin}")
    if parts is None:
        return ""
    host, repository = parts
    package = f"artifacts/{identity.kind}/{identity.name}"
    return f"https://{host}/{repository}/blob/{source.resolved_commit}/{package}"


def _planned_capabilities(installer: SetupInstaller) -> tuple[Capability, ...]:
    """The recipe's capability need, typed. The mapping itself lives beside the module catalog."""

    return tuple(Capability(value) for value in planned_capabilities(installer))


def _policy_allows(
    request: SetupRequest,
    trust: TrustClass,
    capabilities: tuple[Capability, ...],
    custom: bool,
    effective: EffectiveConfiguration,
) -> Result[None]:
    if trust in {TrustClass.UNVERIFIED, TrustClass.LOCAL, TrustClass.DIRECT_SOURCE} and not (
        request.authorize_untrusted_source
    ):
        return _error(
            SETUP_POLICY_DENIED,
            f"setup from {trust.value} requires explicit source authorization",
            ("re-run setup with --authorize-untrusted-source",),
        )
    allowed = effective.policy.allowed_setup_capabilities
    if allowed is not None:
        missing = tuple(item for item in capabilities if item not in set(allowed))
        if missing:
            return _error(
                SETUP_POLICY_DENIED,
                "setup capability denied by organization policy: "
                + ", ".join(str(item) for item in missing),
                ("ask the organization policy owner to allow the named setup capabilities",),
            )
    if custom and not request.authorize_custom_entrypoint:
        return _error(
            SETUP_POLICY_DENIED,
            "custom setup entrypoint requires explicit authorization",
            ("re-run setup with --authorize-custom-entrypoint",),
        )
    if custom and effective.policy.allow_custom_setup_entrypoints is False:
        return _error(
            SETUP_POLICY_DENIED,
            "custom setup entrypoints are denied by organization policy",
            ("use the verified manual setup route or ask the organization policy owner",),
        )
    return Ok(None)


def _previous_record(snapshot: PathSnapshot) -> Result[SetupStateRecord | None]:
    if snapshot.kind == "absent":
        return Ok(None)
    if snapshot.kind != "file":
        return _error(SETUP_INVALID, "setup state path is not a regular file")
    try:
        parsed = parse_setup_state(snapshot.content.decode("utf-8"))
    except UnicodeDecodeError:
        return _error(SETUP_INVALID, "setup state is not UTF-8")
    if isinstance(parsed, LegacyErr) or len(parsed.value.records) != 1:
        reason = parsed.reason if isinstance(parsed, LegacyErr) else "expected one setup record"
        return _error(SETUP_INVALID, f"setup state is invalid: {reason}")
    return Ok(parsed.value.records[0])


@dataclass(frozen=True, slots=True)
class _SetupObject:
    """One installed record and the exact object facts proven before trust and policy apply."""

    state_paths: InstallStatePaths
    record: InstallationRecord
    item: MarketplaceItem
    stored: StoredObject
    manifest: ArtifactManifest
    recipe_entry: SnapshotEntry
    custom_path: SafeRelativePath | None
    custom_entry: SnapshotEntry | None
    queue_item: SetupQueueItem


def _prepare_setup_object(
    request: SetupRequest,
    catalog: MarketplaceCatalog,
    effective: EffectiveConfiguration,
    location: InstallLocation,
    store_paths: ObjectStorePaths,
    ports: SetupReadPorts,
) -> Result[_SetupObject]:
    """Resolve and validate the installed object, including any required manual document."""

    state_paths = install_state_paths(
        request.scope,
        project_root=location.project_root,
        user_home=location.user_home,
        data_root=location.data_root,
    )
    state = ports.read_state(state_paths.destination_path)
    if isinstance(state, Err):
        return state
    if state.value is None:
        return _error(SETUP_INVALID, "setup requires an installed payload")
    record = _selected_record(state.value, request)
    if record is None:
        return _error(SETUP_INVALID, "setup requires the selected installed artifact/profile")
    resolved = _resolve_installed_item(record, catalog, effective)
    if isinstance(resolved, Err):
        return resolved
    item = resolved.value
    loaded = ports.read_object(ObjectReadRequest(store_paths, record.artifact.object_digest))
    if isinstance(loaded, Err):
        return loaded
    if loaded.value is None:
        return _error(
            SETUP_OBJECT_UNAVAILABLE,
            f"installed setup object is unavailable: {record.coordinate}",
        )
    stored = loaded.value
    if stored.candidate.digest != record.artifact.object_digest:
        return _error(SETUP_INVALID, "loaded setup object digest is invalid")
    recipe = _setup_recipe(stored, record)
    if isinstance(recipe, Err):
        return recipe
    manifest, recipe_entry, installer, custom_path, custom_entry = recipe
    return Ok(
        _SetupObject(
            state_paths,
            record,
            item,
            stored,
            manifest,
            recipe_entry,
            custom_path,
            custom_entry,
            SetupQueueItem(
                cast(ArtifactType, record.artifact.identity.kind),
                record.artifact.identity.name,
                record.profile,
                record.scope,
                str(record.coordinate.source),
                stored.root,
                installer,
                _manual_source_url(record.source, record.artifact.identity),
                str(record.artifact.version),
            ),
        )
    )


def prepare_setup_attempt(
    request: SetupRequest,
    catalog: MarketplaceCatalog,
    effective: EffectiveConfiguration,
    location: InstallLocation,
    store_paths: ObjectStorePaths,
    ports: SetupReadPorts,
) -> CanonicalSetupAttempt:
    """Plan setup and keep the verified manual route even when trust or policy denies the plan."""

    prepared = _prepare_setup_object(request, catalog, effective, location, store_paths, ports)
    if isinstance(prepared, Err):
        return CanonicalSetupAttempt(prepared)
    return CanonicalSetupAttempt(
        _prepare_setup_plan(prepared.value, request, effective, location, store_paths, ports),
        manual_reference(prepared.value.queue_item),
    )


def prepare_setup(
    request: SetupRequest,
    catalog: MarketplaceCatalog,
    effective: EffectiveConfiguration,
    location: InstallLocation,
    store_paths: ObjectStorePaths,
    ports: SetupReadPorts,
) -> Result[CanonicalSetupPlan]:
    """Build a non-secret plan from one installed record and its exact CAS object."""

    return prepare_setup_attempt(request, catalog, effective, location, store_paths, ports).result


def _prepare_setup_plan(
    prepared: _SetupObject,
    request: SetupRequest,
    effective: EffectiveConfiguration,
    location: InstallLocation,
    store_paths: ObjectStorePaths,
    ports: SetupReadPorts,
) -> Result[CanonicalSetupPlan]:
    """Bind trust, policy, effect plan, and durable preconditions to one validated object."""

    state_paths = prepared.state_paths
    record = prepared.record
    item = prepared.item
    stored = prepared.stored
    manifest = prepared.manifest
    recipe_entry = prepared.recipe_entry
    custom_path = prepared.custom_path
    custom_entry = prepared.custom_entry
    queue_item = prepared.queue_item
    installer = queue_item.installer
    assert manifest.setup is not None
    target_root = location.project_root if request.scope == "project" else location.user_home
    legacy_plan = plan_setup(
        queue_item,
        target_root=target_root,
        home_root=location.user_home,
        run_root=location.data_root,
        platform=request.platform,
    )
    capabilities = _planned_capabilities(installer)
    indexed_setup = item.artifact.artifact.setup
    if (
        indexed_setup is None
        or indexed_setup.recipe != manifest.setup.recipe
        or indexed_setup.platforms != manifest.setup.platforms
        or (indexed_setup.capabilities and indexed_setup.capabilities != capabilities)
    ):
        return _error(
            SETUP_INVALID,
            "compiled setup recipe, platform, or capability evidence does not match the object",
        )
    allowed = _policy_allows(
        request,
        item.trust.kind,
        capabilities,
        custom_path is not None,
        effective,
    )
    if isinstance(allowed, Err):
        return allowed
    capability_plan_digest = json_digest(
        JsonObject(
            (
                ("capabilities", JsonArray(tuple(str(value) for value in capabilities))),
                ("effect_plan_digest", f"sha256:{legacy_plan.plan_hash}"),
            )
        )
    )
    identity = json_digest(
        JsonObject(
            (
                ("coordinate", str(request.coordinate)),
                ("profile", request.profile),
                ("scope", request.scope),
                ("install_state_path", state_paths.destination_path),
            )
        )
    )
    setup_state_ref = f"setup-{identity.value[:48]}"
    state_path = posixpath.join(
        location.data_root,
        "state",
        "setup",
        f"{setup_state_ref}.json",
    )
    state_snapshot = ports.inspect_path(state_path)
    if isinstance(state_snapshot, Err):
        return state_snapshot
    previous = _previous_record(state_snapshot.value)
    if isinstance(previous, Err):
        return previous
    references = ports.read_references(ReferenceReadRequest(store_paths))
    if isinstance(references, Err):
        return references
    owner = f"setup/{setup_state_ref}"
    owner_references = tuple(
        sorted(
            (
                reference.digest
                for reference in references.value.references
                if reference.kind is ReferenceKind.SETUP and reference.owner == owner
            ),
            key=str,
        )
    )
    placeholder = sha256_bytes(b"unreviewed-setup-plan")
    try:
        plan = CanonicalSetupPlan(
            request,
            record,
            state_paths.destination_path,
            state_paths.lock_path,
            item.trust.kind.value,
            item.trust.evidence_digest,
            sha256_bytes(organization_policy_bytes(effective.policy)),
            store_paths,
            stored.candidate,
            stored.root,
            stored.candidate.digest,
            manifest.setup.recipe,
            sha256_bytes(recipe_entry.content),
            custom_path,
            None if custom_entry is None else sha256_bytes(custom_entry.content),
            capabilities,
            capability_plan_digest,
            legacy_plan,
            setup_state_ref,
            state_path,
            state_snapshot.value,
            previous.value,
            owner,
            owner_references,
            placeholder,
        )
        return Ok(replace(plan, review_digest=json_digest(setup_review_value(plan))))
    except ValueError as error:
        return _error(SETUP_INVALID, f"canonical setup plan is invalid: {error}")


def _selected_state_matches(plan: CanonicalSetupPlan, ports: SetupReadPorts) -> bool:
    state = ports.read_state(plan.install_state_path)
    return (
        isinstance(state, Ok)
        and state.value is not None
        and _selected_record(state.value, plan.request) == plan.installation
    )


def _preconditions_current(
    plan: CanonicalSetupPlan,
    catalog: MarketplaceCatalog,
    effective: EffectiveConfiguration,
    ports: SetupReadPorts,
) -> bool:
    if sha256_bytes(organization_policy_bytes(effective.policy)) != plan.policy_digest:
        return False
    current = _resolve_installed_item(plan.installation, catalog, effective)
    if not isinstance(current, Ok):
        return False
    if (
        current.value.trust.kind.value != plan.trust
        or current.value.trust.evidence_digest != plan.trust_evidence_digest
    ):
        return False
    loaded = ports.read_object(ObjectReadRequest(plan.object_store_paths, plan.object_digest))
    if (
        not isinstance(loaded, Ok)
        or loaded.value is None
        or loaded.value.candidate != plan.object_candidate
        or loaded.value.root != plan.object_root
    ):
        return False
    if not _selected_state_matches(plan, ports):
        return False
    state = ports.inspect_path(plan.setup_state_path)
    if not isinstance(state, Ok) or state.value != plan.setup_state_precondition:
        return False
    references = ports.read_references(ReferenceReadRequest(plan.object_store_paths))
    if not isinstance(references, Ok):
        return False
    current_owner = tuple(
        sorted(
            (
                reference.digest
                for reference in references.value.references
                if reference.kind is ReferenceKind.SETUP
                and reference.owner == plan.setup_reference_owner
            ),
            key=str,
        )
    )
    return current_owner == plan.setup_reference_precondition


_LEGACY_STATUS = {
    "configured": SetupExecutionStatus.CONFIGURED,
    "already_configured": SetupExecutionStatus.ALREADY_CONFIGURED,
    "cancelled": SetupExecutionStatus.CANCELLED,
    "skipped": SetupExecutionStatus.SKIPPED,
    "unsupported": SetupExecutionStatus.UNSUPPORTED,
    "prerequisite_missing": SetupExecutionStatus.PREREQUISITE_MISSING,
    "apply_failed_rolled_back": SetupExecutionStatus.APPLY_FAILED_ROLLED_BACK,
    "rollback_incomplete": SetupExecutionStatus.ROLLBACK_INCOMPLETE,
    "verification_failed": SetupExecutionStatus.VERIFICATION_FAILED,
}


def _outcome(
    plan: CanonicalSetupPlan,
    status: SetupExecutionStatus,
    detail: str,
    *,
    state_written: bool,
    record: SetupStateRecord | None = None,
) -> SetupOutcome:
    return SetupOutcome(
        plan.request.coordinate,
        plan.request.profile,
        plan.request.scope,
        PayloadStatus.INSTALLED,
        status,
        _redact(detail),
        plan.review_digest,
        plan.setup_state_ref,
        state_written,
        record,
    )


def _bound_record(plan: CanonicalSetupPlan, record: SetupStateRecord) -> SetupStateRecord:
    return replace(
        record,
        object_digest=str(plan.object_digest),
        recipe_digest=str(plan.recipe_digest),
        trust=plan.trust,
        trust_evidence_digest=str(plan.trust_evidence_digest),
        policy_digest=str(plan.policy_digest),
        capability_plan_digest=str(plan.capability_plan_digest),
        canonical_review_digest=str(plan.review_digest),
        setup_state_ref=plan.setup_state_ref,
    )


def finalize_setup(
    plan: CanonicalSetupPlan,
    reviewed_digest: ObjectDigest,
    catalog: MarketplaceCatalog,
    effective: EffectiveConfiguration,
    ports: SetupApplyPorts,
    runtime: SetupRuntime,
    *,
    consent: Consent,
) -> Result[SetupOutcome]:
    """Run only the reviewed setup against unchanged object/trust/policy evidence."""

    if reviewed_digest != plan.review_digest:
        return _error(SETUP_REVIEW_MISMATCH, "finalize digest does not match the reviewed setup")
    if runtime.platform != plan.request.platform or not _preconditions_current(
        plan, catalog, effective, ports
    ):
        return Ok(
            _outcome(
                plan,
                SetupExecutionStatus.CONFLICTED,
                "object, installation, source trust, policy, setup state, or reference changed after review",
                state_written=False,
            )
        )
    applied = _bound_record(plan, apply_setup_plan(plan.legacy_plan, runtime, consent=consent))
    persisted = ports.persist_setup(plan, applied, expected_record=plan.previous_record)
    if isinstance(persisted, Err):
        persistence_detail = "; ".join(item.message for item in persisted.diagnostics)
        recovery = rollback_record(applied, runtime) if applied.receipt else applied
        status = (
            SetupExecutionStatus.ROLLBACK_INCOMPLETE
            if recovery.status == "rollback_incomplete"
            else SetupExecutionStatus.FAILED
        )
        if status is SetupExecutionStatus.FAILED:
            detail = (
                f"setup state persistence failed: {persistence_detail}; "
                "applied effects were compensated"
            )
            # A compensated receipt is evidence of what happened, not a second undo recipe.
            # Keep every step for `receipt show`, mark it explicitly, and teach the receipt
            # readers below to make no live-world claim from it.
            failure_record = replace(
                recovery,
                status="apply_failed_rolled_back",
                detail=detail,
                exit_status=1,
                rollback_command="",
                receipt=tuple(
                    {**dict(receipt), "setup_disposition": "compensated"}
                    for receipt in applied.receipt
                ),
            )
        else:
            detail = (
                f"setup state persistence failed: {persistence_detail}; "
                "effect rollback was incomplete"
            )
            failure_record = replace(recovery, detail=detail, exit_status=1)

        # The original failure may be a transient write error. After compensation, make one
        # best-effort write of the failure evidence through the same transactional adapter. If
        # the storage failure persists we still return the original specific cause, plus the
        # reason the receipt could not be retained.
        failure_persisted = ports.persist_setup(
            plan,
            failure_record,
            expected_record=plan.previous_record,
        )
        state_written = isinstance(failure_persisted, Ok)
        if isinstance(failure_persisted, Err):
            receipt_detail = "; ".join(item.message for item in failure_persisted.diagnostics)
            detail += f"; failure receipt was not persisted: {receipt_detail}"
        return Ok(
            _outcome(
                plan,
                status,
                detail,
                state_written=state_written,
                record=_bound_record(plan, failure_record),
            )
        )
    return Ok(
        _outcome(
            plan,
            _LEGACY_STATUS[applied.status],
            applied.detail,
            state_written=True,
            record=applied,
        )
    )


def _failed(plan: CanonicalSetupPlan, error: Err) -> SetupOutcome:
    return _outcome(
        plan,
        SetupExecutionStatus.FAILED,
        "; ".join(item.message for item in error.diagnostics),
        state_written=False,
    )


def execute_setup_queue(
    plans: Sequence[CanonicalSetupPlan],
    reviewed_digests: Sequence[ObjectDigest],
    catalog: MarketplaceCatalog,
    effective: EffectiveConfiguration,
    ports: SetupApplyPorts,
    runtime: SetupRuntime,
    *,
    consent: Consent,
    stop_on_failure: bool = False,
) -> SetupQueueOutcome:
    """Execute reviewed items sequentially and emit one payload/setup outcome per item."""

    if len(plans) != len(reviewed_digests):
        raise ValueError("each setup plan requires one reviewed digest")
    items: list[SetupOutcome] = []
    stopped = False
    for plan, reviewed in zip(plans, reviewed_digests, strict=True):
        if stopped:
            items.append(
                _outcome(
                    plan,
                    SetupExecutionStatus.SKIPPED,
                    "setup queue stopped after an incomplete item",
                    state_written=False,
                )
            )
            continue
        result = finalize_setup(
            plan,
            reviewed,
            catalog,
            effective,
            ports,
            runtime,
            consent=consent,
        )
        outcome = _failed(plan, result) if isinstance(result, Err) else result.value
        items.append(outcome)
        stopped = stop_on_failure and not outcome.successful
    return SetupQueueOutcome(tuple(items))


def retryable_plans(
    plans: Sequence[CanonicalSetupPlan], outcome: SetupQueueOutcome
) -> tuple[CanonicalSetupPlan, ...]:
    """Select only incomplete exact queue identities for a newly prepared retry."""

    incomplete = {item.key for item in outcome.items if not item.successful}
    return tuple(
        plan
        for plan in plans
        if (str(plan.request.coordinate), plan.request.profile, plan.request.scope) in incomplete
    )


def rollback_setup(
    plan: CanonicalSetupPlan,
    outcome: SetupOutcome,
    ports: SetupApplyPorts,
    runtime: SetupRuntime,
) -> Result[SetupOutcome]:
    """Rollback only receipts bound to the exact canonical reviewed setup plan."""

    record = outcome.record
    receipts_match = record is not None and all(
        receipt_matches_plan(receipt, plan.legacy_plan) for receipt in record.receipt
    )
    if (
        record is None
        or not outcome.successful
        or record.canonical_review_digest != str(plan.review_digest)
        or record.object_digest != str(plan.object_digest)
        or record.setup_state_ref != plan.setup_state_ref
        or not receipts_match
    ):
        return _error(SETUP_REVIEW_MISMATCH, "setup rollback receipt is not review-bound")
    current_state = ports.inspect_path(plan.setup_state_path)
    if not isinstance(current_state, Ok):
        return current_state
    current_record = _previous_record(current_state.value)
    references = ports.read_references(ReferenceReadRequest(plan.object_store_paths))
    current_owner = (
        ()
        if not isinstance(references, Ok)
        else tuple(
            sorted(
                (
                    reference.digest
                    for reference in references.value.references
                    if reference.kind is ReferenceKind.SETUP
                    and reference.owner == plan.setup_reference_owner
                ),
                key=str,
            )
        )
    )
    if (
        not isinstance(current_record, Ok)
        or current_record.value != record
        or current_owner != (plan.object_digest,)
    ):
        return _error(
            SETUP_REVIEW_MISMATCH,
            "durable setup state or object reference changed before rollback",
        )
    rolled = _bound_record(plan, rollback_record(record, runtime))
    persisted = ports.persist_setup(plan, rolled, expected_record=record)
    if isinstance(persisted, Err):
        return persisted
    status = (
        SetupExecutionStatus.ROLLED_BACK
        if rolled.status == "skipped"
        else SetupExecutionStatus.ROLLBACK_INCOMPLETE
    )
    return Ok(
        _outcome(
            plan,
            status,
            rolled.detail,
            state_written=True,
            record=rolled,
        )
    )


def setup_outcome_event(outcome: SetupOutcome) -> dict[str, object]:
    """Return the bounded allowlist projection suitable for future analytics/reporting."""

    return {
        "schema_version": 1,
        "artifact": str(outcome.coordinate),
        "profile": outcome.profile,
        "scope": outcome.scope,
        "payload_status": outcome.payload_status.value,
        "setup_status": outcome.setup_status.value,
        "detail": _redact(outcome.detail),
        "review_digest": str(outcome.review_digest),
        "setup_state_ref": outcome.setup_state_ref,
        "state_written": outcome.state_written,
    }
