"""WP-20 tests: the interactive selector's text/fallback flow, driven headless.

Run: ``python -m unittest discover -s tests -p "tui_test.py" -v``

These tests never touch a real terminal or ``curses``: they drive :func:`tui._run_text`
directly with a scripted ``read`` and a capturing ``write``, point ``source_factory`` at the
on-disk fixtures (``tests/fixtures``), and use a fresh temp ``--project``. They assert the
selector (a) returns the right exit code, (b) actually dispatches through the *real* command
core (filesystem effects appear), and (c) builds the expected `Request` (via a patched
``cli.DISPATCH`` recorder) — proving no command logic is duplicated in the TUI.
"""

import io
import json
import os
import pathlib
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

from agent_artifacts import tui
from agent_artifacts.model import Ok, Request
from agent_artifacts.source import open_source

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = str(REPO_ROOT / "tests" / "fixtures")


def _scripted_reader(answers):
    """Return a ``read(prompt)`` callable that yields *answers* in order, then raises EOF."""
    it = iter(answers)

    def _read(_prompt=""):
        try:
            return next(it)
        except StopIteration:
            raise EOFError from None
    return _read


def _collector():
    """Return ``(write, lines)`` where ``write(text)`` appends to the ``lines`` list."""
    lines = []
    return (lambda text="": lines.append(text)), lines


