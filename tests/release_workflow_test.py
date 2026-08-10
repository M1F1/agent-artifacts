from __future__ import annotations

import unittest

from tests.versioning_test import ROOT


class ReleaseWorkflowTest(unittest.TestCase):
    def test_tag_workflow_repeats_quality_and_reference_registry_release_check(self) -> None:
        workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")

        self.assertIn('- "v1.0.0"', workflow)
        self.assertNotIn('- "v*"', workflow)
        self.assertIn('python-version: "3.10"', workflow)
        self.assertIn('python-version: "3.14"', workflow)
        self.assertIn('pip install --disable-pip-version-check -e ".[dev]"', workflow)
        self.assertIn("make quality", workflow)
        self.assertIn("M1F1/agent-artifacts-registry.git", workflow)
        self.assertIn("make release-check", workflow)
        self.assertIn("scripts/version.py check-tag", workflow)
        self.assertIn("docs/release/github-release-v1.0.0.md", workflow)
        self.assertIn("fetch-depth: 0", workflow)
        self.assertIn(
            "git fetch --no-tags origin +refs/heads/main:refs/remotes/origin/main",
            workflow,
        )
        self.assertIn('git merge-base --is-ancestor "$TAG_COMMIT" origin/main', workflow)
        self.assertIn("github.event.release.tag_name == 'v1.0.0'", workflow)


if __name__ == "__main__":
    unittest.main()
