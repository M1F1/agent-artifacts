"""SBC-5: what a consumer is actually shown before consenting to a build.

The recipe is the guided route and never the only route: every setup-bearing package ships a
package-root `SETUP.md`, and the review renders that manual alternative *before* consent. Two
consequences this file holds. An effect that fell through to the generic "Run a reviewed setup
effect" would be a review that understates executing a Dockerfile with network access. And a
capability that reached policy as nothing at all would let an organization that forbids container
execution approve one without noticing.
"""

from __future__ import annotations

import unittest

from agent_artifacts.model import SetupInstaller, SetupQueueItem
from agent_artifacts.setup import (
    parse_installer,
    plan_setup,
    project_setup_review,
    render_setup_review,
)
from agent_artifacts.setup_engine.application import _planned_capabilities
from tests.setup_fixtures import recipe

_STEPS = [
    {
        "id": "ca",
        "use": "trust-store.export-certificates@1",
        "with": {"subject_contains": "Example Corp Root", "output": "company-ca.pem"},
    },
    {
        "id": "image",
        "use": "docker.build@1",
        "with": {"context": "payload", "dockerfile": "Dockerfile"},
    },
    {
        "id": "token",
        "use": "macos-keychain.store@1",
        "with": {"input": "api_token", "service": "aart/mcp/atlassian", "account": "default"},
    },
    {
        "id": "restart",
        "use": "restart.notice@1",
        "with": {"message": "Restart the harness to pick up the new server."},
    },
]


def acceptance_installer() -> SetupInstaller:
    raw = recipe(
        required_tools=["docker", "/usr/bin/security"],
        capabilities=["docker", "network", "process", "trust-store", "keychain"],
        steps=_STEPS,
    )
    outcome = parse_installer(
        raw,
        artifact_key="mcp/atlassian",
        descriptor_path="mcp/atlassian/setup/installer.json",
    )
    assert hasattr(outcome, "value"), getattr(outcome, "reason", "")
    return outcome.value


def acceptance_plan():
    item = SetupQueueItem(
        artifact_type="mcp",
        artifact_name="atlassian",
        profile="claude",
        scope="user",
        source_label="pin:abc",
        source_root="/registry",
        installer=acceptance_installer(),
        artifact_version="1.4.0",
    )
    return plan_setup(item, target_root="/home", platform="darwin")


class TheReviewNamesEveryEffectTest(unittest.TestCase):
    def test_no_effect_falls_through_to_the_generic_identity(self) -> None:
        for effect in project_setup_review(acceptance_plan()).effects:
            with self.subTest(effect=effect.index):
                self.assertNotEqual(effect.identity, "Run a reviewed setup effect")

    def test_the_new_modules_say_more_than_that_nothing_runs(self) -> None:
        """A restart notice truly runs nothing; a build and an export must not claim the same."""

        by_identity = {
            effect.identity: effect for effect in project_setup_review(acceptance_plan()).effects
        }
        generic = "no additional automated command"
        self.assertEqual(by_identity["Show a restart notice"].details, generic)
        self.assertNotEqual(
            by_identity["Build a local Docker image from this package"].details, generic
        )
        self.assertNotEqual(
            by_identity["Export certificates into the build context"].details, generic
        )

    def test_the_rendered_review_names_the_tag_and_the_tools(self) -> None:
        rendered = "\n".join(render_setup_review(acceptance_plan()))
        self.assertIn("aart/mcp/atlassian:1.4.0", rendered)
        self.assertIn("docker, /usr/bin/security", rendered)
        self.assertIn("Build a local Docker image from this package", rendered)
        self.assertIn("Export certificates into the build context", rendered)

    def test_the_rendered_review_names_both_new_capabilities(self) -> None:
        rendered = "\n".join(render_setup_review(acceptance_plan()))
        self.assertIn("trust-store", rendered)
        self.assertIn("docker", rendered)

    def test_the_manual_route_is_offered_before_any_effect_is_listed(self) -> None:
        rendered = render_setup_review(acceptance_plan())
        self.assertIn("Manual alternative", rendered)
        self.assertIn("Effects", rendered)
        self.assertLess(rendered.index("Manual alternative"), rendered.index("Effects"))
        self.assertIn("mcp/atlassian/SETUP.md", "\n".join(rendered[: rendered.index("Effects")]))

    def test_recovery_is_claimed_only_where_it_is_true(self) -> None:
        by_identity = {
            effect.identity: effect for effect in project_setup_review(acceptance_plan()).effects
        }
        owned = "removes only changes created by this run"
        self.assertEqual(
            by_identity["Build a local Docker image from this package"].recovery, owned
        )
        self.assertEqual(by_identity["Export certificates into the build context"].recovery, owned)


class ThePolicyCanSeeABuildTest(unittest.TestCase):
    """A capability that reached policy as nothing at all could not be denied by anyone."""

    def test_a_build_declares_what_it_actually_does(self) -> None:
        planned = {str(item) for item in _planned_capabilities(acceptance_installer())}
        self.assertIn("docker-build", planned)
        self.assertIn("network", planned)
        self.assertIn("process", planned)

    def test_reading_the_trust_store_is_declared_apart_from_the_keychain(self) -> None:
        planned = {str(item) for item in _planned_capabilities(acceptance_installer())}
        self.assertIn("trust-store", planned)
        self.assertIn("keychain", planned)

    def test_a_recipe_without_a_build_declares_neither(self) -> None:
        outcome = parse_installer(
            recipe(),
            artifact_key="mcp/atlassian",
            descriptor_path="mcp/atlassian/setup/installer.json",
        )
        planned = {str(item) for item in _planned_capabilities(outcome.value)}
        self.assertNotIn("docker-build", planned)
        self.assertNotIn("trust-store", planned)


if __name__ == "__main__":
    unittest.main()
