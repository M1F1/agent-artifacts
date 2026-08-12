"""Issue #21: real text-wizard lifecycle across Review/Edit/Finalize."""

from __future__ import annotations

import pathlib
import shutil
import tempfile
import unittest

from agent_artifacts import tui

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"


def scripted(answers):
    values = iter(answers)

    def read(_prompt=""):
        try:
            return next(values)
        except StopIteration:
            raise EOFError from None

    return read


class WizardLifecycleTests(unittest.TestCase):
    def test_review_edit_finalize_performs_one_real_install(self):
        writes = []
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            source = root / "source"
            project = root / "project"
            shutil.copytree(FIXTURES, source)
            project.mkdir()

            code = tui._run_text(
                scripted(
                    [
                        "",  # onboarding
                        "1",  # User
                        "1",  # claude
                        "install",
                        "1",  # Project
                        "",  # Copy
                        "1",  # code-review
                        "back",
                        "",  # keep the same basket
                        "finalize",
                    ]
                ),
                writes.append,
                source_dir=str(source),
                project=str(project),
            )

            destination = project / ".claude" / "skills" / "code-review" / "SKILL.md"
            manifest = project / ".agent-artifacts" / "manifest.json"
            self.assertEqual(code, 0)
            self.assertTrue(destination.is_file())
            self.assertTrue(manifest.is_file())
            self.assertEqual(sum(1 for line in writes if "▸ Review" in line), 2)
            self.assertIn("Basket: 1 selected", "\n".join(writes))

    def test_quit_from_review_discards_basket_without_real_mutation(self):
        writes = []
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            source = root / "source"
            project = root / "project"
            shutil.copytree(FIXTURES, source)
            project.mkdir()

            code = tui._run_text(
                scripted(["", "1", "1", "install", "1", "", "1", "q", "y"]),
                writes.append,
                source_dir=str(source),
                project=str(project),
            )

            self.assertEqual(code, 0)
            self.assertFalse((project / ".agent-artifacts" / "manifest.json").exists())
            self.assertIn("no changes were made", "\n".join(writes).lower())


if __name__ == "__main__":
    unittest.main()
