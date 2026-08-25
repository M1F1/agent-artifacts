"""RR-3: `marketplace receipt verify` asks the world, and says what it could not ask.

The probes are injected, so what is under test is the decision of which questions a receipt
licenses — not whether this machine has a docker daemon.
"""

from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace

from agent_artifacts.model import SetupQueueItem, SetupStateRecord
from agent_artifacts.setup import rollback_command
from agent_artifacts.setup_runtime import new_run_directory
from agent_artifacts.setup_verify import (
    BLOCK_PRESENT,
    FALSE,
    KEYCHAIN_HOLDS_VALUE,
    NO_CREDENTIAL_IN_RECORD,
    NO_ORPHAN_RUN,
    ROLLBACK_COMMAND_RUNS,
    TAG_RESOLVES,
    TRUE,
    UNKNOWN,
    VerificationProbes,
    plan_verification,
    verification_payload,
    verify_claims,
)
from agent_artifacts.setup_verify_probes import command_accepted, orphan_run_directories
from tests.credential_fixtures import access_token
from tests.function_cases import function_test_case

BLOCK = (
    "# >>> aart setup: mcp/x@claude >>>\nexport TOKEN_LOOKUP=1\n# <<< aart setup: mcp/x@claude <<<"
)


def _probes(**overrides) -> VerificationProbes:
    defaults = dict(
        image_present=lambda _image: True,
        image_id=lambda _tag: "sha256:" + "3" * 64,
        keychain_value_present=lambda _service, _account: True,
        read_text=lambda _path: BLOCK,
        path_present=lambda _path: True,
        orphan_run_directories=lambda _plan_hash: (),
        command_accepted=lambda _command: True,
    )
    defaults.update(overrides)
    return VerificationProbes(**defaults)  # type: ignore[arg-type]


def _record(*steps, plan_hash: str = "a" * 64) -> SetupStateRecord:
    return SetupStateRecord(
        artifact_type="mcp",
        artifact_name="x",
        profile="claude",
        scope="project",
        status="configured",
        detail="done",
        plan_hash=plan_hash,
        receipt=tuple(steps),
    )


def _record_with_rollback(command: str) -> SetupStateRecord:
    return SetupStateRecord(
        artifact_type="mcp",
        artifact_name="x",
        profile="claude",
        scope="project",
        status="apply_failed_rolled_back",
        detail="done",
        plan_hash="a" * 64,
        rollback_command=command,
    )


def _statuses(record, probes) -> dict:
    results = verify_claims(plan_verification(record), probes=probes)
    return {result.claim.kind: (result.status, result.detail) for result in results}


def test_a_compensated_failure_receipt_makes_no_live_world_claim() -> None:
    record = _record(
        {
            "module": "macos-keychain.store@1",
            "step_id": "token",
            "service": "aart/mcp/x",
            "account": "token",
            "created": True,
            "setup_disposition": "compensated",
        },
        plan_hash="",
    )

    kinds = tuple(claim.kind for claim in plan_verification(record))

    assert KEYCHAIN_HOLDS_VALUE not in kinds
    assert kinds == (NO_CREDENTIAL_IN_RECORD,)


def test_laf55_a_keychain_item_that_holds_nothing_is_reported_false() -> None:
    # The condition LAF-55 describes: the step exited 0, the receipt records it, and the
    # Keychain is empty. Nothing but asking the Keychain can tell them apart.
    record = _record(
        {
            "module": "macos-keychain.store@1",
            "step_id": "token",
            "service": "aart/mcp/x",
            "account": "default",
            "created": False,
            "replaced": False,
        }
    )

    status, detail = _statuses(record, _probes(keychain_value_present=lambda *_: False))[
        KEYCHAIN_HOLDS_VALUE
    ]

    assert status == FALSE
    assert "without a terminal" in detail


def test_a_keychain_that_cannot_be_asked_is_unknown_not_true() -> None:
    record = _record(
        {
            "module": "macos-keychain.store@1",
            "step_id": "token",
            "service": "aart/mcp/x",
            "account": "default",
        }
    )

    status, _detail = _statuses(record, _probes(keychain_value_present=lambda *_: None))[
        KEYCHAIN_HOLDS_VALUE
    ]

    assert status == UNKNOWN, "a verifier that passes what it did not check is worse than none"


def test_a_tag_that_now_resolves_elsewhere_is_false_and_names_both_ids() -> None:
    record = _record(
        {
            "module": "docker.build@1",
            "step_id": "build",
            "tag": "x:1.0.0",
            "image_id": "sha256:" + "3" * 64,
        }
    )

    status, detail = _statuses(record, _probes(image_id=lambda _tag: "sha256:" + "9" * 64))[
        TAG_RESOLVES
    ]

    assert status == FALSE
    assert "9" * 64 in detail and "3" * 64 in detail


