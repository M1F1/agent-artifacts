"""Live filesystem contract for Tabnine's documented project and user MCP locations."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.marketplace_lifecycle_e2e_test import _environment

_COORDINATE = "reference/mcp/atlassian"


def _source_with_mcp(root: Path) -> Path:
    fixture = Path(__file__).parent / "fixtures/protocol/native-source-v1"
    source = root / "source"
    shutil.copytree(fixture, source)
    package = source / "artifacts/mcp/atlassian"
    (package / "payload").mkdir(parents=True)
    (package / "artifact.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "type": "mcp",
                "name": "atlassian",
                "version": "1.0.0",
                "summary": "Connect the company Atlassian service.",
                "payload": {"root": "payload", "format": "aart-mcp-v1"},
                "compatibility": {
                    "profiles": ["tabnine"],
                    "platforms": ["darwin", "linux"],
                },
                "install": {
                    "scopes": ["project", "user"],
                    "modes": ["copy"],
                    "effects": ["merge-json"],
                },
                "authors": ["AART maintainers"],
                "license": "MIT",
            }
        ),
        encoding="utf-8",
    )
    (package / "payload/mcp.json").write_text(
        json.dumps(
            {
                "name": "atlassian",
                "server": {
                    "command": "npx",
                    "args": ["-y", "@company/atlassian-mcp"],
                },
            }
        ),
        encoding="utf-8",
    )
    return source


class TabnineMcpE2ETest(unittest.TestCase):
    def test_project_and_user_scopes_use_the_documented_files_independently(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = _source_with_mcp(Path(raw))
            with _environment(source) as environment:
                project_code, project_payload = environment.run(
                    "marketplace",
                    "install",
                    _COORDINATE,
                    "--profile",
                    "tabnine",
                    "--yes",
                )
                user_code, user_payload = environment.run(
                    "marketplace",
                    "install",
                    _COORDINATE,
                    "--profile",
                    "tabnine",
                    "--scope",
                    "user",
                    "--yes",
                )

                self.assertEqual(project_code, 0, project_payload)
                self.assertEqual(user_code, 0, user_payload)
                project_file = environment.project / ".tabnine/mcp_servers.json"
                user_file = environment.home / ".tabnine/mcp_servers.json"
                for path in (project_file, user_file):
                    self.assertEqual(
                        json.loads(path.read_text(encoding="utf-8"))["mcpServers"]["atlassian"][
                            "command"
                        ],
                        "npx",
                    )
                self.assertFalse((environment.project / ".tabnine/agent/settings.json").exists())
                self.assertFalse((environment.home / ".tabnine/agent/settings.json").exists())

                project_status, project_status_payload = environment.run(
                    "marketplace", "status", "--profile", "tabnine"
                )
                user_status, user_status_payload = environment.run(
                    "marketplace",
                    "status",
                    "--profile",
                    "tabnine",
                    "--scope",
                    "user",
                )
                self.assertEqual(project_status, 0, project_status_payload)
                self.assertEqual(user_status, 0, user_status_payload)
                self.assertEqual(project_status_payload["items"][0]["status"], "current")
                self.assertEqual(user_status_payload["items"][0]["status"], "current")

                removed_project, removed_project_payload = environment.run(
                    "marketplace",
                    "uninstall",
                    _COORDINATE,
                    "--profile",
                    "tabnine",
                    "--yes",
                )
                self.assertEqual(removed_project, 0, removed_project_payload)
                self.assertFalse(project_file.exists())
                self.assertTrue(user_file.exists())

                removed_user, removed_user_payload = environment.run(
                    "marketplace",
                    "uninstall",
                    _COORDINATE,
                    "--profile",
                    "tabnine",
                    "--scope",
                    "user",
                    "--yes",
                )
                self.assertEqual(removed_user, 0, removed_user_payload)
                self.assertFalse(user_file.exists())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
