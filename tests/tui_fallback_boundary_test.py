"""ERR05 (partial): the curses-to-text fallback boundary.

Text fallback is legitimate for exactly one condition — the terminal cannot host curses,
detected before the wizard interacts with the user. Every other failure must propagate, so a
defect can never be mistaken for a missing terminal and silently restart the wizard at
onboarding with the user's selections discarded.
"""

from __future__ import annotations

import curses
import io
import unittest
from contextlib import redirect_stdout
from unittest import mock

from agent_artifacts import tui
from agent_artifacts.configuration.model import (
    OrganizationPolicy,
    default_user_configuration,
)
from agent_artifacts.domain.result import Ok
from agent_artifacts.tui_sources import build_source_stage


class _TtyCapture(io.StringIO):
    """Captures stdout while still answering the TTY probe the way a terminal would."""

    def isatty(self) -> bool:
        return True


def _runtime() -> tui._RuntimeSourceStage:
    stage = build_source_stage(default_user_configuration(), OrganizationPolicy(1), {})
    assert isinstance(stage, Ok), stage
    return tui._RuntimeSourceStage(
        stage.value, lambda _request: Ok(object()), lambda _request: Ok(object())
    )


class CursesFallbackBoundaryTests(unittest.TestCase):
    """``_run_curses`` distinguishes "no terminal" from "the wizard broke"."""

    def test_setup_failure_before_interaction_reports_curses_unavailable(self):
        def wrapper(_callback):
            raise curses.error("setupterm: could not find terminal")

        with mock.patch.object(curses, "wrapper", side_effect=wrapper):
            with self.assertRaises(tui.CursesUnavailable):
                tui._run_curses(source_dir=None, repo=None, project=None)

    def test_failure_after_interaction_propagates_unchanged(self):
        """A defect inside the wizard must not be reported as a terminal problem."""

        def wrapper(callback):
            callback(object())

        with (
            mock.patch.object(curses, "wrapper", side_effect=wrapper),
            mock.patch.object(curses, "curs_set", return_value=None),
            mock.patch.object(
                tui,
                "_curses_onboarding",
                side_effect=ValueError("TUI marketplace artifact row is invalid"),
            ),
        ):
            with self.assertRaises(ValueError):
                tui._run_curses(source_dir=None, repo=None, project=None)

    def test_run_starts_the_text_wizard_once_when_curses_is_unavailable(self):
        with (
            mock.patch.object(tui, "_runtime_source_stage_context", return_value=Ok(_runtime())),
            mock.patch.object(tui.sys.stdin, "isatty", return_value=True),
            mock.patch.object(tui.sys.stdout, "isatty", return_value=True),
            mock.patch.object(tui, "_run_curses", side_effect=tui.CursesUnavailable("no terminal")),
            mock.patch.object(tui, "_run_text", return_value=0) as fallback,
        ):
            code = tui.run(user_home="/tmp/aart-home")

        self.assertEqual(code, 0)
        self.assertEqual(fallback.call_count, 1)

    def test_run_never_restarts_the_wizard_after_an_internal_defect(self):
        output = _TtyCapture()
        with (
            mock.patch.object(tui, "_runtime_source_stage_context", return_value=Ok(_runtime())),
            mock.patch.object(tui.sys.stdin, "isatty", return_value=True),
            mock.patch.object(
                tui, "_run_curses", side_effect=ValueError("duplicate claude:current")
            ),
            mock.patch.object(tui, "_run_text", return_value=0) as fallback,
            redirect_stdout(output),
        ):
            code = tui.run(user_home="/tmp/aart-home")

        rendered = output.getvalue()
        self.assertNotEqual(code, 0)
        fallback.assert_not_called()
        self.assertIn("tui-stage-internal", rendered)

    def test_internal_defect_output_carries_no_traceback_or_exception_text(self):
        """Redacted by default; the opt-in debug channel is deferred to ERR05b."""

        output = _TtyCapture()
        with (
            mock.patch.object(tui, "_runtime_source_stage_context", return_value=Ok(_runtime())),
            mock.patch.object(tui.sys.stdin, "isatty", return_value=True),
            mock.patch.object(
                tui, "_run_curses", side_effect=ValueError("/Users/secret/path leaked")
            ),
            mock.patch.object(tui, "_run_text", return_value=0),
            redirect_stdout(output),
        ):
            tui.run(user_home="/tmp/aart-home")

        rendered = output.getvalue()
        self.assertNotIn("Traceback", rendered)
        self.assertNotIn("/Users/secret/path leaked", rendered)
        self.assertIn("ValueError", rendered)

    def test_missing_tty_still_falls_back_before_any_interaction(self):
        with (
            mock.patch.object(tui, "_runtime_source_stage_context", return_value=Ok(_runtime())),
            mock.patch.object(tui.sys.stdin, "isatty", return_value=False),
            mock.patch.object(tui, "_run_curses") as never,
            mock.patch.object(tui, "_run_text", return_value=0) as fallback,
        ):
            code = tui.run(user_home="/tmp/aart-home")

        self.assertEqual(code, 0)
        never.assert_not_called()
        self.assertEqual(fallback.call_count, 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
