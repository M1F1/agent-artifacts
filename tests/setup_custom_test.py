"""Issue #20: hash-bound optional custom setup protocol."""

from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from agent_artifacts.model import SetupQueueItem
from agent_artifacts.setup import parse_installer, plan_setup
from agent_artifacts.setup_runtime import ProcessResult, SetupRuntime, apply_setup_plan
from tests.setup_fixtures import recipe


class FakeCustomProcess:
    def __init__(self):
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv, *, env, cwd, timeout, capture):
        args = tuple(argv)
        self.calls.append(args)
        if "find-generic-password" in args:
            return ProcessResult(0, "", "")
        if args[0].endswith("install.sh"):
            phase = args[1]
            result_path = pathlib.Path(args[args.index("--result") + 1])
            status = {"plan": "planned", "apply": "configured", "verify": "verified"}[phase]
            result_path.write_text(
                json.dumps({"status": status, "detail": f"{phase} ok", "reversible": True}),
                encoding="utf-8",
            )
        return ProcessResult(0, "", "")


class FailingVerifyAndRollbackProcess(FakeCustomProcess):
    def __call__(self, argv, *, env, cwd, timeout, capture):
        args = tuple(argv)
        if args[0].endswith("install.sh") and args[1] in ("verify", "rollback"):
            self.calls.append(args)
            return ProcessResult(1)
        return super().__call__(argv, env=env, cwd=cwd, timeout=timeout, capture=capture)


def custom_plan(source_root: str, target_root: str):
    script = b"#!/bin/sh\nexit 0\n"
    setup_dir = pathlib.Path(source_root, "mcp", "atlassian", "setup")
    setup_dir.mkdir(parents=True)
    script_path = setup_dir / "install.sh"
    script_path.write_bytes(script)
    script_path.chmod(0o700)
    parsed = parse_installer(
        recipe(
            required_tools=[],
            capabilities=["process", "custom-code"],
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
    item = SetupQueueItem("mcp", "atlassian", "tabnine", "project", "pin:abc", source_root, parsed)
    return plan_setup(item, target_root=target_root, platform="darwin"), script_path


class CustomProtocolTests(unittest.TestCase):
    def test_plan_apply_verify_use_fixed_argv_minimal_environment_and_private_run_dir(self):
        fake = FakeCustomProcess()
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as target:
            plan, script = custom_plan(source, target)
            runtime = SetupRuntime(
                process=fake,
                platform="darwin",
                environ={"PATH": "/bin", "SECRET_CANARY": "do-not-forward"},
            )

            result = apply_setup_plan(plan, runtime, consent=lambda _effect: True)

            self.assertEqual(result.status, "configured")
            custom_calls = [call for call in fake.calls if call[0].endswith("install.sh")]
            self.assertEqual([call[1] for call in custom_calls], ["plan", "apply", "verify"])
            self.assertIn("--plan-hash", custom_calls[1])
            run_dirs = list(pathlib.Path(target, ".agent-artifacts", "setup-runs").iterdir())
            self.assertEqual(len(run_dirs), 1)
            self.assertEqual(run_dirs[0].stat().st_mode & 0o777, 0o700)
            executed = pathlib.Path(custom_calls[0][0])
            self.assertNotEqual(executed, script)
            self.assertEqual(executed.parent, run_dirs[0])
            self.assertEqual(executed.read_bytes(), script.read_bytes())
            self.assertEqual(executed.stat().st_mode & 0o777, 0o700)
            self.assertTrue(all(pathlib.Path(call[0]) == executed for call in custom_calls))
            self.assertNotIn("do-not-forward", repr(fake.calls) + repr(result))

    def test_hash_drift_is_rejected_before_custom_execution(self):
        fake = FakeCustomProcess()
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as target:
            plan, script = custom_plan(source, target)
            script.write_text("#!/bin/sh\n# drift\n", encoding="utf-8")

            result = apply_setup_plan(
                plan,
                SetupRuntime(process=fake, platform="darwin", environ={}),
                consent=lambda _effect: True,
            )

            self.assertEqual(result.status, "apply_failed_rolled_back")
            self.assertIn("hash", result.detail)
            self.assertFalse(any(call[0].endswith("install.sh") for call in fake.calls))

    def test_failed_custom_compensation_is_never_reported_as_rolled_back(self):
        fake = FailingVerifyAndRollbackProcess()
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as target:
            plan, _script = custom_plan(source, target)

            result = apply_setup_plan(
                plan,
                SetupRuntime(process=fake, platform="darwin", environ={}),
                consent=lambda _effect: True,
            )

            self.assertEqual(result.status, "rollback_incomplete")
            self.assertIn("rollback", result.detail)
            self.assertIn("custom.install@1", [item["module"] for item in result.receipt])
            self.assertIn("setup rollback", result.rollback_command)


if __name__ == "__main__":
    unittest.main()
