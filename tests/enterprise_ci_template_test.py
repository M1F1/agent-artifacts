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

from agent_artifacts.registry_commands.model import ToolOrigin
from agent_artifacts.registry_commands.templates import (
    REGISTRY_CI_WORKFLOW,
    USAGE_REPORT_DASHBOARD_WORKFLOW,
    USAGE_REPORT_VALIDATE_WORKFLOW,
    stamp_tool_origin,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs" / "ci" / "enterprise-fork-v1.md"
ACTION = ROOT / ".github" / "actions" / "aart" / "action.yml"
WORKFLOWS = (
    ROOT / ".github" / "workflows" / "validate.yml",
    ROOT / ".github" / "workflows" / "release.yml",
)
# The registry's workflow has one home: the bytes `registry init` writes.  A second copy under
# docs/ would rot, and `plan_registry_init` refuses a template whose content has drifted.
TEMPLATE_TEXT = REGISTRY_CI_WORKFLOW.decode("utf-8")
# `registry init` writes three workflows.  Portability that stops at the quality gate leaves the
# usage-reporting half reaching github.com from inside an Enterprise instance.
_SHIPPED = {
    "registry quality": REGISTRY_CI_WORKFLOW,
    "usage validate": USAGE_REPORT_VALIDATE_WORKFLOW,
    "usage dashboard": USAGE_REPORT_DASHBOARD_WORKFLOW,
}
# A registry created inside a company gets a stamped copy, not this one, and it is the stamped
# copy that has to keep every promise below.  Both forms are checked so a change that only holds
# for the shipped default cannot pass.
_STAMP = ToolOrigin(repository="platform/agent-artifacts", ref="v9.9.9")
EMITTED = {
    **{label: body.decode("utf-8") for label, body in _SHIPPED.items()},
    **{
        f"{label} (stamped)": stamp_tool_origin(body, _STAMP).decode("utf-8")
        for label, body in _SHIPPED.items()
    },
}
_VARIABLE = re.compile(r"vars\.(AART_[A-Z0-9_]+)")


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


class VariablesAreDocumentedTest(unittest.TestCase):
    def test_every_variable_a_workflow_reads_is_on_the_page(self) -> None:
        page = _read(PAGE)
        sources = [(str(path.relative_to(ROOT)), _read(path)) for path in WORKFLOWS]
        sources.extend(
            (f"registry init's {label} workflow", body) for label, body in EMITTED.items()
        )
        for label, body in sources:
            for name in sorted(set(_VARIABLE.findall(body))):
                self.assertIn(
                    name, page, f"{label} reads {name}, which the fork page does not list"
                )

    def test_the_page_lists_no_variable_that_nothing_reads(self) -> None:
        used: set[str] = set()
        for body in EMITTED.values():
            used.update(_VARIABLE.findall(body))
        for path in WORKFLOWS:
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
        template = TEMPLATE_TEXT
        self.assertIn("PYTHONPATH=", template)
        self.assertIn("-m agent_artifacts", template)
        self.assertNotIn("pip install", template)
        self.assertNotIn("setup-python", template)

    def test_the_template_keeps_one_marketplace_action(self) -> None:
        """`uses:` cannot be a variable, so each one is a hand edit on an instance that lacks it."""

        uses = re.findall(r"^\s*(?:-\s+)?uses:\s*(\S+)", TEMPLATE_TEXT, re.M)
        self.assertEqual(uses, ["actions/checkout@v4"], "template grew a marketplace dependency")

    def test_both_resolvers_check_the_package_before_trusting_the_tree(self) -> None:
        for body in (TEMPLATE_TEXT, _read(ACTION)):
            self.assertIn("agent_artifacts/__main__.py", body)
            self.assertIn('echo "$bin" >> "$GITHUB_PATH"', body)

    def test_a_commit_sha_falls_back_from_the_shallow_clone(self) -> None:
        """`--depth 1 --branch` rejects a sha, and a sha is what an operator pins with."""

        for body in (TEMPLATE_TEXT, _read(ACTION)):
            self.assertIn("--depth 1 --branch", body)
            self.assertIn("checkout --quiet", body)


class EveryEmittedWorkflowIsPortableTest(unittest.TestCase):
    """All three, not just the quality gate."""

    def test_none_of_them_installs_the_tool(self) -> None:
        for label, body in EMITTED.items():
            self.assertNotIn("pip install", body, label)
            self.assertNotIn("setup-python", body, label)
            self.assertIn("PYTHONPATH=", body, label)

    def test_none_of_them_pins_a_hosted_runner(self) -> None:
        for label, body in EMITTED.items():
            self.assertNotIn("runs-on: ubuntu-latest", body, label)
            self.assertIn("fromJSON(vars.AART_RUNNER", body, label)

    def test_gh_is_pointed_at_the_instance_the_job_runs_on(self) -> None:
        """`gh --repo owner/name` defaults to github.com, which on GHES is the wrong server."""

        for label, body in EMITTED.items():
            if "gh issue" not in body and "gh label" not in body:
                continue
            self.assertIn("GH_HOST=${GH_HOST_OVERRIDE:-${GITHUB_SERVER_URL#https://}}", body, label)

    def test_pages_deployment_can_be_switched_off(self) -> None:
        """An Enterprise instance may not offer Pages; the dashboard must still be built."""

        dashboard = EMITTED["usage dashboard"]
        self.assertIn("if: vars.AART_PAGES != 'false'", dashboard)
        self.assertIn("aart reporting aggregate", dashboard)
        # The build and the publication are separate jobs, so the gate can skip one and keep the
        # other, and so the github-pages environment belongs only to the job that deploys.
        self.assertIn("needs: aggregate", dashboard)


class RegistryGatesAreCompleteTest(unittest.TestCase):
    def test_the_template_runs_every_registry_gate(self) -> None:
        template = TEMPLATE_TEXT
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
        self.assertIn("compatibility: [minimum, latest]", TEMPLATE_TEXT)


class StampingChangesOnlyTheDefaultsTest(unittest.TestCase):
    """`registry init` rewrites two fallback literals, and nothing else about the file."""

    def test_a_stamp_adds_no_marketplace_action(self) -> None:
        stamped = EMITTED["registry quality (stamped)"]
        uses = re.findall(r"^\s*(?:-\s+)?uses:\s*(\S+)", stamped, re.M)
        self.assertEqual(uses, ["actions/checkout@v4"])

    def test_a_stamp_changes_exactly_two_lines(self) -> None:
        for label, body in _SHIPPED.items():
            before = body.decode("utf-8").splitlines()
            after = EMITTED[f"{label} (stamped)"].splitlines()
            self.assertEqual(len(before), len(after), label)
            moved = [line for old, line in zip(before, after, strict=False) if old != line]
            self.assertEqual(len(moved), 2, f"{label}: {moved}")
            self.assertTrue(all("TOOL_URL:" in line or "TOOL_REF:" in line for line in moved))


if __name__ == "__main__":
    unittest.main()
