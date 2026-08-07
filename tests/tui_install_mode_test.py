"""Issue #18 TDD contracts for interactive Copy/Symlink selection."""

from __future__ import annotations

import curses
import io
import json
import os
import pathlib
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

from agent_artifacts import tui
from agent_artifacts.install_modes import supports_symlink
from agent_artifacts.model import Ok, Request
from agent_artifacts.outcomes import ActionSummary, CommandOutcome, OutcomeItem
from agent_artifacts.profiles.loader import load_profiles
from agent_artifacts.source import Source, open_source

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = str(REPO_ROOT / "tests" / "fixtures")


def _scripted_reader(answers):
    iterator = iter(answers)

    def read(_prompt=""):
        try:
            return next(iterator)
        except StopIteration:
            raise EOFError from None

    return read


def _collector():
    lines = []
    return (lambda text="": lines.append(text)), lines


def _catalog():
    return open_source(Request(command="list", source_dir=FIXTURES)).value.catalog().value


def _outcome(request: Request) -> CommandOutcome:
    return CommandOutcome(
        0,
        ActionSummary(
            action=request.command,
            selected=1,
            items=(
                OutcomeItem(
                    "skill/code-review@claude",
                    "installed",
                    artifact="code-review",
                    artifact_type="skill",
                    profile="claude",
                    mode=request.install_mode,
                ),
            ),
        ),
    )


class InstallModePolicyTests(unittest.TestCase):
    def setUp(self):
        self.catalog = _catalog()
        self.profiles = load_profiles()

    def test_mode_choices_are_copy_first_and_use_shared_terminology(self):
        self.assertEqual(
            [(choice.mode, choice.label) for choice in tui.INSTALL_MODE_CHOICES],
            [("copy", "Copy (recommended)"), ("symlink", "Symlink")],
        )
        self.assertIn("independent snapshot", tui.INSTALL_MODE_CHOICES[0].description)
        self.assertIn("local catalog", tui.INSTALL_MODE_CHOICES[1].description)

    def test_linkability_is_one_shared_domain_rule(self):
        self.assertTrue(supports_symlink("skill"))
        self.assertTrue(supports_symlink("hook"))
        self.assertFalse(supports_symlink("guideline"))
        self.assertFalse(supports_symlink("mcp"))
        self.assertFalse(supports_symlink("memory"))

    def test_symlink_choices_disable_copy_only_artifacts_with_a_reason(self):
        choices = tui.build_install_choices(
            self.catalog,
            ("claude",),
            self.profiles,
            install_mode="symlink",
        )
        by_name = {choice.name: choice for choice in choices if choice.kind == "artifact"}

        self.assertTrue(by_name["code-review"].enabled)
        self.assertTrue(by_name["block-secrets"].enabled)
        for name in ("python-style", "postgres"):
            with self.subTest(name=name):
                self.assertFalse(by_name[name].enabled)
                self.assertIn("copy-only", by_name[name].reason)
                self.assertIn("copy-only", by_name[name].label)

    def test_mixed_bundle_discloses_actual_target_counts_and_hidden_members(self):
        choices = tui.build_install_choices(
            self.catalog,
            ("claude",),
            self.profiles,
            install_mode="symlink",
        )
        backend = next(choice for choice in choices if choice.name == "backend")

        self.assertTrue(backend.enabled)
        self.assertEqual((backend.linked_count, backend.copied_count), (2, 2))
        self.assertIn("2 linked, 2 copied", backend.label)
        self.assertIn("1 hidden", backend.label)

    def test_mode_counts_deduplicate_overlapping_artifact_and_bundle(self):
        choices = tui.build_install_choices(
            self.catalog,
            ("claude",),
            self.profiles,
            install_mode="symlink",
        )
        code_review = next(choice for choice in choices if choice.name == "code-review")
        backend = next(choice for choice in choices if choice.name == "backend")

        counts = tui.install_selection_mode_counts(
            self.catalog,
            (code_review, backend),
            ("claude",),
            self.profiles,
            "symlink",
        )

        self.assertEqual((counts.linked, counts.copied), (2, 2))

    def test_multi_profile_counts_are_artifact_profile_targets(self):
        choices = tui.build_install_choices(
            self.catalog,
            ("claude", "opencode"),
            self.profiles,
            install_mode="symlink",
        )
        backend = next(choice for choice in choices if choice.name == "backend")

        self.assertEqual((backend.linked_count, backend.copied_count), (4, 4))

    def test_confirmation_contains_every_execution_relevant_mode_fact(self):
        choices = tui.build_install_choices(
            self.catalog,
            ("claude",),
            self.profiles,
            install_mode="symlink",
        )
        backend = next(choice for choice in choices if choice.name == "backend")

        confirmation = tui.build_install_confirmation(
            source_label=f"local:{FIXTURES}",
            source_root=FIXTURES,
            project="relative-project",
            profiles=("claude",),
            requested_mode="symlink",
            catalog=self.catalog,
            choices=(backend,),
            profiles_map=self.profiles,
        )
        lines = tui.render_install_confirmation(confirmation)
        rendered = "\n".join(lines)

        self.assertIn(f"Source: local:{FIXTURES} ({FIXTURES})", rendered)
        self.assertIn(f"Destination: Project — {os.path.abspath('relative-project')}", rendered)
        self.assertIn("Harnesses: claude", rendered)
        self.assertIn("Role: User", rendered)
        self.assertIn("Action: Install", rendered)
        self.assertIn("Requested mode: Symlink", rendered)
        self.assertIn("Projected modes: 2 linked, 2 copied", rendered)
        self.assertIn("Selected count: 1", rendered)
        self.assertIn("Selected: backend", rendered)
        self.assertIn("Expected mutation:", rendered)
        self.assertIn("mixed-mode fallback", rendered)


class TextInstallModeFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = self.temp.name

    def _run(self, answers, *, source_factory=open_source, repo=None):
        captured = []
        write, lines = _collector()

        def dispatch(request):
            captured.append(request)
            return _outcome(request)

        with mock.patch.object(tui, "_dispatch_result", side_effect=dispatch):
            code = tui._run_text(
                _scripted_reader(answers),
                write,
                source_factory=source_factory,
                source_dir=None if repo else FIXTURES,
                repo=repo,
                project=self.project,
            )
        return code, captured, lines

    def test_blank_mode_selects_copy_and_confirmation_dispatches_once(self):
        code, captured, lines = self._run(["1", "1", "1", "1", "", "1", "y"])

        self.assertEqual(code, 0)
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].install_mode, "copy")
        self.assertIn("Copy (recommended)", "\n".join(lines))
        self.assertIn("Requested mode: Copy", "\n".join(lines))

    def test_explicit_symlink_reaches_request_and_completion_mode(self):
        code, captured, lines = self._run(["1", "1", "install", "1", "2", "1", "yes"])

        self.assertEqual(code, 0)
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].install_mode, "symlink")
        self.assertIn("Requested mode: Symlink", "\n".join(lines))
        self.assertTrue(any("mode=symlink" in line for line in lines))

    def test_mode_back_returns_to_action_without_losing_profile(self):
        code, captured, _lines = self._run(
            ["1", "1", "install", "1", "back", "install", "1", "1", "1", "y"]
        )

        self.assertEqual(code, 0)
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].profiles, ("claude",))
        self.assertEqual(captured[0].install_mode, "copy")

    def test_declining_confirmation_does_not_dispatch(self):
        code, captured, lines = self._run(["1", "1", "install", "1", "2", "1", "n"])

        self.assertEqual(code, 0)
        self.assertEqual(captured, [])
        self.assertIn("no changes were made", "\n".join(lines).lower())

    def test_remote_symlink_fails_before_artifact_selection_or_dispatch(self):
        catalog = _catalog()
        remote = Source(root=FIXTURES, _label="main:" + "a" * 40)
        source_factory = mock.Mock(return_value=Ok(remote))

        code, captured, lines = self._run(
            ["1", "1", "install", "1", "2"],
            source_factory=source_factory,
            repo="owner/catalog",
        )

        self.assertEqual(code, 2)
        self.assertEqual(captured, [])
        self.assertEqual(source_factory.call_count, 1)
        rendered = "\n".join(lines)
        self.assertIn("durable local catalog", rendered)
        self.assertIn("--source DIR", rendered)
        self.assertIn("--link", rendered)
        self.assertNotIn("Select artifact", rendered)
        self.assertTrue(catalog.artifacts)

    def test_disabled_text_row_is_rejected_then_valid_row_can_be_selected(self):
        choices = tui.build_install_choices(
            _catalog(),
            ("claude",),
            load_profiles(),
            install_mode="symlink",
        )
        write, lines = _collector()

        selected = tui._prompt_indices(
            _scripted_reader(["2", "1"]),
            write,
            "Selection: ",
            choices,
        )

        self.assertEqual(selected, (0,))
        self.assertIn("copy-only", "\n".join(lines))


