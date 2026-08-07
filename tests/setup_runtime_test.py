"""Issue #20: transactional setup runtime with fake process/Keychain adapters."""

from __future__ import annotations

import os
import pathlib
import tempfile
import unittest

from agent_artifacts.model import SetupQueueItem
from agent_artifacts.setup import parse_installer, plan_setup
from agent_artifacts.setup_runtime import ProcessResult, SetupRuntime, apply_setup_plan
from tests.setup_catalog_test import recipe


class FakeProcess:
    def __init__(self, *, fail_add: bool = False):
        self.calls: list[tuple[tuple[str, ...], dict[str, str], str | None]] = []
        self.capture_modes: list[tuple[tuple[str, ...], bool]] = []
        self.exists = False
        self.fail_add = fail_add

    def __call__(self, argv, *, env, cwd, timeout, capture):
        self.calls.append((tuple(argv), dict(env), cwd))
        self.capture_modes.append((tuple(argv), capture))
        if "find-generic-password" in argv:
            return ProcessResult(0 if self.exists else 44, "", "")
        if "add-generic-password" in argv:
            if self.fail_add:
                return ProcessResult(1, "", "synthetic add failure")
            self.exists = True
            return ProcessResult(0, "", "")
        if "delete-generic-password" in argv:
            self.exists = False
            return ProcessResult(0, "", "")
        return ProcessResult(0, "", "")


def _plan(home: str):
    parsed = parse_installer(
        recipe(),
        artifact_key="mcp/atlassian",
        descriptor_path="mcp/atlassian/setup/installer.json",
    ).value
    item = SetupQueueItem("mcp", "atlassian", "tabnine", "user", "pin:abc", "/source", parsed)
    return plan_setup(item, target_root=home, platform="darwin")


class SetupRuntimeTests(unittest.TestCase):
    def test_keychain_prompt_argv_never_contains_secret_and_shell_stores_lookup_only(self):
        canary = "aart-secret-canary-123"
        fake = FakeProcess()
        with tempfile.TemporaryDirectory() as home:
            runtime = SetupRuntime(process=fake, platform="darwin", environ={"CANARY": canary})

            result = apply_setup_plan(_plan(home), runtime, consent=lambda _effect: True)

            self.assertEqual(result.status, "configured")
            flattened = repr(fake.calls) + repr(result)
            self.assertNotIn(canary, flattened)
            add_argv = next(
                argv for argv, _env, _cwd in fake.calls if "add-generic-password" in argv
            )
            self.assertEqual(add_argv[-1], "-w")
            self.assertNotIn(canary, add_argv)
            self.assertFalse(
                next(
                    capture
                    for argv, capture in fake.capture_modes
                    if "add-generic-password" in argv
                )
            )
            zshrc = pathlib.Path(home, ".zshrc").read_text(encoding="utf-8")
            self.assertIn("find-generic-password", zshrc)
            self.assertNotIn(canary, zshrc)

    def test_second_run_is_idempotent(self):
        fake = FakeProcess()
        with tempfile.TemporaryDirectory() as home:
            runtime = SetupRuntime(process=fake, platform="darwin", environ={})
            first = apply_setup_plan(_plan(home), runtime, consent=lambda _effect: True)
            second = apply_setup_plan(_plan(home), runtime, consent=lambda _effect: True)

            self.assertEqual(first.status, "configured")
            self.assertEqual(second.status, "already_configured")
            self.assertEqual(
                sum("add-generic-password" in argv for argv, _env, _cwd in fake.calls),
                1,
            )

    def test_cancel_before_first_effect_is_terminal_and_non_mutating(self):
        fake = FakeProcess()
        with tempfile.TemporaryDirectory() as home:
            result = apply_setup_plan(
                _plan(home),
                SetupRuntime(process=fake, platform="darwin", environ={}),
                consent=lambda _effect: False,
            )

            self.assertEqual(result.status, "cancelled")
            self.assertFalse(os.path.exists(os.path.join(home, ".zshrc")))
            self.assertEqual(fake.calls, [])

    def test_cancel_after_first_mutation_rolls_back_the_current_item(self):
        fake = FakeProcess()
        approvals = iter((True, False))
        with tempfile.TemporaryDirectory() as home:
            result = apply_setup_plan(
                _plan(home),
                SetupRuntime(process=fake, platform="darwin", environ={}),
                consent=lambda _effect: next(approvals),
            )

            self.assertEqual(result.status, "cancelled")
            self.assertFalse(fake.exists)
            self.assertFalse(os.path.exists(os.path.join(home, ".zshrc")))

    def test_non_darwin_never_calls_effect_adapters(self):
        fake = FakeProcess()
        with tempfile.TemporaryDirectory() as home:
            darwin_plan = _plan(home)
            linux_plan = plan_setup(darwin_plan.item, target_root=home, platform="linux")

            result = apply_setup_plan(
                linux_plan,
                SetupRuntime(process=fake, platform="linux", environ={}),
                consent=lambda _effect: True,
            )

            self.assertEqual(result.status, "unsupported")
            self.assertEqual(fake.calls, [])


if __name__ == "__main__":
    unittest.main()
