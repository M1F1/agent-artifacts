from __future__ import annotations

import unittest

from tests.versioning_test import ROOT, _load_script


class ReleaseWorkflowTest(unittest.TestCase):
    def test_tag_workflow_repeats_quality_and_reference_registry_release_check(self) -> None:
        workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")

        self.assertIn('python-version: "3.10"', workflow)
        self.assertIn('python-version: "3.14"', workflow)
        self.assertIn('pip install --disable-pip-version-check -e ".[dev]"', workflow)
        self.assertIn("make quality", workflow)
        self.assertIn("M1F1/agent-artifacts-registry.git", workflow)
        self.assertIn("make release-check", workflow)
        self.assertIn("scripts/version.py check-tag", workflow)
        self.assertIn("fetch-depth: 0", workflow)
        self.assertIn(
            "git fetch --no-tags origin +refs/heads/main:refs/remotes/origin/main",
            workflow,
        )
        self.assertIn('git merge-base --is-ancestor "$TAG_COMMIT" origin/main', workflow)

    def test_workflow_follows_the_tag_instead_of_pinning_one_release(self) -> None:
        """A pinned trigger silently builds nothing for the next release.

        The workflow was pinned to ``v1.0.0`` in three places - the tag pattern, the release-job
        condition, and the release-notes filename - so pushing ``v1.1.0`` would have run no job,
        built no wheel, and attached no asset. The pattern stays precise rather than a bare ``v*``
        glob, and ``scripts/version.py check-tag`` remains the real gate on acceptable tags.
        """

        workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        release = _load_script("release")

        self.assertIn('- "v[0-9]+.[0-9]+.[0-9]+"', workflow)
        self.assertNotIn('- "v*"', workflow)
        self.assertIn("github-release-${TAG}.md", workflow)
        self.assertNotIn("github-release-v1.0.0.md", workflow)
        self.assertNotIn(f"tag_name == 'v{release.EXPECTED_VERSION}'", workflow)
        self.assertNotIn("tag_name == 'v1.0.0'", workflow)


if __name__ == "__main__":
    unittest.main()
