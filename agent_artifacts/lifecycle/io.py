"""Local no-follow adapter for reviewed canonical lifecycle mutations."""

from __future__ import annotations

from pathlib import Path

from agent_artifacts.application.store import (
    ReferenceUpdatePorts,
    ReferenceUpdateRequest,
    replace_references,
)
from agent_artifacts.domain.identifiers import ObjectDigest
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.install_state.schema import install_state_bytes
from agent_artifacts.installation.io import (
    LocalInstallAdapter,
    _lock,
    _remove,
    _restore,
    _write_atomic,
)
from agent_artifacts.installation.model import file_snapshot_digest
from agent_artifacts.io.reference_store import read_references, write_references
from agent_artifacts.io.store_lock import acquire_store_lock, release_store_lock
from agent_artifacts.store.model import ReferenceIndex, ReferenceKind, ReferenceReadRequest

from .application import LifecycleApplyPorts
from .model import (
    LifecycleEffect,
    LifecycleItem,
    LifecycleKey,
    LifecycleStatus,
    ScopeTeardown,
    UninstallOperation,
    UninstallPlan,
)


def _replace_installed_reference(
    plan: UninstallPlan, digests: tuple[ObjectDigest, ...]
) -> Result[ReferenceIndex]:
    return replace_references(
        ReferenceUpdateRequest(
            plan.object_store_paths,
            ReferenceKind.INSTALLED,
            plan.reference_owner,
            tuple(digests),
        ),
        ReferenceUpdatePorts(
            acquire_store_lock,
            release_store_lock,
            read_references,
            write_references,
        ),
    )


def _owner_digests(index: ReferenceIndex, plan: UninstallPlan) -> tuple[ObjectDigest, ...]:
    return tuple(
        reference.digest
        for reference in index.references
        if reference.kind is ReferenceKind.INSTALLED and reference.owner == plan.reference_owner
    )


def _apply_operation(operation: UninstallOperation) -> None:
    path = Path(operation.absolute_destination)
    if operation.mutation == "none":
        return
    if operation.mutation == "remove":
        _remove(path)
        return
    _write_atomic(path, operation.replacement_content)


def _diagnostic_detail(result: Err) -> str:
    return "; ".join(diagnostic.message for diagnostic in result.diagnostics)


def _remove_if_empty(path: Path) -> None:
    """Remove ``path`` only if it is a real, empty directory.

    ``rmdir`` is the guard rather than a check preceding one: a directory holding anything at all —
    foreign content, or a concurrent installation's files — refuses to go, and refusing is the
    outcome this wants.
    """

    try:
        path.rmdir()
    except OSError:
        return


def _tear_down(teardown: ScopeTeardown) -> str:
    """Reclaim what the uninstall emptied, reporting rather than raising.

    This runs after the uninstall it belongs to has been proven, so nothing here may fail the
    operation: the artifact really is gone, and rolling a proven removal back over leftover litter
    would trade a correct result for an incorrect one.  What is left behind is named in the item's
    detail instead.
    """

    for directory in teardown.directories:
        _remove_if_empty(Path(directory))
    if not teardown.reclaims_state:
        return ""
    try:
        _remove(Path(teardown.state_path))
        _remove(Path(teardown.state_lock_path))
    except OSError as error:
        return f"installation state left in place: {error}"
    _remove_if_empty(Path(teardown.state_root))
    return ""


