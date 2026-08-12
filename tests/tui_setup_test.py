"""Issue #20: immutable setup queue facts in Install confirmation."""

from __future__ import annotations

import unittest
from unittest import mock

from agent_artifacts import tui
from agent_artifacts.model import Artifact, Catalog, Err, Request, SetupStateRecord
from agent_artifacts.profiles.loader import load_profiles
from agent_artifacts.setup import parse_installer
from agent_artifacts.tui_layout import CONTENT_MEASURE
from tests.setup_catalog_test import recipe


class TuiSetupReviewTests(unittest.TestCase):
    def test_confirmation_lists_setup_after_core_artifact_facts(self):
        setup = parse_installer(
            recipe(),
            artifact_key="mcp/atlassian",
            descriptor_path="mcp/atlassian/setup/installer.json",
        ).value
        artifact = Artifact(
            "mcp",
            "atlassian",
            "mcp/atlassian/mcp.json",
            description="Atlassian",
            setup=setup,
        )
        catalog = Catalog({("mcp", "atlassian"): artifact}, {})
        profiles = load_profiles()
        choices = tui.build_install_choices(catalog, ("tabnine",), profiles)

        confirmation = tui.build_install_confirmation(
            source_label="pin:abc",
            source_root="/source",
            project="/project",
            profiles=("tabnine",),
            requested_mode="copy",
            catalog=catalog,
            choices=choices,
            profiles_map=profiles,
        )
        rendered = "\n".join(tui.render_install_confirmation(confirmation))

        self.assertEqual(len(confirmation.setup_queue), 1)
        self.assertIn("Setup queue", rendered)
        self.assertIn("mcp/atlassian@tabnine", rendered)
        self.assertIn("Configure optional Atlassian token access", rendered)
        self.assertIn("Manual alternative", rendered)
        self.assertIn("manual documentation unavailable", rendered)

    def test_confirmation_and_incomplete_post_install_outcome_repeat_v2_manual_route(self):
        setup = parse_installer(
            recipe(schema_version=2, protocol_version=2),
            artifact_key="mcp/atlassian",
            descriptor_path="mcp/atlassian/setup/installer.json",
        ).value
        artifact = Artifact("mcp", "atlassian", "mcp/atlassian/mcp.json", setup=setup)
        queue = tui.build_queue(
            (artifact,),
            ("tabnine",),
            scope="project",
            source_label="pin:abc",
            source_root="/source",
            source_url="https://github.com/acme/catalog/blob/" + "a" * 40,
        )
        record = SetupStateRecord("mcp", "atlassian", "tabnine", "project", "cancelled", "No")
        output: list[str] = []
        with mock.patch("agent_artifacts.commands.setup.run_queue", return_value=(record,)):
            code = tui._run_post_install_setup(
                queue,
                Request(command="install", user_home="/fake-home"),
                scope_root="/project",
                read=lambda _prompt: "n",
                write=output.append,
            )

        self.assertEqual(code, 1)
        rendered = "\n".join(output)
        self.assertIn("Manual alternative", rendered)
        self.assertIn("mcp/atlassian/SETUP.md", rendered)
        self.assertIn("Automated setup is incomplete", rendered)

    def _v2_queue(self):
        setup = parse_installer(
            recipe(schema_version=2, protocol_version=2),
            artifact_key="mcp/atlassian",
            descriptor_path="mcp/atlassian/setup/installer.json",
        ).value
        artifact = Artifact("mcp", "atlassian", "mcp/atlassian/mcp.json", setup=setup)
        return tui.build_queue(
            (artifact,),
            ("tabnine",),
            scope="project",
            source_label="pin:abc",
            source_root="/source",
            source_url="https://github.com/acme/catalog/blob/" + "a" * 40,
        )

    def test_blocking_setup_run_failure_uses_the_shared_stage_record_and_manual_route(self):
        blocked = Err(
            "cannot write setup receipt at /project/.agent-artifacts/setup-runs/ab/receipt.json: "
            "No space left on device; rollback incomplete; recovery state persisted",
            code=3,
        )
        output: list[str] = []
        with mock.patch("agent_artifacts.commands.setup.run_queue", return_value=blocked):
            code = tui._run_post_install_setup(
                self._v2_queue(),
                Request(command="install", user_home="/fake-home"),
                scope_root="/project",
                read=lambda _prompt: "n",
                write=output.append,
            )

        rendered = "\n".join(output)
        self.assertEqual(code, 3)
        self.assertNotIn("error: cannot write setup receipt", rendered)
        self.assertIn("Review could not be set up", rendered)
        self.assertIn("rollback incomplete", rendered)
        self.assertIn("Quit = q", rendered)
        self.assertNotIn("Retry = r", rendered)
        self.assertNotIn("legacy exit code", rendered)
        self.assertIn("Manual alternative", rendered)
        self.assertIn("mcp/atlassian/SETUP.md", rendered)
        self.assertIn("Automated setup is incomplete", rendered)
        self.assertTrue(all(len(line) <= CONTENT_MEASURE for line in output))

    def test_blocking_retry_failure_uses_the_same_stage_record(self):
        cancelled = SetupStateRecord("mcp", "atlassian", "tabnine", "project", "cancelled", "No")
        blocked = Err("cannot read setup state at /project/setup-state.json: denied", code=1)
        output: list[str] = []
        with mock.patch(
            "agent_artifacts.commands.setup.run_queue",
            side_effect=((cancelled,), blocked),
        ) as runner:
            code = tui._run_post_install_setup(
                self._v2_queue(),
                Request(command="install", user_home="/fake-home"),
                scope_root="/project",
                read=lambda _prompt: "y",
                write=output.append,
            )

        rendered = "\n".join(output)
        self.assertEqual(runner.call_count, 2)
        self.assertEqual(code, 1)
        self.assertNotIn("error: cannot read setup state", rendered)
        self.assertIn("Review could not be set up", rendered)
        self.assertIn("cannot read setup state", rendered)
        self.assertIn("Quit = q", rendered)
        self.assertTrue(all(len(line) <= CONTENT_MEASURE for line in output))

    def test_post_install_runner_executes_once_for_complete_queue(self):
        setup = parse_installer(
            recipe(),
            artifact_key="mcp/atlassian",
            descriptor_path="mcp/atlassian/setup/installer.json",
        ).value
        artifact = Artifact("mcp", "atlassian", "mcp/atlassian/mcp.json", setup=setup)
        queue = tui.build_queue(
            (artifact,),
            ("tabnine",),
            scope="project",
            source_label="pin:abc",
            source_root="/source",
        )
        record = SetupStateRecord(
            "mcp", "atlassian", "tabnine", "project", "configured", "Configured"
        )
        output: list[str] = []
        with mock.patch(
            "agent_artifacts.commands.setup.run_queue", return_value=(record,)
        ) as runner:
            code = tui._run_post_install_setup(
                queue,
                Request(command="install", user_home="/fake-home"),
                scope_root="/project",
                read=lambda _prompt: "",
                write=output.append,
            )

        self.assertEqual(code, 0)
        runner.assert_called_once()
        self.assertIn("configured", "\n".join(output))

    def test_preselected_retry_only_reruns_incomplete_items(self):
        setup = parse_installer(
            recipe(),
            artifact_key="mcp/atlassian",
            descriptor_path="mcp/atlassian/setup/installer.json",
        ).value
        artifact = Artifact("mcp", "atlassian", "mcp/atlassian/mcp.json", setup=setup)
        queue = tui.build_queue(
            (artifact,),
            ("tabnine", "claude"),
            scope="project",
            source_label="pin:abc",
            source_root="/source",
        )
        complete = SetupStateRecord(
            "mcp", "atlassian", "tabnine", "project", "configured", "Configured"
        )
        failed = SetupStateRecord(
            "mcp",
            "atlassian",
            "claude",
            "project",
            "cancelled",
            "Cancelled",
            retry_command="aart setup retry mcp/atlassian --profile claude --scope project",
        )
        retried = SetupStateRecord(
            "mcp", "atlassian", "claude", "project", "configured", "Configured"
        )
        with mock.patch(
            "agent_artifacts.commands.setup.run_queue",
            side_effect=((complete, failed), (retried,)),
        ) as runner:
            code = tui._run_post_install_setup(
                queue,
                Request(command="install", user_home="/fake-home"),
                scope_root="/project",
                read=lambda _prompt: "",
                write=lambda _line: None,
            )

        self.assertEqual(code, 0)
        self.assertEqual(runner.call_count, 2)
        retried_queue = runner.call_args_list[1].args[0]
        self.assertEqual([(item.profile) for item in retried_queue], ["claude"])


if __name__ == "__main__":
    unittest.main()
