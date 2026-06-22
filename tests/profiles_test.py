"""Tests for WP-8: built-in harness profiles + override loader."""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from agent_artifacts.model import (
    CopyTarget,
    GuidelineTarget,
    HookTarget,
    MergeSpec,
    Profile,
)
from agent_artifacts.profiles.builtin import builtin
from agent_artifacts.profiles.loader import _profile_from_dict, load_profiles


class TestBuiltinProfiles(unittest.TestCase):
    """The four built-in profiles exist and have expected key fields."""

    def test_all_builtin_profiles_exist(self) -> None:
        profiles = builtin()
        self.assertEqual(
            set(profiles.keys()), {"claude", "opencode", "tabnine", "vibe"}
        )

    def test_all_values_are_profile_instances(self) -> None:
        for name, profile in builtin().items():
            with self.subTest(name=name):
                self.assertIsInstance(profile, Profile)
                self.assertEqual(profile.name, name)

    # ------------------------------------------------------------------ #
    # Claude                                                              #
    # ------------------------------------------------------------------ #
    def test_claude_skills(self) -> None:
        p = builtin()["claude"]
        self.assertIsInstance(p.skills, CopyTarget)
        self.assertEqual(p.skills.dir, ".claude/skills/<name>/")

    def test_claude_guidelines(self) -> None:
        p = builtin()["claude"]
        self.assertIsInstance(p.guidelines, GuidelineTarget)
        self.assertEqual(p.guidelines.mode, "append-sentinel")
        self.assertEqual(p.guidelines.dest, "CLAUDE.md")

    def test_claude_mcp(self) -> None:
        p = builtin()["claude"]
        self.assertIsInstance(p.mcp, MergeSpec)
        self.assertEqual(p.mcp.file, ".mcp.json")
        self.assertEqual(p.mcp.json_path, "mcpServers")
        self.assertEqual(p.mcp.mode, "key")

    def test_claude_hooks(self) -> None:
        p = builtin()["claude"]
        self.assertIsInstance(p.hooks, HookTarget)
        self.assertEqual(p.hooks.scripts_dir, ".claude/hooks/<name>/")
        self.assertIn("PreToolUse", p.hooks.events)
        self.assertIn("PostToolUse", p.hooks.events)
        self.assertIn("Stop", p.hooks.events)
        self.assertEqual(p.hooks.merge.file, ".claude/settings.json")
        self.assertEqual(p.hooks.merge.mode, "list")
        self.assertEqual(p.hooks.merge.identity, ("matcher", "command"))
        self.assertIsNotNone(p.hooks.merge.entry_template)

    # ------------------------------------------------------------------ #
    # OpenCode                                                            #
    # ------------------------------------------------------------------ #
    def test_opencode_skills(self) -> None:
        p = builtin()["opencode"]
        self.assertEqual(p.skills.dir, ".opencode/skills/<name>/")

    def test_opencode_guidelines(self) -> None:
        p = builtin()["opencode"]
        self.assertEqual(p.guidelines.mode, "append-sentinel")
        self.assertEqual(p.guidelines.dest, "AGENTS.md")

    def test_opencode_mcp(self) -> None:
        p = builtin()["opencode"]
        self.assertEqual(p.mcp.file, "opencode.json")
        self.assertEqual(p.mcp.json_path, "mcp")
        self.assertEqual(p.mcp.mode, "key")

    def test_opencode_hooks(self) -> None:
        p = builtin()["opencode"]
        self.assertEqual(p.hooks.scripts_dir, ".opencode/hooks/<name>/")
        self.assertIsInstance(p.hooks.merge, MergeSpec)

    # ------------------------------------------------------------------ #
    # Tabnine                                                             #
    # ------------------------------------------------------------------ #
    def test_tabnine_skills(self) -> None:
        p = builtin()["tabnine"]
        self.assertEqual(p.skills.dir, ".tabnine/agent/skills/<name>/")

    def test_tabnine_guidelines(self) -> None:
        p = builtin()["tabnine"]
        self.assertEqual(p.guidelines.mode, "copy")
        self.assertEqual(p.guidelines.dest, ".tabnine/guidelines/")

    def test_tabnine_mcp(self) -> None:
        # Corrected paths (DESIGN-agents.md §6): settings.json, not config.json.
        p = builtin()["tabnine"]
        self.assertIsInstance(p.mcp, MergeSpec)
        self.assertEqual(p.mcp.file, ".tabnine/agent/settings.json")
        self.assertEqual(p.mcp.json_path, "mcpServers")
        self.assertEqual(p.mcp.mode, "key")

    def test_tabnine_hooks(self) -> None:
        # Corrected paths/events (DESIGN-agents.md §6/§6.2).
        p = builtin()["tabnine"]
        self.assertIsInstance(p.hooks, HookTarget)
        self.assertEqual(p.hooks.scripts_dir, ".tabnine/agent/hooks/<name>/")
        self.assertEqual(p.hooks.events["PreToolUse"], "hooks.BeforeTool")
        self.assertEqual(p.hooks.events["PostToolUse"], "hooks.AfterTool")
        self.assertEqual(p.hooks.events["Stop"], "hooks.SessionEnd")
        self.assertEqual(p.hooks.merge.file, ".tabnine/agent/settings.json")
        self.assertEqual(p.hooks.merge.json_path, "hooks.BeforeTool")
        self.assertEqual(p.hooks.merge.mode, "list")

    # ------------------------------------------------------------------ #
    # Immutability                                                        #
    # ------------------------------------------------------------------ #
    def test_builtin_mapping_is_read_only(self) -> None:
        profiles = builtin()
        with self.assertRaises(TypeError):
            profiles["new"] = None  # type: ignore[index]


