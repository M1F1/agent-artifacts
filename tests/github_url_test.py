"""Tests for the GitHub deep-link URL parser (`parse_github_url`)."""

import unittest

from agent_artifacts.github_source import GitHubUrlParts, parse_github_url
from agent_artifacts.model import Err, Ok


class ParseGithubUrlTests(unittest.TestCase):
    def _ok(self, url: str) -> GitHubUrlParts:
        result = parse_github_url(url)
        self.assertIsInstance(result, Ok, msg=getattr(result, "reason", ""))
        return result.value

    def _err(self, url) -> str:
        result = parse_github_url(url)
        self.assertIsInstance(result, Err)
        self.assertEqual(result.code, 2)
        return result.reason

    def test_bare_repo_url(self):
        parts = self._ok("https://github.com/mattpocock/skills")
        self.assertEqual(parts.repo, "mattpocock/skills")
        self.assertIsNone(parts.ref)
        self.assertIsNone(parts.path)
        self.assertIsNone(parts.is_file)
        self.assertIsNone(parts.api_url)
        self.assertEqual(parts.web_url, "https://github.com/mattpocock/skills")

    def test_bare_repo_url_with_dot_git(self):
        parts = self._ok("https://github.com/mattpocock/skills.git")
        self.assertEqual(parts.repo, "mattpocock/skills")
        self.assertIsNone(parts.ref)

    def test_tree_url_decomposes_repo_ref_path(self):
        parts = self._ok(
            "https://github.com/mattpocock/skills/tree/main/skills/engineering/domain-modeling"
        )
        self.assertEqual(parts.repo, "mattpocock/skills")
        self.assertEqual(parts.ref, "main")
        self.assertEqual(parts.path, "skills/engineering/domain-modeling")
        self.assertIs(parts.is_file, False)
        self.assertIsNone(parts.api_url)

    def test_blob_url_marks_single_file(self):
        parts = self._ok("https://github.com/acme/skills/blob/v1.2.0/guidelines/style.md")
        self.assertEqual(parts.repo, "acme/skills")
        self.assertEqual(parts.ref, "v1.2.0")
        self.assertEqual(parts.path, "guidelines/style.md")
        self.assertIs(parts.is_file, True)

    def test_tree_branch_root_has_no_path(self):
        parts = self._ok("https://github.com/acme/skills/tree/main")
        self.assertEqual(parts.ref, "main")
        self.assertIsNone(parts.path)
        self.assertIs(parts.is_file, False)

    def test_enterprise_host_derives_api_url(self):
        parts = self._ok("https://github.my-co.com/platform/skills/tree/main/skills/x")
        self.assertEqual(parts.repo, "platform/skills")
        self.assertEqual(parts.api_url, "https://github.my-co.com/api/v3")
        self.assertEqual(parts.web_url, "https://github.my-co.com/platform/skills")

    def test_query_and_fragment_are_stripped(self):
        parts = self._ok(
            "https://github.com/acme/skills/blob/main/guidelines/x.md?plain=1#L40"
        )
        self.assertEqual(parts.path, "guidelines/x.md")
        self.assertIs(parts.is_file, True)

    def test_slashed_ref_takes_first_segment(self):
        # Ambiguous by construction: first segment after `tree` is the ref.
        parts = self._ok("https://github.com/acme/skills/tree/feature/login/skills/x")
        self.assertEqual(parts.ref, "feature")
        self.assertEqual(parts.path, "login/skills/x")

    def test_errors(self):
        self.assertIn("HTTPS", self._err("http://github.com/acme/skills"))
        self.assertIn("owner", self._err("https://github.com/acme"))
        self.assertIn("credentials", self._err("https://user:pw@github.com/acme/skills"))
        self.assertIn("ref", self._err("https://github.com/acme/skills/tree"))
        self.assertIn("tree", self._err("https://github.com/acme/skills/pulls/3"))
        self.assertIn("HTTPS GitHub URL", self._err(""))
        self.assertIn("HTTPS GitHub URL", self._err(None))


if __name__ == "__main__":
    unittest.main()
