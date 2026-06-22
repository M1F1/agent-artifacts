"""Command orchestration tests for ``aart upstream``."""

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


class UpstreamCommandUsageTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, request: Request):
        out = io.StringIO()
        with redirect_stdout(out):
            code = upstream.run(request)
        return code, out.getvalue()

    def test_update_requires_explicit_selector(self):
        code, output = self._run(
            Request(command="upstream", upstream_action="update", source_dir=self.project)
        )

        self.assertEqual(code, _common.USAGE)
        self.assertIn("selector", output.lower())

    def test_check_reports_missing_tracking_file(self):
        code, output = self._run(
            Request(command="upstream", upstream_action="check", all=True, source_dir=self.project)
        )

        self.assertEqual(code, _common.USAGE)
        self.assertIn("upstreams.json", output)

    def test_update_reports_missing_tracking_file_after_selector_validation(self):
        code, output = self._run(
            Request(
                command="upstream",
                upstream_action="update",
                names=("skill/code-review",),
                source_dir=self.project,
            )
        )

        self.assertEqual(code, _common.USAGE)
        self.assertIn("upstreams.json", output)
        self.assertEqual(os.listdir(self.project), [])


class UpstreamCommandValidationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.catalog_root = self._tmp.name
        os.makedirs(os.path.join(self.catalog_root, "skills", "demo"))
        with open(
            os.path.join(self.catalog_root, "skills", "demo", "SKILL.md"),
            "w",
            encoding="utf-8",
        ) as fh:
            fh.write("---\nname: demo\n---\nbody\n")
        with open(os.path.join(self.catalog_root, "upstreams.json"), "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "version": 1,
                    "artifacts": {
                        "skill/ghost": {
                            "source": {
                                "kind": "github",
                                "repo": "acme/ghost",
                                "ref": "main",
                                "path": "skills/ghost",
                            },
                            "last_synced": {
                                "sha": "base-sha",
                                "content_hash": "sha256:base",
                                "synced_at": "2026-06-22T10:00:00Z",
                            },
                        }
                    },
                },
                fh,
            )

    def tearDown(self):
        self._tmp.cleanup()

    def test_check_rejects_dangling_tracking_entries_before_resolution(self):
        out = io.StringIO()
        with patch.object(upstream, "resolve_upstream_source", side_effect=AssertionError):
            with redirect_stdout(out):
                code = upstream.run(
                    Request(
                        command="upstream",
                        upstream_action="check",
                        all=True,
                        source_dir=self.catalog_root,
                    )
                )

        self.assertEqual(code, _common.USAGE)
        self.assertIn("unknown artifact skill/ghost", out.getvalue())


