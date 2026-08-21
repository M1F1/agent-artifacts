"""Issue #20: transactional setup runtime with fake process/Keychain adapters."""

from __future__ import annotations

import os
import pathlib
import tempfile
import unittest
from types import SimpleNamespace

from agent_artifacts import setup_runtime
from agent_artifacts.model import SetupQueueItem
from agent_artifacts.setup import (
    advisory_messages,
    home_relative,
    parse_installer,
    plan_setup,
    recovery_messages,
    render_setup_outcome,
    render_setup_review,
    run_reload_reminders,
    shell_reload_reminder,
)
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
        self.assertIn("only its first 128 bytes", keychain["advisory"])
        self.assertNotIn("existing_secret_kept", keychain)
        # One command, not a sequence: a remedy split across lines is one that gets half-applied.
        commands = tuple(keychain["remediation_commands"])
        self.assertEqual(len(commands), 1)
        self.assertIn("add-generic-password", commands[0])
        self.assertIn('-w "$(pbpaste)"', commands[0])
        # Bare `-w` is the prompt that truncates; the remedy must never send them back into it.
        self.assertNotIn('-w"', commands[0].replace('-w "$(pbpaste)"', ""))
        self.assertNotRegex(commands[0].replace('-w "$(pbpaste)"', ""), r"-w\s*$")
        # The warning has to reach the person before they paste, not only after.
        self.assertTrue(any("at most 128 bytes" in one for one in prompts))

    def test_an_existing_secret_is_reported_rather_than_passed_over_in_silence(self):
        """The common case, and the one that used to be silent.

        Finding an item already there is the normal outcome of every run after the first. The
        run cannot know whether the credential was rotated since; the operator can, and could
        not act on what they were never told (`AD-35`).
        """

        fake = FakeProcess()
        fake.exists = True
        prompts: list[str] = []
        with tempfile.TemporaryDirectory() as home:
            runtime = SetupRuntime(
                process=fake,
                platform="darwin",
                environ={},
                write_prompt=prompts.append,
                secret_length=lambda _service, _account: 40,
            )

            result = apply_setup_plan(_plan(home), runtime, consent=lambda _effect: True)

        self.assertEqual(result.status, "configured")
        keychain = next(r for r in result.receipt if r["module"] == "macos-keychain.store@1")
        self.assertIs(keychain["existing_secret_kept"], True)
        self.assertIs(keychain["created"], False)
        self.assertIs(keychain["replaced"], False)
        self.assertEqual(keychain["stored_length"], 40)
        self.assertNotIn("truncation_suspected", keychain)
        self.assertIn("never asked for a new one", keychain["advisory"])
        self.assertEqual(len(tuple(keychain["remediation_commands"])), 1)
        # Nothing was asked for, so the pre-prompt warning must not be printed.
        self.assertFalse(any("at most 128 bytes" in one for one in prompts))
        # Nothing was written either: an advisory is not a change.
        self.assertFalse(
            any("add-generic-password" in " ".join(argv) for argv, _e, _c in fake.calls)
        )

    def test_an_existing_secret_at_the_ceiling_reports_both_findings_together(self):
        fake = FakeProcess()
        fake.exists = True
        with tempfile.TemporaryDirectory() as home:
            runtime = SetupRuntime(
                process=fake,
                platform="darwin",
                environ={},
                secret_length=lambda _service, _account: 128,
            )

            result = apply_setup_plan(_plan(home), runtime, consent=lambda _effect: True)

        keychain = next(r for r in result.receipt if r["module"] == "macos-keychain.store@1")
        self.assertIs(keychain["existing_secret_kept"], True)
        self.assertIs(keychain["truncation_suspected"], True)
        # One advisory carrying both, because one command fixes both.
        self.assertIn("never asked for a new one", keychain["advisory"])
        self.assertIn("only its first 128 bytes", keychain["advisory"])
        self.assertEqual(len(tuple(keychain["remediation_commands"])), 1)

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
        self.assertNotIn("advisory", keychain)

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


