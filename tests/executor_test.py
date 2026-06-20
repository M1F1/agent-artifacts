"""Tests for the executor (WP-9). Uses an in-memory fake fs so they run without WP-6."""

from __future__ import annotations

import json
import unittest

from agent_artifacts.executor import (
    MANIFEST_PATH,
    Report,
    execute,
    plan_to_json,
    render_plan,
)
from agent_artifacts.model import (
    CopyTree,
    ManifestEntry,
    MergeJson,
    RemovePath,
    Warn,
    WriteFile,
    WriteManifest,
)


class FakeFs:
    """In-memory fake of the io.fs performer interface, backed by dicts.

    `files` maps path -> bytes (write_atomic / remove_path / exists).
    `trees` records copy_tree (src -> dst) calls.
    JSON files are stored as encoded bytes and parsed back in read_json.
    """

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.trees: list[tuple[str, str]] = []
        self.removed: list[str] = []

    def read_json(self, path: str):
        return json.loads(self.files[path].decode())

    def write_atomic(self, path: str, content: bytes) -> None:
        assert isinstance(content, (bytes, bytearray)), "write_atomic expects bytes"
        self.files[path] = bytes(content)

    def copy_tree(self, src: str, dst: str) -> None:
        self.trees.append((src, dst))

    def remove_path(self, path: str) -> None:
        self.removed.append(path)
        self.files.pop(path, None)

    def exists(self, path: str) -> bool:
        return path in self.files


def _entry() -> ManifestEntry:
    return ManifestEntry(
        artifact="code-review",
        type="skill",
        profile="claude",
        source="main:abc123",
        files={"skills/code-review/SKILL.md": "sha256:deadbeef"},
        installed_at="2026-06-20T00:00:00Z",
    )


class ExecuteOrderTest(unittest.TestCase):
    def test_every_action_kind_executes_in_order(self):
        fs = FakeFs()
        plan = (
            CopyTree(src="src/skills/code-review", dst="dst/skills/code-review"),
            WriteFile(path="dst/AGENTS.md", content=b"hello"),
            MergeJson(
                file="dst/.mcp.json",
                json_path="mcpServers",
                mode="key",
                value={"command": "x"},
                identity=("fetch",),
            ),
            RemovePath(path="dst/old-skill"),
            WriteManifest(entries=(_entry(),)),
            Warn(message="heads up"),
        )

        report = execute(plan, fs=fs)

        self.assertIsInstance(report, Report)
        # Ordered record of what ran.
        kinds = [line.split()[0] for line in report.performed]
        self.assertEqual(
            kinds,
            [
                "copy_tree",
                "write_file",
                "merge_json",
                "remove_path",
                "write_manifest",
                "warn",
            ],
        )
        # Effects landed on the fake fs.
        self.assertEqual(fs.trees, [("src/skills/code-review", "dst/skills/code-review")])
        self.assertEqual(fs.files["dst/AGENTS.md"], b"hello")
        self.assertIn("dst/.mcp.json", fs.files)
        self.assertEqual(fs.removed, ["dst/old-skill"])
        self.assertTrue(report.manifest_written)
        self.assertIn(MANIFEST_PATH, fs.files)
        self.assertEqual(report.warnings, ("heads up",))

    def test_unknown_action_raises(self):
        with self.assertRaises(TypeError):
            execute((object(),), fs=FakeFs())


