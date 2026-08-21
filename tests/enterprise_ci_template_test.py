"""The Enterprise fork contract: every knob is a variable, and every variable is documented.

`docs/ci/enterprise-fork-v1.md` promises two things that prose alone cannot keep true.  First,
that an unconfigured fork behaves exactly like the public run, which is a claim about *defaults*.
Second, that the variable table is complete, which is a claim about the workflows.  A variable
added to a workflow and not to the page fails here, the same way
`tests/git_environment_docs_test.py` guards the Git environment page.
"""

from __future__ import annotations

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs" / "ci" / "enterprise-fork-v1.md"
TEMPLATE = ROOT / "docs" / "ci" / "templates" / "registry-quality.yml"
ACTION = ROOT / ".github" / "actions" / "aart" / "action.yml"
WORKFLOWS = (
    ROOT / ".github" / "workflows" / "validate.yml",
    ROOT / ".github" / "workflows" / "release.yml",
)
_VARIABLE = re.compile(r"vars\.(AART_[A-Z0-9_]+)")


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


class VariablesAreDocumentedTest(unittest.TestCase):
    def test_every_variable_a_workflow_reads_is_on_the_page(self) -> None:
        page = _read(PAGE)
        for path in (*WORKFLOWS, TEMPLATE):
            for name in sorted(set(_VARIABLE.findall(_read(path)))):
                self.assertIn(
                    name,
                    page,
                    f"{path.relative_to(ROOT)} reads {name}, which the fork page does not list",
                )

    def test_the_page_lists_no_variable_that_nothing_reads(self) -> None:
        used = set()
        for path in (*WORKFLOWS, TEMPLATE):
            used.update(_VARIABLE.findall(_read(path)))
        listed = set(re.findall(r"`(AART_[A-Z0-9_]+)`", _read(PAGE)))
        self.assertEqual(
            listed - used,
            set(),
            "the fork page documents a variable no workflow reads",
        )


class DefaultsReproduceThePublicRunTest(unittest.TestCase):
    """An unconfigured fork must run what this repository runs, or the template is a trap."""

    def test_runner_container_and_index_defaults(self) -> None:
        for path in WORKFLOWS:
            workflow = _read(path)
            self.assertIn("fromJSON(vars.AART_RUNNER || '[\"ubuntu-latest\"]')", workflow)
            self.assertIn("vars.AART_PIP_INDEX_URL || 'https://pypi.org/simple'", workflow)
            # An unset image must leave the job on the runner's own environment.
            self.assertIn("container: ${{ vars.AART_CI_IMAGE }}", workflow)

    def test_release_defaults_still_name_this_projects_registry_and_host(self) -> None:
        workflow = _read(WORKFLOWS[1])
        self.assertIn(
            "vars.AART_REFERENCE_REGISTRY_URL || "
            "'https://github.com/M1F1/agent-artifacts-registry.git'",
            workflow,
        )
        self.assertIn("vars.AART_GH_HOST || 'github.com'", workflow)

    def test_setup_python_is_skipped_only_when_an_image_carries_one(self) -> None:
        for path in WORKFLOWS:
            workflow = _read(path)
            self.assertIn("if: vars.AART_CI_IMAGE == ''", workflow)


class ToolNeedsNoPackagingTest(unittest.TestCase):
    """The registry gates run from a source tree.  That is the whole portability story."""

    def test_the_registry_template_installs_nothing(self) -> None:
        template = _read(TEMPLATE)
        self.assertIn("PYTHONPATH=", template)
        self.assertIn("-m agent_artifacts", template)
        self.assertNotIn("pip install", template)
        self.assertNotIn("setup-python", template)

    def test_the_template_keeps_one_marketplace_action(self) -> None:
        """`uses:` cannot be a variable, so each one is a hand edit on an instance that lacks it."""

        uses = re.findall(r"^\s*uses:\s*(\S+)", _read(TEMPLATE), re.M)
        self.assertEqual(uses, ["actions/checkout@v4"], "template grew a marketplace dependency")

    def test_both_resolvers_check_the_package_before_trusting_the_tree(self) -> None:
        for path in (TEMPLATE, ACTION):
            body = _read(path)
            self.assertIn("agent_artifacts/__main__.py", body)
            self.assertIn('echo "$bin" >> "$GITHUB_PATH"', body)

    def test_a_commit_sha_falls_back_from_the_shallow_clone(self) -> None:
        """`--depth 1 --branch` rejects a sha, and a sha is what an operator pins with."""

        for path in (TEMPLATE, ACTION):
            body = _read(path)
            self.assertIn("--depth 1 --branch", body)
            self.assertIn("checkout --quiet", body)


class RegistryGatesAreCompleteTest(unittest.TestCase):
    def test_the_template_runs_every_registry_gate(self) -> None:
        template = _read(TEMPLATE)
        for gate in (
            "aart registry format --source . --check",
            "aart registry validate --source . --strict --frozen",
            "aart registry lock --source . --check",
            "aart registry build --source . --check",
            "aart registry audit --source .",
            "aart registry test --source . --compatibility",
        ):
            self.assertIn(gate, template)

    def test_both_compatibility_ends_are_exercised(self) -> None:
        self.assertIn("compatibility: [minimum, latest]", _read(TEMPLATE))


if __name__ == "__main__":
    unittest.main()
