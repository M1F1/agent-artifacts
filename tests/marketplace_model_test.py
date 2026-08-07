from __future__ import annotations

import unittest
from dataclasses import replace

from agent_artifacts.configuration.model import CompanyReviewedSource, SourceKind
from agent_artifacts.domain.identifiers import ArtifactIdentity, ObjectDigest, SourceAlias, SourceId
from agent_artifacts.domain.result import Ok
from agent_artifacts.marketplace.catalog import build_marketplace
from agent_artifacts.marketplace.model import (
    ArtifactQuery,
    MarketplaceCatalog,
    MarketplaceItem,
    MarketplaceQuery,
    MarketplaceSourceState,
    MarketplaceSourceView,
    TrustClass,
    TrustDecision,
)
from agent_artifacts.sources.model import HealthStatus, SourceHealth
from tests.marketplace_fixtures import (
    artifact,
    configured_source,
    effective_configuration,
    graph,
    source_state,
)


class MarketplaceModelTest(unittest.TestCase):
    def test_source_state_rejects_disabled_mismatched_and_inconsistent_health(self) -> None:
        source = configured_source("direct", SourceKind.SOURCE_GIT)
        valid = source_state(source, "direct-id", display_order=0)
        disabled = replace(source, enabled=False)
        different = configured_source("other", SourceKind.SOURCE_GIT)
        invalid = (
            lambda: MarketplaceSourceState(disabled, valid.health, 0),
            lambda: MarketplaceSourceState(different, valid.health, 0),
            lambda: MarketplaceSourceState(source, valid.health, -1),
            lambda: MarketplaceSourceState(
                source,
                SourceHealth(HealthStatus.HEALTHY, None, None),
                0,
            ),
            lambda: MarketplaceSourceState(
                source,
                SourceHealth(HealthStatus.MISSING, valid.health.age_seconds, valid.health.current),
                0,
            ),
        )
        for constructor in invalid:
            with self.subTest(constructor=constructor), self.assertRaises(ValueError):
                constructor()

    def test_views_trust_catalog_and_queries_enforce_nominal_invariants(self) -> None:
        digest = ObjectDigest("sha256", "a" * 64)
        valid_view = MarketplaceSourceView(
            SourceAlias("source"),
            SourceKind.SOURCE_GIT,
            SourceId("source-id"),
            "example.test/team/repo",
            "b" * 40,
            digest,
            HealthStatus.HEALTHY,
            1,
            0,
            False,
        )
        valid_trust = TrustDecision(TrustClass.DIRECT_SOURCE, digest, ("direct", "direct"))
        self.assertEqual(valid_trust.reasons, ("direct",))
        self.assertEqual(MarketplaceCatalog((valid_view,), ()).sources, (valid_view,))
        degraded_without_current = MarketplaceSourceView(
            SourceAlias("degraded"),
            SourceKind.SOURCE_GIT,
            None,
            "example.test/team/degraded",
            None,
            None,
            HealthStatus.DEGRADED,
            None,
            1,
            False,
        )
        self.assertIs(degraded_without_current.health, HealthStatus.DEGRADED)

        invalid = (
            lambda: MarketplaceSourceView(
                SourceAlias("source"),
                SourceKind.SOURCE_GIT,
                SourceId("source-id"),
                "origin",
                None,
                digest,
                HealthStatus.HEALTHY,
                1,
                0,
                False,
            ),
            lambda: MarketplaceSourceView(
                SourceAlias("source"),
                SourceKind.SOURCE_GIT,
                None,
                "origin",
                None,
                None,
                HealthStatus.HEALTHY,
                None,
                0,
                False,
            ),
            lambda: MarketplaceSourceView(
                SourceAlias("source"),
                SourceKind.SOURCE_GIT,
                SourceId("source-id"),
                "origin",
                "b" * 40,
                digest,
                HealthStatus.MISSING,
                1,
                0,
                False,
            ),
            lambda: MarketplaceSourceView(
                SourceAlias("source"),
                SourceKind.SOURCE_GIT,
                SourceId("source-id"),
                "origin",
                "b" * 40,
                digest,
                HealthStatus.HEALTHY,
                True,  # type: ignore[arg-type]
                0,
                False,
            ),
            lambda: TrustDecision(
                TrustClass.DIRECT_SOURCE,
                ObjectDigest("sha256", "bad"),
                ("direct",),
            ),
            lambda: TrustDecision(TrustClass.DIRECT_SOURCE, digest, ()),
            lambda: MarketplaceCatalog((valid_view, valid_view), ()),
            lambda: ArtifactQuery(ArtifactIdentity("collection", "bundle")),
            lambda: ArtifactQuery(
                ArtifactIdentity("skill", "item"),
                source=SourceAlias(""),
            ),
            lambda: ArtifactQuery(ArtifactIdentity("skill", "item"), version="latest"),
            lambda: MarketplaceQuery(kinds=("collection",)),
            lambda: MarketplaceQuery(text="x" * 513),
        )
        for constructor in invalid:
            with self.subTest(constructor=constructor), self.assertRaises(ValueError):
                constructor()

        source = configured_source("direct", SourceKind.SOURCE_GIT)
        state = source_state(source, "direct-id", display_order=0)
        other_view = replace(
            valid_view,
            alias=SourceAlias("other"),
        )
        catalog = build_marketplace(
            graph((source, "direct-id", (artifact("direct-id", "item"),))),
            effective_configuration((source,)),
            (state,),
        )
        assert isinstance(catalog, Ok)
        item = catalog.value.items[0]
        with self.assertRaises(ValueError):
            MarketplaceItem(item.artifact, other_view, item.trust)

    def test_company_reviewed_identity_is_canonical_and_rejects_broad_or_invalid_values(
        self,
    ) -> None:
        canonical = CompanyReviewedSource(
            SourceId("company-registry"),
            "Git.Company.Example",
            "agents/registry.git",
        )
        self.assertEqual(canonical.git_host, "git.company.example")
        self.assertEqual(canonical.repository, "agents/registry")
        for constructor in (
            lambda: CompanyReviewedSource(SourceId("Bad_ID"), "example.test", "team/repo"),
            lambda: CompanyReviewedSource(SourceId("id"), "https://example.test", "team/repo"),
            lambda: CompanyReviewedSource(SourceId("id"), "example.test", "/team/repo"),
            lambda: CompanyReviewedSource(SourceId("id"), "example.test", "../repo"),
            lambda: CompanyReviewedSource(SourceId("id"), "example.test", "team/repo?ref=main"),
            lambda: CompanyReviewedSource(SourceId("id"), 1, "team/repo"),  # type: ignore[arg-type]
            lambda: CompanyReviewedSource(SourceId("id"), "example.test", 1),  # type: ignore[arg-type]
        ):
            with self.subTest(constructor=constructor), self.assertRaises(ValueError):
                constructor()


if __name__ == "__main__":
    unittest.main()
