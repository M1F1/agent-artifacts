"""WP-5 planner tests: golden Plans for each artifact type + the install aggregator.

Run: ``python -m unittest discover -s tests -p "planners_test.py" -v``

These tests are pure: they build inline data, call a planner, and assert the resulting
`Plan` tuple exactly (golden assertions). No filesystem or network is touched.
"""

import unittest

from agent_artifacts import planners
from agent_artifacts.model import (
    Artifact,
    CopyTarget,
    CopyTree,
    Err,
    GuidelineTarget,
    HookTarget,
    MergeJson,
    MergeSpec,
    Ok,
    Profile,
    Request,
    WriteFile,
    WriteManifest,
)


# --------------------------------------------------------------------------- #
# Shared fixtures (Claude-like profile, mirroring DESIGN.md §11)              #
# --------------------------------------------------------------------------- #
def claude_profile() -> Profile:
    return Profile(
        name="claude",
        skills=CopyTarget(dir=".claude/skills/<name>/"),
        guidelines=GuidelineTarget(dest=".claude/guidelines/"),
        mcp=MergeSpec(file=".mcp.json", json_path="mcpServers", mode="key"),
        hooks=HookTarget(
            scripts_dir=".claude/hooks/<name>/",
            events={"PreToolUse": "hooks.PreToolUse"},
            merge=MergeSpec(
                file=".claude/settings.json",
                json_path="hooks.PreToolUse",
                mode="list",
                identity=("matcher", "command"),
                entry_template={
                    "matcher": "${matcher}",
                    "hooks": [{"type": "command", "command": "${command}"}],
                },
            ),
        ),
    )


# --------------------------------------------------------------------------- #
# plan_skill                                                                   #
# --------------------------------------------------------------------------- #
class SkillPlannerTests(unittest.TestCase):
    def test_golden_copytree_with_name_substitution(self):
        art = Artifact(type="skill", name="code-review", root="skills/code-review")
        result = planners.plan_skill(art, ".claude/skills/<name>/")
        self.assertEqual(
            result,
            Ok((CopyTree(src="skills/code-review", dst=".claude/skills/code-review"),)),
        )

    def test_dir_without_placeholder_appends_name(self):
        art = Artifact(type="skill", name="code-review", root="skills/code-review")
        result = planners.plan_skill(art, ".tabnine/agent/skills")
        self.assertEqual(
            result,
            Ok((CopyTree(src="skills/code-review", dst=".tabnine/agent/skills/code-review"),)),
        )


# --------------------------------------------------------------------------- #
# plan_guideline                                                               #
# --------------------------------------------------------------------------- #
class GuidelinePlannerTests(unittest.TestCase):
    """Guidelines are copy-only: a standalone reference doc written into the target dir as
    ``<name>.md``. They never merge into a shared file (that is the memory artifact's job),
    so there is no mode, no ``existing_text``, and no sentinel wrapping."""

    def test_copy_golden(self):
        art = Artifact(type="guideline", name="python-style", root="guidelines/python-style.md")
        target = GuidelineTarget(dest=".tabnine/guidelines")
        result = planners.plan_guideline(art, target, "Use black.\n")
        self.assertEqual(
            result,
            Ok((WriteFile(path=".tabnine/guidelines/python-style.md", content=b"Use black.\n"),)),
        )

    def test_copy_into_dir_with_trailing_slash(self):
        art = Artifact(type="guideline", name="python-style", root="guidelines/python-style.md")
        target = GuidelineTarget(dest=".claude/guidelines/")
        result = planners.plan_guideline(art, target, "body")
        self.assertEqual(
            result,
            Ok((WriteFile(path=".claude/guidelines/python-style.md", content=b"body"),)),
        )


# --------------------------------------------------------------------------- #
# plan_mcp                                                                     #
# --------------------------------------------------------------------------- #
class McpPlannerTests(unittest.TestCase):
    def setUp(self):
        self.art = Artifact(type="mcp", name="postgres", root="mcp/postgres.json")
        self.descriptor = {
            "name": "postgres",
            "description": "MCP server for PostgreSQL",
            "server": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-postgres"],
            },
        }
        self.spec = MergeSpec(file=".mcp.json", json_path="mcpServers", mode="key")

    def test_golden_mergejson(self):
        result = planners.plan_mcp(self.art, self.descriptor, self.spec, {})
        self.assertEqual(
            result,
            Ok(
                (
                    MergeJson(
                        file=".mcp.json",
                        json_path="mcpServers",
                        mode="key",
                        value={
                            "command": "npx",
                            "args": ["-y", "@modelcontextprotocol/server-postgres"],
                        },
                        identity=("postgres",),
                    ),
                )
            ),
        )

    def test_idempotent_install_same_value_ok(self):
        existing = {"mcpServers": {"postgres": self.descriptor["server"]}}
        result = planners.plan_mcp(self.art, self.descriptor, self.spec, existing)
        self.assertIsInstance(result, Ok)

    def test_collision_without_force_is_err(self):
        existing = {"mcpServers": {"postgres": {"command": "other-binary"}}}
        result = planners.plan_mcp(self.art, self.descriptor, self.spec, existing)
        self.assertIsInstance(result, Err)
        self.assertIn("force", result.reason)

    def test_collision_with_force_overwrites(self):
        existing = {"mcpServers": {"postgres": {"command": "other-binary"}}}
        result = planners.plan_mcp(self.art, self.descriptor, self.spec, existing, force=True)
        self.assertIsInstance(result, Ok)


