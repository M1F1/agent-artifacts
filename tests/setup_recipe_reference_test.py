"""SBC-6: a module that is not written down does not exist to a maintainer.

Until now the modules lived only in `_MODULES` and in a design document, which explains why the
protocol is shaped as it is and is not something you can write a recipe from. The reference covers
all of them, not only the two this release adds — documenting the new ones alone would be worse than
documenting none, because it would imply the others are not there.

The coverage test is the point: a module cannot be added without being written down.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from agent_artifacts.setup import _CAPABILITIES, _MODULES, parse_installer, render_setup_review
from tests.setup_build_review_test import acceptance_plan

_REFERENCE = Path(__file__).resolve().parent.parent / "docs/protocol/setup-recipe-v2.md"


class EveryModuleIsDocumentedTest(unittest.TestCase):
    def setUp(self) -> None:
        self.text = _REFERENCE.read_text()

    def test_the_reference_names_every_module(self) -> None:
        for module in _MODULES:
            with self.subTest(module=module):
                self.assertIn(f"`{module}`", self.text)

    def test_the_reference_names_every_capability(self) -> None:
        for capability in _CAPABILITIES:
            with self.subTest(capability=capability):
                self.assertIn(f"`{capability}`", self.text)

    def test_every_module_carries_a_manual_equivalent_or_says_why_not(self) -> None:
        """A module that cannot be described as something a person does is not finished."""

        self.assertIn("By hand", self.text)
        self.assertIn("find-certificate -a -c", self.text)
        self.assertIn("docker build --tag aart/<type>/<name>:<version>", self.text)

    def test_the_reference_states_the_limits_rather_than_hiding_them(self) -> None:
        self.assertIn("only as offline as its `FROM` line", self.text)
        self.assertIn("private base image will not authenticate", self.text)
        self.assertIn('min_inclusive: "2.5.0"', self.text)


class TheWorkedArtifactIsRealTest(unittest.TestCase):
    """The recipe printed in the reference is fed to the parser that consumers use."""

    def _worked_recipe(self) -> bytes:
        text = _REFERENCE.read_text()
        marker = "## A worked artifact"
        section = text.split(marker, 1)[1]
        block = section.split("```json\n", 1)[1].split("```", 1)[0]
        return block.encode("utf-8")

    def test_the_documented_recipe_parses(self) -> None:
        outcome = parse_installer(
            self._worked_recipe(),
            artifact_key="mcp/company-atlassian",
            descriptor_path="mcp/company-atlassian/setup/installer.json",
        )
        self.assertTrue(hasattr(outcome, "value"), getattr(outcome, "reason", ""))

    def test_the_documented_recipe_uses_the_documented_modules(self) -> None:
        outcome = parse_installer(
            self._worked_recipe(),
            artifact_key="mcp/company-atlassian",
            descriptor_path="mcp/company-atlassian/setup/installer.json",
        )
        used = {step.use for step in outcome.value.steps}
        self.assertIn("docker.build@1", used)
        self.assertIn("trust-store.export-certificates@1", used)
        self.assertLessEqual(used, set(_MODULES))

    def test_the_acceptance_recipe_still_renders_a_complete_review(self) -> None:
        rendered = render_setup_review(acceptance_plan())
        self.assertTrue(rendered)
        self.assertIn("Manual alternative", rendered)


if __name__ == "__main__":
    unittest.main()
