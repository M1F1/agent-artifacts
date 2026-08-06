"""Maintainer context, validate, and health command contracts."""

import io
import json
import pathlib
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from agent_artifacts.commands import _common, upstream
from agent_artifacts.model import Ok, Request
from agent_artifacts.upstream_source import ResolvedUpstream, hash_upstream_path

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"


class MaintainerCommandTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name) / "catalog"
        shutil.copytree(FIXTURES, self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, action: str, *, json_mode: bool = False):
        output = io.StringIO()
        with redirect_stdout(output):
            code = upstream.run(
                Request(
                    command="upstream",
                    upstream_action=action,
                    source_dir=str(self.root),
                    json=json_mode,
                )
            )
        return code, output.getvalue()

    def test_validate_accepts_catalog_without_upstreams_file(self):
        code, output = self._run("validate")

        self.assertEqual(code, _common.OK)
        self.assertIn(f"Catalog valid: {self.root}", output)

    def test_health_reports_counts_and_untracked_artifacts_without_network(self):
        code, output = self._run("health", json_mode=True)

        self.assertEqual(code, _common.OK)
        payload = json.loads(output)
        self.assertEqual(payload["catalog_root"], str(self.root))
        self.assertEqual(payload["counts"]["skill"], 1)
        self.assertEqual(payload["tracked"], [])
        self.assertIn("skill/code-review", payload["untracked"])
        self.assertEqual(payload["needs_attention"], [])

    def test_non_catalog_directory_is_rejected_with_absolute_path(self):
        self.root = pathlib.Path(self._tmp.name) / "not-a-catalog"
        self.root.mkdir()

        code, output = self._run("validate")

        self.assertEqual(code, _common.USAGE)
        self.assertIn(str(self.root), output)
        self.assertIn("not a catalog", output)

    def test_invalid_catalog_is_reported_by_validate(self):
        (self.root / "bundles/broken.json").write_text("{not json", encoding="utf-8")

        code, output = self._run("validate")

        self.assertNotEqual(code, _common.OK)
        self.assertIn(str(self.root), output)
        self.assertIn("broken", output)

    def test_health_lists_changed_upstream_as_requiring_attention(self):
        local_skill = self.root / "skills/code-review"
        staged_root = pathlib.Path(self._tmp.name) / "staged"
        staged_skill = staged_root / "skills/code-review"
        shutil.copytree(local_skill, staged_skill)
        (staged_skill / "SKILL.md").write_text(
            "---\nname: code-review\n---\n# changed\n", encoding="utf-8"
        )
        local_hash = hash_upstream_path(str(local_skill))
        (self.root / "upstreams.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "artifacts": {
                        "skill/code-review": {
                            "source": {
                                "kind": "github",
                                "repo": "acme/catalog",
                                "ref": "main",
                                "path": "skills/code-review",
                            },
                            "last_synced": {
                                "sha": "base",
                                "content_hash": local_hash,
                                "synced_at": "2026-08-06T00:00:00Z",
                            },
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        def resolve(entry, **_kwargs):
            return Ok(
                ResolvedUpstream(
                    entry=entry,
                    sha="head",
                    root=str(staged_root),
                    path=str(staged_skill),
                    content_hash=hash_upstream_path(str(staged_skill)),
                )
            )

        with patch.object(upstream, "resolve_upstream_source", side_effect=resolve):
            code, output = self._run("health", json_mode=True)

        self.assertEqual(code, _common.OK)
        payload = json.loads(output)
        self.assertEqual(payload["needs_attention"], ["skill/code-review"])
        self.assertEqual(payload["statuses"][0]["state"], "changed")


if __name__ == "__main__":
    unittest.main()
