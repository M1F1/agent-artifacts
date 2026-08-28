"""WP-21 tests: offline packaging — inject_commit + stdlib wheel builder.

Hermetic: inject_commit's source mutation is captured and restored; build_wheel is run
against a throwaway copy of the project so the repo's real ``dist/`` is never touched.

Run: ``python -m unittest discover -s tests -p "packaging_test.py" -v``
"""

import hashlib
import importlib.util
import io
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
        self.assertIn("agent-artifacts = agent_artifacts.cli:main", eps)
        self.assertIn("aart = agent_artifacts.cli:main", eps)
        self.assertNotIn("aa = agent_artifacts.cli:main", eps)

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

    def test_members_are_dated_from_the_stamped_commit(self):
        epoch = 1_600_000_000
        self._stamp(epoch)

        wheel = self._build_at(1_700_000_000.0)

        expected = time.gmtime(epoch)[:6]
        with zipfile.ZipFile(io.BytesIO(wheel)) as archive:
            dates = {item.date_time for item in archive.infolist()}
        self.assertEqual(dates, {expected})

    def test_an_unstamped_source_dates_at_the_zip_floor_rather_than_now(self):
        # An editable checkout, or a copy taken outside git, has no commit date. It still must not
        # reach for the clock: two dev builds of one tree are the same wheel.
        self._stamp(0)

        wheel = self._build_at(1_700_000_000.0)

        with zipfile.ZipFile(io.BytesIO(wheel)) as archive:
            dates = {item.date_time for item in archive.infolist()}
        self.assertEqual(dates, {(1980, 1, 1, 0, 0, 0)})

    def test_member_order_compression_and_attributes_are_pinned(self):
        self._stamp(1_600_000_000)

        wheel = self._build_at(1_700_000_000.0)

        with zipfile.ZipFile(io.BytesIO(wheel)) as archive:
            members = archive.infolist()
        names = [item.filename for item in members]
        record = names[-1]
        self.assertTrue(record.endswith(".dist-info/RECORD"), names[-3:])
        self.assertEqual(names[:-1], sorted(names[:-1]))
        # Create-system would otherwise be 0 on a Windows build host, and the mode would come from
        # a zipfile default rather than from this builder.
        self.assertEqual({item.create_system for item in members}, {3})
        self.assertEqual({item.external_attr for item in members}, {0o600 << 16})
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


class LentBuildBackendTest(unittest.TestCase):
    """A new virtual environment can no longer be assumed to contain setuptools.

    `ensurepip` stopped bundling it in Python 3.12, and `system_site_packages` reaches the base
    interpreter rather than a virtual environment the developer is working inside -- so a venv
    made from a venv on a recent Python has none.  The editable install then failed with a
    hundred lines of pip traceback ending in `Cannot import 'setuptools.build_meta'`, which never
    says that the build backend is the missing thing.
    """

    def test_the_lent_directory_carries_the_backend_and_nothing_else(self) -> None:
        smoke = _load_script("distribution_smoke")
        with tempfile.TemporaryDirectory() as raw:
            lent = smoke._lend_build_backend(pathlib.Path(raw))

            names = {entry.name for entry in lent.iterdir()}
            self.assertIn("setuptools", names)
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
                [sys.executable, "-S", "-c", "import setuptools.build_meta"],
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
        self.assertIn('pip install -e ".[dev]"', str(caught.exception))


if __name__ == "__main__":
    unittest.main()
