"""Tests for WP-28: memory targets, the corrected tabnine record, the vibe
partial profile, and the loader's tolerance of partial / memory overrides."""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from agent_artifacts.model import MemoryTarget, Profile
from agent_artifacts.profiles.builtin import builtin
from agent_artifacts.profiles.loader import _profile_from_dict, load_profiles


class TestMemoryTargets(unittest.TestCase):
    """Each built-in profile carries the expected `memory` target (DESIGN-memory §4)."""

    def test_claude_memory_is_file_claude_md(self) -> None:
        a = builtin()["claude"].memory
        self.assertIsInstance(a, MemoryTarget)
        self.assertEqual(a.kind, "file")
        self.assertEqual(a.dest, "CLAUDE.md")

    def test_opencode_memory_is_file_memory_md(self) -> None:
        a = builtin()["opencode"].memory
        self.assertIsInstance(a, MemoryTarget)
        self.assertEqual(a.kind, "file")
        self.assertEqual(a.dest, "AGENTS.md")

    def test_vibe_memory_is_file_memory_md(self) -> None:
        a = builtin()["vibe"].memory
        self.assertIsInstance(a, MemoryTarget)
        self.assertEqual(a.kind, "file")
        self.assertEqual(a.dest, "AGENTS.md")

    def test_tabnine_memory_is_file_tabnine_md(self) -> None:
        a = builtin()["tabnine"].memory
        self.assertIsInstance(a, MemoryTarget)
        self.assertEqual(a.kind, "file")
        self.assertEqual(a.dest, "TABNINE.md")


class TestVibePartialProfile(unittest.TestCase):
    """The new vibe profile is a legitimate partial profile (DESIGN-memory §7.2)."""

    def test_vibe_is_a_profile(self) -> None:
        v = builtin()["vibe"]
        self.assertIsInstance(v, Profile)
        self.assertEqual(v.name, "vibe")

    def test_vibe_skills_and_guidelines(self) -> None:
        v = builtin()["vibe"]
        self.assertEqual(v.skills.dir, ".vibe/skills/<name>/")
        self.assertEqual(v.guidelines.dest, ".vibe/guidelines/")

    def test_vibe_mcp_and_hooks_are_none(self) -> None:
        v = builtin()["vibe"]
        self.assertIsNone(v.mcp)
        self.assertIsNone(v.hooks)


class TestTabnineCorrectedTargets(unittest.TestCase):
    """The corrected tabnine MCP/hooks targets (DESIGN-memory §6/§6.1/§6.2)."""

    def test_tabnine_mcp_in_settings_json(self) -> None:
        m = builtin()["tabnine"].mcp
        self.assertEqual(m.file, ".tabnine/agent/settings.json")
        self.assertEqual(m.json_path, "mcpServers")
        self.assertEqual(m.mode, "key")

    def test_tabnine_hooks_scripts_and_merge(self) -> None:
        h = builtin()["tabnine"].hooks
        self.assertEqual(h.scripts_dir, ".tabnine/agent/hooks/<name>/")
        self.assertEqual(h.merge.file, ".tabnine/agent/settings.json")
        self.assertEqual(h.merge.json_path, "hooks.BeforeTool")
        self.assertEqual(h.merge.mode, "list")

    def test_tabnine_hook_event_vocabulary(self) -> None:
        events = builtin()["tabnine"].hooks.events
        self.assertEqual(events["PreToolUse"], "hooks.BeforeTool")
        self.assertEqual(events["PostToolUse"], "hooks.AfterTool")
        self.assertEqual(events["Stop"], "hooks.SessionEnd")


class TestLoaderMemoryTarget(unittest.TestCase):
    """_profile_from_dict parses an `memory` section into an MemoryTarget."""

    def test_memory_override_parsed(self) -> None:
        record = {
            "name": "withmemory",
            "skills": {"dir": "s/<name>/"},
            "guidelines": {"dest": ".x/guidelines/"},
            "mcp": {"file": "m.json", "json_path": "mcp", "mode": "key"},
            "hooks": {
                "scripts_dir": "h/<name>/",
                "events": {"PreToolUse": "hooks.pre"},
                "merge": {"file": "h.json", "json_path": "hooks", "mode": "list"},
            },
            "memory": {"kind": "file", "dest": "AGENTS.md"},
        }
        p = _profile_from_dict(record)
        self.assertIsInstance(p.memory, MemoryTarget)
        self.assertEqual(p.memory.kind, "file")
        self.assertEqual(p.memory.dest, "AGENTS.md")

    def test_memory_dir_override_parsed(self) -> None:
        record = {
            "name": "tn-like",
            "memory": {"kind": "dir", "dest": ".x/guidelines/"},
        }
        p = _profile_from_dict(record)
        self.assertEqual(p.memory.kind, "dir")
        self.assertEqual(p.memory.dest, ".x/guidelines/")


class TestLoaderPartialProfile(unittest.TestCase):
    """A record omitting a type section yields None (no KeyError) — partial profiles load."""

    def test_partial_record_omitting_mcp_loads(self) -> None:
        record = {
            "name": "partial",
            "skills": {"dir": ".partial/skills/<name>/"},
            "guidelines": {"dest": ".x/guidelines/"},
            # no "mcp", no "hooks"
            "memory": {"kind": "file", "dest": "AGENTS.md"},
        }
        p = _profile_from_dict(record)  # must not raise
        self.assertEqual(p.name, "partial")
        self.assertIsNone(p.mcp)
        self.assertIsNone(p.hooks)
        self.assertEqual(p.skills.dir, ".partial/skills/<name>/")
        self.assertEqual(p.memory.dest, "AGENTS.md")

    def test_name_only_record_is_all_none(self) -> None:
        p = _profile_from_dict({"name": "bare"})
        self.assertEqual(p.name, "bare")
        self.assertIsNone(p.skills)
        self.assertIsNone(p.guidelines)
        self.assertIsNone(p.mcp)
        self.assertIsNone(p.hooks)
        self.assertIsNone(p.memory)

    def test_partial_override_loaded_via_load_profiles(self) -> None:
        override = {
            "vibe-custom": {
                "name": "vibe-custom",
                "skills": {"dir": ".vibe/skills/<name>/"},
                "guidelines": {"dest": ".x/guidelines/"},
                "memory": {"kind": "file", "dest": "AGENTS.md"},
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            override_dir = os.path.join(tmp, ".agent-artifacts")
            os.makedirs(override_dir, exist_ok=True)
            with open(os.path.join(override_dir, "profiles.json"), "w", encoding="utf-8") as fh:
                json.dump(override, fh)

            profiles = load_profiles(project=tmp)
            self.assertIn("vibe-custom", profiles)
            vc = profiles["vibe-custom"]
            self.assertIsNone(vc.mcp)
            self.assertIsNone(vc.hooks)
            self.assertEqual(vc.memory.kind, "file")


if __name__ == "__main__":
    unittest.main()
