"""Selector-to-coordinate resolution against a real compiled catalog (LIFE02).

The lifecycle commands must never guess which source an unqualified selector meant.  These tests
pin the deterministic ambiguity diagnostic and the exact resolved coordinates.
"""

from __future__ import annotations

import unittest

from agent_artifacts.configuration.model import SourceKind
from agent_artifacts.consumer.coordinates import parse_artifact_selectors
from agent_artifacts.consumer.resolution import resolve_selectors
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.marketplace.catalog import build_marketplace
from tests.marketplace_fixtures import (
    artifact,
    configured_source,
    effective_configuration,
    graph,
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


if __name__ == "__main__":  # pragma: no cover - unittest entry point
    unittest.main()
