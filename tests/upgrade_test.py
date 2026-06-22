"""Tests for ``agent_artifacts.commands.upgrade`` (WP-17).

stdlib only — ``unittest`` + ``tempfile``. The injectable ``runner`` and ``opener`` ensure
no live network calls or real pip invocations happen.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from io import StringIO
from typing import List

from agent_artifacts.commands.upgrade import _upgrade
from agent_artifacts.model import Ok, Request


def _request(*, dry_run: bool = False, version: str | None = None) -> Request:
    return Request(command="upgrade", dry_run=dry_run, version=version)


class _FakeRunner:
    """Records the argv it was called with and returns a configurable exit code."""

    def __init__(self, rc: int = 0) -> None:
        self.calls: List[List[str]] = []
        self.rc = rc

    def __call__(self, argv: List[str]) -> int:
        self.calls.append(list(argv))
        return self.rc


def _never_opener(_req):
    raise AssertionError("opener must not be called in local-wheel tests")


class TestLocalWheelDryRun(unittest.TestCase):
    """Dry-run with a local wheel: prints pip argv, never calls runner or opener."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.dist_dir = os.path.join(self.tmpdir, "dist")
        os.makedirs(self.dist_dir)
        self.wheel = os.path.join(self.dist_dir, "agent_artifacts-0.1.0-py3-none-any.whl")
        with open(self.wheel, "wb") as f:
            f.write(b"fake wheel")

    def test_dry_run_prints_argv_and_does_not_run(self) -> None:
        runner = _FakeRunner()
        # Capture stdout.
        import contextlib

        buf = StringIO()
        with contextlib.redirect_stdout(buf):
            rc = _upgrade(
                _request(dry_run=True),
                runner=runner,
                opener=_never_opener,
                dist_dir=self.dist_dir,
            )
        output = buf.getvalue()

        # Exit OK.
        self.assertEqual(rc, 0)
        # Runner was NOT called (dry-run).
        self.assertEqual(len(runner.calls), 0)
        # Printed line contains the expected pip tokens.
        self.assertIn("pip", output)
        self.assertIn("install", output)
        self.assertIn("--no-index", output)
        self.assertIn("--force-reinstall", output)
        self.assertIn("agent_artifacts-0.1.0-py3-none-any.whl", output)
        # NEVER references PyPI or an index URL.
        self.assertNotIn("pypi", output.lower())
        self.assertNotIn("--index-url", output)
        self.assertNotIn("--extra-index-url", output)

    def test_opener_never_called(self) -> None:
        """With a local wheel, opener must not be invoked even on non-dry-run."""
        runner = _FakeRunner()
        import contextlib

        buf = StringIO()
        with contextlib.redirect_stdout(buf):
            rc = _upgrade(
                _request(dry_run=False),
                runner=runner,
                opener=_never_opener,
                dist_dir=self.dist_dir,
            )
        self.assertEqual(rc, 0)
        self.assertEqual(len(runner.calls), 1)


