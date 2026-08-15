"""`RS-12`: a docker step runs with the environment Docker needs to know who the user is.

A setup run passes a deliberately small environment to every process it starts. Docker was in that
environment with no `HOME` and no `DOCKER_CONFIG`, which means no `config.json`, which means every
pull is anonymous. A public image still arrives, so nothing looks wrong until the first private
base image — and then the failure is an authentication error the run did not explain, because the
pull path raised a fixed string and dropped the transcript that said `denied`.

The widening is confined to the two docker adapters on purpose. `curl`, `security` and a recipe's
own verification command keep the environment they had: `HOME` there buys nothing and hands each of
them the user's dotfiles.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from agent_artifacts.model import SetupQueueItem, SetupStateRecord
from agent_artifacts.setup import parse_installer, plan_setup
from agent_artifacts.setup_runtime import (
    ProcessResult,
    SetupRuntime,
    apply_setup_plan,
    rollback_record,
)
from tests.setup_fixtures import recipe

_IMAGE = "registry.example/tool@sha256:" + "a" * 64


def pull_recipe() -> bytes:
    return recipe(
        required_tools=["docker"],
        capabilities=["docker", "network", "process"],
        inputs=[],
        steps=[
            {
                "id": "image",
                "use": "docker.pull@1",
                "with": {"image": _IMAGE, "official_url": "https://example.test/tool"},
            }
        ],
    )


def plan_for(raw: bytes, home: str):
    parsed = parse_installer(
        raw,
        artifact_key="mcp/atlassian",
        descriptor_path="mcp/atlassian/setup/installer.json",
    ).value
    item = SetupQueueItem("mcp", "atlassian", "tabnine", "project", "pin:abc", "/source", parsed)
    return plan_setup(item, target_root=home, platform="darwin")


class RecordingProcess:
    """Records the environment each call was given, which is the thing under test here."""

    def __init__(self, *, pull_stderr: str = "", pull_returncode: int = 0):
        self.calls: list[tuple[tuple[str, ...], dict[str, str]]] = []
        self.pull_stderr = pull_stderr
        self.pull_returncode = pull_returncode

    def __call__(self, argv, *, env, cwd, timeout, capture):
        args = tuple(argv)
        self.calls.append((args, dict(env)))
        if args[:3] == ("docker", "image", "inspect"):
            return ProcessResult(1)
        if args[:2] == ("docker", "pull"):
            return ProcessResult(self.pull_returncode, "", self.pull_stderr)
        if "find-generic-password" in args:
            return ProcessResult(44)
        return ProcessResult(0)

    def env_for(self, prefix: tuple[str, ...]) -> dict[str, str]:
        return next(env for args, env in self.calls if args[: len(prefix)] == prefix)


class DockerCredentialEnvironmentTests(unittest.TestCase):
    def test_rs12_a_pull_carries_the_docker_config_derived_from_home(self):
        process = RecordingProcess()
        with tempfile.TemporaryDirectory() as home:
            runtime = SetupRuntime(
                process=process,
                platform="darwin",
                environ={"HOME": home, "PATH": "/usr/local/bin:/usr/bin"},
            )

            result = apply_setup_plan(
                plan_for(pull_recipe(), home), runtime, consent=lambda _e: True
            )

            self.assertEqual(result.status, "configured")
            env = process.env_for(("docker", "pull"))
            self.assertEqual(env["DOCKER_CONFIG"], os.path.join(home, ".docker"))
            self.assertEqual(env["HOME"], home)

    def test_rs12_an_explicit_docker_config_is_not_overwritten_by_the_derived_one(self):
        process = RecordingProcess()
        with tempfile.TemporaryDirectory() as home:
            elsewhere = os.path.join(home, "config", "docker")
            runtime = SetupRuntime(
                process=process,
                platform="darwin",
                environ={"HOME": home, "DOCKER_CONFIG": elsewhere},
            )

            apply_setup_plan(plan_for(pull_recipe(), home), runtime, consent=lambda _e: True)

            self.assertEqual(process.env_for(("docker", "pull"))["DOCKER_CONFIG"], elsewhere)

    def test_rs12_an_image_inspect_is_asked_with_the_same_environment_as_the_pull(self):
        """A probe narrower than the run answers about a different machine than the one that ran."""

        process = RecordingProcess()
        with tempfile.TemporaryDirectory() as home:
            runtime = SetupRuntime(process=process, platform="darwin", environ={"HOME": home})

            apply_setup_plan(plan_for(pull_recipe(), home), runtime, consent=lambda _e: True)

            self.assertEqual(
                process.env_for(("docker", "image", "inspect")),
                process.env_for(("docker", "pull")),
            )

    def test_rs12_a_run_without_home_still_starts_and_names_no_config(self):
        """No `HOME` is a legitimate environment; it must degrade, not raise."""

        process = RecordingProcess()
        with tempfile.TemporaryDirectory() as home:
            runtime = SetupRuntime(process=process, platform="darwin", environ={})

            result = apply_setup_plan(
                plan_for(pull_recipe(), home), runtime, consent=lambda _e: True
            )

            self.assertEqual(result.status, "configured")
            env = process.env_for(("docker", "pull"))
            self.assertNotIn("DOCKER_CONFIG", env)
            self.assertNotIn("HOME", env)

    def test_rs12_the_keychain_step_is_not_given_home(self):
        """The widening is for docker. Nothing else inherits it."""

        process = RecordingProcess()
        with tempfile.TemporaryDirectory() as home:
            runtime = SetupRuntime(process=process, platform="darwin", environ={"HOME": home})

            apply_setup_plan(plan_for(recipe(), home), runtime, consent=lambda _e: True)

            env = process.env_for(("/usr/bin/security",))
            self.assertNotIn("HOME", env)
            self.assertNotIn("DOCKER_CONFIG", env)


class DockerRollbackEnvironmentTests(unittest.TestCase):
    def test_rs12_removing_a_built_tag_asks_the_daemon_that_built_it(self):
        """`DOCKER_CONFIG` carries the context, so an unequal environment is an unequal daemon."""

        from agent_artifacts.setup_runtime import _docker_env, _minimal_env

        with tempfile.TemporaryDirectory() as home:
            runtime = SetupRuntime(
                process=RecordingProcess(),
                platform="darwin",
                environ={
                    "HOME": home,
                    "DOCKER_CONFIG": os.path.join(home, "elsewhere"),
                },
            )

            self.assertNotEqual(_docker_env(runtime), _minimal_env(runtime))
            self.assertEqual(
                _rollback_env_for_a_built_tag(runtime),
                _docker_env(runtime),
            )


def _rollback_env_for_a_built_tag(runtime: SetupRuntime) -> dict[str, str]:
    """Drive the real rollback for `docker.build@1` and hand back the environment it used."""

    seen: list[dict[str, str]] = []

    def record(argv, *, env, cwd, timeout, capture):
        seen.append(dict(env))
        return ProcessResult(0)

    driven = SetupRuntime(process=record, platform=runtime.platform, environ=runtime.environ)
    rollback_record(
        SetupStateRecord(
            artifact_type="mcp",
            artifact_name="atlassian",
            profile="claude",
            scope="project",
            status="configured",
            detail="done",
            plan_hash="a" * 64,
            receipt=(
                {
                    "module": "docker.build@1",
                    "step_id": "image",
                    "tag": "t:1",
                    "preexisting": False,
                },
            ),
        ),
        driven,
    )
    return seen[0]


class DockerPullFailureTests(unittest.TestCase):
    def test_rs12_a_failed_pull_reports_what_docker_said(self):
        """`denied: requested access to the resource is denied` is the whole answer to *why*."""

        denial = "Error response from daemon: pull access denied for registry.example/tool"
        process = RecordingProcess(pull_returncode=1, pull_stderr=denial)
        with tempfile.TemporaryDirectory() as home:
            runtime = SetupRuntime(process=process, platform="darwin", environ={"HOME": home})

            result = apply_setup_plan(
                plan_for(pull_recipe(), home), runtime, consent=lambda _e: True
            )

            self.assertEqual(result.status, "apply_failed_rolled_back")
            self.assertIn("pull access denied", result.detail)


if __name__ == "__main__":
    unittest.main()
