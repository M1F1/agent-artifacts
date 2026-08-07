"""Issue #20: setup CLI surface and local status behavior."""

from __future__ import annotations

import io
import json
import pathlib
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from agent_artifacts import cli
from agent_artifacts.commands import install
from agent_artifacts.commands import setup as setup_command
from agent_artifacts.model import Err, Request, SetupQueueItem, SetupStateRecord
from agent_artifacts.setup import parse_installer
from agent_artifacts.setup_runtime import ProcessResult, SetupRuntime
from tests.setup_catalog_test import recipe


class SetupCliTests(unittest.TestCase):
    def test_setup_is_registered(self):
        self.assertIn("setup", cli.DISPATCH)

    def test_run_maps_nested_action_selection_and_scope(self):
        captured: list[Request] = []

        def run(request: Request) -> int:
            captured.append(request)
            return 0

        with patch.dict(cli.DISPATCH, {"setup": run}):
            code = cli.main(
                [
                    "setup",
                    "run",
                    "mcp/atlassian",
                    "--profile",
                    "tabnine",
                    "--scope",
                    "user",
                    "--yes",
                ]
            )

        self.assertEqual(code, 0)
        self.assertEqual(captured[0].setup_action, "run")
        self.assertEqual(captured[0].names, ("mcp/atlassian",))
        self.assertEqual(captured[0].profiles, ("tabnine",))
        self.assertEqual(captured[0].scope, "user")

    def test_status_is_local_only_parser_surface(self):
        parser = cli.build_parser()
        args = parser.parse_args(["setup", "status", "--scope", "project", "--json"])
        request = cli._to_request(args)

        self.assertEqual(request.setup_action, "status")
        self.assertTrue(request.json)
        self.assertIsNone(request.repo)
        self.assertIsNone(request.source_dir)


class _FailsFirstAdd:
    def __init__(self):
        self.failed = False
        self.exists = False

    def __call__(self, argv, *, env, cwd, timeout, capture):
        if "find-generic-password" in argv:
            return ProcessResult(0 if self.exists else 44)
        if "add-generic-password" in argv and not self.failed:
            self.failed = True
            return ProcessResult(1)
        if "add-generic-password" in argv:
            self.exists = True
        if "delete-generic-password" in argv:
            self.exists = False
        return ProcessResult(0)


class SetupQueueCommandTests(unittest.TestCase):
    def queue(self):
        installer = parse_installer(
            recipe(required_tools=[]),
            artifact_key="mcp/atlassian",
            descriptor_path="mcp/atlassian/setup/installer.json",
        ).value
        return tuple(
            SetupQueueItem("mcp", "atlassian", profile, "project", "pin:abc", "/source", installer)
            for profile in ("tabnine", "claude")
        )

    def test_queue_continues_after_normal_failure(self):
        process = _FailsFirstAdd()
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as home:
            results = setup_command.run_queue(
                self.queue(),
                scope_root=root,
                target_root=home,
                request=Request(command="setup", setup_action="run", yes=True),
                runtime=SetupRuntime(process=process, platform="darwin", environ={}),
                write=lambda _line: None,
            )

        self.assertEqual(
            [record.status for record in results],
            ["apply_failed_rolled_back", "configured"],
        )

    def test_explicit_stop_marks_unstarted_items_skipped(self):
        process = _FailsFirstAdd()
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as home:
            results = setup_command.run_queue(
                self.queue(),
                scope_root=root,
                target_root=home,
                request=Request(
                    command="setup", setup_action="run", yes=True, stop_on_failure=True
                ),
                runtime=SetupRuntime(process=process, platform="darwin", environ={}),
                write=lambda _line: None,
            )

        self.assertEqual(
            [record.status for record in results],
            ["apply_failed_rolled_back", "skipped"],
        )

    def test_interactive_failure_can_stop_remaining_items_with_default_continue_prompt(self):
        process = _FailsFirstAdd()
        answers = iter(("y", "n"))
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as home:
            results = setup_command.run_queue(
                self.queue(),
                scope_root=root,
                target_root=home,
                request=Request(command="setup", setup_action="run"),
                runtime=SetupRuntime(process=process, platform="darwin", environ={}),
                read=lambda _prompt: next(answers),
                write=lambda _line: None,
            )

        self.assertEqual(
            [record.status for record in results],
            ["apply_failed_rolled_back", "skipped"],
        )

    def test_retry_preserves_sparse_artifact_profile_pairs(self):
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as project:
            for name in ("alpha", "beta"):
                package = pathlib.Path(source, "mcp", name)
                (package / "setup").mkdir(parents=True)
                (package / "mcp.json").write_text(
                    json.dumps(
                        {
                            "name": name,
                            "description": f"{name} MCP.",
                            "server": {"command": name},
                        }
                    ),
                    encoding="utf-8",
                )
                installer = json.loads(recipe(required_tools=[]))
                installer["artifact"] = f"mcp/{name}"
                (package / "setup" / "installer.json").write_text(
                    json.dumps(installer), encoding="utf-8"
                )
            with redirect_stdout(io.StringIO()):
                self.assertEqual(
                    install.run(
                        Request(
                            command="install",
                            names=("alpha",),
                            profiles=("tabnine",),
                            source_dir=source,
                            project=project,
                            yes=True,
                        )
                    ),
                    0,
                )
                self.assertEqual(
                    install.run(
                        Request(
                            command="install",
                            names=("beta",),
                            profiles=("claude",),
                            source_dir=source,
                            project=project,
                            yes=True,
                        )
                    ),
                    0,
                )
            retry_records = (
                SetupStateRecord("mcp", "alpha", "tabnine", "project", "cancelled", "retry"),
                SetupStateRecord("mcp", "beta", "claude", "project", "cancelled", "retry"),
            )
            request = Request(
                command="setup",
                setup_action="retry",
                source_dir=source,
                project=project,
            )

            queue = setup_command._queue_from_installed(request, retry_records)

            self.assertEqual(
                [(item.artifact_name, item.profile) for item in queue],
                [("alpha", "tabnine"), ("beta", "claude")],
            )

    def test_state_write_failure_compensates_new_effects_and_persists_recovery(self):
        process = _FailsFirstAdd()
        process.failed = True
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as home:
            with patch.object(
                setup_command,
                "_save_state",
                side_effect=[Err("synthetic state failure"), None],
            ):
                result = setup_command.run_queue(
                    self.queue()[:1],
                    scope_root=root,
                    target_root=home,
                    request=Request(command="setup", setup_action="run", yes=True),
                    runtime=SetupRuntime(process=process, platform="darwin", environ={}),
                    write=lambda _line: None,
                )

            self.assertIsInstance(result, Err)
            self.assertIn("rollback completed", result.reason)
            self.assertFalse(process.exists)
            self.assertFalse(pathlib.Path(home, ".zshrc").exists())


if __name__ == "__main__":
    unittest.main()
