from __future__ import annotations

import copy
import json
import unittest
from typing import Callable

from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.protocol.json import canonical_json_bytes
from agent_artifacts.protocol.registry_schema import (
    parse_registry_entry,
    parse_registry_index,
    parse_registry_lock,
    parse_registry_manifest,
    registry_entry_to_json,
    registry_index_to_json,
    registry_lock_to_json,
    registry_manifest_to_json,
)


def _digest(character: str) -> str:
    return f"sha256:{character * 64}"


def _manifest() -> dict[str, object]:
    return {
        "schema_version": 1,
        "protocol_version": 1,
        "registry_id": "company-registry",
        "display_name": "Company Registry",
        "requires_aart": {"min_inclusive": "1.0.0", "max_exclusive": "2.0.0"},
        "required_capabilities": ["registry-entry-v1"],
        "default_channel": "main",
        "services": {
            "usage_reporting": {
                "kind": "github-issues",
                "repository": "agents/company-registry",
            }
        },
    }


def _entry() -> dict[str, object]:
    return {
        "schema_version": 1,
        "type": "mcp",
        "name": "atlassian",
        "source": {
            "kind": "git",
            "url": "https://github.example/platform/atlassian.git",
            "ref": "main",
            "path": "artifacts/mcp/atlassian",
        },
        "review": {"status": "approved", "policy": "review-v1"},
    }


def _locked() -> dict[str, object]:
    return {
        "origin_url": "https://github.example/platform/atlassian.git",
        "requested_ref": "main",
        "resolved_commit": "a" * 40,
        "path": "artifacts/mcp/atlassian",
        "manifest_digest": _digest("1"),
        "payload_digest": _digest("2"),
        "object_digest": _digest("3"),
        "artifact_version": "2.1.0",
        "review": {"status": "approved", "policy": "review-v1"},
        "provenance_digest": _digest("4"),
    }


def _lock() -> dict[str, object]:
    return {
        "schema_version": 1,
        "registry_inputs_digest": _digest("0"),
        "entries": {"mcp/atlassian": _locked()},
    }


def _index_artifact() -> dict[str, object]:
    return {
        "source_id": "company-registry",
        "type": "mcp",
        "name": "atlassian",
        "version": "2.1.0",
        "summary": "Connect reviewed Atlassian tools.",
        "manifest_digest": _digest("1"),
        "payload_digest": _digest("2"),
        "object_digest": _digest("3"),
        "compatibility": {
            "profiles": ["claude", "tabnine"],
            "platforms": ["darwin", "linux"],
        },
        "install": {
            "scopes": ["project", "user"],
            "modes": ["copy"],
            "effects": ["merge-json"],
        },
        "setup": {
            "recipe": "setup/installer.json",
            "platforms": ["darwin"],
            "capabilities": ["keychain-write-v1"],
        },
        "review": {"status": "approved", "policy": "review-v1"},
        "provenance": {
            "origin_url": "https://github.example/platform/atlassian.git",
            "resolved_commit": "a" * 40,
            "path": "artifacts/mcp/atlassian",
        },
        "collections": ["essentials"],
    }


def _collection(name: str = "essentials") -> dict[str, object]:
    return {
        "name": name,
        "summary": "Reviewed essentials.",
        "artifacts": [{"type": "mcp", "name": "atlassian"}],
        "collections": [],
    }


def _index() -> dict[str, object]:
    return {
        "schema_version": 1,
        "protocol_version": 1,
        "registry_id": "company-registry",
        "registry_inputs_digest": _digest("0"),
        "artifacts": [_index_artifact()],
        "collections": [_collection()],
        "services": {},
    }


