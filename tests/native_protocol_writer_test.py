from __future__ import annotations

import unittest

from agent_artifacts.domain.identifiers import ArtifactIdentity, ObjectDigest
from agent_artifacts.domain.result import Ok
from agent_artifacts.protocol.json import canonical_json_bytes
from agent_artifacts.protocol.native_models import (
    ArtifactSelector,
    CollectionManifest,
    ImporterProvenance,
    OriginProvenance,
    Provenance,
)
from agent_artifacts.protocol.native_schema import (
    collection_manifest_to_json,
    parse_collection_manifest,
    parse_provenance,
    provenance_to_json,
)
from agent_artifacts.protocol.paths import SafeRelativePath
from agent_artifacts.protocol.semver import SemVer


class NativeProtocolWriterTest(unittest.TestCase):
    def test_provenance_and_collection_canonical_writers_round_trip(self) -> None:
        digest = ObjectDigest("sha256", "a" * 64)
        provenance = Provenance(
            1,
            OriginProvenance(
                "git",
                "https://example.test/upstream.git",
                "b" * 40,
                SafeRelativePath(("skills", "demo")),
                digest,
            ),
            ImporterProvenance("legacy-catalog-v1", SemVer(1, 0, 0), digest),
            ("preserved legacy metadata",),
        )
        collection = CollectionManifest(
            1,
            "base",
            "Base collection.",
            (ArtifactSelector(ArtifactIdentity("skill", "demo")),),
        )

        provenance_bytes = canonical_json_bytes(provenance_to_json(provenance))
        collection_bytes = canonical_json_bytes(collection_manifest_to_json(collection))

        self.assertEqual(parse_provenance(provenance_bytes), Ok(provenance))
        self.assertEqual(parse_collection_manifest(collection_bytes), Ok(collection))


if __name__ == "__main__":
    unittest.main()
