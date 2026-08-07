from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PURE_ROOT = ROOT / "agent_artifacts" / "registry_maintenance"
FORBIDDEN = {"os", "pathlib", "shutil", "socket", "subprocess", "tempfile", "importlib"}
CONSUMERS = (
    ROOT / "agent_artifacts" / "commands" / "install.py",
    ROOT / "agent_artifacts" / "commands" / "update.py",
    ROOT / "agent_artifacts" / "marketplace" / "catalog.py",
)


class RegistryMaintenanceBoundaryTest(unittest.TestCase):
    def test_planner_has_no_io_git_execution_or_dynamic_plugin_dependencies(self) -> None:
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
                    if name.split(".", 1)[0] in FORBIDDEN:
                        violations.append(f"{path.name}: {name}")
        self.assertEqual(violations, [])

    def test_consumer_paths_cannot_invoke_registry_maintenance(self) -> None:
        violations = [
            path.name
            for path in CONSUMERS
            if "registry_maintenance" in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