def test_a_build_receipt_without_a_recorded_id_falls_back_to_existence() -> None:
    record = _record({"module": "docker.build@1", "step_id": "build", "tag": "x:1.0.0"})

    kinds = {claim.kind for claim in plan_verification(record)}

    assert TAG_RESOLVES not in kinds, "no recorded id licenses no identity claim"


def test_a_changed_managed_block_is_distinguished_from_a_removed_one() -> None:
    step = {
        "module": "shell.env-from-keychain@1",
        "step_id": "shell",
        "path": "/home/u/.zshrc",
        "installed_block": BLOCK,
    }

    edited = _statuses(
        _record(step),
        _probes(read_text=lambda _p: "# >>> aart setup: mcp/x@claude >>>\nexport OTHER=2\n"),
    )[BLOCK_PRESENT]
    removed = _statuses(_record(step), _probes(read_text=lambda _p: "unrelated content"))[
        BLOCK_PRESENT
    ]

    assert edited == (FALSE, "the managed block is present and its content has changed")
    assert removed == (FALSE, "the managed block is no longer in the file")


def test_an_intact_block_is_true() -> None:
    record = _record(
        {
            "module": "file.managed-block@1",
            "step_id": "block",
            "path": "/home/u/.zshrc",
            "installed_block": BLOCK,
        }
    )

    status, _detail = _statuses(record, _probes(read_text=lambda _p: f"before\n{BLOCK}\nafter"))[
        BLOCK_PRESENT
    ]

    assert status == TRUE


def test_laf61_an_orphaned_run_directory_is_named_and_not_removed() -> None:
    seen: list[str] = []

    def orphans(plan_hash: str):
        seen.append(plan_hash)
        return ("/p/.agent-artifacts/setup-runs/aaaaaaaaaaaaaaaa-xyz",)

    status, detail = _statuses(_record(), _probes(orphan_run_directories=orphans))[NO_ORPHAN_RUN]

    assert status == FALSE
    assert "setup-runs/aaaaaaaaaaaaaaaa-xyz" in detail
    assert "not removed" in detail
    assert seen == ["a" * 64]


def test_laf66_the_probe_reads_the_root_the_engine_writes_into() -> None:
    """The real writer and the real reader, held together (`LAF-66`).

    The test above drives a fake probe, so it proved the *claim* renders and never proved the
    probe looks anywhere real.  This one calls `new_run_directory` — the function a run actually
    uses — and then the real `orphan_run_directories`, so the two cannot drift apart again.
    """

    plan_hash = "b" * 64
    with tempfile.TemporaryDirectory() as root:
        data_root = os.path.join(root, "data")
        project_root = os.path.join(root, "project")
        os.makedirs(data_root)
        os.makedirs(project_root)

        run_dir = new_run_directory(SimpleNamespace(run_root=data_root, plan_hash=plan_hash))

        found = orphan_run_directories(data_root, plan_hash)
        assert found == (run_dir,)

        # And not by widening the search: the directory the probe used to scan is a different
        # place, and a leftover there is not this run's.
        assert orphan_run_directories(project_root, plan_hash) == ()


def test_laf66_an_unreachable_run_root_is_unknown_and_never_true() -> None:
    """A probe that cannot ask says so.

    `LAF-66` was not a missing check.  It was a check that answered `true` about a directory it had
    never looked in, which is worse than no check.  An empty root is the one case where the probe
    genuinely cannot look, and it must not resolve to `()`, because `()` means *asked, and nothing
    was there*.
    """

    assert orphan_run_directories("", "c" * 64) is None


def test_a_step_that_leaves_nothing_behind_licenses_no_claim() -> None:
    record = _record(
        {"module": "restart.notice@1", "step_id": "restart", "message": "restart your shell"},
        {"module": "command.verify@1", "step_id": "check", "verified": True},
        plan_hash="",
    )

    # The two record-wide claims are not derived from a step and are excluded here: this asserts
    # that a *step* which changed nothing licenses nothing, which is the invariant it was
    # written for.
    step_claims = tuple(
        claim
        for claim in plan_verification(record)
        if claim.kind not in (NO_CREDENTIAL_IN_RECORD, NO_ORPHAN_RUN)
    )

    assert step_claims == ()


def test_rr10f_a_record_written_before_the_fix_is_reported_not_repaired() -> None:
    """The fix reaches records already on disk, without the fix editing them.

    `RR-10A` corrects what is written from here on.  It does nothing about a record `2.5.0` wrote
    with a credential in it, and rewriting one would destroy the evidence receipts exist to be.
    So `verify` says so and stops there, which is the same contract every other claim has.
    """

    record = _record(
        {
            "module": "docker.build@1",
            "step_id": "build",
            "detail": "fatal: authentication failed for " + access_token("leftoverfromoldrecord1"),
        }
    )

    before = tuple(dict(step) for step in record.receipt)
    status, detail = _statuses(record, _probes())[NO_CREDENTIAL_IN_RECORD]

    assert status == FALSE
    assert "delete the record" in detail
    # The value is never echoed back. Saying where it is, is the whole answer.
    assert access_token("leftoverfromoldrecord1") not in detail
    assert tuple(dict(step) for step in record.receipt) == before


