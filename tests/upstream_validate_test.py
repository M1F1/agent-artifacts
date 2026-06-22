"""Validation tests for ``upstreams.json`` against a local catalog."""

import unittest
from typing import Any, cast

from agent_artifacts.model import Artifact, Catalog
from agent_artifacts.upstreams import (
    UpstreamCatalog,
    UpstreamEntry,
    UpstreamKey,
    UpstreamSource,
    UpstreamSync,
    validate_upstreams,
)


def _catalog(*artifacts: Artifact) -> Catalog:
    return Catalog(
        artifacts={(artifact.type, artifact.name): artifact for artifact in artifacts},
        bundles={},
    )


def _artifact(artifact_type, name, root=None) -> Artifact:
    roots = {
        "skill": f"skills/{name}",
        "guideline": f"guidelines/{name}.md",
        "mcp": f"mcp/{name}.json",
        "hook": f"hooks/{name}",
        "memory": f"memory/{name}.md",
    }
    return Artifact(type=artifact_type, name=name, root=root or roots[artifact_type])


_DEFAULT_SYNC = UpstreamSync("base-sha", "sha256:base", "2026-06-22T10:00:00Z")


def _entry(
    artifact_type="skill",
    name="demo",
    *,
    repo="acme/demo",
    kind="github",
    last_synced=_DEFAULT_SYNC,
) -> UpstreamEntry:
    key = UpstreamKey(artifact_type, name)
    return UpstreamEntry(
        key=key,
        source=UpstreamSource(
            kind=cast(Any, kind),
            repo=repo,
            ref="main",
            path=f"{artifact_type}s/{name}",
        ),
        last_synced=last_synced,
    )


def _upstreams(*entries: UpstreamEntry) -> UpstreamCatalog:
    return UpstreamCatalog(version=1, entries={entry.key: entry for entry in entries})


class UpstreamValidationTests(unittest.TestCase):
    def test_valid_upstream_metadata_has_no_errors(self):
        errors = validate_upstreams(
            _upstreams(_entry("skill", "demo")),
            _catalog(_artifact("skill", "demo")),
        )

        self.assertEqual(errors, ())

    def test_reports_missing_local_artifact(self):
        errors = validate_upstreams(
            _upstreams(_entry("skill", "ghost")),
            _catalog(_artifact("skill", "demo")),
        )

        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].code, 2)
        self.assertIn("unknown artifact skill/ghost", errors[0].reason)

    def test_reports_missing_last_sync_state(self):
        errors = validate_upstreams(
            _upstreams(_entry("skill", "demo", last_synced=None)),
            _catalog(_artifact("skill", "demo")),
        )

        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].code, 2)
        self.assertIn("skill/demo: last_synced is required", errors[0].reason)

    def test_reports_unknown_source_kind_and_invalid_repo_shape(self):
        errors = validate_upstreams(
            _upstreams(_entry("skill", "demo", kind="gitlab", repo="not-a-github-repo")),
            _catalog(_artifact("skill", "demo")),
        )

        reasons = [err.reason for err in errors]
        self.assertTrue(any("source.kind must be 'github'" in reason for reason in reasons))
        self.assertTrue(any("source.repo must be 'owner/name'" in reason for reason in reasons))

    def test_reports_catalog_root_that_does_not_match_key_destination(self):
        errors = validate_upstreams(
            _upstreams(_entry("skill", "demo")),
            _catalog(_artifact("skill", "demo", root="guidelines/demo.md")),
        )

        self.assertEqual(len(errors), 1)
        self.assertIn("expected catalog root skills/demo", errors[0].reason)


if __name__ == "__main__":
    unittest.main()
