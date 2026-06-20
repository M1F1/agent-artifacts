"""WP-19 tests: CLI wiring (argparse -> Request -> dispatch -> exit code).

Pure wiring tests: every command's ``run`` is replaced by a recorder so we assert (a) the
right handler is dispatched, (b) flags map onto the right :class:`Request` fields, and (c) the
handler's return value becomes the process exit code. argparse usage/help/version behaviour is
checked against its standard ``SystemExit`` codes.

Run: ``python -m unittest discover -s tests -p "cli_test.py" -v``
"""

import contextlib
import io
import sys
import types
import unittest
from unittest.mock import patch

from agent_artifacts import cli
from agent_artifacts.model import Request


class _TTYBuffer(io.StringIO):
    """A capture buffer that reports itself as a TTY (to drive the bare->TUI branch)."""

    def isatty(self) -> bool:  # noqa: D401
        return True


def _recorder(code: int = 0):
    """A fake command ``run`` that records the Request it received and returns ``code``."""
    calls = []

    def run(request: Request) -> int:
        calls.append(request)
        return code

    run.calls = calls  # type: ignore[attr-defined]
    return run


def _dispatch(argv, *, command, code=0):
    """Run ``cli.main(argv)`` with ``command``'s handler stubbed; return (rc, captured Request)."""
    rec = _recorder(code)
    with patch.dict(cli.DISPATCH, {command: rec}):
        rc = cli.main(argv)
    req = rec.calls[0] if rec.calls else None  # type: ignore[attr-defined]
    return rc, req


class TestStaticWiring(unittest.TestCase):
    """The dispatch table and parser agree on exactly the §13 command surface."""

    EXPECTED = {"list", "install", "status", "check", "update", "uninstall", "upgrade"}

    def test_dispatch_keys(self):
        self.assertEqual(set(cli.DISPATCH), self.EXPECTED)

    def test_dispatch_points_at_real_run_functions(self):
        from agent_artifacts.commands import check, install, status, uninstall, update, upgrade
        from agent_artifacts.commands import list as list_cmd
        self.assertIs(cli.DISPATCH["list"], list_cmd.run)
        self.assertIs(cli.DISPATCH["install"], install.run)
        self.assertIs(cli.DISPATCH["status"], status.run)
        self.assertIs(cli.DISPATCH["check"], check.run)
        self.assertIs(cli.DISPATCH["update"], update.run)
        self.assertIs(cli.DISPATCH["uninstall"], uninstall.run)
        self.assertIs(cli.DISPATCH["upgrade"], upgrade.run)

    def test_parser_subcommands_match_dispatch(self):
        parser = cli.build_parser()
        import argparse
        sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
        self.assertEqual(set(sub.choices), self.EXPECTED)


class TestExitCodePropagation(unittest.TestCase):
    """The handler's int return becomes the CLI's exit code, untouched."""

    def test_ok(self):
        rc, _ = _dispatch(["status"], command="status", code=0)
        self.assertEqual(rc, 0)

    def test_conflict_code_propagates(self):
        rc, _ = _dispatch(["install", "x", "--profile", "claude"], command="install", code=4)
        self.assertEqual(rc, 4)

    def test_corrupt_manifest_code_propagates(self):
        rc, _ = _dispatch(["status"], command="status", code=5)
        self.assertEqual(rc, 5)


