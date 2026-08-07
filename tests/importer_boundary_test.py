from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PURE_ROOT = ROOT / "agent_artifacts" / "importers"
FORBIDDEN_PURE_ROOTS = {"os", "pathlib", "shutil", "socket", "subprocess", "tempfile", "importlib"}
CONSUMER_FILES = (
    ROOT / "agent_artifacts" / "marketplace" / "catalog.py",
    ROOT / "agent_artifacts" / "commands" / "install.py",
    ROOT / "agent_artifacts" / "commands" / "update.py",
    ROOT / "agent_artifacts" / "commands" / "list.py",
)


class ImporterBoundaryTest(unittest.TestCase):
    def test_pure_importers_have_no_io_execution_or_dynamic_plugin_dependencies(self) -> None:
        violations: list[str] = []
        for path in sorted(PURE_ROOT.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                names: tuple[str, ...] = ()
                if isinstance(node, ast.Import):
                    names = tuple(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = (node.module,)
                for name in names:
                    if name.split(".", 1)[0] in FORBIDDEN_PURE_ROOTS:
                        violations.append(f"{path.name}: {name}")
        self.assertEqual(violations, [])

    def test_consumer_paths_cannot_invoke_maintainer_importers(self) -> None:
        violations = []
        for path in CONSUMER_FILES:
            text = path.read_text(encoding="utf-8")
            if (
                "agent_artifacts.importers" in text
                or "agent_artifacts.application.importers" in text
                or "from .importers" in text
            ):
                violations.append(path.name)
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
