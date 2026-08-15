"""RR-3: ask the world whether what a receipt claims is still true.

The receipt is an honest record of what a run *reported*.  `LAF-55` is the case where that is
not enough: `security add-generic-password -w` with no terminal exits 0 having stored nothing,
so the run reports `configured`, the receipt records the step, and the Keychain is empty.  The
only way to learn that is to ask the Keychain, and nothing asks it today.

Two halves, separated on purpose.  `plan_verification` is pure: it reads a persisted record and
decides which questions the receipt licenses, asking nothing.  `verify_claims` puts those
questions to a set of probes.  A claim this module cannot check reports `unknown` and says why —
it never reports `true` for a question it did not ask, because a verifier that quietly passes
what it cannot see is worse than no verifier.

This module reports and never repairs.  An orphaned run directory is named and left; an emptied
merge file is named and left.  Deciding when AART may delete something it may not own is the
separate question `PLAN-subscription-identity-binding` recorded.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Sequence, Tuple

from agent_artifacts.model import SetupStateRecord
from agent_artifacts.redaction import contains_credential_shape
from agent_artifacts.setup import rollback_command_for

TRUE = "true"
FALSE = "false"
UNKNOWN = "unknown"

# What a step claims, keyed by the module that wrote it.  A module absent from here is a step
# that leaves nothing behind to check — `restart.notice@1` shows a message, `command.verify@1`
# ran a command that has already finished.
IMAGE_PRESENT = "image-present"
TAG_RESOLVES = "tag-resolves"
KEYCHAIN_HOLDS_VALUE = "keychain-holds-value"
BLOCK_PRESENT = "block-present"
FILE_PRESENT = "file-present"
NO_ORPHAN_RUN = "no-orphan-run-directory"
NO_CREDENTIAL_IN_RECORD = "no-credential-in-record"
ROLLBACK_COMMAND_RUNS = "rollback-command-runs"


@dataclass(frozen=True, slots=True)
class Claim:
    """One checkable assertion a receipt step makes about the world."""

    index: int
    module: str
    kind: str
    subject: str
    # Everything the probe needs, taken from the receipt and never recomputed.
    arguments: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class ClaimResult:
    claim: Claim
    status: str
    detail: str


@dataclass(frozen=True, slots=True)
class VerificationProbes:
    """The questions this module is allowed to put to the machine.

    Each returns `None` for "I could not ask" — a missing docker daemon, a Keychain this
    platform does not have — which becomes `unknown` rather than a false alarm.
    """

    image_present: Callable[[str], bool | None]
    image_id: Callable[[str], str | None]
    keychain_value_present: Callable[[str, str], bool | None]
    read_text: Callable[[str], str | None]
    path_present: Callable[[str], bool | None]
    orphan_run_directories: Callable[[str], Tuple[str, ...] | None]
    # Not the machine, but the executable doing the asking: does its own CLI accept this string?
    command_accepted: Callable[[str], bool | None]


def _record_text(record: SetupStateRecord) -> str:
    """Everything in the record that could carry free text, as one string.

    Only the fields a run *writes prose into* — the detail and the receipt steps.  The digests,
    hashes and timestamps are structured and are the fields the shape rules deliberately do not
    match, so scanning them would only invite a false positive on the data receipts exist for.
    """

    parts = [record.detail or ""]
    for step in record.receipt:
        parts.extend(f"{key}={value}" for key, value in step.items())
    return "\n".join(parts)


def plan_verification(record: SetupStateRecord) -> Tuple[Claim, ...]:
    """Decide which questions this record licenses, asking nothing."""

    claims: list[Claim] = []
    for index, step in enumerate(record.receipt, start=1):
        module = str(step.get("module", ""))
        claims.extend(_claims_for_step(index, module, step))
    # Asked of every record, including one with no steps: a record written before `RR-10A` may
    # carry a credential that today's redactor would have caught, and the operator cannot know
    # that without being told.  `RR-10A` fixes what is written from here on; this is how the fix
    # reaches what is already on disk, without the fix editing it.
    claims.append(
        Claim(
            index=0,
            module="",
            kind=NO_CREDENTIAL_IN_RECORD,
            subject="credential-shaped text in the persisted record",
            arguments={"record": _record_text(record)},
        )
    )
    # `LAF-73`: the record's own instruction to the operator, checked against the command surface
    # of the executable reading it.  A record written before `2.6.0` says no undo exists, and the
    # same executable ships one.  Nothing rewrites the field — this is how the reader stops
    # repeating it without the writer touching evidence.
    if record.rollback_command:
        claims.append(
            Claim(
                index=0,
                module="",
                kind=ROLLBACK_COMMAND_RUNS,
                subject="the rollback command this record recorded",
                arguments={
                    "command": record.rollback_command,
                    "today": rollback_command_for(
                        record.artifact_type,
                        record.artifact_name,
                        record.profile,
                        record.scope,
                    ),
                },
            )
        )
    if record.plan_hash:
        claims.append(
            Claim(
                index=0,
                module="",
                kind=NO_ORPHAN_RUN,
                subject=f"working copies left by plan {record.plan_hash[:16]}",
                arguments={"plan_hash": record.plan_hash},
            )
        )
    return tuple(claims)


def verify_claims(
    claims: Sequence[Claim],
    *,
    probes: VerificationProbes,
) -> Tuple[ClaimResult, ...]:
    """Put each claim to the world, and say plainly which ones could not be asked."""

    return tuple(_verify(claim, probes) for claim in claims)


def verification_payload(results: Sequence[ClaimResult]) -> dict:
    """The one value both `--json` and the text renderer read, as `RR-2A` requires."""

    return {
        "claims": [
            {
                "step": result.claim.index,
                "module": result.claim.module,
                "kind": result.claim.kind,
                "subject": result.claim.subject,
                "status": result.status,
                "detail": result.detail,
            }
            for result in results
        ],
        "true": sum(1 for result in results if result.status == TRUE),
        "false": sum(1 for result in results if result.status == FALSE),
        "unknown": sum(1 for result in results if result.status == UNKNOWN),
    }


def _claims_for_step(index: int, module: str, step: Mapping[str, object]) -> Tuple[Claim, ...]:
    def claim(kind: str, subject: str, **arguments: str) -> Claim:
        return Claim(index=index, module=module, kind=kind, subject=subject, arguments=arguments)

    if module == "docker.pull@1":
        image = str(step.get("image", ""))
        return (claim(IMAGE_PRESENT, image, image=image),) if image else ()

    if module == "docker.build@1":
        tag = str(step.get("tag", ""))
        if not tag:
            return ()
        image_id = str(step.get("image_id", ""))
        # Without a recorded id the tag can only be checked for existence: a tag that was
        # rebuilt to different content would pass, and saying so is the honest report.
        if not image_id:
            return (claim(IMAGE_PRESENT, tag, image=tag),)
        return (claim(TAG_RESOLVES, tag, tag=tag, image_id=image_id),)

    if module == "macos-keychain.store@1":
        service = str(step.get("service", ""))
        account = str(step.get("account", ""))
        if not service or not account:
            return ()
        return (
            claim(
                KEYCHAIN_HOLDS_VALUE,
                f"Keychain item service={service!r} account={account!r}",
                service=service,
                account=account,
            ),
        )

    if module in ("shell.env-from-keychain@1", "file.managed-block@1"):
        path = str(step.get("path", ""))
        block = str(step.get("installed_block", ""))
        if not path:
            return ()
        # `changed: False` means the block was already what the plan wanted, and no
        # `installed_block` was recorded — the file is all this receipt can speak for.
        if not block:
            return (claim(FILE_PRESENT, path, path=path),)
        return (claim(BLOCK_PRESENT, path, path=path, block=block),)

    if module == "trust-store.export-certificates@1":
        # The receipt records `output`, `subject_contains` and the certificate names — no digest,
        # contrary to this design's first draft. Existence is what it licenses.
        output = str(step.get("output", ""))
        return (claim(FILE_PRESENT, output, path=output),) if output else ()

    if module == "json.managed-merge@1":
        path = str(step.get("path", ""))
        return (claim(FILE_PRESENT, path, path=path),) if path else ()

    return ()


def _verify(claim: Claim, probes: VerificationProbes) -> ClaimResult:
    def result(status: str, detail: str) -> ClaimResult:
        return ClaimResult(claim=claim, status=status, detail=detail)

    if claim.kind == IMAGE_PRESENT:
        present = probes.image_present(claim.arguments["image"])
        if present is None:
            return result(UNKNOWN, "docker could not be asked")
        return result(TRUE if present else FALSE, "image present" if present else "image is gone")

    if claim.kind == TAG_RESOLVES:
        current = probes.image_id(claim.arguments["tag"])
        if current is None:
            return result(UNKNOWN, "docker could not be asked")
        recorded = claim.arguments["image_id"]
        if not current:
            return result(FALSE, "tag is gone")
        if current != recorded:
            return result(
                FALSE,
                f"tag now resolves to {current}, and the receipt recorded {recorded}",
            )
        return result(TRUE, "tag resolves to the recorded image")

    if claim.kind == KEYCHAIN_HOLDS_VALUE:
        held = probes.keychain_value_present(claim.arguments["service"], claim.arguments["account"])
        if held is None:
            return result(UNKNOWN, "the Keychain could not be asked")
        if held:
            return result(TRUE, "the item exists and holds a value")
        # `LAF-55` in one sentence, at the moment it becomes visible.
        return result(
            FALSE,
            "the item is missing or empty; a Keychain step run without a terminal "
            "exits 0 having stored nothing",
        )

    if claim.kind == BLOCK_PRESENT:
        content = probes.read_text(claim.arguments["path"])
        if content is None:
            return result(FALSE, "the file the block was written into is gone")
        expected = claim.arguments["block"]
        if expected.strip() and expected.strip() in content:
            return result(TRUE, "the managed block is present and unchanged")
        if _marker_of(expected) and _marker_of(expected) in content:
            return result(FALSE, "the managed block is present and its content has changed")
        return result(FALSE, "the managed block is no longer in the file")

    if claim.kind == FILE_PRESENT:
        present = probes.path_present(claim.arguments["path"])
        if present is None:
            return result(UNKNOWN, "the path could not be read")
        return result(TRUE if present else FALSE, "present" if present else "gone")

    if claim.kind == NO_ORPHAN_RUN:
        orphans = probes.orphan_run_directories(claim.arguments["plan_hash"])
        if orphans is None:
            return result(UNKNOWN, "the run directory could not be read")
        if not orphans:
            return result(TRUE, "no working copy was left behind")
        # `LAF-61`: reported, named, and left exactly where it is.
        return result(
            FALSE,
            f"{len(orphans)} working copy left by an interrupted run, not removed: "
            + ", ".join(orphans),
        )

    if claim.kind == ROLLBACK_COMMAND_RUNS:
        accepted = probes.command_accepted(claim.arguments["command"])
        if accepted is None:
            return result(UNKNOWN, "this executable's command surface could not be asked")
        if accepted:
            return result(TRUE, "this executable accepts the recorded rollback command")
        # `LAF-73`, at the moment it becomes visible.  The recorded line is not echoed back: it is
        # the wrong instruction, and repeating it is what this claim exists to stop.
        return result(
            FALSE,
            "this executable does not accept the rollback line this record carries, which is "
            "what a record written before the undo command looks like. The record is left as it "
            f"is; the command that reverses this setup today is: {claim.arguments['today']}",
        )

    if claim.kind == NO_CREDENTIAL_IN_RECORD:
        if contains_credential_shape(claim.arguments["record"]):
            # Reported and never repaired, like every other claim.  A persisted record is evidence
            # of what a run did; rewriting it would destroy the thing receipts exist to be.  The
            # value itself is never echoed back — saying where it is, is the whole answer.
            return result(
                FALSE,
                "this record contains credential-shaped text; it was written before the redactor "
                "was corrected. Nothing here removes it: delete the record if that is what you "
                "want, and re-run setup",
            )
        return result(TRUE, "no credential-shaped text in the record")

    return ClaimResult(claim=claim, status=UNKNOWN, detail="no probe exists for this claim")


def _marker_of(block: str) -> str:
    first = block.splitlines()[0] if block.splitlines() else ""
    return first.strip()


__all__ = [
    "BLOCK_PRESENT",
    "Claim",
    "ClaimResult",
    "FALSE",
    "FILE_PRESENT",
    "IMAGE_PRESENT",
    "KEYCHAIN_HOLDS_VALUE",
    "NO_CREDENTIAL_IN_RECORD",
    "NO_ORPHAN_RUN",
    "ROLLBACK_COMMAND_RUNS",
    "TAG_RESOLVES",
    "TRUE",
    "UNKNOWN",
    "VerificationProbes",
    "plan_verification",
    "verification_payload",
    "verify_claims",
]
