"""WP-36 upstream planner tests.

These tests are intentionally pure: local catalog state is represented by content hashes,
staged validation by an injected error map, and staged file bytes by an injected content map.
The planner returns status records plus existing model Actions; the command shell will later
perform the actual filesystem work.
"""

import unittest

from agent_artifacts.model import CopyTree, Ok, RemovePath, Warn, WriteFile
from agent_artifacts.upstream_planner import plan_upstream_check, plan_upstream_update
from agent_artifacts.upstream_source import ResolvedUpstream
from agent_artifacts.upstreams import UpstreamEntry, UpstreamKey, UpstreamSource, UpstreamSync


def make_entry(artifact_type="skill", name="superpowers", *, base_hash="sha256:base"):
    key = UpstreamKey(artifact_type, name)
    return UpstreamEntry(
        key=key,
        source=UpstreamSource(
            kind="github",
            repo="example/source",
            ref="main",
            path=source_path(artifact_type, name),
        ),
        last_synced=UpstreamSync(
            sha="base-sha",
            content_hash=base_hash,
            synced_at="2026-06-22T00:00:00Z",
        ),
    )


def source_path(artifact_type, name):
    if artifact_type == "skill":
        return f"skills/{name}"
    if artifact_type == "hook":
        return f"hooks/{name}"
    if artifact_type == "guideline":
        return f"guidelines/{name}.md"
    if artifact_type == "mcp":
        return f"mcp/{name}.json"
    if artifact_type == "memory":
        return f"memory/{name}.md"
    return f"{artifact_type}/{name}"


def make_resolved(
    entry,
    *,
    head_hash="sha256:base",
    head_sha="head-sha",
    root="staged",
    path=None,
):
    return ResolvedUpstream(
        entry=entry,
        sha=head_sha,
        root=root,
        path=path if path is not None else entry.source.path,
        content_hash=head_hash,
    )


def unwrap_ok(result):
    if not isinstance(result, Ok):
        raise AssertionError(f"expected Ok, got {result!r}")
    return result.value


class UpstreamCheckPlannerTests(unittest.TestCase):
    def test_check_reports_up_to_date_when_content_hash_matches_last_sync(self):
        entry = make_entry()
        status = unwrap_ok(plan_upstream_check((entry,), (make_resolved(entry),)))[0]

        self.assertEqual(status.key, entry.key)
        self.assertEqual(status.state, "up_to_date")
        self.assertEqual(status.base_sha, "base-sha")
        self.assertEqual(status.head_sha, "head-sha")
        self.assertEqual(status.base_hash, "sha256:base")
        self.assertEqual(status.head_hash, "sha256:base")

    def test_check_reports_changed_when_upstream_content_hash_differs(self):
        entry = make_entry()
        status = unwrap_ok(
            plan_upstream_check((entry,), (make_resolved(entry, head_hash="sha256:new"),))
        )[0]

        self.assertEqual(status.state, "changed")
        self.assertEqual(status.base_hash, "sha256:base")
        self.assertEqual(status.head_hash, "sha256:new")

    def test_check_reports_local_drift_against_last_synced_hash(self):
        entry = make_entry()
        status = unwrap_ok(
            plan_upstream_check(
                (entry,),
                (make_resolved(entry),),
                local_hashes={entry.key: "sha256:local-edit"},
            )
        )[0]

        self.assertEqual(status.state, "local_drift")
        self.assertIn("local catalog differs", status.message)

    def test_check_reports_missing_upstream_when_no_resolved_snapshot_exists(self):
        entry = make_entry()
        status = unwrap_ok(plan_upstream_check((entry,), ()))[0]

        self.assertEqual(status.state, "missing_upstream")
        self.assertEqual(status.base_sha, "base-sha")
        self.assertEqual(status.base_hash, "sha256:base")
        self.assertIsNone(status.head_sha)
        self.assertIsNone(status.head_hash)


