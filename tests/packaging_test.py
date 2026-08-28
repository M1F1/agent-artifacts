"""WP-21 tests: offline packaging — inject_commit + stdlib wheel builder.

Hermetic: inject_commit's source mutation is captured and restored; build_wheel is run
against a throwaway copy of the project so the repo's real ``dist/`` is never touched.

Run: ``python -m unittest discover -s tests -p "packaging_test.py" -v``
"""

import configparser
import hashlib
import importlib.util
import io
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from unittest import mock

from tests.credential_fixtures import secret_field

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
# Captured before any test patches ``time.localtime``, so a build under a moved clock can still be
# handed the local time that clock implies.
real_localtime = time.localtime


def _load_script(name: str):
    """Import ``scripts/<name>.py`` as a standalone module (scripts/ isn't a package)."""
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_wp21_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class InjectCommitTest(unittest.TestCase):
    def test_writes_sha_or_unknown_and_is_restorable(self):
        inject = _load_script("inject_commit")
        target = inject.TARGET
        original = target.read_text(encoding="utf-8")
        try:
            rc = inject.main()
            self.assertEqual(rc, 0)
            written = target.read_text(encoding="utf-8")
            # Docstring must survive the rewrite.
            self.assertIn("Source commit the package was built from", written)
            # Extract the COMMIT literal and assert it's a full sha or "unknown".
            match = re.search(r'COMMIT = "([^"]*)"', written)
            self.assertIsNotNone(match, "COMMIT assignment not found")
            commit = match.group(1)
            self.assertTrue(
                commit == "unknown" or _SHA_RE.match(commit),
                f"COMMIT must be 40-hex sha or 'unknown', got {commit!r}",
            )
            # Idempotent: a second run yields identical output.
            inject.main()
            self.assertEqual(target.read_text(encoding="utf-8"), written)
        finally:
            target.write_text(original, encoding="utf-8")
        # Restored byte-for-byte.
        self.assertEqual(target.read_text(encoding="utf-8"), original)

    def test_render_quotes_commit(self):
        inject = _load_script("inject_commit")
        rendered = inject.render("deadbeef")
        self.assertIn('COMMIT = "deadbeef"', rendered)
        self.assertTrue(rendered.endswith("\n"))


class _WheelBuildFixture:
    """A throwaway copy of the project, built by the real builder redirected into it."""

    def setUp(self):
        # Build against a throwaway copy of the project so the real dist/ is untouched.
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="wp21_wheel_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        shutil.copytree(
            REPO_ROOT / "agent_artifacts",
            self.tmp / "agent_artifacts",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        shutil.copy2(REPO_ROOT / "pyproject.toml", self.tmp / "pyproject.toml")
        readme = REPO_ROOT / "README.md"
        if readme.exists():
            shutil.copy2(readme, self.tmp / "README.md")

        self.build = _load_script("build_wheel")
        self.build.ROOT = self.tmp  # redirect all I/O into the temp tree

    def _build(self) -> pathlib.Path:
        rc = self.build.main()
        self.assertEqual(rc, 0)
        wheels = list((self.tmp / "dist").glob("aart_cli-*-py3-none-any.whl"))
        self.assertEqual(len(wheels), 1, f"expected exactly one wheel, got {wheels}")
        return wheels[0]


