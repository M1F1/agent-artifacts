"""RR-3: `marketplace receipt verify` asks the world, and says what it could not ask.

The probes are injected, so what is under test is the decision of which questions a receipt
licenses — not whether this machine has a docker daemon.
"""

from __future__ import annotations

from agent_artifacts.model import SetupStateRecord
from agent_artifacts.setup_verify import (
    BLOCK_PRESENT,
    FALSE,
    KEYCHAIN_HOLDS_VALUE,
    NO_ORPHAN_RUN,
    TAG_RESOLVES,
    TRUE,
    UNKNOWN,
    VerificationProbes,
    plan_verification,
    verification_payload,
    verify_claims,
)

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


def _statuses(record, probes) -> dict:
    results = verify_claims(plan_verification(record), probes=probes)
    return {result.claim.kind: (result.status, result.detail) for result in results}


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


def test_a_step_that_leaves_nothing_behind_licenses_no_claim() -> None:
    record = _record(
        {"module": "restart.notice@1", "step_id": "restart", "message": "restart your shell"},
        {"module": "command.verify@1", "step_id": "check", "verified": True},
        plan_hash="",
    )

    assert plan_verification(record) == ()


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

    assert (payload["true"], payload["false"], payload["unknown"]) == (1, 1, 1)
    assert len(payload["claims"]) == 3
