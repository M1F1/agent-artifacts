"""ERR09-B: bounded, non-secret setup-review projection."""

from __future__ import annotations

import os
import unittest
from dataclasses import replace

from agent_artifacts.model import SetupQueueItem
from agent_artifacts.setup import (
    manual_reference,
    parse_installer,
    plan_setup,
    project_setup_review,
    render_run_summary,
    render_setup_outcome,
    render_setup_review,
    setup_banner,
)
from agent_artifacts.tui_layout import CONTENT_MEASURE
from tests.credential_fixtures import assignment
from tests.setup_fixtures import recipe

RETRY = "aart marketplace setup mcp/atlassian --profile tabnine --scope project"


def installer(**changes: object):
    return parse_installer(
        recipe(**changes),
        artifact_key="mcp/atlassian",
        descriptor_path="mcp/atlassian/setup/installer.json",
    ).value


class SetupReviewProjectionTests(unittest.TestCase):
    def test_reference_keeps_relative_route_and_uses_only_a_commit_pinned_url(self):
        item = SetupQueueItem(
            "mcp",
            "atlassian",
            "tabnine",
            "project",
            "pin:abc",
            "/materialized/catalog",
            installer(),
            "https://github.com/acme/catalog/blob/" + "a" * 40,
        )

        reference = manual_reference(item)

        self.assertEqual(reference.relative_path, "mcp/atlassian/SETUP.md")
        self.assertEqual(
            reference.source,
            "https://github.com/acme/catalog/blob/" + "a" * 40 + "/mcp/atlassian/SETUP.md",
        )

    def test_an_unpinned_or_missing_web_origin_uses_the_absolute_local_manual_path(self):
        item = SetupQueueItem(
            "mcp",
            "atlassian",
            "tabnine",
            "project",
            "main:abc",
            "/materialized/catalog",
            installer(),
            "https://github.com/acme/catalog/blob/main",
        )

        reference = manual_reference(item)

        self.assertEqual(reference.source, "/materialized/catalog/mcp/atlassian/SETUP.md")

    def test_a_route_escaping_the_source_root_never_reaches_the_rendered_review(self):
        # The derived route cannot escape today; the guard is what keeps that true for any
        # future producer, so it is pinned here rather than trusted.
        escaping = replace(installer(), manual_path=os.path.join("..", "outside", "SETUP.md"))
        item = SetupQueueItem(
            "mcp", "atlassian", "tabnine", "project", "pin:abc", "/source/catalog", escaping
        )
        plan = plan_setup(item, target_root="/project", platform="darwin")

        review = project_setup_review(plan)

        self.assertEqual(review.manual.relative_path, os.path.join("..", "outside", "SETUP.md"))
        self.assertEqual(review.manual.source, review.manual.relative_path)
        self.assertNotIn("/source/outside", "\n".join(render_setup_review(plan)))

    def test_effects_are_safe_records_with_identity_and_recovery_at_every_width(self):
        item = SetupQueueItem(
            "mcp",
            "atlassian",
            "tabnine",
            "project",
            "pin:abc",
            "/source",
            installer(
                purpose="Configure "
                + assignment("token", "do-not-render")
                + " through reviewed automation.",
                required_tools=["/usr/bin/security", "api_token=do-not-render"],
            ),
            "https://github.com/acme/catalog/blob/" + "b" * 40,
        )
        plan = plan_setup(
            item, target_root="/very/long/project/root/" + "x" * 120, platform="darwin"
        )

        review = project_setup_review(plan)

        self.assertEqual([effect.index for effect in review.effects], [1, 2])
        self.assertTrue(all(effect.identity and effect.recovery for effect in review.effects))
        self.assertNotIn("do-not-render", repr(review))
        for width in (40, 80, 120, 200):
            rendered = render_setup_review(plan, width=width)
            self.assertTrue(rendered)
            self.assertTrue(all(len(line) <= min(width, CONTENT_MEASURE) for line in rendered))
            text = "\n".join(rendered)
            self.assertIn("Manual alternative", text)
            self.assertIn("1. Store a secret in macOS Keychain", text)
            self.assertNotIn(" -> ", text)
            self.assertNotIn("do-not-render", text)
            self.assertNotIn("api_token", text)

    def test_empty_capabilities_and_manual_recovery_remain_visible(self):
        item = SetupQueueItem(
            "mcp",
            "atlassian",
            "tabnine",
            "project",
            "pin:abc",
            "/source",
            installer(
                capabilities=[],
                required_tools=[],
                inputs=[],
                steps=[
                    {
                        "id": "restart",
                        "use": "restart.notice@1",
                        "with": {"message": "Restart the harness."},
                    }
                ],
            ),
        )
        plan = plan_setup(item, target_root="/project", platform="darwin")

        review = project_setup_review(plan)

        self.assertEqual(review.capabilities, ())
        self.assertEqual(review.effects[0].capability, "none")
        self.assertEqual(review.effects[0].recovery, "manual recovery is required")
        self.assertIn("capabilities    none", "\n".join(render_setup_review(plan)))

    def test_incomplete_outcome_is_a_bounded_redacted_record_with_the_manual_route(self):
        item = SetupQueueItem(
            "mcp",
            "atlassian",
            "tabnine",
            "project",
            "pin:abc",
            "/source",
            installer(),
            "https://github.com/acme/catalog/blob/" + "a" * 40,
        )
        reference = manual_reference(item)

        for width in (40, 80, 120, 200):
            rendered = render_setup_outcome(
                artifact="mcp/atlassian",
                profile="tabnine",
                scope="project",
                status="cancelled",
                detail="setup api_token=do-not-render was cancelled",
                retry_command=RETRY,
                recovery=("Remove only a file created by this run.",),
                manual=reference,
                width=width,
            )

            # Every line is bounded except the command, which is printed whole on purpose: a
            # folded command is pasted broken, which is the defect `AD-34` and `AD-35` closed.
            prose = [line for line in rendered if not line.strip().startswith("aart ")]
            self.assertTrue(all(len(line) <= min(width, CONTENT_MEASURE) for line in prose))
            self.assertIn("    " + RETRY, rendered)
            text = "\n".join(rendered)
            # The block opens with a rule that names the item, not with a sentence: a queue
            # prints these back to back and prose does not separate one item from the next.
            self.assertIn("mcp/atlassian@tabnine (project)", text)
            self.assertIn("SUMMARY", text)
            self.assertIn("Manual alternative", text)
            self.assertIn("mcp/atlassian/SETUP.md", text)
            self.assertNotIn("do-not-render", text)

    def test_outcome_manual_status_separates_an_unstarted_setup_from_a_partial_one(self):
        item = SetupQueueItem(
            "mcp",
            "atlassian",
            "tabnine",
            "project",
            "pin:abc",
            "/source",
            installer(),
            "https://github.com/acme/catalog/blob/" + "a" * 40,
        )
        reference = manual_reference(item)

        def rendered(status: str) -> str:
            return "\n".join(
                render_setup_outcome(
                    artifact="mcp/atlassian",
                    profile="tabnine",
                    scope="project",
                    status=status,
                    detail="setup did not complete",
                    manual=reference,
                )
            )

        for status in ("declined", "planning-failed", "unsupported"):
            self.assertIn("No setup effect has run.", rendered(status))
            self.assertNotIn("Automated setup is incomplete", rendered(status))
        # A completed rollback also reports ``skipped``, so it may never claim nothing ran.
        for status in ("cancelled", "apply_failed_rolled_back", "rollback-incomplete", "skipped"):
            self.assertIn("Automated setup is incomplete", rendered(status))
            self.assertNotIn("No setup effect has run.", rendered(status))

    def test_custom_review_withholds_script_body_and_keeps_its_recovery_record(self):
        script = b"#!/bin/sh\n# AART manual setup: see ../SETUP.md\n# api_token=do-not-render\n"
        configured = parse_installer(
            recipe(
                capabilities=["process", "custom-code"],
                required_tools=[],
                inputs=[],
                steps=[
                    {
                        "id": "restart",
                        "use": "restart.notice@1",
                        "with": {"message": "Restart the harness."},
                    }
                ],
                custom_entrypoint="install.sh",
            ),
            artifact_key="mcp/atlassian",
            descriptor_path="mcp/atlassian/setup/installer.json",
            custom_bytes=script,
        ).value
        item = SetupQueueItem(
            "mcp", "atlassian", "tabnine", "project", "pin:abc", "/source", configured
        )
        plan = plan_setup(item, target_root="/project", platform="darwin")

        review = project_setup_review(plan)

        custom = review.effects[-1]
        self.assertEqual(custom.identity, "Run reviewed custom setup protocol")
        self.assertEqual(custom.details, "custom script body is withheld from review")
        self.assertEqual(custom.recovery, "removes only changes created by this run")
        self.assertNotIn("do-not-render", repr(review))


