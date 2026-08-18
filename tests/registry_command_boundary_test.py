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

    def test_only_the_explicit_publish_flow_can_commit_and_no_registry_code_can_push(self) -> None:
        command = ROOT / "agent_artifacts" / "commands" / "registry.py"
        calls: list[tuple[str, str]] = []
        tree = ast.parse(command.read_text(encoding="utf-8"), filename=str(command))
        for function in (node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)):
            for node in ast.walk(function):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "_git"
                    and len(node.args) >= 2
                    and isinstance(node.args[1], ast.Constant)
                    and node.args[1].value in {"commit", "push"}
                ):
                    calls.append((function.name, node.args[1].value))
        self.assertEqual(calls, [("_run_publish", "commit")])

        for path in (*PURE.rglob("*.py"), ROOT / "agent_artifacts/io/registry_workspace.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("git commit", text, path)
            self.assertNotIn("git push", text, path)


if __name__ == "__main__":
    unittest.main()
