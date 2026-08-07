from __future__ import annotations

import ast
import unittest
from pathlib import Path


class SourceBoundaryTest(unittest.TestCase):
    def test_source_model_validation_pointer_and_application_have_no_durable_io_imports(
        self,
    ) -> None:
        root = Path(__file__).parents[1] / "agent_artifacts"
        files = (
            root / "sources" / "model.py",
            root / "sources" / "pointer.py",
            root / "sources" / "validation.py",
            root / "application" / "sources.py",
        )
        forbidden = {
            "os",
            "pathlib",
            "shutil",
            "socket",
            "subprocess",
            "tempfile",
            "urllib",
            "agent_artifacts.io",
        }
        for path in files:
            with self.subTest(path=path):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                imported: set[str] = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imported.update(alias.name for alias in node.names)
                    elif isinstance(node, ast.ImportFrom) and node.module is not None:
                        imported.add(node.module)
                self.assertFalse(
                    any(
                        name == forbidden_name or name.startswith(f"{forbidden_name}.")
                        for name in imported
                        for forbidden_name in forbidden
                    ),
                    imported,
                )

    def test_only_io_adapter_invokes_subprocess(self) -> None:
        root = Path(__file__).parents[1] / "agent_artifacts"
        subprocess_importers: list[Path] = []
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import) and any(
                    alias.name == "subprocess" for alias in node.names
                ):
                    subprocess_importers.append(path.relative_to(root))
                elif isinstance(node, ast.ImportFrom) and node.module == "subprocess":
                    subprocess_importers.append(path.relative_to(root))
        self.assertIn(Path("io/git.py"), subprocess_importers)
        self.assertNotIn(Path("application/sources.py"), subprocess_importers)
        self.assertNotIn(Path("sources/model.py"), subprocess_importers)


if __name__ == "__main__":
    unittest.main()
