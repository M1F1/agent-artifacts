"""RR-10C: nothing token-shaped leaves AART except into the Keychain.

`LAF-63` was found by reading a regex, and the regex was not where the damage was — `LAF-72` was.
Two redactors existed with different rules, and the weaker one happened to sit on the path that
writes to disk. Neither finding was reachable from a test of `redact_text`, because both were
about *which* text reaches *which* exit.

So this test is written against the exits, not the call sites. It plants credential-shaped values
where a real run would encounter them, drives the real machinery, and then enumerates every
channel a value could leave by:

    1. the record held in memory after a run
    2. the persisted record, read back as raw file bytes
    3. the run directory, after the run has ended
    4. the `--json` payloads (`setup`, `receipt show`, `receipt verify`)
    5. the text those same payloads render to
    6. the review shown before anything is applied

Channels 2 and 4 are walked structurally: every string anywhere in the payload is checked, so a
field added later and forgotten fails this test without anyone remembering to extend it. That is
the property `LAF-72` needed and did not have — the persisted record grew a field the redactor on
that path did not cover, and nothing noticed for a release.

What this cannot do is prove a *recipe* does not write a secret on purpose; a recipe that echoes
its own input into a file it owns is doing what it was reviewed to do. `DESIGN-token-containment`
§4.4 records that limit.
"""

from __future__ import annotations

import json
import os
import shutil
import unittest
from typing import Any, Iterator

from agent_artifacts.model import SetupState, SetupStateRecord
from agent_artifacts.setup import (
    dump_setup_state,
    parse_installer,
    plan_setup,
    render_setup_review,
)
from agent_artifacts.setup_receipt import ReceiptLocation
from agent_artifacts.setup_render import (
    receipt_payload,
    render_receipt_payload,
    render_setup_payload,
    render_verification_payload,
)
from agent_artifacts.setup_runtime import ProcessResult, SetupRuntime, apply_setup_plan
from agent_artifacts.setup_verify import (
    VerificationProbes,
    plan_verification,
    verification_payload,
    verify_claims,
)
from tests.setup_docker_build_test import queue_item
from tests.setup_fixtures import recipe

# One planted value per shape the redactor recognises, each distinctive enough that a substring
# search cannot match it by accident. Named for where a real run would meet them.
IN_A_TRANSCRIPT = "ghp_planted16charstranscript01"
IN_A_CLONE_URL = "planted-clone-url-secret-02"
IN_AN_ASSIGNMENT = "planted-assignment-secret-03"
IN_A_QUERY_STRING = "planted-query-string-secret-04"

PLANTED = (IN_A_TRANSCRIPT, IN_A_CLONE_URL, IN_AN_ASSIGNMENT, IN_A_QUERY_STRING)

# A transcript of the kind a failing tool prints: the value arrives four different ways, and only
# one of them has a name sitting next to it.
TRANSCRIPT = (
    f"fatal: authentication failed for {IN_A_TRANSCRIPT}\n"
    f"remote: https://oauth2:{IN_A_CLONE_URL}@ghe.example.test/team/repo.git\n"
    f"COMPANY_GHE_TOKEN={IN_AN_ASSIGNMENT}\n"
    f"tried https://ghe.example.test/api/v3?access_token={IN_A_QUERY_STRING}\n"
)

BUILD_STEP = {
    "id": "image",
    "use": "docker.build@1",
    "with": {"context": "payload", "dockerfile": "Dockerfile"},
}


def _strings(value: Any) -> Iterator[str]:
    """Every string anywhere in a payload, however deeply nested.

    Structural on purpose: a channel test that lists field names only covers the fields somebody
    remembered, which is the same weakness as redacting at call sites.
    """

    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)


class _FailingDocker:
    """The daemon, refusing a build and printing a credential four ways while it does."""

    def __call__(self, argv, *, env, cwd, timeout, capture) -> ProcessResult:
        argv = tuple(argv)
        if argv[:3] == ("docker", "image", "inspect"):
            return ProcessResult(1)
        if argv[:2] == ("docker", "build"):
            return ProcessResult(1, stderr=TRANSCRIPT)
        return ProcessResult(0)


class TokenContainmentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = os.path.join(
            os.path.realpath(os.environ.get("TMPDIR", "/tmp")),
            f"aart-rr10c-{os.getpid()}-{id(self)}",
        )
        payload = os.path.join(self.workspace, "registry", "mcp", "atlassian", "payload")
        os.makedirs(payload)
        for name, body in (
            ("Dockerfile", "FROM python:3.11-slim\n"),
            ("server.py", "print('serve')\n"),
        ):
            with open(os.path.join(payload, name), "w", encoding="utf-8") as stream:
                stream.write(body)
        self.home = os.path.join(self.workspace, "home")
        os.makedirs(self.home)
        self.addCleanup(shutil.rmtree, self.workspace, ignore_errors=True)
        self.record = self._run()

    def _run(self) -> SetupStateRecord:
        raw = recipe(
            required_tools=["docker"],
            capabilities=["docker", "network", "process"],
            inputs=[],
            steps=[BUILD_STEP],
        )
        item = queue_item(raw, os.path.join(self.workspace, "registry"))
        plan = plan_setup(item, target_root=self.home, platform="darwin", run_root=self.home)
        runtime = SetupRuntime(
            process=_FailingDocker(),
            platform="darwin",
            environ={"PATH": "/usr/bin"},
            tool_exists=lambda _tool: True,
            clock=lambda: "2026-08-15T00:00:00Z",
        )
        return apply_setup_plan(plan, runtime, consent=lambda _effect: True)

    def _assert_contains_none_planted(self, text: str, channel: str) -> None:
        for planted in PLANTED:
            self.assertNotIn(planted, text, f"{channel} carried a planted credential")

    def test_the_run_reached_the_failure_this_test_is_about(self) -> None:
        """Without this, every assertion below could pass on a run that never happened."""

        self.assertEqual(self.record.status, "apply_failed_rolled_back")
        self.assertIn("authentication failed", self.record.detail)

    # Channel 1 — the record in memory.
    def test_the_record_a_run_returns_carries_no_planted_value(self) -> None:
        self._assert_contains_none_planted(self.record.detail, "record.detail")
        self._assert_contains_none_planted(json.dumps(self.record.receipt), "record.receipt")

    # Channel 2 — the persisted record, as bytes.
    def test_the_persisted_record_carries_no_planted_value_in_any_field(self) -> None:
        text = dump_setup_state(SetupState((self.record,)))

        self._assert_contains_none_planted(text, "the persisted record")
        # And structurally, so a field added later is covered without being named here.
        for value in _strings(json.loads(text)):
            self._assert_contains_none_planted(value, "a field of the persisted record")

    # Channel 3 — what the run left on disk. See `RunDirectoryChannelTest` for what it holds
    # while the run is still in flight, which is the half a post-run walk cannot see.
    def test_the_run_directory_does_not_outlive_the_run_that_made_it(self) -> None:
        runs = os.path.join(self.home, ".agent-artifacts", "setup-runs")

        self.assertTrue(os.path.isdir(runs), "the run made a working copy, so the root exists")
        self.assertEqual(os.listdir(runs), [], "a failed run removes its working copy")

    # Channel 4 — the JSON the CLI emits, and channel 5 — the text it renders.
    def test_the_setup_payload_and_its_text_carry_no_planted_value(self) -> None:
        payload = {
            "planned": [],
            "planning_failures": [],
            "configured": 0,
            "incomplete": 1,
            "items": [
                {
                    "key": "registry-a/mcp/atlassian@1.4.0#claude/user",
                    "status": self.record.status,
                    "detail": self.record.detail,
                }
            ],
        }

        for value in _strings(payload):
            self._assert_contains_none_planted(value, "the setup --json payload")
        self._assert_contains_none_planted(
            "\n".join(render_setup_payload(payload)), "the setup text output"
        )

    def test_the_receipt_payload_and_its_text_carry_no_planted_value(self) -> None:
        location = ReceiptLocation(
            coordinate="registry-a/mcp/atlassian",
            profile="claude",
            scope="user",
            setup_state_ref="setup-" + "e" * 20,
            state_path="/data/state/setup/setup-" + "e" * 20 + ".json",
        )
        payload = receipt_payload(self.record, location=location)

        for value in _strings(payload):
            self._assert_contains_none_planted(value, "the receipt show --json payload")
        self._assert_contains_none_planted(
            "\n".join(render_receipt_payload(payload)), "the receipt show text output"
        )

    def test_the_verification_payload_and_its_text_carry_no_planted_value(self) -> None:
        probes = VerificationProbes(
            image_present=lambda _image: False,
            image_id=lambda _tag: "",
            keychain_value_present=lambda *_: None,
            read_text=lambda _path: None,
            path_present=lambda _path: False,
            orphan_run_directories=lambda _plan_hash: (),
            # `LAF-73`: answering `False` is the reporting path, which is the one that renders text.
            command_accepted=lambda _command: False,
        )
        results = verify_claims(plan_verification(self.record), probes=probes)
        payload = verification_payload(results)

        for value in _strings(payload):
            self._assert_contains_none_planted(value, "the receipt verify --json payload")
        self._assert_contains_none_planted(
            "\n".join(render_verification_payload(payload)), "the receipt verify text output"
        )

    # Channel 6 — the review, which is the one output an operator reads before consenting.
    def test_the_review_carries_no_planted_value(self) -> None:
        raw = recipe(
            required_tools=["docker"],
            capabilities=["docker", "network", "process"],
            inputs=[],
            steps=[BUILD_STEP],
            purpose=f"Configure access using COMPANY_GHE_TOKEN={IN_AN_ASSIGNMENT}.",
        )
        item = queue_item(raw, os.path.join(self.workspace, "registry"))
        plan = plan_setup(item, target_root=self.home, platform="darwin", run_root=self.home)

        text = "\n".join(render_setup_review(plan))

        self.assertIn("Configure access", text, "the review must still say what it is for")
        self._assert_contains_none_planted(text, "the setup review")


