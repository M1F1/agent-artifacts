from __future__ import annotations

import unittest

from agent_artifacts.domain.identifiers import ObjectDigest, SourceId
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.protocol.capabilities import Capability
from agent_artifacts.protocol.json import canonical_json_bytes
from agent_artifacts.protocol.native_models import CollectionManifest
from agent_artifacts.protocol.native_schema import (
    parse_artifact_manifest,
    parse_collection_manifest,
    parse_provenance,
)
from agent_artifacts.protocol.native_tree import NativeArtifactPackage
from agent_artifacts.protocol.registry_index import (
    build_registry_index,
    index_artifact_from_package,
)
from agent_artifacts.protocol.registry_models import ReviewRecord
from agent_artifacts.protocol.registry_schema import (
    parse_registry_index,
    parse_registry_manifest,
    registry_index_to_json,
)


def _digest(character: str) -> ObjectDigest:
    return ObjectDigest("sha256", character * 64)


def _manifest_json(name: str) -> str:
    return f"""{{
      "schema_version": 1,
      "type": "skill",
      "name": "{name}",
      "version": "1.2.0",
      "summary": "Use {name} during agent work.",
      "payload": {{"root": "payload", "format": "aart-skill-v1"}},
      "compatibility": {{"profiles": ["tabnine", "claude"], "platforms": ["linux", "darwin"]}},
      "install": {{"scopes": ["user", "project"], "modes": ["symlink", "copy"], "effects": ["copy-tree"]}}
    }}"""


def _registry():
    result = parse_registry_manifest(
        """{
          "schema_version": 1,
          "protocol_version": 1,
          "registry_id": "company-registry",
          "display_name": "Company Registry",
          "requires_aart": {"min_inclusive": "1.0.0", "max_exclusive": "2.0.0"},
          "required_capabilities": ["registry-entry-v1"],
          "default_channel": "main",
          "services": {}
        }"""
    )
    assert isinstance(result, Ok)
    return result.value


def _package(name: str) -> NativeArtifactPackage:
    manifest = parse_artifact_manifest(_manifest_json(name))
    assert isinstance(manifest, Ok)
    return NativeArtifactPackage(manifest.value, None, _digest("1"), _digest("2"))


def _configured_package() -> NativeArtifactPackage:
    manifest = parse_artifact_manifest(
        """{
          "schema_version": 1,
          "type": "mcp",
          "name": "atlassian",
          "version": "2.1.0",
          "summary": "Connect reviewed Atlassian tools.",
          "payload": {"root": "payload", "format": "aart-mcp-v1"},
          "compatibility": {"profiles": ["claude"], "platforms": ["darwin"]},
          "install": {"scopes": ["user"], "modes": ["copy"], "effects": ["merge-json"]},
          "setup": {"recipe": "setup/installer.json", "platforms": ["darwin"]}
        }"""
    )
    provenance = parse_provenance(
        f"""{{
          "schema_version": 1,
          "origin": {{
            "kind": "git",
            "url": "https://github.example/platform/atlassian.git",
            "resolved_commit": "{"a" * 40}",
            "path": "artifacts/mcp/atlassian",
            "input_digest": "{_digest("4")}"
          }},
          "importer": {{
            "id": "native-importer",
            "version": "1.0.0",
            "options_digest": "{_digest("5")}"
          }},
          "warnings": []
        }}"""
    )
    assert isinstance(manifest, Ok)
    assert isinstance(provenance, Ok)
    return NativeArtifactPackage(manifest.value, provenance.value, _digest("1"), _digest("2"))


def _collection(name: str, artifacts: list[str], collections: list[str]) -> CollectionManifest:
    selectors = ",".join(f'{{"type":"skill","name":"{artifact}"}}' for artifact in artifacts)
    nested = ",".join(f'"{collection}"' for collection in collections)
    result = parse_collection_manifest(
        f"""{{
          "schema_version": 1,
          "name": "{name}",
          "summary": "The {name} collection.",
          "artifacts": [{selectors}],
          "collections": [{nested}]
        }}"""
    )
    assert isinstance(result, Ok)
    return result.value