if __name__ == "__main__":
    unittest.main()


class SetupBoundaryTests(unittest.TestCase):
    """`AD-40`. A queue of six printed one wall of text with nothing saying whose turn it was.

    Every shape the run prints — effects, approval prompts, the `security` password request that
    names no artifact at all — is identical from item to item, and effect numbering restarts at 1
    for each, which reads as a glitch rather than as a boundary. The operator could not tell which
    server they were being asked to give a credential to.
    """

    def test_the_banner_is_one_rule_of_exactly_the_measure(self):
        (line,) = setup_banner(
            artifact="registry/mcp/alation@0.9.1",
            profile="claude",
            scope="user",
            phase="START",
            position=2,
            total=3,
        )

        self.assertEqual(len(line), CONTENT_MEASURE)
        self.assertIn("registry/mcp/alation@0.9.1@claude (user)", line)
        self.assertIn("setup 2/3", line)
        self.assertIn("START", line)
        self.assertTrue(line.startswith("-") and line.endswith("-"), line)

    def test_a_narrow_terminal_drops_the_rule_and_keeps_every_word(self):
        """The rule is decoration and the words are the point, so the rule gives way first."""

        for width in (20, 32, 40, 60, 80, 100, 200):
            lines = setup_banner(
                artifact="registry/mcp/github-docker@1.0.0",
                profile="claude",
                scope="project",
                phase="SUMMARY",
                position=1,
                total=2,
                width=width,
            )
            bound = min(width, CONTENT_MEASURE)

            for line in lines:
                self.assertLessEqual(len(line), bound, (width, line))
            if width < 40:
                # A column count smaller than the identity itself is the one case where the
                # identity breaks across lines, exactly as every other wrapped value in this
                # tool does. Nothing is dropped; it is only folded.
                continue
            text = " ".join(lines)
            for word in ("registry/mcp/github-docker@1.0.0@claude", "(project)", "1/2", "SUMMARY"):
                self.assertIn(word, text, width)

    def test_one_artifact_selected_for_two_harnesses_gets_two_distinct_banners(self):
        """The queue is an artifacts x profiles product, so the profile is identity, not decor."""

        first = setup_banner(
            artifact="mcp/atlassian", profile="claude", scope="user", phase="START"
        )
        second = setup_banner(
            artifact="mcp/atlassian", profile="cursor", scope="user", phase="START"
        )

        self.assertNotEqual(first, second)

    def test_the_run_summary_tallies_the_run_and_names_only_what_failed(self):
        rendered = "\n".join(render_run_summary(_ROWS))

        self.assertIn("RUN SUMMARY", rendered)
        self.assertIn("selected    3", rendered)
        self.assertIn("configured  2", rendered)
        self.assertIn("incomplete  1", rendered)
        self.assertIn("Not configured", rendered)
        self.assertIn("mcp/alation@claude (user)", rendered)
        # The two that worked are counted, not repeated: the summary exists to find the one that
        # did not, in a run whose per-item blocks have already scrolled past.
        self.assertNotIn("mcp/atlassian@claude (user)", rendered)

    def test_the_run_summary_redacts_the_detail_it_repeats(self):
        """A repeat is a second chance to print a credential, so it is redacted twice."""

        rendered = "\n".join(render_run_summary(_ROWS))

        self.assertNotIn("do-not-render", rendered)
        self.assertIn("[redacted]", rendered)

    def test_the_retry_command_is_printed_whole_on_one_line(self):
        lines = render_run_summary(_ROWS)

        self.assertIn("    " + _RETRY, lines)

    def test_a_run_with_no_items_prints_no_summary(self):
        self.assertEqual(render_run_summary(()), ())


_RETRY = (
    "aart marketplace setup mcp/alation --profile claude --scope user --yes --approve-setup-effects"
)

_ROWS = (
    {
        "artifact": "mcp/atlassian",
        "profile": "claude",
        "scope": "user",
        "status": "configured",
        "detail": "Setup configured",
        "successful": True,
        "retry_command": "",
    },
    {
        "artifact": "mcp/alation",
        "profile": "claude",
        "scope": "user",
        "status": "apply-failed-rolled-back",
        "detail": "setup api_token=do-not-render was rejected by the server",
        "successful": False,
        "retry_command": _RETRY,
    },
    {
        "artifact": "mcp/github-docker",
        "profile": "claude",
        "scope": "user",
        "status": "already-configured",
        "detail": "Setup already configured",
        "successful": True,
        "retry_command": "",
    },
)
