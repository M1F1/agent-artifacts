"""Issue #16: first-class, validated catalog descriptions."""

import json
import unittest

from agent_artifacts import catalog
from agent_artifacts.model import Err, Ok


class ParsedDescriptionTests(unittest.TestCase):
    def test_all_artifact_shapes_and_bundles_keep_normalized_description(self):
        cases = (
            (
                "skill",
                catalog.parse_skill(
                    "---\nname: review\ndescription: Review risky changes.\n---\nbody\n",
                    "review",
                ),
                "Review risky changes.",
            ),
            (
                "guideline",
                catalog.parse_guideline(
                    "---\ndescription:  Keep Python consistent.  \n---\nbody\n",
                    "python",
                ),
                "Keep Python consistent.",
            ),
            (
                "memory",
                catalog.parse_memory(
                    "---\ndescription: Apply repository conventions.\n---\nbody\n",
                    "house",
                ),
                "Apply repository conventions.",
            ),
            (
                "mcp",
                catalog.parse_mcp(
                    json.dumps(
                        {
                            "name": "postgres",
                            "description": "  Query PostgreSQL databases.  ",
                            "server": {"command": "npx"},
                        }
                    ),
                    "postgres",
                ),
                "Query PostgreSQL databases.",
            ),
            (
                "hook",
                catalog.parse_hook(
                    json.dumps(
                        {
                            "name": "guard",
                            "description": "Prevent accidental secret writes.",
                            "events": ["PreToolUse"],
                            "command": "python guard.py",
                        }
                    ),
                    "guard",
                ),
                "Prevent accidental secret writes.",
            ),
            (
                "bundle",
                catalog.parse_bundle(
                    json.dumps({"description": "  Start with team essentials.  "}),
                    "base",
                ),
                "Start with team essentials.",
            ),
        )

        for label, result, expected in cases:
            with self.subTest(label=label):
                self.assertIsInstance(result, Ok, getattr(result, "reason", ""))
                self.assertEqual(result.value.description, expected)


class InvalidDescriptionTests(unittest.TestCase):
    def test_missing_descriptions_name_the_artifact_and_descriptor_path(self):
        cases = (
            (
                catalog.parse_skill("---\nname: review\n---\nbody\n", "review"),
                "skill 'review'",
                "skills/review/SKILL.md",
            ),
            (
                catalog.parse_guideline("# body\n", "python"),
                "guideline 'python'",
                "guidelines/python.md",
            ),
            (
                catalog.parse_memory("# body\n", "house"),
                "memory 'house'",
                "memory/house.md",
            ),
            (
                catalog.parse_mcp(
                    json.dumps({"name": "postgres", "server": {"command": "npx"}}),
                    "postgres",
                    root="mcp/postgres/mcp.json",
                ),
                "mcp 'postgres'",
                "mcp/postgres/mcp.json",
            ),
            (
                catalog.parse_hook(
                    json.dumps(
                        {
                            "name": "guard",
                            "events": ["PreToolUse"],
                            "command": "python guard.py",
                        }
                    ),
                    "guard",
                ),
                "hook 'guard'",
                "hooks/guard/hook.json",
            ),
            (
                catalog.parse_bundle("{}", "base"),
                "bundle 'base'",
                "bundles/base.json",
            ),
        )

        for result, identity, path in cases:
            with self.subTest(identity=identity):
                self.assertIsInstance(result, Err)
                self.assertIn(identity, result.reason)
                self.assertIn(path, result.reason)
                self.assertIn("description", result.reason)

    def test_blank_and_non_string_descriptions_are_rejected(self):
        cases = (
            catalog.parse_skill("---\nname: review\ndescription: '   '\n---\nbody\n", "review"),
            catalog.parse_guideline("---\ndescription:\n---\nbody\n", "python"),
            catalog.parse_mcp(
                json.dumps({"name": "postgres", "description": 42, "server": {"command": "npx"}}),
                "postgres",
            ),
            catalog.parse_hook(
                json.dumps(
                    {
                        "name": "guard",
                        "description": None,
                        "events": ["PreToolUse"],
                        "command": "python guard.py",
                    }
                ),
                "guard",
            ),
            catalog.parse_bundle(json.dumps({"description": []}), "base"),
        )

        for result in cases:
            with self.subTest(result=result):
                self.assertIsInstance(result, Err)
                self.assertIn("description", result.reason)

    def test_multiline_json_and_markdown_descriptions_are_rejected(self):
        cases = (
            catalog.parse_mcp(
                json.dumps(
                    {
                        "name": "postgres",
                        "description": "First line\nsecond line",
                        "server": {"command": "npx"},
                    }
                ),
                "postgres",
            ),
            catalog.parse_bundle(json.dumps({"description": "First line\r\nsecond line"}), "base"),
            catalog.parse_skill(
                "---\nname: review\ndescription: |\n  First line\n  second line\n---\nbody\n",
                "review",
            ),
            catalog.parse_memory(
                "---\ndescription: First line\n  second line\n---\nbody\n", "house"
            ),
        )

        for result in cases:
            with self.subTest(result=result):
                self.assertIsInstance(result, Err)
                self.assertIn("single line", result.reason)


if __name__ == "__main__":
    unittest.main()