class UpstreamUpdatePlannerTests(unittest.TestCase):
    def test_update_conflicts_when_local_and_upstream_both_changed(self):
        entry = make_entry()
        result = unwrap_ok(
            plan_upstream_update(
                (entry,),
                (make_resolved(entry, head_hash="sha256:new"),),
                local_hashes={entry.key: "sha256:local-edit"},
            )
        )

        self.assertTrue(result.conflict)
        self.assertEqual(result.statuses[0].state, "conflict")
        self.assertEqual(
            result.plan,
            (
                Warn(
                    message=(
                        "skill/superpowers: local catalog and upstream both differ "
                        "from last synced upstream; use --force to overwrite local changes"
                    )
                ),
                RemovePath(path="skills/superpowers.agent-artifacts-upstream-new"),
                CopyTree(
                    src="staged/skills/superpowers",
                    dst="skills/superpowers.agent-artifacts-upstream-new",
                ),
            ),
        )

    def test_file_conflict_writes_candidate_sidecar_without_touching_destination(self):
        entry = make_entry("guideline", "python-style")
        result = unwrap_ok(
            plan_upstream_update(
                (entry,),
                (make_resolved(entry, head_hash="sha256:new"),),
                local_hashes={entry.key: "sha256:local-edit"},
                file_contents={entry.key: b"incoming\n"},
            )
        )

        self.assertTrue(result.conflict)
        self.assertEqual(result.statuses[0].state, "conflict")
        self.assertEqual(
            result.plan,
            (
                Warn(
                    message=(
                        "guideline/python-style: local catalog and upstream both differ "
                        "from last synced upstream; use --force to overwrite local changes"
                    )
                ),
                WriteFile(
                    path="guidelines/python-style.md.agent-artifacts-upstream-new",
                    content=b"incoming\n",
                ),
            ),
        )

    def test_force_update_overwrites_conflicted_tree_artifact(self):
        entry = make_entry("skill", "superpowers")
        result = unwrap_ok(
            plan_upstream_update(
                (entry,),
                (make_resolved(entry, head_hash="sha256:new"),),
                local_hashes={entry.key: "sha256:local-edit"},
                force=True,
            )
        )

        self.assertFalse(result.conflict)
        self.assertEqual(result.statuses[0].state, "changed")
        self.assertEqual(
            result.plan,
            (
                RemovePath(path="skills/superpowers"),
                CopyTree(src="staged/skills/superpowers", dst="skills/superpowers"),
            ),
        )

    def test_update_reports_invalid_staged_artifact_without_writes(self):
        entry = make_entry()
        result = unwrap_ok(
            plan_upstream_update(
                (entry,),
                (make_resolved(entry, head_hash="sha256:new"),),
                validation_errors={entry.key: "missing SKILL.md"},
            )
        )

        self.assertTrue(result.conflict)
        self.assertEqual(result.statuses[0].state, "invalid")
        self.assertIn("missing SKILL.md", result.statuses[0].message)
        self.assertFalse(any(isinstance(a, (CopyTree, RemovePath, WriteFile)) for a in result.plan))

    def test_update_warns_and_leaves_missing_upstream_in_place(self):
        entry = make_entry()
        result = unwrap_ok(plan_upstream_update((entry,), ()))

        self.assertFalse(result.conflict)
        self.assertEqual(result.statuses[0].state, "missing_upstream")
        self.assertEqual(result.plan, (Warn(message="skill/superpowers: upstream path missing"),))

    def test_clean_tree_update_removes_stale_local_files_before_copy(self):
        entry = make_entry("hook", "block-secrets")
        result = unwrap_ok(
            plan_upstream_update(
                (entry,),
                (make_resolved(entry, head_hash="sha256:new"),),
            )
        )

        self.assertEqual(result.statuses[0].state, "changed")
        self.assertEqual(
            result.plan,
            (
                RemovePath(path="hooks/block-secrets"),
                CopyTree(src="staged/hooks/block-secrets", dst="hooks/block-secrets"),
            ),
        )

    def test_tree_update_uses_absolute_staged_path_without_rejoining_root(self):
        entry = make_entry("skill", "superpowers")
        result = unwrap_ok(
            plan_upstream_update(
                (entry,),
                (
                    make_resolved(
                        entry,
                        head_hash="sha256:new",
                        root="/cache/example",
                        path="/cache/example/skills/superpowers",
                        head_sha="head-sha",
                    ),
                ),
            )
        )

        self.assertEqual(
            result.plan,
            (
                RemovePath(path="skills/superpowers"),
                CopyTree(src="/cache/example/skills/superpowers", dst="skills/superpowers"),
            ),
        )

    def test_update_writes_file_artifacts_to_catalog_destinations(self):
        cases = (
            ("guideline", "python-style", "guidelines/python-style.md"),
            ("mcp", "postgres", "mcp/postgres.json"),
            ("memory", "house", "memory/house.md"),
        )
        for artifact_type, name, destination in cases:
            with self.subTest(artifact_type=artifact_type):
                entry = make_entry(artifact_type, name)
                result = unwrap_ok(
                    plan_upstream_update(
                        (entry,),
                        (make_resolved(entry, head_hash="sha256:new"),),
                        file_contents={entry.key: b"new body\n"},
                    )
                )

                self.assertEqual(result.statuses[0].state, "changed")
                self.assertEqual(
                    result.plan,
                    (WriteFile(path=destination, content=b"new body\n"),),
                )

    def test_update_copies_directory_mcp_artifacts(self):
        entry = UpstreamEntry(
            key=UpstreamKey("mcp", "stripe"),
            source=UpstreamSource(
                kind="github",
                repo="example/source",
                ref="main",
                path="servers/stripe",
            ),
            last_synced=UpstreamSync(
                sha="base-sha",
                content_hash="sha256:base",
                synced_at="2026-06-22T00:00:00Z",
            ),
        )

        result = unwrap_ok(
            plan_upstream_update(
                (entry,),
                (
                    make_resolved(
                        entry,
                        head_hash="sha256:new",
                        root="staged",
                        path="servers/stripe",
                    ),
                ),
            )
        )

        self.assertEqual(result.statuses[0].state, "changed")
        self.assertEqual(
            result.plan,
            (
                RemovePath(path="mcp/stripe"),
                CopyTree(src="staged/servers/stripe", dst="mcp/stripe"),
            ),
        )

    def test_update_keeps_local_drift_when_upstream_has_not_changed(self):
        entry = make_entry()
        result = unwrap_ok(
            plan_upstream_update(
                (entry,),
                (make_resolved(entry, head_hash="sha256:base"),),
                local_hashes={entry.key: "sha256:local-edit"},
            )
        )

        self.assertFalse(result.conflict)
        self.assertEqual(result.statuses[0].state, "local_drift")
        self.assertEqual(
            result.plan,
            (Warn(message="skill/superpowers: local catalog differs from last synced upstream"),),
        )


if __name__ == "__main__":
    unittest.main()
