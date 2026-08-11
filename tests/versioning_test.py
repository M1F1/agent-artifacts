"""V01 contracts for explicit prerelease versioning and release discipline."""

from __future__ import annotations

import importlib.util
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]

_VERSION_PARTS = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:(a|b|rc)(\d+))?$")


def _load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    if not path.is_file():
        raise AssertionError(f"missing V01 script: {path.relative_to(ROOT)}")
    spec = importlib.util.spec_from_file_location(f"_v01_{name}", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {path.relative_to(ROOT)}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _fixture_root(raw: str, *, version: str = "0.1.48", complete: bool = False) -> pathlib.Path:
    root = pathlib.Path(raw)
    package = root / "agent_artifacts"
    package.mkdir()
    (package / "__init__.py").write_text(f'__version__ = "{version}"\n', encoding="utf-8")
    match = _VERSION_PARTS.fullmatch(version)
    if match is None:
        raise AssertionError(f"invalid test fixture version: {version}")
    prerelease = "" if match.group(4) is None else f', ("{match.group(4)}", {match.group(5)})'
    (package / "runtime_contract.py").write_text(
        "from agent_artifacts.protocol.semver import SemVer\n"
        "EXECUTABLE_VERSION = SemVer("
        f"{match.group(1)}, {match.group(2)}, {match.group(3)}{prerelease})\n",
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
        f"| REL01 | Release | all | {state} | — | — | — |\n\n"
        "## Current-task template\n",
        encoding="utf-8",
    )
    return root


class VersionValueTest(unittest.TestCase):
    def test_parses_canonical_pep440_semantic_versions(self):
        versioning = _load_script("version")
        for raw in ("0.1.48", "1.0.0a1", "1.0.0b2", "1.0.0rc3"):
            self.assertEqual(str(versioning.parse_version(raw)), raw)
        for raw in ("1.0", "v1.0.0", "1.0.0-alpha.1", "1.0.0a", "01.0.0"):
            with self.subTest(raw=raw), self.assertRaises(versioning.VersionError):
                versioning.parse_version(raw)

    def test_next_alpha_only_advances_an_alpha_train(self):
        versioning = _load_script("version")
        current = versioning.parse_version("1.0.0a1")
        self.assertEqual(str(versioning.next_alpha(current)), "1.0.0a2")
        with self.assertRaises(versioning.VersionError):
            versioning.next_alpha(versioning.parse_version("1.0.0"))

    def test_finalize_candidate_preserves_core_and_requires_a_prerelease(self):
        versioning = _load_script("version")
        for raw in ("1.0.0a7", "1.0.0b2", "1.0.0rc3"):
            self.assertEqual(
                str(versioning.finalize_candidate(versioning.parse_version(raw))), "1.0.0"
            )
        with self.assertRaises(versioning.VersionError):
            versioning.finalize_candidate(versioning.parse_version("1.0.0"))


class VersionFilesTest(unittest.TestCase):
    def test_explicit_write_updates_all_version_files(self):
        versioning = _load_script("version")
        with tempfile.TemporaryDirectory() as raw:
            root = _fixture_root(raw)
            versioning.write_version(root, versioning.parse_version("1.0.0a1"))
            self.assertEqual(str(versioning.read_version(root)), "1.0.0a1")
            self.assertIn('version = "1.0.0a1"', (root / "pyproject.toml").read_text())
            self.assertIn(
                '__version__ = "1.0.0a1"', (root / "agent_artifacts/__init__.py").read_text()
            )
            self.assertIn(
                'EXECUTABLE_VERSION = SemVer(1, 0, 0, ("a", 1))',
                (root / "agent_artifacts/runtime_contract.py").read_text(),
            )

    def test_writing_a_version_preserves_each_file_trailing_newline(self):
        """A bump must not leave the repository failing `ruff format --check`.

        The version patterns previously ended in ``\\s*$``, which consumed the matched line's
        newline, so every release bump silently stripped the final newline from the files it
        touched.
        """

        versioning = _load_script("version")
        with tempfile.TemporaryDirectory() as raw:
            root = _fixture_root(raw)
            touched = (
                root / "agent_artifacts" / "__init__.py",
                root / "pyproject.toml",
                root / "agent_artifacts" / "runtime_contract.py",
            )
            for path in touched:
                self.assertTrue(
                    path.read_text().endswith("\n"), f"fixture precondition: {path.name}"
                )

            versioning.write_version(root, versioning.parse_version("1.0.0a1"))

            for path in touched:
                self.assertTrue(
                    path.read_text().endswith("\n"),
                    f"{path.name} lost its trailing newline during a version bump",
                )

    def test_check_reports_mismatched_files_without_mutation(self):
        versioning = _load_script("version")
        with tempfile.TemporaryDirectory() as raw:
            root = _fixture_root(raw)
            init = root / "agent_artifacts" / "__init__.py"
            init.write_text('__version__ = "1.0.0a1"\n', encoding="utf-8")
            before = init.read_bytes()
            diagnostics = versioning.check_version(root)
            self.assertTrue(any("mismatch" in item for item in diagnostics), diagnostics)
            self.assertEqual(init.read_bytes(), before)

    def test_check_reports_runtime_contract_mismatch_without_mutation(self):
        versioning = _load_script("version")
        with tempfile.TemporaryDirectory() as raw:
            root = _fixture_root(raw)
            runtime_contract = root / "agent_artifacts" / "runtime_contract.py"
            runtime_contract.write_text(
                "from agent_artifacts.protocol.semver import SemVer\n"
                "EXECUTABLE_VERSION = SemVer(9, 9, 9)\n",
                encoding="utf-8",
            )
            before = runtime_contract.read_bytes()
            diagnostics = versioning.check_version(root)
            self.assertTrue(any("mismatch" in item for item in diagnostics), diagnostics)
            self.assertEqual(runtime_contract.read_bytes(), before)

    def test_cli_requires_explicit_write_acknowledgement(self):
        versioning = _load_script("version")
        with tempfile.TemporaryDirectory() as raw:
            root = _fixture_root(raw, version="1.0.0a1")
            before = tuple(
                path.read_bytes()
                for path in (
                    root / "agent_artifacts" / "__init__.py",
                    root / "agent_artifacts" / "runtime_contract.py",
                    root / "pyproject.toml",
                )
            )
            self.assertEqual(versioning.main(("bump-alpha",), root), 1)
            self.assertEqual(versioning.main(("set", "1.0.0a2"), root), 1)
            after = tuple(
                path.read_bytes()
                for path in (
                    root / "agent_artifacts" / "__init__.py",
                    root / "agent_artifacts" / "runtime_contract.py",
                    root / "pyproject.toml",
                )
            )
            self.assertEqual(after, before)

            self.assertEqual(versioning.main(("bump-alpha", "--write"), root), 0)
            self.assertEqual(str(versioning.read_version(root)), "1.0.0a2")

    def test_stable_version_and_tag_fail_closed_until_release_complete(self):
        versioning = _load_script("version")
        alpha = versioning.parse_version("1.0.0a1")
        stable = versioning.parse_version("1.0.0")
        with tempfile.TemporaryDirectory() as raw:
            incomplete = _fixture_root(raw, version="1.0.0")
            versioning.ensure_allowed(incomplete, alpha)
            with self.assertRaises(versioning.VersionError):
                versioning.ensure_allowed(incomplete, stable)
            with self.assertRaises(versioning.VersionError):
                versioning.validate_tag(incomplete, "v1.0.0", stable)
        with tempfile.TemporaryDirectory() as raw:
            complete = _fixture_root(raw, version="1.0.0", complete=True)
            versioning.ensure_allowed(complete, stable)
            versioning.validate_tag(complete, "v1.0.0", stable)


class RepositoryReleaseContractTest(unittest.TestCase):
    def test_repository_version_matches_its_release_contract(self):
        """The tree is at the exact stable version its release contract governs.

        Bound to ``release.EXPECTED_VERSION`` rather than a literal so the single source of truth
        stays in the release contract and a bump does not need this assertion edited.
        """

        versioning = _load_script("version")
        release = _load_script("release")

        version = versioning.read_version(ROOT)

        self.assertEqual(str(version), release.EXPECTED_VERSION)
        self.assertTrue(version.stable)
        self.assertEqual(versioning.check_version(ROOT), ())

    def test_hook_is_non_mutating_and_release_workflow_checks_tag(self):
        hook = (ROOT / ".githooks" / "pre-commit").read_text(encoding="utf-8")
        self.assertIn("scripts/version.py check", hook)
        self.assertIn("git diff --cached --check", hook)
        self.assertNotIn("bump", hook)
        self.assertNotIn("wheel", hook)
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn("scripts/version.py check-tag", workflow)

    def test_retired_bump_script_cannot_mutate_version_files(self):
        paths = (ROOT / "agent_artifacts" / "__init__.py", ROOT / "pyproject.toml")
        before = tuple(path.read_bytes() for path in paths)
        result = subprocess.run(
            [sys.executable, "scripts/bump_version.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("explicitly", result.stderr)
        self.assertEqual(tuple(path.read_bytes() for path in paths), before)

    def test_wheels_are_release_outputs_not_tracked_files(self):
        tracked = subprocess.check_output(["git", "ls-files", "dist"], cwd=ROOT, text=True)
        self.assertEqual(tracked, "")
        self.assertIn("/dist/*.whl", (ROOT / ".gitignore").read_text(encoding="utf-8"))

    @unittest.skipIf(sys.version_info < (3, 11), "stdlib wheel builder requires Python 3.11+")
    def test_local_wheel_filename_and_metadata_match_package_version(self):
        versioning = _load_script("version")
        build = _load_script("build_wheel")
        with tempfile.TemporaryDirectory() as raw:
            target = pathlib.Path(raw)
            shutil.copytree(ROOT / "agent_artifacts", target / "agent_artifacts")
            shutil.copy2(ROOT / "pyproject.toml", target / "pyproject.toml")
            shutil.copy2(ROOT / "README.md", target / "README.md")
            build.ROOT = target
            self.assertEqual(build.main(), 0)
            version = str(versioning.read_version(ROOT))
            wheel = target / "dist" / f"agent_artifacts-{version}-py3-none-any.whl"
            self.assertTrue(wheel.is_file(), wheel)
            with zipfile.ZipFile(wheel) as archive:
                metadata_name = next(
                    name for name in archive.namelist() if name.endswith("/METADATA")
                )
                metadata = archive.read(metadata_name).decode("utf-8")
            self.assertIn(f"Version: {version}\n", metadata)


if __name__ == "__main__":
    unittest.main()
