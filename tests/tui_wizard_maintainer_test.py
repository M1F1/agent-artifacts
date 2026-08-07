"""Issue #21: Maintainer paths share Review and the Finalize mutation boundary."""

from __future__ import annotations

import pathlib
import unittest
from unittest import mock

from agent_artifacts import tui

FIXTURES = str(pathlib.Path(__file__).resolve().parent / "fixtures")


def scripted(answers):
    values = iter(answers)

    def read(_prompt=""):
        try:
            return next(values)
        except StopIteration:
            raise EOFError from None

    return read


class MaintainerWizardTests(unittest.TestCase):
    def test_health_review_back_returns_one_stage_and_finalize_dispatches_once(self):
        writes = []
        captured = []
        with mock.patch.object(
            tui, "_dispatch", side_effect=lambda request: captured.append(request) or 0
        ):
            code = tui._run_text(
                scripted(["", "2", "1", "back", "1", "finalize"]),
                writes.append,
                source_dir=FIXTURES,
            )

        self.assertEqual(code, 0)
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].upstream_action, "health")
        self.assertGreaterEqual(writes.count("Stage: Review"), 2)
        self.assertIn("Stage: Maintainer action", writes)

    def test_add_quit_after_successful_preview_never_applies(self):
        writes = []
        captured = []
        with mock.patch.object(
            tui, "_dispatch", side_effect=lambda request: captured.append(request) or 0
        ):
            code = tui._run_text(
                scripted(
                    [
                        "",
                        "2",
                        "3",
                        "skill/demo",
                        "https://github.com/acme/demo/tree/main/skills/demo",
                        "",
                        "",
                        "q",
                    ]
                ),
                writes.append,
                source_dir=FIXTURES,
            )

        self.assertEqual(code, 0)
        self.assertEqual(
            [(request.upstream_action, request.dry_run) for request in captured],
            [("validate", False), ("add", True)],
        )
        self.assertIn("Preview succeeded", "\n".join(writes))
        self.assertIn("no changes were made", "\n".join(writes).lower())

    def test_add_finalize_applies_once_then_validates(self):
        captured = []
        with mock.patch.object(
            tui, "_dispatch", side_effect=lambda request: captured.append(request) or 0
        ):
            code = tui._run_text(
                scripted(
                    [
                        "",
                        "2",
                        "3",
                        "skill/demo",
                        "https://github.com/acme/demo/tree/main/skills/demo",
                        "",
                        "",
                        "y",
                    ]
                ),
                lambda _line="": None,
                source_dir=FIXTURES,
            )

        self.assertEqual(code, 0)
        self.assertEqual(
            [(request.upstream_action, request.dry_run) for request in captured],
            [
                ("validate", False),
                ("add", True),
                ("add", False),
                ("validate", False),
            ],
        )


if __name__ == "__main__":
    unittest.main()
