"""Issue #21: curses onboarding, Backspace, viewport, basket, and Finalize."""

from __future__ import annotations

import curses
import io
import pathlib
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
        self.assertIn("Selected: 1", rendered)
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
