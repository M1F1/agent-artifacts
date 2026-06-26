"""Stable JSON contracts for maintainer-side upstream commands."""

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


class UpstreamJsonContractTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.catalog_root = os.path.join(self._tmp.name, "catalog")
        self.staged_root = os.path.join(self._tmp.name, "staged")
        os.makedirs(self.catalog_root)
        os.makedirs(self.staged_root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_check_json_includes_stable_checked_records_with_source_info(self):
        local_skill = self._seed_skill(self.catalog_root, "demo", "base")
        staged_skill = self._seed_skill(self.staged_root, "demo", "new")
        base_hash = hash_upstream_path(os.path.dirname(local_skill))
        head_hash = hash_upstream_path(os.path.dirname(staged_skill))
        self._write_upstreams(base_hash=base_hash)

        code, output = self._run(
            Request(
                command="upstream",
                upstream_action="check",
                all=True,
                source_dir=self.catalog_root,
                json=True,
            ),
            staged_skill=staged_skill,
        )

        self.assertEqual(code, _common.OK)
        payload = json.loads(output)
        self.assertEqual(
            list(payload.keys()),
            ["action", "catalog", "selected", "warnings", "checked", "statuses"],
        )
        self.assertEqual(payload["action"], "check")
        self.assertEqual(payload["selected"], ["skill/demo"])
        self.assertEqual(
            payload["checked"],
            [
                {
                    "artifact": "skill/demo",
                    "type": "skill",
                    "name": "demo",
                    "state": "changed",
                    "repo": "acme/demo-skills",
                    "ref": "main",
                    "path": "skills/demo",
                    "base_sha": "base-sha",
                    "head_sha": "head-sha",
                    "base_hash": base_hash,
                    "head_hash": head_hash,
                    "message": "",
                }
            ],
        )

    def test_check_json_includes_host_metadata_for_enterprise_source(self):
        local_skill = self._seed_skill(self.catalog_root, "demo", "base")
        staged_skill = self._seed_skill(self.staged_root, "demo", "new")
        base_hash = hash_upstream_path(os.path.dirname(local_skill))
        self._write_upstreams(
            base_hash=base_hash,
            api_url="https://github.my-company.com/api/v3",
            web_url="https://github.my-company.com/acme/demo-skills",
        )

        code, output = self._run(
            Request(
                command="upstream",
                upstream_action="check",
                all=True,
                source_dir=self.catalog_root,
                json=True,
            ),
            staged_skill=staged_skill,
        )

        self.assertEqual(code, _common.OK)
        checked = json.loads(output)["checked"][0]
        self.assertEqual(checked["repo"], "acme/demo-skills")
        self.assertEqual(checked["api_url"], "https://github.my-company.com/api/v3")
        self.assertEqual(checked["web_url"], "https://github.my-company.com/acme/demo-skills")

    def test_update_json_includes_statuses_source_info_and_planned_actions(self):
        local_skill = self._seed_skill(self.catalog_root, "demo", "base")
        staged_skill = self._seed_skill(self.staged_root, "demo", "new")
        base_hash = hash_upstream_path(os.path.dirname(local_skill))
        self._write_upstreams(base_hash=base_hash)

        code, output = self._run(
            Request(
                command="upstream",
                upstream_action="update",
                names=("skill/demo",),
                source_dir=self.catalog_root,
                json=True,
                dry_run=True,
            ),
            staged_skill=staged_skill,
        )

        self.assertEqual(code, _common.OK)
        payload = json.loads(output)
        self.assertEqual(
            list(payload.keys()),
            [
                "action",
                "dry_run",
                "warnings",
                "conflict",
                "updates",
                "statuses",
                "plan",
            ],
        )
        self.assertEqual(payload["action"], "update")
        self.assertTrue(payload["dry_run"])
        self.assertFalse(payload["conflict"])
        self.assertEqual(payload["updates"][0]["artifact"], "skill/demo")
        self.assertEqual(payload["updates"][0]["repo"], "acme/demo-skills")
        self.assertEqual(payload["updates"][0]["state"], "changed")
        self.assertEqual([item["action"] for item in payload["plan"]], ["remove-path", "copy-tree"])

    def test_update_json_includes_host_metadata_for_enterprise_source(self):
        local_skill = self._seed_skill(self.catalog_root, "demo", "base")
        staged_skill = self._seed_skill(self.staged_root, "demo", "new")
        base_hash = hash_upstream_path(os.path.dirname(local_skill))
        self._write_upstreams(
            base_hash=base_hash,
            api_url="https://github.my-company.com/api/v3",
            web_url="https://github.my-company.com/acme/demo-skills",
        )

        code, output = self._run(
            Request(
                command="upstream",
                upstream_action="update",
                names=("skill/demo",),
                source_dir=self.catalog_root,
                json=True,
                dry_run=True,
            ),
            staged_skill=staged_skill,
        )

        self.assertEqual(code, _common.OK)
        update = json.loads(output)["updates"][0]
        self.assertEqual(update["api_url"], "https://github.my-company.com/api/v3")
        self.assertEqual(update["web_url"], "https://github.my-company.com/acme/demo-skills")

    def _run(self, request: Request, *, staged_skill: str):
        def fake_resolve(entry, **_kw):
            staged_path = os.path.dirname(staged_skill)
            return Ok(
                ResolvedUpstream(
                    entry=entry,
                    sha="head-sha",
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

    def _seed_skill(self, root: str, name: str, body: str) -> str:
        path = os.path.join(root, "skills", name, "SKILL.md")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(f"---\nname: {name}\n---\n{body}\n")
        return path

    def _write_upstreams(
        self,
        *,
        base_hash: str,
        api_url: str | None = None,
        web_url: str | None = None,
    ) -> None:
        path = os.path.join(self.catalog_root, "upstreams.json")
        source = {
            "kind": "github",
            "repo": "acme/demo-skills",
            "ref": "main",
            "path": "skills/demo",
        }
        if api_url is not None:
            source["api_url"] = api_url
        if web_url is not None:
            source["web_url"] = web_url
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "version": 1,
                    "artifacts": {
                        "skill/demo": {
                            "source": source,
                            "last_synced": {
                                "sha": "base-sha",
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


if __name__ == "__main__":
    unittest.main()
