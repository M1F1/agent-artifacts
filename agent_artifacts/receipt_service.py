"""RR-5: one receipt service, two front-ends.

`VN-9` established that a maintainer action existing only in the CLI is half-shipped.  The way
to ship an action twice without writing it twice is for both skins to call the same functions
and render the same lines — so this module owns resolving an installation to its persisted
record, and projecting that record into the three payloads, and neither front-end owns any of
it.

Emission stays with the front-end: the CLI prints, the text front-end writes through its own
`write` port.  Everything above that line is here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence, Tuple

from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.install_state.paths import install_state_paths
from agent_artifacts.install_state.schema import parse_install_state
from agent_artifacts.io import fs
from agent_artifacts.model import InstallScope, SetupState, SetupStateRecord
from agent_artifacts.setup import dump_setup_state
from agent_artifacts.setup_receipt import (
    RECEIPT_INVALID,
    RECEIPT_NOT_INSTALLED,
    ReceiptLocation,
    locate_setup_record,
    missing_record,
    read_setup_record,
)
from agent_artifacts.setup_render import receipt_payload
from agent_artifacts.setup_runtime import production_runtime, rollback_record
from agent_artifacts.setup_undo import plan_undo, undo_digest, undo_payload
from agent_artifacts.setup_verify import plan_verification, verification_payload, verify_claims
from agent_artifacts.setup_verify_probes import local_probes

RECEIPT_ACTIONS: Tuple[str, ...] = ("show", "verify", "undo")

_NO_MANIFEST = "this scope has no installation state, so no setup run has been recorded in it"


@dataclass(frozen=True, slots=True)
class LoadedReceipt:
    """One installation's persisted record, and where it and its project live."""

    record: SetupStateRecord
    location: ReceiptLocation
    project_root: str


def load_receipt(
    *,
    data_root: str,
    project_root: str,
    user_home: str,
    scope: InstallScope,
    selector: str,
    profiles: Sequence[str] = (),
) -> Result[LoadedReceipt]:
    """Resolve one installation to the record a setup run persisted for it."""

    state_paths = install_state_paths(
        scope,
        project_root=project_root,
        user_home=user_home,
        data_root=data_root,
    )
    manifest = Path(state_paths.destination_path)
    if not manifest.is_file():
        return _error(RECEIPT_NOT_INSTALLED, _NO_MANIFEST)
    parsed = parse_install_state(manifest.read_bytes())
    if isinstance(parsed, Err):
        return parsed

    candidates = _candidates(parsed.value, selector=selector, scope=scope)
    chosen = tuple(profiles)
    if chosen:
        candidates = [record for record in candidates if record.profile in chosen]
    if not candidates:
        return _error(
            RECEIPT_NOT_INSTALLED,
            f"no installation of {selector} in {scope} scope"
            + (f" for profile {', '.join(chosen)}" if chosen else ""),
            (
                "list what is installed with: aart marketplace status",
                "install it with: aart marketplace install",
            ),
        )
    if len(candidates) > 1:
        found = ", ".join(sorted(f"{item.coordinate}#{item.profile}" for item in candidates))
        return _error(
            RECEIPT_INVALID,
            f"{selector} names more than one installation in {scope} scope: {found}",
            ("name one with: aart marketplace receipt show <coordinate> --profile <profile>",),
        )

    installation = candidates[0]
    located = locate_setup_record(
        parsed.value,
        coordinate=str(installation.coordinate),
        profile=installation.profile,
        scope=scope,
        data_root=data_root,
    )
    if isinstance(located, Err):
        return located
    location = located.value

    record_file = Path(location.state_path)
    if not record_file.is_file():
        return missing_record(location)
    record = read_setup_record(record_file.read_text(encoding="utf-8"), location=location)
    if isinstance(record, Err):
        return record
    return Ok(LoadedReceipt(record.value, location, project_root))


def show_view(loaded: LoadedReceipt) -> dict:
    return receipt_payload(loaded.record, location=loaded.location)


def verify_view(loaded: LoadedReceipt) -> dict:
    return verification_payload(
        verify_claims(
            plan_verification(loaded.record),
            probes=local_probes(project_root=loaded.project_root),
        )
    )


def undo_view(loaded: LoadedReceipt) -> tuple[dict, str]:
    payload = undo_payload(
        plan_undo(loaded.record),
        coordinate=loaded.location.coordinate,
        profile=loaded.location.profile,
        scope=loaded.location.scope,
    )
    return payload, undo_digest(payload)


def apply_undo(loaded: LoadedReceipt) -> SetupStateRecord:
    """Reverse the recorded effects and write the resulting record back over the same file."""

    rolled = rollback_record(loaded.record, production_runtime())
    fs.write_atomic(
        loaded.location.state_path,
        (dump_setup_state(SetupState((rolled,))) + "\n").encode("utf-8"),
    )
    return rolled


def resolved_paths(
    *,
    data_root: str,
    project: str | None,
    user_home: str | None,
) -> tuple[str, str]:
    """The project root and home a receipt operation reads, resolved once and in one place."""

    del data_root
    return (
        os.path.abspath(project or os.getcwd()),
        os.path.abspath(user_home or os.path.expanduser("~")),
    )


def unsupported_action(action: str | None) -> Err:
    return _error(
        RECEIPT_INVALID,
        f"unsupported receipt action {action!r}",
        (
            "read a persisted record with: aart marketplace receipt show <coordinate>",
            "check whether it is still true with: aart marketplace receipt verify <coordinate>",
            "reverse what it recorded with: aart marketplace receipt undo <coordinate>",
        ),
    )


def _candidates(state, *, selector: str, scope: str) -> list:
    """Every installation the operator's selector could mean, in this scope.

    A coordinate may be given fully qualified, with or without a version, or as the
    ``kind/name`` tail. Ambiguity is reported rather than resolved by picking the first, because
    a receipt printed for the wrong installation reads exactly like a correct one.
    """

    wanted = selector.split("@", 1)[0]
    matched = []
    for record in state.installations:
        if record.scope != scope:
            continue
        coordinate = str(record.coordinate)
        if coordinate == wanted or coordinate.endswith(f"/{wanted}"):
            matched.append(record)
    return matched


def _error(code: DiagnosticCode, message: str, remediation: Tuple[str, ...] = ()) -> Err:
    return Err(
        (
            Diagnostic(
                code,
                Severity.ERROR,
                message,
                remediation=remediation
                or ("list what is installed with: aart marketplace status",),
            ),
        )
    )


__all__ = [
    "RECEIPT_ACTIONS",
    "LoadedReceipt",
    "apply_undo",
    "load_receipt",
    "resolved_paths",
    "show_view",
    "undo_view",
    "unsupported_action",
    "verify_view",
]
