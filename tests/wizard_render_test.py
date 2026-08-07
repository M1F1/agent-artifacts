"""Issue #21: accessible, narrow-safe pure wizard rendering."""

from __future__ import annotations

import unittest

from agent_artifacts.wizard import (
    BasketItem,
    advance,
    onboarding_lines,
    reconcile_basket,
    render_header,
    render_stepper,
    select,
)


class WizardOnboardingTests(unittest.TestCase):
    def test_curses_onboarding_names_actual_navigation_controls(self):
        rendered = "\n".join(onboarding_lines("curses"))

        self.assertIn("How aart TUI works", rendered)
        self.assertIn("Up / Down", rendered)
        self.assertIn("Space", rendered)
        self.assertIn("Enter", rendered)
        self.assertIn("Backspace", rendered)
        self.assertIn("q", rendered)

    def test_text_onboarding_explains_back_and_multi_select(self):
        rendered = "\n".join(onboarding_lines("text"))

        self.assertIn("b / back", rendered)
        self.assertIn("comma-separated", rendered)
        self.assertIn("Press Enter to start", rendered)


class WizardStepperTests(unittest.TestCase):
    def session_at_scope(self):
        from agent_artifacts.wizard import initial_session

        session = initial_session()
        session = advance(session)
        session = select(session, "role", "user")
        session = advance(session)
        session = select(session, "profiles", ("claude",))
        session = advance(session)
        session = select(session, "action", "install")
        return advance(session)

    def test_stepper_distinguishes_confirmed_current_and_future_without_color(self):
        session = self.session_at_scope()
        rendered = "\n".join(render_stepper(session, width=120))

        self.assertIn("[x] How it works", rendered)
        self.assertIn("[x] Role", rendered)
        self.assertIn("[x] Harness", rendered)
        self.assertIn("[x] Action", rendered)
        self.assertIn("[●] Scope", rendered)
        self.assertIn("[ ] Review", rendered)

    def test_stepper_wraps_whole_tokens_within_narrow_width(self):
        lines = render_stepper(self.session_at_scope(), width=28)

        self.assertGreater(len(lines), 1)
        self.assertTrue(all(len(line) <= 28 for line in lines))
        self.assertTrue(all(not line.startswith(" ->") for line in lines))

    def test_header_shows_stage_hint_basket_and_visible_invalidation_reason(self):
        session = self.session_at_scope()
        session = select(
            session,
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

        self.assertIn("Scope", rendered)
        self.assertIn("Basket: 1 selected", rendered)
        self.assertIn("mcp/postgres", rendered)
        self.assertIn("unsupported by selected", rendered)
        self.assertIn("scope", rendered)
        self.assertIn("b / back", rendered)
        self.assertTrue(all(len(line) <= 50 for line in rendered.splitlines()))


if __name__ == "__main__":
    unittest.main()
