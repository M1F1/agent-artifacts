from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PURE = ROOT / "agent_artifacts" / "registry_commands"
FORBIDDEN = {"os", "pathlib", "shutil", "socket", "subprocess", "tempfile", "importlib"}


class RegistryCommandBoundaryTest(unittest.TestCase):
    def test_registry_functional_core_has_no_io_or_git_process_dependencies(self) -> None:
        violations: list[str] = []
        for path in sorted(PURE.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                module = node.module if isinstance(node, ast.ImportFrom) else None
                names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else []
                for name in [module] if module else names:
                    if name and name.split(".", 1)[0] in FORBIDDEN:
                        violations.append(f"{path.name}: {name}")
        self.assertEqual(violations, [])

    def test_registry_command_product_code_cannot_commit_or_push(self) -> None:
        files = tuple(PURE.rglob("*.py")) + (
            ROOT / "agent_artifacts" / "commands" / "registry.py",
            ROOT / "agent_artifacts" / "io" / "registry_workspace.py",
        )
        violations = []
        for path in files:
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            if "git commit" in text or "git push" in text:
                violations.append(path.name)
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
