"""SBC-2: `docker.build@1` — an image built from the package, locally, owned only if created.

`docker.pull@1` names bytes fetched from elsewhere and can demand an immutable digest for them. A
build has no digest before it runs, and two machines building one context get two image ids, so the
invariant does not transfer. What transfers is the other half: the *inputs* are pinned, so the
receipt records the digest of the context that was built from, and the tag is derived from identity
and version rather than authored — predictable enough for a descriptor to name, unambiguous enough
for rollback to know what it may remove.
"""

from __future__ import annotations

import json
import os
import shutil
import unittest

from agent_artifacts.model import SetupQueueItem
from agent_artifacts.setup import parse_installer, plan_setup, project_setup_review
from agent_artifacts.setup_runtime import ProcessResult, SetupRuntime, apply_setup_plan
from tests.setup_fixtures import recipe

_BUILD_STEP = {
    "id": "image",
    "use": "docker.build@1",
    "with": {"context": "payload", "dockerfile": "Dockerfile"},
}


def build_recipe(**changes: object) -> bytes:
    value = {
        "required_tools": ["docker"],
        "capabilities": ["docker", "network", "process"],
        "inputs": [],
        "steps": [_BUILD_STEP],
    }
    value.update(changes)
    return recipe(**value)


def parsed(raw: bytes):
    return parse_installer(
        raw,
        artifact_key="mcp/atlassian",
        descriptor_path="mcp/atlassian/setup/installer.json",
    )


def queue_item(raw: bytes, source_root: str, *, version: str = "1.4.0") -> SetupQueueItem:
    installer = parsed(raw)
    assert not hasattr(installer, "reason"), getattr(installer, "reason", "")
    return SetupQueueItem(
        artifact_type="mcp",
        artifact_name="atlassian",
        profile="claude",
        scope="user",
        source_label="pin:abc",
        source_root=source_root,
        installer=installer.value,
        artifact_version=version,
    )


class RecipeShapeTest(unittest.TestCase):
    def test_a_build_step_parses(self) -> None:
        self.assertTrue(hasattr(parsed(build_recipe()), "value"))

    def test_a_recipe_declared_tag_is_refused(self) -> None:
        """The tag is derived; an author who names one is told the field does not exist."""

        outcome = parsed(
            build_recipe(
                steps=[
                    {
                        "id": "image",
                        "use": "docker.build@1",
                        "with": {"context": "payload", "tag": "company-atlassian-mcp:latest"},
                    }
                ]
            )
        )
        self.assertIn("unknown field(s): tag", outcome.reason)

    def test_a_context_outside_the_package_is_refused(self) -> None:
        outcome = parsed(
            build_recipe(
                steps=[
                    {"id": "image", "use": "docker.build@1", "with": {"context": "../elsewhere"}}
                ]
            )
        )
        self.assertIn("image", outcome.reason)
        self.assertIn("directly below the package root", outcome.reason)

    def test_a_dockerfile_escaping_the_context_is_refused(self) -> None:
        outcome = parsed(
            build_recipe(
                steps=[
                    {
                        "id": "image",
                        "use": "docker.build@1",
                        "with": {"context": "payload", "dockerfile": "../Dockerfile"},
                    }
                ]
            )
        )
        self.assertIn("inside the build context", outcome.reason)

    def test_a_build_without_network_or_process_capability_is_refused(self) -> None:
        outcome = parsed(build_recipe(capabilities=["docker"]))
        self.assertIn("network", outcome.reason)

    def test_a_build_that_does_not_require_the_docker_tool_is_refused(self) -> None:
        """Missing `docker` must surface as a missing prerequisite, before consent, not mid-run."""

        outcome = parsed(build_recipe(required_tools=["/usr/bin/security"]))
        self.assertIn("required_tools", outcome.reason)

    def test_two_build_steps_are_refused(self) -> None:
        second = dict(_BUILD_STEP, id="image_two")
        outcome = parsed(build_recipe(steps=[_BUILD_STEP, second]))
        self.assertIn("at most one docker.build@1", outcome.reason)


