"""WP-24 — end-to-end integration gate (the final green-light for the whole system).

Drives the **real CLI** (`cli.main(argv)`) against a temp consumer project and the local
`tests/fixtures` `--source`, exercising the full install -> status -> update -> uninstall
round-trip for all 4 artifact types across 2 profiles, plus the agent-mode surface
(`--yes`/`--json`/`--dry-run`/`--force`), a golden Plan snapshot, and the error exit codes.

No network (everything uses a local `--source`). Run:
    python -m unittest discover -s tests -p "e2e_test.py" -v
"""

import contextlib
import io
import json
import os
import pathlib
import tempfile
import unittest

from agent_artifacts import cli

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = str(REPO_ROOT / "tests" / "fixtures")

# The fixture catalog: one artifact of each type, installable into two harnesses.
TYPES = {"skill", "guideline", "mcp", "hook", "agents"}
PROFILES = ("claude", "opencode")


def _cli(*argv):
    """Run ``cli.main(argv)`` capturing output; returns ``(rc, stdout, stderr)``.

    argparse usage errors raise ``SystemExit`` — its code is surfaced as ``rc`` so callers can
    assert on exit codes uniformly.
    """
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = cli.main(list(argv))
        except SystemExit as exc:  # argparse usage errors
            rc = exc.code if isinstance(exc.code, int) else 1
    return rc, out.getvalue(), err.getvalue()


