"""Issue #21: curses onboarding, Backspace, viewport, basket, and Finalize."""

from __future__ import annotations

import ast
import curses
import io
import pathlib
import re
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from agent_artifacts import tui
from agent_artifacts.consumer import (
    ConsumerApplicationService,
    ConsumerContext,
    LocalConsumerAdapter,
)
from agent_artifacts.domain.result import Ok
from agent_artifacts.outcomes import ActionSummary, CommandOutcome, OutcomeItem
from agent_artifacts.profiles.builtin import builtin
from agent_artifacts.tui_sources import build_source_stage
from agent_artifacts.wizard import (
    BasketItem,
    WizardInput,
    initial_session,
)
from agent_artifacts.wizard import (
    advance as wizard_advance,
)
from agent_artifacts.wizard import (
    select as wizard_select,
)
from tests.canonical_symlink_test import _fixture
from tests.marketplace_fixtures import source_state
from tests.wizard_state_test import source_selection

FIXTURES = str(pathlib.Path(__file__).resolve().parent / "fixtures")


class Screen:
    def __init__(self, keys=(), *, height=14, width=54):
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


class StatusBarTests(unittest.TestCase):
    """WP-3 steps 1 and 6 of DESIGN-tui-legibility: one pinned bar, and `b` goes back."""

    def bar(self, screen: Screen) -> str:
        painted = [value for row, _column, value in screen.lines if row == screen.height - 1]
        self.assertEqual(len(painted), 1, painted)
        return painted[0]

    def test_the_bar_holds_the_last_row_at_every_scroll_offset(self) -> None:
        labels = tuple(f"item-{index}" for index in range(40))

        for scroll, cursor in ((0, 0), (33, 39)):
            with self.subTest(scroll=scroll):
                screen = Screen(height=12, width=70)

                tui._draw_list(
                    curses,
                    screen,
                    "Artifacts",
                    labels,
                    cursor,
                    [False] * len(labels),
                    hints=(("enter", "confirm"), ("q", "quit")),
                    scroll=scroll,
                )

                bar = self.bar(screen)
                self.assertIn("enter=confirm", bar)
                self.assertIn("q=quit", bar)
                self.assertIn("of 40", bar)

    def test_the_bar_advertises_exactly_the_keys_the_screen_accepts(self) -> None:
        screen = Screen((10,), height=16, width=90)

        tui._curses_multiselect(
            curses,
            screen,
            "Artifacts",
            ("one", "two"),
            details=("first", "second"),
            wizard=True,
            allow_add=True,
        )

        bar = self.bar(screen)
        for hint in ("space=toggle", "enter=confirm", "b=back", "?=details", "a=add", "q=quit"):
            self.assertIn(hint, bar)

    def test_a_single_choice_bar_offers_neither_toggle_nor_add(self) -> None:
        screen = Screen((10,), height=16, width=90)

        tui._curses_singleselect(curses, screen, "Role", ("User", "Maintainer"), wizard=True)

        bar = self.bar(screen)
        self.assertIn("enter=confirm", bar)
        self.assertIn("b=back", bar)
        self.assertNotIn("space=toggle", bar)
        self.assertNotIn("a=add", bar)
        self.assertNotIn("?=details", bar)

    def test_the_bar_counts_the_selection_and_sheds_counters_before_keys(self) -> None:
        wide = Screen((10,), height=16, width=90)
        tui._curses_multiselect(
            curses, wide, "Artifacts", ("one", "two"), wizard=True, initial_checked=(0,)
        )
        self.assertIn("1 selected", self.bar(wide))

        narrow = Screen((10,), height=8, width=22)
        tui._curses_multiselect(
            curses, narrow, "Artifacts", ("one", "two"), wizard=True, initial_checked=(0,)
        )
        cramped = self.bar(narrow)
        self.assertNotIn("selected", cramped)
        self.assertIn("enter=confirm", cramped)
        self.assertIn("q=quit", cramped)
        self.assertLessEqual(len(cramped), 21)

    def test_b_returns_the_same_back_event_as_backspace(self) -> None:
        for key in (ord("b"), curses.KEY_BACKSPACE):
            with self.subTest(key=key):
                multi = tui._curses_multiselect(
                    curses, Screen((key,)), "Artifacts", ("one",), wizard=True
                )
                single = tui._curses_singleselect(
                    curses, Screen((key,)), "Role", ("User",), wizard=True
                )

                self.assertEqual(multi.kind, "back")
                self.assertEqual(single.kind, "back")

    def test_a_disabled_row_keeps_its_box_column_and_warns(self) -> None:
        screen = Screen((10,), height=16, width=60)

        tui._curses_multiselect(
            curses,
            screen,
            "Artifacts",
            ("selectable", "blocked"),
            disabled=(False, True),
        )

        rendered = "\n".join(value for _row, _column, value in screen.history)
        self.assertIn("[!] blocked", rendered)
        self.assertIn("[ ] selectable", rendered)
        self.assertNotIn("[-]", rendered)


