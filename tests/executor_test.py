"""Tests for the executor (WP-9). Uses an in-memory fake fs so they run without WP-6."""

from __future__ import annotations

import json
import pathlib
import tempfile
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

    def read_bytes(self, path: str) -> bytes:
        return self.files[path]

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
        fs.files["dst/old-skill"] = b"old"
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
        self.assertEqual(data, {"mcpServers": {"fetch": {"command": "uvx", "args": ["fetch"]}}})

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


class EffectObservationsTest(unittest.TestCase):
    def test_equal_write_merge_and_absent_remove_are_unchanged(self):
        fs = FakeFs()
        fs.files["same.txt"] = b"same"
        fs.files["settings.json"] = json.dumps({"tools": {"demo": {"command": "x"}}}).encode()
        plan = (
            WriteFile("same.txt", b"same"),
            MergeJson(
                file="settings.json",
                json_path="tools",
                mode="key",
                value={"command": "x"},
                identity=("demo",),
            ),
            RemovePath("already-absent"),
        )

        report = execute(plan, fs=fs)

        self.assertEqual(
            [(item.operation, item.target, item.state) for item in report.observations],
            [
                ("write-file", "same.txt", "unchanged"),
                ("merge-json", "settings.json#tools.demo", "unchanged"),
                ("remove-path", "already-absent", "unchanged"),
            ],
        )
        self.assertEqual(report.performed, ())

    def test_tree_comparison_skips_equal_copy_and_detects_changed_source(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            src = root / "src"
            dst = root / "dst"
            src.mkdir()
            dst.mkdir()
            (src / "nested").mkdir()
            (dst / "nested").mkdir()
            (src / "nested/data.txt").write_text("one", encoding="utf-8")
            (dst / "nested/data.txt").write_text("one", encoding="utf-8")
            (dst / "user-only.txt").write_text("preserve", encoding="utf-8")

            first = execute((CopyTree(str(src), str(dst)),))
            (src / "nested/data.txt").write_text("two", encoding="utf-8")
            second = execute((CopyTree(str(src), str(dst)),))

        self.assertEqual(first.observations[0].state, "unchanged")
        self.assertEqual(first.performed, ())
        self.assertEqual(second.observations[0].state, "changed")
        self.assertEqual(len(second.performed), 1)

    def test_missing_merge_key_with_none_value_is_still_a_change(self):
        fs = FakeFs()
        fs.files["settings.json"] = b'{"tools": {}}'

        report = execute(
            (
                MergeJson(
                    file="settings.json",
                    json_path="tools",
                    mode="key",
                    value=None,
                    identity=("demo",),
                ),
            ),
            fs=fs,
        )

        self.assertEqual(report.observations[0].state, "changed")
        self.assertIn("demo", json.loads(fs.files["settings.json"])["tools"])

    def test_effect_failure_is_a_value_and_later_actions_continue(self):
        class FailingFs(FakeFs):
            def write_atomic(self, path: str, content: bytes) -> None:
                if path == "blocked":
                    raise PermissionError("denied")
                super().write_atomic(path, content)

        report = execute(
            (WriteFile("blocked", b"x"), WriteFile("ok", b"y")),
            fs=FailingFs(),
        )

        self.assertEqual(report.observations[0].state, "failed")
        self.assertIn("denied", report.observations[0].detail or "")
        self.assertEqual(report.observations[1].state, "changed")
        self.assertTrue(report.failed)


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
