"""Issue #21: text wizard onboarding, Back, basket, Review, and Finalize."""

from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest import mock

from agent_artifacts import tui
from agent_artifacts.outcomes import ActionSummary, CommandOutcome, OutcomeItem

FIXTURES = str(pathlib.Path(__file__).resolve().parent / "fixtures")


def scripted(answers):
    values = iter(answers)

    def read(_prompt=""):
        try:
            return next(values)
        except StopIteration:
            raise EOFError from None

    return read


def outcome(request):
    return CommandOutcome(
        0,
        ActionSummary(
            action=request.command,
            selected=1,
            items=(OutcomeItem("skill/code-review@claude", "installed"),),
        ),
    )


class TextWizardTests(unittest.TestCase):
    def run_flow(self, answers):
        writes = []
        captured = []
        with tempfile.TemporaryDirectory() as project:
            with mock.patch.object(
                tui,
                "_dispatch_result",
                side_effect=lambda request: captured.append(request) or outcome(request),
            ):
                code = tui._run_text(
                    scripted(answers),
                    writes.append,
                    source_dir=FIXTURES,
                    project=project,
                )
        return code, captured, writes

    def test_onboarding_is_first_and_every_stage_has_a_stepper(self):
        # D2 moved key hints out of the header: in text mode they live in the input prompt, which
        # is not part of the written screen, so this asserts the stepper only.
        code, captured, writes = self.run_flow(["q"])

        self.assertEqual(code, 0)
        self.assertEqual(captured, [])
        rendered = "\n".join(writes)
        self.assertTrue(rendered.startswith("How aart works"))
        self.assertIn("▸ How it works", rendered)
        self.assertIn("no changes were made", rendered.lower())

    def test_review_back_restores_same_basket_and_finalize_dispatches_once(self):
        code, captured, writes = self.run_flow(
            ["", "1", "1", "install", "1", "", "1", "back", "", "y"]
        )

        self.assertEqual(code, 0)
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].names, ("code-review",))
        rendered = "\n".join(writes)
        self.assertGreaterEqual(rendered.count("▸ Review"), 2)
        self.assertIn("Basket: 1 selected", rendered)
        self.assertIn("Finalize", rendered)

    def test_back_moves_exactly_one_stage_and_preserves_profiles(self):
        code, captured, writes = self.run_flow(
            [
                "",
                "1",
                "1",
                "install",
                "1",
                "back",
                "back",
                "install",
                "1",
                "",
                "1",
                "y",
            ]
        )

        self.assertEqual(code, 0)
        self.assertEqual(captured[0].profiles, ("claude",))
        stages = [
            token[2:] for line in writes for token in line.split(" → ") if token.startswith("▸ ")
        ]
        mode_index = stages.index("Mode")
        self.assertEqual(stages[mode_index + 1 : mode_index + 3], ["Scope", "Action"])

    def test_quit_with_basket_requires_confirmation_and_no_returns_to_review(self):
        code, captured, writes = self.run_flow(
            ["", "1", "1", "install", "1", "", "1", "q", "n", "y"]
        )

        self.assertEqual(code, 0)
        self.assertEqual(len(captured), 1)
        rendered = "\n".join(writes)
        self.assertIn("Discard 1 selected basket item", rendered)
        self.assertGreaterEqual(rendered.count("▸ Review"), 2)

    def test_confirming_an_empty_selection_re_prompts_instead_of_ending_the_session(self):
        # D5 in text mode (design section 5): equivalence at the level of outcome, not gesture.
        # There is no cursor to fall back on, so an empty confirm must say so and ask again.
        code, captured, writes = self.run_flow(["", "1", "1", "install", "1", "", "", "1", "y"])

        self.assertEqual(code, 0)
        self.assertEqual(len(captured), 1)
        rendered = "\n".join(writes)
        self.assertIn("Nothing is selected yet", rendered)
        self.assertNotIn("no changes were made", rendered.lower())

    def test_status_uses_short_dynamic_path_and_finalizes_from_review(self):
        code, captured, writes = self.run_flow(["", "1", "1", "status", "1", "y"])

        self.assertEqual(code, 0)
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].command, "status")
        rendered = "\n".join(writes)
        self.assertIn("▸ Review", rendered)
        stepper_labels = {
            token[2:] for line in writes for token in line.split(" → ") if len(token) > 2
        }
        self.assertNotIn("Mode", stepper_labels)
        self.assertNotIn("Artifacts", stepper_labels)
        self.assertIn("Expected mutation: none", rendered)


if __name__ == "__main__":
    unittest.main()
