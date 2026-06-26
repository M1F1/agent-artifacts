import json
import os
import tempfile
import unittest

from agent_artifacts.import_scanner import scan_import_root
from agent_artifacts.model import Err, Ok
from agent_artifacts.upstreams import UpstreamSource


class ImportScannerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.source = UpstreamSource(
            kind="github",
            repo="acme/superpowers",
            ref="main",
            path="",
        )

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, rel: str, text: str) -> str:
        path = os.path.join(self.root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def test_manifest_mode_builds_explicit_candidates(self):
        self._write(
            "agent-artifacts.import.json",
            json.dumps(
                {
                    "version": 1,
                    "artifacts": [
                        {"type": "skill", "name": "debugging", "path": "skills/debugging"}
                    ],
                }
            ),
        )
        self._write("skills/debugging/SKILL.md", "---\nname: debugging\n---\nbody\n")

        result = scan_import_root(self.root, source=self.source, sha="abc", mode="auto")

        self.assertIsInstance(result, Ok, getattr(result, "reason", ""))
        scan = result.value
        self.assertEqual(scan.mode, "manifest")
        self.assertEqual(scan.candidates[0].key.type, "skill")
        self.assertEqual(scan.candidates[0].source.path, "skills/debugging")

    def test_manifest_mode_fails_when_declared_artifact_is_invalid(self):
        self._write(
            "agent-artifacts.import.json",
            json.dumps(
                {
                    "version": 1,
                    "artifacts": [
                        {"type": "skill", "name": "debugging", "path": "skills/debugging"}
                    ],
                }
            ),
        )

        result = scan_import_root(self.root, source=self.source, sha="abc", mode="manifest")

        self.assertIsInstance(result, Err)
        self.assertIn("debugging", result.reason)

    def test_heuristic_mode_detects_high_confidence_artifacts(self):
        self._write("skills/debugging/SKILL.md", "---\nname: debugging\n---\nbody\n")
        self._write("memory/superpowers.md", "# Superpowers\n")
        self._write(
            "mcp/github/mcp.json",
            json.dumps({"name": "github", "server": {"command": "npx"}}),
        )
        self._write("README.md", "# Not an artifact\n")

        result = scan_import_root(self.root, source=self.source, sha="abc", mode="heuristic")

        self.assertIsInstance(result, Ok, getattr(result, "reason", ""))
        keys = {(c.key.type, c.key.name) for c in result.value.candidates}
        self.assertEqual(
            keys,
            {
                ("skill", "debugging"),
                ("memory", "superpowers"),
                ("mcp", "github"),
            },
        )
        self.assertTrue(all(c.selected_by_default for c in result.value.candidates))

    def test_heuristic_mode_reports_ambiguous_markdown_without_default_selection(self):
        self._write("docs/prompting.md", "# Prompting\n")

        result = scan_import_root(self.root, source=self.source, sha="abc", mode="heuristic")

        self.assertIsInstance(result, Ok, getattr(result, "reason", ""))
        self.assertEqual(len(result.value.candidates), 1)
        candidate = result.value.candidates[0]
        self.assertEqual(candidate.confidence, "ambiguous")
        self.assertFalse(candidate.selected_by_default)


if __name__ == "__main__":
    unittest.main()
