"""Read one installation's persisted setup record from outside a run.

AART writes a complete account of every setup run — plan hash, timings, exit status, and a
per-step receipt — and persists it under the data root, bound to one installation
(`setup_engine/io.py`).  The only reader is the run about to replace it
(`setup_engine/application.py`, `_previous_record`).  This module is the read path everything
else needs: given an already-parsed install state, it resolves where one installation's record
lives and parses it, with no run in flight and nothing locked for writing.

Reading never locks.  A read that blocked on the install-state write lock would make `receipt
show` fail during an unrelated install, which is the opposite of what a reader is for.
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass

from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.install_state.model import InstallState
from agent_artifacts.model import Err as LegacyErr
from agent_artifacts.model import InstallScope, SetupStateRecord
from agent_artifacts.setup import parse_setup_state

RECEIPT_NOT_INSTALLED = DiagnosticCode("receipt-not-installed")
RECEIPT_NO_SETUP = DiagnosticCode("receipt-no-setup")
RECEIPT_MISSING = DiagnosticCode("receipt-missing")
RECEIPT_INVALID = DiagnosticCode("receipt-invalid")


@dataclass(frozen=True, slots=True)
class ReceiptLocation:
    """Where one installation's persisted setup record lives, and what it belongs to."""

    coordinate: str
    profile: str
    scope: InstallScope
    setup_state_ref: str
    state_path: str


def setup_state_file(data_root: str, setup_state_ref: str) -> str:
    """The canonical per-installation setup state path.

    Mirrors what `setup_engine/application.py` composes when it writes.  The legacy
    `setup.setup_state_path` is a different, scope-wide file kept for 0.1.x readers.
    """

    return posixpath.join(data_root, "state", "setup", f"{setup_state_ref}.json")


def locate_setup_record(
    state: InstallState,
    *,
    coordinate: str,
    profile: str,
    scope: InstallScope,
    data_root: str,
) -> Result[ReceiptLocation]:
    """Resolve one installation's setup record location, or say precisely what is absent.

    Three absences, three sentences.  An installation that was never installed is not an
    installation without setup, and neither is a pointer whose target is gone — conflating them
    is what makes a refusal useless to the operator holding it.
    """

    installation = _selected(state, coordinate=coordinate, profile=profile, scope=scope)
    if installation is None:
        return _error(
            RECEIPT_NOT_INSTALLED,
            f"no installation of {coordinate} for profile {profile} in {scope} scope",
            (
                "list what is installed with: aart marketplace status",
                "install it with: aart marketplace install",
            ),
        )
    if not installation.setup_state_ref:
        return _error(
            RECEIPT_NO_SETUP,
            f"{coordinate} is installed and declares no setup, so there is no receipt to read",
            (
                "check whether the artifact declares setup with: aart marketplace list",
                "run declared setup with: aart marketplace setup",
            ),
        )
    return Ok(
        ReceiptLocation(
            coordinate=coordinate,
            profile=profile,
            scope=scope,
            setup_state_ref=installation.setup_state_ref,
            state_path=setup_state_file(data_root, installation.setup_state_ref),
        )
    )


def read_setup_record(text: str, *, location: ReceiptLocation) -> Result[SetupStateRecord]:
    """Parse the record a located file holds, requiring exactly the one it is bound to."""

    parsed = parse_setup_state(text)
    if isinstance(parsed, LegacyErr):
        return _error(
            RECEIPT_INVALID,
            f"setup record for {location.coordinate} is invalid: {parsed.reason}",
            ("re-run setup to rewrite the record with: aart marketplace setup",),
        )
    records = parsed.value.records
    if len(records) != 1:
        return _error(
            RECEIPT_INVALID,
            (
                f"setup record for {location.coordinate} holds {len(records)} records "
                "where exactly one is bound to an installation"
            ),
            ("re-run setup to rewrite the record with: aart marketplace setup",),
        )
    return Ok(records[0])


def missing_record(location: ReceiptLocation) -> Err:
    """The pointer exists and its target does not — the third absence, named separately."""

    return _error(
        RECEIPT_MISSING,
        (
            f"{location.coordinate} points at setup record {location.setup_state_ref} "
            "and that record is not present under the data root"
        ),
        ("re-run setup to rewrite the record with: aart marketplace setup",),
    )


def _selected(
    state: InstallState,
    *,
    coordinate: str,
    profile: str,
    scope: InstallScope,
):
    for record in state.installations:
        if (
            str(record.coordinate) == coordinate
            and record.profile == profile
            and record.scope == scope
        ):
            return record
    return None


def _error(code: DiagnosticCode, message: str, remediation: tuple[str, ...]) -> Err:
    return Err((Diagnostic(code, Severity.ERROR, message, remediation=remediation),))