class LocalLifecycleAdapter(LocalInstallAdapter, LifecycleApplyPorts):
    """Install-compatible adapter with transactional proven-effect uninstall."""

    def read_references(self, request: ReferenceReadRequest) -> Result[ReferenceIndex]:
        return read_references(request)

    def apply_uninstall_plan(self, plan: UninstallPlan) -> Result[LifecycleItem]:
        attempted: list[UninstallOperation] = []
        state_attempted = False
        released_reference = False
        release_warning = ""
        try:
            with _lock(Path(plan.state_lock_path)):
                state = self.inspect_path(plan.state_path)
                references = self.read_references(ReferenceReadRequest(plan.object_store_paths))
                if (
                    not isinstance(state, Ok)
                    or state.value != plan.state_precondition
                    or not isinstance(references, Ok)
                    or references.value != plan.reference_precondition
                ):
                    return Ok(
                        LifecycleItem(
                            LifecycleKey.from_record(plan.record),
                            LifecycleStatus.CONFLICT,
                            detail="state or object references changed after Review",
                        )
                    )
                for operation in plan.operations:
                    observed = self.inspect_path(operation.absolute_destination)
                    if not isinstance(observed, Ok) or observed.value != operation.precondition:
                        return Ok(
                            LifecycleItem(
                                LifecycleKey.from_record(plan.record),
                                LifecycleStatus.CONFLICT,
                                detail=f"destination changed after Review: {operation.effect.destination}",
                            )
                        )
                for operation in plan.operations:
                    if operation.mutation == "none":
                        continue
                    attempted.append(operation)
                    _apply_operation(operation)
                    observed = self.inspect_path(operation.absolute_destination)
                    if isinstance(observed, Err):
                        raise OSError(_diagnostic_detail(observed))
                    if operation.mutation == "remove" and observed.value.kind != "absent":
                        raise OSError(
                            f"destination removal did not take effect: {operation.effect.destination}"
                        )
                    if operation.mutation == "write" and (
                        observed.value.kind != "file"
                        or observed.value.digest
                        != file_snapshot_digest(operation.replacement_content)
                    ):
                        raise OSError(
                            f"destination replacement did not take effect: "
                            f"{operation.effect.destination}"
                        )
                state_attempted = True
                replacement_state = install_state_bytes(plan.replacement_state)
                _write_atomic(Path(plan.state_path), replacement_state)
                observed_state = self.inspect_path(plan.state_path)
                if isinstance(observed_state, Err):
                    raise OSError(_diagnostic_detail(observed_state))
                if (
                    observed_state.value.kind != "file"
                    or observed_state.value.digest != file_snapshot_digest(replacement_state)
                ):
                    raise OSError("installation state replacement did not take effect")
                released = _replace_installed_reference(plan, ())
                if isinstance(released, Err):
                    current = self.read_references(ReferenceReadRequest(plan.object_store_paths))
                    if isinstance(current, Ok) and current.value == plan.reference_replacement:
                        released_reference = True
                        release_warning = (
                            "object reference released; store-lock cleanup reported a warning"
                        )
                    else:
                        raise OSError(_diagnostic_detail(released))
                else:
                    current = self.read_references(ReferenceReadRequest(plan.object_store_paths))
                    released_reference = isinstance(current, Ok) and not _owner_digests(
                        current.value, plan
                    )
                    if (
                        released.value != plan.reference_replacement
                        or not isinstance(current, Ok)
                        or current.value != plan.reference_replacement
                    ):
                        raise OSError("object references changed after Review")
                    released_reference = True
                effects = tuple(
                    LifecycleEffect(
                        operation.effect.kind,
                        operation.effect.destination,
                        (
                            LifecycleStatus.CURRENT
                            if operation.mutation == "none"
                            else LifecycleStatus.CHANGED
                        ),
                    )
                    for operation in plan.operations
                )
                # Teardown runs inside the scope lock, and removes that lock's own file last.  The
                # descriptor stays valid across the unlink, so the exclusion this holds outlives
                # the path; anything arriving afterwards creates the scope again from nothing.
                litter = "" if plan.teardown is None else _tear_down(plan.teardown)
                return Ok(
                    LifecycleItem(
                        LifecycleKey.from_record(plan.record),
                        LifecycleStatus.REMOVED,
                        effects,
                        "; ".join(item for item in (release_warning, litter) if item),
                    )
                )
        except (OSError, RuntimeError, ValueError) as error:
            rollback_errors: list[str] = []
            if released_reference:
                expected_digests = _owner_digests(plan.reference_precondition, plan)
                restored = _replace_installed_reference(plan, expected_digests)
                restored_index = (
                    self.read_references(ReferenceReadRequest(plan.object_store_paths))
                    if isinstance(restored, Err)
                    else restored
                )
                if not isinstance(restored_index, Ok) or (
                    _owner_digests(restored_index.value, plan) != expected_digests
                ):
                    rollback_errors.append("installed object reference restore failed")
            if state_attempted:
                try:
                    _restore(plan.state_precondition)
                    restored_state = self.inspect_path(plan.state_path)
                    if (
                        not isinstance(restored_state, Ok)
                        or restored_state.value != plan.state_precondition
                    ):
                        rollback_errors.append("state: restore verification failed")
                except OSError as rollback_error:
                    rollback_errors.append(f"state: {rollback_error}")
            for operation in reversed(attempted):
                try:
                    _restore(operation.precondition)
                    restored_effect = self.inspect_path(operation.absolute_destination)
                    if (
                        not isinstance(restored_effect, Ok)
                        or restored_effect.value != operation.precondition
                    ):
                        rollback_errors.append(
                            f"{operation.effect.destination}: restore verification failed"
                        )
                except OSError as rollback_error:
                    rollback_errors.append(f"{operation.effect.destination}: {rollback_error}")
            detail = str(error)
            if rollback_errors:
                detail += "; rollback incomplete: " + "; ".join(rollback_errors)
            return Ok(
                LifecycleItem(
                    LifecycleKey.from_record(plan.record),
                    LifecycleStatus.FAILED,
                    detail=detail,
                )
            )
