from __future__ import annotations

import json
import unittest

from agent_artifacts.configuration.model import CompanyReviewedSource, SourceKind
from agent_artifacts.domain.identifiers import ArtifactIdentity, SourceAlias, SourceId
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.marketplace.catalog import (
    build_marketplace,
    marketplace_catalog_bytes,
    resolve_artifact,
)
from agent_artifacts.marketplace.model import ArtifactQuery, TrustClass
from agent_artifacts.protocol.registry_models import ReviewRecord
from tests.marketplace_fixtures import (
    artifact,
    configured_source,
    effective_configuration,
    graph,
    provenance,
    source_state,
)


class MarketplaceE2ETest(unittest.TestCase):
    def test_two_real_runtime_sources_preserve_collision_and_resolve_qualified_company_item(
        self,
    ) -> None:
        direct = configured_source(
            "team",
            SourceKind.SOURCE_GIT,
            location="https://git.example/team/native.git",
        )
        company = configured_source(
            "company",
            SourceKind.REGISTRY_GIT,
            location="git@git.company.example:agents/registry.git",
        )
        approved = ReviewRecord("approved", "company-v1")
        compiled = graph(
            (direct, "team-source", (artifact("team-source", "review"),)),
            (
                company,
                "company-registry",
                (
                    artifact(
                        "company-registry",
                        "review",
                        review=approved,
                        provenance=provenance("review"),
                    ),
                ),
            ),
        )
        catalog = build_marketplace(
            compiled,
            effective_configuration(
                (direct, company),
                default_registry="company",
                company_sources=(
                    CompanyReviewedSource(
                        SourceId("company-registry"),
                        "git.company.example",
                        "agents/registry",
                    ),
                ),
            ),
            (
                source_state(direct, "team-source", display_order=0),
                source_state(company, "company-registry", display_order=1),
            ),
        )
        assert isinstance(catalog, Ok), catalog

        ambiguous = resolve_artifact(
            catalog.value,
            ArtifactQuery(ArtifactIdentity("skill", "review")),
        )
        selected = resolve_artifact(
            catalog.value,
            ArtifactQuery(
                ArtifactIdentity("skill", "review"),
                source=SourceAlias("company"),
            ),
        )
        payload = json.loads(marketplace_catalog_bytes(catalog.value))

        self.assertIsInstance(ambiguous, Err)
        self.assertIsInstance(selected, Ok)
        assert isinstance(selected, Ok)
        self.assertIs(selected.value.trust.kind, TrustClass.COMPANY_REVIEWED)
        self.assertEqual(payload["artifacts"][0]["coordinate"], str(selected.value.coordinate))
        self.assertEqual(payload["artifacts"][0]["source"]["source_id"], "company-registry")


if __name__ == "__main__":
    unittest.main()
