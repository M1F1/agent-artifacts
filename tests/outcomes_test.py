"""Pure action-outcome aggregation and rendering contracts for issue #17."""

from __future__ import annotations

import unittest

from agent_artifacts.outcomes import (
    ActionSummary,
    OutcomeItem,
    render_summary,
    summary_to_dict,
)


class OutcomeAggregationTest(unittest.TestCase):
    def test_counts_and_changed_are_derived_from_items(self):
        summary = ActionSummary(
            action="update",
            selected=5,
            items=(
                OutcomeItem("skill/a@claude", "changed"),
                OutcomeItem("skill/b@claude", "up_to_date"),
                OutcomeItem("skill/c@claude", "up_to_date"),
                OutcomeItem("skill/d@claude", "skipped", detail="incompatible"),
                OutcomeItem("skill/e@claude", "failed", detail="permission denied"),
            ),
        )

        payload = summary_to_dict(summary)

        self.assertEqual(payload["selected"], 5)
        self.assertEqual(payload["changed"], 1)
        self.assertFalse(payload["no_changes"])
        self.assertEqual(
            payload["counts"],
            {"changed": 1, "up_to_date": 2, "skipped": 1, "failed": 1},
        )
        self.assertEqual(
            [item["key"] for item in payload["items"]],
            [
                "skill/a@claude",
                "skill/b@claude",
                "skill/c@claude",
                "skill/d@claude",
                "skill/e@claude",
            ],
        )

    def test_update_noop_is_distinct_from_empty_selection(self):
        current = ActionSummary(
            action="update",
            selected=5,
            items=tuple(OutcomeItem(f"skill/{n}@claude", "up_to_date") for n in "abcde"),
        )
        empty = ActionSummary(action="update", selected=0)

        self.assertEqual(
            render_summary(current)[0],
            "Updated 0 artifacts; all 5 selected artifacts are already up to date.",
        )
        self.assertEqual(
            render_summary(empty)[0],
            "No installed artifacts matched the selected harness and filters.",
        )

    def test_install_items_carry_actual_modes_in_human_and_json(self):
        summary = ActionSummary(
            action="install",
            selected=2,
            items=(
                OutcomeItem(
                    "skill/a@claude",
                    "installed",
                    artifact="a",
                    artifact_type="skill",
                    profile="claude",
                    mode="symlink",
                ),
                OutcomeItem(
                    "mcp/b@claude",
                    "reinstalled",
                    artifact="b",
                    artifact_type="mcp",
                    profile="claude",
                    mode="copy",
                ),
            ),
        )

        payload = summary_to_dict(summary)
        lines = render_summary(summary)

        self.assertEqual(payload["changed"], 2)
        self.assertEqual(payload["modes"], {"symlink": 1, "copy": 1})
        self.assertEqual([item["mode"] for item in payload["items"]], ["symlink", "copy"])
        self.assertIn("Modes: 1 copied, 1 symlinked.", lines)
        self.assertTrue(any("mode=symlink" in line for line in lines))
        self.assertTrue(any("mode=copy" in line for line in lines))

    def test_warnings_and_recovery_follow_the_summary(self):
        summary = ActionSummary(
            action="uninstall",
            selected=1,
            items=(
                OutcomeItem("memory/team@claude", "removed", detail="managed block removed"),
                OutcomeItem("CLAUDE.md", "preserved", detail="user content preserved"),
            ),
            warnings=("managed config was already absent",),
            recovery=("Restore from CLAUDE.md.agent-artifacts-bak if needed.",),
        )

        lines = render_summary(summary)

        self.assertEqual(lines[0], "Removed 1 artifact; 1 manifest entry removed.")
        self.assertIn("warning: managed config was already absent", lines)
        self.assertIn(
            "next: Restore from CLAUDE.md.agent-artifacts-bak if needed.",
            lines,
        )

    def test_cancelled_summary_is_explicit_and_successful(self):
        summary = ActionSummary(
            action="cancelled",
            selected=3,
            items=(OutcomeItem("selection", "cancelled"),),
        )

        payload = summary_to_dict(summary)

        self.assertEqual(render_summary(summary)[0], "Cancelled; no changes were made.")
        self.assertEqual(payload["changed"], 0)
        self.assertTrue(payload["no_changes"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
