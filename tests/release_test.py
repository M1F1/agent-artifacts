from __future__ import annotations

import contextlib
import hashlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
import zipfile
from pathlib import Path
from unittest import mock

from tests.credential_fixtures import assignment
from tests.versioning_test import ROOT, _load_script

REFERENCE_ORIGIN = "https://github.com/M1F1/agent-artifacts-registry.git"
REFERENCE_COMMIT = "a" * 40


def _fixture_root(raw: str, release, *, complete: bool = True) -> Path:
    root = Path(raw)
    for relative in release.SCHEMA_INPUTS:
        source = ROOT / relative
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    # Build the fixture at the version the release contract governs, so this test keeps asserting
    # "a complete tree at the declared release version passes" rather than pinning one literal.
    version = release.EXPECTED_VERSION
    major, minor, patch = (int(part) for part in version.split("."))
    package = root / "agent_artifacts"
    package.mkdir(exist_ok=True)
    (package / "__init__.py").write_text(f'__version__ = "{version}"\n', encoding="utf-8")
    (package / "runtime_contract.py").write_text(
        "from agent_artifacts.protocol.semver import SemVer\n"
        f"EXECUTABLE_VERSION = SemVer({major}, {minor}, {patch})\n",
        encoding="utf-8",
    )
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "agent-artifacts"\nversion = "{version}"\ndependencies = []\n',
        encoding="utf-8",
    )
    state = "complete" if complete else "pending"
    (root / "PROGRESS.md").write_text(
        "## Task ledger\n\n"
        "| ID | Task | Depends on | Status | Branch | PR / merge | Gate evidence / notes |\n"
        "|---|---|---|---|---|---|---|\n"
        "| P00 | Plan | — | complete | — | — | — |\n"
        f"| REL01 | Release | all | {state} | — | — | — |\n\n"
        "## Current-task template\n",
        encoding="utf-8",
    )
    for relative in release.REQUIRED_RELEASE_DOCS:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"# AART {version}\n\nRelease evidence.\n", encoding="utf-8")
    for relative in release.REQUIRED_PERSISTENT_DOCS:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# Carried forward\n\nEarlier-boundary evidence.\n", encoding="utf-8")
    freeze = root / release.SCHEMA_FREEZE_PATH
    freeze.parent.mkdir(parents=True, exist_ok=True)
    freeze.write_bytes(release.schema_freeze_bytes(root))
    return root


def _successful_runner(command, _cwd, _environment, _timeout_seconds):
    if command[:4] == ("git", "remote", "get-url", "origin"):
        stdout = REFERENCE_ORIGIN + "\n"
    elif command == ("git", "ls-remote", "--symref", "origin", "HEAD"):
        stdout = f"ref: refs/heads/main\tHEAD\n{REFERENCE_COMMIT}\tHEAD\n"
    elif command[:2] == ("git", "rev-parse"):
        stdout = REFERENCE_COMMIT + "\n"
    else:
        stdout = ""
    return subprocess.CompletedProcess(command, 0, stdout, "")


def _unsafe_registry_runner(calls, registry, status, head, origin_head):
    def runner(command, cwd, environment, timeout_seconds):
        calls.append(command)
        if cwd == registry and command[:3] == ("git", "status", "--porcelain=v1"):
            return subprocess.CompletedProcess(command, 0, status, "")
        if cwd == registry and command[:2] == ("git", "rev-parse"):
            value = origin_head if command[-1] == "origin/HEAD" else head
            return subprocess.CompletedProcess(command, 0, value + "\n", "")
        return _successful_runner(command, cwd, environment, timeout_seconds)

    return runner


