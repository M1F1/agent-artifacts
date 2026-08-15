"""RR-2A: the text renderer prints what the ``setup`` JSON payload carries.

Design §3.4. Counts may accompany content and may not replace it. These tests are written
against the payload dict because that is the value `--json` emits — a field the text renderer
drops is a measurable difference between the two outputs, not a matter of taste.
"""

from __future__ import annotations

from agent_artifacts.setup_render import render_setup_payload

MANUAL = {
    "relative_path": "SETUP.md",
    "source": "https://github.com/example/registry/blob/c472730/SETUP.md",
}

# The payload `aart marketplace setup registry-a/mcp/github-docker@1.0.0` emitted on
# 2026-08-15, which the text path rendered as no lines at all.
PLANNING_FAILURE = {
    "planned": [],
    "planning_failures": [
        {
            "key": "registry-a/mcp/github-docker@1.0.0#claude/project",
            "detail": "setup from unverified requires explicit source authorization",
            "manual": MANUAL,
        }
    ],
}

PLANNED = {
    "planned": [
        {
            "key": "registry-a/mcp/github-docker@1.0.0#claude/project",
            "trust": "unverified",
            "recipe": "setup/installer.json",
            "review_digest": "sha256:" + "a" * 64,
            "manual": MANUAL,
            "effects": [
                {
                    "index": 1,
                    "identity": "docker.build@1 github-mcp:1.0.0",
                    "target": "/tmp/build",
                    "capability": "docker-build",
                    "recovery": "docker image rm github-mcp:1.0.0",
                    "details": "builds the server image",
                }
            ],
        }
    ],
    "planning_failures": [],
}


def _joined(payload, **kwargs) -> str:
    return "\n".join(render_setup_payload(payload, **kwargs))


def test_a_planning_failure_reaches_the_operator_at_all() -> None:
    text = _joined(PLANNING_FAILURE)

    assert "registry-a/mcp/github-docker@1.0.0#claude/project" in text
    assert "setup from unverified requires explicit source authorization" in text


def test_a_planning_failure_carries_the_manual_route_the_json_carries() -> None:
    text = _joined(PLANNING_FAILURE)

    assert "SETUP.md" in text
    assert MANUAL["source"] in text


def test_the_count_survives_but_comes_after_the_content_it_used_to_replace() -> None:
    lines = render_setup_payload(PLANNING_FAILURE)

    assert lines[-1] == "Setup: planned=0, failures=1"
    assert len(lines) > 1, "a count on its own is the LAF-52 defect"


def test_a_planned_effect_is_rendered_field_for_field() -> None:
    text = _joined(PLANNED)

    for expected in (
        "docker.build@1 github-mcp:1.0.0",
        "/tmp/build",
        "docker-build",
        "docker image rm github-mcp:1.0.0",
        "builds the server image",
    ):
        assert expected in text, expected


def test_the_review_call_site_suppresses_only_the_effects_it_renders_itself() -> None:
    # `planned_effects=False` exists so `render_setup_review` is not duplicated, never so the
    # text may carry less than the JSON — a failure in the same payload still prints.
    both = {
        "planned": PLANNED["planned"],
        "planning_failures": PLANNING_FAILURE["planning_failures"],
    }

    text = _joined(both, planned_effects=False)

    assert "docker.build@1 github-mcp:1.0.0" not in text
    assert "setup from unverified requires explicit source authorization" in text


def test_an_empty_payload_says_it_looked() -> None:
    text = _joined({"planned": [], "planning_failures": []})

    assert "nothing to configure" in text


def test_outcome_items_render_their_status_and_detail() -> None:
    payload = {
        "planned": PLANNED["planned"],
        "planning_failures": [],
        "configured": 1,
        "incomplete": 0,
        "items": [
            {
                "key": "registry-a/mcp/github-docker@1.0.0#claude/project",
                "status": "configured",
                "detail": "Setup completed in 4.2s",
            }
        ],
    }

    lines = render_setup_payload(payload)
    text = "\n".join(lines)

    assert "Setup configured: registry-a/mcp/github-docker@1.0.0#claude/project" in text
    assert "Setup completed in 4.2s" in text
    assert lines[-1] == "Setup: planned=1, failures=0, configured=1, incomplete=0"


def _failure_payload(detail: str) -> dict:
    return {
        "planned": [],
        "planning_failures": [
            {"key": "registry-a/mcp/x@1.0.0#claude/project", "detail": detail, "manual": None}
        ],
    }


def test_a_credential_shaped_detail_is_redacted_before_it_is_printed() -> None:
    text = _joined(_failure_payload("failed: secret=realsecretvalue rejected"))

    assert "realsecretvalue" not in text
    assert "[redacted]" in text


def test_laf63_a_prefixed_credential_name_is_redacted() -> None:
    # `LAF-63`, closed by `RR-10A`. The pattern used to anchor on `\b`, so a vendor-prefixed name
    # never matched: a bare `TOKEN=` redacted and every prefixed form did not, which are the forms
    # real recipes use. The same pattern redacts the persisted record, so this was a credential
    # reaching disk, not only a terminal.
    #
    # This test was written asserting the opposite, to hold the gap visible while it was open. It
    # is the same case, measured the same way, with the expectation flipped.
    text = _joined(_failure_payload("failed: SOMEVENDOR_TOKEN=ghp_realsecretvalue rejected"))

    assert "ghp_realsecretvalue" not in text
    assert "[redacted]" in text


def test_a_bare_credential_with_no_name_beside_it_is_redacted() -> None:
    # Rule 4. Rules 1-3 all need the credential next to its name; a transcript that prints the
    # value alone defeats all three, which is the case a wider assignment pattern cannot reach.
    text = _joined(_failure_payload("fatal: authentication failed for ghp_barevaluenotnamed01"))

    assert "ghp_barevaluenotnamed01" not in text


def test_a_digest_is_not_mistaken_for_a_credential() -> None:
    # The limit `DESIGN-token-containment.md` §4.4 accepts: detection is by shape, never by
    # entropy, because an entropy matcher would redact the digests and plan hashes a receipt
    # exists to carry.
    digest = "sha256:" + "a" * 64

    text = _joined(_failure_payload(f"image {digest} was rejected"))

    assert digest in text


def test_a_multiline_detail_cannot_break_the_line_protocol() -> None:
    payload = {
        "planned": [],
        "planning_failures": [
            {
                "key": "registry-a/mcp/x@1.0.0#claude/project",
                "detail": "first\nsecond\rthird",
                "manual": None,
            }
        ],
    }

    for line in render_setup_payload(payload):
        assert "\n" not in line and "\r" not in line


def test_a_payload_missing_optional_fields_renders_rather_than_raises() -> None:
    payload = {"planning_failures": [{"key": None, "detail": None, "manual": None}]}

    text = _joined(payload)

    assert "unknown artifact" in text
    assert "no reason recorded" in text