@unittest.skipIf(sys.version_info < (3, 11), "stdlib wheel builder requires Python 3.11+")
class BuildWheelTest(_WheelBuildFixture, unittest.TestCase):
    def test_wheel_is_valid_zip_with_dist_info(self):
        wheel = self._build()
        self.assertTrue(zipfile.is_zipfile(wheel))
        with zipfile.ZipFile(wheel) as z:
            self.assertIsNone(z.testzip(), "corrupt member in wheel zip")
            names = z.namelist()
        info_dirs = {n.split("/")[0] for n in names if n.endswith(".dist-info/RECORD")}
        self.assertEqual(len(info_dirs), 1, f"expected one .dist-info, got {info_dirs}")
        info = info_dirs.pop()
        for required in ("METADATA", "RECORD", "entry_points.txt", "WHEEL"):
            self.assertIn(f"{info}/{required}", names)
        # The package itself must be bundled.
        self.assertIn("agent_artifacts/__init__.py", names)
        self.assertIn("agent_artifacts/cli.py", names)

    def test_entry_points_list_both_scripts(self):
        wheel = self._build()
        with zipfile.ZipFile(wheel) as z:
            info = next(n.split("/")[0] for n in z.namelist() if n.endswith(".dist-info/RECORD"))
            eps = z.read(f"{info}/entry_points.txt").decode("utf-8")
        self.assertIn("[console_scripts]", eps)
        # Parsed, not matched as text: builders disagree about the spaces around `=`, and a test
        # that pins one builder's whitespace fails on a change that installs identical commands.
        parser = configparser.ConfigParser()
        parser.read_string(eps)
        scripts = dict(parser["console_scripts"])
        self.assertEqual(
            scripts,
            {"agent-artifacts": "agent_artifacts.cli:main", "aart": "agent_artifacts.cli:main"},
        )

    def test_wheel_contains_no_operational_registry_or_legacy_catalog(self):
        wheel = self._build()
        with zipfile.ZipFile(wheel) as archive:
            names = archive.namelist()
        operational_roots = (
            "artifacts/",
            "bundles/",
            "guidelines/",
            "hooks/",
            "mcp/",
            "memory/",
            "skills/",
        )
        self.assertFalse(any(name.startswith(root) for name in names for root in operational_roots))

    def test_builder_rejects_package_data_outside_the_distribution_allowlist(self):
        forbidden = self.tmp / "agent_artifacts" / "artifacts" / "private.json"
        forbidden.parent.mkdir()
        forbidden.write_text("{" + secret_field("secret", "must-not-ship") + "}", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "wheel resource allowlist"):
            self.build.collect_package_files()

    def test_builder_rejects_symlinked_package_directories(self):
        outside = self.tmp / "outside"
        outside.mkdir()
        linked = self.tmp / "agent_artifacts" / "templates"
        linked.symlink_to(outside, target_is_directory=True)

        with self.assertRaisesRegex(ValueError, "wheel resource allowlist"):
            self.build.collect_package_files()

    def test_packaging_gate_rejects_an_unrecorded_allowed_member(self):
        wheel = self._build()
        with zipfile.ZipFile(wheel, "a") as archive:
            archive.writestr("agent_artifacts/unrecorded.py", b"value = 1\n")
        packaging = _load_script("packaging_check")

        with self.assertRaisesRegex(ValueError, "RECORD does not list every member"):
            packaging._validate_wheel(wheel, self.tmp / "inspect")

    def test_metadata_has_name_version_and_zero_deps(self):
        wheel = self._build()
        with zipfile.ZipFile(wheel) as z:
            info = next(n.split("/")[0] for n in z.namelist() if n.endswith(".dist-info/RECORD"))
            meta = z.read(f"{info}/METADATA").decode("utf-8")
        self.assertIn("Name: aart-cli", meta)
        self.assertIn("Version: ", meta)
        self.assertIn("Requires-Python: ", meta)
        # Zero runtime deps: no Requires-Dist lines.
        self.assertNotIn("Requires-Dist:", meta)

    def test_record_lists_every_member(self):
        wheel = self._build()
        with zipfile.ZipFile(wheel) as z:
            names = set(z.namelist())
            info = next(n.split("/")[0] for n in names if n.endswith(".dist-info/RECORD"))
            record = z.read(f"{info}/RECORD").decode("utf-8")
        recorded = {line.split(",")[0] for line in record.splitlines() if line.strip()}
        # Every archive member is accounted for in RECORD (RECORD lists itself too).
        self.assertEqual(names, recorded)


