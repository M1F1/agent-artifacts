"""Pure maintainer catalog-context and health projections."""

import unittest

from agent_artifacts.maintainer import MaintainerContext, build_catalog_health
from agent_artifacts.model import Artifact, Catalog
from agent_artifacts.upstream_planner import UpstreamStatus
from agent_artifacts.upstreams import (
    UpstreamCatalog,
    UpstreamEntry,
    UpstreamKey,
    UpstreamSource,
)


class CatalogHealthTests(unittest.TestCase):
    def setUp(self):
        artifacts = {
            ("skill", "one"): Artifact("skill", "one", "skills/one"),
            ("skill", "two"): Artifact("skill", "two", "skills/two"),
            ("mcp", "db"): Artifact("mcp", "db", "mcp/db.json"),
        }
        self.catalog = Catalog(artifacts=artifacts, bundles={})
        key = UpstreamKey("skill", "one")
        self.upstreams = UpstreamCatalog(
            version=1,
            entries={
                key: UpstreamEntry(
                    key=key,
                    source=UpstreamSource("github", "acme/catalog", "main", "skills/one"),
                )
            },
        )

    def test_counts_types_and_partitions_tracked_artifacts(self):
        context = MaintainerContext("/catalog", self.catalog, self.upstreams)

        health = build_catalog_health(context)

        self.assertEqual(
            health.counts_by_type,
            (("skill", 2), ("guideline", 0), ("mcp", 1), ("hook", 0), ("memory", 0)),
        )
        self.assertEqual(health.tracked, ("skill/one",))
        self.assertEqual(health.untracked, ("mcp/db", "skill/two"))
        self.assertEqual(health.needs_attention, ())

    def test_surfaces_validation_and_non_current_upstreams(self):
        context = MaintainerContext(
            "/catalog",
            self.catalog,
            self.upstreams,
            validation_errors=("bundle broken",),
        )
        statuses = (UpstreamStatus(UpstreamKey("skill", "one"), "changed", message="new content"),)

        health = build_catalog_health(context, statuses)

        self.assertEqual(health.validation_errors, ("bundle broken",))
        self.assertEqual(health.needs_attention, (statuses[0],))


if __name__ == "__main__":
    unittest.main()
