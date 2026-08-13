"""Canonical (protocol 2) setup recipe parser contracts.

Restored from the deleted ``setup_catalog_test`` module: these cover the *current*
recipe revision, not the retired legacy catalog reader that module also carried.
"""

from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError

from agent_artifacts.model import Err, Ok
from agent_artifacts.setup import parse_installer

from tests.setup_fixtures import recipe


class SetupRecipeParserTests(unittest.TestCase):
    def test_valid_recipe_is_frozen_and_hash_bound(self):
        raw = recipe()
        result = parse_installer(
            raw,
            artifact_key="mcp/atlassian",
            descriptor_path="mcp/atlassian/setup/installer.json",
        )

        self.assertIsInstance(result, Ok, getattr(result, "reason", ""))
        installer = result.value
        self.assertEqual(installer.artifact, "mcp/atlassian")
        self.assertEqual(installer.steps[0].use, "macos-keychain.store@1")
        self.assertEqual(len(installer.descriptor_hash), 64)
        with self.assertRaises(FrozenInstanceError):
            installer.purpose = "changed"  # type: ignore[misc]

    def test_unknown_field_and_artifact_mismatch_are_rejected(self):
        unknown = parse_installer(
            recipe(surprise=True),
            artifact_key="mcp/atlassian",
            descriptor_path="mcp/atlassian/setup/installer.json",
        )
        mismatch = parse_installer(
            recipe(artifact="mcp/other"),
            artifact_key="mcp/atlassian",
            descriptor_path="mcp/atlassian/setup/installer.json",
        )

        self.assertIsInstance(unknown, Err)
        self.assertIn("unknown field", unknown.reason)
        self.assertIsInstance(mismatch, Err)
        self.assertIn("does not match", mismatch.reason)

    def test_the_superseded_version_1_pair_is_rejected_with_a_migration_message(self):
        superseded = parse_installer(
            recipe(schema_version=1, protocol_version=1),
            artifact_key="mcp/atlassian",
            descriptor_path="mcp/atlassian/setup/installer.json",
        )

        self.assertIsInstance(superseded, Err)
        # The author has to learn the exact new pair and the document it now requires.
        self.assertIn("schema_version and protocol_version must both be 2", superseded.reason)
        self.assertIn("SETUP.md", superseded.reason)

    def test_recipe_derives_its_package_root_manual_reference(self):
        result = parse_installer(
            recipe(),
            artifact_key="mcp/atlassian",
            descriptor_path="mcp/atlassian/setup/installer.json",
        )

        self.assertIsInstance(result, Ok, getattr(result, "reason", ""))
        self.assertEqual(result.value.schema_version, 2)
        self.assertEqual(result.value.protocol_version, 2)
        self.assertEqual(result.value.manual_path, "mcp/atlassian/SETUP.md")

    def test_recipe_at_a_canonical_object_root_derives_root_setup_document(self):
        result = parse_installer(
            recipe(),
            artifact_key="mcp/atlassian",
            descriptor_path="setup/installer.json",
        )

        self.assertIsInstance(result, Ok, getattr(result, "reason", ""))
        self.assertEqual(result.value.manual_path, "SETUP.md")

    def test_recipe_at_object_root_rejects_a_noncanonical_descriptor_path(self):
        result = parse_installer(
            recipe(),
            artifact_key="mcp/atlassian",
            descriptor_path="./setup/installer.json",
        )

        self.assertIsInstance(result, Err)
        self.assertIn("path", result.reason)

    def test_recipe_rejects_a_noncanonical_descriptor_path(self):
        result = parse_installer(
            recipe(),
            artifact_key="mcp/atlassian",
            descriptor_path="mcp/other/../atlassian/setup/installer.json",
        )

        self.assertIsInstance(result, Err)
        self.assertIn("installer path", result.reason)

    def test_unpinned_docker_and_secret_interpolation_are_rejected(self):
        docker = parse_installer(
            recipe(
                capabilities=["docker", "network", "process"],
                inputs=[],
                required_tools=["docker"],
                steps=[
                    {
                        "id": "image",
                        "use": "docker.pull@1",
                        "with": {"image": "example/tool:latest"},
                    }
                ],
            ),
            artifact_key="mcp/atlassian",
            descriptor_path="mcp/atlassian/setup/installer.json",
        )
        command = parse_installer(
            recipe(
                capabilities=["process"],
                required_tools=[],
                steps=[
                    {
                        "id": "verify",
                        "use": "command.verify@1",
                        "with": {"argv": ["tool", "${api_token}"]},
                    }
                ],
            ),
            artifact_key="mcp/atlassian",
            descriptor_path="mcp/atlassian/setup/installer.json",
        )

        self.assertIsInstance(docker, Err)
        self.assertIn("digest", docker.reason)
        self.assertIsInstance(command, Err)
        self.assertIn("secret", command.reason)

    def test_custom_entrypoint_is_relative_hash_bound_and_capability_gated(self):
        without_capability = parse_installer(
            recipe(custom_entrypoint="install.sh"),
            artifact_key="mcp/atlassian",
            descriptor_path="mcp/atlassian/setup/installer.json",
            custom_bytes=b"#!/bin/sh\n",
        )
        traversing = parse_installer(
            recipe(
                capabilities=["keychain", "filesystem", "process", "custom-code"],
                custom_entrypoint="../install.sh",
            ),
            artifact_key="mcp/atlassian",
            descriptor_path="mcp/atlassian/setup/installer.json",
            custom_bytes=b"#!/bin/sh\n",
        )

        self.assertIsInstance(without_capability, Err)
        self.assertIn("custom-code", without_capability.reason)
        self.assertIsInstance(traversing, Err)
        self.assertIn("relative", traversing.reason)