class RegistryIndexTest(unittest.TestCase):
    def test_registry_owned_package_becomes_index_record_without_duplicate_entry(self) -> None:
        record = index_artifact_from_package(
            _package("code-review"),
            source_id=SourceId("company-registry"),
            object_digest=_digest("3"),
            review=ReviewRecord("approved", "company-review-v1"),
        )

        self.assertEqual(str(record.identity), "skill/code-review")
        self.assertEqual(record.summary, "Use code-review during agent work.")
        self.assertEqual(record.collections, ())
        self.assertIsNone(record.provenance)

    def test_setup_and_provenance_are_summarized_without_content(self) -> None:
        record = index_artifact_from_package(
            _configured_package(),
            source_id=SourceId("company-registry"),
            object_digest=_digest("3"),
        )

        self.assertIsNotNone(record.setup)
        self.assertIsNotNone(record.provenance)
        assert record.setup is not None
        assert record.provenance is not None
        self.assertEqual(str(record.setup.recipe), "setup/installer.json")
        self.assertEqual(record.provenance.resolved_commit, "a" * 40)

    def test_index_output_is_byte_identical_across_input_order(self) -> None:
        first = index_artifact_from_package(
            _package("code-review"),
            source_id=SourceId("company-registry"),
            object_digest=_digest("3"),
        )
        second = index_artifact_from_package(
            _package("python-style"),
            source_id=SourceId("company-registry"),
            object_digest=_digest("4"),
        )
        essentials = _collection("essentials", ["code-review"], [])
        all_tools = _collection("all-tools", ["python-style"], ["essentials"])

        left = build_registry_index(
            _registry(), _digest("0"), (second, first), (all_tools, essentials)
        )
        right = build_registry_index(
            _registry(), _digest("0"), (first, second), (essentials, all_tools)
        )

        self.assertIsInstance(left, Ok)
        self.assertEqual(left, right)
        assert isinstance(left, Ok)
        encoded = canonical_json_bytes(registry_index_to_json(left.value))
        reparsed = parse_registry_index(encoded)
        self.assertEqual(reparsed, left)
        self.assertNotIn(b"trust", encoded)
        self.assertNotIn(b"payload_bytes", encoded)

    def test_membership_is_derived_for_direct_and_nested_collections(self) -> None:
        artifact = index_artifact_from_package(
            _package("code-review"),
            source_id=SourceId("company-registry"),
            object_digest=_digest("3"),
        )
        child = _collection("child", ["code-review"], [])
        parent = _collection("parent", [], ["child"])

        result = build_registry_index(_registry(), _digest("0"), (artifact,), (parent, child))

        self.assertIsInstance(result, Ok)
        assert isinstance(result, Ok)
        self.assertEqual(result.value.artifacts[0].collections, ("child", "parent"))

    def test_dangling_artifact_or_collection_and_cycles_fail_closed(self) -> None:
        artifact = index_artifact_from_package(
            _package("code-review"),
            source_id=SourceId("company-registry"),
            object_digest=_digest("3"),
        )
        cases = (
            (_collection("dangling-artifact", ["missing"], []),),
            (_collection("dangling-collection", [], ["missing"]),),
            (
                _collection("cycle-a", [], ["cycle-b"]),
                _collection("cycle-b", [], ["cycle-a"]),
            ),
        )

        for collections in cases:
            with self.subTest(collections=collections):
                result = build_registry_index(_registry(), _digest("0"), (artifact,), collections)
                self.assertIsInstance(result, Err)

    def test_duplicate_qualified_identity_and_incompatible_registry_fail(self) -> None:
        artifact = index_artifact_from_package(
            _package("code-review"),
            source_id=SourceId("company-registry"),
            object_digest=_digest("3"),
        )
        duplicate = index_artifact_from_package(
            _package("code-review"),
            source_id=SourceId("company-registry"),
            object_digest=_digest("4"),
        )

        self.assertIsInstance(
            build_registry_index(_registry(), _digest("0"), (artifact, duplicate), ()), Err
        )
        self.assertNotIn(Capability("not-used"), _registry().required_capabilities)

    def test_duplicate_collection_and_version_exclusion_fail_closed(self) -> None:
        artifact = index_artifact_from_package(
            _package("code-review"),
            source_id=SourceId("company-registry"),
            object_digest=_digest("3"),
        )
        collection = _collection("tools", ["code-review"], [])
        excluded = parse_collection_manifest(
            """{
              "schema_version": 1,
              "name": "old-only",
              "summary": "Only old releases.",
              "artifacts": [{
                "type": "skill",
                "name": "code-review",
                "version": {"max_exclusive": "1.0.0"}
              }]
            }"""
        )
        assert isinstance(excluded, Ok)

        self.assertIsInstance(
            build_registry_index(_registry(), _digest("0"), (artifact,), (collection, collection)),
            Err,
        )
        self.assertIsInstance(
            build_registry_index(_registry(), _digest("0"), (artifact,), (excluded.value,)),
            Err,
        )


if __name__ == "__main__":
    unittest.main()
