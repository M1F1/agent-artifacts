from __future__ import annotations

import unittest
from dataclasses import replace

from agent_artifacts.configuration.model import SourceKind
from agent_artifacts.domain.identifiers import ArtifactCoordinate, ArtifactIdentity
from agent_artifacts.domain.result import Ok
from agent_artifacts.lifecycle import (
    LifecycleItem,
    LifecycleKey,
    LifecycleStatus,
)
from agent_artifacts.marketplace.catalog import build_marketplace
from agent_artifacts.protocol.native_models import InstallSpec
from agent_artifacts.protocol.registry_models import ReviewRecord
from agent_artifacts.protocol.semver import SemVer, VersionBounds
from agent_artifacts.security.aggregation import ArtifactSecurityEvidence
from agent_artifacts.security.attestations import AttestationTrust
from agent_artifacts.security.model import (
    AssessmentCoverage,
    AssessmentStatus,
    FindingSeverity,
    ProviderAssessment,
    SecurityAssessment,
    risk_from_evidence,
)
from agent_artifacts.tui_layout import CONTENT_MEASURE, READABLE_MEASURE, columns
from agent_artifacts.tui_marketplace import (
    MarketplaceFilters,
    MarketplaceTarget,
    artifact_cells,
    filter_marketplace_rows,
    project_marketplace_rows,
    reconcile_marketplace_basket,
    render_artifact_detail,
    render_artifact_pane,
)
from tests.marketplace_fixtures import (
    artifact,
    configured_source,
    effective_configuration,
    graph,
    source_state,
)


def _catalog():
    company = configured_source("company", SourceKind.REGISTRY_GIT)
    team = configured_source("team", SourceKind.SOURCE_GIT)
    company_artifact = artifact(
        "company-registry",
        "review",
        review=ReviewRecord("approved", "registry-v1"),
    )
    team_artifact = artifact("team-source", "review")
    database = artifact("team-source", "database", kind="mcp")
    result = build_marketplace(
        graph(
            (company, "company-registry", (company_artifact,)),
            (team, "team-source", (team_artifact, database)),
        ),
        effective_configuration((company, team), default_registry="company"),
        (
            source_state(company, "company-registry", display_order=1),
            source_state(team, "team-source", display_order=0),
        ),
    )
    assert isinstance(result, Ok)
    return result.value


def _security(item) -> ArtifactSecurityEvidence:
    coverage = AssessmentCoverage(1, 1)
    provider = ProviderAssessment(
        "aart-baseline",
        "1",
        item.artifact.artifact.object_digest,
        AssessmentStatus.COMPLETE,
        coverage,
        "The deterministic baseline completed.",
    )
    assessment = SecurityAssessment(
        1,
        item.artifact.artifact.object_digest,
        AssessmentStatus.COMPLETE,
        risk_from_evidence(AssessmentStatus.COMPLETE, FindingSeverity.UNKNOWN),
        FindingSeverity.UNKNOWN,
        coverage,
        (),
        (provider,),
    )
    return ArtifactSecurityEvidence(
        item.coordinate,
        assessment,
        AttestationTrust.REGISTRY_REVIEWED,
        30,
    )


def _flat(lines: tuple[str, ...]) -> str:
    """Undo wrapping so an assertion can name a phrase without knowing where it broke."""

    return " ".join(" ".join(lines).split())


