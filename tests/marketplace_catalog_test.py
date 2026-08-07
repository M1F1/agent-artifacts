from __future__ import annotations

import unittest
from unittest.mock import patch

from agent_artifacts.configuration.model import SourceKind
from agent_artifacts.domain.identifiers import ArtifactIdentity, SourceAlias
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.marketplace.catalog import build_marketplace, resolve_artifact
from agent_artifacts.marketplace.model import ArtifactQuery
from agent_artifacts.protocol.registry_models import ReviewRecord
from tests.marketplace_fixtures import (
    artifact,
    configured_source,
    effective_configuration,
    graph,
    source_state,
)


class MarketplaceCatalogTest(unittest.TestCase):
    def test_zero_sources_builds_an_empty_valid_catalog(self) -> None:
        result = build_marketplace(graph(), effective_configuration(()), ())

        self.assertIsInstance(result, Ok)
        assert isinstance(result, Ok)
        self.assertEqual(result.value.sources, ())
        self.assertEqual(result.value.items, ())

    def test_default_registry_changes_ranking_but_never_shadows_an_identity_collision(self) -> None:
        direct = configured_source("direct", SourceKind.SOURCE_GIT)
        company = configured_source("company", SourceKind.REGISTRY_GIT)
        direct_artifact = artifact("direct-source", "review")
        company_artifact = artifact(
            "company-registry",
            "review",
            review=ReviewRecord("approved", "registry-v1"),
        )
        catalog = build_marketplace(
            graph(
                (direct, "direct-source", (direct_artifact,)),
                (company, "company-registry", (company_artifact,)),
            ),
            effective_configuration((direct, company), default_registry="company"),
            (
                source_state(direct, "direct-source", display_order=0),
                source_state(company, "company-registry", display_order=1),
            ),
        )

        self.assertIsInstance(catalog, Ok)
        assert isinstance(catalog, Ok)
        self.assertEqual(
            tuple(item.coordinate.source.value for item in catalog.value.items),
            ("company", "direct"),
        )
        ambiguous = resolve_artifact(
            catalog.value,
            ArtifactQuery(ArtifactIdentity("skill", "review")),
        )
        self.assertIsInstance(ambiguous, Err)
        assert isinstance(ambiguous, Err)
        self.assertEqual(ambiguous.diagnostics[0].code.value, "artifact-ambiguous")
        self.assertEqual(
            dict(ambiguous.diagnostics[0].details)["coordinates"],
            "company/skill/review@1.0.0,direct/skill/review@1.0.0",
        )

    def test_qualified_and_unique_unqualified_resolution_are_exact(self) -> None:
        first = configured_source("first", SourceKind.SOURCE_GIT)
        second = configured_source("second", SourceKind.SOURCE_GIT)
        catalog = build_marketplace(
            graph(
                (first, "first-source", (artifact("first-source", "shared"),)),
                (
                    second,
                    "second-source",
                    (
                        artifact("second-source", "shared"),
                        artifact("second-source", "unique"),
                    ),
                ),
            ),
            effective_configuration((first, second)),
            (
                source_state(first, "first-source", display_order=0),
                source_state(second, "second-source", display_order=1),
            ),
        )
        assert isinstance(catalog, Ok)

        qualified = resolve_artifact(
            catalog.value,
            ArtifactQuery(
                ArtifactIdentity("skill", "shared"),
                source=SourceAlias("second"),
            ),
        )
        unique = resolve_artifact(
            catalog.value,
            ArtifactQuery(ArtifactIdentity("skill", "unique")),
        )
        missing = resolve_artifact(
            catalog.value,
            ArtifactQuery(ArtifactIdentity("skill", "missing")),
        )

        self.assertIsInstance(qualified, Ok)
        self.assertIsInstance(unique, Ok)
        assert isinstance(qualified, Ok)
        self.assertEqual(qualified.value.coordinate.source, SourceAlias("second"))
        self.assertIsInstance(missing, Err)
        assert isinstance(missing, Err)
        self.assertEqual(missing.diagnostics[0].code.value, "artifact-not-found")

    def test_graph_source_identity_must_match_current_source_identity(self) -> None:
        source = configured_source("direct", SourceKind.SOURCE_GIT)
        result = build_marketplace(
            graph((source, "graph-id", (artifact("graph-id", "item"),))),
            effective_configuration((source,)),
            (source_state(source, "current-id", display_order=0),),
        )

        self.assertIsInstance(result, Err)
        assert isinstance(result, Err)
        self.assertEqual(result.diagnostics[0].code.value, "marketplace-invalid")

    def test_duplicate_missing_unconfigured_and_graph_only_source_states_fail_closed(self) -> None:
        source = configured_source("direct", SourceKind.SOURCE_GIT)
        state = source_state(source, "direct-id", display_order=0)
        compiled = graph((source, "direct-id", (artifact("direct-id", "item"),)))
        cases = (
            build_marketplace(
                compiled,
                effective_configuration((source,)),
                (state, state),
            ),
            build_marketplace(compiled, effective_configuration((source,)), ()),
            build_marketplace(graph(), effective_configuration(()), (state,)),
            build_marketplace(compiled, effective_configuration(()), ()),
        )
        for result in cases:
            with self.subTest(result=result):
                self.assertIsInstance(result, Err)
                assert isinstance(result, Err)
                self.assertTrue(
                    all(item.code.value == "marketplace-invalid" for item in result.diagnostics)
                )

    def test_source_and_item_hard_bounds_fail_before_projection(self) -> None:
        source = configured_source("direct", SourceKind.SOURCE_GIT)
        state = source_state(source, "direct-id", display_order=0)
        compiled = graph((source, "direct-id", (artifact("direct-id", "item"),)))
        with patch("agent_artifacts.marketplace.catalog._MAX_SOURCES", 0):
            source_bound = build_marketplace(
                compiled,
                effective_configuration((source,)),
                (state,),
            )
        with patch("agent_artifacts.marketplace.catalog._MAX_ITEMS", 0):
            item_bound = build_marketplace(
                compiled,
                effective_configuration((source,)),
                (state,),
            )

        self.assertIsInstance(source_bound, Err)
        self.assertIsInstance(item_bound, Err)


if __name__ == "__main__":
    unittest.main()
