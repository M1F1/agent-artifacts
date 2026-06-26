"""Tests for `aart upstream add` — adopt an upstream artifact from a GitHub URL."""

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from agent_artifacts.commands import _common, upstream
from agent_artifacts.model import Ok, Request
from agent_artifacts.upstream_source import ResolvedUpstream, hash_upstream_path

TREE_URL = "https://github.com/mattpocock/skills/tree/main/skills/engineering/grill-me"


class UpstreamAddTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.catalog_root = os.path.join(self._tmp.name, "catalog")
        self.staged_root = os.path.join(self._tmp.name, "staged")
        os.makedirs(self.catalog_root)
        os.makedirs(self.staged_root)

    def tearDown(self):
        self._tmp.cleanup()

    # --- helpers ---------------------------------------------------------- #
    def _stage_skill(self, name: str, *, with_skill_md: bool = True) -> str:
        """Create a staged directory skill with a nested subdir; return its path."""
        root = os.path.join(self.staged_root, name)
        os.makedirs(os.path.join(root, "references", "deep"))
        if with_skill_md:
            self._write(os.path.join(root, "SKILL.md"), f"---\nname: {name}\n---\nbody\n")
        self._write(os.path.join(root, "references", "deep", "notes.md"), "nested\n")
        return root

    def _stage_mcp_dir(self, name: str, *, with_descriptor: bool = True) -> str:
        """Create a staged MCP directory with config plus setup guide; return its path."""
        root = os.path.join(self.staged_root, name)
        os.makedirs(root)
        if with_descriptor:
            self._write(
                os.path.join(root, "mcp.json"),
                json.dumps({"name": name, "server": {"command": "npx"}}),
            )
        self._write(os.path.join(root, "SETUP.md"), "# Setup\n")
        return root

    @staticmethod
    def _write(path: str, text: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def _add(self, request: Request, *, staged_path: str, sha: str = "abc123"):
        def fake_resolve(entry):
            return Ok(
                ResolvedUpstream(
                    entry=entry,
                    sha=sha,
                    root=self.staged_root,
                    path=staged_path,
                    content_hash=hash_upstream_path(staged_path),
                )
            )

        out = io.StringIO()
        with patch.object(upstream, "resolve_upstream_source", side_effect=fake_resolve):
            with redirect_stdout(out):
                code = upstream.run(request)
        return code, out.getvalue()

    def _add_no_network(self, request: Request):
        """Run add asserting the network resolver is never reached."""
        out = io.StringIO()
        with patch.object(upstream, "resolve_upstream_source", side_effect=AssertionError):
            with redirect_stdout(out):
                code = upstream.run(request)
        return code, out.getvalue()

    def _req(self, **kw) -> Request:
        base = dict(
            command="upstream",
            upstream_action="add",
            names=("skill/grill-me",),
            url=TREE_URL,
            source_dir=self.catalog_root,
        )
        base.update(kw)
        return Request(**base)

    def _tracking(self) -> dict:
        with open(os.path.join(self.catalog_root, "upstreams.json"), encoding="utf-8") as fh:
            return json.load(fh)

    # --- happy path ------------------------------------------------------- #
    def test_add_vendors_whole_dir_and_tracks_entry(self):
        staged = self._stage_skill("grill-me")
        code, output = self._add(self._req(), staged_path=staged)

        self.assertEqual(code, _common.OK, msg=output)
        # The whole directory landed, including the nested subdir.
        dest = os.path.join(self.catalog_root, "skills", "grill-me")
        self.assertTrue(os.path.isfile(os.path.join(dest, "SKILL.md")))
        self.assertTrue(os.path.isfile(os.path.join(dest, "references", "deep", "notes.md")))
        # The tracking entry is fully formed.
        data = self._tracking()
        entry = data["artifacts"]["skill/grill-me"]
        self.assertEqual(entry["source"]["repo"], "mattpocock/skills")
        self.assertEqual(entry["source"]["ref"], "main")
        self.assertEqual(entry["source"]["path"], "skills/engineering/grill-me")
        self.assertEqual(entry["last_synced"]["sha"], "abc123")
        self.assertNotIn("api_url", entry["source"])  # public github stays compact
        self.assertIn("Tracked", output)

    def test_dry_run_writes_nothing(self):
        staged = self._stage_skill("grill-me")
        code, output = self._add(self._req(dry_run=True), staged_path=staged)

        self.assertEqual(code, _common.OK)
        self.assertFalse(os.path.exists(os.path.join(self.catalog_root, "skills", "grill-me")))
        self.assertFalse(os.path.exists(os.path.join(self.catalog_root, "upstreams.json")))
        self.assertIn("Would vendor", output)

    def test_json_output(self):
        staged = self._stage_skill("grill-me")
        code, output = self._add(self._req(json=True), staged_path=staged)

        self.assertEqual(code, _common.OK)
        payload = json.loads(output)
        self.assertEqual(payload["action"], "add")
        self.assertEqual(payload["artifact"], "skill/grill-me")
        self.assertEqual(payload["path"], "skills/engineering/grill-me")
        self.assertEqual(payload["destination"], os.path.join("skills", "grill-me"))

    def test_add_mcp_tree_vendors_directory_with_setup_guide(self):
        staged = self._stage_mcp_dir("stripe")
        req = self._req(
            names=("mcp/stripe",),
            url="https://github.com/acme/mcps/tree/main/servers/stripe",
        )
        code, output = self._add(req, staged_path=staged)

        self.assertEqual(code, _common.OK, msg=output)
        dest = os.path.join(self.catalog_root, "mcp", "stripe")
        self.assertTrue(os.path.isfile(os.path.join(dest, "mcp.json")))
        self.assertTrue(os.path.isfile(os.path.join(dest, "SETUP.md")))
        entry = self._tracking()["artifacts"]["mcp/stripe"]
        self.assertEqual(entry["source"]["repo"], "acme/mcps")
        self.assertEqual(entry["source"]["path"], "servers/stripe")

    def test_invalid_mcp_tree_writes_nothing(self):
        staged = self._stage_mcp_dir("stripe", with_descriptor=False)
        req = self._req(
            names=("mcp/stripe",),
            url="https://github.com/acme/mcps/tree/main/servers/stripe",
        )
        code, output = self._add(req, staged_path=staged)

        self.assertEqual(code, _common.USAGE)
        self.assertIn("missing MCP descriptor", output)
        self.assertFalse(os.path.exists(os.path.join(self.catalog_root, "mcp", "stripe")))
        self.assertFalse(os.path.exists(os.path.join(self.catalog_root, "upstreams.json")))

    # --- guards ----------------------------------------------------------- #
    def test_invalid_url_is_usage_without_network(self):
        code, output = self._add_no_network(self._req(url="http://github.com/a/b"))
        self.assertEqual(code, _common.USAGE)
        self.assertIn("invalid URL", output)

    def test_type_shape_mismatch_rejected_without_network(self):
        # A /blob (file) URL for a directory artifact (skill).
        code, output = self._add_no_network(
            self._req(url="https://github.com/acme/skills/blob/main/x.md")
        )
        self.assertEqual(code, _common.USAGE)
        self.assertIn("directory artifact", output)

    def test_bare_repo_requires_ref_and_path(self):
        code, output = self._add_no_network(self._req(url="https://github.com/acme/skills"))
        self.assertEqual(code, _common.USAGE)
        self.assertIn("ref", output)

    def test_bare_repo_with_overrides_succeeds(self):
        staged = self._stage_skill("grill-me")
        code, output = self._add(
            self._req(url="https://github.com/acme/skills", ref="main", path="skills/grill-me"),
            staged_path=staged,
        )
        self.assertEqual(code, _common.OK, msg=output)
        self.assertEqual(self._tracking()["artifacts"]["skill/grill-me"]["source"]["ref"], "main")

    def test_existing_destination_conflicts_without_force(self):
        os.makedirs(os.path.join(self.catalog_root, "skills", "grill-me"))
        staged = self._stage_skill("grill-me")
        code, output = self._add(self._req(), staged_path=staged)
        self.assertEqual(code, _common.CONFLICT)
        self.assertIn("--force", output)

    def test_force_overwrites_existing_destination(self):
        stale = os.path.join(self.catalog_root, "skills", "grill-me")
        self._write(os.path.join(stale, "stale.md"), "old\n")
        staged = self._stage_skill("grill-me")
        code, output = self._add(self._req(force=True), staged_path=staged)
        self.assertEqual(code, _common.OK, msg=output)
        # The stale file is gone (replaced, not merged) and the new tree is present.
        self.assertFalse(os.path.exists(os.path.join(stale, "stale.md")))
        self.assertTrue(os.path.isfile(os.path.join(stale, "SKILL.md")))

    def test_already_tracked_key_points_to_update(self):
        # Seed an existing entry, then re-add the same key without --force.
        staged = self._stage_skill("grill-me")
        self._add(self._req(), staged_path=staged)
        code, output = self._add_no_network(self._req(force=False))
        self.assertEqual(code, _common.USAGE)
        self.assertIn("update", output)

    def test_invalid_content_writes_nothing(self):
        staged = self._stage_skill("grill-me", with_skill_md=False)  # no SKILL.md
        code, output = self._add(self._req(), staged_path=staged)
        self.assertEqual(code, _common.USAGE)
        self.assertFalse(os.path.exists(os.path.join(self.catalog_root, "skills", "grill-me")))
        self.assertFalse(os.path.exists(os.path.join(self.catalog_root, "upstreams.json")))


if __name__ == "__main__":
    unittest.main()