class UpstreamCommandWorkflowTests(unittest.TestCase):
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

    def _seed_skill(self, root: str, name: str, body: str) -> str:
        return self._write(root, f"skills/{name}/SKILL.md", f"---\nname: {name}\n---\n{body}\n")

    def _write_upstreams(self, *, base_sha: str, base_hash: str) -> None:
        self._write(
            self.catalog_root,
            "upstreams.json",
            json.dumps(
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
                indent=2,
            )
            + "\n",
        )

    def _run(self, request: Request, *, staged_skill: str, head_sha: str = "head-sha"):
        def fake_resolve(entry):
            staged_path = os.path.dirname(staged_skill)
            return Ok(
                ResolvedUpstream(
                    entry=entry,
                    sha=head_sha,
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

    def test_check_json_reports_selected_status_without_writing_tracking_file(self):
        local_skill = self._seed_skill(self.catalog_root, "demo", "base")
        staged_skill = self._seed_skill(self.staged_root, "demo", "base")
        base_hash = hash_upstream_path(os.path.dirname(local_skill))
        self._write_upstreams(base_sha="base-sha", base_hash=base_hash)
        before = self._read_tracking()

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
        self.assertEqual(payload["action"], "check")
        self.assertEqual(payload["selected"], ["skill/demo"])
        self.assertEqual(payload["statuses"][0]["key"], "skill/demo")
        self.assertEqual(payload["statuses"][0]["state"], "up_to_date")
        self.assertEqual(payload["statuses"][0]["base_sha"], "base-sha")
        self.assertEqual(payload["statuses"][0]["head_sha"], "head-sha")
        self.assertEqual(self._read_tracking(), before)

    def test_update_dry_run_renders_plan_without_touching_catalog_or_tracking_file(self):
        local_skill = self._seed_skill(self.catalog_root, "demo", "base")
        staged_skill = self._seed_skill(self.staged_root, "demo", "new")
        base_hash = hash_upstream_path(os.path.dirname(local_skill))
        self._write_upstreams(base_sha="base-sha", base_hash=base_hash)
        tracking_before = self._read_tracking()
        skill_before = self._read_file(local_skill)

        code, output = self._run(
            Request(
                command="upstream",
                upstream_action="update",
                names=("skill/demo",),
                source_dir=self.catalog_root,
                dry_run=True,
            ),
            staged_skill=staged_skill,
        )

        self.assertEqual(code, _common.OK)
        self.assertIn("remove-path", output)
        self.assertIn("copy-tree", output)
        self.assertEqual(self._read_file(local_skill), skill_before)
        self.assertEqual(self._read_tracking(), tracking_before)

    def test_update_applies_clean_tree_and_persists_new_last_sync(self):
        local_skill = self._seed_skill(self.catalog_root, "demo", "base")
        staged_skill = self._seed_skill(self.staged_root, "demo", "new")
        base_hash = hash_upstream_path(os.path.dirname(local_skill))
        self._write_upstreams(base_sha="base-sha", base_hash=base_hash)
        head_hash = hash_upstream_path(os.path.dirname(staged_skill))

        code, output = self._run(
            Request(
                command="upstream",
                upstream_action="update",
                names=("skill/demo",),
                source_dir=self.catalog_root,
            ),
            staged_skill=staged_skill,
            head_sha="new-sha",
        )

        self.assertEqual(code, _common.OK)
        self.assertIn("Updated 1 upstream artifact", output)
        self.assertIn("new", self._read_file(local_skill))
        saved = json.loads(self._read_tracking())
        synced = saved["artifacts"]["skill/demo"]["last_synced"]
        self.assertEqual(synced["sha"], "new-sha")
        self.assertEqual(synced["content_hash"], head_hash)
        self.assertTrue(synced["synced_at"])

    def test_update_conflict_leaves_catalog_and_tracking_file_unchanged(self):
        local_skill = self._seed_skill(self.catalog_root, "demo", "local edit")
        staged_skill = self._seed_skill(self.staged_root, "demo", "new")
        self._write_upstreams(base_sha="base-sha", base_hash="sha256:old-base")
        tracking_before = self._read_tracking()
        skill_before = self._read_file(local_skill)

        code, output = self._run(
            Request(
                command="upstream",
                upstream_action="update",
                names=("skill/demo",),
                source_dir=self.catalog_root,
            ),
            staged_skill=staged_skill,
        )

        self.assertEqual(code, _common.CONFLICT)
        self.assertIn("local catalog and upstream both differ", output)
        self.assertEqual(self._read_file(local_skill), skill_before)
        self.assertEqual(self._read_tracking(), tracking_before)

    def test_force_update_overwrites_local_drift_and_persists_new_last_sync(self):
        local_skill = self._seed_skill(self.catalog_root, "demo", "local edit")
        staged_skill = self._seed_skill(self.staged_root, "demo", "new")
        self._write_upstreams(base_sha="base-sha", base_hash="sha256:old-base")
        head_hash = hash_upstream_path(os.path.dirname(staged_skill))

        code, output = self._run(
            Request(
                command="upstream",
                upstream_action="update",
                names=("skill/demo",),
                source_dir=self.catalog_root,
                force=True,
            ),
            staged_skill=staged_skill,
            head_sha="new-sha",
        )

        self.assertEqual(code, _common.OK)
        self.assertIn("Updated 1 upstream artifact", output)
        self.assertIn("new", self._read_file(local_skill))
        saved = json.loads(self._read_tracking())
        synced = saved["artifacts"]["skill/demo"]["last_synced"]
        self.assertEqual(synced["sha"], "new-sha")
        self.assertEqual(synced["content_hash"], head_hash)

    def _read_tracking(self) -> str:
        return self._read_file(os.path.join(self.catalog_root, "upstreams.json"))

    def _read_file(self, path: str) -> str:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()


if __name__ == "__main__":
    unittest.main()
