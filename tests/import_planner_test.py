import json
import os
import tempfile
import unittest

from agent_artifacts.import_candidates import ImportCandidate, ImportScan
from agent_artifacts.import_planner import plan_import
from agent_artifacts.model import CopyTree, Ok, WriteFile
from agent_artifacts.upstreams import UpstreamKey, UpstreamSource


def _source(path: str) -> UpstreamSource:
    return UpstreamSource(kind="github", repo="acme/superpowers", ref="main", path=path)


class ImportPlannerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.catalog = os.path.join(self._tmp.name, "catalog")
        self.upstream = os.path.join(self._tmp.name, "upstream")
        os.makedirs(self.catalog)
        os.makedirs(self.upstream)

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, root: str, rel: str, text: str) -> str:
        path = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def _scan(self, candidates):
        return ImportScan(
            mode="manifest",
            repo="acme/superpowers",
            ref="main",
            scan_root="",
            sha="abc123",
            root=self.upstream,
            candidates=tuple(candidates),
        )

    def test_plans_vendor_tracking_and_bundle(self):
        skill_dir = os.path.join(self.upstream, "skills", "debugging")
        os.makedirs(skill_dir)
        self._write(self.upstream, "skills/debugging/SKILL.md", "---\nname: debugging\n---\n")
        memory_file = self._write(self.upstream, "memory/superpowers.md", "# Memory\n")
        candidates = (
            ImportCandidate(
                key=UpstreamKey("skill", "debugging"),
                source=_source("skills/debugging"),
                detected_by="manifest",
                confidence="explicit",
                upstream_kind="tree",
                local_destination="skills/debugging",
                absolute_path=skill_dir,
            ),
            ImportCandidate(
                key=UpstreamKey("memory", "superpowers"),
                source=_source("memory/superpowers.md"),
                detected_by="manifest",
                confidence="explicit",
                upstream_kind="file",
                local_destination="memory/superpowers.md",
                absolute_path=memory_file,
            ),
        )

        result = plan_import(
            self._scan(candidates),
            catalog_root=self.catalog,
            bundle_name="superpowers",
            bundle_description="Superpowers kit",
        )

        self.assertIsInstance(result, Ok, getattr(result, "reason", ""))
        actions = result.value.plan
        self.assertIsInstance(actions[0], CopyTree)
        self.assertIsInstance(actions[1], WriteFile)
        self.assertTrue(actions[2].path.endswith("bundles/superpowers.json"))
        self.assertTrue(actions[3].path.endswith("upstreams.json"))
        bundle = json.loads(actions[2].content)
        self.assertEqual(bundle["includes"]["skills"], ["debugging"])
        self.assertEqual(bundle["includes"]["memory"], ["superpowers"])

    def test_existing_destination_conflicts_without_force(self):
        skill_dir = os.path.join(self.upstream, "skills", "debugging")
        os.makedirs(skill_dir)
        os.makedirs(os.path.join(self.catalog, "skills", "debugging"))
        candidate = ImportCandidate(
            key=UpstreamKey("skill", "debugging"),
            source=_source("skills/debugging"),
            detected_by="manifest",
            confidence="explicit",
            upstream_kind="tree",
            local_destination="skills/debugging",
            absolute_path=skill_dir,
        )

        result = plan_import(self._scan((candidate,)), catalog_root=self.catalog)

        self.assertIsInstance(result, Ok, getattr(result, "reason", ""))
        self.assertEqual(len(result.value.selection.conflicts), 1)
        self.assertIn("already exists", result.value.selection.conflicts[0].reason)

    def test_append_bundle_deduplicates_existing_includes(self):
        os.makedirs(os.path.join(self.catalog, "bundles"))
        self._write(
            self.catalog,
            "bundles/superpowers.json",
            json.dumps(
                {
                    "name": "superpowers",
                    "description": "Existing",
                    "includes": {"skills": ["debugging"]},
                }
            ),
        )
        skill_dir = os.path.join(self.upstream, "skills", "debugging")
        os.makedirs(skill_dir)
        candidate = ImportCandidate(
            key=UpstreamKey("skill", "debugging"),
            source=_source("skills/debugging"),
            detected_by="manifest",
            confidence="explicit",
            upstream_kind="tree",
            local_destination="skills/debugging",
            absolute_path=skill_dir,
        )

        result = plan_import(
            self._scan((candidate,)),
            catalog_root=self.catalog,
            bundle_name="superpowers",
            force=True,
        )

        self.assertIsInstance(result, Ok, getattr(result, "reason", ""))
        bundle_action = next(
            a
            for a in result.value.plan
            if isinstance(a, WriteFile) and a.path.endswith("superpowers.json")
        )
        bundle = json.loads(bundle_action.content)
        self.assertEqual(bundle["includes"]["skills"], ["debugging"])


if __name__ == "__main__":
    unittest.main()
