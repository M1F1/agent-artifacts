"""Q01 contracts for hermetic local and CI quality gates."""

from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXPECTED_GATES = (
    "format-check",
    "lint",
    "typecheck",
    "unit",
    "integration",
    "e2e",
    "validate",
    "coverage",
    "packaging-check",
    "docs-check",
)


def _load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    if not path.is_file():
        raise AssertionError(f"missing Q01 script: {path.relative_to(ROOT)}")
    spec = importlib.util.spec_from_file_location(f"_q01_{name}", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {path.relative_to(ROOT)}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class QualitySurfaceTest(unittest.TestCase):
    def test_makefile_exposes_every_canonical_gate(self):
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        for target in (*EXPECTED_GATES, "quality"):
            self.assertIn(f"\n{target}:", "\n" + makefile, target)

    def test_ci_delegates_to_quality_on_minimum_and_latest_python(self):
        workflow = (ROOT / ".github" / "workflows" / "validate.yml").read_text(encoding="utf-8")
        self.assertIn('python-version: ["3.10", "3.14"]', workflow)
        self.assertIn("run: make quality", workflow)
        self.assertNotIn("unittest discover", workflow)
        self.assertNotIn("ast.walk", workflow)

    def test_dev_extra_adds_coverage_but_runtime_stays_empty(self):
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        project = pyproject.split("[project]", 1)[1].split("[project.optional-dependencies]", 1)[0]
        self.assertIn("dependencies = []", project)
        self.assertIn('"coverage>=', pyproject)


class QualityRunnerTest(unittest.TestCase):
    def test_canonical_order_and_selection_are_deterministic(self):
        quality = _load_script("quality")
        self.assertEqual(quality.QUALITY_GATES, EXPECTED_GATES)
        self.assertEqual(quality.select_gates(()), EXPECTED_GATES)
        self.assertEqual(quality.select_gates(("lint", "unit")), ("lint", "unit"))
        with self.assertRaises(ValueError):
            quality.select_gates(("unknown",))

    def test_path_snapshot_detects_a_source_mutation(self):
        quality = _load_script("quality")
        with tempfile.TemporaryDirectory() as raw:
            path = pathlib.Path(raw) / "tracked.py"
            path.write_text("before\n", encoding="utf-8")
            before = quality.snapshot_paths((path,))
            path.write_text("after\n", encoding="utf-8")
            after = quality.snapshot_paths((path,))
        self.assertNotEqual(before, after)


class DocsCheckTest(unittest.TestCase):
    def test_reports_unmatched_fence_and_missing_relative_link(self):
        docs_check = _load_script("docs_check")
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            path = root / "broken.md"
            text = "# Broken\n\n[missing](nope.md)\n\n```text\n"
            diagnostics = docs_check.validate_markdown(path, text, root)
        codes = {diagnostic.code for diagnostic in diagnostics}
        self.assertEqual(codes, {"DOC001", "DOC002"})

    def test_repository_documentation_passes(self):
        docs_check = _load_script("docs_check")
        self.assertEqual(docs_check.check_repository(ROOT), ())


class PackagingCheckTest(unittest.TestCase):
    def test_packaging_smoke_does_not_mutate_tracked_source(self):
        packaging_check = _load_script("packaging_check")
        before = subprocess.check_output(["git", "diff", "--binary", "HEAD"], cwd=ROOT)
        self.assertEqual(packaging_check.main(), 0)
        after = subprocess.check_output(["git", "diff", "--binary", "HEAD"], cwd=ROOT)
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
