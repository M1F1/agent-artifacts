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

from agent_artifacts.registry_commands.templates import (
    REGISTRY_CI_WORKFLOW,
    USAGE_REPORT_DASHBOARD_WORKFLOW,
    USAGE_REPORT_VALIDATE_WORKFLOW,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs" / "ci" / "enterprise-fork-v1.md"
ACTION = ROOT / ".github" / "actions" / "aart" / "action.yml"
WORKFLOWS = (
    ROOT / ".github" / "workflows" / "validate.yml",
    ROOT / ".github" / "workflows" / "release.yml",
    ROOT / ".github" / "workflows" / "cut-release.yml",
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
EMITTED = {label: body.decode("utf-8") for label, body in _SHIPPED.items()}
_VARIABLE = re.compile(r"vars\.(AART_[A-Z0-9_]+)")


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _uncommented(text: str) -> str:
    """The settings only.  A comment naming a tool is the note explaining why it is gone."""

    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


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

    def test_the_registry_url_is_the_switch_and_carries_no_default(self) -> None:
        """One variable decides whether a release reconciles against a registry at all.

        Every other variable defaults to the public run, because an unconfigured fork should
        behave the way this repository always has.  This one cannot: a default naming a
        github.com repository reproduces nothing on an instance that cannot reach github.com --
        it guarantees a failed clone.  So the default is gone and presence is the switch, the
        same shape `AART_IMAGE_USERNAME_SECRET` already uses.

        Actions cannot tell an unset variable from an empty one, which is why a default and an
        opt-out cannot both exist here.  This repository sets the variable explicitly; clearing
        it is a real change, and the checklist says so on every run that skips.
        """

        workflow = _read(WORKFLOWS[1])
        self.assertIn("REFERENCE_REGISTRY_URL: ${{ vars.AART_REFERENCE_REGISTRY_URL }}", workflow)
        self.assertNotIn("AART_REFERENCE_REGISTRY_URL ||", workflow)
        # And no `GH_HOST` is set here any more -- checked outside the comments, which say why.
        # The wheel is attached through the REST API at `GITHUB_API_URL`, which the runner sets
        # to this instance, so there is no host to configure and none to forget.  `gh` defaulted
        # to github.com, so a fork that missed the variable uploaded to the wrong server.
        self.assertNotIn("GH_HOST", _uncommented(workflow))

        # Neither `gh` nor `curl` may come back: a real Enterprise image had neither, and the
        # attach step failed on each in turn after the wheel was already built.  The interpreter
        # is the only thing the release can assume, because every other step already needs it.
        action = _read(ROOT / ".github" / "actions" / "release" / "action.yml")
        for absent in ("gh release", "curl "):
            self.assertNotIn(absent, _uncommented(action), absent)
        self.assertIn("scripts/attach_release_asset.py", action)
        self.assertIn("if: env.REFERENCE_REGISTRY_URL != ''", action)
        self.assertIn("--without-registry", action)

    def test_setup_python_is_skipped_only_when_an_image_carries_one(self) -> None:
        """The decision still belongs to the variable; only the place it is read moved.

        The steps live in a composite action now, because two jobs that differ solely in how
        their image is pulled must not differ in what they run.  An action cannot read `vars`,
        so the job passes the answer down and the action acts on it.
        """

        for path in WORKFLOWS:
            self.assertIn("setup-python: ${{ vars.AART_CI_IMAGE == '' }}", _read(path))
        for action in ("quality", "release"):
            body = _read(ROOT / ".github" / "actions" / action / "action.yml")
            self.assertIn("if: inputs.setup-python == 'true'", body)


class ToolNeedsNoPackagingTest(unittest.TestCase):
    """The registry gates run from a source tree.  That is the whole portability story."""

    def test_the_default_arm_installs_nothing(self) -> None:
        """Unconfigured, the template still needs no packaging: it clones and sets PYTHONPATH.

        `pip` appears exactly once, inside the arm that exists to use an index, and that arm is
        unreachable unless somebody sets `AART_PACKAGE`.  So the claim this test has always made
        survives the four arms: a fork that configures nothing needs no build backend.
        """

        template = TEMPLATE_TEXT
        self.assertIn("PYTHONPATH=", template)
        self.assertIn("-m agent_artifacts", template)
        self.assertNotIn("setup-python", template)
        for name, body in _fetching_jobs(template).items():
            self.assertEqual(body.count("pip install"), 1, name)
            self.assertIn('if [ -n "$PACKAGE" ]', body.split("pip install")[0][-200:], name)

    def test_the_template_keeps_one_marketplace_action(self) -> None:
        """`uses:` cannot be a variable, so each one is a hand edit on an instance that lacks it."""

        uses = re.findall(r"^\s*(?:-\s+)?uses:\s*(\S+)", TEMPLATE_TEXT, re.M)
        self.assertEqual(
            set(uses), {"actions/checkout@v4"}, "template grew a marketplace dependency"
        )

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

    def test_none_of_them_needs_packaging_unless_asked_to(self) -> None:
        for label, body in EMITTED.items():
            self.assertNotIn("setup-python", body, label)
            self.assertIn("PYTHONPATH=", body, label)
            for name, job in _fetching_jobs(body).items():
                self.assertEqual(job.count("pip install"), 1, f"{label}: {name}")

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
        self.assertIn("vars.AART_PAGES != 'false'", dashboard)
        self.assertIn("aart reporting aggregate", dashboard)
        # The build and the publication are separate jobs, so the gate can skip one and keep the
        # other, and so the github-pages environment belongs only to the job that deploys.  It
        # waits on both shapes of the build and tolerates the one that stood down, which is what
        # `!cancelled()` buys: without it, a skipped dependency skips the dependent too.
        self.assertIn("needs: [aggregate, aggregate-private-image]", dashboard)
        self.assertIn("!cancelled() && !failure()", dashboard)
        # Deployment runs no Python and never fetches AART, so it needs no image at all.
        deploy = _job_bodies(dashboard)["deploy"]
        self.assertNotIn("container", deploy)


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


class EveryFetchArmIsReachableTest(unittest.TestCase):
    """Four ways in, and an order that has to stay the order the page documents.

    The arms are `elif`s, so one that is always set hides every arm below it.  Git carries the
    only shipped default, which is why it has to be last -- a rule that is invisible in the YAML
    and would be re-broken by anyone reordering the block for readability.
    """

    ARMS = ("PACKAGE", "WHEEL_URL", "TOOL_PATH", "TOOL_URL")

    @staticmethod
    def _chain(body: str) -> str:
        """Only the if/elif/else that selects an arm — the pin is read before it and is not one."""

        return body.split('tool="$RUNNER_TEMP/aart-tool"', 1)[1].split("\n          fi\n", 1)[0]

    def test_the_arms_are_tried_from_the_most_governed_supply_chain_to_the_least(self) -> None:
        for label, body in EMITTED.items():
            found = re.findall(r'\[ -n "\$(\w+)" \]', self._chain(body))
            self.assertEqual(tuple(found) + ("TOOL_URL",), self.ARMS, label)

    def test_the_git_arm_is_the_else_so_it_cannot_be_reordered(self) -> None:
        """The rule that keeps the other three reachable is structural, not a convention."""

        for label, body in EMITTED.items():
            chain = self._chain(body)
            self.assertIn("\n          else\n", chain, label)
            self.assertLess(chain.index('[ -n "$TOOL_PATH" ]'), chain.index("\n          else\n"))

    def test_only_the_git_arm_carries_a_default(self) -> None:
        """Every other arm must be empty unless somebody sets it, or it shadows the ones below."""

        for label, body in EMITTED.items():
            for name in ("AART_PACKAGE", "AART_WHEEL_URL", "AART_TOOL_PATH"):
                self.assertIn(f"${{{{ vars.{name} }}}}", body, label)

    def test_the_run_log_names_which_arm_answered(self) -> None:
        """A variable is not in the file, so the run is the only place the truth can appear."""

        for label, body in EMITTED.items():
            self.assertIn('echo "AART: agent-artifacts $got  via $how', body, label)

    def test_every_arm_ends_at_the_same_check(self) -> None:
        for label, body in EMITTED.items():
            for name, job in _fetching_jobs(body).items():
                self.assertEqual(
                    job.count('test -f "$tool/agent_artifacts/__main__.py"'), 1, f"{label}: {name}"
                )


class ThePinIsReadFromTheRepositoryTest(unittest.TestCase):
    """`.aart-version` decides the version; the variables only decide where to get it.

    The split is the point: a registry stood up at two companies runs the same version through
    different supply chains, so a version in a variable would have to be repeated per deployment
    and a supply chain in the repository would have to be edited per deployment.
    """

    def test_every_workflow_reads_the_pin_before_choosing_an_arm(self) -> None:
        for label, body in EMITTED.items():
            self.assertIn("if [ -f .aart-version ]; then PIN=", body, label)
            self.assertLess(body.index(".aart-version"), body.index('if [ -n "$PACKAGE" ]'), label)

    def test_the_index_and_wheel_arms_substitute_the_pin(self) -> None:
        """Otherwise a version would have to be written into a variable as well as the file."""

        for label, body in EMITTED.items():
            self.assertIn(r'requirement="${PACKAGE//\{version\}/$PIN}"', body, label)
            self.assertIn(r'url="${WHEEL_URL//\{version\}/$PIN}"', body, label)

    def test_the_git_arm_derives_its_ref_from_the_pin(self) -> None:
        for label, body in EMITTED.items():
            self.assertIn('ref="${PIN:+v$PIN}"', body, label)

    def test_no_variable_carries_a_default_ref_any_more(self) -> None:
        """`AART_REF` with a `main` default would silently outrank the pin on every run."""

        for label, body in EMITTED.items():
            self.assertIn("TOOL_REF: ${{ vars.AART_REF }}", body, label)
            self.assertNotIn("vars.AART_REF || 'main'", body, label)

    def test_the_fetched_version_is_verified_against_the_pin(self) -> None:
        """A pin that is only declared is the stamp again. This one is checked on every arm."""

        for label, body in EMITTED.items():
            self.assertIn(
                'if [ -n "$PIN" ] && [ -z "$override" ] && [ "$got" != "$PIN" ]; then', body, label
            )
            self.assertIn("exit 2", body, label)

    def test_an_override_is_announced_rather_than_silent(self) -> None:
        for label, body in EMITTED.items():
            self.assertIn("overridden by AART_REF", body, label)


def _job_bodies(workflow: str) -> dict[str, str]:
    """Split a workflow into its jobs.

    Every job that runs in a container is emitted twice, once per container shape, so a count
    taken over a whole file now says two where it means one.  The invariants are per job, and
    this is what makes them expressible that way.
    """

    jobs = workflow.split("\njobs:\n", 1)[1]
    bodies: dict[str, str] = {}
    name: str | None = None
    lines: list[str] = []
    for line in jobs.splitlines(keepends=True):
        match = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if match:
            if name is not None:
                bodies[name] = "".join(lines)
            name, lines = match.group(1), []
        elif name is not None:
            lines.append(line)
    if name is not None:
        bodies[name] = "".join(lines)
    return bodies


def _fetching_jobs(workflow: str) -> dict[str, str]:
    return {name: body for name, body in _job_bodies(workflow).items() if "Provide AART" in body}


def _steps_of(body: str) -> str:
    return body.split("    steps:\n", 1)[1] if "    steps:\n" in body else ""


class TheContainerSwitchTest(unittest.TestCase):
    """A private image needs credentials, and a credentials block cannot be conditional.

    Measured on a real instance, not reasoned about: an empty `credentials` block and a `null`
    one are both rejected before the job starts, and filling it with a placeholder makes an
    anonymous pull fail a `docker login` it never needed.  The `secrets` context is not even
    readable at `container:` itself.  So the switch lives at `if:`, the one place a choice
    survives, and every containerised job is emitted twice.  `docs/ci/enterprise-fork-v1.md`
    records the runs that established each of those facts.
    """

    SOURCES = {
        **{str(path.relative_to(ROOT)): _read(path) for path in WORKFLOWS},
        **EMITTED,
    }

    def test_every_containerised_job_comes_in_both_shapes(self) -> None:
        for label, workflow in self.SOURCES.items():
            bodies = _job_bodies(workflow)
            plain = [name for name, body in bodies.items() if "    container:" in body]
            for name in plain:
                if name.endswith("-private-image"):
                    continue
                self.assertIn(f"{name}-private-image", bodies, f"{label}: {name} has one shape")

    def test_the_two_shapes_run_the_same_steps(self) -> None:
        """The one thing duplication can break, held by a test rather than by care."""

        for label, workflow in self.SOURCES.items():
            bodies = _job_bodies(workflow)
            for name, body in bodies.items():
                if not name.endswith("-private-image"):
                    continue
                plain = bodies[name[: -len("-private-image")]]
                self.assertEqual(
                    _steps_of(plain).strip(), _steps_of(body).strip(), f"{label}: {name} drifted"
                )

    def test_the_switch_is_exclusive_so_exactly_one_shape_runs(self) -> None:
        for label, workflow in self.SOURCES.items():
            for name, body in _job_bodies(workflow).items():
                if "    container:" not in body:
                    continue
                expected = "!=" if name.endswith("-private-image") else "=="
                self.assertIn(
                    f"vars.AART_IMAGE_USERNAME_SECRET {expected} ''", body, f"{label}: {name}"
                )

    def test_the_default_shape_carries_no_credentials_block(self) -> None:
        """Naming no secrets must leave the job this project always ran, byte for byte."""

        for label, workflow in self.SOURCES.items():
            for name, body in _job_bodies(workflow).items():
                if name.endswith("-private-image"):
                    continue
                # `persist-credentials: false` on the checkout is a different key at a different
                # depth; what must be absent is the container's own block.
                self.assertNotIn("\n      credentials:\n", body, f"{label}: {name}")
                self.assertNotIn("secrets[vars.AART_IMAGE_", body, f"{label}: {name}")

    def test_the_credentialed_shape_names_both_secrets_through_variables(self) -> None:
        """A secret's *name* is not a secret, so an instance keeps its own naming."""

        for label, workflow in self.SOURCES.items():
            for name, body in _job_bodies(workflow).items():
                if not name.endswith("-private-image"):
                    continue
                where = f"{label}: {name}"
                self.assertIn(
                    "username: ${{ secrets[vars.AART_IMAGE_USERNAME_SECRET] }}", body, where
                )
                self.assertIn(
                    "password: ${{ secrets[vars.AART_IMAGE_PASSWORD_SECRET] }}", body, where
                )


class TheIndexCredentialIsAssembledNotStoredTest(unittest.TestCase):
    """A variable cannot hold a credential, so it holds the host and names the secret."""

    def test_both_halves_are_remasked_before_use(self) -> None:
        """GitHub masks the value it was given -- `user:pass` -- and neither half after a split."""

        action = _read(ROOT / ".github" / "actions" / "quality" / "action.yml")
        self.assertEqual(action.count("::add-mask::"), 2, "quality action: one half left unmasked")
        # A workflow emits its job once per container shape, so the count is taken per job.
        for label, body in EMITTED.items():
            for name, job in _fetching_jobs(body).items():
                self.assertEqual(
                    job.count("::add-mask::"), 2, f"{label}: {name}: one half left unmasked"
                )

    def test_no_log_line_carries_the_assembled_url(self) -> None:
        for label, body in EMITTED.items():
            self.assertIn('how="index $announce', body, label)
            self.assertNotIn('how="index $INDEX_URL', body, label)


if __name__ == "__main__":
    unittest.main()