class MergeJsonKeyModeTest(unittest.TestCase):
    def test_key_mode_sets_key_in_new_file(self):
        fs = FakeFs()
        action = MergeJson(
            file="dst/.mcp.json",
            json_path="mcpServers",
            mode="key",
            value={"command": "uvx", "args": ["fetch"]},
            identity=("fetch",),
        )
        execute((action,), fs=fs)

        data = json.loads(fs.files["dst/.mcp.json"].decode())
        self.assertEqual(
            data, {"mcpServers": {"fetch": {"command": "uvx", "args": ["fetch"]}}}
        )

    def test_key_mode_preserves_siblings_and_merges_into_existing_file(self):
        fs = FakeFs()
        fs.files["dst/.mcp.json"] = json.dumps(
            {"mcpServers": {"other": {"command": "keep"}}}
        ).encode()
        action = MergeJson(
            file="dst/.mcp.json",
            json_path="mcpServers",
            mode="key",
            value={"command": "new"},
            identity=("fetch",),
        )
        execute((action,), fs=fs)

        data = json.loads(fs.files["dst/.mcp.json"].decode())
        self.assertEqual(data["mcpServers"]["other"], {"command": "keep"})
        self.assertEqual(data["mcpServers"]["fetch"], {"command": "new"})

    def test_nested_dotted_path_is_created(self):
        fs = FakeFs()
        action = MergeJson(
            file="dst/settings.json",
            json_path="a.b.c",
            mode="key",
            value=1,
            identity=("leaf",),
        )
        execute((action,), fs=fs)
        data = json.loads(fs.files["dst/settings.json"].decode())
        self.assertEqual(data, {"a": {"b": {"c": {"leaf": 1}}}})


class MergeJsonListModeTest(unittest.TestCase):
    def _action(self, value):
        return MergeJson(
            file="dst/settings.json",
            json_path="hooks.PreToolUse",
            mode="list",
            value=value,
            identity=(),
        )

    def test_list_mode_appends(self):
        fs = FakeFs()
        execute((self._action({"id": "h1"}),), fs=fs)
        data = json.loads(fs.files["dst/settings.json"].decode())
        self.assertEqual(data["hooks"]["PreToolUse"], [{"id": "h1"}])

    def test_list_mode_is_idempotent_on_rerun(self):
        fs = FakeFs()
        plan = (self._action({"id": "h1"}),)
        execute(plan, fs=fs)
        execute(plan, fs=fs)  # re-run against the same fs
        data = json.loads(fs.files["dst/settings.json"].decode())
        # Deep-equal element already present -> no duplicate.
        self.assertEqual(data["hooks"]["PreToolUse"], [{"id": "h1"}])

    def test_list_mode_appends_distinct_values(self):
        fs = FakeFs()
        execute((self._action({"id": "h1"}),), fs=fs)
        execute((self._action({"id": "h2"}),), fs=fs)
        data = json.loads(fs.files["dst/settings.json"].decode())
        self.assertEqual(data["hooks"]["PreToolUse"], [{"id": "h1"}, {"id": "h2"}])


class RenderersTest(unittest.TestCase):
    def setUp(self):
        self.plan = (
            CopyTree(src="s", dst="d"),
            WriteFile(path="f", content=b"abc"),
            MergeJson(
                file="m.json",
                json_path="k",
                mode="key",
                value={"x": 1},
                identity=("id",),
            ),
            RemovePath(path="p"),
            WriteManifest(entries=(_entry(),)),
            Warn(message="w"),
        )

    def test_render_plan_produces_one_line_per_action_and_no_disk_effect(self):
        fs = FakeFs()
        out = render_plan(self.plan)
        self.assertEqual(len(out.splitlines()), len(self.plan))
        self.assertIn("copy-tree", out)
        self.assertIn("warn", out)
        # Renderers must not touch the fs.
        self.assertEqual(fs.files, {})
        self.assertEqual(fs.trees, [])
        self.assertEqual(fs.removed, [])

    def test_plan_to_json_parses_back_and_no_disk_effect(self):
        fs = FakeFs()
        out = plan_to_json(self.plan)
        parsed = json.loads(out)  # must round-trip through json.loads
        self.assertIsInstance(parsed, list)
        self.assertEqual(len(parsed), len(self.plan))
        self.assertEqual(parsed[0]["action"], "copy-tree")
        self.assertEqual(
            [o["action"] for o in parsed],
            [
                "copy-tree",
                "write-file",
                "merge-json",
                "remove-path",
                "write-manifest",
                "warn",
            ],
        )
        # No disk effect.
        self.assertEqual(fs.files, {})


if __name__ == "__main__":
    unittest.main()
