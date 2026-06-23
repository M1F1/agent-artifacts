"""CLI wiring tests for the nested ``upstream`` maintainer command."""

import contextlib
import io
import unittest
from unittest.mock import patch

from agent_artifacts import cli
from agent_artifacts.model import Request


def _recorder(code: int = 0):
    calls = []

    def run(request: Request) -> int:
        calls.append(request)
        return code

    run.calls = calls  # type: ignore[attr-defined]
    return run


def _dispatch(argv, code=0):
    rec = _recorder(code)
    with patch.dict(cli.DISPATCH, {"upstream": rec}):
        rc = cli.main(argv)
    return rc, rec.calls[0] if rec.calls else None  # type: ignore[attr-defined]


class UpstreamCliTests(unittest.TestCase):
    def test_upstream_check_maps_request(self):
        # Pure namespace->Request mapping (maps via _to_request, bypassing cli.main's validator):
        # --all + --bundle is a now-invalid combination, exercised here only to cover field
        # mapping. The rejection itself is asserted in test_upstream_check_rejects_all_with_bundle.
        argv = [
            "upstream",
            "check",
            "--all",
            "--type",
            "skill",
            "--bundle",
            "base",
            "--source",
            "/catalog",
            "--json",
        ]
        req = cli._to_request(cli.build_parser().parse_args(argv))
        self.assertEqual(req.command, "upstream")
        self.assertEqual(req.upstream_action, "check")
        self.assertTrue(req.all)
        self.assertEqual(req.type_filter, "skill")
        self.assertEqual(req.bundles, ("base",))
        self.assertEqual(req.source_dir, "/catalog")
        self.assertTrue(req.json)

    def test_upstream_update_maps_request(self):
        rc, req = _dispatch(
            [
                "upstream",
                "update",
                "skill/code-review",
                "--bundle",
                "backend",
                "--dry-run",
                "--force",
                "--json",
            ]
        )

        self.assertEqual(rc, 0)
        self.assertEqual(req.command, "upstream")
        self.assertEqual(req.upstream_action, "update")
        self.assertEqual(req.names, ("skill/code-review",))
        self.assertEqual(req.bundles, ("backend",))
        self.assertTrue(req.dry_run)
        self.assertTrue(req.force)
        self.assertTrue(req.json)

    def test_upstream_help_exits_zero(self):
        for argv in (["upstream", "--help"], ["upstream", "check", "--help"]):
            with self.subTest(argv=argv):
                with contextlib.redirect_stdout(io.StringIO()) as out:
                    with self.assertRaises(SystemExit) as ctx:
                        cli.main(argv)

                self.assertEqual(ctx.exception.code, 0)
                self.assertIn("upstream", out.getvalue())


class UpstreamFlagRejectionTests(unittest.TestCase):
    """Issue #4: ``upstream`` operates on a catalog repo, so consumer-side globals are rejected."""

    def _reject(self, argv):
        """Run ``cli.main(argv)`` (no dispatch stub) and return (rc, stderr); never dispatches."""
        rec = _recorder()
        err = io.StringIO()
        with patch.dict(cli.DISPATCH, {"upstream": rec}), contextlib.redirect_stderr(err):
            rc = cli.main(argv)
        self.assertEqual(rec.calls, [])  # type: ignore[attr-defined]  rejected before dispatch
        return rc, err.getvalue()

    def _reject_argparse(self, argv):
        err = io.StringIO()
        with self.assertRaises(SystemExit) as cm, contextlib.redirect_stderr(err):
            cli.main(argv)
        return cm.exception.code, err.getvalue()

    def test_check_rejects_project(self):
        rc, err = self._reject_argparse(["upstream", "check", "--all", "--project", "./app"])
        self.assertEqual(rc, 2)
        self.assertIn("unrecognized arguments: --project", err)

    def test_update_rejects_project(self):
        rc, err = self._reject_argparse(["upstream", "update", "skill/x", "--project", "./app"])
        self.assertEqual(rc, 2)
        self.assertIn("unrecognized arguments: --project", err)

    def test_add_rejects_project(self):
        rc, err = self._reject_argparse(
            ["upstream", "add", "skill/x", "https://github.com/o/r", "--project", "./app"]
        )
        self.assertEqual(rc, 2)
        self.assertIn("unrecognized arguments: --project", err)

    def test_check_rejects_repo(self):
        rc, err = self._reject_argparse(["upstream", "check", "--all", "--repo", "o/r"])
        self.assertEqual(rc, 2)
        self.assertIn("unrecognized arguments: --repo", err)

    def test_check_rejects_all_with_bundle(self):
        rc, err = self._reject(["upstream", "check", "--all", "--bundle", "base"])
        self.assertEqual(rc, 2)
        self.assertIn("--all cannot be combined", err)

    def test_source_is_still_accepted(self):
        # --source names the catalog repo for upstream commands and must remain valid.
        rec = _recorder()
        with patch.dict(cli.DISPATCH, {"upstream": rec}):
            rc = cli.main(["upstream", "check", "--all", "--source", "/catalog"])
        self.assertEqual(rc, 0)
        self.assertEqual(len(rec.calls), 1)  # type: ignore[attr-defined]


if __name__ == "__main__":
    unittest.main()
