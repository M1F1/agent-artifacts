"""SBC-3: `trust-store.export-certificates@1` — a certificate is not a credential.

A corporate root CA is public by nature: it is what the interception proxy presents to every machine
on the network. Routing it through the recipe's secret machinery would prompt a human for something
they neither have nor can type, and secret inputs may only be interpolated by the Keychain module
anyway. So this is its own narrow module with its own capability — `trust-store`, not `keychain` —
because a review that called reading the public certificate list "credential-store access" would
teach maintainers to discount the word.
"""

from __future__ import annotations

import os
import shutil
import unittest

from agent_artifacts.model import SetupQueueItem
from agent_artifacts.setup import parse_installer, plan_setup, project_setup_review
from agent_artifacts.setup_runtime import ProcessResult, SetupRuntime, apply_setup_plan
from tests.setup_fixtures import recipe

_EXPORT_STEP = {
    "id": "ca",
    "use": "trust-store.export-certificates@1",
    "with": {"subject_contains": "Example Corp Root", "output": "company-ca.pem"},
}
_BUILD_STEP = {
    "id": "image",
    "use": "docker.build@1",
    "with": {"context": "payload", "dockerfile": "Dockerfile"},
}
_CERTIFICATE = "-----BEGIN CERTIFICATE-----\nQUFB\n-----END CERTIFICATE-----\n"


def ca_recipe(**changes: object) -> bytes:
    value: dict[str, object] = {
        "required_tools": ["docker", "/usr/bin/security"],
        "capabilities": ["docker", "network", "process", "trust-store"],
        "inputs": [],
        "steps": [_EXPORT_STEP, _BUILD_STEP],
    }
    value.update(changes)
    return recipe(**value)


def parsed(raw: bytes):
    return parse_installer(
        raw,
        artifact_key="mcp/atlassian",
        descriptor_path="mcp/atlassian/setup/installer.json",
    )


def queue_item(raw: bytes, source_root: str) -> SetupQueueItem:
    return SetupQueueItem(
        artifact_type="mcp",
        artifact_name="atlassian",
        profile="claude",
        scope="user",
        source_label="pin:abc",
        source_root=source_root,
        installer=parsed(raw).value,
        artifact_version="1.4.0",
    )


class RecipeShapeTest(unittest.TestCase):
    def test_an_export_before_a_build_parses(self) -> None:
        self.assertTrue(hasattr(parsed(ca_recipe()), "value"))

    def test_the_capability_is_not_keychain(self) -> None:
        outcome = parsed(ca_recipe(capabilities=["docker", "network", "process", "keychain"]))
        self.assertIn("trust-store", outcome.reason)

    def test_an_export_without_a_build_is_refused(self) -> None:
        """It writes into the build context and nowhere else, so without one it has no target."""

        outcome = parsed(ca_recipe(steps=[_EXPORT_STEP]))
        self.assertIn("requires a docker.build@1 step", outcome.reason)

    def test_an_export_after_the_build_is_refused(self) -> None:
        outcome = parsed(ca_recipe(steps=[_BUILD_STEP, _EXPORT_STEP]))
        self.assertIn("must come before", outcome.reason)

    def test_an_output_escaping_the_context_is_refused(self) -> None:
        outcome = parsed(
            ca_recipe(
                steps=[
                    {
                        "id": "ca",
                        "use": "trust-store.export-certificates@1",
                        "with": {
                            "subject_contains": "Example Corp Root",
                            "output": "../company-ca.pem",
                        },
                    },
                    _BUILD_STEP,
                ]
            )
        )
        self.assertIn("inside the build context", outcome.reason)

    def test_an_export_that_does_not_require_the_security_tool_is_refused(self) -> None:
        outcome = parsed(ca_recipe(required_tools=["docker"]))
        self.assertIn("/usr/bin/security", outcome.reason)


class ReviewedExportTest(unittest.TestCase):
    def _review(self):
        return project_setup_review(
            plan_setup(queue_item(ca_recipe(), "/registry"), target_root="/home", platform="darwin")
        )

    def test_the_export_is_reported_apart_from_credential_store_access(self) -> None:
        effect = self._review().effects[0]
        self.assertEqual(effect.capability, "trust-store")
        self.assertEqual(effect.identity, "Export certificates into the build context")
        self.assertNotEqual(effect.identity, "Run a reviewed setup effect")

    def test_the_review_says_what_is_read_and_what_is_not(self) -> None:
        effect = self._review().effects[0]
        self.assertIn("/usr/bin/security", effect.details)
        self.assertIn("public certificates", effect.details)
        self.assertIn("exports no private key", effect.details)
        self.assertIn("only into the build context", effect.details)

    def test_the_capability_list_names_the_trust_store_separately(self) -> None:
        self.assertIn("trust-store", self._review().capabilities)
        self.assertNotIn("keychain", self._review().capabilities)


