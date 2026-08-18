"""Issue #20: transactional setup runtime with fake process/Keychain adapters."""

from __future__ import annotations

import os
import pathlib
import tempfile
import unittest

from agent_artifacts.model import SetupQueueItem
from agent_artifacts.setup import parse_installer, plan_setup, render_setup_review
from agent_artifacts.setup_runtime import ProcessResult, SetupRuntime, apply_setup_plan
from tests.setup_fixtures import recipe


class FakeProcess:
    def __init__(self, *, fail_add: bool = False):
        self.calls: list[tuple[tuple[str, ...], dict[str, str], str | None]] = []
        self.capture_modes: list[tuple[tuple[str, ...], bool]] = []
        self.exists = False
        self.fail_add = fail_add
        self.events: list[tuple[str, object]] = []

    def __call__(self, argv, *, env, cwd, timeout, capture):
        self.events.append(("process", tuple(argv)))
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


def _text_plan(home: str):
    parsed = parse_installer(
        recipe(
            required_tools=[],
            capabilities=["filesystem"],
            inputs=[
                {
                    "id": "account_email",
                    "type": "text",
                    "prompt": "Your Atlassian account e-mail",
                }
            ],
            steps=[
                {
                    "id": "account",
                    "use": "shell.env-from-input@1",
                    "with": {
                        "file": "~/.zshrc",
                        "variables": {"ATLASSIAN_USERNAME": "account_email"},
                    },
                }
            ],
        ),
        artifact_key="mcp/atlassian",
        descriptor_path="mcp/atlassian/setup/installer.json",
    ).value
    item = SetupQueueItem("mcp", "atlassian", "tabnine", "user", "pin:abc", "/source", parsed)
    return plan_setup(item, target_root=home, platform="darwin")


class SetupRuntimeTests(unittest.TestCase):
    def test_text_input_is_reviewed_prompted_with_echo_and_written_as_an_owned_shell_value(self):
        fake = FakeProcess()
        prompts: list[str] = []
        with tempfile.TemporaryDirectory() as home:
            plan = _text_plan(home)
            review = "\n".join(render_setup_review(plan))
            runtime = SetupRuntime(
                process=fake,
                platform="darwin",
                environ={},
                read_text_input=lambda prompt: prompts.append(prompt) or "dev'one@example.test",
            )

            first = apply_setup_plan(plan, runtime, consent=lambda _effect: True)
            second = apply_setup_plan(plan, runtime, consent=lambda _effect: True)

            content = pathlib.Path(home, ".zshrc").read_text(encoding="utf-8")

        self.assertIn("prompts with echo", review)
        self.assertIn("Your Atlassian account e-mail", review)
        self.assertEqual(prompts, ["Your Atlassian account e-mail"] * 2)
        self.assertEqual(first.status, "configured")
        self.assertEqual(second.status, "already_configured")
        self.assertIn("export ATLASSIAN_USERNAME='dev'\"'\"'one@example.test'", content)
        self.assertEqual(fake.calls, [])

    def test_keychain_prompt_is_named_immediately_before_security_takes_the_terminal(self):
        fake = FakeProcess()
        with tempfile.TemporaryDirectory() as home:
            runtime = SetupRuntime(
                process=fake,
                platform="darwin",
                environ={},
                write_prompt=lambda message: fake.events.append(("prompt", message)),
            )

            result = apply_setup_plan(_plan(home), runtime, consent=lambda _effect: True)

        self.assertEqual(result.status, "configured")
        add_index = next(
            index
            for index, event in enumerate(fake.events)
            if event[0] == "process" and "add-generic-password" in event[1]
        )
        prompt = fake.events[add_index - 1]
        self.assertEqual(prompt[0], "prompt")
        self.assertIn("Paste the Atlassian API token", prompt[1])
        self.assertIn("service='aart/mcp/atlassian'", prompt[1])
        self.assertIn("account='default'", prompt[1])

    def test_managed_file_preflight_refuses_a_symlink_before_the_first_effect(self):
        fake = FakeProcess()
        with tempfile.TemporaryDirectory() as home:
            real = pathlib.Path(home, "dotfiles-zshrc")
            real.write_text("owned by dotfiles\n", encoding="utf-8")
            pathlib.Path(home, ".zshrc").symlink_to(real)
            prompts: list[str] = []

            result = apply_setup_plan(
                _plan(home),
                SetupRuntime(
                    process=fake,
                    platform="darwin",
                    environ={},
                    write_prompt=prompts.append,
                ),
                consent=lambda _effect: True,
            )

            self.assertEqual(result.status, "prerequisite_missing")
            self.assertIn("refusing to edit symlink", result.detail)
            self.assertEqual(fake.calls, [])
            self.assertEqual(prompts, [])
            self.assertEqual(real.read_text(encoding="utf-8"), "owned by dotfiles\n")

    def test_a_secret_stored_at_the_prompt_ceiling_is_reported_with_a_way_to_fix_it(self):
        fake = FakeProcess()
        prompts: list[str] = []
        with tempfile.TemporaryDirectory() as home:
            runtime = SetupRuntime(
                process=fake,
                platform="darwin",
                environ={},
                write_prompt=prompts.append,
                # 128 is `_PASSWORD_LEN`: what `getpass(3)` keeps and `security` inherits.
                secret_length=lambda _service, _account: 128,
            )

            result = apply_setup_plan(_plan(home), runtime, consent=lambda _effect: True)

        self.assertEqual(result.status, "configured")
        keychain = next(r for r in result.receipt if r["module"] == "macos-keychain.store@1")
        self.assertEqual(keychain["stored_length"], 128)
        self.assertIs(keychain["truncation_suspected"], True)
        self.assertIn("only its first 128 bytes", keychain["truncation_detail"])
        commands = tuple(keychain["remediation_commands"])
        self.assertTrue(any("add-generic-password" in one and "pbpaste" in one for one in commands))
        self.assertTrue(any("wc -c" in one for one in commands))
        # The warning has to reach the person before they paste, not only after.
        self.assertTrue(any("at most 128 bytes" in one for one in prompts))

    def test_a_secret_shorter_than_the_ceiling_raises_nothing(self):
        fake = FakeProcess()
        with tempfile.TemporaryDirectory() as home:
            runtime = SetupRuntime(
                process=fake,
                platform="darwin",
                environ={},
                secret_length=lambda _service, _account: 93,
            )

            result = apply_setup_plan(_plan(home), runtime, consent=lambda _effect: True)

        keychain = next(r for r in result.receipt if r["module"] == "macos-keychain.store@1")
        self.assertEqual(keychain["stored_length"], 93)
        self.assertNotIn("truncation_suspected", keychain)

    def test_an_unmeasurable_secret_leaves_the_receipt_silent_rather_than_guessing(self):
        fake = FakeProcess()
        with tempfile.TemporaryDirectory() as home:
            # The default probe returns None: no measurement is not the same claim as no problem.
            runtime = SetupRuntime(process=fake, platform="darwin", environ={})

            result = apply_setup_plan(_plan(home), runtime, consent=lambda _effect: True)

        keychain = next(r for r in result.receipt if r["module"] == "macos-keychain.store@1")
        self.assertNotIn("stored_length", keychain)
        self.assertNotIn("truncation_suspected", keychain)

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
