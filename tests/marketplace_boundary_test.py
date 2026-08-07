from __future__ import annotations

import ast
import unittest
from pathlib import Path


class MarketplaceBoundaryTest(unittest.TestCase):
    def test_marketplace_context_has_no_durable_io_or_cli_imports(self) -> None:
        root = Path(__file__).parents[1] / "agent_artifacts" / "marketplace"
        forbidden = {
            "os",
            "pathlib",
            "shutil",
            "socket",
            "subprocess",
            "tempfile",
            "agent_artifacts.io",
            "agent_artifacts.cli",
            "agent_artifacts.tui",
        }
        for path in root.glob("*.py"):
            with self.subTest(path=path):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                imported = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imported.update(alias.name for alias in node.names)
                    elif isinstance(node, ast.ImportFrom) and node.module is not None:
                        imported.add(node.module)
                self.assertFalse(
                    any(
                        name == denied or name.startswith(f"{denied}.")
                        for name in imported
                        for denied in forbidden
                    ),
                    imported,
                )


if __name__ == "__main__":
    unittest.main()
