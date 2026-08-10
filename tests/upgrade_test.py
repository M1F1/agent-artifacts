"""Explicit, index-free local upgrade boundary for AART 1.0."""

from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

from agent_artifacts.commands.upgrade import plan_upgrade, run
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.model import Request


class UpgradePlanningTest(unittest.TestCase):
    def test_wheel_plan_is_explicit_absolute_and_index_free(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            wheel = Path(raw, "agent_artifacts-1.0.0a1-py3-none-any.whl")
            wheel.write_bytes(b"fixture")

            result = plan_upgrade(sys.executable, wheel=str(wheel), source_checkout=None)

            self.assertIsInstance(result, Ok)
            self.assertEqual(result.value.source_kind, "wheel")
            self.assertEqual(result.value.argv[:4], (sys.executable, "-m", "pip", "install"))
            self.assertIn("--no-index", result.value.argv)
            self.assertIn("--no-deps", result.value.argv)
            self.assertNotIn("--index-url", result.value.argv)
            self.assertEqual(result.value.argv[-1], str(wheel))

    def test_editable_plan_requires_a_real_checkout_and_disables_index_access(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            checkout = Path(raw, "source")
            checkout.mkdir()
            (checkout / "agent_artifacts").mkdir()
            (checkout / "pyproject.toml").write_text("[project]\n", encoding="utf-8")

            result = plan_upgrade(
                sys.executable,
                wheel=None,
                source_checkout=str(checkout),
            )

            self.assertIsInstance(result, Ok)
            self.assertEqual(result.value.source_kind, "editable")
            self.assertIn("--editable", result.value.argv)
            self.assertIn("--no-build-isolation", result.value.argv)
            self.assertIn("--no-index", result.value.argv)
            self.assertEqual(result.value.argv[-1], str(checkout))

    def test_missing_ambiguous_and_unsafe_sources_fail_before_pip(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            wheel = Path(raw, "agent_artifacts-1.0.0a1-py3-none-any.whl")
            wheel.write_bytes(b"fixture")
            checkout = Path(raw, "source")
            checkout.mkdir()
            (checkout / "agent_artifacts").mkdir()
            (checkout / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
            linked = Path(raw, "linked.whl")
            linked.symlink_to(wheel)

            cases = (
                plan_upgrade(sys.executable, wheel=None, source_checkout=None),
                plan_upgrade(
                    sys.executable,
                    wheel=str(wheel),
                    source_checkout=str(checkout),
                ),
                plan_upgrade(sys.executable, wheel=str(linked), source_checkout=None),
                plan_upgrade(
                    sys.executable,
                    wheel=str(Path(raw, "wrong.whl")),
                    source_checkout=None,
                ),
            )

            self.assertTrue(all(isinstance(result, Err) for result in cases))


class UpgradeCommandTest(unittest.TestCase):
    def test_dry_run_quotes_paths_and_never_invokes_runner(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            wheel = Path(raw, "wheel dir", "agent_artifacts-1.0.0a1-py3-none-any.whl")
            wheel.parent.mkdir()
            wheel.write_bytes(b"fixture")
            calls: list[tuple[str, ...]] = []
            output = io.StringIO()

            with contextlib.redirect_stdout(output):
                result = run(
                    Request(command="upgrade", upgrade_wheel=str(wheel), dry_run=True),
                    runner=lambda argv: calls.append(tuple(argv)) or 0,
                )

            self.assertEqual(result, 0)
            self.assertEqual(calls, [])
            self.assertIn("'" + str(wheel) + "'", output.getvalue())
            self.assertNotIn("pypi", output.getvalue().casefold())

    def test_apply_uses_reviewed_fixed_argv_and_propagates_failure(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            wheel = Path(raw, "agent_artifacts-1.0.0a1-py3-none-any.whl")
            wheel.write_bytes(b"fixture")
            calls: list[tuple[str, ...]] = []

            result = run(
                Request(command="upgrade", upgrade_wheel=str(wheel)),
                runner=lambda argv: calls.append(tuple(argv)) or 9,
            )

            self.assertEqual(result, 1)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][-1], str(wheel))
            self.assertEqual(calls[0][0], os.path.abspath(sys.executable))


if __name__ == "__main__":
    unittest.main()
