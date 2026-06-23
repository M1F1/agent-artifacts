"""End-to-end coverage for the maintainer-side ``upstream`` command family."""

import io
import json
import os
import pathlib
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from agent_artifacts import cli
from agent_artifacts.model import Ok
from agent_artifacts.upstream_source import ResolvedUpstream, hash_upstream_path

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "upstreams"


class UpstreamE2ETests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.catalog_root = os.path.join(self._tmp.name, "catalog")
        self.remote_root = os.path.join(self._tmp.name, "remote")
        shutil.copytree(FIXTURES / "catalog", self.catalog_root)
        shutil.copytree(FIXTURES / "remote", self.remote_root)
        self.local_skill = os.path.join(self.catalog_root, "skills", "demo", "SKILL.md")

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
        self.assertEqual(
            self._states_by_key(check_payload),
            {
                "memory/house": "up_to_date",
                "skill/demo": "changed",
            },
        )

        bundle_code, bundle_output = self._run_cli(
            "upstream",
            "check",
            "--bundle",
            "backend",
            "--source",
            self.catalog_root,
            "--json",
        )

        self.assertEqual(bundle_code, 0)
        bundle_payload = json.loads(bundle_output)
        self.assertEqual(bundle_payload["selected"], ["skill/demo", "memory/house"])

        update_code, update_output = self._run_cli(
            "upstream",
            "update",
            "skill/demo",
            "--source",
            self.catalog_root,
        )

        self.assertEqual(update_code, 0)
        self.assertIn("Updated 1 upstream artifact", update_output)
        self.assertIn("Updated demo skill", self._read_file(self.local_skill))

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
        self.assertEqual(
            self._states_by_key(recheck_payload),
            {
                "memory/house": "up_to_date",
                "skill/demo": "up_to_date",
            },
        )

        self._seed_skill(self.catalog_root, "local edit")
        self._seed_skill(self.remote_root, "newer upstream")
        tracking_before = self._read_file(os.path.join(self.catalog_root, "upstreams.json"))

        conflict_code, conflict_output = self._run_cli(
            "upstream",
            "update",
            "skill/demo",
            "--source",
            self.catalog_root,
        )

        self.assertEqual(conflict_code, 4)
        self.assertIn("local catalog and upstream both differ", conflict_output)
        self.assertIn("local edit", self._read_file(self.local_skill))
        sidecar = os.path.join(
            self.catalog_root, "skills", "demo.agent-artifacts-upstream-new", "SKILL.md"
        )
        self.assertIn("newer upstream", self._read_file(sidecar))
        self.assertEqual(
            self._read_file(os.path.join(self.catalog_root, "upstreams.json")),
            tracking_before,
        )

    def _run_cli(self, *argv: str):
        def fake_resolve(entry):
            staged_path = os.path.join(self.remote_root, *entry.source.path.split("/"))
            return Ok(
                ResolvedUpstream(
                    entry=entry,
                    sha="new-sha",
                    root=self.remote_root,
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

    def _read_file(self, path: str) -> str:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()

    def _states_by_key(self, payload):
        return {item["key"]: item["state"] for item in payload["statuses"]}


if __name__ == "__main__":
    unittest.main()