class PlannedBuildTest(unittest.TestCase):
    def test_the_tag_is_derived_from_identity_and_version(self) -> None:
        plan = plan_setup(
            queue_item(build_recipe(), "/registry"), target_root="/home", platform="darwin"
        )
        effect = plan.effects[0]
        self.assertEqual(effect.target, "aart/mcp/atlassian:1.4.0")
        self.assertEqual(
            effect.argv,
            ("docker", "build", "--tag", "aart/mcp/atlassian:1.4.0", "--file", "Dockerfile", "."),
        )

    def test_the_context_is_resolved_against_the_package_at_plan_time(self) -> None:
        plan = plan_setup(
            queue_item(build_recipe(), "/registry"), target_root="/home", platform="darwin"
        )
        self.assertEqual(
            plan.effects[0].config["context_source"],
            os.path.join("/registry", "mcp", "atlassian", "payload"),
        )

    def test_a_record_without_a_version_cannot_be_planned(self) -> None:
        plan = plan_setup(
            queue_item(build_recipe(), "/registry", version=""),
            target_root="/home",
            platform="darwin",
        )
        self.assertEqual(plan.preflight_status, "prerequisite_missing")
        self.assertEqual(plan.effects, ())
        self.assertIn("artifact version", plan.preflight_detail)

    def test_the_review_names_the_tag_the_tool_and_what_a_build_runs(self) -> None:
        review = project_setup_review(
            plan_setup(
                queue_item(build_recipe(), "/registry"), target_root="/home", platform="darwin"
            )
        )
        effect = review.effects[0]
        self.assertEqual(effect.identity, "Build a local Docker image from this package")
        self.assertNotEqual(effect.identity, "Run a reviewed setup effect")
        self.assertEqual(effect.target, "aart/mcp/atlassian:1.4.0")
        self.assertIn("required tool: docker", effect.details)
        self.assertIn("runs the instructions in Dockerfile", effect.details)
        self.assertIn("network access", effect.details)
        self.assertIn("stays on this machine", effect.details)


class _Docker:
    """A recording stand-in for the daemon, so a build can be observed without running one."""

    def __init__(self, *, preexisting: bool = False, build_returncode: int = 0) -> None:
        self.preexisting = preexisting
        self.build_returncode = build_returncode
        self.calls: list[tuple[tuple[str, ...], str | None]] = []
        self.context_listing: list[str] = []
        self.removed: list[str] = []

    def __call__(self, argv, *, env, cwd, timeout, capture) -> ProcessResult:
        argv = tuple(argv)
        self.calls.append((argv, cwd))
        if argv[:3] == ("docker", "image", "inspect") and "--format" not in argv:
            return ProcessResult(0 if self.preexisting else 1)
        if argv[:3] == ("docker", "image", "inspect"):
            return ProcessResult(0, stdout="sha256:feedface\n")
        if argv[:2] == ("docker", "build"):
            assert cwd is not None
            self.context_listing = sorted(os.listdir(cwd))
            return ProcessResult(self.build_returncode, stderr="RUN pip install failed")
        if argv[:3] == ("docker", "image", "rm"):
            self.removed.append(argv[3])
            return ProcessResult(0)
        raise AssertionError(f"unexpected argv: {argv}")