_KEY_HINT = re.compile(
    r"(?:^|[\s(])[\w?↑↓/]+\s*=\s*"
    r"(?:toggle|confirm|back|quit|details|add|start|scroll|finalize|cancel|choose|continue)",
    re.IGNORECASE,
)


class ScreenChromeTests(unittest.TestCase):
    """WP-3 step 3: titles are nouns, and every pinned footer speaks the bar's vocabulary."""

    def footer(self, screen: Screen) -> str:
        painted = [value for row, _column, value in screen.lines if row == screen.height - 1]
        self.assertEqual(len(painted), 1, painted)
        return painted[0]

    def test_no_screen_string_advertises_a_key_outside_the_bar(self) -> None:
        # Text-mode prompts keep their hints (design section 5): they are the last thing printed
        # before input, which is text mode's pinned bar. Everything else defers to status_bar.
        module = ast.parse(pathlib.Path(tui.__file__).read_text(encoding="utf-8"))
        literals = [
            node.value
            for node in ast.walk(module)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        ]

        offenders = [
            text for text in literals if _KEY_HINT.search(text) and not text.endswith(": ")
        ]

        self.assertEqual(offenders, [])

    def test_no_screen_string_uses_the_dot_as_a_separator(self) -> None:
        module = ast.parse(pathlib.Path(tui.__file__).read_text(encoding="utf-8"))
        offenders = [
            node.value
            for node in ast.walk(module)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and " · " in node.value
        ]

        self.assertEqual(offenders, [])

    def test_the_onboarding_footer_is_a_status_bar(self) -> None:
        screen = Screen((10,), height=14, width=70)

        tui._curses_onboarding(curses, screen)

        footer = self.footer(screen)
        self.assertIn("enter=start", footer)
        self.assertIn("q=quit", footer)

    def test_the_review_footer_names_finalize_back_and_quit(self) -> None:
        session = wizard_advance(initial_session())
        screen = Screen((ord("n"),), height=14, width=70)

        tui._curses_review(curses, screen, session, ("Review", "line"))

        footer = self.footer(screen)
        self.assertIn("enter=finalize", footer)
        self.assertIn("b=back", footer)
        self.assertIn("q=quit", footer)

    def test_the_mode_screen_paints_the_same_bar_as_any_other_list(self) -> None:
        screen = Screen((10,), height=14, width=70)

        tui._curses_install_mode(curses, screen)

        footer = self.footer(screen)
        self.assertIn("enter=confirm", footer)
        self.assertIn("b=back", footer)
        self.assertIn("q=quit", footer)

    def test_b_goes_back_from_the_review_and_mode_screens(self) -> None:
        session = wizard_advance(initial_session())

        self.assertEqual(
            tui._curses_review(curses, Screen((ord("b"),)), session, ("Review",)), "back"
        )
        self.assertEqual(tui._curses_install_mode(curses, Screen((ord("b"),))), "back")


