"""Issue #20: pure setup queue, plan, managed block, and continuation rules."""

from __future__ import annotations

import unittest

from agent_artifacts.model import Artifact, SetupQueueItem
from agent_artifacts.setup import (
    build_queue,
    mark_unstarted_skipped,
    parse_installer,
    plan_setup,
    render_setup_review,
)
from tests.setup_fixtures import recipe


def installer():
    return parse_installer(
        recipe(),
        artifact_key="mcp/atlassian",
        descriptor_path="mcp/atlassian/setup/installer.json",
    ).value


class SetupPlanningTests(unittest.TestCase):
    def test_queue_is_stable_deduplicated_and_only_contains_setup_artifacts(self):
        configured = Artifact(
            "mcp", "atlassian", "mcp/atlassian/mcp.json", description="Atlassian", setup=installer()
        )
        ordinary = Artifact("mcp", "postgres", "mcp/postgres/mcp.json")

        queue = build_queue(
            (configured, ordinary, configured),
            ("tabnine", "claude"),
            scope="user",
            source_label="pin:abc",
            source_root="/source",
        )

        self.assertEqual(
            [(item.artifact_name, item.profile) for item in queue],
            [("atlassian", "tabnine"), ("atlassian", "claude")],
        )

    def test_plan_resolves_home_without_reading_environment_and_hashes_exact_effects(self):
        item = SetupQueueItem(
            artifact_type="mcp",
            artifact_name="atlassian",
            profile="tabnine",
            scope="user",
            source_label="pin:abc",
            source_root="/source",
            installer=installer(),
        )

        first = plan_setup(item, target_root="/fake-home", platform="darwin")
        second = plan_setup(item, target_root="/fake-home", platform="darwin")

        self.assertEqual(first, second)
        self.assertEqual(len(first.plan_hash), 64)
        self.assertEqual(first.effects[1].target, "/fake-home/.zshrc")
        review = "\n".join(render_setup_review(first))
        self.assertIn("pin:abc", review)
        self.assertIn("Store a secret in macOS Keychain", review)
        self.assertIn("details     required tool: /usr/bin/security", review)
        self.assertIn("removes only changes created by this run", review)
        self.assertNotIn("api_token=", review)

    def test_non_darwin_plan_is_unsupported_and_has_no_effects(self):
        item = SetupQueueItem(
            "mcp", "atlassian", "tabnine", "user", "pin:abc", "/source", installer()
        )

        plan = plan_setup(item, target_root="/fake-home", platform="linux")

        self.assertEqual(plan.preflight_status, "unsupported")
        self.assertEqual(plan.effects, ())

    def test_relative_targets_use_scope_root_while_tilde_targets_use_home_root(self):
        parsed = parse_installer(
            recipe(
                required_tools=[],
                capabilities=["filesystem"],
                inputs=[],
                steps=[
                    {
                        "id": "project",
                        "use": "file.managed-block@1",
                        "with": {"file": ".config/tool", "content": "project=true"},
                    },
                    {
                        "id": "home",
                        "use": "file.managed-block@1",
                        "with": {"file": "~/.zshrc", "content": "home=true"},
                    },
                ],
            ),
            artifact_key="mcp/atlassian",
            descriptor_path="mcp/atlassian/setup/installer.json",
        ).value
        item = SetupQueueItem(
            "mcp", "atlassian", "tabnine", "project", "pin:abc", "/source", parsed
        )

        plan = plan_setup(
            item,
            target_root="/project",
            home_root="/fake-home",
            platform="darwin",
        )

        self.assertEqual(
            [effect.target for effect in plan.effects],
            ["/project/.config/tool", "/fake-home/.zshrc"],
        )

    def test_stop_marks_every_unstarted_item_skipped(self):
        queue = tuple(
            SetupQueueItem("mcp", "atlassian", p, "user", "pin:abc", "/src", installer())
            for p in ("tabnine", "claude", "opencode")
        )

        records = mark_unstarted_skipped(queue[1:], detail="Stopped after failure")

        self.assertEqual([record.status for record in records], ["skipped", "skipped"])
        self.assertTrue(all("setup retry" in record.retry_command for record in records))


if __name__ == "__main__":
    unittest.main()
