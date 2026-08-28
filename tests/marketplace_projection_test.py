from __future__ import annotations

import json
import unittest
from dataclasses import replace

from agent_artifacts.configuration.model import SourceKind
from agent_artifacts.domain.identifiers import ArtifactIdentity
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.marketplace.catalog import (
    build_marketplace,
    list_marketplace,
    marketplace_catalog_bytes,
    render_marketplace,
    resolve_artifact,
    search_marketplace,
)
from agent_artifacts.marketplace.model import (
    ArtifactQuery,
    MarketplaceCatalog,
    MarketplaceQuery,
)
from agent_artifacts.protocol.native_models import ArtifactSelector, CollectionManifest
from agent_artifacts.protocol.paths import SafeRelativePath
from agent_artifacts.protocol.registry_models import IndexProvenance, ReviewRecord
from agent_artifacts.protocol.semver import SemVer, VersionBounds
from tests.credential_fixtures import credential_url
from tests.marketplace_fixtures import (
    artifact,
    configured_source,
    effective_configuration,
    graph,
    graph_with_collections,
    missing_source_state,
    provenance,
    source_state,
)


class MarketplaceProjectionTest(unittest.TestCase):
    def test_search_and_outputs_include_health_trust_provenance_and_all_digests(self) -> None:
        registry = configured_source("registry", SourceKind.REGISTRY_GIT)
        missing = configured_source("missing", SourceKind.SOURCE_GIT)
        indexed = artifact(
            "registry-id",
            "atlassian",
            review=ReviewRecord("approved", "registry-v1"),
            provenance=provenance("atlassian"),
            requires_aart=VersionBounds(min_inclusive=SemVer(1, 1, 0)),
        )
        catalog = build_marketplace(
            graph((registry, "registry-id", (indexed,))),
            effective_configuration((registry, missing), default_registry="registry"),
            (
                source_state(
                    registry,
                    "registry-id",
                    display_order=1,
                    published_at=0,
                    now=100,
                    max_age=10,
                ),
                missing_source_state(missing, display_order=0),
            ),
        )
        assert isinstance(catalog, Ok)

        found = search_marketplace(catalog.value, MarketplaceQuery(text="ATLASSIAN"))
        absent = search_marketplace(catalog.value, MarketplaceQuery(text="database"))
        encoded = marketplace_catalog_bytes(
            catalog.value,
            executable_version=SemVer(1, 0, 0),
        )
        payload = json.loads(encoded)
        rendered = render_marketplace(catalog.value, executable_version=SemVer(1, 0, 0))

        self.assertEqual(len(found), 1)
        self.assertEqual(absent, ())
        self.assertEqual(payload["sources"][0]["alias"], "registry")
        self.assertEqual(payload["sources"][0]["health"], "stale")
        self.assertEqual(payload["sources"][1]["health"], "missing")
        item = payload["artifacts"][0]
        self.assertEqual(item["coordinate"], "registry/skill/atlassian@1.0.0")
        self.assertEqual(item["trust"], "registry-reviewed")
        self.assertEqual(item["manifest_digest"], "sha256:" + "1" * 64)
        self.assertEqual(item["payload_digest"], "sha256:" + "2" * 64)
        self.assertEqual(item["object_digest"], "sha256:" + "3" * 64)
        self.assertEqual(item["provenance"]["resolved_commit"], "b" * 40)
        self.assertEqual(item["requires_aart"], {"min_inclusive": "1.1.0"})
        self.assertFalse(item["aart_compatible"])
        self.assertIn("installation is disabled", item["compatibility_notice"])
        self.assertIn("trust_evidence_digest", item)
        self.assertIn("registry/skill/atlassian@1.0.0", rendered)
        self.assertIn("registry-reviewed", rendered)
        self.assertIn("sha256:" + "3" * 64, rendered)
        self.assertIn("https://upstream.example/atlassian.git", rendered)
        self.assertIn("requires AART >=1.1.0, unavailable on 1.0.0", rendered)

    def test_filtering_by_kind_source_and_removed_policy_is_deterministic(self) -> None:
        source = configured_source("direct", SourceKind.SOURCE_GIT)
        catalog = build_marketplace(
            graph(
                (
                    source,
                    "direct-id",
                    (
                        artifact("direct-id", "skill"),
                        artifact("direct-id", "guide", kind="guideline"),
                    ),
                )
            ),
            effective_configuration((source,)),
            (source_state(source, "direct-id", display_order=0),),
        )
        assert isinstance(catalog, Ok)

        result = search_marketplace(
            catalog.value,
            MarketplaceQuery(kinds=("guideline",), sources=(source.alias,)),
        )

        self.assertEqual(tuple(item.artifact.artifact.identity.name for item in result), ("guide",))
        self.assertEqual(
            search_marketplace(
                catalog.value,
                MarketplaceQuery(
                    sources=(configured_source("other", SourceKind.SOURCE_GIT).alias,)
                ),
            ),
            (),
        )

    def test_removed_history_is_listable_only_when_requested_and_never_resolves(self) -> None:
        source = configured_source("direct", SourceKind.SOURCE_GIT)
        previous = graph((source, "direct-id", (artifact("direct-id", "removed"),)))
        historical = graph((source, "direct-id", ()), previous=previous)
        catalog = build_marketplace(
            historical,
            effective_configuration((source,)),
            (source_state(source, "direct-id", display_order=0),),
        )
        assert isinstance(catalog, Ok)

        self.assertEqual(search_marketplace(catalog.value), ())
        self.assertEqual(list_marketplace(catalog.value), ())
        self.assertEqual(
            len(list_marketplace(catalog.value, include_removed=True)),
            1,
        )
        resolved = resolve_artifact(
            catalog.value,
            ArtifactQuery(ArtifactIdentity("skill", "removed")),
        )
        self.assertIsInstance(resolved, Err)
        with self.assertRaises(ValueError):
            list_marketplace(catalog.value, include_removed=1)  # type: ignore[arg-type]

    def test_qualified_collections_survive_runtime_projection_and_rendering(self) -> None:
        source = configured_source("direct", SourceKind.SOURCE_GIT)
        indexed = artifact("direct-id", "member")
        compiled = graph_with_collections(
            source,
            "direct-id",
            (indexed,),
            (
                CollectionManifest(
                    1,
                    "starter",
                    "Start with one reviewed artifact.",
                    (ArtifactSelector(indexed.identity),),
                ),
            ),
        )
        catalog = build_marketplace(
            compiled,
            effective_configuration((source,)),
            (source_state(source, "direct-id", display_order=0),),
        )
        assert isinstance(catalog, Ok)

        payload = json.loads(marketplace_catalog_bytes(catalog.value))
        self.assertNotIn("requires_aart", payload["artifacts"][0])
        self.assertEqual(payload["collections"][0]["coordinate"], "direct/collection/starter")
        self.assertEqual(
            payload["collections"][0]["members"],
            ["direct/skill/member@1.0.0"],
        )
        self.assertIn("direct/collection/starter", render_marketplace(catalog.value))
        collection = catalog.value.collections[0]
        with self.assertRaises(ValueError):
            MarketplaceCatalog(
                catalog.value.sources,
                catalog.value.items,
                (collection, collection),
            )

    def test_outputs_redact_credentials_from_untrusted_provenance(self) -> None:
        source = configured_source("direct", SourceKind.SOURCE_GIT)
        planted = "do-not-leak"
        indexed = artifact(
            "direct-id",
            "private",
            provenance=IndexProvenance(
                credential_url(
                    "upstream.example",
                    f"/private.git?token={planted}",
                    held=planted,
                ),
                "b" * 40,
                SafeRelativePath(("artifacts", "skill", "private")),
            ),
        )
        indexed = replace(indexed, summary=f"Use private with api_key={planted}")
        catalog = build_marketplace(
            graph((source, "direct-id", (indexed,))),
            effective_configuration((source,)),
            (source_state(source, "direct-id", display_order=0),),
        )
        assert isinstance(catalog, Ok)

        encoded = marketplace_catalog_bytes(catalog.value).decode("utf-8")
        rendered = render_marketplace(catalog.value)

        self.assertNotIn(planted, encoded)
        self.assertNotIn(planted, rendered)
        self.assertIn("[redacted]", encoded)
        self.assertIn("[redacted]", rendered)


if __name__ == "__main__":
    unittest.main()
