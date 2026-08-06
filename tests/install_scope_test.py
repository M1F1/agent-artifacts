"""Issue #19 TDD contracts for project/user installation scope."""

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
from agent_artifacts.commands import _common, check, install, status, uninstall, update
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


class ScopeStateAndCliTests(unittest.TestCase):
    def test_manifest_roots_are_separate(self):
        project_request = Request(command="status", project="/consumer", user_home="/fake/home")
        user_request = Request(command="status", scope="user", user_home="/fake/home")

        self.assertEqual(
            _common.manifest_path(_common.manifest_root(project_request)),
            "/consumer/.agent-artifacts/manifest.json",
        )
        self.assertEqual(
            _common.manifest_path(_common.manifest_root(user_request)),
            "/fake/home/.agent-artifacts/manifest.json",
        )

    def test_cli_parses_scope_and_keeps_project_default(self):
        commands = (
            ["install", "code-review", "--profile", "claude"],
            ["status"],
            ["check"],
            ["update"],
            ["uninstall", "code-review", "--profile", "claude"],
        )
        for argv in commands:
            with self.subTest(command=argv[0]):
                user = cli._to_request(cli.build_parser().parse_args([*argv, "--scope", "user"]))
                project = cli._to_request(cli.build_parser().parse_args(argv))
                self.assertEqual(user.scope, "user")
                self.assertEqual(project.scope, "project")

    def test_user_scope_with_project_fails_before_dispatch(self):
        with mock.patch.dict(cli.DISPATCH, {"install": mock.Mock(return_value=0)}, clear=False):
            dispatch = cli.DISPATCH["install"]
            with redirect_stderr(io.StringIO()) as err:
                code = cli.main(
                    [
                        "install",
                        "code-review",
                        "--profile",
                        "claude",
                        "--scope",
                        "user",
                        "--project",
                        "/consumer",
                    ]
                )
        self.assertEqual(code, 2)
        self.assertIn("--scope user", err.getvalue())
        dispatch.assert_not_called()

    def test_command_boundaries_reject_user_scope_with_project_before_io(self):
        request = Request(
            command="install",
            scope="user",
            project="/consumer",
            user_home="/fake/home",
        )
        cases = (
            (install.run, mock.patch.object(install, "open_source")),
            (status.run, mock.patch.object(_common, "load_manifest")),
            (check.run, mock.patch.object(check.net, "resolve_ref")),
            (update.run, mock.patch.object(_common, "load_manifest")),
            (uninstall.run, mock.patch.object(_common, "load_manifest")),
        )

        for runner, io_patch in cases:
            with self.subTest(command=runner.__module__), io_patch as touched:
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    self.assertEqual(runner(request), 2)
                touched.assert_not_called()


class UserScopeLifecycleTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self._tmp.name)
        self.home = root / "home"
        self.project = root / "project"
        self.home.mkdir()
        self.project.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _user_request(self, command: str, **kwargs) -> Request:
        values = {
            "command": command,
            "scope": "user",
            "user_home": str(self.home),
            "source_dir": FIXTURES,
        }
        values.update(kwargs)
        return Request(**values)

    def _run_quiet(self, request: Request) -> int:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return {
                "install": install.run,
                "status": status.run,
                "update": update.run,
                "uninstall": uninstall.run,
            }[request.command](request)

    def _manifest(self) -> dict:
        return json.loads((self.home / ".agent-artifacts" / "manifest.json").read_text())

    def test_supported_matrix_installs_only_inside_fake_home(self):
        code = self._run_quiet(
            self._user_request(
                "install",
                all=True,
                profiles=("claude", "opencode", "tabnine", "vibe"),
            )
        )
        self.assertEqual(code, 0)

        expected = (
            self.home / ".claude" / "skills" / "code-review" / "SKILL.md",
            self.home / ".claude" / "rules" / "python-style.md",
            self.home / ".claude.json",
            self.home / ".claude" / "hooks" / "block-secrets" / "scripts" / "guard.py",
            self.home / ".claude" / "CLAUDE.md",
            self.home / ".config" / "opencode" / "skills" / "code-review" / "SKILL.md",
            self.home / ".config" / "opencode" / "opencode.json",
            self.home / ".config" / "opencode" / "AGENTS.md",
            self.home / ".tabnine" / "guidelines" / "python-style.md",
            self.home / ".tabnine" / "mcp_servers.json",
            self.home / ".vibe" / "skills" / "code-review" / "SKILL.md",
        )
        for path in expected:
            with self.subTest(path=path):
                self.assertTrue(path.exists())
                self.assertTrue(path.is_relative_to(self.home))

        manifest = self._manifest()
        self.assertEqual(
            {entry["profile"] for entry in manifest["installed"]},
            {"claude", "opencode", "tabnine", "vibe"},
        )
        serialized = json.dumps(manifest)
        self.assertNotIn("DATABASE_URL", serialized)
        self.assertNotIn("@modelcontextprotocol/server-postgres", serialized)
        claude_settings = json.loads(
            (self.home / ".claude" / "settings.json").read_text(encoding="utf-8")
        )
        hook_command = claude_settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        hook_script = self.home / ".claude" / "hooks" / "block-secrets" / "scripts" / "guard.py"
        self.assertEqual(hook_command, f"python3 {hook_script}")
        self.assertTrue(hook_script.exists())
        for entry in manifest["installed"]:
            for path in entry["files"]:
                self.assertTrue(os.path.isabs(path))
                self.assertTrue(pathlib.Path(path).is_relative_to(self.home))
            if "merge" in entry:
                self.assertTrue(os.path.isabs(entry["merge"]["file"]))
                self.assertTrue(pathlib.Path(entry["merge"]["file"]).is_relative_to(self.home))

    def test_explicit_unsupported_combination_uses_declared_reason(self):
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            code = install.run(
                self._user_request(
                    "install",
                    names=("house",),
                    profiles=("vibe",),
                )
            )
        self.assertEqual(code, 2)
        self.assertIn("no documented always-loaded global instruction file", err.getvalue())
        self.assertFalse((self.home / ".agent-artifacts" / "manifest.json").exists())

    def test_user_hook_uninstall_removes_only_its_global_registration(self):
        request = self._user_request(
            "install",
            names=("block-secrets",),
            profiles=("claude",),
        )
        self.assertEqual(self._run_quiet(request), 0)

        settings_path = self.home / ".claude" / "settings.json"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        foreign = {
            "matcher": "Bash",
            "hooks": [{"type": "command", "command": "python3 /foreign/hook.py"}],
        }
        settings["hooks"]["PreToolUse"].insert(0, foreign)
        settings_path.write_text(json.dumps(settings), encoding="utf-8")

        self.assertEqual(
            self._run_quiet(
                self._user_request(
                    "uninstall",
                    names=("block-secrets",),
                    profiles=("claude",),
                )
            ),
            0,
        )
        remaining = json.loads(settings_path.read_text(encoding="utf-8"))
        self.assertEqual(remaining["hooks"]["PreToolUse"], [foreign])
        self.assertFalse((self.home / ".claude" / "hooks" / "block-secrets").exists())

    def test_project_and_user_lifecycles_never_cross_manifests_or_effects(self):
        project_install = Request(
            command="install",
            source_dir=FIXTURES,
            project=str(self.project),
            names=("code-review",),
            profiles=("claude",),
        )
        self.assertEqual(self._run_quiet(project_install), 0)
        self.assertEqual(
            self._run_quiet(
                self._user_request("install", names=("code-review",), profiles=("claude",))
            ),
            0,
        )

        project_skill = self.project / ".claude" / "skills" / "code-review" / "SKILL.md"
        user_skill = self.home / ".claude" / "skills" / "code-review" / "SKILL.md"
        project_manifest = self.project / ".agent-artifacts" / "manifest.json"
        user_manifest = self.home / ".agent-artifacts" / "manifest.json"
        self.assertTrue(project_skill.exists())
        self.assertTrue(user_skill.exists())

        project_before = project_manifest.read_bytes()
        self.assertEqual(self._run_quiet(self._user_request("status", json=True)), 0)
        self.assertEqual(self._run_quiet(self._user_request("update")), 0)
        self.assertEqual(project_manifest.read_bytes(), project_before)
        self.assertTrue(project_skill.exists())

        self.assertEqual(
            self._run_quiet(
                self._user_request(
                    "uninstall",
                    names=("code-review",),
                    profiles=("claude",),
                )
            ),
            0,
        )
        self.assertFalse(user_skill.exists())
        self.assertTrue(project_skill.exists())
        self.assertTrue(project_manifest.exists())
        self.assertEqual(json.loads(user_manifest.read_text())["installed"], [])

    def test_user_symlink_lifecycle_removes_only_fake_home_link(self):
        request = self._user_request(
            "install",
            names=("code-review",),
            profiles=("claude",),
            install_mode="symlink",
        )
        self.assertEqual(self._run_quiet(request), 0)

        destination = self.home / ".claude" / "skills" / "code-review"
        source_target = pathlib.Path(FIXTURES) / "skills" / "code-review"
        self.assertTrue(destination.is_symlink())
        self.assertEqual(pathlib.Path(os.readlink(destination)), source_target)
        entry = self._manifest()["installed"][0]
        self.assertEqual(entry["install"]["mode"], "symlink")
        self.assertEqual(entry["install"]["links"][0]["path"], str(destination))

        self.assertEqual(self._run_quiet(self._user_request("status", json=True)), 0)
        self.assertEqual(self._run_quiet(self._user_request("update")), 0)
        self.assertTrue(destination.is_symlink())

        self.assertEqual(
            self._run_quiet(
                self._user_request(
                    "uninstall",
                    names=("code-review",),
                    profiles=("claude",),
                )
            ),
            0,
        )
        self.assertFalse(os.path.lexists(destination))
        self.assertTrue((source_target / "SKILL.md").exists())
