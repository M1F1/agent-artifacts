"""Selector-to-coordinate resolution against a real compiled catalog (LIFE02).

The lifecycle commands must never guess which source an unqualified selector meant.  These tests
pin the deterministic ambiguity diagnostic and the exact resolved coordinates.
"""

from __future__ import annotations

import unittest
from dataclasses import replace

from agent_artifacts.compiler import CollectionCoordinate, MarketplaceCollection
from agent_artifacts.configuration.model import SourceKind
from agent_artifacts.consumer.coordinates import parse_artifact_selectors
from agent_artifacts.consumer.resolution import resolve_selectors
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.marketplace.catalog import build_marketplace
from agent_artifacts.protocol.native_models import ArtifactSelector, CollectionManifest
from tests.marketplace_fixtures import (
    artifact,
    configured_source,
    effective_configuration,
    graph,
    graph_with_collections,
    source_state,
)


def _catalog():
    team = configured_source("team", SourceKind.SOURCE_GIT)
    company = configured_source("company", SourceKind.REGISTRY_GIT)
    compiled = graph(
        (team, "team-source", (artifact("team-source", "code-review"),)),
        (
            company,
            "company-source",
            (artifact("company-source", "code-review"), artifact("company-source", "release")),
        ),
    )
    effective = effective_configuration((team, company), default_registry="company")
    built = build_marketplace(
        compiled,
        effective,
        (
            source_state(team, "team-source", display_order=0),
            source_state(company, "company-source", display_order=1),
        ),
    )
    assert isinstance(built, Ok), built
    return built.value


def _resolve(catalog, *raw: str):
    parsed = parse_artifact_selectors(raw)
    assert isinstance(parsed, Ok), parsed
    return resolve_selectors(catalog, parsed.value)


def _collection_catalog():
    company = configured_source("company", SourceKind.REGISTRY_GIT)
    review = artifact("company-source", "code-review")
    release = artifact("company-source", "release")
    compiled = graph_with_collections(
        company,
        "company-source",
        (review, release),
        (
            CollectionManifest(
                1,
                "starter",
                "Install the reviewed starter set.",
                (ArtifactSelector(review.identity), ArtifactSelector(release.identity)),
            ),
        ),
    )
    built = build_marketplace(
        compiled,
        effective_configuration((company,), default_registry="company"),
        (source_state(company, "company-source", display_order=0),),
    )
    assert isinstance(built, Ok), built
    return built.value


