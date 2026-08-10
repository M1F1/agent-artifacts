from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PURE_ROOT = ROOT / "agent_artifacts" / "curation" / "model.py"
RUNTIME = ROOT / "agent_artifacts" / "curation" / "runtime.py"


class CurationBoundaryTest(unittest.TestCase):
    def test_model_has_no_filesystem_network_terminal_or_command_dependencies(self) -> None:
        tree = ast.parse(PURE_ROOT.read_text(encoding="utf-8"), filename=str(PURE_ROOT))
        forbidden = {"pathlib", "shutil", "socket", "subprocess", "tempfile", "curses"}
        violations = []
        for node in ast.walk(tree):
            names: tuple[str, ...] = ()
            if isinstance(node, ast.Import):
                names = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = (node.module,)
            violations.extend(name for name in names if name.split(".", 1)[0] in forbidden)
        self.assertEqual(violations, [])

    def test_runtime_cannot_mutate_consumer_stores_or_publish_git_changes(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")
        for forbidden in (
            "object_store",
            "reference_store",
            "install_state",
            "git commit",
            "git push",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
