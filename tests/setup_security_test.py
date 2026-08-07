"""Issue #20: rollback ownership, prerequisite, Docker, and secret-channel gates."""

from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from agent_artifacts.model import SetupQueueItem
from agent_artifacts.setup import parse_installer, plan_setup, recovery_messages
from agent_artifacts.setup_runtime import (
    ProcessResult,
    SetupRuntime,
    apply_setup_plan,
    rollback_record,
)
from tests.setup_catalog_test import recipe


def plan_for(raw: bytes, home: str):
    parsed = parse_installer(
        raw,
        artifact_key="mcp/atlassian",
        descriptor_path="mcp/atlassian/setup/installer.json",
    ).value
    item = SetupQueueItem("mcp", "atlassian", "tabnine", "project", "pin:abc", "/source", parsed)
    return plan_setup(item, target_root=home, platform="darwin")


class RecordingProcess:
    def __init__(self):
        self.calls: list[tuple[str, ...]] = []
        self.keychain = False
        self.image = False

    def __call__(self, argv, *, env, cwd, timeout, capture):
        args = tuple(argv)
        self.calls.append(args)
        if "find-generic-password" in args:
            return ProcessResult(0 if self.keychain else 44)
        if "add-generic-password" in args:
            self.keychain = True
            return ProcessResult(0)
        if "delete-generic-password" in args:
            self.keychain = False
            return ProcessResult(0)
        if args[:3] == ("docker", "image", "inspect"):
            return ProcessResult(0 if self.image else 1)
        if args[:2] == ("docker", "pull"):
            self.image = True
            return ProcessResult(0)
        if args and args[0] == "verify-tool":
            return ProcessResult(1, "", "token=synthetic-canary")
        return ProcessResult(0)


