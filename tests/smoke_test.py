"""Wave-0 smoke tests: the frozen contracts import, are immutable, and fp combinators work.

Run: ``python -m unittest discover -s tests -p "*_test.py"``
"""

import dataclasses
import unittest

from agent_artifacts import fp, model
from agent_artifacts.model import (
    Artifact,
    Err,
    ManifestEntry,
    MergeJson,
    Ok,
    Resolved,
    WriteFile,
    source_label,
)


class ContractTests(unittest.TestCase):
    def test_records_are_frozen(self):
        art = Artifact(type="skill", name="code-review", root="skills/code-review")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            art.name = "other"  # type: ignore[misc]

    def test_action_algebra_present(self):
        plan: model.Plan = (
            WriteFile(path="a.txt", content=b"x"),
            MergeJson(file=".mcp.json", json_path="mcpServers", mode="key", value={}, identity=("name",)),
        )
        self.assertEqual(len(plan), 2)

    def test_source_label(self):
        self.assertEqual(source_label(Resolved(kind="main", sha="abc123")), "main:abc123")

    def test_manifest_entry_defaults(self):
        e = ManifestEntry(artifact="postgres", type="mcp", profile="claude", source="main:abc")
        self.assertEqual(e.files, {})
        self.assertIsNone(e.merge)


class FpTests(unittest.TestCase):
    def test_map_and_bind(self):
        self.assertEqual(fp.map_ok(Ok(2), lambda x: x + 1), Ok(3))
        self.assertEqual(fp.bind(Ok(2), lambda x: Ok(x * 10)), Ok(20))
        self.assertEqual(fp.bind(Err("boom"), lambda x: Ok(x)), Err("boom"))

    def test_sequence_short_circuits(self):
        self.assertEqual(fp.sequence([Ok(1), Ok(2)]), Ok((1, 2)))
        self.assertEqual(fp.sequence([Ok(1), Err("bad"), Ok(3)]), Err("bad"))

    def test_collect_accumulates(self):
        res = fp.collect([Ok(1), Err("e1"), Err("e2")])
        self.assertIsInstance(res, Err)
        self.assertIn("e1", res.reason)
        self.assertIn("e2", res.reason)

    def test_compose_and_pipe(self):
        f = fp.compose(lambda x: x + 1, lambda x: x * 2)
        self.assertEqual(f(3), 8)  # (3+1)*2
        self.assertEqual(fp.pipe(3, lambda x: x + 1, lambda x: x * 2), 8)


if __name__ == "__main__":
    unittest.main()