class ReleaseChecklistTest(unittest.TestCase):
    def test_complete_stable_tree_and_registry_return_deterministic_pass_receipt(self) -> None:
        release = _load_script("release")
        with tempfile.TemporaryDirectory() as raw:
            root = _fixture_root(raw, release)
            registry = root / "reference-registry"
            registry.mkdir()

            first = release.check_release(root, registry, process_runner=_successful_runner)
            second = release.check_release(root, registry, process_runner=_successful_runner)

        self.assertEqual(first, second)
        self.assertEqual(first["status"], "passed")
        self.assertEqual(first["version"], release.EXPECTED_VERSION)
        self.assertEqual(first["registry_commit"], REFERENCE_COMMIT)
        self.assertEqual(first["diagnostics"], [])
        self.assertEqual(
            tuple(item["name"] for item in first["checks"]),
            release.RELEASE_CHECKS,
        )
        self.assertTrue(all(item["passed"] for item in first["checks"]))

    def test_incomplete_progress_version_mismatch_stale_schema_and_missing_docs_accumulate(
        self,
    ) -> None:
        release = _load_script("release")
        with tempfile.TemporaryDirectory() as raw:
            root = _fixture_root(raw, release, complete=False)
            registry = root / "reference-registry"
            registry.mkdir()
            (root / "agent_artifacts/__init__.py").write_text(
                '__version__ = "1.0.0a1"\n', encoding="utf-8"
            )
            (root / release.REQUIRED_RELEASE_DOCS[1]).unlink()
            schema = root / release.SCHEMA_INPUTS[0]
            schema.write_bytes(schema.read_bytes() + b"\n# changed after freeze\n")

            receipt = release.check_release(
                root,
                registry,
                process_runner=_successful_runner,
                require_clean=False,
            )

        codes = tuple(item["code"] for item in receipt["diagnostics"])
        self.assertEqual(receipt["status"], "failed")
        self.assertIn("progress-incomplete", codes)
        self.assertIn("version-invalid", codes)
        self.assertIn("schema-freeze-stale", codes)
        self.assertIn("release-doc-missing", codes)

    def test_a_dropped_carried_forward_document_still_blocks_the_release(self) -> None:
        """Migration and tutorial guides survive a release-series bump.

        They describe an earlier boundary and so cannot be required to name the current version,
        but a release must not silently ship without the 0.1.x migration guide or the onboarding
        tutorials either.
        """

        release = _load_script("release")
        for relative in release.REQUIRED_PERSISTENT_DOCS:
            with self.subTest(document=relative), tempfile.TemporaryDirectory() as raw:
                root = _fixture_root(raw, release)
                registry = root / "reference-registry"
                registry.mkdir()
                (root / relative).unlink()

                receipt = release.check_release(root, registry, process_runner=_successful_runner)

                self.assertEqual(receipt["status"], "failed")
                self.assertIn(
                    "release-doc-missing",
                    tuple(item["code"] for item in receipt["diagnostics"]),
                )

    def test_a_carried_forward_document_need_not_name_the_current_version(self) -> None:
        release = _load_script("release")
        with tempfile.TemporaryDirectory() as raw:
            root = _fixture_root(raw, release)
            registry = root / "reference-registry"
            registry.mkdir()
            # Mentions only the earlier boundary, exactly like the real migration guide.
            (root / release.REQUIRED_PERSISTENT_DOCS[0]).write_text(
                "# Migrating from AART 0.1.x to 1.0.0\n", encoding="utf-8"
            )

            receipt = release.check_release(root, registry, process_runner=_successful_runner)

        self.assertEqual(receipt["status"], "passed")

    def test_incompatible_registry_and_stale_index_have_distinct_redacted_codes(self) -> None:
        release = _load_script("release")

        def failing_registry(command, cwd, environment, timeout_seconds):
            if command[0] == "git":
                return _successful_runner(command, cwd, environment, timeout_seconds)
            rendered = " ".join(command)
            if "registry validate" in rendered:
                return subprocess.CompletedProcess(command, 5, assignment("token", "secret"), "")
            if "registry build" in rendered:
                return subprocess.CompletedProcess(command, 5, "", assignment("password", "secret"))
            return subprocess.CompletedProcess(command, 0, "", "")

        with tempfile.TemporaryDirectory() as raw:
            root = _fixture_root(raw, release)
            registry = root / "reference-registry"
            registry.mkdir()
            receipt = release.check_release(
                root,
                registry,
                process_runner=failing_registry,
                require_clean=False,
            )

        codes = tuple(item["code"] for item in receipt["diagnostics"])
        self.assertIn("registry-incompatible", codes)
        self.assertIn("registry-index-stale", codes)
        self.assertNotIn("secret", repr(receipt))

    def test_dirty_generated_output_is_blocking_and_freeze_write_is_explicit(self) -> None:
        release = _load_script("release")

        def dirty(command, cwd, environment, timeout_seconds):
            if command[:3] == ("git", "status", "--porcelain=v1"):
                return subprocess.CompletedProcess(command, 0, " M generated.json\n", "")
            return _successful_runner(command, cwd, environment, timeout_seconds)

        with tempfile.TemporaryDirectory() as raw:
            root = _fixture_root(raw, release)
            registry = root / "reference-registry"
            registry.mkdir()
            receipt = release.check_release(root, registry, process_runner=dirty)
            freeze = root / release.SCHEMA_FREEZE_PATH
            freeze.unlink()

            self.assertEqual(release.main(("freeze",), root=root), 1)
            self.assertFalse(freeze.exists())
            self.assertEqual(release.main(("freeze", "--write"), root=root), 0)
            self.assertTrue(freeze.is_file())

        self.assertIn(
            "repository-dirty",
            tuple(item["code"] for item in receipt["diagnostics"]),
        )

    def test_post_check_source_mutation_is_blocking(self) -> None:
        release = _load_script("release")
        with tempfile.TemporaryDirectory() as raw:
            root = _fixture_root(raw, release)
            registry = root / "reference-registry"
            registry.mkdir()
            source_statuses = 0

            def mutating_runner(command, cwd, environment, timeout_seconds):
                nonlocal source_statuses
                if cwd == root and command[:3] == ("git", "status", "--porcelain=v1"):
                    source_statuses += 1
                    stdout = "" if source_statuses == 1 else " M generated-after-check.json\n"
                    return subprocess.CompletedProcess(command, 0, stdout, "")
                return _successful_runner(command, cwd, environment, timeout_seconds)

            receipt = release.check_release(root, registry, process_runner=mutating_runner)

        self.assertIn(
            "repository-dirty",
            tuple(item["code"] for item in receipt["diagnostics"]),
        )

    def test_post_check_registry_revision_change_is_blocking(self) -> None:
        release = _load_script("release")
        with tempfile.TemporaryDirectory() as raw:
            root = _fixture_root(raw, release)
            registry = root / "reference-registry"
            registry.mkdir()
            revisions = 0

            def moving_registry(command, cwd, environment, timeout_seconds):
                nonlocal revisions
                if cwd == registry and command[:2] == ("git", "rev-parse"):
                    revisions += 1
                    value = REFERENCE_COMMIT if revisions <= 2 else "b" * 40
                    return subprocess.CompletedProcess(command, 0, value + "\n", "")
                return _successful_runner(command, cwd, environment, timeout_seconds)

            receipt = release.check_release(
                root,
                registry,
                process_runner=moving_registry,
                require_clean=False,
            )

        self.assertIn(
            "registry-revision-changed",
            tuple(item["code"] for item in receipt["diagnostics"]),
        )

    def test_wrong_reference_registry_origin_fails_before_claiming_compatibility(self) -> None:
        release = _load_script("release")
        calls: list[tuple[str, ...]] = []

        def spoofed(command, _cwd, _environment, _timeout_seconds):
            calls.append(command)
            stdout = "https://github.com/example/spoof.git\n" if command[0] == "git" else ""
            return subprocess.CompletedProcess(command, 0, stdout, "")

        with tempfile.TemporaryDirectory() as raw:
            root = _fixture_root(raw, release)
            registry = root / "reference-registry"
            registry.mkdir()
            receipt = release.check_release(
                root,
                registry,
                process_runner=spoofed,
                require_clean=False,
            )

        self.assertIn(
            "registry-origin-invalid",
            tuple(item["code"] for item in receipt["diagnostics"]),
        )
        checks = {item["name"]: item["passed"] for item in receipt["checks"]}
        self.assertFalse(checks["registry-compatibility"])
        self.assertFalse(any("registry validate" in " ".join(command) for command in calls))

    def test_a_fork_reconciles_against_the_registry_the_workflow_cloned(self) -> None:
        """The approved origin follows `REFERENCE_REGISTRY_URL`, defaulting to this project's.

        The release workflow clones whatever that variable names, because a fork publishes to its
        own registry and cannot reach this one.  Before this, the checklist compared against a
        constant, so a fork's release failed as `registry-origin-invalid` no matter what it set --
        a variable contradicted by a constant, and the exact class of defect this branch exists to
        remove.  Unset, the default still admits exactly one registry.
        """

        release = _load_script("release")
        fork_origin = "https://ghe.example.invalid/platform/aart-registry"

        def fork(command, _cwd, _environment, _timeout_seconds):
            if command[:4] == ("git", "remote", "get-url", "origin"):
                stdout = fork_origin + ".git\n"
            elif command == ("git", "ls-remote", "--symref", "origin", "HEAD"):
                stdout = f"ref: refs/heads/main\tHEAD\n{REFERENCE_COMMIT}\tHEAD\n"
            elif command[:2] == ("git", "rev-parse"):
                stdout = REFERENCE_COMMIT + "\n"
            else:
                stdout = ""
            return subprocess.CompletedProcess(command, 0, stdout, "")

        def codes(**environment: str) -> tuple[str, ...]:
            with tempfile.TemporaryDirectory() as raw:
                root = _fixture_root(raw, release)
                registry = root / "reference-registry"
                registry.mkdir()
                with unittest.mock.patch.dict(os.environ, environment, clear=False):
                    receipt = release.check_release(
                        root, registry, process_runner=fork, require_clean=False
                    )
            return tuple(item["code"] for item in receipt["diagnostics"])

        self.assertIn("registry-origin-invalid", codes(REFERENCE_REGISTRY_URL=""))
        self.assertNotIn(
            "registry-origin-invalid", codes(REFERENCE_REGISTRY_URL=fork_origin + ".git")
        )
        self.assertEqual(release.approved_registry_origin(), release.REFERENCE_REGISTRY_ORIGIN)

    def test_dirty_or_noncurrent_registry_is_blocking_before_registry_tools(self) -> None:
        release = _load_script("release")
        for status, head, origin_head, expected in (
            (" M catalog/index.json\n", REFERENCE_COMMIT, REFERENCE_COMMIT, "registry-dirty"),
            ("", "b" * 40, REFERENCE_COMMIT, "registry-revision-not-current"),
        ):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as raw:
                root = _fixture_root(raw, release)
                registry = root / "reference-registry"
                registry.mkdir()
                calls: list[tuple[str, ...]] = []
                receipt = release.check_release(
                    root,
                    registry,
                    process_runner=_unsafe_registry_runner(
                        calls, registry, status, head, origin_head
                    ),
                    require_clean=False,
                )

                self.assertIn(expected, tuple(item["code"] for item in receipt["diagnostics"]))
                self.assertFalse(any("registry validate" in " ".join(command) for command in calls))

    def test_stale_registry_tracking_ref_is_blocking_before_registry_tools(self) -> None:
        release = _load_script("release")
        with tempfile.TemporaryDirectory() as raw:
            root = _fixture_root(raw, release)
            registry = root / "reference-registry"
            registry.mkdir()
            calls: list[tuple[str, ...]] = []

            def stale_remote(command, cwd, environment, timeout_seconds):
                calls.append(command)
                if cwd == registry and command == (
                    "git",
                    "ls-remote",
                    "--symref",
                    "origin",
                    "HEAD",
                ):
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        f"ref: refs/heads/main\tHEAD\n{'b' * 40}\tHEAD\n",
                        "",
                    )
                return _successful_runner(command, cwd, environment, timeout_seconds)

            receipt = release.check_release(
                root,
                registry,
                process_runner=stale_remote,
                require_clean=False,
            )

        self.assertIn(
            "registry-remote-revision-mismatch",
            tuple(item["code"] for item in receipt["diagnostics"]),
        )
        self.assertFalse(any("registry validate" in " ".join(command) for command in calls))

    def test_source_not_merged_into_main_is_blocking(self) -> None:
        release = _load_script("release")

        def unmerged(command, cwd, environment, timeout_seconds):
            if cwd != ROOT and command[:3] == ("git", "merge-base", "--is-ancestor"):
                return subprocess.CompletedProcess(command, 1, "", "")
            return _successful_runner(command, cwd, environment, timeout_seconds)

        with tempfile.TemporaryDirectory() as raw:
            root = _fixture_root(raw, release)
            registry = root / "reference-registry"
            registry.mkdir()
            receipt = release.check_release(
                root,
                registry,
                process_runner=unmerged,
                require_clean=False,
            )

        self.assertIn(
            "source-not-merged-into-main",
            tuple(item["code"] for item in receipt["diagnostics"]),
        )


