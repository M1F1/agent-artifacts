"""Issue #20: install -> setup -> idempotent retry -> rollback with fake Keychain."""

from __future__ import annotations

import io
import json
import pathlib
import tempfile
import unittest
from contextlib import redirect_stderr

from agent_artifacts.commands import install
from agent_artifacts.commands import setup as setup_command
from agent_artifacts.model import Request
from agent_artifacts.setup import parse_setup_state, setup_state_path
from agent_artifacts.setup_runtime import SetupRuntime
from tests.setup_catalog_test import recipe
from tests.setup_runtime_test import FakeProcess


class SetupEndToEndTests(unittest.TestCase):
    def test_installed_atlassian_setup_is_stateful_idempotent_and_recoverable(self):
        with (
            tempfile.TemporaryDirectory() as source,
            tempfile.TemporaryDirectory() as project,
            tempfile.TemporaryDirectory() as home,
        ):
            package = pathlib.Path(source, "mcp", "atlassian")
            (package / "setup").mkdir(parents=True)
            (package / "mcp.json").write_text(
                json.dumps(
                    {
                        "name": "atlassian",
                        "description": "Atlassian Rovo MCP.",
                        "server": {"url": "https://mcp.atlassian.com/v1/mcp/authv2"},
                    }
                ),
                encoding="utf-8",
            )
            (package / "setup" / "installer.json").write_bytes(recipe())
            install_request = Request(
                command="install",
                names=("atlassian",),
                profiles=("tabnine",),
                source_dir=source,
                project=project,
                user_home=home,
                yes=True,
            )
            self.assertEqual(install.run(install_request), 0)
            fake = FakeProcess()
            runtime = SetupRuntime(process=fake, platform="darwin", environ={})
            setup_request = Request(
                command="setup",
                setup_action="run",
                names=("mcp/atlassian",),
                profiles=("tabnine",),
                source_dir=source,
                project=project,
                user_home=home,
                yes=True,
            )

            first = setup_command.execute(setup_request, runtime=runtime, write=lambda _line: None)
            second = setup_command.execute(setup_request, runtime=runtime, write=lambda _line: None)

            self.assertEqual((first, second), (0, 0))
            state_path = pathlib.Path(setup_state_path(project))
            state = parse_setup_state(state_path.read_text(encoding="utf-8")).value
            self.assertEqual(state.records[0].status, "already_configured")
            self.assertTrue(pathlib.Path(state.records[0].receipt_path).is_file())
            self.assertEqual(
                pathlib.Path(state.records[0].receipt_path).stat().st_mode & 0o777, 0o600
            )
            self.assertTrue(pathlib.Path(home, ".zshrc").exists())
            self.assertFalse(pathlib.Path(home, ".agent-artifacts").exists())

            rollback_request = Request(
                command="setup",
                setup_action="rollback",
                names=("mcp/atlassian",),
                profiles=("tabnine",),
                project=project,
                user_home=home,
                yes=True,
            )
            original_state = state_path.read_text(encoding="utf-8")
            tampered = json.loads(original_state)
            shell_receipt = next(
                receipt
                for receipt in tampered["records"][0]["receipt"]
                if receipt["module"] == "shell.env-from-keychain@1"
            )
            shell_receipt["path"] = str(pathlib.Path(home, "foreign"))
            state_path.write_text(json.dumps(tampered), encoding="utf-8")
            with redirect_stderr(io.StringIO()):
                unsafe = setup_command.execute(
                    rollback_request, runtime=runtime, write=lambda _line: None
                )
            self.assertEqual(unsafe, 4)
            self.assertTrue(fake.exists)
            state_path.write_text(original_state, encoding="utf-8")

            rolled = setup_command.execute(
                rollback_request, runtime=runtime, write=lambda _line: None
            )

            self.assertEqual(rolled, 0)
            self.assertFalse(fake.exists)
            zshrc = pathlib.Path(home, ".zshrc")
            self.assertTrue(
                not zshrc.exists() or "aart setup:" not in zshrc.read_text(encoding="utf-8")
            )


if __name__ == "__main__":
    unittest.main()
