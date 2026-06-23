"""Shape and metadata checks for upstream command fixtures."""

import json
import pathlib
import unittest

from agent_artifacts.catalog import parse_skill
from agent_artifacts.model import Err
from agent_artifacts.upstream_source import hash_upstream_path

FIXTURE_ROOT = pathlib.Path(__file__).resolve().parent / "fixtures" / "upstreams"
CATALOG = FIXTURE_ROOT / "catalog"
REMOTE = FIXTURE_ROOT / "remote"


class UpstreamFixturesTests(unittest.TestCase):
    def test_fixture_tree_contains_catalog_and_fake_remote_content(self):
        self.assertTrue((CATALOG / "skills" / "demo" / "SKILL.md").is_file())
        self.assertTrue((CATALOG / "memory" / "house.md").is_file())
        self.assertTrue((CATALOG / "bundles" / "backend.json").is_file())
        self.assertTrue((CATALOG / "upstreams.json").is_file())
        self.assertTrue((REMOTE / "skills" / "demo" / "SKILL.md").is_file())
        self.assertTrue((REMOTE / "memory" / "house.md").is_file())
        self.assertTrue((REMOTE / "README.md").is_file())
        self.assertTrue((REMOTE / "skills" / "broken" / "SKILL.md").is_file())

    def test_fixture_tracking_metadata_matches_catalog_base_hashes(self):
        data = json.loads((CATALOG / "upstreams.json").read_text(encoding="utf-8"))

        self.assertEqual(data["version"], 1)
        artifacts = data["artifacts"]
        self.assertEqual(
            artifacts["memory/house"]["source"]["api_url"],
            "https://github.my-company.com/api/v3",
        )
        self.assertEqual(
            artifacts["skill/demo"]["last_synced"]["content_hash"],
            hash_upstream_path(str(CATALOG / "skills" / "demo")),
        )
        self.assertEqual(
            artifacts["memory/house"]["last_synced"]["content_hash"],
            hash_upstream_path(str(CATALOG / "memory" / "house.md")),
        )

    def test_invalid_remote_skill_fixture_is_rejected_by_parser(self):
        result = parse_skill(
            (REMOTE / "skills" / "broken" / "SKILL.md").read_text(encoding="utf-8"),
            "broken",
        )

        self.assertIsInstance(result, Err)


if __name__ == "__main__":
    unittest.main()
