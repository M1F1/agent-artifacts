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
    render_setup_outcome,
    render_setup_review,
)
from agent_artifacts.tui_layout import CONTENT_MEASURE
from tests.setup_fixtures import recipe


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
                purpose="Configure token=do-not-render through reviewed automation.",
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
                retry_command="aart setup retry mcp/atlassian --profile tabnine --scope project",
                recovery=("Remove only a file created by this run.",),
                manual=reference,
                width=width,
            )

            self.assertTrue(all(len(line) <= min(width, CONTENT_MEASURE) for line in rendered))
            text = "\n".join(rendered)
            self.assertIn("Setup outcome", text)
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
