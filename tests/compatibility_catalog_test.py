import json
import unittest

from agent_artifacts import catalog
from agent_artifacts.model import Compatibility, Err, Ok


class CompatibilityCatalogParsingTests(unittest.TestCase):
    def test_skill_frontmatter_compatibility(self):
        text = (
            "---\n"
            "name: code-review\n"
            "compatibility.profiles: claude, tabnine\n"
            "---\n"
            "body\n"
        )
        result = catalog.parse_skill(text, "code-review")
        self.assertIsInstance(result, Ok)
        self.assertEqual(result.value.compatibility, Compatibility(("claude", "tabnine")))
        self.assertEqual(result.value.root, "skills/code-review")

    def test_guideline_frontmatter_compatibility(self):
        text = "---\ncompatibility.profiles: [opencode]\n---\nbody\n"
        result = catalog.parse_guideline(text, "python-style")
        self.assertIsInstance(result, Ok)
        self.assertEqual(result.value.compatibility, Compatibility(("opencode",)))

    def test_memory_frontmatter_compatibility(self):
        text = "---\nmode: prepend\ncompatibility.profiles: vibe\n---\nbody\n"
        result = catalog.parse_memory(text, "house")
        self.assertIsInstance(result, Ok)
        self.assertEqual(result.value.compatibility, Compatibility(("vibe",)))

    def test_mcp_json_compatibility(self):
        text = json.dumps({
            "name": "postgres",
            "server": {"command": "npx"},
            "compatibility": {"profiles": ["tabnine"]},
        })
        result = catalog.parse_mcp(text, "postgres")
        self.assertIsInstance(result, Ok)
        self.assertEqual(result.value.compatibility, Compatibility(("tabnine",)))

    def test_hook_json_compatibility_keeps_directory_root(self):
        text = json.dumps({
            "name": "block-secrets",
            "events": ["PreToolUse"],
            "command": "python guard.py",
            "compatibility": {"profiles": ["claude"]},
        })
        result = catalog.parse_hook(text, "block-secrets")
        self.assertIsInstance(result, Ok)
        self.assertEqual(result.value.compatibility, Compatibility(("claude",)))
        self.assertEqual(result.value.root, "hooks/block-secrets")

    def test_invalid_compatibility_is_artifact_error(self):
        text = json.dumps({
            "name": "postgres",
            "server": {"command": "npx"},
            "compatibility": {"profiles": []},
        })
        result = catalog.parse_mcp(text, "postgres")
        self.assertIsInstance(result, Err)
        self.assertIn("mcp 'postgres'", result.reason)
        self.assertIn("compatibility.profiles", result.reason)


if __name__ == "__main__":
    unittest.main()
