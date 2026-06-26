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


class UpstreamImportCommandTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.catalog_root = os.path.join(self._tmp.name, "catalog")
        self.staged_root = os.path.join(self._tmp.name, "staged")
        os.makedirs(self.catalog_root)
        os.makedirs(self.staged_root)

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, root: str, rel: str, text: str) -> str:
        path = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def _seed_manifest_repo(self):
        self._write(
            self.staged_root,
            "agent-artifacts.import.json",
            json.dumps(
                {
                    "version": 1,
                    "artifacts": [
                        {"type": "skill", "name": "debugging", "path": "skills/debugging"},
                        {
                            "type": "memory",
                            "name": "superpowers",
                            "path": "memory/superpowers.md",
                        },
                    ],
                }
            ),
        )
        self._write(self.staged_root, "skills/debugging/SKILL.md", "---\nname: debugging\n---\n")
        self._write(self.staged_root, "memory/superpowers.md", "# Memory\n")

    def _run(self, request: Request):
        def fake_resolve(entry):
            return Ok(
                ResolvedUpstream(
                    entry=entry,
                    sha="abc123",
                    root=self.staged_root,
                    path=self.staged_root,
                    content_hash=hash_upstream_path(self.staged_root),
                )
            )

        out = io.StringIO()
        with patch.object(upstream, "resolve_upstream_source", side_effect=fake_resolve):
            with redirect_stdout(out):
                code = upstream.run(request)
        return code, out.getvalue()

    def _request(self, action: str, **kw) -> Request:
        data = {
            "command": "upstream",
            "upstream_action": action,
            "url": "https://github.com/acme/superpowers",
            "ref": "main",
            "source_dir": self.catalog_root,
        }
        data.update(kw)
        return Request(**data)

    def test_scan_json_reports_manifest_candidates(self):
        self._seed_manifest_repo()

        code, output = self._run(self._request("scan", json=True))

        self.assertEqual(code, _common.OK, msg=output)
        payload = json.loads(output)
        self.assertEqual(payload["action"], "scan")
        self.assertEqual(payload["mode"], "manifest")
        self.assertEqual(
            [item["key"] for item in payload["candidates"]],
            ["skill/debugging", "memory/superpowers"],
        )

    def test_import_dry_run_writes_nothing_and_reports_bundle_plan(self):
        self._seed_manifest_repo()

        code, output = self._run(
            self._request(
                "import",
                dry_run=True,
                json=True,
                bundles=("superpowers",),
                bundle_description="Superpowers kit",
            )
        )

        self.assertEqual(code, _common.OK, msg=output)
        payload = json.loads(output)
        self.assertEqual(payload["action"], "import")
        self.assertTrue(payload["dry_run"])
        self.assertEqual(len(payload["selected"]), 2)
        self.assertFalse(os.path.exists(os.path.join(self.catalog_root, "upstreams.json")))
        self.assertTrue(any(a["action"] == "write-file" for a in payload["plan"]))

    def test_import_writes_artifacts_tracking_and_bundle(self):
        self._seed_manifest_repo()

        code, output = self._run(
            self._request(
                "import",
                bundles=("superpowers",),
                bundle_description="Superpowers kit",
            )
        )

        self.assertEqual(code, _common.OK, msg=output)
        self.assertTrue(
            os.path.isfile(os.path.join(self.catalog_root, "skills", "debugging", "SKILL.md"))
        )
        self.assertTrue(
            os.path.isfile(os.path.join(self.catalog_root, "memory", "superpowers.md"))
        )
        tracking = json.loads(self._read("upstreams.json"))
        self.assertEqual(set(tracking["artifacts"]), {"skill/debugging", "memory/superpowers"})
        bundle = json.loads(self._read("bundles/superpowers.json"))
        self.assertEqual(bundle["includes"]["skills"], ["debugging"])
        self.assertEqual(bundle["includes"]["memory"], ["superpowers"])

    def test_heuristic_import_skips_ambiguous_markdown(self):
        self._write(self.staged_root, "docs/prompting.md", "# Prompting\n")

        code, output = self._run(self._request("import", import_mode="heuristic", json=True))

        self.assertEqual(code, _common.OK, msg=output)
        payload = json.loads(output)
        self.assertEqual(payload["selected"], [])
        self.assertEqual(payload["skipped"][0]["confidence"], "ambiguous")
        self.assertFalse(os.path.exists(os.path.join(self.catalog_root, "upstreams.json")))

    def _read(self, rel: str) -> str:
        with open(os.path.join(self.catalog_root, *rel.split("/")), encoding="utf-8") as fh:
            return fh.read()


if __name__ == "__main__":
    unittest.main()
