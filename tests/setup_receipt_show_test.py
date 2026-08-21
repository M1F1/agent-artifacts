"""RR-2: `marketplace receipt show` renders the persisted record.

The parity test here is structural rather than a list of field names: it walks the payload
`--json` emits and requires each value to appear in the text. A field added to the receipt and
forgotten in the renderer fails this test without anyone remembering to extend it.
"""

from __future__ import annotations

from agent_artifacts.model import SetupStateRecord
from agent_artifacts.setup_receipt import ReceiptLocation
from agent_artifacts.setup_render import receipt_payload, render_receipt_payload
from tests.function_cases import function_test_case

LOCATION = ReceiptLocation(
    coordinate="registry-a/mcp/github-docker",
    profile="claude",
    scope="project",
    setup_state_ref="setup-" + "e" * 20,
    state_path="/data/state/setup/setup-" + "e" * 20 + ".json",
)

RECORD = SetupStateRecord(
    artifact_type="mcp",
    artifact_name="github-docker",
    profile="claude",
    scope="project",
    status="configured",
    detail="Setup completed",
    source_label="registry-a (unverified)",
    installer_path="setup/installer.json",
    installer_hash="1" * 64,
    plan_hash="2" * 64,
    started_at="2026-08-15T09:00:00Z",
    finished_at="2026-08-15T09:00:42Z",
    exit_status=0,
    retry_command="aart marketplace setup registry-a/mcp/github-docker@1.0.0 --yes",
    rollback_command="aart marketplace receipt undo registry-a/mcp/github-docker",
    receipt=(
        {
            "step_id": "build",
            "module": "docker.build@1",
            "tag": "github-mcp:1.0.0",
            "image_id": "sha256:" + "3" * 64,
            "disposition": "created",
        },
        {
            "step_id": "token",
            "module": "macos-keychain.store@1",
            "service": "aart-github",
            "account": "token",
            "disposition": "created",
        },
    ),
    object_digest="sha256:" + "4" * 64,
    recipe_digest="sha256:" + "5" * 64,
    trust="unverified",
    canonical_review_digest="sha256:" + "6" * 64,
    setup_state_ref=LOCATION.setup_state_ref,
)


def _text(record: SetupStateRecord = RECORD) -> str:
    return "\n".join(render_receipt_payload(receipt_payload(record, location=LOCATION)))


def _flatten(value, out: list[str]) -> None:
    if isinstance(value, dict):
        for item in value.values():
            _flatten(item, out)
    elif isinstance(value, list):
        for item in value:
            _flatten(item, out)
    elif value is not None and str(value):
        out.append(str(value))


def test_every_value_the_json_payload_carries_appears_in_the_text() -> None:
    payload = receipt_payload(RECORD, location=LOCATION)
    text = "\n".join(render_receipt_payload(payload))
    # Long values wrap across lines, so parity is measured against the text with its line
    # breaks and indentation removed — wrapping is presentation, dropping a field is not.
    unwrapped = "".join(text.split())

    values: list[str] = []
    _flatten(payload, values)

    assert values, "an empty payload would make this test vacuous"
    for value in values:
        assert "".join(value.split()) in unwrapped, value


def test_a_step_field_the_renderer_never_heard_of_is_still_printed() -> None:
    record = SetupStateRecord(
        artifact_type="mcp",
        artifact_name="x",
        profile="claude",
        scope="project",
        status="configured",
        detail="done",
        receipt=({"step_id": "s", "module": "m@1", "future_field": "future-value"},),
    )

    assert "future-value" in _text(record)


def test_a_run_that_applied_no_effect_says_so_rather_than_printing_nothing() -> None:
    record = SetupStateRecord(
        artifact_type="mcp",
        artifact_name="x",
        profile="claude",
        scope="project",
        status="declined",
        detail="every effect was declined",
        receipt=(),
    )

    text = _text(record)

    assert "applied no effect" in text
    assert "every effect was declined" in text


def test_the_record_names_where_it_was_read_from() -> None:
    # An operator comparing two machines needs the path, not only the content.
    assert LOCATION.state_path in _text()


def test_a_credential_shaped_detail_in_a_step_is_redacted() -> None:
    record = SetupStateRecord(
        artifact_type="mcp",
        artifact_name="x",
        profile="claude",
        scope="project",
        status="configured",
        detail="done",
        receipt=({"step_id": "s", "module": "m@1", "detail": "secret=realsecretvalue"},),
    )

    text = _text(record)

    assert "realsecretvalue" not in text
    assert "[redacted]" in text


# Collected by `unittest discover`, which sees `TestCase` subclasses and nothing
# else; without this the functions above are imported and never run (`AD-41`).
SetupReceiptShowTests = function_test_case(globals(), name="SetupReceiptShowTests")
