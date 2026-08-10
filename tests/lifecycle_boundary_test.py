from __future__ import annotations

import ast
import unittest
from pathlib import Path


class LifecycleBoundaryTest(unittest.TestCase):
    def test_model_and_application_are_io_free_and_cannot_fetch_sources(self) -> None:
        root = Path(__file__).parents[1] / "agent_artifacts/lifecycle"
        forbidden_roots = {"http", "os", "pathlib", "shutil", "socket", "subprocess", "urllib"}
        forbidden_modules = {
            "agent_artifacts.io",
            "agent_artifacts.sources.git",
            "agent_artifacts.sources.local",
        }

        violations: list[str] = []
        for path in (root / "model.py", root / "application.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                names: tuple[str, ...]
                if isinstance(node, ast.Import):
                    names = tuple(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    names = (node.module or "",)
                else:
                    continue
                for name in names:
                    if name.split(".", 1)[0] in forbidden_roots or any(
                        name == denied or name.startswith(f"{denied}.")
                        for denied in forbidden_modules
                    ):
                        violations.append(f"{path.name}:{node.lineno}: {name}")

        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