class StoredSecretLengthTest(unittest.TestCase):
    """`security -w` prints hex for anything but printable ASCII, and says so only under `-g`."""

    def _measure(self, printed, hex_form):
        """Answer the two child pipelines without running them, recording what they were asked."""

        asked: list[tuple[str, ...]] = []

        def fake_count(producer, counter, **_options):
            asked.append(tuple(producer))
            return printed if "-w" in producer else hex_form

        original = setup_runtime._piped_count
        setup_runtime._piped_count = fake_count
        try:
            return setup_runtime._stored_secret_length("svc", "acct"), asked
        finally:
            setup_runtime._piped_count = original

    def test_a_printable_value_is_as_long_as_it_printed(self):
        # `wc -c` counts the trailing newline `-w` adds, which is not part of what is stored.
        measured, asked = self._measure(printed=94, hex_form=0)

        self.assertEqual(measured, 93)
        self.assertTrue(any("-g" in producer for producer in asked))

    def test_a_hex_dump_is_half_as_long_as_it_printed(self):
        # 128 stored bytes print as 256 hex characters; reading them as 256 would lose the warning.
        self.assertEqual(self._measure(printed=257, hex_form=1)[0], setup_runtime._PROMPT_CEILING)

    def test_a_value_of_only_hex_digits_is_not_a_hex_dump(self):
        # `-g` quotes it, so it is 128 printable characters and warns, rather than halving to 64.
        self.assertEqual(self._measure(printed=129, hex_form=0)[0], setup_runtime._PROMPT_CEILING)

    def test_an_odd_hex_count_is_refused_rather_than_guessed(self):
        self.assertIsNone(self._measure(printed=100, hex_form=1)[0])

    def test_either_count_failing_leaves_the_length_unknown(self):
        self.assertIsNone(self._measure(printed=None, hex_form=1)[0])
        self.assertIsNone(self._measure(printed=129, hex_form=None)[0])


class RemediationCommandTest(unittest.TestCase):
    """The remedy is one line, and it ends where the operator's problem actually ends."""

    def test_without_a_shell_file_it_only_stores(self):
        (command,) = setup_runtime._manual_keychain_commands("svc", "acct")

        self.assertTrue(command.startswith("/usr/bin/security add-generic-password -U "))
        self.assertNotIn("source", command)

    def test_with_a_shell_file_it_stores_and_reloads_in_one_line(self):
        (command,) = setup_runtime._manual_keychain_commands("svc", "acct", "/opt/x/.zshrc")

        self.assertEqual(command.count("&&"), 1)
        self.assertTrue(command.endswith("&& source /opt/x/.zshrc"))
        self.assertNotIn("\n", command)

    def test_a_shell_file_in_the_home_directory_prints_as_a_tilde(self):
        """`~/.zshrc` is the path the operator recognises as theirs.

        The absolute form is correct and unreadable: it names one machine's home directory in a
        command that is copied, pasted and shared (`AD-35`).
        """

        home = os.path.expanduser("~")
        (command,) = setup_runtime._manual_keychain_commands(
            "svc", "acct", os.path.join(home, ".zshrc")
        )

        self.assertTrue(command.endswith("&& source ~/.zshrc"))
        self.assertNotIn(home, command)

    def test_a_shell_file_outside_the_home_directory_stays_absolute(self):
        self.assertEqual(home_relative("/etc/zshrc", "/Users/someone"), "/etc/zshrc")

    def test_a_tilde_path_needing_quotes_keeps_the_tilde_expandable(self):
        # A quoted `~` is a literal one: the shell would look for a directory named `~`.
        rendered = home_relative("/Users/someone/my shell/.zshrc", "/Users/someone")

        self.assertEqual(rendered, "~/'my shell/.zshrc'")

    def test_values_needing_quotes_survive_as_values(self):
        (command,) = setup_runtime._manual_keychain_commands("a b", "x;rm -rf /", "/tmp/f g")

        self.assertIn("-a 'x;rm -rf /'", command)
        self.assertIn("-s 'a b'", command)
        self.assertIn("source '/tmp/f g'", command)


if __name__ == "__main__":
    unittest.main()