class TestLocalWheelExecute(unittest.TestCase):
    """Execute path (non-dry-run) with a local wheel: calls runner, returns correct exit code."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.dist_dir = os.path.join(self.tmpdir, "dist")
        os.makedirs(self.dist_dir)
        self.wheel = os.path.join(self.dist_dir, "agent_artifacts-0.1.0-py3-none-any.whl")
        with open(self.wheel, "wb") as f:
            f.write(b"fake wheel")

    def test_execute_success(self) -> None:
        runner = _FakeRunner(rc=0)
        import contextlib

        buf = StringIO()
        with contextlib.redirect_stdout(buf):
            rc = _upgrade(
                _request(dry_run=False),
                runner=runner,
                opener=_never_opener,
                dist_dir=self.dist_dir,
            )
        self.assertEqual(rc, 0)
        self.assertEqual(len(runner.calls), 1)

        argv = runner.calls[0]
        # Starts with sys.executable -m pip install --no-index ...
        self.assertEqual(argv[0], sys.executable)
        self.assertEqual(argv[1:5], ["-m", "pip", "install", "--no-index"])
        self.assertIn("--force-reinstall", argv)
        self.assertTrue(argv[-1].endswith(".whl"))
        # Index-free assertion.
        self.assertNotIn("--index-url", argv)
        self.assertNotIn("--extra-index-url", argv)

    def test_execute_failure(self) -> None:
        runner = _FakeRunner(rc=1)
        import contextlib

        buf = StringIO()
        with contextlib.redirect_stdout(buf):
            rc = _upgrade(
                _request(dry_run=False),
                runner=runner,
                opener=_never_opener,
                dist_dir=self.dist_dir,
            )
        # Runner failure → ERROR (1).
        self.assertEqual(rc, 1)


class TestRemotePath(unittest.TestCase):
    """Remote path (no local wheel): resolve_ref → ensure_snapshot → pip install snapshot."""

    def setUp(self) -> None:
        # Empty dist dir — forces the remote path.
        self.tmpdir = tempfile.mkdtemp()
        self.dist_dir = os.path.join(self.tmpdir, "dist")
        os.makedirs(self.dist_dir)  # exists but no wheel

    def test_remote_dry_run(self) -> None:
        """Remote dry-run: resolves ref, ensures snapshot, prints argv, does not run."""
        runner = _FakeRunner()
        fake_sha = "abc123def456"
        snapshot_dir = os.path.join(self.tmpdir, "snapshot")
        os.makedirs(snapshot_dir, exist_ok=True)

        import contextlib
        from unittest.mock import patch

        buf = StringIO()
        with (
            patch("agent_artifacts.commands.upgrade.resolve_ref", return_value=Ok(fake_sha)),
            patch("agent_artifacts.commands.upgrade.ensure_snapshot", return_value=snapshot_dir),
            patch("agent_artifacts.commands.upgrade.fetch_tarball"),
            contextlib.redirect_stdout(buf),
        ):
            rc = _upgrade(
                _request(dry_run=True),
                runner=runner,
                dist_dir=self.dist_dir,
            )

        self.assertEqual(rc, 0)
        self.assertEqual(len(runner.calls), 0)
        output = buf.getvalue()
        self.assertIn("pip", output)
        self.assertIn("--no-index", output)
        self.assertIn("--no-build-isolation", output)
        self.assertIn("--force-reinstall", output)
        self.assertIn(snapshot_dir, output)
        self.assertNotIn("pypi", output.lower())
        self.assertNotIn("--index-url", output)

    def test_remote_execute(self) -> None:
        runner = _FakeRunner(rc=0)
        fake_sha = "abc123def456"
        snapshot_dir = os.path.join(self.tmpdir, "snapshot")
        os.makedirs(snapshot_dir, exist_ok=True)

        import contextlib
        from unittest.mock import patch

        buf = StringIO()
        with (
            patch("agent_artifacts.commands.upgrade.resolve_ref", return_value=Ok(fake_sha)),
            patch("agent_artifacts.commands.upgrade.ensure_snapshot", return_value=snapshot_dir),
            patch("agent_artifacts.commands.upgrade.fetch_tarball"),
            contextlib.redirect_stdout(buf),
        ):
            rc = _upgrade(
                _request(dry_run=False),
                runner=runner,
                dist_dir=self.dist_dir,
            )

        self.assertEqual(rc, 0)
        self.assertEqual(len(runner.calls), 1)
        argv = runner.calls[0]
        self.assertEqual(argv[0], sys.executable)
        self.assertEqual(argv[1:5], ["-m", "pip", "install", "--no-index"])
        self.assertIn("--no-build-isolation", argv)
        self.assertIn("--force-reinstall", argv)
        self.assertEqual(argv[-1], snapshot_dir)

    def test_network_failure_returns_network_code(self) -> None:
        """resolve_ref returning Err → prints reason, returns NETWORK (3)."""
        from agent_artifacts.model import Err

        runner = _FakeRunner()

        import contextlib
        from unittest.mock import patch

        buf = StringIO()
        with (
            patch(
                "agent_artifacts.commands.upgrade.resolve_ref",
                return_value=Err("connection refused", code=3),
            ),
            contextlib.redirect_stdout(buf),
        ):
            rc = _upgrade(
                _request(dry_run=False),
                runner=runner,
                dist_dir=self.dist_dir,
            )

        self.assertEqual(rc, 3)
        self.assertEqual(len(runner.calls), 0)
        self.assertIn("connection refused", buf.getvalue())


class TestWheelSelection(unittest.TestCase):
    """When multiple wheels exist, the latest (sorted last) is chosen."""

    def test_picks_latest_wheel(self) -> None:
        tmpdir = tempfile.mkdtemp()
        dist_dir = os.path.join(tmpdir, "dist")
        os.makedirs(dist_dir)
        for ver in ("0.1.0", "0.2.0", "0.3.0"):
            with open(os.path.join(dist_dir, f"agent_artifacts-{ver}-py3-none-any.whl"), "wb") as f:
                f.write(b"fake")

        runner = _FakeRunner()
        import contextlib

        buf = StringIO()
        with contextlib.redirect_stdout(buf):
            rc = _upgrade(
                _request(dry_run=True),
                runner=runner,
                opener=_never_opener,
                dist_dir=dist_dir,
            )
        self.assertEqual(rc, 0)
        self.assertIn("0.3.0", buf.getvalue())


class TestRunEntryPoint(unittest.TestCase):
    """``run(request)`` delegates to ``_upgrade``."""

    def test_run_delegates(self) -> None:
        from agent_artifacts.commands.upgrade import run

        tmpdir = tempfile.mkdtemp()
        dist_dir = os.path.join(tmpdir, "dist")
        os.makedirs(dist_dir)
        with open(os.path.join(dist_dir, "agent_artifacts-1.0.0-py3-none-any.whl"), "wb") as f:
            f.write(b"fake")

        import contextlib
        from unittest.mock import patch

        buf = StringIO()
        with (
            contextlib.redirect_stdout(buf),
            patch("agent_artifacts.commands.upgrade._find_local_wheel") as mock_find,
        ):
            mock_find.return_value = os.path.join(dist_dir, "agent_artifacts-1.0.0-py3-none-any.whl")
            rc = run(_request(dry_run=True))
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