class SetupSecurityTests(unittest.TestCase):
    def test_verification_failure_rolls_back_current_item_and_redacts_error(self):
        raw = recipe(
            required_tools=[],
            capabilities=["keychain", "filesystem", "process"],
            steps=json.loads(recipe())["steps"]
            + [
                {
                    "id": "verify",
                    "use": "command.verify@1",
                    "with": {"argv": ["verify-tool"]},
                }
            ],
        )
        process = RecordingProcess()
        with tempfile.TemporaryDirectory() as home:
            result = apply_setup_plan(
                plan_for(raw, home),
                SetupRuntime(process=process, platform="darwin", environ={}),
                consent=lambda _effect: True,
            )

            self.assertEqual(result.status, "verification_failed")
            self.assertFalse(process.keychain)
            self.assertFalse(pathlib.Path(home, ".zshrc").exists())
            self.assertNotIn("synthetic-canary", repr(result))
            self.assertIn("[redacted]", result.detail)

    def test_missing_prerequisite_is_terminal_and_non_mutating(self):
        process = RecordingProcess()
        with tempfile.TemporaryDirectory() as home:
            result = apply_setup_plan(
                plan_for(recipe(), home),
                SetupRuntime(
                    process=process,
                    platform="darwin",
                    environ={},
                    tool_exists=lambda _tool: False,
                ),
                consent=lambda _effect: True,
            )

            self.assertEqual(result.status, "prerequisite_missing")
            self.assertEqual(process.calls, [])

    def test_recipe_hash_drift_is_rejected_before_effect_adapters(self):
        process = RecordingProcess()
        raw = recipe()
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as home:
            descriptor = pathlib.Path(source, "mcp", "atlassian", "setup", "installer.json")
            descriptor.parent.mkdir(parents=True)
            descriptor.write_bytes(raw)
            parsed = parse_installer(
                raw,
                artifact_key="mcp/atlassian",
                descriptor_path="mcp/atlassian/setup/installer.json",
            ).value
            item = SetupQueueItem(
                "mcp", "atlassian", "tabnine", "project", "local:test", source, parsed
            )
            plan = plan_setup(item, target_root=home, platform="darwin")
            descriptor.write_bytes(recipe(purpose="Changed after review."))

            result = apply_setup_plan(
                plan,
                SetupRuntime(
                    process=process,
                    platform="darwin",
                    environ={},
                    enforce_source_hash=True,
                ),
                consent=lambda _effect: True,
            )

            self.assertEqual(result.status, "apply_failed_rolled_back")
            self.assertIn("hash changed", result.detail)
            self.assertEqual(process.calls, [])

    def test_managed_block_rollback_preserves_later_unrelated_edit(self):
        raw = recipe(
            required_tools=[],
            capabilities=["filesystem"],
            inputs=[],
            steps=[
                {
                    "id": "file",
                    "use": "file.managed-block@1",
                    "with": {"file": "~/config", "content": "managed=true"},
                }
            ],
        )
        with tempfile.TemporaryDirectory() as home:
            target = pathlib.Path(home, "config")
            target.write_text("foreign=before\n", encoding="utf-8")
            runtime = SetupRuntime(process=RecordingProcess(), platform="darwin", environ={})
            configured = apply_setup_plan(
                plan_for(raw, home), runtime, consent=lambda _effect: True
            )
            target.write_text(
                target.read_text(encoding="utf-8") + "foreign=after\n", encoding="utf-8"
            )

            rolled = rollback_record(configured, runtime)

            text = target.read_text(encoding="utf-8")
            self.assertEqual(rolled.status, "skipped")
            self.assertIn("foreign=before", text)
            self.assertIn("foreign=after", text)
            self.assertNotIn("managed=true", text)

    def test_json_rollback_preserves_foreign_keys(self):
        raw = recipe(
            required_tools=[],
            capabilities=["filesystem"],
            inputs=[],
            steps=[
                {
                    "id": "json",
                    "use": "json.managed-merge@1",
                    "with": {
                        "file": "~/settings.json",
                        "path": ["aart", "enabled"],
                        "value": True,
                    },
                }
            ],
        )
        with tempfile.TemporaryDirectory() as home:
            target = pathlib.Path(home, "settings.json")
            target.write_text('{"foreign": 1}\n', encoding="utf-8")
            runtime = SetupRuntime(process=RecordingProcess(), platform="darwin", environ={})
            configured = apply_setup_plan(
                plan_for(raw, home), runtime, consent=lambda _effect: True
            )

            rolled = rollback_record(configured, runtime)

            data = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(rolled.status, "skipped")
            self.assertEqual(data["foreign"], 1)
            self.assertNotIn("enabled", data.get("aart", {}))

    def test_json_collision_never_copies_an_existing_value_into_receipt(self):
        raw = recipe(
            required_tools=[],
            capabilities=["filesystem"],
            inputs=[],
            steps=[
                {
                    "id": "json",
                    "use": "json.managed-merge@1",
                    "with": {
                        "file": "~/settings.json",
                        "path": ["aart", "enabled"],
                        "value": True,
                    },
                }
            ],
        )
        canary = "synthetic-canary-value"
        with tempfile.TemporaryDirectory() as home:
            target = pathlib.Path(home, "settings.json")
            target.write_text(json.dumps({"aart": {"enabled": canary}}), encoding="utf-8")

            result = apply_setup_plan(
                plan_for(raw, home),
                SetupRuntime(process=RecordingProcess(), platform="darwin", environ={}),
                consent=lambda _effect: True,
            )

            self.assertEqual(result.status, "apply_failed_rolled_back")
            self.assertNotIn(canary, repr(result))
            self.assertEqual(
                json.loads(target.read_text(encoding="utf-8"))["aart"]["enabled"], canary
            )

    def test_docker_inspects_before_one_digest_pinned_pull(self):
        image = "registry.example/tool@sha256:" + "a" * 64
        raw = recipe(
            required_tools=["docker"],
            capabilities=["docker", "network", "process"],
            inputs=[],
            steps=[
                {
                    "id": "image",
                    "use": "docker.pull@1",
                    "with": {"image": image, "official_url": "https://example.test/tool"},
                }
            ],
        )
        process = RecordingProcess()
        with tempfile.TemporaryDirectory() as home:
            runtime = SetupRuntime(process=process, platform="darwin", environ={})
            first = apply_setup_plan(plan_for(raw, home), runtime, consent=lambda _effect: True)
            second = apply_setup_plan(plan_for(raw, home), runtime, consent=lambda _effect: True)

            self.assertEqual(first.status, "configured")
            self.assertEqual(second.status, "already_configured")
            self.assertEqual(process.calls[0][:3], ("docker", "image", "inspect"))
            self.assertEqual(sum(call[:2] == ("docker", "pull") for call in process.calls), 1)

    def test_incomplete_rollback_keeps_receipt_and_command_for_recovery(self):
        image = "registry.example/tool@sha256:" + "a" * 64
        raw = recipe(
            required_tools=["docker"],
            capabilities=["docker", "network", "process"],
            inputs=[],
            steps=[
                {
                    "id": "image",
                    "use": "docker.pull@1",
                    "with": {"image": image, "official_url": "https://example.test/tool"},
                }
            ],
        )
        process = RecordingProcess()
        with tempfile.TemporaryDirectory() as home:
            runtime = SetupRuntime(process=process, platform="darwin", environ={})
            configured = apply_setup_plan(
                plan_for(raw, home), runtime, consent=lambda _effect: True
            )

            rolled = rollback_record(configured, runtime)

            self.assertEqual(rolled.status, "rollback_incomplete")
            self.assertEqual(rolled.receipt, configured.receipt)
            self.assertEqual(rolled.rollback_command, configured.rollback_command)
            self.assertIn("remove it manually", recovery_messages(rolled)[0])


if __name__ == "__main__":
    unittest.main()