class SelectorResolutionTests(unittest.TestCase):
    def test_a_source_qualified_selector_resolves_to_that_exact_source(self) -> None:
        resolved = _resolve(_catalog(), "team/skill/code-review")

        self.assertIsInstance(resolved, Ok)
        assert isinstance(resolved, Ok)
        self.assertEqual(
            tuple(str(coordinate) for coordinate in resolved.value),
            ("team/skill/code-review@1.0.0",),
        )

    def test_an_unqualified_selector_with_one_match_resolves(self) -> None:
        resolved = _resolve(_catalog(), "skill/release")

        self.assertIsInstance(resolved, Ok)
        assert isinstance(resolved, Ok)
        self.assertEqual(
            tuple(str(coordinate) for coordinate in resolved.value),
            ("company/skill/release@1.0.0",),
        )

    def test_an_ambiguous_unqualified_selector_names_every_valid_coordinate(self) -> None:
        resolved = _resolve(_catalog(), "skill/code-review")

        self.assertIsInstance(resolved, Err)
        assert isinstance(resolved, Err)
        diagnostic = resolved.diagnostics[0]
        self.assertEqual(diagnostic.code.value, "artifact-ambiguous")
        self.assertIn("company/skill/code-review", diagnostic.message)
        self.assertIn("team/skill/code-review", diagnostic.message)

    def test_an_unknown_artifact_reports_not_found_rather_than_an_empty_selection(self) -> None:
        resolved = _resolve(_catalog(), "team/skill/absent")

        self.assertIsInstance(resolved, Err)
        assert isinstance(resolved, Err)
        self.assertEqual(resolved.diagnostics[0].code.value, "artifact-not-found")

    def test_every_unresolvable_selector_is_reported_together(self) -> None:
        resolved = _resolve(_catalog(), "team/skill/absent", "skill/code-review")

        self.assertIsInstance(resolved, Err)
        assert isinstance(resolved, Err)
        self.assertEqual(
            tuple(sorted(diagnostic.code.value for diagnostic in resolved.diagnostics)),
            ("artifact-ambiguous", "artifact-not-found"),
        )

    def test_resolved_coordinates_are_deduplicated_and_deterministically_ordered(self) -> None:
        resolved = _resolve(
            _catalog(),
            "company/skill/release",
            "skill/release",
            "team/skill/code-review",
        )

        self.assertIsInstance(resolved, Ok)
        assert isinstance(resolved, Ok)
        self.assertEqual(
            tuple(str(coordinate) for coordinate in resolved.value),
            ("company/skill/release@1.0.0", "team/skill/code-review@1.0.0"),
        )

    def test_an_empty_selection_resolves_to_no_coordinates(self) -> None:
        resolved = resolve_selectors(_catalog(), ())

        self.assertIsInstance(resolved, Ok)
        assert isinstance(resolved, Ok)
        self.assertEqual(resolved.value, ())

    def test_a_collection_selector_expands_to_its_pinned_artifact_coordinates(self) -> None:
        resolved = _resolve(_collection_catalog(), "company/collection/starter")

        self.assertIsInstance(resolved, Ok)
        assert isinstance(resolved, Ok)
        self.assertEqual(
            tuple(str(coordinate) for coordinate in resolved.value),
            (
                "company/skill/code-review@1.0.0",
                "company/skill/release@1.0.0",
            ),
        )

    def test_collection_members_are_deduplicated_against_explicit_artifacts(self) -> None:
        resolved = _resolve(
            _collection_catalog(),
            "company/collection/starter",
            "company/skill/code-review@1.0.0",
        )

        self.assertIsInstance(resolved, Ok)
        assert isinstance(resolved, Ok)
        self.assertEqual(
            tuple(str(coordinate) for coordinate in resolved.value),
            (
                "company/skill/code-review@1.0.0",
                "company/skill/release@1.0.0",
            ),
        )

    def test_an_unknown_collection_reports_a_specific_not_found_diagnostic(self) -> None:
        resolved = _resolve(_collection_catalog(), "company/collection/absent")

        self.assertIsInstance(resolved, Err)
        assert isinstance(resolved, Err)
        self.assertEqual(resolved.diagnostics[0].code.value, "collection-not-found")

    def test_an_unqualified_collection_never_guesses_between_sources(self) -> None:
        catalog = _catalog()
        team_member = next(
            item.coordinate for item in catalog.items if str(item.source.alias) == "team"
        )
        company_member = next(
            item.coordinate for item in catalog.items if str(item.source.alias) == "company"
        )
        catalog = replace(
            catalog,
            collections=(
                MarketplaceCollection(
                    CollectionCoordinate(team_member.source, "starter"),
                    "Team starter.",
                    (team_member,),
                ),
                MarketplaceCollection(
                    CollectionCoordinate(company_member.source, "starter"),
                    "Company starter.",
                    (company_member,),
                ),
            ),
        )

        resolved = _resolve(catalog, "collection/starter")

        self.assertIsInstance(resolved, Err)
        assert isinstance(resolved, Err)
        self.assertEqual(resolved.diagnostics[0].code.value, "collection-ambiguous")
        self.assertIn("company/collection/starter", resolved.diagnostics[0].message)
        self.assertIn("team/collection/starter", resolved.diagnostics[0].message)

    def test_direct_selection_expands_declared_dependencies_in_the_same_registry(self) -> None:
        company = configured_source("company", SourceKind.REGISTRY_GIT)
        kernel = artifact("company-source", "using-residues")
        stage = artifact(
            "company-source",
            "residual-stage",
            requires=(ArtifactSelector(kernel.identity),),
        )
        compiled = graph((company, "company-source", (kernel, stage)))
        built = build_marketplace(
            compiled,
            effective_configuration((company,), default_registry="company"),
            (source_state(company, "company-source", display_order=0),),
        )
        assert isinstance(built, Ok), built

        resolved = _resolve(built.value, "company/skill/residual-stage")

        self.assertIsInstance(resolved, Ok)
        assert isinstance(resolved, Ok)
        self.assertEqual(
            tuple(str(item) for item in resolved.value),
            (
                "company/skill/residual-stage@1.0.0",
                "company/skill/using-residues@1.0.0",
            ),
        )

    def test_missing_runtime_dependency_fails_before_installation_planning(self) -> None:
        company = configured_source("company", SourceKind.REGISTRY_GIT)
        stage = artifact(
            "company-source",
            "residual-stage",
            requires=(ArtifactSelector(artifact("company-source", "using-residues").identity),),
        )
        compiled = graph((company, "company-source", (stage,)))
        built = build_marketplace(
            compiled,
            effective_configuration((company,), default_registry="company"),
            (source_state(company, "company-source", display_order=0),),
        )
        assert isinstance(built, Ok), built

        resolved = _resolve(built.value, "company/skill/residual-stage")

        self.assertIsInstance(resolved, Err)
        assert isinstance(resolved, Err)
        self.assertEqual(resolved.diagnostics[0].code.value, "dependency-unavailable")


if __name__ == "__main__":  # pragma: no cover - unittest entry point
    unittest.main()
