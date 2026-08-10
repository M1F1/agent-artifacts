"""Local transactional persistence adapter for canonical setup evidence."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from agent_artifacts.application.store import (
    ReferenceUpdatePorts,
    ReferenceUpdateRequest,
    replace_references,
)
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.install_state.model import InstallationRecord, InstallState
from agent_artifacts.install_state.schema import install_state_bytes
from agent_artifacts.installation.io import LocalInstallAdapter, _lock, _restore, _write_atomic
from agent_artifacts.io.reference_store import read_references, write_references
from agent_artifacts.io.store_lock import acquire_store_lock, release_store_lock
from agent_artifacts.model import Err as LegacyErr
from agent_artifacts.model import SetupState, SetupStateRecord
from agent_artifacts.setup import dump_setup_state, parse_setup_state
from agent_artifacts.store.model import (
    ReferenceIndex,
    ReferenceKind,
    ReferenceReadRequest,
)

from .application import SetupApplyPorts
from .model import CanonicalSetupPlan

SETUP_IO_FAILED = DiagnosticCode("setup-io-failed")


def _error(message: str) -> Err:
    return Err((Diagnostic(SETUP_IO_FAILED, Severity.ERROR, message),))


def _selected(state: InstallState, plan: CanonicalSetupPlan) -> InstallationRecord | None:
    return next(
        (
            record
            for record in state.installations
            if record.coordinate == plan.request.coordinate
            and record.profile == plan.request.profile
            and record.scope == plan.request.scope
        ),
        None,
    )


def _owner_digests(index: ReferenceIndex, plan: CanonicalSetupPlan):
    return tuple(
        sorted(
            (
                reference.digest
                for reference in index.references
                if reference.kind is ReferenceKind.SETUP
                and reference.owner == plan.setup_reference_owner
            ),
            key=str,
        )
    )


def _replace_setup_reference(plan: CanonicalSetupPlan, retain: bool) -> Result[ReferenceIndex]:
    return replace_references(
        ReferenceUpdateRequest(
            plan.object_store_paths,
            ReferenceKind.SETUP,
            plan.setup_reference_owner,
            (plan.object_digest,) if retain else (),
        ),
        ReferenceUpdatePorts(
            acquire_store_lock,
            release_store_lock,
            read_references,
            write_references,
        ),
    )


class LocalSetupAdapter(LocalInstallAdapter, SetupApplyPorts):
    """Persist setup record, install-state pointer, and CAS reference as one compensated unit."""

    def read_references(self, request: ReferenceReadRequest) -> Result[ReferenceIndex]:
        return read_references(request)

    def persist_setup(
        self,
        plan: CanonicalSetupPlan,
        record: SetupStateRecord,
        *,
        expected_record: SetupStateRecord | None,
    ) -> Result[None]:
        setup_before = None
        install_before = None
        wrote_setup = False
        wrote_install = False
        try:
            with _lock(Path(plan.install_state_lock_path)):
                state = self.read_state(plan.install_state_path)
                if not isinstance(state, Ok) or state.value is None:
                    return _error("installed payload state is unavailable during setup persistence")
                current_installation = _selected(state.value, plan)
                expected_installations = {
                    plan.installation,
                    replace(plan.installation, setup_state_ref=plan.setup_state_ref),
                }
                if current_installation not in expected_installations:
                    return _error("installed payload changed before setup persistence")
                setup_before_result = self.inspect_path(plan.setup_state_path)
                install_before_result = self.inspect_path(plan.install_state_path)
                references = self.read_references(ReferenceReadRequest(plan.object_store_paths))
                if (
                    not isinstance(setup_before_result, Ok)
                    or not isinstance(install_before_result, Ok)
                    or not isinstance(references, Ok)
                ):
                    return _error("setup persistence preconditions cannot be inspected")
                setup_before = setup_before_result.value
                install_before = install_before_result.value
                if expected_record is None:
                    state_matches = setup_before == plan.setup_state_precondition
                    reference_matches = (
                        _owner_digests(references.value, plan) == plan.setup_reference_precondition
                    )
                else:
                    try:
                        parsed_setup = parse_setup_state(setup_before.content.decode("utf-8"))
                    except UnicodeDecodeError:
                        parsed_setup = None
                    state_matches = (
                        setup_before.kind == "file"
                        and parsed_setup is not None
                        and not isinstance(parsed_setup, LegacyErr)
                        and parsed_setup.value.records == (expected_record,)
                    )
                    reference_matches = _owner_digests(references.value, plan) == (
                        plan.object_digest,
                    )
                if not state_matches or not reference_matches:
                    return _error("setup state or object reference changed after Review")
                replacement_record = replace(
                    current_installation,
                    setup_state_ref=plan.setup_state_ref,
                )
                replacement_state = InstallState(
                    2,
                    tuple(
                        replacement_record if item.key == replacement_record.key else item
                        for item in state.value.installations
                    ),
                )
                _write_atomic(
                    Path(plan.setup_state_path),
                    (dump_setup_state(SetupState((record,))) + "\n").encode("utf-8"),
                )
                wrote_setup = True
                _write_atomic(
                    Path(plan.install_state_path),
                    install_state_bytes(replacement_state),
                )
                wrote_install = True
                referenced = _replace_setup_reference(plan, True)
                if isinstance(referenced, Err):
                    raise OSError(
                        "cannot retain setup object reference: "
                        + "; ".join(item.message for item in referenced.diagnostics)
                    )
            return Ok(None)
        except (OSError, RuntimeError, ValueError) as error:
            rollback: list[str] = []
            if wrote_install and install_before is not None:
                try:
                    _restore(install_before)
                except OSError as rollback_error:
                    rollback.append(f"install state: {rollback_error}")
            if wrote_setup and setup_before is not None:
                try:
                    _restore(setup_before)
                except OSError as rollback_error:
                    rollback.append(f"setup state: {rollback_error}")
            detail = f"cannot persist canonical setup state: {error}"
            if rollback:
                detail += "; rollback incomplete: " + "; ".join(rollback)
            return _error(detail)