@unittest.skipIf(sys.version_info < (3, 11), "stdlib wheel builder requires Python 3.11+")
class ReproducibleWheelTest(_WheelBuildFixture, unittest.TestCase):
    """SI-8: rebuilding one commit reproduces the published archive, not merely its contents.

    `LAF-30`'s probe failed this by hand — two builds of the same source differed, because every
    member was dated from the clock. The assertions here compare whole-archive digests, so a
    regression cannot pass by being "content-identical" while the bytes move.
    """

    def _stamp(self, epoch: int) -> None:
        commit = self.tmp / "agent_artifacts" / "_commit.py"
        commit.write_text(
            f'"""Stamp fixture."""\n\nCOMMIT = "{"a" * 40}"\nCOMMIT_EPOCH = {epoch}\n',
            encoding="utf-8",
        )

    def _dates_of(self, wheel: bytes) -> set:
        with zipfile.ZipFile(io.BytesIO(wheel)) as archive:
            return {item.date_time for item in archive.infolist()}

    def _build_at(self, now: float) -> bytes:
        # Everything zipfile would reach for if a member were dated from the clock, moved between
        # the two builds. A builder that reads either one produces a different archive.
        with (
            mock.patch("time.time", return_value=now),
            mock.patch("time.localtime", lambda *arguments: real_localtime(now)),
        ):
            return self._build().read_bytes()

    def test_two_builds_of_one_commit_at_different_times_are_byte_identical(self):
        self._stamp(1_600_000_000)

        first = self._build_at(1_700_000_000.0)
        second = self._build_at(1_700_086_400.0)

        self.assertEqual(
            hashlib.sha256(first).hexdigest(),
            hashlib.sha256(second).hexdigest(),
            "the wheel is not byte-reproducible across build times",
        )

    def test_member_dates_are_fixed_and_read_neither_the_clock_nor_the_stamp(self):
        """Poetry dates every member at one constant, so no input can move the dates at all.

        Until 2.8.6 the dates came from `COMMIT_EPOCH`. That was one way to keep the clock out of
        the archive; a constant is another, and a stricter one -- two commits an hour apart now
        differ only where their content differs.
        """

        self._stamp(1_600_000_000)
        early = self._dates_of(self._build_at(1_700_000_000.0))

        self._stamp(1_500_000_000)
        late = self._dates_of(self._build_at(1_700_086_400.0))

        self.assertEqual(early, late)
        self.assertEqual(len(early), 1, early)
        # Not "now", under any clock this test could run at.
        self.assertLess(early.pop()[0], 2020)

    def test_the_environment_cannot_move_the_digest(self):
        """`SOURCE_DATE_EPOCH` is the hole Poetry opens, and the builder closes it.

        poetry-core honours the variable. A digest that depends on it is a digest that cannot be
        checked by anyone who did not happen to have it set the same way -- so the builder removes
        it before invoking Poetry rather than documenting it as a caveat.
        """

        self._stamp(1_600_000_000)
        clean = self._build().read_bytes()

        with mock.patch.dict(os.environ, {"SOURCE_DATE_EPOCH": "1000000000"}):
            steered = self._build().read_bytes()

        self.assertEqual(
            hashlib.sha256(clean).hexdigest(),
            hashlib.sha256(steered).hexdigest(),
            "SOURCE_DATE_EPOCH moved the wheel's bytes",
        )

    def test_a_builder_other_than_the_pinned_one_fails_the_build(self):
        """The builder stamps its version into the archive, so an upgrade moves the digest.

        Left unchecked, upgrading Poetry would silently invalidate every published digest while
        every gate stayed green. The pin is checked against what actually built the file.
        """

        self._stamp(1_600_000_000)
        wheel = self._build()
        with zipfile.ZipFile(wheel) as archive:
            info = next(n.split("/")[0] for n in archive.namelist() if n.endswith("/WHEEL"))
            metadata = archive.read(f"{info}/WHEEL").decode("utf-8")
        self.assertIn(f"Generator: poetry-core {self.build.pinned_backend()}", metadata)

        with mock.patch.object(self.build, "pinned_backend", return_value="0.0.0"):
            with self.assertRaises(SystemExit) as raised:
                self.build.main()
        self.assertIn("[build-system] pins 0.0.0", str(raised.exception))

    def test_compression_and_attributes_are_pinned(self):
        self._stamp(1_600_000_000)

        wheel = self._build_at(1_700_000_000.0)

        with zipfile.ZipFile(io.BytesIO(wheel)) as archive:
            members = archive.infolist()
        names = [item.filename for item in members]
        self.assertTrue(any(n.endswith(".dist-info/RECORD") for n in names), names[-3:])
        # Create-system would otherwise be 0 on a Windows build host.
        self.assertEqual({item.create_system for item in members}, {3})
        self.assertEqual({item.compress_type for item in members}, {zipfile.ZIP_DEFLATED})


class TypedBehaviorProbeTest(unittest.TestCase):
    """ERR07: a built wheel must reproduce the checkout's typed diagnostics, not merely import."""

    def setUp(self):
        self.packaging = _load_script("packaging_check")

    def test_probe_renders_the_legacy_state_record_from_the_installed_package_alone(self):
        rendered = self.packaging.run_typed_behavior_probe(sys.executable, env=None, cwd=REPO_ROOT)

        # The probe must exercise the whole typed path — parser code, stage record, renderer —
        # not just prove that an import succeeded.
        self.assertIn("error [install-state-legacy]", rendered)
        self.assertIn("Artifacts could not be loaded", rendered)
        self.assertIn("install-state-v0.1", rendered)
        self.assertIn("error [install-state-invalid]", rendered)
        self.assertIn("internal error: tui-stage-internal", rendered)
        self.assertIn("Quit = q", rendered)

    def test_probe_output_is_free_of_environment_specific_text(self):
        rendered = self.packaging.run_typed_behavior_probe(sys.executable, env=None, cwd=REPO_ROOT)

        # Equality between two interpreters is only meaningful if nothing local leaks in.
        self.assertNotIn(str(REPO_ROOT), rendered)
        self.assertNotIn(sys.prefix, rendered)
        self.assertNotIn("Traceback", rendered)

    def test_mismatched_typed_behavior_is_a_packaging_failure(self):
        with self.assertRaisesRegex(ValueError, "typed behavior differs"):
            self.packaging._compare_typed_behavior("checkout-record\n", "wheel-record\n")

    def test_identical_typed_behavior_passes(self):
        self.assertIsNone(self.packaging._compare_typed_behavior("same\n", "same\n"))