class _Tools:
    """Stands in for `security` and the daemon, recording what each was asked to do."""

    def __init__(self, *, bundle: str = _CERTIFICATE * 2, security_returncode: int = 0) -> None:
        self.bundle = bundle
        self.security_returncode = security_returncode
        self.security_argv: tuple[str, ...] = ()
        self.context_listing: list[str] = []

    def __call__(self, argv, *, env, cwd, timeout, capture, stdout_path=None) -> ProcessResult:
        argv = tuple(argv)
        if argv[:2] == ("/usr/bin/security", "find-certificate"):
            self.security_argv = argv
            assert stdout_path is not None, "a bundle must be written, not captured as a message"
            with open(stdout_path, "w", encoding="utf-8") as stream:
                stream.write(self.bundle)
            return ProcessResult(self.security_returncode, stderr="security failed")
        if argv[:3] == ("docker", "image", "inspect") and "--format" not in argv:
            return ProcessResult(1)
        if argv[:3] == ("docker", "image", "inspect"):
            return ProcessResult(0, stdout="sha256:feedface\n")
        if argv[:2] == ("docker", "build"):
            assert cwd is not None
            self.context_listing = sorted(os.listdir(cwd))
            return ProcessResult(0)
        raise AssertionError(f"unexpected argv: {argv}")


class AppliedExportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = os.path.join(
            os.path.realpath(os.environ.get("TMPDIR", "/tmp")),
            f"aart-sbc3-{os.getpid()}-{id(self)}",
        )
        self.payload = os.path.join(self.workspace, "registry", "mcp", "atlassian", "payload")
        os.makedirs(self.payload)
        for name, body in (
            ("Dockerfile", "FROM python:3.11-slim\nCOPY . /app\n"),
            ("requirements.txt", "requests==2.32.3\n"),
        ):
            with open(os.path.join(self.payload, name), "w", encoding="utf-8") as stream:
                stream.write(body)
        self.home = os.path.join(self.workspace, "home")
        os.makedirs(self.home)
        self.addCleanup(shutil.rmtree, self.workspace, ignore_errors=True)

    def _plan(self, raw: bytes | None = None):
        item = queue_item(raw or ca_recipe(), os.path.join(self.workspace, "registry"))
        return plan_setup(item, target_root=self.home, platform="darwin", run_root=self.home)

    def _runtime(self, tools: _Tools) -> SetupRuntime:
        return SetupRuntime(
            process=tools,
            platform="darwin",
            environ={"PATH": "/usr/local/bin:/usr/bin:/bin"},
            tool_exists=lambda _tool: True,
            clock=lambda: "2026-01-01T00:00:00Z",
        )

    def test_the_bundle_reaches_the_build_and_never_the_package(self) -> None:
        tools = _Tools()
        record = apply_setup_plan(self._plan(), self._runtime(tools), consent=lambda _e: True)
        self.assertEqual(record.status, "configured")
        self.assertEqual(
            tools.context_listing, ["Dockerfile", "company-ca.pem", "requirements.txt"]
        )
        self.assertEqual(sorted(os.listdir(self.payload)), ["Dockerfile", "requirements.txt"])

    def test_the_substring_is_the_only_filter_and_it_is_the_tools_own(self) -> None:
        tools = _Tools()
        apply_setup_plan(self._plan(), self._runtime(tools), consent=lambda _e: True)
        self.assertEqual(
            tools.security_argv,
            ("/usr/bin/security", "find-certificate", "-a", "-c", "Example Corp Root", "-p"),
        )

    def test_the_receipt_counts_what_was_exported(self) -> None:
        record = apply_setup_plan(self._plan(), self._runtime(_Tools()), consent=lambda _e: True)
        receipt = record.receipt[0]
        self.assertEqual(receipt["certificates"], 2)
        self.assertEqual(receipt["output"], "company-ca.pem")
        self.assertEqual(receipt["subject_contains"], "Example Corp Root")

    def test_matching_nothing_fails_and_names_the_substring(self) -> None:
        """`security` exits 0 on no match, so an empty bundle has to be caught here."""

        record = apply_setup_plan(
            self._plan(), self._runtime(_Tools(bundle="")), consent=lambda _e: True
        )
        self.assertEqual(record.status, "apply_failed_rolled_back")
        self.assertIn("Example Corp Root", record.detail)

    def test_a_failing_export_leaves_no_half_written_bundle(self) -> None:
        record = apply_setup_plan(
            self._plan(),
            self._runtime(_Tools(bundle="garbage", security_returncode=1)),
            consent=lambda _e: True,
        )
        self.assertEqual(record.status, "apply_failed_rolled_back")
        self.assertEqual(os.listdir(os.path.join(self.home, ".agent-artifacts", "setup-runs")), [])

    def test_the_export_will_not_overwrite_a_file_the_package_ships(self) -> None:
        with open(os.path.join(self.payload, "company-ca.pem"), "w", encoding="utf-8") as stream:
            stream.write("shipped by the maintainer\n")
        record = apply_setup_plan(self._plan(), self._runtime(_Tools()), consent=lambda _e: True)
        self.assertEqual(record.status, "apply_failed_rolled_back")
        self.assertIn("overwrite a package file", record.detail)

    def test_nothing_outside_the_run_directory_is_written(self) -> None:
        before = sorted(os.listdir(self.home))
        apply_setup_plan(self._plan(), self._runtime(_Tools()), consent=lambda _e: True)
        self.assertEqual(sorted(os.listdir(self.home)), sorted(set(before) | {".agent-artifacts"}))
        self.assertEqual(os.listdir(os.path.join(self.home, ".agent-artifacts", "setup-runs")), [])


if __name__ == "__main__":
    unittest.main()