class TestRequestMapping(unittest.TestCase):
    """Flags land on the correct Request fields per subcommand."""

    def test_install_full(self):
        argv = [
            "install", "code-review", "second",
            "--bundle", "base", "--bundle", "backend",
            "--profile", "claude,opencode", "--profile", "tabnine",
            "--all", "--version", "v1.2",
            "--source", "/src", "--repo", "o/r", "--project", "/proj",
            "--dry-run", "--yes", "--force", "--json",
        ]
        rc, req = _dispatch(argv, command="install")
        self.assertEqual(rc, 0)
        self.assertEqual(req.command, "install")
        self.assertEqual(req.names, ("code-review", "second"))
        self.assertEqual(req.bundles, ("base", "backend"))
        self.assertEqual(req.profiles, ("claude", "opencode", "tabnine"))
        self.assertTrue(req.all)
        self.assertEqual(req.version, "v1.2")
        self.assertEqual(req.source_dir, "/src")
        self.assertEqual(req.repo, "o/r")
        self.assertEqual(req.project, "/proj")
        self.assertTrue(req.dry_run and req.yes and req.force and req.json)

    def test_install_defaults(self):
        rc, req = _dispatch(["install", "--profile", "claude"], command="install")
        self.assertEqual(rc, 0)
        self.assertEqual(req.names, ())
        self.assertEqual(req.bundles, ())
        self.assertEqual(req.profiles, ("claude",))
        self.assertFalse(req.all or req.dry_run or req.yes or req.force or req.json)
        self.assertIsNone(req.version)
        self.assertIsNone(req.source_dir)
        self.assertIsNone(req.type_filter)

    def test_list_type_and_filters(self):
        rc, req = _dispatch(
            ["list", "--type", "skill", "--bundle", "base", "--version", "main", "--json"],
            command="list",
        )
        self.assertEqual(rc, 0)
        self.assertEqual(req.type_filter, "skill")
        self.assertEqual(req.bundles, ("base",))
        self.assertEqual(req.version, "main")
        self.assertTrue(req.json)

    def test_update_names_and_prune(self):
        rc, req = _dispatch(
            ["update", "code-review", "--profile", "claude", "--prune", "--force", "--json"],
            command="update",
        )
        self.assertEqual(rc, 0)
        self.assertEqual(req.names, ("code-review",))
        self.assertEqual(req.profiles, ("claude",))
        self.assertTrue(req.prune and req.force and req.json)

    def test_uninstall_all_and_profile(self):
        rc, req = _dispatch(
            ["uninstall", "--all", "--profile", "claude", "--dry-run"],
            command="uninstall",
        )
        self.assertEqual(rc, 0)
        self.assertTrue(req.all and req.dry_run)
        self.assertEqual(req.profiles, ("claude",))

    def test_check_version(self):
        rc, req = _dispatch(["check", "--version", "main", "--json"], command="check")
        self.assertEqual(rc, 0)
        self.assertEqual(req.version, "main")
        self.assertTrue(req.json)

    def test_upgrade_dry_run(self):
        rc, req = _dispatch(["upgrade", "--version", "main", "--dry-run"], command="upgrade")
        self.assertEqual(rc, 0)
        self.assertEqual(req.version, "main")
        self.assertTrue(req.dry_run)

    def test_status_minimal(self):
        rc, req = _dispatch(["status", "--json"], command="status")
        self.assertEqual(rc, 0)
        self.assertEqual(req.command, "status")
        self.assertTrue(req.json)


class TestProfileSplitting(unittest.TestCase):
    """--profile accepts comma-separated and/or repeated values."""

    def test_comma(self):
        _, req = _dispatch(["install", "--profile", "a,b"], command="install")
        self.assertEqual(req.profiles, ("a", "b"))

    def test_repeated(self):
        _, req = _dispatch(["install", "--profile", "a", "--profile", "b"], command="install")
        self.assertEqual(req.profiles, ("a", "b"))

    def test_mixed_with_whitespace(self):
        _, req = _dispatch(["install", "--profile", " a , b ", "--profile", "c"],
                           command="install")
        self.assertEqual(req.profiles, ("a", "b", "c"))


class TestUsageErrors(unittest.TestCase):
    """argparse maps bad invocations to SystemExit(2) == _common.USAGE."""

    def _exit_code(self, argv):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                cli.main(argv)
        return ctx.exception.code

    def test_unknown_command(self):
        self.assertEqual(self._exit_code(["frobnicate"]), 2)

    def test_invalid_type_choice(self):
        self.assertEqual(self._exit_code(["list", "--type", "bogus"]), 2)

    def test_unknown_flag(self):
        self.assertEqual(self._exit_code(["status", "--nope"]), 2)


class TestHelpAndVersion(unittest.TestCase):
    def test_help_exits_zero(self):
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                cli.main(["--help"])
        self.assertEqual(ctx.exception.code, 0)

    def test_version_exits_zero(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit) as ctx:
                cli.main(["--version"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertIn("agent-artifacts", buf.getvalue())


class TestBareInvocation(unittest.TestCase):
    """No subcommand: help when not a TTY; TUI when a TTY and the module exists."""

    def test_non_tty_prints_help(self):
        buf = io.StringIO()  # StringIO.isatty() is False -> help path
        with contextlib.redirect_stdout(buf):
            rc = cli.main([])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("usage", out.lower())
        self.assertIn("install", out)

    def test_tty_launches_tui(self):
        fake_tui = types.ModuleType("agent_artifacts.tui")
        fake_tui.run = lambda: 7  # type: ignore[attr-defined]
        with patch.dict(sys.modules, {"agent_artifacts.tui": fake_tui}), \
             patch.object(sys.stdin, "isatty", return_value=True), \
             patch.object(sys.stdout, "isatty", return_value=True):
            rc = cli.main([])
        self.assertEqual(rc, 7)

    def test_tty_without_tui_falls_back_to_help(self):
        # TTY in/out but no agent_artifacts.tui -> ImportError -> help, rc 0.
        buf = _TTYBuffer()  # reports isatty() True so the TUI branch is entered
        with patch.dict(sys.modules, {"agent_artifacts.tui": None}), \
             patch.object(sys.stdin, "isatty", return_value=True), \
             contextlib.redirect_stdout(buf):
            rc = cli.main([])
        self.assertEqual(rc, 0)
        self.assertIn("usage", buf.getvalue().lower())


if __name__ == "__main__":
    unittest.main()
