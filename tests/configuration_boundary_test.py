from __future__ import annotations

import ast
import unittest
from pathlib import Path


class ConfigurationBoundaryTest(unittest.TestCase):
    def test_configuration_core_and_application_do_not_import_durable_io(self) -> None:
        root = Path(__file__).parents[1] / "agent_artifacts"
        files = (
            root / "configuration" / "model.py",
            root / "configuration" / "paths.py",
            root / "configuration" / "schema.py",
            root / "configuration" / "policy.py",
            root / "application" / "configuration.py",
        )
        forbidden = {
            "os",
            "pathlib",
            "shutil",
            "socket",
            "subprocess",
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


if __name__ == "__main__":
    unittest.main()
