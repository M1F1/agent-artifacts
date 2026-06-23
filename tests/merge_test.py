"""WP-3 merge-engine tests: render, identity, key-merge (MCP) and list-merge (hooks), DESIGN.md §10."""

import unittest

from agent_artifacts import merge
from agent_artifacts.model import Err, MergeJson, MergeSpec, Ok

MCP_SPEC = MergeSpec(file=".mcp.json", json_path="mcpServers", mode="key")
HOOK_SPEC = MergeSpec(
    file=".claude/settings.json",
    json_path="hooks.PreToolUse",
    mode="list",
    identity=("matcher", "command"),
    entry_template={
        "matcher": "${matcher}",
        "hooks": [{"type": "command", "command": "${command}"}],
    },
)


class RenderTests(unittest.TestCase):
    def test_whole_field_placeholder_preserves_type(self):
        # a lone ${field} returns the descriptor's value unchanged (here a list)
        out = merge.render("${events}", {"events": ["PreToolUse"]})
        self.assertEqual(out, ["PreToolUse"])

    def test_substring_substitution_is_stringified(self):
        out = merge.render("python3 ${dir}/guard.py", {"dir": ".claude/hooks/x"})
        self.assertEqual(out, "python3 .claude/hooks/x/guard.py")

    def test_nested_template_renders_recursively(self):
        out = merge.render(
            HOOK_SPEC.entry_template, {"matcher": "Edit|Write", "command": "python3 g.py"}
        )
        self.assertEqual(
            out,
            {"matcher": "Edit|Write", "hooks": [{"type": "command", "command": "python3 g.py"}]},
        )

    def test_missing_field_in_substring_becomes_empty(self):
        self.assertEqual(merge.render("a${gone}b", {}), "ab")


class IdentityTests(unittest.TestCase):
    def test_identity_of_pulls_declared_fields(self):
        ident = merge.identity_of(
            HOOK_SPEC, {"matcher": "Edit", "command": "c", "extra": "ignored"}
        )
        self.assertEqual(ident, (("matcher", "Edit"), ("command", "c")))


class KeyMergeTests(unittest.TestCase):
    def test_new_key_is_ok(self):
        res = merge.plan_merge(MCP_SPEC, {"command": "npx"}, {"mcpServers": {}}, key="postgres")
        self.assertIsInstance(res, Ok)
        self.assertEqual(
            res.value,
            MergeJson(
                file=".mcp.json",
                json_path="mcpServers",
                mode="key",
                value={"command": "npx"},
                identity=("postgres",),
            ),
        )

    def test_identical_existing_value_is_not_a_collision(self):
        existing = {"mcpServers": {"postgres": {"command": "npx"}}}
        res = merge.plan_merge(MCP_SPEC, {"command": "npx"}, existing, key="postgres")
        self.assertIsInstance(res, Ok)

    def test_differing_existing_collides_without_force(self):
        existing = {"mcpServers": {"postgres": {"command": "OLD"}}}
        res = merge.plan_merge(MCP_SPEC, {"command": "npx"}, existing, key="postgres")
        self.assertIsInstance(res, Err)
        self.assertEqual(res.code, 4)  # conflict-needs-force exit code (PLAN.md §7)

    def test_force_overrides_collision(self):
        existing = {"mcpServers": {"postgres": {"command": "OLD"}}}
        res = merge.plan_merge(MCP_SPEC, {"command": "npx"}, existing, key="postgres", force=True)
        self.assertIsInstance(res, Ok)

    def test_key_mode_requires_a_key(self):
        res = merge.plan_merge(MCP_SPEC, {"command": "npx"}, {"mcpServers": {}})
        self.assertIsInstance(res, Err)


class ListMergeTests(unittest.TestCase):
    def test_list_append_emits_list_mode_mergejson(self):
        value = {"matcher": "Edit", "hooks": [{"type": "command", "command": "g"}]}
        res = merge.plan_merge(HOOK_SPEC, value, {"hooks": {"PreToolUse": []}})
        self.assertIsInstance(res, Ok)
        self.assertEqual(res.value.mode, "list")
        self.assertEqual(res.value.value, value)
        self.assertEqual(res.value.json_path, "hooks.PreToolUse")


if __name__ == "__main__":
    unittest.main()
