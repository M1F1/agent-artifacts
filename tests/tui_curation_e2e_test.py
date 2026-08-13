from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from agent_artifacts import cli, tui


def _scripted(values):
    answers = iter(values)

    def read(_prompt=""):
        return next(answers)

    return read


class TuiCurationEndToEndTest(unittest.TestCase):
    def test_text_tui_initializes_and_scaffolds_without_committing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "registry"
            root.mkdir()
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            # An empty Git checkout is not a registry (design §3.2), so the maintainer TUI has
            # no init action to offer; initialization is a flag-mode command.
            initialized = cli.main(
                [
                    "registry",
                    "init",
                    "--source",
                    str(root),
                    "--source-id",
                    "e2e-registry",
                    "--display-name",
                    "E2E Registry",
                    "--yes",
                ]
            )
            self.assertEqual(initialized, 0)
            self.assertTrue((root / "aart-registry.json").is_file())

            scaffold_output = []
            scaffolded = tui._run_text(
                _scripted(
                    [
                        "",
                        "2",
                        "2",
                        "skill",
                        "demo",
                        "Explain the end-to-end demo workflow.",
                        "",
                        "codex",
                        "darwin,linux",
                        "",
                        "",
                        "finalize",
                    ]
                ),
                scaffold_output.append,
                source_dir=str(root),
            )
            self.assertEqual(scaffolded, 0)
            self.assertTrue((root / "artifacts/skill/demo/artifact.json").is_file())
            self.assertIn("Review digest", "\n".join(scaffold_output))
            commit_count = subprocess.run(
                ["git", "-C", str(root), "rev-list", "--all", "--count"],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(commit_count.stdout.strip(), "0")


if __name__ == "__main__":
    unittest.main()