def test_rr10f_a_clean_record_says_it_checked() -> None:
    # `LAF-45`'s lesson: a path with nothing to report says that it checked, rather than printing
    # nothing and letting silence read as either success or a dropped flag.
    status, _detail = _statuses(_record(), _probes())[NO_CREDENTIAL_IN_RECORD]

    assert status == TRUE


def test_laf73_a_rollback_line_this_executable_rejects_is_reported_not_rewritten() -> None:
    """`LAF-73`: the write path was fixed and the read path kept believing the old records.

    `RR-10E` corrected `rollback_command` for records written from now on. A record written
    before it still carries *no command reverses a completed setup*, and the same executable that
    holds both facts said nothing — an operator reading an old receipt does by hand what one
    command does. Same contract as every other claim: report, name the command that works, and
    leave the record exactly as it is.
    """

    record = _record_with_rollback(
        "no command reverses a completed setup; undo mcp/x in claude (project) "
        "from the recorded receipt, then re-run setup"
    )

    before = record.rollback_command
    # The real parser answers, not a fake: what makes the old sentence wrong is this executable.
    statuses = _statuses(record, _probes(command_accepted=command_accepted))
    status, detail = statuses[ROLLBACK_COMMAND_RUNS]

    assert status == FALSE
    assert "aart marketplace receipt undo mcp/x --profile claude --scope project --yes" in detail
    assert record.rollback_command == before


def test_laf73_the_command_this_release_writes_is_the_one_verify_accepts() -> None:
    """The real writer and the real reader, driven together — `LAF-66`'s lesson.

    A fake probe that answers `True` would prove nothing about whether the string a run records
    is a string this CLI accepts. So the command comes from `rollback_command`, the function the
    engine calls, and the answer comes from the probe a real machine uses.
    """

    item = SetupQueueItem(
        "mcp",
        "x",
        "claude",
        "project",
        "pin:abc",
        "/src",
        SimpleNamespace(descriptor_path="", descriptor_hash="", custom_hash="", schema_version=2),
    )
    record = _record_with_rollback(rollback_command(item))

    results = verify_claims(
        plan_verification(record), probes=_probes(command_accepted=command_accepted)
    )
    statuses = {result.claim.kind: (result.status, result.detail) for result in results}

    assert statuses[ROLLBACK_COMMAND_RUNS][0] == TRUE


def test_laf73_the_probe_rejects_the_sentence_and_accepts_the_command() -> None:
    # The probe itself, against the shipped parser: the two strings the finding is about.
    assert command_accepted("no command reverses a completed setup; undo mcp/x") is False
    assert (
        command_accepted(
            "aart marketplace receipt undo mcp/x --profile claude --scope project --yes"
        )
        is True
    )


def test_laf73_a_record_carrying_no_rollback_line_claims_nothing() -> None:
    # A successful run clears the field. There is no claim to make about an empty string, and
    # inventing one would report `false` for every clean record.
    kinds = {claim.kind for claim in plan_verification(_record())}

    assert ROLLBACK_COMMAND_RUNS not in kinds


def test_a_receipt_with_nothing_checkable_still_reports_a_payload() -> None:
    payload = verification_payload(verify_claims((), probes=_probes()))

    assert payload == {"claims": [], "true": 0, "false": 0, "unknown": 0}


def test_the_payload_counts_each_status_once() -> None:
    record = _record(
        {"module": "docker.pull@1", "step_id": "pull", "image": "img@sha256:" + "1" * 64},
        {
            "module": "macos-keychain.store@1",
            "step_id": "token",
            "service": "s",
            "account": "a",
        },
    )

    payload = verification_payload(
        verify_claims(
            plan_verification(record),
            probes=_probes(
                image_present=lambda _i: False,
                keychain_value_present=lambda *_: None,
            ),
        )
    )

    # Four claims, not three: the image, the Keychain item, the orphan directory, and the
    # record-wide credential scan `RR-10F` added. The scan is `true` here, which is the point of
    # it — a path with nothing to report says that it checked (`LAF-45`).
    assert (payload["true"], payload["false"], payload["unknown"]) == (2, 1, 1)
    assert len(payload["claims"]) == 4


# Collected by `unittest discover`, which sees `TestCase` subclasses and nothing
# else; without this the functions above are imported and never run (`AD-41`).
SetupVerifyTests = function_test_case(globals(), name="SetupVerifyTests")
