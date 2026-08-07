from __future__ import annotations

import unittest

from agent_artifacts.configuration.model import CompanyReviewedSource, SourceKind
from agent_artifacts.domain.identifiers import SourceId
from agent_artifacts.domain.result import Ok
from agent_artifacts.marketplace.catalog import build_marketplace
from agent_artifacts.marketplace.model import TrustClass
from agent_artifacts.protocol.registry_models import ReviewRecord
from tests.marketplace_fixtures import (
    artifact,
    configured_source,
    effective_configuration,
    graph,
    source_state,
)


class MarketplaceTrustTest(unittest.TestCase):
    def test_trust_is_derived_from_kind_review_and_exact_company_policy_identity(self) -> None:
        local = configured_source("local", SourceKind.SOURCE_LOCAL)
        direct = configured_source("direct", SourceKind.SOURCE_GIT)
        registry = configured_source("registry", SourceKind.REGISTRY_GIT)
        company = configured_source(
            "company",
            SourceKind.REGISTRY_GIT,
            location="https://Git.Company.Example/agents/company-registry.git",
        )
        pending = configured_source("pending", SourceKind.REGISTRY_GIT)
        approved = ReviewRecord("approved", "registry-v1")
        catalog = build_marketplace(
            graph(
                (local, "local-source", (artifact("local-source", "local"),)),
                (
                    direct,
                    "direct-source",
                    (artifact("direct-source", "direct", review=approved),),
                ),
                (
                    registry,
                    "public-registry",
                    (artifact("public-registry", "registry", review=approved),),
                ),
                (
                    company,
                    "company-registry",
                    (artifact("company-registry", "company", review=approved),),
                ),
                (
                    pending,
                    "pending-registry",
                    (
                        artifact(
                            "pending-registry",
                            "pending",
                            review=ReviewRecord("pending", "registry-v1"),
                        ),
                    ),
                ),
            ),
            effective_configuration(
                (local, direct, registry, company, pending),
                company_sources=(
                    CompanyReviewedSource(
                        SourceId("company-registry"),
                        "git.company.example",
                        "agents/company-registry",
                    ),
                ),
            ),
            tuple(
                source_state(source, source_id, display_order=index)
                for index, (source, source_id) in enumerate(
                    (
                        (local, "local-source"),
                        (direct, "direct-source"),
                        (registry, "public-registry"),
                        (company, "company-registry"),
                        (pending, "pending-registry"),
                    )
                )
            ),
        )

        self.assertIsInstance(catalog, Ok)
        assert isinstance(catalog, Ok)
        trust = {
            item.artifact.artifact.identity.name: item.trust.kind for item in catalog.value.items
        }
        self.assertEqual(
            trust,
            {
                "local": TrustClass.LOCAL,
                "direct": TrustClass.DIRECT_SOURCE,
                "registry": TrustClass.REGISTRY_REVIEWED,
                "company": TrustClass.COMPANY_REVIEWED,
                "pending": TrustClass.UNVERIFIED,
            },
        )

    def test_alias_default_and_direct_source_review_cannot_escalate_trust(self) -> None:
        source = configured_source(
            "company",
            SourceKind.SOURCE_GIT,
            location="https://git.company.example/agents/company-registry.git",
        )
        catalog = build_marketplace(
            graph(
                (
                    source,
                    "company-registry",
                    (
                        artifact(
                            "company-registry",
                            "claimed",
                            review=ReviewRecord("approved", "self-claim"),
                        ),
                    ),
                )
            ),
            effective_configuration(
                (source,),
                company_sources=(
                    CompanyReviewedSource(
                        SourceId("company-registry"),
                        "git.company.example",
                        "agents/company-registry",
                    ),
                ),
            ),
            (source_state(source, "company-registry", display_order=0),),
        )

        assert isinstance(catalog, Ok)
        self.assertIs(catalog.value.items[0].trust.kind, TrustClass.DIRECT_SOURCE)

    def test_trust_evidence_changes_with_origin_commit_object_review_and_policy(self) -> None:
        source = configured_source(
            "registry",
            SourceKind.REGISTRY_GIT,
            location="https://registry.example/team/repo.git",
        )
        approved = ReviewRecord("approved", "review-v1")

        def evidence(
            *,
            configured=source,
            content: bytes = b"source",
            resolved_revision: str | None = None,
            object_character: str = "3",
            review: ReviewRecord = approved,
            company: bool = False,
        ):
            company_sources = (
                (CompanyReviewedSource(SourceId("registry-id"), "registry.example", "team/repo"),)
                if company
                else ()
            )
            result = build_marketplace(
                graph(
                    (
                        configured,
                        "registry-id",
                        (
                            artifact(
                                "registry-id",
                                "item",
                                object_character=object_character,
                                review=review,
                            ),
                        ),
                    )
                ),
                effective_configuration((configured,), company_sources=company_sources),
                (
                    source_state(
                        configured,
                        "registry-id",
                        display_order=0,
                        content=content,
                        resolved_revision=resolved_revision,
                    ),
                ),
            )
            assert isinstance(result, Ok), result
            return result.value.items[0].trust.evidence_digest

        baseline = evidence()
        changed_origin = evidence(
            configured=configured_source(
                "registry",
                SourceKind.REGISTRY_GIT,
                location="https://registry.example/team/other.git",
            )
        )
        changed_commit = evidence(resolved_revision="c" * 40)
        changed_snapshot = evidence(content=b"changed")
        changed_object = evidence(object_character="4")
        changed_review = evidence(review=ReviewRecord("approved", "review-v2"))
        changed_policy = evidence(company=True)

        self.assertEqual(
            len(
                {
                    baseline,
                    changed_origin,
                    changed_commit,
                    changed_snapshot,
                    changed_object,
                    changed_review,
                    changed_policy,
                }
            ),
            7,
        )


if __name__ == "__main__":
    unittest.main()
