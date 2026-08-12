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
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from agent_artifacts import tui
from agent_artifacts.configuration.model import (
    OrganizationPolicy,
    default_user_configuration,
)
from agent_artifacts.domain.result import Ok
from agent_artifacts.tui_sources import build_source_stage
from agent_artifacts.wizard import WizardSession


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

    def test_failure_context_keeps_the_last_safe_stage_without_touching_the_session(self):
        context = tui.InternalFailureContext()

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
                tui._run_curses(
                    source_dir=None,
                    repo=None,
                    project=None,
                    failure_context=context,
                )

        self.assertEqual((context.stage, context.operation), ("onboarding", "load"))

    def test_failure_context_tracks_the_artifacts_loader_boundary(self):
        context = tui.InternalFailureContext()
        session = WizardSession(
            current="artifacts",
            action="install",
            profiles=("claude",),
            scope="project",
        )

        with mock.patch.object(
            tui,
            "_load_user_wizard_read_model",
            side_effect=ValueError("broken marketplace projection"),
        ):
            with self.assertRaises(ValueError):
                tui._run_user_curses_wizard(
                    curses,
                    object(),
                    session,
                    {},
                    source_dir=None,
                    repo=None,
                    project="/work/project",
                    user_home=None,
                    failure_context=context,
                )

        self.assertEqual((context.stage, context.operation), ("artifacts", "load"))

    def test_failure_context_marks_reporting_after_the_known_setup_outcome(self):
        context = tui.InternalFailureContext("review", "setup")

        with (
            mock.patch.object(
                tui,
                "_canonical_setup_run",
                return_value=tui._CanonicalSetupRun(0, ()),
            ),
            mock.patch.object(
                tui,
                "usage_report_from_consumer",
                side_effect=RuntimeError("reporting adapter failed"),
            ),
        ):
            with self.assertRaises(RuntimeError):
                tui._complete_canonical_consumer_action(
                    mock.Mock(),
                    mock.Mock(),
                    mock.Mock(),
                    None,
                    read=lambda _prompt="": "",
                    write=lambda _line: None,
                    failure_context=context,
                )

        self.assertEqual((context.stage, context.operation), ("review", "reporting"))

    def test_internal_failure_record_includes_stage_and_operation_but_not_message(self):
        lines = tui.internal_failure_lines(
            ValueError("/Users/secret/path leaked"),
            tui.InternalFailureContext("artifacts", "load"),
        )

        rendered = "\n".join(lines)
        self.assertIn("tui-stage-internal", rendered)
        self.assertIn("stage: artifacts", rendered)
        self.assertIn("operation: load", rendered)
        self.assertNotIn("/Users/secret/path leaked", rendered)

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
        self.assertIn("stage: onboarding", rendered)
        self.assertIn("operation: load", rendered)

    def test_internal_defect_output_carries_no_traceback_or_exception_text(self):
        """Default terminal output never includes raw exception text or a traceback."""

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

    def test_debug_traceback_is_explicit_local_stderr_output(self):
        output = _TtyCapture()
        debug = io.StringIO()
        with (
            mock.patch.object(tui, "_runtime_source_stage_context", return_value=Ok(_runtime())),
            mock.patch.object(tui.sys.stdin, "isatty", return_value=True),
            mock.patch.object(
                tui, "_run_curses", side_effect=ValueError("/Users/secret/path leaked")
            ),
            mock.patch.object(tui, "_run_text", return_value=0) as fallback,
            mock.patch.dict(tui.os.environ, {"AART_DEBUG": "1"}, clear=False),
            redirect_stdout(output),
            redirect_stderr(debug),
        ):
            code = tui.run(user_home="/tmp/aart-home")

        self.assertEqual(code, 2)
        fallback.assert_not_called()
        self.assertNotIn("/Users/secret/path leaked", output.getvalue())
        self.assertIn("ValueError: /Users/secret/path leaked", debug.getvalue())

    def test_unexpected_terminal_probe_error_is_not_silently_downgraded_to_text(self):
        output = _TtyCapture()
        with (
            mock.patch.object(tui, "_runtime_source_stage_context", return_value=Ok(_runtime())),
            mock.patch.object(tui, "_curses_supported", side_effect=ValueError("probe secret")),
            mock.patch.object(tui, "_run_text", return_value=0) as fallback,
            redirect_stdout(output),
        ):
            code = tui.run(user_home="/tmp/aart-home")

        self.assertEqual(code, 2)
        fallback.assert_not_called()
        self.assertIn("tui-stage-internal", output.getvalue())
        self.assertNotIn("probe secret", output.getvalue())

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
