"""End-to-end coverage for the maintainer-side ``upstream`` command family."""

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from agent_artifacts import cli
from agent_artifacts.model import Ok
from agent_artifacts.upstream_source import ResolvedUpstream, hash_upstream_path


class UpstreamE2ETests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.catalog_root = os.path.join(self._tmp.name, "catalog")
        self.staged_root = os.path.join(self._tmp.name, "staged")
        os.makedirs(self.catalog_root)
        os.makedirs(self.staged_root)
        self.local_skill = self._seed_skill(self.catalog_root, "base")
        self.staged_skill = self._seed_skill(self.staged_root, "new")
        self._write_upstreams(
            base_sha="base-sha",
            base_hash=hash_upstream_path(os.path.dirname(self.local_skill)),
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_check_then_update_then_check_clean_through_cli(self):
        check_code, check_output = self._run_cli(
            "upstream",
            "check",
            "--all",
            "--source",
            self.catalog_root,
            "--json",
        )

        self.assertEqual(check_code, 0)
        check_payload = json.loads(check_output)
        self.assertEqual(check_payload["statuses"][0]["state"], "changed")

        update_code, update_output = self._run_cli(
            "upstream",
            "update",
            "skill/demo",
            "--source",
            self.catalog_root,
        )

        self.assertEqual(update_code, 0)
        self.assertIn("Updated 1 upstream artifact", update_output)
        self.assertIn("new", self._read_file(self.local_skill))

        recheck_code, recheck_output = self._run_cli(
            "upstream",
            "check",
            "--all",
            "--source",
            self.catalog_root,
            "--json",
        )

        self.assertEqual(recheck_code, 0)
        recheck_payload = json.loads(recheck_output)
        self.assertEqual(recheck_payload["statuses"][0]["state"], "up_to_date")

    def _run_cli(self, *argv: str):
        def fake_resolve(entry):
            staged_path = os.path.dirname(self.staged_skill)
            return Ok(
                ResolvedUpstream(
                    entry=entry,
                    sha="new-sha",
                    root=self.staged_root,
                    path=staged_path,
                    content_hash=hash_upstream_path(staged_path),
                )
            )

        out = io.StringIO()
        with patch("agent_artifacts.commands.upstream.resolve_upstream_source", fake_resolve):
            with redirect_stdout(out):
                code = cli.main(list(argv))
        return code, out.getvalue()

    def _seed_skill(self, root: str, body: str) -> str:
        path = os.path.join(root, "skills", "demo", "SKILL.md")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(f"---\nname: demo\n---\n{body}\n")
        return path

    def _write_upstreams(self, *, base_sha: str, base_hash: str) -> None:
        path = os.path.join(self.catalog_root, "upstreams.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "version": 1,
                    "artifacts": {
                        "skill/demo": {
                            "source": {
                                "kind": "github",
                                "repo": "acme/demo-skills",
                                "ref": "main",
                                "path": "skills/demo",
                            },
                            "last_synced": {
                                "sha": base_sha,
                                "content_hash": base_hash,
                                "synced_at": "2026-06-22T10:00:00Z",
                            },
                        }
                    },
                },
                fh,
                indent=2,
            )
            fh.write("\n")

    def _read_file(self, path: str) -> str:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()


if __name__ == "__main__":
    unittest.main()
