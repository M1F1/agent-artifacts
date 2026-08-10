"""Repository-level boundary tests for the code-only AART tool checkout."""

import pathlib
import tempfile
import unittest

from tests.packaging_test import _load_script

REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[1]
EMBEDDED_CATALOG_PATHS = (
    "skills",
    "guidelines",
    "mcp",
    "hooks",
    "memory",
    "bundles",
    "artifacts",
    "collections",
    "aart-source.json",
    "aart-registry.json",
    "aart.lock.json",
    "aart.index.json",
)


class RepositoryBoundaryTest(unittest.TestCase):
    def test_tool_checkout_has_no_embedded_operational_catalog(self) -> None:
        present = tuple(
            name
            for name in EMBEDDED_CATALOG_PATHS
            if (REPOSITORY_ROOT / name).exists() or (REPOSITORY_ROOT / name).is_symlink()
        )
        self.assertEqual(
            present,
            (),
            "operational artifacts belong in an explicit registry or external legacy source, "
            f"not the AART tool checkout: {present}",
        )

    def test_validation_gate_rejects_reintroduced_operational_roots(self) -> None:
        validate = _load_script("validate")
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            (root / "mcp").mkdir()

            diagnostics = validate.operational_catalog_diagnostics(root)

        self.assertEqual(
            diagnostics,
            ("repository contains embedded operational catalog path: mcp",),
        )

    def test_validation_gate_rejects_dangling_legacy_root_symlink(self) -> None:
        validate = _load_script("validate")
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            (root / "skills").symlink_to(root / "missing-catalog", target_is_directory=True)

            diagnostics = validate.operational_catalog_diagnostics(root)

        self.assertEqual(
            diagnostics,
            ("repository contains embedded operational catalog path: skills",),
        )

    def test_validation_gate_rejects_canonical_source_or_registry_markers(self) -> None:
        validate = _load_script("validate")
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            (root / "aart-source.json").write_text("{}", encoding="utf-8")
            (root / "artifacts").mkdir()

            diagnostics = validate.operational_catalog_diagnostics(root)

        self.assertEqual(
            diagnostics,
            (
                "repository contains embedded operational catalog path: artifacts",
                "repository contains embedded operational catalog path: aart-source.json",
            ),
        )


if __name__ == "__main__":
    unittest.main()