@unittest.skipIf(sys.version_info < (3, 11), "the stdlib wheel builder requires Python 3.11+")
class WheelDigestEvidenceTest(unittest.TestCase):
    """SI-8: the digest a verifier compares against is produced by a command, not by hand."""

    def test_the_digest_names_the_published_wheel_and_repeats(self) -> None:
        release = _load_script("release")

        first_name, first_digest = release.wheel_digest(ROOT)
        second_name, second_digest = release.wheel_digest(ROOT)

        self.assertEqual(first_name, f"agent_artifacts-{release.EXPECTED_VERSION}-py3-none-any.whl")
        self.assertEqual(first_digest, second_digest)
        self.assertRegex(first_digest, r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(first_name, second_name)

    def test_the_command_prints_the_digest_beside_the_wheel_name(self) -> None:
        release = _load_script("release")
        stdout = io.StringIO()

        with tempfile.TemporaryDirectory(prefix="aart-digest-line-") as raw:
            with contextlib.redirect_stdout(stdout):
                code = release.main(["wheel-digest", "--output", raw], root=ROOT)

        self.assertEqual(code, 0)
        digest, name = stdout.getvalue().splitlines()[0].split()
        self.assertRegex(digest, r"^sha256:[0-9a-f]{64}$")
        self.assertTrue(name.endswith("-py3-none-any.whl"), name)


@unittest.skipIf(sys.version_info < (3, 11), "the stdlib wheel builder requires Python 3.11+")
class WheelDigestArtifactTest(unittest.TestCase):
    """`LAF-75`: the command hands over the wheel whose digest it prints.

    The digest used to describe a wheel inside a temporary directory that was removed before the
    command returned, so the publisher had to build a second wheel by another route and attach
    that one — a different file, because the checkout carries no commit stamp. One build serves
    every assertion here; building it per test would triple a slow test for no extra evidence.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory(prefix="aart-laf75-")
        cls.output = Path(cls._temporary.name) / "handed-over"
        release = _load_script("release")
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            cls.code = release.main(["wheel-digest", "--output", str(cls.output)], root=ROOT)
        cls.stdout = stdout.getvalue()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def _written_wheel(self) -> Path:
        digest, name = self.stdout.splitlines()[0].split()
        return self.output / name

    def test_laf75_the_printed_digest_is_the_digest_of_the_file_left_behind(self) -> None:
        self.assertEqual(self.code, 0, self.stdout)
        digest, _ = self.stdout.splitlines()[0].split()
        written = self._written_wheel()

        self.assertTrue(written.is_file(), self.stdout)
        self.assertEqual(digest, "sha256:" + hashlib.sha256(written.read_bytes()).hexdigest())

    def test_laf75_the_command_names_the_path_it_wrote(self) -> None:
        lines = self.stdout.splitlines()

        self.assertEqual(len(lines), 2, self.stdout)
        self.assertTrue(lines[1].startswith("wrote "), lines[1])
        self.assertEqual(Path(lines[1][len("wrote ") :]), self._written_wheel())

    def test_laf75_the_written_wheel_is_the_stamped_one_a_plain_build_does_not_produce(
        self,
    ) -> None:
        inject = _load_script("inject_commit")

        with zipfile.ZipFile(self._written_wheel()) as archive:
            stamp = archive.read("agent_artifacts/_commit.py").decode("utf-8")

        # The tracked source says `unknown`; `build_wheel.py` run in the checkout packages that.
        self.assertIn(f'COMMIT = "{inject.current_commit()}"', stamp)
        self.assertNotIn('COMMIT = "unknown"', stamp)

    def test_laf75_without_an_output_directory_the_wheel_lands_in_dist(self) -> None:
        release = _load_script("release")
        seen: dict[str, object] = {}

        def record(root: Path, *, output_dir: Path | None = None) -> tuple[str, str]:
            seen["output_dir"] = output_dir
            return "agent_artifacts-0.0.0-py3-none-any.whl", "sha256:" + "0" * 64

        with mock.patch.object(release, "wheel_digest", record):
            with contextlib.redirect_stdout(io.StringIO()):
                code = release.main(["wheel-digest"], root=Path("/nonexistent-root"))

        self.assertEqual(code, 0)
        self.assertEqual(seen["output_dir"], Path("/nonexistent-root/dist"))


if __name__ == "__main__":
    unittest.main()