def _encoded(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


Parser = Callable[[bytes | str], Result[object]]


class RegistryProtocolEdgesTest(unittest.TestCase):
    def assert_invalid(self, parser: Parser, value: object) -> None:
        self.assertIsInstance(parser(_encoded(value)), Err)

    def test_canonical_projection_round_trips_all_registry_documents(self) -> None:
        cases = (
            (parse_registry_manifest, registry_manifest_to_json, _manifest()),
            (parse_registry_entry, registry_entry_to_json, _entry()),
            (parse_registry_lock, registry_lock_to_json, _lock()),
            (parse_registry_index, registry_index_to_json, _index()),
        )
        for parser, projector, document in cases:
            with self.subTest(parser=parser.__name__):
                parsed = parser(_encoded(document))
                self.assertIsInstance(parsed, Ok)
                assert isinstance(parsed, Ok)
                self.assertEqual(parser(canonical_json_bytes(projector(parsed.value))), parsed)

    def test_authored_namespaced_extensions_survive_canonical_projection(self) -> None:
        manifest = _manifest()
        manifest["com.example.channel"] = "preview"
        entry = _entry()
        entry["com.example.owner"] = "platform"

        parsed_manifest = parse_registry_manifest(_encoded(manifest))
        parsed_entry = parse_registry_entry(_encoded(entry))

        self.assertIsInstance(parsed_manifest, Ok)
        self.assertIsInstance(parsed_entry, Ok)
        assert isinstance(parsed_manifest, Ok)
        assert isinstance(parsed_entry, Ok)
        self.assertEqual(
            parse_registry_manifest(
                canonical_json_bytes(registry_manifest_to_json(parsed_manifest.value))
            ),
            parsed_manifest,
        )
        self.assertEqual(
            parse_registry_entry(canonical_json_bytes(registry_entry_to_json(parsed_entry.value))),
            parsed_entry,
        )

    def test_manifest_scalar_version_and_capability_edges_fail_closed(self) -> None:
        mutations: tuple[tuple[str, object], ...] = (
            ("schema_version", "1"),
            ("schema_version", 2),
            ("protocol_version", "1"),
            ("protocol_version", 2),
            ("registry_id", "Bad ID"),
            ("display_name", "two\nlines"),
            ("display_name", ""),
            ("requires_aart", []),
            ("required_capabilities", "registry-entry-v1"),
            ("required_capabilities", [1]),
            ("required_capabilities", ["Bad Capability"]),
            ("default_channel", "--unsafe"),
            ("default_channel", "feature//bad"),
            ("default_channel", "feature."),
            ("default_channel", "feature bad"),
            ("default_channel", "@"),
            ("default_channel", ".hidden/main"),
            ("default_channel", "release.lock"),
            ("services", []),
        )
        for field, replacement in mutations:
            with self.subTest(field=field, replacement=replacement):
                value = _manifest()
                value[field] = replacement
                self.assert_invalid(parse_registry_manifest, value)

        for bounds in (
            {"unknown": "1.0.0"},
            {"min_inclusive": 1},
            {"min_inclusive": "bad"},
            {"max_exclusive": 2},
            {"max_exclusive": "bad"},
            {"min_inclusive": "2.0.0", "max_exclusive": "1.0.0"},
        ):
            with self.subTest(bounds=bounds):
                value = _manifest()
                value["requires_aart"] = bounds
                self.assert_invalid(parse_registry_manifest, value)

    def test_manifest_service_shapes_fail_closed(self) -> None:
        services = (
            {"bad-name": {"kind": "github-issues", "repository": "org/repo"}},
            {"usage_reporting": "github-issues"},
            {"usage_reporting": {}},
            {"usage_reporting": {"kind": 1}},
            {"usage_reporting": {"kind": "Bad Kind"}},
            {"usage_reporting": {"kind": "github-issues"}},
            {"usage_reporting": {"kind": "github-issues", "repository": 1}},
            {
                "usage_reporting": {
                    "kind": "github-issues",
                    "repository": "https://example.test/org/repo",
                }
            },
            {"usage_reporting": {"kind": "custom", "repository": "org/repo", "enabled": True}},
        )
        for replacement in services:
            with self.subTest(replacement=replacement):
                value = _manifest()
                value["services"] = replacement
                self.assert_invalid(parse_registry_manifest, value)

    def test_entry_shape_review_source_and_ref_edges_fail_closed(self) -> None:
        top_mutations: tuple[tuple[str, object], ...] = (
            ("schema_version", "1"),
            ("schema_version", 2),
            ("type", 1),
            ("type", "collection"),
            ("name", 1),
            ("name", "Bad Name"),
            ("source", []),
            ("review", []),
            ("review", {"status": "unknown", "policy": "review-v1"}),
            ("review", {"status": 1, "policy": "review-v1"}),
            ("review", {"status": "approved", "policy": 1}),
            ("review", {"status": "approved", "policy": "Bad Policy"}),
        )
        for field, replacement in top_mutations:
            with self.subTest(field=field, replacement=replacement):
                value = _entry()
                value[field] = replacement
                self.assert_invalid(parse_registry_entry, value)

        source_mutations: tuple[tuple[str, object], ...] = (
            ("kind", 1),
            ("kind", "http"),
            ("url", 1),
            ("url", "http://example.test/repo.git"),
            ("url", "https://example.test/repo.git?token=x"),
            ("url", "https://example.test/repo.git#fragment"),
            ("url", "https://example test/repo.git"),
            ("ref", 1),
            ("ref", "refs/../main"),
            ("ref", "/main"),
            ("ref", "main/"),
            ("ref", "main~1"),
            ("path", 1),
            ("path", "../artifacts/mcp/atlassian"),
            ("path", "artifacts/mcp/other"),
        )
        for field, replacement in source_mutations:
            with self.subTest(field=field, replacement=replacement):
                value = _entry()
                source = copy.deepcopy(value["source"])
                assert isinstance(source, dict)
                source[field] = replacement
                value["source"] = source
                self.assert_invalid(parse_registry_entry, value)

    def test_lock_header_identity_and_record_edges_fail_closed(self) -> None:
        top_mutations: tuple[tuple[str, object], ...] = (
            ("schema_version", "1"),
            ("schema_version", 2),
            ("registry_inputs_digest", 1),
            ("registry_inputs_digest", "sha256:bad"),
            ("entries", []),
            ("entries", {"bad-key": _locked()}),
            ("entries", {"mcp/atlassian": []}),
        )
        for field, replacement in top_mutations:
            with self.subTest(field=field, replacement=replacement):
                value = _lock()
                value[field] = replacement
                self.assert_invalid(parse_registry_lock, value)

        locked_mutations: tuple[tuple[str, object], ...] = (
            ("origin_url", 1),
            ("origin_url", "http://example.test/repo.git"),
            ("requested_ref", 1),
            ("requested_ref", "main..bad"),
            ("resolved_commit", 1),
            ("resolved_commit", "A" * 40),
            ("path", 1),
            ("path", "../artifacts/mcp/atlassian"),
            ("path", "artifacts/mcp/other"),
            ("manifest_digest", 1),
            ("manifest_digest", "sha256:bad"),
            ("payload_digest", "sha256:bad"),
            ("object_digest", "sha256:bad"),
            ("artifact_version", 1),
            ("artifact_version", "latest"),
            ("review", []),
            ("provenance_digest", 1),
            ("provenance_digest", "sha256:bad"),
        )
        for field, replacement in locked_mutations:
            with self.subTest(field=field, replacement=replacement):
                value = _lock()
                locked = _locked()
                locked[field] = replacement
                value["entries"] = {"mcp/atlassian": locked}
                self.assert_invalid(parse_registry_lock, value)

    def test_index_header_artifact_setup_and_provenance_edges_fail_closed(self) -> None:
        top_mutations: tuple[tuple[str, object], ...] = (
            ("schema_version", "1"),
            ("schema_version", 2),
            ("protocol_version", "1"),
            ("protocol_version", 2),
            ("registry_id", "Bad ID"),
            ("registry_inputs_digest", "sha256:bad"),
            ("artifacts", {}),
            ("collections", {}),
            ("services", []),
        )
        for field, replacement in top_mutations:
            with self.subTest(field=field, replacement=replacement):
                value = _index()
                value[field] = replacement
                self.assert_invalid(parse_registry_index, value)

        artifact_mutations: tuple[tuple[str, object], ...] = (
            ("source_id", 1),
            ("source_id", "Bad ID"),
            ("type", 1),
            ("name", 1),
            ("version", 1),
            ("version", "latest"),
            ("summary", 1),
            ("summary", "two\nlines"),
            ("manifest_digest", "sha256:bad"),
            ("payload_digest", "sha256:bad"),
            ("object_digest", "sha256:bad"),
            ("compatibility", []),
            ("compatibility", {"profiles": [], "platforms": ["darwin"]}),
            ("compatibility", {"profiles": ["Bad"], "platforms": ["darwin"]}),
            ("install", []),
            ("install", {"scopes": [], "modes": ["copy"], "effects": ["merge-json"]}),
            (
                "install",
                {"scopes": ["project"], "modes": ["unknown"], "effects": ["merge-json"]},
            ),
            (
                "install",
                {"scopes": ["project"], "modes": ["copy"], "effects": ["copy-tree"]},
            ),
            ("setup", []),
            ("setup", {"recipe": "setup/x.json", "platforms": ["darwin"]}),
            (
                "setup",
                {"recipe": "README.md", "platforms": ["darwin"], "capabilities": []},
            ),
            (
                "setup",
                {"recipe": "setup/x.json", "platforms": [], "capabilities": []},
            ),
            (
                "setup",
                {
                    "recipe": "setup/x.json",
                    "platforms": ["darwin"],
                    "capabilities": ["Bad Capability"],
                },
            ),
            ("review", {"status": "unknown", "policy": "review-v1"}),
            ("provenance", []),
            (
                "provenance",
                {
                    "origin_url": "http://example.test/repo",
                    "resolved_commit": "a" * 40,
                    "path": "artifacts/mcp/atlassian",
                },
            ),
            (
                "provenance",
                {
                    "origin_url": "https://example.test/repo",
                    "resolved_commit": "main",
                    "path": "artifacts/mcp/atlassian",
                },
            ),
            (
                "provenance",
                {
                    "origin_url": "https://example.test/repo",
                    "resolved_commit": "a" * 40,
                    "path": "../unsafe",
                },
            ),
            ("collections", "essentials"),
            ("collections", ["Bad Name"]),
        )
        for field, replacement in artifact_mutations:
            with self.subTest(field=field, replacement=replacement):
                value = _index()
                artifact = _index_artifact()
                artifact[field] = replacement
                value["artifacts"] = [artifact]
                self.assert_invalid(parse_registry_index, value)

    def test_index_collection_and_duplicate_edges_fail_closed(self) -> None:
        invalid_collections: tuple[object, ...] = (
            "essentials",
            {"name": "empty", "summary": "Empty.", "artifacts": [], "collections": []},
            {
                "name": "bad",
                "summary": "Bad.",
                "artifacts": [{"type": "unknown", "name": "x"}],
                "collections": [],
            },
        )
        for collection in invalid_collections:
            with self.subTest(collection=collection):
                value = _index()
                value["collections"] = [collection]
                self.assert_invalid(parse_registry_index, value)

        duplicate_artifacts = _index()
        duplicate_artifacts["artifacts"] = [_index_artifact(), _index_artifact()]
        self.assert_invalid(parse_registry_index, duplicate_artifacts)

        duplicate_collections = _index()
        duplicate_collections["collections"] = [_collection(), _collection()]
        self.assert_invalid(parse_registry_index, duplicate_collections)

    def test_index_parser_revalidates_graph_and_derived_memberships(self) -> None:
        wrong_membership = _index()
        artifact = _index_artifact()
        artifact["collections"] = []
        wrong_membership["artifacts"] = [artifact]
        self.assert_invalid(parse_registry_index, wrong_membership)

        dangling = _index()
        collection = _collection()
        collection["collections"] = ["missing"]
        dangling["collections"] = [collection]
        self.assert_invalid(parse_registry_index, dangling)

        cyclic = _index()
        child = _collection("child")
        child["collections"] = ["parent"]
        parent = _collection("parent")
        parent["collections"] = ["child"]
        cyclic["collections"] = [child, parent]
        cyclic_artifact = _index_artifact()
        cyclic_artifact["collections"] = ["child", "parent"]
        cyclic["artifacts"] = [cyclic_artifact]
        self.assert_invalid(parse_registry_index, cyclic)

        repeated_schema = _index()
        collection = _collection()
        collection["schema_version"] = 1
        repeated_schema["collections"] = [collection]
        self.assert_invalid(parse_registry_index, repeated_schema)

    def test_index_collection_namespaced_extension_round_trips(self) -> None:
        value = _index()
        collection = _collection()
        collection["com.example.label"] = "reviewed"
        value["collections"] = [collection]

        parsed = parse_registry_index(_encoded(value))

        self.assertIsInstance(parsed, Ok)
        assert isinstance(parsed, Ok)
        encoded = canonical_json_bytes(registry_index_to_json(parsed.value))
        self.assertIn(b"com.example.label", encoded)
        self.assertEqual(parse_registry_index(encoded), parsed)

    def test_non_object_missing_and_unknown_documents_fail_closed(self) -> None:
        parsers = (
            parse_registry_manifest,
            parse_registry_entry,
            parse_registry_lock,
            parse_registry_index,
        )
        for parser in parsers:
            for document in ("[]", "{", "{}", '{"unknown":true}'):
                with self.subTest(parser=parser.__name__, document=document):
                    self.assertIsInstance(parser(document), Err)


if __name__ == "__main__":
    unittest.main()