class RunDirectoryChannelTest(unittest.TestCase):
    """What the working copy holds *while* the run is in flight.

    A walk after the run proves only that the directory was removed. The question this answers is
    the one an operator on a shared machine asks: for the seconds that directory exists, mode 0700
    or not, is a credential sitting in it? The custom protocol is the case with the most surface —
    AART copies a script in, composes an argv, hands over an environment, and reads a result file
    back out — so the snapshot is taken from inside the process call, when everything is there.
    """

    ENV_SECRET = "planted-inherited-env-secret-05"

    def setUp(self) -> None:
        self.workspace = os.path.join(
            os.path.realpath(os.environ.get("TMPDIR", "/tmp")),
            f"aart-rr10c-run-{os.getpid()}-{id(self)}",
        )
        setup_dir = os.path.join(self.workspace, "registry", "mcp", "atlassian", "setup")
        os.makedirs(setup_dir)
        self.script = os.path.join(setup_dir, "install.sh")
        with open(self.script, "wb") as stream:
            stream.write(b"#!/bin/sh\nexit 0\n")
        os.chmod(self.script, 0o700)
        self.home = os.path.join(self.workspace, "home")
        os.makedirs(self.home)
        self.addCleanup(shutil.rmtree, self.workspace, ignore_errors=True)

        self.snapshots: list[tuple[str, str]] = []
        self.argvs: list[tuple[str, ...]] = []
        self.envs: list[dict] = []
        self._apply()

    def _snapshot(self, root: str) -> None:
        for directory, _subdirs, names in os.walk(root):
            for name in names:
                path = os.path.join(directory, name)
                with open(path, "rb") as stream:
                    self.snapshots.append((path, stream.read().decode("utf-8", "replace")))

    def _process(self, argv, *, env, cwd, timeout, capture) -> ProcessResult:
        argv = tuple(argv)
        self.argvs.append(argv)
        self.envs.append(dict(env))
        if argv[0].endswith("install.sh"):
            phase = argv[1]
            result_path = argv[argv.index("--result") + 1]
            with open(result_path, "w", encoding="utf-8") as stream:
                json.dump(
                    {
                        "status": {"plan": "planned", "apply": "configured", "verify": "verified"}[
                            phase
                        ],
                        "detail": f"{phase} ok",
                        "reversible": True,
                    },
                    stream,
                )
            self._snapshot(os.path.dirname(argv[0]))
        return ProcessResult(0, "", "")

    def _apply(self) -> None:
        from agent_artifacts.model import SetupQueueItem

        with open(self.script, "rb") as stream:
            custom_bytes = stream.read()
        installer = parse_installer(
            recipe(
                required_tools=[],
                capabilities=["process", "custom-code"],
                inputs=[],
                steps=[{"id": "note", "use": "restart.notice@1", "with": {"message": "restart"}}],
                custom_entrypoint="install.sh",
            ),
            artifact_key="mcp/atlassian",
            descriptor_path="mcp/atlassian/setup/installer.json",
            custom_bytes=custom_bytes,
        ).value
        item = SetupQueueItem(
            "mcp",
            "atlassian",
            "claude",
            "user",
            "pin:abc",
            os.path.join(self.workspace, "registry"),
            installer,
        )
        plan = plan_setup(item, target_root=self.home, platform="darwin", run_root=self.home)
        runtime = SetupRuntime(
            process=self._process,
            platform="darwin",
            environ={"PATH": "/usr/bin", "COMPANY_GHE_TOKEN": self.ENV_SECRET},
            tool_exists=lambda _tool: True,
            clock=lambda: "2026-08-15T00:00:00Z",
        )
        self.record = apply_setup_plan(plan, runtime, consent=lambda _effect: True)

    def test_the_snapshot_saw_the_working_copy_it_is_asserting_about(self) -> None:
        # Without this the three tests below would pass on an empty list, which is the failure
        # mode `LAF-66` was: a check that answers about a place it never looked.
        self.assertEqual(self.record.status, "configured")
        self.assertTrue(self.snapshots, "nothing was observed inside the run directory")
        self.assertTrue(
            any(path.endswith("install.sh") for path, _body in self.snapshots),
            "the copied script should be one of the files observed",
        )

    def test_no_file_in_the_working_copy_carries_an_inherited_secret(self) -> None:
        for path, body in self.snapshots:
            self.assertNotIn(self.ENV_SECRET, path, path)
            self.assertNotIn(self.ENV_SECRET, body, path)

    def test_no_argv_carries_an_inherited_secret(self) -> None:
        for argv in self.argvs:
            self.assertNotIn(self.ENV_SECRET, " ".join(argv))

    def test_the_environment_handed_to_a_recipe_is_the_one_the_plan_composed(self) -> None:
        """`custom-code` runs code AART did not write, so it inherits nothing it was not given.

        The environment is the channel with no redactor in front of it — a value forwarded here
        leaves AART intact, into a process that may do anything with it.
        """

        for env in self.envs:
            self.assertNotIn("COMPANY_GHE_TOKEN", env)
            self.assertNotIn(self.ENV_SECRET, "\n".join(f"{k}={v}" for k, v in env.items()))


