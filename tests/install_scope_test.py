"""Issue #19 TDD contracts for project/user installation scope.

The legacy-command lifecycle half of this module was removed with the legacy consumer
verbs; canonical user-scope lifecycle lives in ``canonical_install_planning_test`` and
``marketplace_lifecycle_e2e_test``.
"""

from __future__ import annotations

import io
import json
import os
import pathlib
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from agent_artifacts import cli
from agent_artifacts.model import Request
from agent_artifacts.profiles.builtin import builtin
from agent_artifacts.profiles.loader import load_profiles
from agent_artifacts.profiles.scope import profile_for_scope, support_for

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = str(REPO_ROOT / "tests" / "fixtures")
ARTIFACT_TYPES = ("skill", "guideline", "mcp", "hook", "memory")


class ScopeDomainTests(unittest.TestCase):
    def test_request_defaults_to_project_scope(self):
        self.assertEqual(Request(command="status").scope, "project")

    def test_project_projection_is_the_original_profile(self):
        claude = builtin()["claude"]
        self.assertIs(profile_for_scope(claude, "project", "/unused"), claude)

    def test_user_projection_expands_every_claude_target_under_injected_home(self):
        claude = profile_for_scope(builtin()["claude"], "user", "/fake/home")

        self.assertEqual(claude.skills.dir, "/fake/home/.claude/skills/<name>/")
        self.assertEqual(claude.guidelines.dest, "/fake/home/.claude/rules/")
        self.assertEqual(claude.mcp.file, "/fake/home/.claude.json")
        self.assertEqual(claude.hooks.scripts_dir, "/fake/home/.claude/hooks/<name>/")
        self.assertEqual(claude.hooks.merge.file, "/fake/home/.claude/settings.json")
        self.assertEqual(claude.memory.dest, "/fake/home/.claude/CLAUDE.md")

    def test_official_user_target_matrix_is_explicit(self):
        expected_supported = {
            "claude": set(ARTIFACT_TYPES),
            "opencode": {"skill", "mcp", "memory"},
            "tabnine": {"guideline", "mcp"},
            "vibe": {"skill"},
        }

        for profile_name, profile in builtin().items():
            for artifact_type in ARTIFACT_TYPES:
                with self.subTest(profile=profile_name, artifact_type=artifact_type):
                    decision = support_for(profile, "user", artifact_type)
                    self.assertEqual(
                        decision.supported, artifact_type in expected_supported[profile_name]
                    )
                    if not decision.supported:
                        self.assertTrue(decision.reason)
                        self.assertNotIn("unsupported-type", decision.reason)

    def test_non_claude_official_paths_are_not_derived_from_project_paths(self):
        home = "/fake/home"
        opencode = profile_for_scope(builtin()["opencode"], "user", home)
        tabnine = profile_for_scope(builtin()["tabnine"], "user", home)
        vibe = profile_for_scope(builtin()["vibe"], "user", home)

        self.assertEqual(opencode.skills.dir, f"{home}/.config/opencode/skills/<name>/")
        self.assertEqual(opencode.mcp.file, f"{home}/.config/opencode/opencode.json")
        self.assertEqual(opencode.memory.dest, f"{home}/.config/opencode/AGENTS.md")
        self.assertEqual(tabnine.guidelines.dest, f"{home}/.tabnine/guidelines/")
        self.assertEqual(tabnine.mcp.file, f"{home}/.tabnine/mcp_servers.json")
        self.assertEqual(vibe.skills.dir, f"{home}/.vibe/skills/<name>/")

    def test_custom_profile_loads_explicit_user_targets_and_reasons(self):
        with tempfile.TemporaryDirectory() as project:
            state = pathlib.Path(project) / ".agent-artifacts"
            state.mkdir()
            (state / "profiles.json").write_text(
                json.dumps(
                    {
                        "custom": {
                            "name": "custom",
                            "skills": {"dir": ".custom/skills/<name>/"},
                            "user": {
                                "skills": {"dir": "~/.custom/skills/<name>/"},
                                "unsupported": {"guideline": "custom has no user guideline target"},
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )

            profile = load_profiles(project)["custom"]
            projected = profile_for_scope(profile, "user", "/fake/home")

        self.assertEqual(projected.skills.dir, "/fake/home/.custom/skills/<name>/")
        self.assertEqual(
            support_for(profile, "user", "guideline").reason,
            "custom has no user guideline target",
        )
        self.assertEqual(support_for(profile, "user", "hook").reason, "")

    def test_custom_profile_rejects_malformed_unsupported_reasons(self):
        for malformed in (("not-an-object",), {"hook": ""}, {"other": "no target"}):
            with self.subTest(malformed=malformed), tempfile.TemporaryDirectory() as project:
                state = pathlib.Path(project) / ".agent-artifacts"
                state.mkdir()
                (state / "profiles.json").write_text(
                    json.dumps(
                        {
                            "custom": {
                                "name": "custom",
                                "user": {"unsupported": malformed},
                            }
                        }
                    ),
                    encoding="utf-8",
                )
                with self.assertRaises(ValueError):
                    load_profiles(project)
