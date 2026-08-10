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
from agent_artifacts.tui_marketplace import (
    MarketplaceFilters,
    MarketplaceTarget,
    filter_marketplace_rows,
    project_marketplace_rows,
    reconcile_marketplace_basket,
    render_marketplace_row,
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


class TuiMarketplaceTest(unittest.TestCase):
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
        self.assertIn("company/skill/review@1.0.0", render_marketplace_row(review_rows[0]))
        self.assertIn("risk low", render_marketplace_row(review_rows[0]))
        self.assertIn("max unknown", render_marketplace_row(review_rows[0]))

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


if __name__ == "__main__":
    unittest.main()