class CursesWizardPrimitiveTests(unittest.TestCase):
    def test_onboarding_is_first_and_enter_continues(self):
        screen = Screen((10,))

        event = tui._curses_onboarding(curses, screen)

        self.assertEqual(event, WizardInput("confirm"))
        rendered = "\n".join(value for _row, _column, value in screen.history)
        # D11: onboarding explains the product, not the keys — those are permanently in the bar.
        self.assertIn("How aart works", rendered)
        self.assertIn("Maintainer", rendered)
        self.assertNotIn("Backspace", rendered)
        self.assertIn("▸ How it works", rendered)

    def test_every_backspace_code_returns_explicit_back_event(self):
        for key in (curses.KEY_BACKSPACE, 127, 8):
            with self.subTest(key=key):
                result = tui._curses_singleselect(
                    curses,
                    Screen((key,)),
                    "Role",
                    ("User", "Maintainer"),
                    wizard=True,
                )
                self.assertEqual(result.kind, "back")

    def test_multiselect_recognizes_every_backspace_code_without_toggling(self):
        for key in (curses.KEY_BACKSPACE, 127, 8):
            with self.subTest(key=key):
                result = tui._curses_multiselect(
                    curses,
                    Screen((key,)),
                    "Artifacts",
                    ("one", "two"),
                    wizard=True,
                    initial_checked=(1,),
                )
                self.assertEqual(result.kind, "back")
                self.assertEqual(result.selected, ())

    def test_multiselect_restores_checked_cursor_and_scroll(self):
        screen = Screen((10,), height=6)

        result = tui._curses_multiselect(
            curses,
            screen,
            "Artifacts",
            tuple(f"item {index}" for index in range(8)),
            wizard=True,
            initial_checked=(5,),
            initial_cursor=5,
            initial_scroll=3,
        )

        self.assertEqual(result.kind, "confirm")
        self.assertEqual(result.selected, (5,))
        self.assertEqual(result.cursor, 5)
        self.assertGreaterEqual(result.scroll, 3)
        self.assertIn("[x] item 5", "\n".join(value for _, _, value in screen.history))

    def test_narrow_wizard_keeps_stage_basket_controls_and_a_visible_row(self):
        session = wizard_advance(initial_session())
        session = wizard_select(session, "role", "user")
        session = wizard_advance(session)
        session = wizard_select(session, "source", source_selection())
        session = wizard_advance(session)
        session = wizard_select(session, "profiles", ("claude",))
        session = wizard_advance(session)
        session = wizard_select(session, "action", "install")
        session = wizard_advance(session)
        session = wizard_select(session, "scope", "project")
        session = wizard_advance(session)
        session = wizard_select(session, "mode", "copy")
        session = wizard_advance(session)
        session = wizard_select(
            session,
            "artifacts",
            (BasketItem("artifact", "skill/one", "one"),),
        )
        screen = Screen((10,), height=8, width=22)

        tui._curses_multiselect(
            curses,
            screen,
            "Artifacts (enter=continue)",
            ("one", "two"),
            wizard=True,
            initial_checked=(0,),
            header=tui._curses_header(screen, session),
        )

        rendered = "\n".join(value for _, _, value in screen.history)
        self.assertIn("▸ Artifacts", rendered)
        self.assertIn("Basket:", rendered)
        # D2 moved the selection count out of its own header line and into the bar's counters,
        # which are the first thing a narrow terminal sheds. What survives here is the exit.
        self.assertIn("enter=confirm", rendered)
        self.assertIn("q=quit", rendered)
        self.assertIn("[x] one", rendered)
        self.assertTrue(all(len(value) <= 21 for _, _, value in screen.history))


