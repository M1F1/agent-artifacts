"""WP-12 install command — end-to-end integration tests.

Run: ``python -m unittest discover -s tests -p "install_test.py" -v``

These tests drive the real ``install.run`` against the on-disk fixture source
(``tests/fixtures``) and a fresh temp project, then assert the filesystem effects: all four
artifact types land correctly, the manifest is written, multi-profile installs fan out, and
``--dry-run`` / ``--json`` behave per the contract.
"""

import io
import json
import os
import pathlib
import tempfile
import unittest
from contextlib import redirect_stdout

from agent_artifacts.commands import install
from agent_artifacts.model import Request

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = str(REPO_ROOT / "tests" / "fixtures")


def _request(project: str, *, profiles=("claude",), **kwargs) -> Request:
    return Request(
        command="install",
        source_dir=FIXTURES,
        project=project,
        profiles=tuple(profiles),
        all=True,
        **kwargs,
    )


class InstallEndToEndTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def _path(self, *parts) -> str:
        return os.path.join(self.project, *parts)

    # ---- all four types install (single profile) ------------------------- #
    def test_installs_all_five_types_claude(self):
        with redirect_stdout(io.StringIO()):
            code = install.run(_request(self.project))
        self.assertEqual(code, 0)

        # skill: tree copied under .claude/skills/code-review/
        self.assertTrue(os.path.isfile(self._path(".claude", "skills", "code-review", "SKILL.md")))

        # memory: CLAUDE.md carries the sentinel-wrapped house block
        claude_md = pathlib.Path(self._path("CLAUDE.md")).read_text()
        self.assertIn("<!-- >>> agent-artifacts memory:house >>> -->", claude_md)
        self.assertIn("<!-- <<< agent-artifacts memory:house <<< -->", claude_md)

        # guideline: a standalone reference doc under .claude/guidelines/ — it is NOT merged
        # into the memory file, so the two no longer share (and clobber) CLAUDE.md.
        guideline = self._path(".claude", "guidelines", "python-style.md")
        self.assertTrue(os.path.isfile(guideline))
        self.assertIn("Python Style", pathlib.Path(guideline).read_text())
        self.assertNotIn("python-style", claude_md)

        # mcp: .mcp.json has mcpServers.postgres
        mcp = json.loads(pathlib.Path(self._path(".mcp.json")).read_text())
        self.assertIn("postgres", mcp["mcpServers"])
        self.assertEqual(mcp["mcpServers"]["postgres"]["command"], "npx")

        # hook: registration under hooks.PreToolUse in .claude/settings.json
        settings = json.loads(pathlib.Path(self._path(".claude", "settings.json")).read_text())
        pre = settings["hooks"]["PreToolUse"]
        self.assertTrue(any(h.get("matcher") == "Edit|Write|MultiEdit" for h in pre))

        # hook: script copied to disk under .claude/hooks/block-secrets/
        self.assertTrue(
            os.path.isfile(self._path(".claude", "hooks", "block-secrets", "scripts", "guard.py"))
        )

    def test_manifest_has_five_entries(self):
        with redirect_stdout(io.StringIO()):
            install.run(_request(self.project))
        manifest_file = self._path(".agent-artifacts", "manifest.json")
        self.assertTrue(os.path.isfile(manifest_file))
        data = json.loads(pathlib.Path(manifest_file).read_text())
        self.assertEqual(len(data["installed"]), 5)
        types = sorted(e["type"] for e in data["installed"])
        self.assertEqual(types, ["guideline", "hook", "mcp", "memory", "skill"])
        # local source label recorded verbatim
        self.assertTrue(all(e["source"].startswith("local:") for e in data["installed"]))

    # ---- two profiles ---------------------------------------------------- #
    def test_installs_to_two_profiles(self):
        with redirect_stdout(io.StringIO()):
            code = install.run(_request(self.project, profiles=("claude", "opencode")))
        self.assertEqual(code, 0)

        # memory dest: claude → CLAUDE.md, opencode → AGENTS.md (each its own file)
        self.assertTrue(os.path.isfile(self._path("CLAUDE.md")))
        self.assertTrue(os.path.isfile(self._path("AGENTS.md")))
        memory_md = pathlib.Path(self._path("AGENTS.md")).read_text()
        self.assertIn("<!-- >>> agent-artifacts memory:house >>> -->", memory_md)

        # guideline dest: claude → .claude/guidelines/, opencode → .opencode/guidelines/
        self.assertTrue(os.path.isfile(self._path(".claude", "guidelines", "python-style.md")))
        self.assertTrue(os.path.isfile(self._path(".opencode", "guidelines", "python-style.md")))

        # claude skills vs opencode skills
        self.assertTrue(os.path.isfile(self._path(".claude", "skills", "code-review", "SKILL.md")))
        self.assertTrue(
            os.path.isfile(self._path(".opencode", "skills", "code-review", "SKILL.md"))
        )

        # opencode mcp merges into opencode.json under "mcp"
        opencode = json.loads(pathlib.Path(self._path("opencode.json")).read_text())
        self.assertIn("postgres", opencode["mcp"])

        # manifest has 5 artifacts x 2 profiles = 10 entries
        data = json.loads(pathlib.Path(self._path(".agent-artifacts", "manifest.json")).read_text())
        self.assertEqual(len(data["installed"]), 10)
        profiles = {e["profile"] for e in data["installed"]}
        self.assertEqual(profiles, {"claude", "opencode"})

    # ---- dry-run writes nothing ------------------------------------------ #
    def test_dry_run_writes_nothing(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = install.run(_request(self.project, dry_run=True))
        self.assertEqual(code, 0)
        # The project dir must be untouched (no files created at all).
        self.assertEqual(os.listdir(self.project), [])
        # The dry-run still rendered a plan to stdout.
        self.assertTrue(buf.getvalue().strip())

    def test_dry_run_json_writes_nothing_and_is_valid_json(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = install.run(_request(self.project, dry_run=True, json=True))
        self.assertEqual(code, 0)
        self.assertEqual(os.listdir(self.project), [])
        parsed = json.loads(buf.getvalue())  # raises if not valid JSON
        self.assertIsInstance(parsed, dict)
        self.assertIn("actions", parsed)
        self.assertIn("skipped", parsed)
        self.assertTrue(any(item["reason"] == "incompatible-profile" for item in parsed["skipped"]))

    # ---- --json output is valid JSON ------------------------------------- #
    def test_json_output_is_valid_json(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = install.run(_request(self.project, json=True))
        self.assertEqual(code, 0)
        parsed = json.loads(buf.getvalue())
        self.assertEqual(len(parsed["installed"]), 5)
        self.assertIn("performed", parsed)

    # ---- idempotent re-install ------------------------------------------- #
    def test_reinstall_is_idempotent(self):
        with redirect_stdout(io.StringIO()):
            install.run(_request(self.project))
            install.run(_request(self.project))
        # memory block appears exactly once (sentinel replace-in-place, not duplicated).
        claude_md = pathlib.Path(self._path("CLAUDE.md")).read_text()
        self.assertEqual(claude_md.count("<!-- >>> agent-artifacts memory:house >>> -->"), 1)
        # guideline copy is still a single clean file.
        self.assertTrue(os.path.isfile(self._path(".claude", "guidelines", "python-style.md")))
        # And the manifest still has exactly 5 entries (upsert, not append).
        data = json.loads(pathlib.Path(self._path(".agent-artifacts", "manifest.json")).read_text())
        self.assertEqual(len(data["installed"]), 5)

    # ---- usage error on unknown profile ---------------------------------- #
    def test_unknown_profile_is_usage_error(self):
        with redirect_stdout(io.StringIO()):
            code = install.run(_request(self.project, profiles=("nope",)))
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