class _ProjectCase(unittest.TestCase):
    """Base: a throwaway consumer project + helpers to read its manifest."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    # --- helpers ----------------------------------------------------------- #
    def install(self, *extra):
        return _cli("install", "--source", FIXTURES, "--project", self.project, *extra)

    def status_json(self):
        rc, out, _ = _cli("status", "--project", self.project, "--json")
        self.assertEqual(rc, 0, "status should succeed")
        return json.loads(out)

    def manifest_entries(self):
        return self.status_json()["installed"]

    def p(self, *parts):
        return os.path.join(self.project, *parts)


class TestRoundTrip(_ProjectCase):
    """install -> status -> update -> uninstall for all 4 types x 2 profiles."""

    def test_full_round_trip(self):
        # install everything into both profiles, agent mode.
        rc, out, err = self.install("--all", "--profile", "claude,opencode", "--yes")
        self.assertEqual(rc, 0, f"install failed: {err}")

        entries = self.manifest_entries()
        self.assertEqual(len(entries), 10, "5 types x 2 profiles == 10 manifest entries")
        self.assertEqual({e["type"] for e in entries}, TYPES)
        self.assertEqual({e["profile"] for e in entries}, set(PROFILES))

        # representative files/merges for every type landed (both profiles).
        for path in (
            ".claude/skills/code-review", "CLAUDE.md", ".mcp.json", ".claude/settings.json",
            ".opencode/skills/code-review", "AGENTS.md", "opencode.json",
        ):
            self.assertTrue(os.path.exists(self.p(path)), f"missing {path}")

        # The agents instruction block landed in the same file as the guideline block,
        # each under its own sentinel markers (DESIGN-agents.md §3.5).
        for inst_file in ("CLAUDE.md", "AGENTS.md"):
            text = pathlib.Path(self.p(inst_file)).read_text()
            self.assertIn("agent-artifacts agents:house", text,
                          f"{inst_file} should carry the agents block")

        # update with no changes upstream -> clean, no error.
        rc, _out, err = _cli("update", "--source", FIXTURES, "--project", self.project, "--yes")
        self.assertEqual(rc, 0, f"update failed: {err}")
        self.assertEqual(len(self.manifest_entries()), 10, "update keeps the same entries")

        # uninstall everything -> manifest empty, skill trees gone.
        rc, _out, err = _cli(
            "uninstall", "--all", "--profile", "claude,opencode",
            "--project", self.project, "--yes",
        )
        self.assertEqual(rc, 0, f"uninstall failed: {err}")
        self.assertEqual(self.manifest_entries(), [], "uninstall clears the manifest")
        self.assertFalse(os.path.exists(self.p(".claude/skills/code-review")))
        self.assertFalse(os.path.exists(self.p(".opencode/skills/code-review")))

    def test_single_type_each(self):
        # Each artifact installs on its own into one profile.
        for name in ("code-review", "python-style", "postgres", "block-secrets", "house"):
            rc, _out, err = self.install(name, "--profile", "claude", "--yes")
            self.assertEqual(rc, 0, f"install {name} failed: {err}")
        self.assertEqual(
            {e["artifact"] for e in self.manifest_entries()},
            {"code-review", "python-style", "postgres", "block-secrets", "house"},
        )


class TestAgentsCli(_ProjectCase):
    """Agents-specific CLI behaviour: install modes and the unsupported-type policy."""

    def test_replace_over_foreign_needs_force_then_backs_up(self):
        # A hand-authored instruction file: `replace` without --force is a CONFLICT (4)...
        claude_md = self.p("CLAUDE.md")
        pathlib.Path(claude_md).write_text("# my own notes\n- keep me\n")
        rc, _out, _err = self.install("house", "--profile", "claude",
                                      "--agents-mode", "replace", "--yes")
        self.assertEqual(rc, 4, "replace over foreign content without --force is CONFLICT")
        self.assertIn("my own notes", pathlib.Path(claude_md).read_text())  # untouched

        # ...with --force the body replaces the file and the prior content is backed up.
        rc, _out, err = self.install("house", "--profile", "claude",
                                     "--agents-mode", "replace", "--force", "--yes")
        self.assertEqual(rc, 0, f"forced replace failed: {err}")
        self.assertNotIn("my own notes", pathlib.Path(claude_md).read_text())
        self.assertTrue(os.path.exists(claude_md + ".agent-artifacts-bak"),
                        "replace should back up the prior content")

    def test_vibe_rejects_unsupported_type_by_name(self):
        # vibe declares no MCP target; an explicit by-name request is a USAGE error (§5).
        rc, _out, _err = self.install("postgres", "--profile", "vibe", "--yes")
        self.assertEqual(rc, 2, "installing mcp into vibe (unsupported) is USAGE")


class TestDryRunIsPure(_ProjectCase):
    """--dry-run prints a Plan and mutates nothing."""

    def test_dry_run_writes_nothing(self):
        rc, out, _err = self.install("--all", "--profile", "claude,opencode", "--dry-run")
        self.assertEqual(rc, 0)
        self.assertTrue(out.strip(), "dry-run should print the plan")
        # No project artifacts created at all.
        self.assertFalse(os.path.exists(self.p(".agent-artifacts")))
        self.assertFalse(os.path.exists(self.p(".claude")))
        self.assertFalse(os.path.exists(self.p("CLAUDE.md")))

    def test_dry_run_json_is_a_plan(self):
        rc, out, _err = self.install(
            "code-review", "--profile", "claude", "--dry-run", "--json"
        )
        self.assertEqual(rc, 0)
        plan = json.loads(out)  # a JSON array of actions
        self.assertIsInstance(plan, list)
        copies = [a for a in plan if a.get("action") == "copy-tree"]
        self.assertTrue(
            any(a["dst"].endswith(".claude/skills/code-review") for a in copies),
            f"expected a copy-tree into .claude/skills/code-review, got {plan}",
        )


class TestForceReinstall(_ProjectCase):
    """--force authorizes overwriting an already-installed artifact."""

    def test_reinstall_with_force(self):
        rc, _o, err = self.install("code-review", "--profile", "claude", "--yes")
        self.assertEqual(rc, 0, err)
        rc, _o, err = self.install("code-review", "--profile", "claude", "--yes", "--force")
        self.assertEqual(rc, 0, f"forced re-install failed: {err}")
        # still exactly one entry (idempotent upsert, not a duplicate).
        self.assertEqual(len(self.manifest_entries()), 1)


class TestJsonOutputs(_ProjectCase):
    """Agent-mode JSON is well-formed across commands."""

    def test_install_status_list_json(self):
        rc, out, _e = self.install("--all", "--profile", "claude", "--yes", "--json")
        self.assertEqual(rc, 0)
        self.assertIn("installed", json.loads(out))

        self.assertIn("installed", self.status_json())

        rc, out, _e = _cli("list", "--source", FIXTURES, "--json")
        self.assertEqual(rc, 0)
        json.loads(out)  # must parse


class TestErrorExitCodes(_ProjectCase):
    """The §7 exit-code vocabulary is honored end-to-end."""

    def test_unknown_artifact_is_usage(self):
        rc, _o, _e = self.install("does-not-exist", "--profile", "claude", "--yes")
        self.assertEqual(rc, 2)

    def test_unknown_profile_is_usage(self):
        rc, _o, _e = self.install("code-review", "--profile", "nope", "--yes")
        self.assertEqual(rc, 2)

    def test_bad_subcommand_is_usage(self):
        rc, _o, _e = _cli("frobnicate")
        self.assertEqual(rc, 2)

    def test_corrupt_manifest_is_code_5(self):
        meta = self.p(".agent-artifacts")
        os.makedirs(meta, exist_ok=True)
        with open(os.path.join(meta, "manifest.json"), "w", encoding="utf-8") as f:
            f.write("{ this is not valid json ]")
        rc, _o, _e = _cli("status", "--project", self.project, "--json")
        self.assertEqual(rc, 5)


if __name__ == "__main__":
    unittest.main()