class CursesWizardFlowTests(unittest.TestCase):
    def test_canonical_consumer_finalizes_after_curses_teardown_without_legacy_dispatch(self):
        with tempfile.TemporaryDirectory() as raw:
            fixture = _fixture(Path(raw), "skill")
            project, _checkout, paths, location, _request, catalog, effective = fixture
            service = ConsumerApplicationService(
                ConsumerContext(catalog, effective, builtin(), location, paths),
                LocalConsumerAdapter(),
            )
            configured = effective.configuration.sources[0]
            state = source_state(configured, "direct-source", display_order=0)
            source_view = build_source_stage(
                effective.configuration,
                effective.policy,
                {configured.alias: state.health},
                first_run=False,
            )
            assert isinstance(source_view, Ok), source_view
            inside_wrapper = {"value": False}

            def wrapper(callback):
                inside_wrapper["value"] = True
                callback(object())
                inside_wrapper["value"] = False

            singles = iter((0, 0))  # User, Install
            multis = iter(((0,), (0,), (0,)))  # source, profile, artifact
            output = io.StringIO()
            with (
                redirect_stdout(output),
                mock.patch.object(tui.sys, "platform", "darwin"),
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
                mock.patch.object(tui, "_curses_review", return_value=True),
                mock.patch.object(tui, "_dispatch_result") as legacy_dispatch,
            ):
                code = tui._run_curses(
                    project=str(project),
                    source_stage_view=source_view.value,
                    consumer_service=service,
                )

            self.assertFalse(inside_wrapper["value"])
            self.assertEqual(code, 0)
            legacy_dispatch.assert_not_called()
            self.assertIn("Install outcome: succeeded", output.getvalue())
            self.assertTrue((project / ".claude/skills/review/SKILL.md").exists())

    def test_review_back_keeps_basket_and_finalize_dispatches_once_after_teardown(self):
        inside_wrapper = {"value": False}

        def wrapper(callback):
            inside_wrapper["value"] = True
            callback(object())
            inside_wrapper["value"] = False

        singles = iter((0, 0))  # User, Install
        multis = iter(((0,), (0,), (0,)))  # profiles, artifacts, restored artifacts
        reviews = iter(("back", "quit", True))
        captured = []

        def dispatch(request):
            self.assertFalse(inside_wrapper["value"])
            captured.append(request)
            return CommandOutcome(
                0,
                ActionSummary(
                    action="install",
                    selected=1,
                    items=(OutcomeItem("skill/code-review@claude", "installed"),),
                ),
            )

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
            ) as multi,
            mock.patch.object(tui, "_curses_install_scope", return_value="project"),
            mock.patch.object(tui, "_curses_install_mode", return_value="copy"),
            mock.patch.object(
                tui, "_curses_confirm_install", side_effect=lambda *_a, **_k: next(reviews)
            ) as review,
            mock.patch.object(tui, "_curses_confirm_discard", return_value=False) as discard,
            mock.patch.object(tui, "_dispatch_result", side_effect=dispatch),
        ):
            code = tui._run_curses(source_dir=FIXTURES)

        self.assertEqual(code, 0)
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].names, ("code-review",))
        self.assertEqual(multi.call_count, 3)
        self.assertEqual(review.call_count, 3)
        discard.assert_called_once()

    def test_maintainer_user_back_returns_to_maintainer_action(self):
        titles = []
        singles = iter((1, 6, 0))  # Maintainer, User workflows, Health

        def wrapper(callback):
            callback(object())

        def single(_curses, _screen, title, _labels, **_kwargs):
            titles.append(title)
            return next(singles)

        captured = []
        with (
            redirect_stdout(io.StringIO()),
            mock.patch.object(curses, "wrapper", side_effect=wrapper),
            mock.patch.object(curses, "curs_set", return_value=None),
            mock.patch("builtins.input", side_effect=["finalize"]),
            mock.patch.object(tui, "_curses_singleselect", side_effect=single),
            mock.patch.object(tui, "_curses_multiselect", return_value=WizardInput("back")),
            mock.patch.object(
                tui, "_dispatch", side_effect=lambda request: captured.append(request) or 0
            ),
        ):
            code = tui._run_curses(source_dir=FIXTURES)

        self.assertEqual(code, 0)
        self.assertEqual(sum(title.startswith("Maintainer") for title in titles), 2)
        self.assertEqual(captured[0].upstream_action, "health")


if __name__ == "__main__":
    unittest.main()
