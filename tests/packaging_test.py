"""WP-21 tests: offline packaging — inject_commit + stdlib wheel builder.

Hermetic: inject_commit's source mutation is captured and restored; build_wheel is run
against a throwaway copy of the project so the repo's real ``dist/`` is never touched.

Run: ``python -m unittest discover -s tests -p "packaging_test.py" -v``
"""

import importlib.util
import pathlib
import re
import shutil
import tempfile
import unittest
import zipfile

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


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


class BuildWheelTest(unittest.TestCase):
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
        wheels = list((self.tmp / "dist").glob("agent_artifacts-*-py3-none-any.whl"))
        self.assertEqual(len(wheels), 1, f"expected exactly one wheel, got {wheels}")
        return wheels[0]

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
            info = next(
                n.split("/")[0] for n in z.namelist() if n.endswith(".dist-info/RECORD")
            )
            eps = z.read(f"{info}/entry_points.txt").decode("utf-8")
        self.assertIn("[console_scripts]", eps)
        self.assertIn("agent-artifacts = agent_artifacts.cli:main", eps)
        self.assertIn("aa = agent_artifacts.cli:main", eps)

    def test_metadata_has_name_version_and_zero_deps(self):
        wheel = self._build()
        with zipfile.ZipFile(wheel) as z:
            info = next(
                n.split("/")[0] for n in z.namelist() if n.endswith(".dist-info/RECORD")
            )
            meta = z.read(f"{info}/METADATA").decode("utf-8")
        self.assertIn("Name: agent-artifacts", meta)
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


if __name__ == "__main__":
    unittest.main()
