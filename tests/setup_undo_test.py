"""RR-4: the undo review predicts what the real rollback does.

`plan_undo` is a projection of `_rollback_receipt`. A projection that drifts from what it
projects is worse than none, because the operator approves the projection and the machine
executes the original. The first test here runs the real `rollback_record` against a fake
runtime and requires the prediction to agree, module by module.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from agent_artifacts.model import SetupStateRecord
from agent_artifacts.setup_runtime import SetupRuntime, rollback_record
from agent_artifacts.setup_undo import KEEPS, REVERSES, plan_undo, undo_payload

BLOCK = "# >>> aart setup: mcp/x@claude >>>\nexport A=1\n# <<< aart setup: mcp/x@claude <<<"


class _Completed:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _runtime(returncode: int = 0) -> SetupRuntime:
    return SetupRuntime(
        process=lambda *_args, **_kwargs: _Completed(returncode),
        platform="darwin",
        environ={"PATH": "/usr/bin:/bin"},
        clock=lambda: "2026-08-15T00:00:00Z",
    )


def _record(*steps) -> SetupStateRecord:
    return SetupStateRecord(
        artifact_type="mcp",
        artifact_name="x",
        profile="claude",
        scope="project",
        status="configured",
        detail="done",
        plan_hash="a" * 64,
        receipt=tuple(steps),
    )


class UndoReviewMatchesTheRollbackTest(unittest.TestCase):
    """Every module, predicted and then actually rolled back with a runtime that always succeeds."""

    def test_the_prediction_agrees_with_what_the_rollback_reports(self) -> None:
        cases = (
            (
                "keychain created",
                {
                    "module": "macos-keychain.store@1",
                    "step_id": "k",
                    "service": "s",
                    "account": "a",
                    "created": True,
                    "replaced": False,
                },
                REVERSES,
                True,
            ),
            (
                "keychain replaced",
                {
                    "module": "macos-keychain.store@1",
                    "step_id": "k",
                    "service": "s",
                    "account": "a",
                    "created": False,
                    "replaced": True,
                },
                KEEPS,
                False,
            ),
            (
                "keychain stored nothing",
                {
                    "module": "macos-keychain.store@1",
                    "step_id": "k",
                    "service": "s",
                    "account": "a",
                    "created": False,
                    "replaced": False,
                },
                KEEPS,
                True,
            ),
            (
                "docker tag this run built",
                {"module": "docker.build@1", "step_id": "b", "tag": "t", "preexisting": False},
                REVERSES,
                True,
            ),
            (
                "docker tag that predates the run",
                {"module": "docker.build@1", "step_id": "b", "tag": "t", "preexisting": True},
                KEEPS,
                True,
            ),
            (
                "image this run pulled",
                {"module": "docker.pull@1", "step_id": "p", "image": "i", "preexisting": False},
                KEEPS,
                False,
            ),
            (
                "image that predates the run",
                {"module": "docker.pull@1", "step_id": "p", "image": "i", "preexisting": True},
                KEEPS,
                True,
            ),
            (
                "restart notice",
                {"module": "restart.notice@1", "step_id": "r", "message": "restart"},
                KEEPS,
                True,
            ),
            (
                "custom install without a rollback phase",
                {"module": "custom.install@1", "step_id": "c", "reversible": False},
                KEEPS,
                False,
            ),
        )

        for name, receipt, expected_disposition, expected_complete in cases:
            with self.subTest(name):
                record = _record(receipt)

                predicted = plan_undo(record)[0]
                rolled = rollback_record(record, _runtime())

                self.assertEqual(predicted.disposition, expected_disposition)
                complete = rolled.status == "skipped"
                self.assertEqual(complete, expected_complete, rolled.detail)
                # The prediction's whole job: a step the review says is kept must not be the
                # reason the rollback reports success, and one it says is reversed must not fail.
                if predicted.disposition == REVERSES:
                    self.assertTrue(complete, f"{name} was predicted reversible and was not")


class UndoReviewContentTest(unittest.TestCase):
    def test_a_managed_block_in_a_file_the_run_created_says_the_file_goes(self) -> None:
        record = _record(
            {
                "module": "shell.env-from-keychain@1",
                "step_id": "s",
                "path": "/home/u/.zshrc",
                "marker": "mcp/x@claude",
                "installed_block": BLOCK,
                "changed": True,
                "file_existed": False,
            }
        )

        step = plan_undo(record)[0]

        self.assertEqual(step.disposition, REVERSES)
        self.assertIn("removes the file this run created", step.reason)

    def test_laf58_is_named_in_the_review_rather_than_discovered_afterwards(self) -> None:
        record = _record(
            {"module": "docker.build@1", "step_id": "b", "tag": "t:1", "preexisting": True}
        )

        step = plan_undo(record)[0]

        self.assertEqual(step.disposition, KEEPS)
        self.assertIn("LAF-58", step.reason)
        self.assertIn("cannot restore the original binding", step.reason)

    def test_a_pulled_image_warns_that_the_undo_will_report_incomplete(self) -> None:
        # Otherwise an operator reads `rollback_incomplete` afterwards and thinks it broke.
        record = _record(
            {"module": "docker.pull@1", "step_id": "p", "image": "i@sha256:x", "preexisting": False}
        )

        step = plan_undo(record)[0]

        self.assertIn("rollback_incomplete", step.reason)

    def test_the_review_is_in_the_order_the_rollback_runs(self) -> None:
        record = _record(
            {"module": "docker.build@1", "step_id": "first", "tag": "t", "preexisting": False},
            {"module": "restart.notice@1", "step_id": "last", "message": "m"},
        )

        steps = plan_undo(record)

        self.assertEqual([step.index for step in steps], [2, 1])

    def test_the_payload_counts_both_dispositions(self) -> None:
        record = _record(
            {"module": "docker.build@1", "step_id": "b", "tag": "t", "preexisting": False},
            {"module": "restart.notice@1", "step_id": "r", "message": "m"},
        )

        payload = undo_payload(
            plan_undo(record), coordinate="registry-a/mcp/x", profile="claude", scope="project"
        )

        self.assertEqual((payload["reverses"], payload["keeps"]), (1, 1))
        self.assertEqual(len(payload["steps"]), 2)


class UndoActuallyReversesTest(unittest.TestCase):
    """One end-to-end reversal on real files, since the review is only a promise."""

    def test_a_managed_block_is_restored_to_what_the_file_held_before(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "shellrc")
            with open(path, "w", encoding="utf-8") as stream:
                stream.write(f"before\n{BLOCK}\nafter\n")
            record = _record(
                {
                    "module": "file.managed-block@1",
                    "step_id": "s",
                    "path": path,
                    "marker": "mcp/x@claude",
                    "installed_block": BLOCK,
                    "changed": True,
                    "file_existed": True,
                    "mode": 0o600,
                }
            )

            rolled = rollback_record(record, _runtime())

            with open(path, "r", encoding="utf-8") as stream:
                content = stream.read()
            self.assertEqual(rolled.status, "skipped")
            self.assertNotIn("aart setup", content)
            self.assertIn("before", content)
            self.assertIn("after", content)
            self.assertEqual(rolled.receipt, ())