# --------------------------------------------------------------------------- #
# plan_hook                                                                    #
# --------------------------------------------------------------------------- #
class HookPlannerTests(unittest.TestCase):
    def setUp(self):
        self.art = Artifact(type="hook", name="block-secrets", root="hooks/block-secrets")
        self.descriptor = {
            "name": "block-secrets",
            "description": "Block writes that introduce obvious secrets.",
            "events": ["PreToolUse"],
            "matcher": "Edit|Write|MultiEdit",
            "command": "python3 .claude/hooks/block-secrets/guard.py",
            "files": ["scripts/guard.py"],
        }
        self.hooks = claude_profile().hooks

    def test_plan_has_copy_and_mergejson(self):
        result = planners.plan_hook(self.art, self.descriptor, self.hooks, {})
        self.assertIsInstance(result, Ok)
        plan = result.value
        copies = [a for a in plan if isinstance(a, CopyTree)]
        merges = [a for a in plan if isinstance(a, MergeJson)]
        self.assertGreaterEqual(len(copies), 1, "hook plan MUST contain a copy action")
        self.assertEqual(len(merges), 1, "hook plan MUST contain exactly one MergeJson")

    def test_golden_whole_tree_copy(self):
        result = planners.plan_hook(self.art, self.descriptor, self.hooks, {})
        self.assertEqual(
            result,
            Ok(
                (
                    CopyTree(src="hooks/block-secrets", dst=".claude/hooks/block-secrets"),
                    MergeJson(
                        file=".claude/settings.json",
                        json_path="hooks.PreToolUse",
                        mode="list",
                        value={
                            "matcher": "Edit|Write|MultiEdit",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "python3 .claude/hooks/block-secrets/guard.py",
                                }
                            ],
                        },
                        identity=(),
                    ),
                )
            ),
        )


# --------------------------------------------------------------------------- #
# plan_install aggregator                                                      #
# --------------------------------------------------------------------------- #
class PlanInstallTests(unittest.TestCase):
    def setUp(self):
        self.profiles = {"claude": claude_profile()}

    def test_aggregates_multiple_artifacts_and_appends_manifest(self):
        skill = Artifact(type="skill", name="code-review", root="skills/code-review")
        mcp = Artifact(type="mcp", name="postgres", root="mcp/postgres.json")
        request = Request(
            command="install", names=("code-review", "postgres"), profiles=("claude",)
        )
        files = {
            "__targets__": ((skill, "claude"), (mcp, "claude")),
            "__installed_at__": "2026-06-20T00:00:00Z",
            "descriptor:postgres": {"name": "postgres", "server": {"command": "npx"}},
            "source:code-review": "main:abc",
            "source:postgres": "main:abc",
        }
        configs = {"claude": {}}
        result = planners.plan_install(request, None, files, self.profiles, None, configs)
        self.assertIsInstance(result, Ok)
        plan = result.value
        # Last action is the trailing WriteManifest with one entry per target.
        self.assertIsInstance(plan[-1], WriteManifest)
        self.assertEqual(len(plan[-1].entries), 2)
        # Earlier actions: a CopyTree (skill) and a MergeJson (mcp).
        self.assertTrue(any(isinstance(a, CopyTree) for a in plan[:-1]))
        self.assertTrue(any(isinstance(a, MergeJson) for a in plan[:-1]))
        # Manifest proofs: skill has files, mcp has a merge proof.
        by_type = {e.type: e for e in plan[-1].entries}
        self.assertIn(".claude/skills/code-review", by_type["skill"].files)
        self.assertIsNotNone(by_type["mcp"].merge)

    def test_accumulates_multiple_errors_at_once(self):
        # Two failing targets: an mcp collision AND a missing-descriptor hook.
        mcp = Artifact(type="mcp", name="postgres", root="mcp/postgres.json")
        hook = Artifact(type="hook", name="block-secrets", root="hooks/block-secrets")
        request = Request(command="install", profiles=("claude",))  # no force
        files = {
            "__targets__": ((mcp, "claude"), (hook, "claude")),
            "descriptor:postgres": {"name": "postgres", "server": {"command": "npx"}},
            # NOTE: no "descriptor:block-secrets" -> hook target fails too.
        }
        configs = {"claude": {"mcpServers": {"postgres": {"command": "DIFFERENT"}}}}
        result = planners.plan_install(request, None, files, self.profiles, None, configs)
        self.assertIsInstance(result, Err)
        # Both failures are reported, not just the first.
        self.assertIn("force", result.reason)  # mcp collision
        self.assertIn("block-secrets", result.reason)  # missing hook descriptor

    def test_unknown_profile_is_err(self):
        skill = Artifact(type="skill", name="code-review", root="skills/code-review")
        request = Request(command="install", profiles=("nope",))
        files = {"__targets__": ((skill, "nope"),)}
        result = planners.plan_install(request, None, files, self.profiles, None, {})
        self.assertIsInstance(result, Err)
        self.assertIn("nope", result.reason)


if __name__ == "__main__":
    unittest.main()