class TuiMarketplaceTest(unittest.TestCase):
    def test_newer_aart_requirement_stays_visible_but_cannot_enter_the_basket(self) -> None:
        source = configured_source("team", SourceKind.SOURCE_GIT)
        future = artifact(
            "team-source",
            "future",
            requires_aart=VersionBounds(min_inclusive=SemVer(2, 0, 0)),
        )
        result = build_marketplace(
            graph((source, "team-source", (future,))),
            effective_configuration((source,)),
            (source_state(source, "team-source", display_order=0),),
        )
        assert isinstance(result, Ok), result

        rows = project_marketplace_rows(
            result.value,
            MarketplaceTarget(("claude",), "darwin", "project", "copy"),
        )

        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0].compatible)
        # Replaces the assertion that render_marketplace_row said "unavailable": the row now
        # carries that verdict in its last cell, and the pane says why.
        self.assertEqual(artifact_cells(rows[0])[1], "unavailable")
        pane = _flat(render_artifact_pane(rows[0], width=100))
        self.assertIn("unavailable", pane)
        self.assertIn("requires AART >=2.0.0", pane)
        self.assertEqual(rows[0].reasons[0].code, "aart-version-unsupported")
        self.assertIn("requires AART >=2.0.0", rows[0].reasons[0].message)
        self.assertEqual(reconcile_marketplace_basket((rows[0].key,), rows).retained, ())

    def test_collision_rows_stay_qualified_and_expose_value_trust_health_and_security(self) -> None:
        catalog = _catalog()
        evidence = (_security(catalog.items[0]),)

        rows = project_marketplace_rows(
            catalog,
            MarketplaceTarget(("claude",), "darwin", "project", "copy"),
            security=evidence,
        )

        review_rows = tuple(
            row for row in rows if row.identity == ArtifactIdentity("skill", "review")
        )
        self.assertEqual(
            tuple(row.key for row in review_rows),
            ("company/skill/review@1.0.0", "team/skill/review@1.0.0"),
        )
        self.assertEqual(review_rows[0].summary, "Use review to improve agent work.")
        self.assertEqual(review_rows[0].trust, "registry-reviewed")
        self.assertEqual(review_rows[0].source_health, "healthy")
        self.assertEqual(review_rows[0].security.installation_risk, "low")
        self.assertEqual(review_rows[1].security.installation_risk, "unknown")
        # Replaces the three assertions that render_marketplace_row carried the key, the risk and
        # the maximum severity: the key and risk are now cells, the severity is pane evidence.
        cells = artifact_cells(review_rows[0])
        self.assertEqual(cells[0], "company/skill/review@1.0.0")
        self.assertIn("risk low", cells)
        pane = _flat(render_artifact_pane(review_rows[0], width=100))
        self.assertIn("max severity unknown", pane)

    def test_compatibility_is_evaluated_for_every_harness_scope_and_mode(self) -> None:
        catalog = _catalog()
        rows = project_marketplace_rows(
            catalog,
            MarketplaceTarget(("claude", "tabnine"), "darwin", "user", "symlink"),
        )

        database = next(row for row in rows if row.identity == ArtifactIdentity("mcp", "database"))

        self.assertFalse(database.compatible)
        self.assertEqual(
            tuple(item.profile for item in database.compatibility), ("claude", "tabnine")
        )
        self.assertTrue(any(reason.code == "mode-unsupported" for reason in database.reasons))
        self.assertEqual(database.actual_modes, ())

    def test_filters_cover_text_kind_source_trust_compatibility_and_installed_state(self) -> None:
        catalog = _catalog()
        team_review = next(
            item for item in catalog.items if str(item.coordinate).startswith("team/skill")
        )
        installed = LifecycleItem(
            LifecycleKey(
                ArtifactCoordinate(team_review.coordinate.source, team_review.coordinate.artifact),
                "claude",
                "project",
            ),
            LifecycleStatus.CURRENT,
        )
        rows = project_marketplace_rows(
            catalog,
            MarketplaceTarget(("claude",), "darwin", "project", "copy"),
            lifecycle=(installed,),
        )

        filtered = filter_marketplace_rows(
            rows,
            MarketplaceFilters(
                text="review",
                kinds=("skill",),
                sources=(team_review.source.alias,),
                trusts=("direct-source",),
                compatible_only=True,
                installed_only=True,
            ),
        )

        self.assertEqual(tuple(row.key for row in filtered), ("team/skill/review@1.0.0",))
        self.assertEqual(filtered[0].installed_statuses, ("claude:current",))
        self.assertEqual(
            tuple(
                row.identity.kind
                for row in filter_marketplace_rows(rows, MarketplaceFilters(kinds=("mcp",)))
            ),
            ("mcp",),
        )
        self.assertTrue(
            all(
                row.source_alias.value == "company"
                for row in filter_marketplace_rows(
                    rows,
                    MarketplaceFilters(sources=(catalog.sources[0].alias,)),
                )
            )
        )
        self.assertTrue(
            all(
                row.trust == "direct-source"
                for row in filter_marketplace_rows(
                    rows,
                    MarketplaceFilters(trusts=("direct-source",)),
                )
            )
        )
        self.assertEqual(
            len(filter_marketplace_rows(rows, MarketplaceFilters(installed_only=True))),
            1,
        )

    def test_duplicate_lifecycle_observations_collapse_without_losing_distinct_statuses(
        self,
    ) -> None:
        catalog = _catalog()
        item = next(
            candidate
            for candidate in catalog.items
            if candidate.coordinate.artifact == ArtifactIdentity("mcp", "database")
        )
        key = LifecycleKey(
            ArtifactCoordinate(item.coordinate.source, item.coordinate.artifact),
            "claude",
            "project",
        )
        current = LifecycleItem(key, LifecycleStatus.CURRENT)
        update_available = LifecycleItem(key, LifecycleStatus.UPDATE_AVAILABLE)

        rows = project_marketplace_rows(
            catalog,
            MarketplaceTarget(("claude",), "darwin", "project", "copy"),
            lifecycle=(current, current, update_available),
        )

        database = next(row for row in rows if row.identity == ArtifactIdentity("mcp", "database"))
        self.assertEqual(
            database.installed_statuses,
            ("claude:current", "claude:update-available"),
        )

    def test_symlink_projection_reports_mixed_actual_modes(self) -> None:
        source = configured_source("team", SourceKind.SOURCE_GIT)
        mixed = replace(
            artifact("team-source", "mixed"),
            install=InstallSpec(
                ("project",),
                ("copy", "symlink"),
                ("copy-tree", "merge-json"),
            ),
        )
        result = build_marketplace(
            graph((source, "team-source", (mixed,))),
            effective_configuration((source,)),
            (source_state(source, "team-source", display_order=0),),
        )
        assert isinstance(result, Ok), result

        rows = project_marketplace_rows(
            result.value,
            MarketplaceTarget(("claude",), "darwin", "project", "symlink"),
        )

        self.assertTrue(rows[0].compatible)
        self.assertEqual(rows[0].actual_modes, ("copy", "symlink"))

    def test_basket_keeps_qualified_values_and_invalidates_only_unavailable_entries(self) -> None:
        rows = project_marketplace_rows(
            _catalog(),
            MarketplaceTarget(("claude",), "darwin", "project", "copy"),
        )
        basket = tuple(row.key for row in rows if row.identity.name == "review")

        reconciled = reconcile_marketplace_basket(
            basket,
            tuple(row for row in rows if row.source_alias.value == "team"),
        )

        self.assertEqual(reconciled.retained, ("team/skill/review@1.0.0",))
        self.assertEqual(reconciled.invalidated, ("company/skill/review@1.0.0",))

    def test_target_rejects_an_empty_harness_selection(self) -> None:
        with self.assertRaises(ValueError):
            MarketplaceTarget((), "darwin", "project", "copy")


