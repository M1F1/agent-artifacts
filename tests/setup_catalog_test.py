"""Issue #20: declarative setup recipe and catalog attachment contracts."""

from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
from dataclasses import FrozenInstanceError

from agent_artifacts.model import Err, Ok, Request
from agent_artifacts.setup import parse_installer
from agent_artifacts.source import open_source


def recipe(**changes: object) -> bytes:
    value: dict[str, object] = {
        "schema_version": 1,
        "protocol_version": 1,
        "artifact": "mcp/atlassian",
        "purpose": "Configure optional Atlassian token access.",
        "platforms": ["darwin"],
        "help_urls": [{"label": "Atlassian auth", "url": "https://example.test/auth"}],
        "required_tools": ["/usr/bin/security"],
        "capabilities": ["keychain", "filesystem"],
        "inputs": [
            {
                "id": "api_token",
                "type": "secret",
                "prompt": "Paste the Atlassian API token",
                "help_url": "https://example.test/token",
            }
        ],
        "steps": [
            {
                "id": "token",
                "use": "macos-keychain.store@1",
                "with": {
                    "input": "api_token",
                    "service": "aart/mcp/atlassian",
                    "account": "default",
                },
            },
            {
                "id": "shell",
                "use": "shell.env-from-keychain@1",
                "with": {
                    "file": "~/.zshrc",
                    "variables": {
                        "ATLASSIAN_API_TOKEN": {
                            "service": "aart/mcp/atlassian",
                            "account": "default",
                        }
                    },
                },
            },
        ],
    }
    value.update(changes)
    return json.dumps(value).encode()


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

    def test_v2_recipe_derives_its_package_root_manual_reference(self):
        result = parse_installer(
            recipe(schema_version=2, protocol_version=2),
            artifact_key="mcp/atlassian",
            descriptor_path="mcp/atlassian/setup/installer.json",
        )

        self.assertIsInstance(result, Ok, getattr(result, "reason", ""))
        self.assertEqual(result.value.schema_version, 2)
        self.assertEqual(result.value.protocol_version, 2)
        self.assertEqual(result.value.manual_path, "mcp/atlassian/SETUP.md")

    def test_v2_recipe_rejects_a_noncanonical_descriptor_path(self):
        result = parse_installer(
            recipe(schema_version=2, protocol_version=2),
            artifact_key="mcp/atlassian",
            descriptor_path="mcp/other/../atlassian/setup/installer.json",
        )

        self.assertIsInstance(result, Err)
        self.assertIn("version-2 installer path", result.reason)

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


class SetupSourceTests(unittest.TestCase):
    def test_directory_mcp_attaches_validated_installer_without_executing_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = pathlib.Path(tmp) / "mcp" / "atlassian"
            (package / "setup").mkdir(parents=True)
            (package / "mcp.json").write_text(
                json.dumps(
                    {
                        "name": "atlassian",
                        "description": "Use the Atlassian remote MCP server.",
                        "server": {"url": "https://mcp.atlassian.com/v1/mcp/authv2"},
                    }
                ),
                encoding="utf-8",
            )
            (package / "setup" / "installer.json").write_bytes(recipe())

            result = open_source(Request(command="list", source_dir=tmp)).value.catalog()

            self.assertIsInstance(result, Ok, getattr(result, "reason", ""))
            installer = result.value.artifacts[("mcp", "atlassian")].setup
            self.assertIsNotNone(installer)
            assert installer is not None
            self.assertEqual(installer.descriptor_path, "mcp/atlassian/setup/installer.json")

    def test_invalid_installer_invalidates_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = pathlib.Path(tmp) / "mcp" / "atlassian"
            (package / "setup").mkdir(parents=True)
            (package / "mcp.json").write_text(
                json.dumps(
                    {
                        "name": "atlassian",
                        "description": "Use Atlassian.",
                        "server": {"url": "https://example.test"},
                    }
                ),
                encoding="utf-8",
            )
            (package / "setup" / "installer.json").write_bytes(recipe(schema_version=2))

            result = open_source(Request(command="list", source_dir=tmp)).value.catalog()

            self.assertIsInstance(result, Err)
            self.assertIn("schema_version", result.reason)

    def test_v2_installer_requires_a_regular_utf8_package_root_setup_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = pathlib.Path(tmp) / "mcp" / "atlassian"
            (package / "setup").mkdir(parents=True)
            (package / "mcp.json").write_text(
                json.dumps(
                    {
                        "name": "atlassian",
                        "description": "Use Atlassian.",
                        "server": {"url": "https://example.test"},
                    }
                ),
                encoding="utf-8",
            )
            (package / "setup" / "installer.json").write_bytes(
                recipe(schema_version=2, protocol_version=2)
            )

            missing = open_source(Request(command="list", source_dir=tmp)).value.catalog()
            self.assertIsInstance(missing, Err)
            self.assertIn("SETUP.md", missing.reason)

            (package / "SETUP.md").write_bytes(b"\xff")
            unreadable = open_source(Request(command="list", source_dir=tmp)).value.catalog()
            self.assertIsInstance(unreadable, Err)
            self.assertIn("UTF-8", unreadable.reason)

            (package / "SETUP.md").write_text("Configure this manually.", encoding="utf-8")
            valid = open_source(Request(command="list", source_dir=tmp)).value.catalog()
            self.assertIsInstance(valid, Ok, getattr(valid, "reason", ""))
            installer = valid.value.artifacts[("mcp", "atlassian")].setup
            assert installer is not None
            self.assertEqual(installer.manual_path, "mcp/atlassian/SETUP.md")

    def test_v2_custom_entrypoint_requires_the_manual_setup_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = pathlib.Path(tmp) / "mcp" / "atlassian"
            setup = package / "setup"
            setup.mkdir(parents=True)
            (package / "mcp.json").write_text(
                json.dumps(
                    {
                        "name": "atlassian",
                        "description": "Use Atlassian.",
                        "server": {"url": "https://example.test"},
                    }
                ),
                encoding="utf-8",
            )
            (package / "SETUP.md").write_text("Configure this manually.", encoding="utf-8")
            (setup / "installer.json").write_bytes(
                recipe(
                    schema_version=2,
                    protocol_version=2,
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
                )
            )
            script = setup / "install.sh"
            script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

            missing_header = open_source(Request(command="list", source_dir=tmp)).value.catalog()
            self.assertIsInstance(missing_header, Err)
            self.assertIn("SETUP.md header", missing_header.reason)

            script.write_text(
                "#!/bin/sh\n# AART manual setup: see ../SETUP.md\nexit 0\n",
                encoding="utf-8",
            )
            valid = open_source(Request(command="list", source_dir=tmp)).value.catalog()
            self.assertIsInstance(valid, Ok, getattr(valid, "reason", ""))

    def test_setup_package_symlink_cannot_escape_the_reviewed_source(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            package = pathlib.Path(outside)
            (package / "setup").mkdir()
            (package / "mcp.json").write_text(
                json.dumps(
                    {
                        "name": "atlassian",
                        "description": "Use Atlassian.",
                        "server": {"url": "https://example.test"},
                    }
                ),
                encoding="utf-8",
            )
            (package / "setup" / "installer.json").write_bytes(recipe())
            mcp_root = pathlib.Path(tmp, "mcp")
            mcp_root.mkdir()
            mcp_root.joinpath("atlassian").symlink_to(package, target_is_directory=True)

            result = open_source(Request(command="list", source_dir=tmp)).value.catalog()

            self.assertIsInstance(result, Err)
            self.assertIn("regular file", result.reason)


if __name__ == "__main__":
    unittest.main()