class RecordedTokenIsReportedTest(unittest.TestCase):
    """The other half of `RR-10F`: a record that already carries one is not silently accepted.

    Every assertion above is about text this release writes. A machine that ran `2.5.0` has records
    on disk written by the weaker redactor, and a containment story that only covers new writes
    leaves those unmentioned forever.
    """

    def test_a_record_written_by_an_older_release_is_reported_by_verify(self) -> None:
        record = SetupStateRecord(
            artifact_type="mcp",
            artifact_name="atlassian",
            profile="claude",
            scope="user",
            status="configured",
            detail=f"cloned https://oauth2:{IN_A_TRANSCRIPT}@ghe.example.test/team/repo.git",
            plan_hash="a" * 64,
        )
        probes = VerificationProbes(
            image_present=lambda _image: True,
            image_id=lambda _tag: "",
            keychain_value_present=lambda *_: True,
            read_text=lambda _path: "",
            path_present=lambda _path: True,
            orphan_run_directories=lambda _plan_hash: (),
            command_accepted=lambda _command: True,
        )

        payload = verification_payload(verify_claims(plan_verification(record), probes=probes))

        self.assertEqual(payload["false"], 1)
        for value in _strings(payload):
            self.assertNotIn(IN_A_TRANSCRIPT, value, "verify must not echo what it reports")


if __name__ == "__main__":
    unittest.main()
