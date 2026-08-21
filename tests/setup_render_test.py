"""RR-2A: the text renderer prints what the ``setup`` JSON payload carries.

Design §3.4. Counts may accompany content and may not replace it. These tests are written
against the payload dict because that is the value `--json` emits — a field the text renderer
drops is a measurable difference between the two outputs, not a matter of taste.
"""

from __future__ import annotations

from types import SimpleNamespace

from agent_artifacts.commands.marketplace import _setup_reminders
from agent_artifacts.setup import render_setup_outcome
from agent_artifacts.setup_render import render_setup_payload
from tests.function_cases import function_test_case

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
                "coordinate": "registry-a/mcp/github-docker@1.0.0",
                "profile": "claude",
                "scope": "project",
                "status": "configured",
                "detail": "Setup completed in 4.2s",
                "successful": True,
                "retry": "",
                "recovery": [],
            }
        ],
    }

    lines = render_setup_payload(payload)
    text = "\n".join(lines)

    # The block opens with the same rule the wizard opens it with, and names the artifact the
    # same way: `coordinate@profile (scope)`, not the `#`/`/` key that only a machine reads.
    assert "registry-a/mcp/github-docker@1.0.0@claude (project)" in text
    assert "setup 1/1 — SUMMARY" in text
    assert "Setup completed in 4.2s" in text
    assert "Setup: planned=1, failures=0, configured=1, incomplete=0" in lines
    # And the run is tallied once, at the end, after the counts it does not replace.
    assert "RUN SUMMARY" in text
    assert "  selected    1" in lines


def test_an_item_written_before_the_identity_fields_existed_still_names_itself() -> None:
    """A payload from an older run carries only `key`, and the rule falls back to it.

    The fields beside it are additive, so a stored `--json` document from `2.8.4` renders rather
    than losing the artifact it is about.
    """

    text = _joined(
        {
            "planned": [],
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
    )

    assert "registry-a/mcp/github-docker@1.0.0#claude/project" in text
    assert "SUMMARY" in text


def test_the_recovery_note_reaches_this_surface_too() -> None:
    """`AD-42`. The wizard printed these and this path dropped them.

    `AD-38` rewrote the Docker note so it names Docker, the tag, and what a rollback would do to
    the image. Everyone who ran setup from the command line saw none of it.
    """

    note = (
        "Docker image tag aart/mcp/github-docker:1.0.0 did not exist before this run and this "
        "run created it. Rollback removes it with `docker image rm`."
    )
    text = _joined(
        {
            "planned": [],
            "planning_failures": [],
            "configured": 1,
            "incomplete": 0,
            "items": [
                {
                    "key": "registry-a/mcp/github-docker@1.0.0#claude/project",
                    "coordinate": "registry-a/mcp/github-docker@1.0.0",
                    "profile": "claude",
                    "scope": "project",
                    "status": "configured",
                    "detail": "Setup configured",
                    "successful": True,
                    "retry": "",
                    "recovery": [note],
                }
            ],
        }
    )

    assert "Recovery" in text
    assert "Docker image tag aart/mcp/github-docker:1.0.0" in text


def test_a_failed_item_carries_the_command_that_repeats_it_whole() -> None:
    """The retry is the operator's next move, so it is never folded to fit the measure."""

    retry = (
        "aart marketplace setup registry-a/mcp/github-docker@1.0.0 --profile claude "
        "--scope project --yes --approve-setup-effects"
    )
    lines = render_setup_payload(
        {
            "planned": [],
            "planning_failures": [],
            "configured": 0,
            "incomplete": 1,
            "items": [
                {
                    "key": "registry-a/mcp/github-docker@1.0.0#claude/project",
                    "coordinate": "registry-a/mcp/github-docker@1.0.0",
                    "profile": "claude",
                    "scope": "project",
                    "status": "apply-failed-rolled-back",
                    "detail": "setup failed",
                    "successful": False,
                    "retry": retry,
                    "recovery": [],
                }
            ],
        }
    )

    # Once in the item's own block, once in the run summary: both whole, on one line each.
    assert lines.count("    " + retry) == 2
    assert "Not configured" in "\n".join(lines)


def test_both_surfaces_print_the_same_block_for_the_same_item() -> None:
    """The strongest form of `AD-40`/`AD-42`: not similar output, the same lines.

    The wizard and the `--json` path are one body with two callers. Anything that can drift is
    something one surface knows and the other does not — which is exactly how the recovery note
    came to exist on one of them only.
    """

    note = (
        "Docker image tag aart/mcp/github-docker:1.0.0 did not exist before this run and this "
        "run created it.\ndocker image rm aart/mcp/github-docker:1.0.0"
    )
    retry = (
        "aart marketplace setup registry-a/mcp/github-docker@1.0.0 --profile claude "
        "--scope project --yes --approve-setup-effects"
    )
    from_wizard = list(
        render_setup_outcome(
            artifact="registry-a/mcp/github-docker@1.0.0",
            profile="claude",
            scope="project",
            status="apply-failed-rolled-back",
            detail="setup failed",
            retry_command=retry,
            recovery=(note,),
            position=1,
            total=1,
        )
    )
    from_payload = list(
        render_setup_payload(
            {
                "planned": [],
                "planning_failures": [],
                "configured": 0,
                "incomplete": 1,
                "items": [
                    {
                        "key": "registry-a/mcp/github-docker@1.0.0#claude/project",
                        "coordinate": "registry-a/mcp/github-docker@1.0.0",
                        "profile": "claude",
                        "scope": "project",
                        "status": "apply-failed-rolled-back",
                        "detail": "setup failed",
                        "successful": False,
                        "retry": retry,
                        "recovery": [note],
                    }
                ],
            }
        )
    )

    # The payload renderer opens the section with a blank line and closes the report with the
    # counts and the run summary; between them is the item, line for line.
    assert from_payload[1 : 1 + len(from_wizard)] == from_wizard
    # And the command inside the note survived the trip through the payload unfolded.
    assert "    docker image rm aart/mcp/github-docker:1.0.0" in from_wizard


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


def test_the_reload_next_step_is_one_row_for_the_run_not_one_per_artifact() -> None:
    """`AD-39` on the `--json` path, which had the same per-item loop the wizard had.

    The row carries no artifact key any more: it never described one. Reloading a shell is a
    property of the machine, and the key is what made the same instruction repeat per item.
    """

    record = SimpleNamespace(
        receipt=[{"module": "shell.env-from-keychain@1", "path": "/tmp/home/.zshrc"}]
    )
    outcome = SimpleNamespace(
        items=[
            SimpleNamespace(record=record),
            SimpleNamespace(record=record),
            SimpleNamespace(record=None),
        ]
    )

    rows = _setup_reminders(outcome)

    assert len(rows) == 1
    assert "key" not in rows[0]
    assert rows[0]["commands"] == ["source /tmp/home/.zshrc"]
    assert "already open does not have them yet" in rows[0]["detail"]

    # And the shared renderer prints that one row once, on this surface too.
    text = "\n".join(
        render_setup_payload(
            {
                "planned": PLANNED["planned"],
                "planning_failures": [],
                "configured": 1,
                "incomplete": 0,
                "items": [],
                "next_steps": rows,
            }
        )
    )
    assert text.count("Next step") == 1


# Collected by `unittest discover`, which sees `TestCase` subclasses and nothing
# else; without this the functions above are imported and never run (`AD-41`).
SetupRenderTests = function_test_case(globals(), name="SetupRenderTests")
