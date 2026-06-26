import json
import unittest

from agent_artifacts.import_manifest import parse_import_manifest
from agent_artifacts.model import Err, Ok


class ImportManifestTests(unittest.TestCase):
    def test_valid_manifest_parses_artifacts_and_bundles(self):
        result = parse_import_manifest(
            json.dumps(
                {
                    "version": 1,
                    "artifacts": [
                        {"type": "skill", "name": "debugging", "path": "skills/debugging"},
                        {
                            "type": "memory",
                            "name": "superpowers",
                            "path": "memory/superpowers.md",
                        },
                    ],
                    "bundles": [
                        {
                            "name": "superpowers",
                            "description": "Superpowers kit",
                            "includes": {
                                "skills": ["debugging"],
                                "memory": ["superpowers"],
                            },
                        }
                    ],
                }
            )
        )

        self.assertIsInstance(result, Ok, getattr(result, "reason", ""))
        manifest = result.value
        self.assertEqual(len(manifest.artifacts), 2)
        self.assertEqual(manifest.artifacts[0].name, "debugging")
        self.assertEqual(manifest.bundles[0].name, "superpowers")

    def test_rejects_duplicate_artifact_keys(self):
        result = parse_import_manifest(
            json.dumps(
                {
                    "version": 1,
                    "artifacts": [
                        {"type": "skill", "name": "debugging", "path": "a"},
                        {"type": "skill", "name": "debugging", "path": "b"},
                    ],
                }
            )
        )

        self.assertIsInstance(result, Err)
        self.assertIn("duplicate", result.reason)

    def test_rejects_paths_outside_scan_root(self):
        result = parse_import_manifest(
            json.dumps(
                {
                    "version": 1,
                    "artifacts": [
                        {"type": "skill", "name": "debugging", "path": "../debugging"},
                    ],
                }
            )
        )

        self.assertIsInstance(result, Err)
        self.assertIn("relative path inside", result.reason)


if __name__ == "__main__":
    unittest.main()