class ArtifactProjectionTest(unittest.TestCase):
    """WP-2 of DESIGN-tui-legibility: one line per row, evidence in the pane and the record."""

    def rows(self) -> tuple:
        catalog = _catalog()
        installed = LifecycleItem(
            LifecycleKey(
                ArtifactCoordinate(
                    catalog.items[0].coordinate.source,
                    catalog.items[0].coordinate.artifact,
                ),
                "claude",
                "project",
            ),
            LifecycleStatus.CURRENT,
        )
        return project_marketplace_rows(
            catalog,
            MarketplaceTarget(("claude",), "darwin", "project", "copy"),
            security=(_security(catalog.items[0]),),
            lifecycle=(installed,),
        )

    def test_cells_lead_with_the_key_and_carry_only_the_deciding_fields(self) -> None:
        rows = self.rows()
        reviewed = next(row for row in rows if row.key.startswith("company/"))
        other = next(row for row in rows if row.identity.kind == "mcp")

        self.assertEqual(
            artifact_cells(reviewed),
            ("company/skill/review@1.0.0", "claude:current", "risk low", "registry-reviewed"),
        )
        self.assertEqual(artifact_cells(other)[1], "available")
        self.assertTrue(all(len(cells) == 4 for cells in map(artifact_cells, rows)))

    def test_cells_are_ordered_so_a_narrow_caller_can_drop_a_suffix(self) -> None:
        # Resolves the question WP-0 carried forward: below roughly fifty columns the kernel
        # shrinks a trailing cell to a meaningless stump, so the caller drops whole columns
        # instead. That only works if the cells are ordered by importance.
        rows = self.rows()
        full = [artifact_cells(row) for row in rows]

        narrow = columns([cells[:2] for cells in full], width=44)

        self.assertTrue(
            all(line.startswith(row.key) for line, row in zip(narrow, rows, strict=True))
        )
        self.assertTrue(all("…" not in line for line in narrow))
        self.assertTrue(all(len(line) <= 44 for line in narrow))

    def test_a_four_hundred_character_summary_never_costs_the_key_at_width_forty(self) -> None:
        rows = self.rows()
        bloated = replace(rows[0], summary="s" * 400)

        laid_out = columns([artifact_cells(row) for row in (bloated, *rows[1:])], width=40)

        self.assertTrue(laid_out[0].startswith(bloated.key))
        self.assertTrue(all(len(line) <= 40 for line in laid_out))
        self.assertEqual(len(laid_out), len(rows))

    def test_the_pane_leads_with_identity_then_wraps_the_summary_over_a_field_block(self) -> None:
        row = next(item for item in self.rows() if item.key.startswith("company/"))

        pane = render_artifact_pane(row, width=200)

        self.assertEqual(pane[0].strip(), row.key)
        self.assertIn(row.summary, _flat(pane))
        labels = [line.split()[0] for line in pane if line.startswith("    ")]
        self.assertEqual(labels[:4], ["source", "risk", "harness", "status"])
        self.assertIn("healthy", _flat(pane))
        self.assertIn("compatible", _flat(pane))

    def test_a_long_summary_is_wrapped_in_the_pane_rather_than_displacing_the_key(self) -> None:
        row = replace(self.rows()[0], summary="word " * 200)

        pane = render_artifact_pane(row, width=40)

        self.assertEqual(pane[0].strip(), row.key)
        self.assertTrue(all(len(line) <= 40 for line in pane))
        self.assertGreater(len(pane), 5)

    def test_the_pane_abbreviates_the_revision_the_record_keeps_whole(self) -> None:
        row = self.rows()[0]

        pane = _flat(render_artifact_pane(row, width=62))
        detail = _flat(render_artifact_detail(row))

        self.assertIn(f"at {row.source_revision[:7]}…", pane)
        self.assertNotIn(row.source_revision, pane)
        self.assertIn(row.source_revision, detail)
        self.assertLessEqual(len(render_artifact_pane(row, width=62)), 6)

    def test_no_structured_pane_line_outgrows_the_content_measure(self) -> None:
        rows = self.rows()
        for width in (40, 80, 120, 200):
            for row in rows:
                for line in render_artifact_pane(row, width=width):
                    self.assertLessEqual(len(line), min(width, CONTENT_MEASURE))

    def test_the_detail_record_carries_every_evidence_field(self) -> None:
        row = next(item for item in self.rows() if item.key.startswith("company/"))

        detail = _flat(render_artifact_detail(row))

        for expected in (
            row.key,
            row.summary,
            row.source_origin,
            row.source_revision,
            "healthy",
            "registry-reviewed",
            "low",
            "severity unknown",
            "complete",
            "1/1",
            "aart-baseline@1",
            "claude:current",
            "copy",
        ):
            self.assertIn(expected, detail)

    def test_every_digest_keeps_its_own_unwrapped_line(self) -> None:
        row = next(item for item in self.rows() if item.key.startswith("company/"))

        detail = render_artifact_detail(row)

        for digest in (row.manifest_digest, row.payload_digest, row.object_digest):
            carriers = [line for line in detail if digest in line]
            self.assertEqual(len(carriers), 1, digest)
            self.assertLessEqual(len(carriers[0]), len(digest) + 16)

    def test_prose_in_the_detail_record_stays_within_the_readable_measure(self) -> None:
        row = replace(self.rows()[0], summary="word " * 200)

        detail = render_artifact_detail(row)
        prose = [line for line in detail if line.startswith("word")]

        self.assertTrue(prose)
        self.assertTrue(all(len(line) <= READABLE_MEASURE for line in prose))

    def test_the_flattened_row_renderer_is_gone(self) -> None:
        # WP-3 step 9: the last caller (_canonical_choice) moved to these projections, so the
        # one-line dump that started observation 7 no longer exists to be reached for.
        import agent_artifacts.tui_marketplace as module

        self.assertFalse(hasattr(module, "render_marketplace_row"))
        self.assertNotIn("render_marketplace_row", module.__all__)

    def test_no_projection_uses_the_dot_as_a_separator(self) -> None:
        rows = self.rows()
        emitted = [
            *(cell for row in rows for cell in artifact_cells(row)),
            *(line for row in rows for line in render_artifact_pane(row, width=100)),
            *(line for row in rows for line in render_artifact_detail(row)),
        ]

        self.assertTrue(emitted)
        for line in emitted:
            self.assertNotIn("·", line)


if __name__ == "__main__":
    unittest.main()
