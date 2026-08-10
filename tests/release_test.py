from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

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
    package = root / "agent_artifacts"
    package.mkdir(exist_ok=True)
    (package / "__init__.py").write_text('__version__ = "1.0.0"\n', encoding="utf-8")
    (root / "pyproject.toml").write_text(
        '[project]\nname = "agent-artifacts"\nversion = "1.0.0"\ndependencies = []\n',
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
        target.write_text("# AART 1.0.0\n\nRelease evidence.\n", encoding="utf-8")
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
        self.assertEqual(first["version"], "1.0.0")
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

    def test_incompatible_registry_and_stale_index_have_distinct_redacted_codes(self) -> None:
        release = _load_script("release")

        def failing_registry(command, cwd, environment, timeout_seconds):
            if command[0] == "git":
                return _successful_runner(command, cwd, environment, timeout_seconds)
            rendered = " ".join(command)
            if "registry validate" in rendered:
                return subprocess.CompletedProcess(command, 5, "token=secret", "")
            if "registry build" in rendered:
                return subprocess.CompletedProcess(command, 5, "", "password=secret")
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


if __name__ == "__main__":
    unittest.main()
