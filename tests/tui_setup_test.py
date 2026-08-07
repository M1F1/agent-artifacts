"""Issue #20: immutable setup queue facts in Install confirmation."""

from __future__ import annotations

import unittest
from unittest import mock

from agent_artifacts import tui
from agent_artifacts.model import Artifact, Catalog, Request, SetupStateRecord
from agent_artifacts.profiles.loader import load_profiles
from agent_artifacts.setup import parse_installer
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
