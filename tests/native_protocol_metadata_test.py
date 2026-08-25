"""P02 contracts for provenance, collections, and the incremental legacy adapter."""

from __future__ import annotations

import json
import unittest

from tests.credential_fixtures import assignment, credential_url


def _unwrap(result):
    from agent_artifacts.domain.result import Ok

    if not isinstance(result, Ok):
        raise AssertionError(f"expected Ok, got {result!r}")
    return result.value


def _codes(result) -> tuple[str, ...]:
    from agent_artifacts.domain.result import Err

    if not isinstance(result, Err):
        raise AssertionError(f"expected Err, got {result!r}")
    return tuple(diagnostic.code.value for diagnostic in result.diagnostics)


def _provenance_document(**overrides):
    document = {
        "schema_version": 1,
        "origin": {
            "kind": "git",
            "url": "https://github.com/example/upstream.git",
            "resolved_commit": "a" * 40,
            "path": ".claude/skills/example",
            "input_digest": f"sha256:{'b' * 64}",
        },
        "importer": {
            "id": "claude-skill-v1",
            "version": "1.0.0",
            "options_digest": f"sha256:{'c' * 64}",
        },
        "warnings": ["Frontmatter field x was preserved as an extension."],
    }
    document.update(overrides)
    return document


class ProvenanceTest(unittest.TestCase):
    def test_parses_digest_bound_import_provenance(self):
        from agent_artifacts.protocol.native_schema import parse_provenance

        provenance = _unwrap(parse_provenance(json.dumps(_provenance_document())))

        self.assertEqual(provenance.origin.kind, "git")
        self.assertEqual(provenance.origin.resolved_commit, "a" * 40)
        self.assertEqual(str(provenance.origin.input_digest), f"sha256:{'b' * 64}")
        self.assertEqual(str(provenance.importer.version), "1.0.0")

    def test_rejects_credentials_unpinned_commits_and_invalid_digests(self):
        from agent_artifacts.protocol.native_schema import parse_provenance

        for origin_update in (
            {"url": credential_url("github.com", "/example/upstream.git")},
            {"url": "https://github.com/example/upstream.git?" + assignment("token", "secret")},
            {"resolved_commit": "main"},
            {"input_digest": "sha256:not-a-digest"},
        ):
            document = _provenance_document()
            document["origin"].update(origin_update)
            with self.subTest(origin_update=origin_update):
                self.assertEqual(
                    _codes(parse_provenance(json.dumps(document))),
                    ("provenance-invalid",),
                )

    def test_provenance_schema_and_importer_fields_are_strict(self):
        from agent_artifacts.protocol.native_schema import parse_provenance

        cases = []
        for origin_update in (
            {"kind": "local"},
            {"url": "ftp://example.test/repo"},
            {"path": "../outside"},
        ):
            document = _provenance_document()
            document["origin"].update(origin_update)
            cases.append(document)
        for importer_update in (
            {"id": "Bad_Importer"},
            {"version": "latest"},
            {"options_digest": "sha256:bad"},
        ):
            document = _provenance_document()
            document["importer"].update(importer_update)
            cases.append(document)
        cases.extend(
            (
                [],
                _provenance_document(schema_version=2),
                _provenance_document(origin=[]),
                _provenance_document(importer=[]),
                _provenance_document(warnings="none"),
            )
        )
        for document in cases:
            with self.subTest(document=document):
                self.assertEqual(
                    _codes(parse_provenance(json.dumps(document))),
                    ("provenance-invalid",),
                )

        extension = _provenance_document(**{"com.acme.review": "manual"})
        parsed = _unwrap(parse_provenance(json.dumps(extension)))
        self.assertEqual(parsed.extensions, (("com.acme.review", "manual"),))

        ssh = _provenance_document()
        ssh["origin"]["url"] = "git@github.com:example/upstream.git"
        self.assertEqual(
            _unwrap(parse_provenance(json.dumps(ssh))).origin.url,
            "git@github.com:example/upstream.git",
        )


class CollectionTest(unittest.TestCase):
    def test_parses_structured_artifact_selectors_and_collection_references(self):
        from agent_artifacts.protocol.native_schema import parse_collection_manifest

        document = {
            "schema_version": 1,
            "name": "backend",
            "summary": "Install the reviewed backend toolkit.",
            "artifacts": [
                {
                    "type": "skill",
                    "name": "code-review",
                    "version": {"min_inclusive": "1.0.0", "max_exclusive": "2.0.0"},
                },
                {"type": "mcp", "name": "postgres"},
            ],
            "collections": ["base"],
        }

        collection = _unwrap(parse_collection_manifest(json.dumps(document)))

        self.assertEqual(collection.name, "backend")
        self.assertEqual(
            tuple(str(selector.identity) for selector in collection.artifacts),
            ("mcp/postgres", "skill/code-review"),
        )
        self.assertEqual(collection.collections, ("base",))

    def test_rejects_duplicate_selectors_and_self_reference(self):
        from agent_artifacts.protocol.native_schema import parse_collection_manifest

        duplicate = {
            "schema_version": 1,
            "name": "backend",
            "summary": "Backend tools.",
            "artifacts": [
                {"type": "skill", "name": "review"},
                {"type": "skill", "name": "review"},
            ],
            "collections": ["backend"],
        }
        self.assertEqual(
            _codes(parse_collection_manifest(json.dumps(duplicate))),
            ("collection-invalid",),
        )
        self_reference = {
            "schema_version": 1,
            "name": "backend",
            "summary": "Backend tools.",
            "artifacts": [],
            "collections": ["backend"],
        }
        self.assertEqual(
            _codes(parse_collection_manifest(json.dumps(self_reference))),
            ("collection-invalid",),
        )
        empty = {**self_reference, "collections": []}
        self.assertEqual(
            _codes(parse_collection_manifest(json.dumps(empty))),
            ("collection-invalid",),
        )

    def test_collection_document_and_selector_fields_are_strict(self):
        from agent_artifacts.protocol.native_schema import parse_collection_manifest

        base = {
            "schema_version": 1,
            "name": "backend",
            "summary": "Backend tools.",
            "artifacts": [],
            "collections": [],
        }
        cases = (
            ([], "collection-invalid"),
            ({**base, "schema_version": 2}, "collection-invalid"),
            ({**base, "name": "Bad_Name"}, "collection-invalid"),
            ({**base, "summary": "two\nlines"}, "collection-invalid"),
            ({**base, "artifacts": {}}, "collection-invalid"),
            ({**base, "artifacts": ["skill/review"]}, "collection-invalid"),
            (
                {**base, "artifacts": [{"type": "widget", "name": "review"}]},
                "collection-invalid",
            ),
            (
                {
                    **base,
                    "artifacts": [
                        {
                            "type": "skill",
                            "name": "review",
                            "version": {
                                "min_inclusive": "2.0.0",
                                "max_exclusive": "1.0.0",
                            },
                        }
                    ],
                },
                "protocol-version-bounds-invalid",
            ),
            ({**base, "collections": ["Bad_Name"]}, "collection-invalid"),
        )
        for document, expected in cases:
            with self.subTest(document=document):
                self.assertEqual(
                    _codes(parse_collection_manifest(json.dumps(document))),
                    (expected,),
                )