class AppliedBuildTest(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = os.path.join(
            os.path.realpath(os.environ.get("TMPDIR", "/tmp")),
            f"aart-sbc2-{os.getpid()}-{id(self)}",
        )
        self.payload = os.path.join(self.workspace, "registry", "mcp", "atlassian", "payload")
        os.makedirs(self.payload)
        for name, body in (
            ("Dockerfile", "FROM python:3.11-slim\nCOPY . /app\n"),
            ("server.py", "print('serve')\n"),
        ):
            with open(os.path.join(self.payload, name), "w", encoding="utf-8") as stream:
                stream.write(body)
        self.home = os.path.join(self.workspace, "home")
        os.makedirs(self.home)
        self.addCleanup(shutil.rmtree, self.workspace, ignore_errors=True)

    def _plan(self):
        item = queue_item(build_recipe(), os.path.join(self.workspace, "registry"))
        return plan_setup(item, target_root=self.home, platform="darwin", run_root=self.home)

    def _runtime(self, docker: _Docker) -> SetupRuntime:
        return SetupRuntime(
            process=docker,
            platform="darwin",
            environ={"PATH": "/usr/local/bin:/usr/bin:/bin"},
            tool_exists=lambda _tool: True,
            clock=lambda: "2026-01-01T00:00:00Z",
        )

    def _runs_root(self) -> str:
        return os.path.join(self.home, ".agent-artifacts", "setup-runs")

    def test_a_build_runs_in_a_copy_of_the_package_and_records_what_it_built_from(self) -> None:
        docker = _Docker()
        record = apply_setup_plan(self._plan(), self._runtime(docker), consent=lambda _e: True)
        self.assertEqual(record.status, "configured")
        self.assertEqual(docker.context_listing, ["Dockerfile", "server.py"])
        receipt = record.receipt[0]
        self.assertEqual(receipt["tag"], "aart/mcp/atlassian:1.4.0")
        self.assertEqual(receipt["image_id"], "sha256:feedface")
        self.assertTrue(str(receipt["context_digest"]).startswith("sha256:"))
        self.assertIs(receipt["preexisting"], False)

    def test_the_working_copy_is_gone_when_the_run_ends(self) -> None:
        docker = _Docker()
        apply_setup_plan(self._plan(), self._runtime(docker), consent=lambda _e: True)
        self.assertEqual(os.listdir(self._runs_root()), [])

    def test_the_working_copy_is_gone_after_a_failed_build_too(self) -> None:
        docker = _Docker(build_returncode=1)
        record = apply_setup_plan(self._plan(), self._runtime(docker), consent=lambda _e: True)
        self.assertEqual(record.status, "apply_failed_rolled_back")
        self.assertIn("RUN pip install failed", record.detail)
        self.assertEqual(os.listdir(self._runs_root()), [])

    def test_the_package_is_unchanged_by_a_build(self) -> None:
        before = sorted(os.listdir(self.payload))
        docker = _Docker()
        apply_setup_plan(self._plan(), self._runtime(docker), consent=lambda _e: True)
        self.assertEqual(sorted(os.listdir(self.payload)), before)

    def test_declining_the_build_leaves_no_working_copy_and_calls_no_docker(self) -> None:
        docker = _Docker()
        record = apply_setup_plan(self._plan(), self._runtime(docker), consent=lambda _e: False)
        self.assertEqual(record.status, "cancelled")
        self.assertEqual(docker.calls, [])
        self.assertFalse(os.path.exists(self._runs_root()))

    def test_rollback_removes_a_tag_this_run_created(self) -> None:
        docker = _Docker()
        plan = self._plan()
        record = apply_setup_plan(plan, self._runtime(docker), consent=lambda _e: True)
        from agent_artifacts.setup_runtime import rollback_record

        rolled = rollback_record(record, self._runtime(docker))
        self.assertEqual(rolled.status, "skipped")
        self.assertEqual(docker.removed, ["aart/mcp/atlassian:1.4.0"])

    def test_rollback_leaves_a_tag_that_existed_before_the_run(self) -> None:
        docker = _Docker(preexisting=True)
        record = apply_setup_plan(self._plan(), self._runtime(docker), consent=lambda _e: True)
        from agent_artifacts.setup_runtime import rollback_record

        rolled = rollback_record(record, self._runtime(docker))
        self.assertEqual(rolled.status, "skipped")
        self.assertEqual(docker.removed, [])
        note = str(record.receipt[0]["recovery"])
        # The tag is not "left alone": `docker build --tag` moved it to the image just built.
        # What is left alone is the rollback, and the note has to say which (`AD-37`).
        self.assertIn("now points at the image this run built", note)
        self.assertIn("aart/mcp/atlassian:1.4.0", note)
        # `docker image rm <tag>` deletes the image the server runs from when the tag is its last
        # reference, so the note must never invite it.
        self.assertNotIn("remove it manually", note)
        self.assertIn("do not remove this tag", note)

    def test_a_missing_docker_tool_is_a_prerequisite_not_a_build_failure(self) -> None:
        runtime = SetupRuntime(
            process=_Docker(),
            platform="darwin",
            environ={},
            tool_exists=lambda tool: tool != "docker",
            clock=lambda: "2026-01-01T00:00:00Z",
        )
        record = apply_setup_plan(self._plan(), runtime, consent=lambda _e: True)
        self.assertEqual(record.status, "prerequisite_missing")
        self.assertIn("docker", record.detail)
        self.assertFalse(os.path.isdir(self._runs_root()))

    def test_a_receipt_is_bound_to_the_reviewed_tag(self) -> None:
        from agent_artifacts.setup import receipt_matches_plan

        plan = self._plan()
        record = apply_setup_plan(plan, self._runtime(_Docker()), consent=lambda _e: True)
        self.assertTrue(receipt_matches_plan(record.receipt[0], plan))
        forged = dict(record.receipt[0]) | {"tag": "someone-elses:latest"}
        self.assertFalse(receipt_matches_plan(forged, plan))

    def test_the_recipe_is_the_one_a_maintainer_would_write(self) -> None:
        """The acceptance artifact's build step, parsed as JSON rather than as a Python dict."""

        raw = json.loads(build_recipe())
        self.assertEqual(
            raw["steps"][0]["with"], {"context": "payload", "dockerfile": "Dockerfile"}
        )


if __name__ == "__main__":
    unittest.main()