class FindingPoetryTest(unittest.TestCase):
    """What a machine without Poetry is told, which is the whole of what it can act on.

    `poetry-core` is the build backend, and the dev group installs it -- so every image that can
    run the gates has the `poetry` namespace, whether or not it has the Poetry CLI.  A blind
    `python -m poetry` therefore does not fail as missing: it fails as
    "'poetry' is a package and cannot be directly executed", which names neither Poetry nor the
    variable that points at it.  A real Enterprise image is exactly this shape.
    """

    def setUp(self):
        self.build = _load_script("build_wheel")

    def test_the_variable_names_the_interpreter_outright(self):
        with mock.patch.dict(os.environ, {"AART_POETRY": "/opt/poetry/bin/poetry"}):
            self.assertEqual(["/opt/poetry/bin/poetry"], self.build.poetry_command())

    def test_a_poetry_on_path_is_used_as_found(self):
        with mock.patch.dict(os.environ, {"AART_POETRY": ""}):
            with mock.patch.object(shutil, "which", return_value="/usr/bin/poetry"):
                self.assertEqual(["/usr/bin/poetry"], self.build.poetry_command())

    def test_the_module_is_used_only_when_it_is_the_cli(self):
        with mock.patch.dict(os.environ, {"AART_POETRY": ""}):
            with mock.patch.object(shutil, "which", return_value=None):
                with mock.patch.object(self.build, "_poetry_module_runs", return_value=True):
                    self.assertEqual([sys.executable, "-m", "poetry"], self.build.poetry_command())

    def test_no_poetry_at_all_says_what_to_set(self):
        with mock.patch.dict(os.environ, {"AART_POETRY": ""}):
            with mock.patch.object(shutil, "which", return_value=None):
                with mock.patch.object(self.build, "_poetry_module_runs", return_value=False):
                    with self.assertRaises(SystemExit) as raised:
                        self.build.poetry_command()

        message = str(raised.exception)
        self.assertIn("AART_POETRY", message)
        self.assertIn("docs/ci/enterprise-fork-v1.md", message)
        # The message a bare `python -m poetry` would have produced instead.
        self.assertNotIn("cannot be directly executed", message)

    def test_the_backend_alone_does_not_look_like_the_cli(self):
        """`poetry-core` is installed here, and it must not satisfy the check."""

        self.assertIsNotNone(importlib.util.find_spec("poetry.core"))
        if importlib.util.find_spec("poetry.console") is not None:  # pragma: no cover
            self.skipTest("the Poetry CLI is installed here, so there is nothing to prove")
        self.assertFalse(self.build._poetry_module_runs())


class LentBuildBackendTest(unittest.TestCase):
    """A new virtual environment cannot be assumed to contain the build backend.

    `ensurepip` bundles neither poetry-core nor, since Python 3.12, setuptools, and
    `system_site_packages` reaches the base interpreter rather than a virtual environment the
    developer is working inside -- so a venv made from a venv has none.  The offline editable
    install then failed with a hundred lines of pip traceback ending in
    `Cannot import 'poetry.core.masonry.api'`, which never says that the build backend is the
    missing thing.
    """

    def test_the_lent_directory_carries_the_backend_and_nothing_else(self) -> None:
        smoke = _load_script("distribution_smoke")
        with tempfile.TemporaryDirectory() as raw:
            lent = smoke._lend_build_backend(pathlib.Path(raw))

            names = {entry.name for entry in lent.iterdir()}
            self.assertIn("poetry", names)
            # Only the backend travels.  Lending the whole environment would put the developer's
            # own editable agent_artifacts on the path, and the install would look like it worked
            # when nothing had been installed at all.
            self.assertNotIn("agent_artifacts", names)
            self.assertFalse([name for name in names if name.startswith("agent_artifacts")])

    def test_the_lent_backend_is_importable_by_another_interpreter(self) -> None:
        smoke = _load_script("distribution_smoke")
        with tempfile.TemporaryDirectory() as raw:
            lent = smoke._lend_build_backend(pathlib.Path(raw))
            environment = {"PYTHONPATH": str(lent), "PATH": "/usr/bin:/bin"}

            probe = subprocess.run(
                [sys.executable, "-S", "-c", "import poetry.core.masonry.api"],
                capture_output=True,
                env=environment,
            )

            self.assertEqual(probe.returncode, 0, probe.stderr.decode("utf-8", "replace"))

    def test_a_missing_backend_names_the_command_that_installs_one(self) -> None:
        smoke = _load_script("distribution_smoke")
        with tempfile.TemporaryDirectory() as raw:
            with mock.patch.object(smoke.importlib.util, "find_spec", return_value=None):
                with self.assertRaises(RuntimeError) as caught:
                    smoke._lend_build_backend(pathlib.Path(raw))
        self.assertIn("poetry install --with dev", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
