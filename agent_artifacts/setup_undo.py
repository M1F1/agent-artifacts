"""RR-4: what an undo would reverse, decided before anything is reversed.

`rollback_record` (`setup_runtime.py:1359`) already replays a record's receipts in reverse order
with ownership checks, and already runs — once, on the failure path inside a run.  This module
adds the half that makes it usable from outside one: a review that names every effect the undo
will reverse **and every effect it will not, with the reason**, so the operator approving an
undo is approving something they have read.

`plan_undo` is a projection of `_rollback_receipt`'s decisions and must not drift from them;
`tests/setup_undo_test.py` holds the two together by running the real rollback against a fake
runtime and requiring the prediction to match what actually happened, module by module.
"""

from __future__ import annotations

import json as stdlib_json
from dataclasses import dataclass
from typing import Mapping, Sequence, Tuple

from agent_artifacts.domain.result import Err
from agent_artifacts.model import SetupStateRecord
from agent_artifacts.protocol.hashing import json_digest
from agent_artifacts.protocol.json import parse_json

REVERSES = "reverses"
KEEPS = "keeps"


@dataclass(frozen=True, slots=True)
class UndoStep:
    index: int
    module: str
    subject: str
    disposition: str
    reason: str


def plan_undo(record: SetupStateRecord) -> Tuple[UndoStep, ...]:
    """Project each receipt step into what an undo would do to it, touching nothing."""

    steps: list[UndoStep] = []
    # Reverse order, because that is the order the rollback runs in and the order the operator
    # will watch it happen in.
    total = len(record.receipt)
    for offset, receipt in enumerate(reversed(record.receipt)):
        index = total - offset
        disposition, reason = _disposition(receipt)
        steps.append(
            UndoStep(
                index=index,
                module=str(receipt.get("module", "")),
                subject=_subject(receipt),
                disposition=disposition,
                reason=reason,
            )
        )
    return tuple(steps)


def undo_payload(steps: Sequence[UndoStep], *, coordinate: str, profile: str, scope: str) -> dict:
    """The one value both `--json` and the text renderer read."""

    return {
        "coordinate": coordinate,
        "profile": profile,
        "scope": scope,
        "steps": [
            {
                "step": step.index,
                "module": step.module,
                "subject": step.subject,
                "disposition": step.disposition,
                "reason": step.reason,
            }
            for step in steps
        ],
        "reverses": sum(1 for step in steps if step.disposition == REVERSES),
        "keeps": sum(1 for step in steps if step.disposition == KEEPS),
    }


def undo_digest(payload: Mapping[str, object]) -> str:
    """Bind a decision to the exact undo it was read from.

    Digested through the package's own JSON parser rather than a second canonicalization, so
    the digest covers precisely the bytes `--json` printed — `SI-1`'s guarantee, over an undo.
    """

    parsed = parse_json(stdlib_json.dumps(payload))
    if isinstance(parsed, Err):  # pragma: no cover - the payload is built from plain scalars
        raise ValueError("undo payload is not representable as canonical JSON")
    return str(json_digest(parsed.value))


def _subject(receipt: Mapping[str, object]) -> str:
    for key in ("tag", "image", "path", "output", "script"):
        value = receipt.get(key)
        if value:
            return str(value)
    service, account = receipt.get("service"), receipt.get("account")
    if service and account:
        return f"Keychain item service={str(service)!r} account={str(account)!r}"
    return str(receipt.get("step_id", "unnamed step"))


def _disposition(receipt: Mapping[str, object]) -> tuple[str, str]:
    module = str(receipt.get("module", ""))

    if module == "macos-keychain.store@1":
        if receipt.get("replaced") is True:
            return KEEPS, (
                "this step overwrote a value the run did not create, so the undo will not "
                "delete it; the receipt's recovery line has the manual restore"
            )
        if receipt.get("created") is True:
            return REVERSES, "deletes the Keychain item this run created"
        return KEEPS, "this step stored nothing, so there is nothing to delete"

    if module in ("shell.env-from-keychain@1", "file.managed-block@1"):
        if receipt.get("changed") is True:
            if receipt.get("file_existed") is False:
                return REVERSES, "removes the file this run created for the managed block"
            return REVERSES, "restores the file to the block it held before this run"
        return KEEPS, "the file already held this block, so this run changed nothing"

    if module == "directory.create@1":
        if receipt.get("created") is True:
            return REVERSES, "removes the directory this run created, if it is empty"
        return KEEPS, "the directory existed before this run"

    if module == "json.managed-merge@1":
        if receipt.get("replaced") is True:
            return KEEPS, "this step overwrote a value the run did not create"
        if receipt.get("changed") is True:
            return REVERSES, "removes the key this run merged in"
        return KEEPS, "the file already held this value"

    if module == "custom.install@1":
        if receipt.get("reversible") is True:
            return REVERSES, "runs the recipe's own rollback phase"
        return KEEPS, "this recipe declares no rollback, so the undo will report incomplete"

    if module == "docker.pull@1":
        if receipt.get("preexisting") is True:
            return KEEPS, "the image was on this machine before the run and is left alone"
        # `_rollback_receipt` returns False here, so the undo reports `rollback_incomplete`.
        # An operator learning that afterwards would think something went wrong; it did not.
        return KEEPS, (
            "images may be shared, so this one is never removed automatically — and because "
            "it stays, the undo will report `rollback_incomplete` and keep the receipt"
        )

    if module == "docker.build@1":
        if receipt.get("preexisting") is True:
            # `LAF-58`. The tag keeps its name and points at what this run built; the id it
            # pointed at beforehand was never recorded, so nothing can restore the binding.
            return KEEPS, (
                "the tag named an image before this run, so it is not removed — but it now "
                "points at what this run built, and the receipt never recorded the earlier "
                "image id, so the undo cannot restore the original binding (LAF-58)"
            )
        return REVERSES, "removes the image tag this run created"

    if module in ("restart.notice@1", "command.verify@1", "trust-store.export-certificates@1"):
        return KEEPS, "this step changed nothing that outlives the run"

    if not bool(receipt.get("changed", False)):
        return KEEPS, "this step changed nothing"
    return KEEPS, "no compensation exists for this module, so the undo will report incomplete"


__all__ = ["KEEPS", "REVERSES", "UndoStep", "plan_undo", "undo_digest", "undo_payload"]