class TestLoadProfilesNoOverride(unittest.TestCase):
    """load_profiles without a project or with a missing override file."""

    def test_no_project(self) -> None:
        profiles = load_profiles()
        self.assertEqual(
            set(profiles.keys()), {"claude", "opencode", "tabnine", "vibe"}
        )

    def test_nonexistent_project(self) -> None:
        profiles = load_profiles(project="/nonexistent/path/that/does/not/exist")
        self.assertEqual(
            set(profiles.keys()), {"claude", "opencode", "tabnine", "vibe"}
        )

    def test_project_without_override_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            profiles = load_profiles(project=tmp)
            self.assertEqual(
                set(profiles.keys()), {"claude", "opencode", "tabnine", "vibe"}
            )


class TestLoadProfilesOverride(unittest.TestCase):
    """load_profiles with a project override file."""

    def _write_override(self, tmp: str, data: dict) -> None:
        override_dir = os.path.join(tmp, ".agent-artifacts")
        os.makedirs(override_dir, exist_ok=True)
        with open(os.path.join(override_dir, "profiles.json"), "w", encoding="utf-8") as fh:
            json.dump(data, fh)

    def test_override_claude_skills_dir(self) -> None:
        """Overriding claude's skills dir is reflected after load_profiles."""
        override = {
            "claude": {
                "name": "claude",
                "skills": {"dir": ".custom-claude/skills/<name>/"},
                "guidelines": {"mode": "append-sentinel", "dest": "CLAUDE.md"},
                "mcp": {"file": ".mcp.json", "json_path": "mcpServers", "mode": "key"},
                "hooks": {
                    "scripts_dir": ".claude/hooks/<name>/",
                    "events": {"PreToolUse": "hooks.PreToolUse"},
                    "merge": {
                        "file": ".claude/settings.json",
                        "json_path": "hooks.PreToolUse",
                        "mode": "list",
                        "identity": ["matcher", "command"],
                    },
                },
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            self._write_override(tmp, override)
            profiles = load_profiles(project=tmp)

            # The overridden claude profile has the custom skills dir
            self.assertEqual(profiles["claude"].skills.dir, ".custom-claude/skills/<name>/")
            # But opencode and tabnine are still the built-in defaults
            self.assertEqual(profiles["opencode"].skills.dir, ".opencode/skills/<name>/")
            self.assertEqual(profiles["tabnine"].skills.dir, ".tabnine/agent/skills/<name>/")

    def test_add_antigravity_profile(self) -> None:
        """Adding a NEW 'antigravity' record via the override file loads as a fourth profile."""
        override = {
            "antigravity": {
                "name": "antigravity",
                "skills": {"dir": ".antigravity/skills/<name>/"},
                "guidelines": {"mode": "append-sentinel", "dest": "AGENTS.md"},
                "mcp": {
                    "file": ".antigravity/config.json",
                    "json_path": "mcp.servers",
                    "mode": "key",
                },
                "hooks": {
                    "scripts_dir": ".antigravity/hooks/<name>/",
                    "events": {"PreToolUse": "hooks.PreToolUse"},
                    "merge": {
                        "file": ".antigravity/config.json",
                        "json_path": "hooks",
                        "mode": "list",
                    },
                },
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            self._write_override(tmp, override)
            profiles = load_profiles(project=tmp)

            self.assertEqual(len(profiles), 5)  # 4 built-ins + antigravity
            self.assertIn("antigravity", profiles)
            ag = profiles["antigravity"]
            self.assertIsInstance(ag, Profile)
            self.assertEqual(ag.name, "antigravity")
            self.assertEqual(ag.skills.dir, ".antigravity/skills/<name>/")
            self.assertEqual(ag.guidelines.mode, "append-sentinel")
            self.assertEqual(ag.guidelines.dest, "AGENTS.md")
            self.assertEqual(ag.mcp.file, ".antigravity/config.json")
            self.assertEqual(ag.mcp.json_path, "mcp.servers")
            self.assertEqual(ag.hooks.scripts_dir, ".antigravity/hooks/<name>/")

    def test_result_mapping_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            profiles = load_profiles(project=tmp)
            with self.assertRaises(TypeError):
                profiles["new"] = None  # type: ignore[index]


class TestProfileFromDict(unittest.TestCase):
    """_profile_from_dict correctly builds Profile records from JSON-parsed dicts."""

    def test_minimal_record(self) -> None:
        record = {
            "name": "test",
            "skills": {"dir": "test/skills/<name>/"},
            "guidelines": {"mode": "copy", "dest": "test/guidelines/"},
            "mcp": {"file": "test.json", "json_path": "mcp", "mode": "key"},
            "hooks": {
                "scripts_dir": "test/hooks/<name>/",
                "events": {},
                "merge": {
                    "file": "test.json",
                    "json_path": "hooks",
                    "mode": "list",
                },
            },
        }
        p = _profile_from_dict(record)
        self.assertEqual(p.name, "test")
        self.assertEqual(p.skills.dir, "test/skills/<name>/")
        self.assertEqual(p.guidelines.mode, "copy")
        self.assertEqual(p.mcp.mode, "key")
        self.assertEqual(p.hooks.merge.mode, "list")
        # Default identity and entry_template
        self.assertEqual(p.mcp.identity, ())
        self.assertIsNone(p.mcp.entry_template)

    def test_record_with_entry_template(self) -> None:
        record = {
            "name": "tmpl",
            "skills": {"dir": "s/"},
            "guidelines": {"mode": "copy", "dest": "g/"},
            "mcp": {"file": "m.json", "json_path": "mcp", "mode": "key"},
            "hooks": {
                "scripts_dir": "h/",
                "events": {"PreToolUse": "hooks.pre"},
                "merge": {
                    "file": "h.json",
                    "json_path": "hooks.PreToolUse",
                    "mode": "list",
                    "identity": ["matcher"],
                    "entry_template": {"matcher": "${matcher}"},
                },
            },
        }
        p = _profile_from_dict(record)
        self.assertEqual(p.hooks.merge.identity, ("matcher",))
        self.assertIsNotNone(p.hooks.merge.entry_template)
        self.assertEqual(p.hooks.merge.entry_template["matcher"], "${matcher}")


if __name__ == "__main__":
    unittest.main()
