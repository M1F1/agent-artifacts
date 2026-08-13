"""Issue #20: immutable setup queue facts in Install confirmation."""

from __future__ import annotations

import unittest


from agent_artifacts import tui
from agent_artifacts.model import Artifact, Catalog, Err, Request, SetupStateRecord
from agent_artifacts.profiles.loader import load_profiles
from agent_artifacts.setup import parse_installer
from agent_artifacts.tui_layout import CONTENT_MEASURE
from tests.setup_fixtures import recipe


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
        self.assertIn("mcp/atlassian/SETUP.md", rendered)
