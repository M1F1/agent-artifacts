"""WP-4 tests: consumer manifest parse/dump roundtrip, upsert/remove, prune.

Run: ``python -m unittest discover -s tests -p "manifest_test.py" -v``
"""

import unittest

from agent_artifacts import manifest
from agent_artifacts.model import (
    Err,
    Manifest,
    ManifestEntry,
    MergeProof,
    Ok,
    RemovePath,
    WriteManifest,
)


def _skill_entry() -> ManifestEntry:
    return ManifestEntry(
        artifact="code-review",
        type="skill",
        profile="claude",
        source="pin:a1b2c3d",
        bundle="backend",
        files={".claude/skills/code-review/SKILL.md": "sha256:aaa"},
        installed_at="2026-06-19T10:00:00Z",
    )


def _mcp_entry() -> ManifestEntry:
    return ManifestEntry(
        artifact="postgres",
        type="mcp",
        profile="claude",
        source="main:9f8e7d6",
        bundle="backend",
        merge=MergeProof(
            file=".mcp.json",
            json_path="mcpServers.postgres",
            mode="key",
            identity={},
            value_hash="sha256:bbb",
            created_file=False,
            overwrote=False,
        ),
        installed_at="2026-06-19T10:00:00Z",
    )


def _hook_entry() -> ManifestEntry:
    # Hooks carry BOTH files and merge (docs/design/DESIGN.md §12).
    return ManifestEntry(
        artifact="block-secrets",
        type="hook",
        profile="claude",
        source="main:9f8e7d6",
        bundle="base",
        files={".claude/hooks/block-secrets/guard.py": "sha256:ccc"},
        merge=MergeProof(
            file=".claude/settings.json",
            json_path="hooks.PreToolUse",
            mode="list",
            identity={
                "matcher": "Edit|Write|MultiEdit",
                "command": "python3 .claude/hooks/block-secrets/guard.py",
            },
            value_hash="sha256:ddd",
            created_file=False,
            overwrote=False,
        ),
        installed_at="2026-06-19T10:00:00Z",
    )


def _full_manifest() -> Manifest:
    return Manifest(
        repo="org/agent-artifacts",
        installed=(_skill_entry(), _mcp_entry(), _hook_entry()),
    )


class RoundtripTests(unittest.TestCase):
    def test_dump_parse_roundtrip(self):
        m = _full_manifest()
        parsed = manifest.parse_manifest(manifest.dump_manifest(m))
        self.assertIsInstance(parsed, Ok)
        self.assertEqual(parsed.value, m)

    def test_hook_entry_roundtrips_both_proofs(self):
        m = Manifest(repo="org/x", installed=(_hook_entry(),))
        parsed = manifest.parse_manifest(manifest.dump_manifest(m))
        self.assertIsInstance(parsed, Ok)
        entry = parsed.value.installed[0]
        self.assertEqual(entry.files, _hook_entry().files)
        self.assertIsNotNone(entry.merge)
        self.assertEqual(entry.merge.mode, "list")
        self.assertEqual(
            entry.merge.identity["command"],
            "python3 .claude/hooks/block-secrets/guard.py",
        )

    def test_dump_is_stable(self):
        m = _full_manifest()
        self.assertEqual(manifest.dump_manifest(m), manifest.dump_manifest(m))
        # Re-dumping a parsed manifest is a no-op.
        once = manifest.dump_manifest(m)
        twice = manifest.dump_manifest(manifest.parse_manifest(once).value)
        self.assertEqual(once, twice)

    def test_empty_manifest_roundtrips(self):
        m = manifest.empty_manifest("org/x")
        parsed = manifest.parse_manifest(manifest.dump_manifest(m))
        self.assertEqual(parsed, Ok(m))

    def test_none_fields_omitted(self):
        e = ManifestEntry(artifact="g", type="guideline", profile="claude", source="main:abc")
        text = manifest.dump_manifest(Manifest(repo="r", installed=(e,)))
        self.assertNotIn('"bundle"', text)
        self.assertNotIn('"merge"', text)
        self.assertIn('"files"', text)  # files always present as an object


class UpsertTests(unittest.TestCase):
    def test_append_when_key_absent(self):
        m = Manifest(repo="r", installed=(_skill_entry(),))
        updated = manifest.upsert(m, _mcp_entry())
        self.assertEqual(len(updated.installed), 2)
        self.assertEqual(updated.installed[1].artifact, "postgres")
        # Original is untouched (new manifest returned).
        self.assertEqual(len(m.installed), 1)

    def test_replace_when_key_present(self):
        m = Manifest(repo="r", installed=(_skill_entry(), _mcp_entry()))
        replacement = ManifestEntry(
            artifact="code-review",
            type="skill",
            profile="claude",
            source="pin:NEWSHA",
            files={".claude/skills/code-review/SKILL.md": "sha256:zzz"},
        )
        updated = manifest.upsert(m, replacement)
        self.assertEqual(len(updated.installed), 2)
        self.assertEqual(updated.installed[0].source, "pin:NEWSHA")
        # Order preserved: replaced in place, postgres still second.
        self.assertEqual(updated.installed[1].artifact, "postgres")

    def test_same_artifact_different_profile_appends(self):
        m = Manifest(repo="r", installed=(_skill_entry(),))
        other_profile = ManifestEntry(
            artifact="code-review", type="skill", profile="codex", source="pin:a1b2c3d"
        )
        updated = manifest.upsert(m, other_profile)
        self.assertEqual(len(updated.installed), 2)


