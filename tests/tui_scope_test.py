"""Issue #19 TDD contracts for scope-aware text/curses TUI behavior."""

from __future__ import annotations

import curses
import pathlib
import tempfile
import unittest
from unittest import mock

from agent_artifacts import tui
from agent_artifacts.model import Request
from agent_artifacts.outcomes import ActionSummary, CommandOutcome
from agent_artifacts.profiles.loader import load_profiles
from agent_artifacts.profiles.scope import profile_for_scope
from agent_artifacts.source import open_source

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


def _catalog():
    return open_source(Request(command="list", source_dir=FIXTURES)).value.catalog().value


class ScopeChoiceTests(unittest.TestCase):
    def test_project_is_first_recommended_and_default(self):
        self.assertEqual(
            [(choice.scope, choice.label) for choice in tui.INSTALL_SCOPE_CHOICES],
            [("project", "Project (recommended)"), ("user", "User")],
        )
        self.assertEqual(
            tui._prompt_install_scope(_scripted_reader([""]), lambda _line: None), "project"
        )
        self.assertEqual(
            tui._prompt_install_scope(_scripted_reader(["2"]), lambda _line: None), "user"
        )

    def test_user_unsupported_row_is_disabled_with_declared_reason(self):
        profiles = load_profiles()
        scoped = {
            name: profile_for_scope(profile, "user", "/fake/home")
            for name, profile in profiles.items()
        }
        choices = tui.build_install_choices(
            _catalog(),
            ("vibe",),
            scoped,
            scope="user",
        )
        house = next(choice for choice in choices if choice.name == "house")
        self.assertFalse(house.enabled)
        self.assertIn("no documented always-loaded global instruction file", house.reason)
        self.assertIn(house.reason, house.label)

    def test_user_confirmation_lists_resolved_absolute_destinations(self):
        profiles = load_profiles()
        scoped = {
            name: profile_for_scope(profile, "user", "/fake/home")
            for name, profile in profiles.items()
        }
        choices = tui.build_install_choices(
            _catalog(),
            ("claude",),
            scoped,
            scope="user",
        )
        selected = tuple(choice for choice in choices if choice.name in ("code-review", "postgres"))

        confirmation = tui.build_install_confirmation(
            source_label=f"local:{FIXTURES}",
            source_root=FIXTURES,
            project=None,
            scope="user",
            user_home="/fake/home",
            profiles=("claude",),
            requested_mode="copy",
            catalog=_catalog(),
            choices=selected,
            profiles_map=scoped,
        )
        rendered = "\n".join(tui.render_install_confirmation(confirmation))

        self.assertIn("Destination: User — /fake/home", rendered)
        self.assertIn("/fake/home/.claude/skills/code-review", rendered)
        self.assertIn("/fake/home/.claude.json", rendered)
        self.assertTrue(all(path.startswith("/fake/home/") for path in confirmation.destinations))


class TextScopeFlowTests(unittest.TestCase):
    def test_install_scope_is_selected_before_source_and_reaches_dispatch(self):
        with tempfile.TemporaryDirectory() as fake_home:
            seen_sources = []
            dispatched = []
            output = []

            def source_factory(request):
                seen_sources.append(request)
                return open_source(request)

            with mock.patch.object(
                tui,
                "_dispatch_result",
                side_effect=lambda request: (
                    dispatched.append(request) or CommandOutcome(0, ActionSummary(action="install"))
                ),
            ):
                code = tui._run_user_text(
                    _scripted_reader(["1", "1", "2", "1", "1", "y"]),
                    output.append,
                    source_factory=source_factory,
                    source_dir=FIXTURES,
                    project="/must-not-reach-user-request",
                    user_home=fake_home,
                )

        self.assertEqual(code, 0)
        self.assertEqual(seen_sources[0].scope, "user")
        self.assertIsNone(seen_sources[0].project)
        self.assertEqual(dispatched[0].scope, "user")
        self.assertEqual(dispatched[0].user_home, fake_home)
        self.assertIsNone(dispatched[0].project)
        self.assertLess(
            output.index("Installation scope:"),
            next(i for i, line in enumerate(output) if line.startswith("Source:")),
        )

    def test_status_selects_scope_and_dispatches_without_loading_catalog(self):
        dispatched = []
        source_factory = mock.Mock(side_effect=AssertionError("status must not load a catalog"))
        with mock.patch.object(
            tui,
            "_dispatch_result",
            side_effect=lambda request: (
                dispatched.append(request) or CommandOutcome(0, ActionSummary(action="status"))
            ),
        ):
            code = tui._run_user_text(
                _scripted_reader(["1", "4", "2"]),
                lambda _line: None,
                source_factory=source_factory,
                source_dir=FIXTURES,
                user_home="/fake/home",
            )

        self.assertEqual(code, 0)
        source_factory.assert_not_called()
        self.assertEqual(dispatched[0].command, "status")
        self.assertEqual(dispatched[0].scope, "user")

    def test_every_consumer_action_prompts_for_scope(self):
        for action_index in ("1", "2", "3", "4"):
            with self.subTest(action_index=action_index):
                output = []
                with (
                    mock.patch.object(
                        tui,
                        "_load_manifest_for_action",
                        return_value=mock.Mock(value=mock.Mock(installed=())),
                    ),
                    mock.patch.object(
                        tui,
                        "_dispatch_result",
                        return_value=CommandOutcome(0, ActionSummary(action="status")),
                    ),
                ):
                    tui._run_user_text(
                        _scripted_reader(["1", action_index, "2"]),
                        output.append,
                        source_dir=FIXTURES,
                        user_home="/fake/home",
                    )
                self.assertIn("Installation scope:", output)


class CursesScopeSelectorTests(unittest.TestCase):
    class Screen:
        def __init__(self, keys):
            self.keys = iter(keys)

        def clear(self):
            pass

        def addstr(self, *_args):
            pass

        def refresh(self):
            pass

        def getch(self):
            return next(self.keys)

        def getmaxyx(self):
            return (24, 120)

    def test_scope_selector_defaults_to_project_and_can_choose_user(self):
        project = self.Screen((10,))
        user = self.Screen((curses.KEY_DOWN, 10))
        self.assertEqual(tui._curses_install_scope(curses, project), "project")
        self.assertEqual(tui._curses_install_scope(curses, user), "user")