class TextFlowInstallTests(unittest.TestCase):
    """The happy path: pick an artifact + profile + install, dispatched for real."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def _path(self, *parts):
        return os.path.join(self.project, *parts)

    def test_install_code_review_to_claude(self):
        # Row 1 = [skill] code-review ; profile 1 = claude ; action install.
        read = _scripted_reader(["1", "1", "install"])
        write, _ = _collector()
        with redirect_stdout(io.StringIO()):
            rc = tui._run_text(
                read,
                write,
                source_factory=open_source,
                source_dir=FIXTURES,
                project=self.project,
            )
        self.assertEqual(rc, 0)
        # The REAL install command ran: the skill tree + manifest are on disk.
        self.assertTrue(
            os.path.isfile(self._path(".claude", "skills", "code-review", "SKILL.md")),
            "selector did not dispatch through the real install command",
        )
        manifest_file = self._path(".agent-artifacts", "manifest.json")
        self.assertTrue(os.path.isfile(manifest_file))
        manifest = json.loads(pathlib.Path(manifest_file).read_text())
        installed = {e["artifact"] for e in manifest["installed"]}
        self.assertIn("code-review", installed)

    def test_action_by_name_or_number_equivalent(self):
        # Selecting the action by its name ("install") works like the number.
        read = _scripted_reader(["1", "1", "install"])
        write, _ = _collector()
        with redirect_stdout(io.StringIO()):
            rc = tui._run_text(
                read, write, source_dir=FIXTURES, project=self.project
            )
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isfile(self._path(".claude", "skills", "code-review", "SKILL.md")))


class TextFlowQuitTests(unittest.TestCase):
    """Quitting at any prompt returns 0 and dispatches nothing."""

    def test_quit_immediately_blank(self):
        read = _scripted_reader([""])  # blank at the first prompt
        write, _ = _collector()
        with mock.patch.object(tui, "_dispatch") as disp:
            rc = tui._run_text(read, write, source_dir=FIXTURES, project=None)
        self.assertEqual(rc, 0)
        disp.assert_not_called()

    def test_quit_with_q(self):
        read = _scripted_reader(["q"])
        write, _ = _collector()
        with mock.patch.object(tui, "_dispatch") as disp:
            rc = tui._run_text(read, write, source_dir=FIXTURES, project=None)
        self.assertEqual(rc, 0)
        disp.assert_not_called()

    def test_quit_at_profile_prompt(self):
        read = _scripted_reader(["1", "q"])  # pick artifact, then quit at profiles
        write, _ = _collector()
        with mock.patch.object(tui, "_dispatch") as disp:
            rc = tui._run_text(read, write, source_dir=FIXTURES, project=None)
        self.assertEqual(rc, 0)
        disp.assert_not_called()

    def test_quit_at_action_prompt(self):
        read = _scripted_reader(["1", "1", "q"])  # pick artifact + profile, quit at action
        write, _ = _collector()
        with mock.patch.object(tui, "_dispatch") as disp:
            rc = tui._run_text(read, write, source_dir=FIXTURES, project=None)
        self.assertEqual(rc, 0)
        disp.assert_not_called()

    def test_eof_is_clean_quit(self):
        read = _scripted_reader([])  # EOF immediately
        write, _ = _collector()
        with mock.patch.object(tui, "_dispatch") as disp:
            rc = tui._run_text(read, write, source_dir=FIXTURES, project=None)
        self.assertEqual(rc, 0)
        disp.assert_not_called()


class RequestAssemblyTests(unittest.TestCase):
    """The built Request carries the expected fields (no command logic duplicated)."""

    def test_dispatch_receives_expected_request(self):
        captured = {}

        def _recorder(request):
            captured["req"] = request
            return 0

        read = _scripted_reader(["1", "1", "install"])
        write, _ = _collector()
        with mock.patch.object(tui, "_dispatch", side_effect=_recorder):
            rc = tui._run_text(
                read, write, source_dir=FIXTURES, project="/tmp/example-proj"
            )
        self.assertEqual(rc, 0)
        req = captured["req"]
        self.assertIsInstance(req, Request)
        self.assertEqual(req.command, "install")
        self.assertEqual(req.names, ("code-review",))
        self.assertEqual(req.bundles, ())
        self.assertEqual(req.profiles, ("claude",))
        self.assertEqual(req.source_dir, FIXTURES)
        self.assertEqual(req.project, "/tmp/example-proj")
        self.assertTrue(req.yes)
        # Selection is left untyped so bare names resolve across types in the core.
        self.assertIsNone(req.type_filter)

    def test_bundle_selection_populates_bundles(self):
        # Row 6 = [bundle] backend (see _build_choices ordering).
        captured = {}

        def _recorder(request):
            captured["req"] = request
            return 0

        read = _scripted_reader(["6", "1", "install"])
        write, _ = _collector()
        with mock.patch.object(tui, "_dispatch", side_effect=_recorder):
            rc = tui._run_text(read, write, source_dir=FIXTURES, project=None)
        self.assertEqual(rc, 0)
        req = captured["req"]
        self.assertEqual(req.bundles, ("backend",))
        self.assertEqual(req.names, ())

    def test_multi_select_artifacts(self):
        captured = {}

        def _recorder(request):
            captured["req"] = request
            return 0

        read = _scripted_reader(["1,3", "1", "install"])  # code-review + postgres
        write, _ = _collector()
        with mock.patch.object(tui, "_dispatch", side_effect=_recorder):
            rc = tui._run_text(read, write, source_dir=FIXTURES, project=None)
        self.assertEqual(rc, 0)
        req = captured["req"]
        self.assertEqual(set(req.names), {"code-review", "postgres"})

    def test_uninstall_action_routes_through(self):
        captured = {}

        def _recorder(request):
            captured["req"] = request
            return 0

        read = _scripted_reader(["1", "1", "uninstall"])
        write, _ = _collector()
        with mock.patch.object(tui, "_dispatch", side_effect=_recorder):
            rc = tui._run_text(read, write, source_dir=FIXTURES, project=None)
        self.assertEqual(rc, 0)
        self.assertEqual(captured["req"].command, "uninstall")


class DispatchRoutingTests(unittest.TestCase):
    """``_dispatch`` reuses the same command handlers (cli.DISPATCH or the module)."""

    def test_dispatch_prefers_cli_dispatch_when_present(self):
        calls = {}

        def _fake_run(request):
            calls["request"] = request
            return 7

        fake_dispatch = {"install": _fake_run}
        import agent_artifacts.cli as cli
        with mock.patch.object(cli, "DISPATCH", fake_dispatch, create=True):
            rc = tui._dispatch(Request(command="install", names=("code-review",)))
        self.assertEqual(rc, 7)
        self.assertEqual(calls["request"].command, "install")

    def test_dispatch_falls_back_to_command_module(self):
        # With no cli.DISPATCH attribute, _dispatch imports commands.<cmd>.run directly.
        import agent_artifacts.cli as cli

        recorded = {}

        def _fake_run(request):
            recorded["req"] = request
            return 0

        # Remove DISPATCH (if present) and stub the install module's run.
        with mock.patch.object(cli, "DISPATCH", None, create=True):
            import agent_artifacts.commands.install as install_mod
            with mock.patch.object(install_mod, "run", side_effect=_fake_run):
                rc = tui._dispatch(Request(command="install", names=("code-review",)))
        self.assertEqual(rc, 0)
        self.assertEqual(recorded["req"].names, ("code-review",))


class InputValidationTests(unittest.TestCase):
    """Bad numeric input re-prompts instead of crashing; selection then proceeds."""

    def test_bad_then_good_selection_reprompts(self):
        captured = {}

        def _recorder(request):
            captured["req"] = request
            return 0

        # "99" out of range, "abc" non-numeric, then "1" valid.
        read = _scripted_reader(["99", "abc", "1", "1", "install"])
        write, lines = _collector()
        with mock.patch.object(tui, "_dispatch", side_effect=_recorder):
            rc = tui._run_text(read, write, source_dir=FIXTURES, project=None)
        self.assertEqual(rc, 0)
        self.assertEqual(captured["req"].names, ("code-review",))
        # A re-prompt message was emitted.
        self.assertTrue(any("between 1 and" in ln for ln in lines))


class SourceErrorTests(unittest.TestCase):
    """A source/catalog failure is surfaced as a nonzero exit, not an exception."""

    def test_source_factory_error_returns_code(self):
        from agent_artifacts.model import Err

        def _bad_source(_request):
            return Err("boom", code=3)

        read = _scripted_reader(["1"])  # never reached
        write, lines = _collector()
        rc = tui._run_text(read, write, source_factory=_bad_source, source_dir=FIXTURES)
        self.assertEqual(rc, 3)
        self.assertTrue(any("boom" in ln for ln in lines))

    def test_empty_catalog_returns_zero(self):
        # A source whose catalog has no artifacts/bundles -> clean 0, no dispatch.
        class _EmptySource:
            def label(self):
                return "local:empty"

            def catalog(self):
                from agent_artifacts.model import Catalog
                return Ok(Catalog(artifacts={}, bundles={}))

        read = _scripted_reader(["1"])
        write, lines = _collector()
        with mock.patch.object(tui, "_dispatch") as disp:
            rc = tui._run_text(
                read, write, source_factory=lambda _r: Ok(_EmptySource())
            )
        self.assertEqual(rc, 0)
        disp.assert_not_called()
        self.assertTrue(any("No artifacts" in ln for ln in lines))


if __name__ == "__main__":
    unittest.main()