class CursesInstallModeTests(unittest.TestCase):
    class Screen:
        def __init__(self, keys=(), *, height=24, width=120):
            self.keys = iter(keys)
            self.height = height
            self.width = width
            self.lines = []
            self.history = []

        def clear(self):
            self.lines.clear()

        def addstr(self, row, column, value):
            self.lines.append((row, column, value))
            self.history.append((row, column, value))

        def refresh(self):
            pass

        def getmaxyx(self):
            return self.height, self.width

        def getch(self):
            return next(self.keys)

    def test_copy_starts_selected_and_down_selects_symlink(self):
        copy_screen = self.Screen((10,))
        symlink_screen = self.Screen((curses.KEY_DOWN, 10))

        self.assertEqual(tui._curses_install_mode(curses, copy_screen), "copy")
        self.assertEqual(tui._curses_install_mode(curses, symlink_screen), "symlink")
        self.assertIn("Copy (recommended)", "\n".join(v for _, _, v in copy_screen.history))

    def test_every_common_backspace_code_returns_to_action(self):
        for key in (curses.KEY_BACKSPACE, 127, 8):
            with self.subTest(key=key):
                self.assertEqual(
                    tui._curses_install_mode(curses, self.Screen((key,))),
                    "back",
                )

    def test_disabled_row_cannot_be_toggled_and_uses_non_color_marker(self):
        screen = self.Screen((ord(" "), 10))

        selected = tui._curses_multiselect(
            curses,
            screen,
            "Artifacts",
            ("copy-only row",),
            disabled=(True,),
        )

        self.assertEqual(selected, ())
        self.assertIn("[-]", "\n".join(value for _, _, value in screen.history))

    def test_install_dispatches_after_wrapper_with_symlink_request(self):
        inside_wrapper = {"value": False}

        def wrapper(callback):
            inside_wrapper["value"] = True
            callback(object())
            inside_wrapper["value"] = False

        singles = iter((0, 0))
        multis = iter(((0,), (0,)))

        def dispatch(request):
            self.assertFalse(inside_wrapper["value"])
            self.assertEqual(request.install_mode, "symlink")
            return _outcome(request)

        with (
            redirect_stdout(io.StringIO()),
            mock.patch.object(curses, "wrapper", side_effect=wrapper),
            mock.patch.object(curses, "curs_set", return_value=None),
            mock.patch.object(
                tui,
                "_curses_singleselect",
                side_effect=lambda *_args, **_kwargs: next(singles),
            ),
            mock.patch.object(
                tui,
                "_curses_multiselect",
                side_effect=lambda *_args, **_kwargs: next(multis),
            ),
            mock.patch.object(tui, "_curses_install_scope", return_value="project"),
            mock.patch.object(tui, "_curses_install_mode", return_value="symlink"),
            mock.patch.object(tui, "_curses_confirm_install", return_value=True) as confirm,
            mock.patch.object(tui, "_dispatch_result", side_effect=dispatch) as dispatch_mock,
        ):
            code = tui._run_curses(source_dir=FIXTURES)

        self.assertEqual(code, 0)
        confirm.assert_called_once()
        confirmation = confirm.call_args.args[2]
        self.assertEqual(confirmation.requested_mode, "symlink")
        self.assertEqual((confirmation.modes.linked, confirmation.modes.copied), (1, 0))
        dispatch_mock.assert_called_once()

    def test_declined_curses_confirmation_never_dispatches(self):
        def wrapper(callback):
            callback(object())

        singles = iter((0, 0))
        multis = iter(((0,), (0,)))
        output = io.StringIO()
        with (
            redirect_stdout(output),
            mock.patch.object(curses, "wrapper", side_effect=wrapper),
            mock.patch.object(curses, "curs_set", return_value=None),
            mock.patch.object(
                tui,
                "_curses_singleselect",
                side_effect=lambda *_args, **_kwargs: next(singles),
            ),
            mock.patch.object(
                tui,
                "_curses_multiselect",
                side_effect=lambda *_args, **_kwargs: next(multis),
            ),
            mock.patch.object(tui, "_curses_install_scope", return_value="project"),
            mock.patch.object(tui, "_curses_install_mode", return_value="copy"),
            mock.patch.object(tui, "_curses_confirm_install", return_value=False),
            mock.patch.object(tui, "_dispatch_result") as dispatch,
        ):
            code = tui._run_curses(source_dir=FIXTURES)

        self.assertEqual(code, 0)
        dispatch.assert_not_called()
        self.assertIn("Cancelled; no changes were made.", output.getvalue())

    def test_curses_mode_back_reopens_scope_before_any_dispatch(self):
        def wrapper(callback):
            callback(object())

        action_titles = []
        singles = iter((0, 0, 0))

        def single(_curses, _screen, title, _labels):
            if title.startswith("Action"):
                action_titles.append(title)
            return next(singles)

        multis = iter(((0,), (0,)))
        with (
            redirect_stdout(io.StringIO()),
            mock.patch.object(curses, "wrapper", side_effect=wrapper),
            mock.patch.object(curses, "curs_set", return_value=None),
            mock.patch.object(tui, "_curses_singleselect", side_effect=single),
            mock.patch.object(
                tui,
                "_curses_multiselect",
                side_effect=lambda *_args, **_kwargs: next(multis),
            ),
            mock.patch.object(tui, "_curses_install_scope", return_value="project") as scope_select,
            mock.patch.object(tui, "_curses_install_mode", side_effect=("back", "copy")),
            mock.patch.object(tui, "_curses_confirm_install", return_value=False),
            mock.patch.object(tui, "_dispatch_result") as dispatch,
        ):
            code = tui._run_curses(source_dir=FIXTURES)

        self.assertEqual(code, 0)
        self.assertEqual(len(action_titles), 1)
        self.assertEqual(scope_select.call_count, 2)
        dispatch.assert_not_called()

    def test_remote_curses_symlink_exits_usage_before_selection(self):
        remote = Source(root=FIXTURES, _label="pin:" + "b" * 40)

        def wrapper(callback):
            callback(object())

        singles = iter((0, 0))
        output = io.StringIO()
        with (
            redirect_stdout(output),
            mock.patch.object(curses, "wrapper", side_effect=wrapper),
            mock.patch.object(curses, "curs_set", return_value=None),
            mock.patch.object(
                tui,
                "_curses_singleselect",
                side_effect=lambda *_args, **_kwargs: next(singles),
            ),
            mock.patch.object(tui, "open_source", return_value=Ok(remote)),
            mock.patch.object(tui, "_curses_multiselect", return_value=(0,)) as multiselect,
            mock.patch.object(tui, "_curses_install_scope", return_value="project"),
            mock.patch.object(tui, "_curses_install_mode", return_value="symlink"),
            mock.patch.object(tui, "_dispatch_result") as dispatch,
        ):
            code = tui._run_curses(repo="owner/catalog")

        self.assertEqual(code, 2)
        self.assertEqual(multiselect.call_count, 1)  # harness only; no artifact selection
        dispatch.assert_not_called()
        self.assertIn("--source DIR --link", output.getvalue())

    def test_confirmation_screen_truncates_to_narrow_terminal(self):
        confirmation = tui.InstallConfirmation(
            source_label="local:/very/long/catalog/path",
            source_root="/very/long/catalog/path",
            destination_root="/very/long/project/path",
            profiles=("claude",),
            requested_mode="symlink",
            selected=("backend",),
            modes=tui.InstallModeCounts(linked=2, copied=3),
        )
        screen = self.Screen((ord("n"),), height=5, width=18)

        confirmed = tui._curses_confirm_install(curses, screen, confirmation)

        self.assertFalse(confirmed)
        self.assertTrue(screen.history)
        self.assertTrue(all(len(value) <= 17 for _, _, value in screen.history))


class TextInstallModeLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.source = self.root / "source"
        self.project = self.root / "project"
        shutil.copytree(FIXTURES, self.source)
        self.project.mkdir()

    def _run(self, answers, *, project=None):
        write, lines = _collector()
        code = tui._run_text(
            _scripted_reader(answers),
            write,
            source_dir=str(self.source),
            project=str(project or self.project),
        )
        return code, lines

    def test_symlink_install_update_and_uninstall_preserve_source_target(self):
        code, install_lines = self._run(["1", "1", "install", "1", "2", "1", "y"])
        destination = self.project / ".claude" / "skills" / "code-review"
        source_target = self.source / "skills" / "code-review"

        self.assertEqual(code, 0)
        self.assertTrue(destination.is_symlink())
        self.assertEqual(os.readlink(destination), str(source_target))
        manifest = json.loads(
            (self.project / ".agent-artifacts" / "manifest.json").read_text(encoding="utf-8")
        )
        entry = manifest["installed"][0]
        self.assertEqual(entry["install"]["requested_mode"], "symlink")
        self.assertEqual(entry["install"]["mode"], "symlink")
        self.assertEqual(entry["install"]["links"][0]["target"], str(source_target))
        self.assertTrue(any("mode=symlink" in line for line in install_lines))

        update_code, update_lines = self._run(["1", "1", "update", "1", "1", "y"])

        self.assertEqual(update_code, 0)
        self.assertTrue(destination.is_symlink())
        self.assertTrue(any("live-linked" in line for line in update_lines))
        self.assertTrue(any("Recorded subscription:" in line for line in update_lines))
        self.assertTrue(any("Resolved destination:" in line for line in update_lines))

        uninstall_code, uninstall_lines = self._run(["1", "1", "uninstall", "1", "1", "y"])

        self.assertEqual(uninstall_code, 0)
        self.assertTrue(any("Recorded subscription:" in line for line in uninstall_lines))
        self.assertTrue(any("Resolved destination:" in line for line in uninstall_lines))
        self.assertFalse(os.path.lexists(destination))
        self.assertTrue((source_target / "SKILL.md").exists())

    def test_mixed_bundle_confirmation_matches_actual_completion_modes(self):
        code, lines = self._run(["1", "1", "install", "1", "2", "6", "y"])
        rendered = "\n".join(lines)

        self.assertEqual(code, 0)
        self.assertIn("Projected modes: 2 linked, 2 copied", rendered)
        self.assertIn("Modes: 2 copied, 2 symlinked.", rendered)
        self.assertIn("--link only applies", rendered)
        self.assertTrue((self.project / ".claude" / "skills" / "code-review").is_symlink())
        self.assertTrue((self.project / ".claude" / "hooks" / "block-secrets").is_symlink())
        self.assertTrue((self.project / ".claude" / "guidelines" / "python-style.md").is_file())
        manifest = json.loads(
            (self.project / ".agent-artifacts" / "manifest.json").read_text(encoding="utf-8")
        )
        modes = {entry["artifact"]: entry["install"]["mode"] for entry in manifest["installed"]}
        self.assertEqual(
            modes,
            {
                "code-review": "symlink",
                "python-style": "copy",
                "block-secrets": "symlink",
                "postgres": "copy",
            },
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