class RemoveTests(unittest.TestCase):
    def test_remove_existing(self):
        m = _full_manifest()
        updated = manifest.remove_entry(m, "postgres", "claude")
        arts = [e.artifact for e in updated.installed]
        self.assertEqual(arts, ["code-review", "block-secrets"])

    def test_remove_missing_is_noop(self):
        m = _full_manifest()
        updated = manifest.remove_entry(m, "nope", "claude")
        self.assertEqual(updated, m)

    def test_remove_respects_profile(self):
        a = ManifestEntry(artifact="x", type="skill", profile="claude", source="main:1")
        b = ManifestEntry(artifact="x", type="skill", profile="codex", source="main:1")
        m = Manifest(repo="r", installed=(a, b))
        updated = manifest.remove_entry(m, "x", "claude")
        self.assertEqual(updated.installed, (b,))


class EntriesForTests(unittest.TestCase):
    def test_filters_by_profile_preserving_order(self):
        a = ManifestEntry(artifact="a", type="skill", profile="claude", source="main:1")
        b = ManifestEntry(artifact="b", type="skill", profile="codex", source="main:1")
        c = ManifestEntry(artifact="c", type="skill", profile="claude", source="main:1")
        m = Manifest(repo="r", installed=(a, b, c))
        self.assertEqual(manifest.entries_for(m, "claude"), (a, c))
        self.assertEqual(manifest.entries_for(m, "codex"), (b,))
        self.assertEqual(manifest.entries_for(m, "none"), ())


class PrunePlanTests(unittest.TestCase):
    def test_removepaths_for_dropped_then_write_manifest(self):
        m = _full_manifest()
        # Keep only the skill; drop the mcp (no files) and the hook (one file).
        keep = (("code-review", "claude"),)
        plan = manifest.prune_plan(m, keep)

        removes = [a for a in plan if isinstance(a, RemovePath)]
        self.assertEqual(
            [r.path for r in removes],
            [".claude/hooks/block-secrets/guard.py"],
        )

        # Exactly one trailing WriteManifest carrying only the survivor(s).
        self.assertIsInstance(plan[-1], WriteManifest)
        writes = [a for a in plan if isinstance(a, WriteManifest)]
        self.assertEqual(len(writes), 1)
        kept_arts = [e.artifact for e in plan[-1].entries]
        self.assertEqual(kept_arts, ["code-review"])

    def test_keep_all_emits_no_removes(self):
        m = _full_manifest()
        keep = (
            ("code-review", "claude"),
            ("postgres", "claude"),
            ("block-secrets", "claude"),
        )
        plan = manifest.prune_plan(m, keep)
        self.assertFalse([a for a in plan if isinstance(a, RemovePath)])
        self.assertIsInstance(plan[-1], WriteManifest)
        self.assertEqual(len(plan[-1].entries), 3)

    def test_drop_all_removes_every_file(self):
        m = _full_manifest()
        plan = manifest.prune_plan(m, keep=())
        removed = sorted(a.path for a in plan if isinstance(a, RemovePath))
        self.assertEqual(
            removed,
            sorted(
                [
                    ".claude/skills/code-review/SKILL.md",
                    ".claude/hooks/block-secrets/guard.py",
                ]
            ),
        )
        self.assertEqual(plan[-1], WriteManifest(entries=()))


class ParseErrorTests(unittest.TestCase):
    def test_corrupt_json_is_err_code_5(self):
        res = manifest.parse_manifest("{not valid json")
        self.assertIsInstance(res, Err)
        self.assertEqual(res.code, 5)

    def test_missing_required_field_is_err_code_5(self):
        # Missing "repo".
        res = manifest.parse_manifest('{"installed": []}')
        self.assertIsInstance(res, Err)
        self.assertEqual(res.code, 5)

    def test_entry_missing_required_field_is_err_code_5(self):
        # Entry missing "source".
        text = (
            '{"repo": "r", "installed": [{"artifact": "a", "type": "skill", "profile": "claude"}]}'
        )
        res = manifest.parse_manifest(text)
        self.assertIsInstance(res, Err)
        self.assertEqual(res.code, 5)


if __name__ == "__main__":
    unittest.main()