class WizardSurfaceTest(unittest.TestCase):
    """What the receipt records has to reach the surface the operator actually runs.

    `AD-34` and `AD-35` were both read by one command path. The wizard is how setup is normally
    run, and it printed none of it: the measurement happened, the receipt carried it, and the
    screen said `configured` (`AD-36`).
    """

    def _record(self, *, replaced: bool, length: int):
        runtime = SimpleNamespace(secret_length=lambda _service, _account: length)
        keychain = setup_runtime._advise(
            setup_runtime._keychain_receipt(
                "macos-keychain.store@1",
                "aart/mcp/atlassian/api-token",
                "atlassian",
                created=not replaced,
                replaced=replaced,
            ),
            "aart/mcp/atlassian/api-token",
            "atlassian",
            runtime,
            kept_existing=False,
        )
        home = os.path.expanduser("~")
        shell = {"module": "shell.env-from-keychain@1", "path": os.path.join(home, ".zshrc")}
        return SimpleNamespace(receipt=[keychain, shell])

    def _rendered(self, record) -> str:
        return "\n".join(
            render_setup_outcome(
                artifact="mcp/atlassian",
                profile="claude",
                scope="user",
                status="configured",
                detail="Setup configured",
                recovery=recovery_messages(record),
                advisories=advisory_messages(record),
            )
        )

    def test_the_wizard_prints_the_truncation_warning_it_used_to_drop(self):
        rendered = self._rendered(self._record(replaced=True, length=128))

        self.assertIn("Warning", rendered)
        self.assertIn("exactly 128 bytes", rendered)

    def test_a_replaced_value_says_the_account_already_had_one(self):
        rendered = self._rendered(self._record(replaced=True, length=40))

        self.assertIn("already had a value in the Keychain", rendered)
        self.assertIn("this run replaced it", rendered)

    def test_every_command_survives_on_one_line(self):
        """A command folded across three lines is repaired by hand before it can be run."""

        rendered = self._rendered(self._record(replaced=True, length=128))
        commands = [line for line in rendered.split("\n") if "add-generic-password" in line]

        self.assertEqual(len(commands), 2)
        for command in commands:
            self.assertTrue(command.startswith("    /usr/bin/security "), command)
            self.assertIn('-w "$(pbpaste)"', command)
        # The defect was a fold, so the assertion that matters is that no line is a fragment of
        # one: a continuation arrives without the tool that starts the command.
        for line in rendered.split("\n"):
            stripped = line.strip()
            self.assertFalse(
                stripped.startswith(("add-generic-password", "-w ", '"$(pbpaste)"', "-s aart")),
                line,
            )

    def test_the_reload_is_a_tilde_on_every_surface(self):
        rendered = self._rendered(self._record(replaced=True, length=128))

        self.assertIn("&& source ~/.zshrc", rendered)
        self.assertNotIn(os.path.expanduser("~") + "/.zshrc", rendered)

    def test_a_healthy_run_prints_no_warning_at_all(self):
        rendered = self._rendered(self._record(replaced=False, length=40))

        self.assertNotIn("Warning", rendered)
        self.assertNotIn("to replace what is stored", rendered)


class ShellReloadReminderTest(unittest.TestCase):
    """A run that writes variables into a shell file says so, every time.

    No effect can source that file — a child process cannot alter its parent's environment — so
    the most a run can do is stop the operator having to remember (`AD-37`).
    """

    def _record(self, *, with_shell: bool):
        receipt = [{"module": "macos-keychain.store@1", "created": True, "replaced": False}]
        if with_shell:
            receipt.append(
                {
                    "module": "shell.env-from-keychain@1",
                    "path": os.path.join(os.path.expanduser("~"), ".zshrc"),
                }
            )
        return SimpleNamespace(receipt=receipt)

    def test_a_run_that_wrote_a_shell_file_names_it_and_the_command(self):
        (reminder,) = shell_reload_reminder(self._record(with_shell=True))

        self.assertEqual(reminder["file"], "~/.zshrc")
        self.assertEqual(tuple(reminder["commands"]), ("source ~/.zshrc",))
        self.assertIn("already open does not have them yet", str(reminder["detail"]))
        self.assertIn("new terminal window", str(reminder["alternative"]))

    def test_a_run_that_wrote_no_shell_file_says_nothing(self):
        self.assertEqual(shell_reload_reminder(self._record(with_shell=False)), ())

    def test_the_reminder_does_not_wait_for_a_warning(self):
        """The whole point: it fires on a healthy run, where no advisory exists."""

        record = self._record(with_shell=True)
        rendered = "\n".join(
            render_setup_outcome(
                artifact="mcp/atlassian",
                profile="claude",
                scope="user",
                status="configured",
                detail="Setup configured",
                advisories=advisory_messages(record),
                reminders=shell_reload_reminder(record),
            )
        )

        self.assertNotIn("Warning", rendered)
        self.assertIn("Next step", rendered)
        self.assertIn("    source ~/.zshrc", rendered.split("\n"))

    def test_the_file_comes_from_the_receipt_not_from_a_guess(self):
        record = SimpleNamespace(
            receipt=[{"module": "shell.env-from-input@1", "path": "/etc/profile.d/aart.sh"}]
        )

        (reminder,) = shell_reload_reminder(record)

        self.assertEqual(reminder["file"], "/etc/profile.d/aart.sh")


