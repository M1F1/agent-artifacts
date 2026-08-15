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

    def test_ignores_markdown_deleted_from_the_unstaged_working_tree(self):
        docs_check = _load_script("docs_check")
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            removed = root / "removed.md"
            subprocess.run(("git", "init", "-q", str(root)), check=True)
            removed.write_text("# removed\n", encoding="utf-8")
            subprocess.run(("git", "-C", str(root), "add", "removed.md"), check=True)
            removed.unlink()

            self.assertEqual(docs_check._repository_markdown(root), ())


class ResidueRegisterGateTest(unittest.TestCase):
    """`RR-7`: the register is the single place, enforced rather than asserted.

    Each test introduces one disagreement into a throwaway copy of the register's shape and
    requires the gate to name it. A rule that cannot be made to fail is not a gate — that is
    cluster `C6`'s whole complaint about closure recorded in prose.
    """

    HEADER = (
        "# Residue register\n\n## Checked documents\n\n"
        "- checked: `docs/plan/*.md`\n\n## Register\n\n"
        "| ID | Severity | Found in | Disposition | Closed or made visible by |\n"
        "|---|---|---|---|---|\n"
    )

    def _root(self, register: str, extra: dict[str, str] | None = None) -> pathlib.Path:
        root = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
        (root / "docs" / "testing").mkdir(parents=True)
        (root / "docs" / "plan").mkdir(parents=True)
        (root / "docs" / "testing" / "residue-register.md").write_text(register, encoding="utf-8")
        for name, text in (extra or {}).items():
            (root / name).write_text(text, encoding="utf-8")
        return root

    def _codes(self, root: pathlib.Path) -> set[str]:
        docs_check = _load_script("docs_check")
        return {item.code for item in docs_check._register_diagnostics(root)}

    def test_a_stream_finding_absent_from_the_register_fails(self):
        root = self._root(
            self.HEADER + "| `LAF-52` | high | run | `open` | — |\n",
            {
                "docs/testing/residue-stream-2026-08-15.md": (
                    "| ID | One line |\n|---|---|\n"
                    "| `LAF-52` | in the register |\n"
                    "| `LAF-99` | not in the register |\n"
                )
            },
        )
        self.assertIn("DOC008", self._codes(root))

    def test_a_closure_claim_without_its_reproduction_fails(self):
        root = self._root(self.HEADER + "| `LAF-52` | high | run | `closed` | — |\n")
        self.assertIn("DOC007", self._codes(root))

    def test_a_closed_finding_still_listed_as_shipped_open_fails(self):
        root = self._root(
            self.HEADER + "| `LAF-52` | high | run | `closed` | a reproduction |\n",
            {"docs/plan/PLAN-x.md": "## Known defects shipped open\n\n- `LAF-52` is open\n"},
        )
        self.assertIn("DOC009", self._codes(root))

    def test_one_id_recorded_twice_fails(self):
        root = self._root(
            self.HEADER
            + "| `LAF-52` | high | run | `open` | — |\n"
            + "| `LAF-52` | high | run | `closed` | a reproduction |\n"
        )
        self.assertIn("DOC006", self._codes(root))

    def test_a_released_document_may_disagree_because_it_is_dated(self):
        # `github-release-v2.5.0.md` lists findings this register now records as closed, and it
        # stays that way: it is evidence of what shipped, not a claim about today.
        root = self._root(
            self.HEADER + "| `LAF-52` | high | run | `closed` | a reproduction |\n",
            {"docs/plan/kept.md": "# nothing here\n"},
        )
        (root / "docs" / "release").mkdir(parents=True)
        (root / "docs" / "release" / "github-release-v2.5.0.md").write_text(
            "## Known defects shipped open\n\n- `LAF-52`\n", encoding="utf-8"
        )
        self.assertEqual(self._codes(root), set())

    def test_the_real_register_and_the_real_documents_agree(self):
        docs_check = _load_script("docs_check")
        self.assertEqual(docs_check._register_diagnostics(ROOT), ())

    def test_every_finding_this_stream_gathered_has_a_disposition(self):
        docs_check = _load_script("docs_check")
        register = (ROOT / "docs" / "testing" / "residue-register.md").read_text(encoding="utf-8")
        rows = docs_check._REGISTER_ROW_RE.findall(register)
        self.assertEqual(len(rows), len({identifier for identifier, _ in rows}))
        # The stream gathered twenty-eight; implementing the response to it added two more.
        self.assertGreaterEqual(len(rows), 28)


class PackagingCheckTest(unittest.TestCase):
    def test_packaging_smoke_does_not_mutate_tracked_source(self):
        packaging_check = _load_script("packaging_check")
        before = subprocess.check_output(["git", "diff", "--binary", "HEAD"], cwd=ROOT)
        self.assertEqual(packaging_check.main(), 0)
        after = subprocess.check_output(["git", "diff", "--binary", "HEAD"], cwd=ROOT)
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
