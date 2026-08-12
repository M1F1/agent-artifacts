"""Issue #21 + WP-1: accessible, narrow-safe pure wizard rendering."""

from __future__ import annotations

import unittest

from agent_artifacts.tui_layout import (
    STAGE_CONFIRMED,
    STAGE_CURRENT,
    STAGE_PENDING,
    STAGE_PROJECTION,
)
from agent_artifacts.wizard import (
    BasketItem,
    advance,
    initial_session,
    onboarding_lines,
    projected_stages_for,
    reconcile_basket,
    render_header,
    render_stepper,
    select,
)
from tests.wizard_state_test import source_selection


def _at_role() -> object:
    return advance(initial_session())


def _at_scope():
    session = advance(initial_session())
    session = select(session, "role", "user")
    session = advance(session)
    session = select(session, "source", source_selection())
    session = advance(session)
    session = select(session, "profiles", ("claude",))
    session = advance(session)
    session = select(session, "action", "install")
    return advance(session)


class WizardOnboardingTests(unittest.TestCase):
    """D11: the status bar documents keys permanently, so onboarding stops repeating them."""

    def test_onboarding_names_no_keys(self):
        for frontend in ("curses", "text"):
            rendered = "\n".join(onboarding_lines(frontend))  # type: ignore[arg-type]
            for key in ("Up / Down", "Backspace", "b / back", "Space", "comma-separated"):
                self.assertNotIn(key, rendered, frontend)

    def test_onboarding_keeps_what_the_bar_cannot_say(self):
        rendered = "\n".join(onboarding_lines("curses"))

        self.assertIn("aart", rendered)
        self.assertIn("User", rendered)
        self.assertIn("Maintainer", rendered)
        self.assertIn("Press Enter to start", rendered)


class ProjectedStagesTests(unittest.TestCase):
    """D3: the whole path is visible from the first screen, and says when it is a guess."""

    def test_the_path_is_projected_before_the_role_fork_is_resolved(self):
        stages, projected = projected_stages_for(_at_role())

        self.assertTrue(projected)
        self.assertEqual(stages, ("onboarding", "role", "source", "profiles", "action"))

    def test_the_path_is_settled_once_every_fork_is_resolved(self):
        stages, projected = projected_stages_for(_at_scope())

        self.assertFalse(projected)
        self.assertIn("review", stages)

    def test_a_maintainer_without_an_action_is_still_a_projection(self):
        session = select(advance(initial_session()), "role", "maintainer")

        _stages, projected = projected_stages_for(session)

        self.assertTrue(projected)


class WizardStepperTests(unittest.TestCase):
    def test_stepper_distinguishes_confirmed_current_and_future_without_color(self):
        rendered = "\n".join(render_stepper(_at_scope(), width=120))

        self.assertIn(f"{STAGE_CONFIRMED} How it works", rendered)
        self.assertIn(f"{STAGE_CONFIRMED} Action", rendered)
        self.assertIn(f"{STAGE_CURRENT} Scope", rendered)
        self.assertIn(f"{STAGE_PENDING} Review", rendered)

    def test_the_whole_path_is_visible_on_the_very_first_screens(self):
        rendered = "\n".join(render_stepper(_at_role(), width=120))

        for label in ("How it works", "Role", "Sources", "Harness", "Action"):
            self.assertIn(label, rendered)

    def test_a_projected_tail_is_marked_and_a_settled_one_is_not(self):
        self.assertIn(STAGE_PROJECTION, "\n".join(render_stepper(_at_role(), width=120)))
        self.assertNotIn(STAGE_PROJECTION, "\n".join(render_stepper(_at_scope(), width=120)))

    def test_the_old_bracket_markers_are_gone(self):
        rendered = "\n".join(render_stepper(_at_scope(), width=120))

        self.assertNotIn("[x]", rendered)
        self.assertNotIn("[●]", rendered)

    def test_stepper_wraps_whole_tokens_within_narrow_width(self):
        lines = render_stepper(_at_scope(), width=28)

        self.assertGreater(len(lines), 1)
        self.assertTrue(all(len(line) <= 28 for line in lines))
        self.assertTrue(all(not line.startswith(f" {'→'}") for line in lines))


class WizardHeaderTests(unittest.TestCase):
    def test_header_keeps_basket_and_invalidation_reason(self):
        session = select(
            _at_scope(),
            "artifacts",
            (
                BasketItem("artifact", "skill/code-review", "code-review", "Review changes."),
                BasketItem("artifact", "mcp/postgres", "postgres", "Query PostgreSQL."),
            ),
        )
        session = reconcile_basket(
            session,
            {"skill/code-review": "", "mcp/postgres": "unsupported by selected scope"},
        )

        rendered = "\n".join(render_header(session, width=50, frontend="text"))

        self.assertIn("Basket: 1 selected", rendered)
        self.assertIn("mcp/postgres", rendered)
        self.assertIn("unsupported by selected", rendered)
        self.assertTrue(all(len(line) <= 50 for line in rendered.splitlines()))

    def test_header_states_the_current_stage_once_not_twice(self):
        """D4: the stepper's marker already says where you are."""

        for frontend in ("text", "curses"):
            rendered = "\n".join(render_header(_at_scope(), width=120, frontend=frontend))  # type: ignore[arg-type]
            self.assertNotIn("Stage:", rendered)
            self.assertEqual(rendered.count(f"{STAGE_CURRENT} Scope"), 1)

    def test_header_carries_no_key_hints(self):
        """D2: hints live in the pinned status bar and nowhere else."""

        for frontend in ("text", "curses"):
            rendered = "\n".join(render_header(_at_scope(), width=120, frontend=frontend))  # type: ignore[arg-type]
            for hint in ("Enter", "enter=", "Backspace", "b / back", "q / quit", "q = quit"):
                self.assertNotIn(hint, rendered, frontend)

    def test_a_stepper_too_narrow_to_show_the_current_stage_gets_a_fallback_line(self):
        rendered = "\n".join(render_header(_at_scope(), width=6, frontend="curses"))

        self.assertIn("Scope", rendered)

    def test_the_dot_is_only_ever_a_marker_never_a_separator(self):
        """D1: stages join with an arrow; `·` survives solely as the not-yet-reached bullet."""

        markers = (STAGE_CONFIRMED, STAGE_CURRENT, STAGE_PENDING)
        for line in render_stepper(_at_scope(), width=120):
            for token in line.split(" → "):
                self.assertTrue(
                    token == STAGE_PROJECTION or token.startswith(markers),
                    f"unexpected stepper token: {token!r}",
                )


if __name__ == "__main__":
    unittest.main()