class DockerTagNoteTest(unittest.TestCase):
    """The note used to claim the tag was untouched and to invite removing it."""

    def test_the_note_states_what_the_build_did_and_offers_no_destructive_command(self):
        note = (
            "Docker image tag aart/mcp/atlassian:1.0.0 pointed at another image before this run "
            "and now points at the image this run built. The earlier image was not recorded and "
            "no longer exists, so nothing can restore that binding. There is nothing to do "
            "unless you are undoing this setup, and do not remove this tag: the server runs "
            "from it."
        )
        source = pathlib.Path("agent_artifacts/setup_runtime.py").read_text(encoding="utf-8")

        self.assertNotIn("is left alone; remove it manually", source)
        self.assertIn("do not remove this tag", source)
        self.assertIn("now points at", note)


class SeveralShellFilesTest(unittest.TestCase):
    """A run that writes two shell files reminds about both, once each."""

    def test_each_distinct_file_gets_its_own_reminder(self):
        record = SimpleNamespace(
            receipt=[
                {"module": "shell.env-from-keychain@1", "path": "/tmp/one/.zshrc"},
                {"module": "shell.env-from-input@1", "path": "/tmp/two/.bashrc"},
                {"module": "shell.env-from-keychain@1", "path": "/tmp/one/.zshrc"},
            ]
        )

        reminders = shell_reload_reminder(record)

        self.assertEqual(
            [str(one["file"]) for one in reminders], ["/tmp/one/.zshrc", "/tmp/two/.bashrc"]
        )


class RunReloadRemindersTest(unittest.TestCase):
    """`AD-39`. The reminder is a fact about the machine, so the run prints it once.

    Reloading a shell file is not a property of an artifact. Three servers appending exports to
    `~/.zshrc` need `source ~/.zshrc` run once, and printing the same three-line block after each
    of them is how the instruction stopped being read at all. This was introduced in 2.8.3 by the
    per-item call and found by rendering a three-server selection rather than by reading code.
    """

    def _record(self, path):
        return SimpleNamespace(receipt=[{"module": "shell.env-from-keychain@1", "path": path}])

    def test_three_artifacts_writing_one_file_produce_one_reminder(self):
        records = [self._record("/tmp/one/.zshrc") for _ in range(3)]

        reminders = run_reload_reminders(records)

        self.assertEqual([str(one["file"]) for one in reminders], ["/tmp/one/.zshrc"])

    def test_two_files_across_a_run_keep_one_reminder_each_in_write_order(self):
        records = [
            self._record("/tmp/one/.zshrc"),
            self._record("/tmp/two/.bashrc"),
            self._record("/tmp/one/.zshrc"),
        ]

        reminders = run_reload_reminders(records)

        self.assertEqual(
            [str(one["file"]) for one in reminders], ["/tmp/one/.zshrc", "/tmp/two/.bashrc"]
        )

    def test_an_item_that_never_ran_carries_no_record_and_is_skipped(self):
        """A queue item that failed to plan has `record=None`, and the run still summarizes."""

        reminders = run_reload_reminders([None, self._record("/tmp/one/.zshrc"), None])

        self.assertEqual([str(one["file"]) for one in reminders], ["/tmp/one/.zshrc"])

    def test_a_run_that_wrote_no_shell_file_says_nothing(self):
        self.assertEqual(run_reload_reminders([None, SimpleNamespace(receipt=[])]), ())
