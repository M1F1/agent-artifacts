"""WP-14 uninstall tests: reverse files AND merges, ours-only (DESIGN.md §10/§12).

Builds a temp project with a known install (manifest + on-disk state constructed directly,
matching exactly what the WP-12 install command would produce), then drives
``commands.uninstall.run`` and asserts full reversal:

- a **hook** (files + list-mode merge): script gone, registration dropped from
  ``.claude/settings.json``, file removed when it was the only entry and we created it,
  manifest entry gone;
- an **mcp** (key-mode merge): our key dropped from ``.mcp.json``, foreign keys preserved;
- a **guideline** (copy): our standalone reference doc removed from ``.claude/guidelines/``.

Run: ``python -m unittest discover -s tests -p "uninstall_test.py" -v``
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout

from agent_artifacts.commands import uninstall
from agent_artifacts.manifest import dump_manifest
from agent_artifacts.model import (
    Manifest,
    ManifestEntry,
    MergeProof,
    Request,
)


# --------------------------------------------------------------------------- #
# Manifest entries mirroring a real WP-12 install (see tests/manifest_test.py). #
# --------------------------------------------------------------------------- #
def _hook_entry() -> ManifestEntry:
    return ManifestEntry(
        artifact="block-secrets",
        type="hook",
        profile="claude",
        source="main:abc",
        bundle="base",
        files={".claude/hooks/block-secrets/guard.py": "sha256:ccc"},
        merge=MergeProof(
            file=".claude/settings.json",
            json_path="hooks.PreToolUse",
            mode="list",
            identity={
                "matcher": "Edit|Write|MultiEdit",
                "command": "python3 .claude/hooks/block-secrets/guard.py",
            },
            value_hash="sha256:ddd",
            created_file=True,  # this install created settings.json
        ),
        installed_at="2026-06-20T00:00:00Z",
    )


def _mcp_entry() -> ManifestEntry:
    return ManifestEntry(
        artifact="postgres",
        type="mcp",
        profile="claude",
        source="main:abc",
        bundle="backend",
        merge=MergeProof(
            file=".mcp.json",
            json_path="mcpServers.postgres",
            mode="key",
            identity={},
            value_hash="sha256:bbb",
            created_file=False,  # foreign keys present -> file pre-existed
        ),
        installed_at="2026-06-20T00:00:00Z",
    )


def _guideline_entry() -> ManifestEntry:
    # Guidelines are standalone copy files in a per-harness dir — not merged into the memory
    # file — so uninstall removes the whole file like any other copied artifact.
    return ManifestEntry(
        artifact="python-style",
        type="guideline",
        profile="claude",
        source="main:abc",
        files={".claude/guidelines/python-style.md": "sha256:eee"},
        installed_at="2026-06-20T00:00:00Z",
    )


def _write(project: str, rel: str, content: str) -> str:
    abs_path = os.path.join(project, rel)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(content)
    return abs_path


def _write_manifest(project: str, manifest: Manifest) -> None:
    path = os.path.join(project, ".agent-artifacts", "manifest.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(dump_manifest(manifest))


def _read(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _load_manifest(project: str) -> dict:
    return json.loads(_read(os.path.join(project, ".agent-artifacts", "manifest.json")))


class _Tmp(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.project = self._dir.name
        self.addCleanup(self._dir.cleanup)

    def req(self, **kw) -> Request:
        base = dict(command="uninstall", project=self.project)
        base.update(kw)
        return Request(**base)

    def run_uninstall(self, request: Request) -> int:
        """Invoke the command with stdout captured (commands print their report)."""
        with redirect_stdout(io.StringIO()):
            return uninstall.run(request)


# --------------------------------------------------------------------------- #
# Hook: BOTH files and a list-mode merge.                                       #
# --------------------------------------------------------------------------- #
class HookUninstallTest(_Tmp):
    def test_full_reversal_leaves_config_clean(self):
        script = _write(self.project, ".claude/hooks/block-secrets/guard.py", "print('x')\n")
        settings = os.path.join(self.project, ".claude", "settings.json")
        # Our install created settings.json with exactly our one registration.
        _write(self.project, ".claude/settings.json", json.dumps({
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Edit|Write|MultiEdit",
                        "hooks": [
                            {"type": "command",
                             "command": "python3 .claude/hooks/block-secrets/guard.py"}
                        ],
                    }
                ]
            }
        }, indent=2))
        _write_manifest(self.project, Manifest(repo="org/x", installed=(_hook_entry(),)))

        rc = self.run_uninstall(self.req(names=("block-secrets",)))
        self.assertEqual(rc, uninstall.OK)

        # 1. hook script gone.
        self.assertFalse(os.path.exists(script))
        # 2/3. settings.json was the only entry AND we created it -> file gone (or empty list).
        if os.path.exists(settings):  # tolerate either policy, but our entry must be gone
            data = json.loads(_read(settings))
            self.assertEqual(data.get("hooks", {}).get("PreToolUse", []), [])
        else:
            self.assertFalse(os.path.exists(settings))
        # 4. manifest entry gone.
        self.assertEqual(_load_manifest(self.project)["installed"], [])

    def test_foreign_hook_registration_is_preserved(self):
        _write(self.project, ".claude/hooks/block-secrets/guard.py", "print('x')\n")
        foreign = {
            "matcher": "Bash",
            "hooks": [{"type": "command", "command": "python3 other/thing.py"}],
        }
        ours = {
            "matcher": "Edit|Write|MultiEdit",
            "hooks": [{"type": "command",
                       "command": "python3 .claude/hooks/block-secrets/guard.py"}],
        }
        settings = _write(self.project, ".claude/settings.json", json.dumps(
            {"hooks": {"PreToolUse": [foreign, ours]}}, indent=2))
        # created_file=False here since the file held a foreign entry too.
        entry = _hook_entry()
        entry = ManifestEntry(
            artifact=entry.artifact, type=entry.type, profile=entry.profile,
            source=entry.source, bundle=entry.bundle, files=entry.files,
            merge=MergeProof(
                file=entry.merge.file, json_path=entry.merge.json_path,
                mode=entry.merge.mode, identity=entry.merge.identity,
                value_hash=entry.merge.value_hash, created_file=False,
            ),
            installed_at=entry.installed_at,
        )
        _write_manifest(self.project, Manifest(repo="org/x", installed=(entry,)))

        rc = self.run_uninstall(self.req(names=("block-secrets",)))
        self.assertEqual(rc, uninstall.OK)

        data = json.loads(_read(settings))
        # Foreign entry survives; ours is gone.
        self.assertEqual(data["hooks"]["PreToolUse"], [foreign])


# --------------------------------------------------------------------------- #
# MCP: key-mode merge with a foreign sibling.                                   #
# --------------------------------------------------------------------------- #
class McpUninstallTest(_Tmp):
    def test_our_key_removed_foreign_preserved(self):
        mcp = _write(self.project, ".mcp.json", json.dumps({
            "mcpServers": {
                "postgres": {"command": "npx", "args": ["-y", "x"]},
                "foreign": {"command": "keep-me"},
            }
        }, indent=2))
        _write_manifest(self.project, Manifest(repo="org/x", installed=(_mcp_entry(),)))

        rc = self.run_uninstall(self.req(names=("postgres",)))
        self.assertEqual(rc, uninstall.OK)

        data = json.loads(_read(mcp))
        self.assertNotIn("postgres", data["mcpServers"])
        self.assertIn("foreign", data["mcpServers"])
        self.assertEqual(data["mcpServers"]["foreign"], {"command": "keep-me"})
        self.assertEqual(_load_manifest(self.project)["installed"], [])


# --------------------------------------------------------------------------- #
# Guideline (copy): the standalone reference doc is removed wholesale.           #
# --------------------------------------------------------------------------- #
class GuidelineUninstallTest(_Tmp):
    def test_copy_file_removed(self):
        doc = _write(self.project, ".claude/guidelines/python-style.md", "Fixture body.\n")
        _write_manifest(self.project, Manifest(repo="org/x", installed=(_guideline_entry(),)))

        rc = self.run_uninstall(self.req(names=("python-style",)))
        self.assertEqual(rc, uninstall.OK)

        # The whole guideline file is gone (no sentinel-stripping — it never shared a file).
        self.assertFalse(os.path.exists(doc))
        self.assertEqual(_load_manifest(self.project)["installed"], [])

    def test_foreign_files_in_guidelines_dir_untouched(self):
        doc = _write(self.project, ".claude/guidelines/python-style.md", "Fixture body.\n")
        other = _write(self.project, ".claude/guidelines/hand-written.md", "mine\n")
        _write_manifest(self.project, Manifest(repo="org/x", installed=(_guideline_entry(),)))

        rc = self.run_uninstall(self.req(names=("python-style",)))
        self.assertEqual(rc, uninstall.OK)

        # Only our tracked file is removed; a sibling the user authored stays.
        self.assertFalse(os.path.exists(doc))
        self.assertTrue(os.path.exists(other))


# --------------------------------------------------------------------------- #
# Selection / exit codes.                                                       #
# --------------------------------------------------------------------------- #
class SelectionTest(_Tmp):
    def test_unknown_name_is_usage_error(self):
        _write_manifest(self.project, Manifest(repo="org/x", installed=(_mcp_entry(),)))
        rc = self.run_uninstall(self.req(names=("does-not-exist",)))
        self.assertEqual(rc, uninstall.USAGE)
        # manifest untouched.
        self.assertEqual(len(_load_manifest(self.project)["installed"]), 1)

    def test_no_selection_is_ok_noop(self):
        # Empty manifest, --all -> nothing to do, OK.
        _write_manifest(self.project, Manifest(repo="org/x", installed=()))
        rc = self.run_uninstall(self.req(all=True))
        self.assertEqual(rc, uninstall.OK)

    def test_corrupt_manifest_returns_5(self):
        path = os.path.join(self.project, ".agent-artifacts", "manifest.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("{not valid json")
        rc = self.run_uninstall(self.req(names=("postgres",)))
        self.assertEqual(rc, 5)

    def test_all_removes_everything_and_reverses_each(self):
        _write(self.project, ".claude/hooks/block-secrets/guard.py", "x\n")
        _write(self.project, ".claude/settings.json", json.dumps({
            "hooks": {"PreToolUse": [{
                "matcher": "Edit|Write|MultiEdit",
                "hooks": [{"type": "command",
                           "command": "python3 .claude/hooks/block-secrets/guard.py"}],
            }]}}, indent=2))
        _write(self.project, ".mcp.json", json.dumps(
            {"mcpServers": {"postgres": {"command": "npx"}, "foreign": {"command": "x"}}},
            indent=2))
        guideline = _write(self.project, ".claude/guidelines/python-style.md", "body\n")
        m = Manifest(repo="org/x",
                     installed=(_hook_entry(), _mcp_entry(), _guideline_entry()))
        _write_manifest(self.project, m)

        rc = self.run_uninstall(self.req(all=True))
        self.assertEqual(rc, uninstall.OK)
        self.assertEqual(_load_manifest(self.project)["installed"], [])
        # guideline copy removed.
        self.assertFalse(os.path.exists(guideline))
        # mcp foreign preserved.
        mcp = json.loads(_read(os.path.join(self.project, ".mcp.json")))
        self.assertIn("foreign", mcp["mcpServers"])
        self.assertNotIn("postgres", mcp["mcpServers"])

    def test_profile_filter_scopes_removal(self):
        e_claude = _mcp_entry()
        e_other = ManifestEntry(
            artifact="postgres", type="mcp", profile="opencode", source="main:abc",
            merge=MergeProof(file="opencode.json", json_path="mcp.postgres",
                             mode="key", identity={}, value_hash="x"),
            installed_at="t",
        )
        _write(self.project, ".mcp.json", json.dumps(
            {"mcpServers": {"postgres": {"command": "npx"}}}, indent=2))
        _write(self.project, "opencode.json", json.dumps(
            {"mcp": {"postgres": {"command": "npx"}}}, indent=2))
        _write_manifest(self.project, Manifest(repo="org/x", installed=(e_claude, e_other)))

        rc = self.run_uninstall(self.req(names=("postgres",), profiles=("claude",)))
        self.assertEqual(rc, uninstall.OK)
        installed = _load_manifest(self.project)["installed"]
        # Only the opencode entry survives.
        self.assertEqual(len(installed), 1)
        self.assertEqual(installed[0]["profile"], "opencode")
        # claude .mcp.json pruned, opencode.json untouched.
        self.assertNotIn("postgres",
                         json.loads(_read(os.path.join(self.project, ".mcp.json")))["mcpServers"])
        self.assertIn("postgres",
                      json.loads(_read(os.path.join(self.project, "opencode.json")))["mcp"])


# --------------------------------------------------------------------------- #
# Dry-run touches nothing.                                                       #
# --------------------------------------------------------------------------- #
class DryRunTest(_Tmp):
    def test_dry_run_touches_nothing(self):
        script = _write(self.project, ".claude/hooks/block-secrets/guard.py", "x\n")
        settings = _write(self.project, ".claude/settings.json", json.dumps({
            "hooks": {"PreToolUse": [{
                "matcher": "Edit|Write|MultiEdit",
                "hooks": [{"type": "command",
                           "command": "python3 .claude/hooks/block-secrets/guard.py"}],
            }]}}, indent=2))
        _write_manifest(self.project, Manifest(repo="org/x", installed=(_hook_entry(),)))
        before_manifest = _read(os.path.join(self.project, ".agent-artifacts", "manifest.json"))
        before_settings = _read(settings)

        rc = self.run_uninstall(self.req(names=("block-secrets",), dry_run=True))
        self.assertEqual(rc, uninstall.OK)

        # Nothing changed on disk.
        self.assertTrue(os.path.exists(script))
        self.assertEqual(_read(settings), before_settings)
        self.assertEqual(
            _read(os.path.join(self.project, ".agent-artifacts", "manifest.json")),
            before_manifest,
        )


if __name__ == "__main__":
    unittest.main()
