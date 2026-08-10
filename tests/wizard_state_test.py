"""Issue #21: pure persistent wizard state and navigation rules."""

from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError

from agent_artifacts.configuration.model import (
    ConfiguredSource,
    OrganizationPolicy,
    SourceKind,
    UserConfiguration,
    default_user_configuration,
)
from agent_artifacts.domain.identifiers import SourceAlias
from agent_artifacts.domain.result import Ok
from agent_artifacts.tui_sources import build_source_stage, plan_source_management
from agent_artifacts.wizard import (
    BasketItem,
    WizardPosition,
    advance,
    back,
    can_finalize,
    initial_session,
    reconcile_basket,
    remember_position,
    request_quit,
    select,
    stages_for,
)


def source_selection():
    baseline = default_user_configuration()
    source = ConfiguredSource(
        SourceAlias("test-source"),
        SourceKind.SOURCE_LOCAL,
        "/test/source",
        None,
        True,
    )
    configuration = UserConfiguration(
        1,
        (source,),
        None,
        baseline.sync,
        baseline.reporting,
    )
    view = build_source_stage(configuration, OrganizationPolicy(1), {})
    assert isinstance(view, Ok)
    planned = plan_source_management(view.value, (source.alias,))
    assert isinstance(planned, Ok)
    return planned.value


class WizardStageGraphTests(unittest.TestCase):
    def test_initial_session_starts_at_onboarding_and_is_frozen(self):
        session = initial_session()

        self.assertEqual(session.current, "onboarding")
        self.assertEqual(stages_for(session), ("onboarding", "role"))
        with self.assertRaises(FrozenInstanceError):
            session.current = "role"  # type: ignore[misc]

    def test_user_paths_are_dynamic(self):
        base = select(select(initial_session(), "role", "user"), "profiles", ("claude",))

        install = select(base, "action", "install")
        update = select(base, "action", "update")
        uninstall = select(base, "action", "uninstall")
        status = select(base, "action", "status")

        self.assertEqual(
            stages_for(install),
            (
                "onboarding",
                "role",
                "source",
                "profiles",
                "action",
                "scope",
                "mode",
                "artifacts",
                "review",
            ),
        )
        self.assertNotIn("mode", stages_for(update))
        self.assertIn("artifacts", stages_for(update))
        self.assertNotIn("mode", stages_for(uninstall))
        self.assertNotIn("artifacts", stages_for(status))
        self.assertEqual(stages_for(status)[-1], "review")

    def test_maintainer_paths_are_dynamic(self):
        base = select(initial_session(), "role", "maintainer")

        health = select(base, "maintainer_action", "health")
        add = select(base, "maintainer_action", "add")
        import_session = select(base, "maintainer_action", "import")
        check = select(base, "maintainer_action", "check")
        user = select(base, "maintainer_action", "user")

        self.assertEqual(stages_for(health)[-2:], ("maintainer_action", "review"))
        self.assertIn("upstream_details", stages_for(add))
        self.assertIn("upstream_details", stages_for(import_session))
        self.assertIn("artifacts", stages_for(import_session))
        self.assertIn("artifacts", stages_for(check))
        self.assertIn("profiles", stages_for(user))


class WizardTransitionTests(unittest.TestCase):
    def configured_install(self):
        session = initial_session()
        session = advance(session)
        session = select(session, "role", "user")
        session = advance(session)
        session = select(session, "source", source_selection())
        session = advance(session)
        session = select(session, "profiles", ("claude",))
        session = advance(session)
        session = select(session, "action", "install")
        session = advance(session)
        session = select(session, "scope", "project")
        session = advance(session)
        session = select(session, "mode", "copy")
        session = advance(session)
        session = select(
            session,
            "artifacts",
            (BasketItem("artifact", "skill/code-review", "code-review", "Review code changes."),),
        )
        return session

    def test_back_and_forward_preserve_values_and_basket(self):
        session = self.configured_install()
        session = advance(session)
        self.assertEqual(session.current, "review")

        edited = back(session)
        self.assertEqual(edited.current, "artifacts")
        self.assertEqual(edited.profiles, ("claude",))
        self.assertEqual(edited.install_mode, "copy")
        self.assertEqual(edited.basket[0].key, "skill/code-review")

        reviewed_again = advance(edited)
        self.assertEqual(reviewed_again.current, "review")
        self.assertEqual(reviewed_again.basket, session.basket)

    def test_earlier_edit_unconfirms_downstream_without_erasing_compatible_values(self):
        session = advance(self.configured_install())
        self.assertTrue(can_finalize(session))

        changed = select(session, "scope", "user")

        self.assertEqual(changed.profiles, ("claude",))
        self.assertEqual(changed.install_mode, "copy")
        self.assertEqual(changed.basket, session.basket)
        self.assertNotIn("scope", changed.confirmed)
        self.assertNotIn("artifacts", changed.confirmed)
        self.assertFalse(can_finalize(changed))

    def test_reconciliation_removes_only_invalid_items_and_explains_them(self):
        session = self.configured_install()
        session = select(
            session,
            "artifacts",
            session.basket
            + (BasketItem("artifact", "mcp/postgres", "postgres", "Query PostgreSQL."),),
        )

        reconciled = reconcile_basket(
            session,
            {"skill/code-review": "", "mcp/postgres": "unsupported for user scope"},
        )

        self.assertEqual([item.key for item in reconciled.basket], ["skill/code-review"])
        self.assertEqual(reconciled.notices[0].value, "mcp/postgres")
        self.assertIn("unsupported", reconciled.notices[0].reason)

    def test_position_memory_clamps_non_negative_values(self):
        session = remember_position(initial_session(), "role", cursor=-3, scroll=-1)

        self.assertEqual(session.positions, (WizardPosition("role", 0, 0),))

    def test_reconciliation_clamps_artifact_cursor_to_the_new_choice_set(self):
        session = remember_position(self.configured_install(), "artifacts", cursor=9, scroll=7)

        reconciled = reconcile_basket(session, {"skill/code-review": ""})

        artifact_position = next(
            position for position in reconciled.positions if position.stage == "artifacts"
        )
        self.assertEqual((artifact_position.cursor, artifact_position.scroll), (0, 0))

    def test_finalize_requires_current_confirmed_review_and_revision(self):
        session = advance(self.configured_install())
        revision = session.revision

        self.assertTrue(can_finalize(session, revision=revision))
        self.assertFalse(can_finalize(session, revision=revision - 1))
        self.assertFalse(can_finalize(back(session), revision=revision))

    def test_quit_requires_confirmation_only_for_non_empty_basket(self):
        self.assertEqual(request_quit(initial_session()), "quit")
        self.assertEqual(request_quit(self.configured_install()), "confirm_quit")


if __name__ == "__main__":
    unittest.main()
