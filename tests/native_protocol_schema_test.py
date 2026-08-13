"""P02 contracts for native source and canonical artifact documents."""

from __future__ import annotations

import json
import unittest


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


def _source_document(**overrides):
    document = {
        "schema_version": 1,
        "protocol_version": 1,
        "source_id": "team-a-artifacts",
        "display_name": "Team A Artifacts",
        "requires_aart": {"min_inclusive": "1.0.0", "max_exclusive": "2.0.0"},
        "required_capabilities": ["source-package-v1", "artifact-manifest-v1"],
        "artifact_roots": ["vendor/artifacts", "artifacts"],
        "collection_roots": ["collections"],
    }
    document.update(overrides)
    return document


def _artifact_document(artifact_type: str, payload_format: str, **overrides):
    effects = {
        "skill": ["copy-tree"],
        "guideline": ["write-file"],
        "mcp": ["merge-json"],
        "hook": ["copy-tree", "merge-json"],
        "memory": ["managed-block"],
    }
    document = {
        "schema_version": 1,
        "type": artifact_type,
        "name": f"example-{artifact_type}",
        "version": "1.2.3",
        "summary": f"Install the example {artifact_type}.",
        "payload": {"root": "payload", "format": payload_format},
        "compatibility": {"profiles": ["tabnine", "claude"], "platforms": ["linux", "darwin"]},
        "install": {
            "scopes": ["user", "project"],
            "modes": ["symlink", "copy"],
            "effects": effects[artifact_type],
        },
    }
    document.update(overrides)
    return document


class SourceManifestTest(unittest.TestCase):
    def test_parses_normalizes_and_serializes_the_v1_source_contract(self):
        from agent_artifacts.protocol.hashing import json_digest
        from agent_artifacts.protocol.native_schema import (
            parse_source_manifest,
            source_manifest_to_json,
        )

        manifest = _unwrap(parse_source_manifest(json.dumps(_source_document())))

        self.assertEqual(str(manifest.source_id), "team-a-artifacts")
        self.assertEqual(
            tuple(str(item) for item in manifest.required_capabilities),
            ("artifact-manifest-v1", "source-package-v1"),
        )
        self.assertEqual(
            tuple(str(item) for item in manifest.artifact_roots),
            ("artifacts", "vendor/artifacts"),
        )
        self.assertEqual(
            str(json_digest(source_manifest_to_json(manifest))),
            "sha256:ad016ef8fa12fead0c8b6fdaa655696a8f0ca89de4079bff529fcfe078bcc67e",
        )

    def test_rejects_unknown_or_self_declared_trust_and_invalid_versions(self):
        from agent_artifacts.protocol.native_schema import parse_source_manifest

        unknown = _source_document(trust="company-reviewed", surprise=True)
        self.assertEqual(
            _codes(parse_source_manifest(json.dumps(unknown))),
            ("protocol-schema-unknown-field", "protocol-schema-unknown-field"),
        )
        self.assertEqual(
            _codes(parse_source_manifest(json.dumps(_source_document(schema_version=2)))),
            ("source-invalid",),
        )
        self.assertEqual(
            _codes(
                parse_source_manifest(
                    json.dumps(
                        _source_document(
                            requires_aart={
                                "min_inclusive": "2.0.0",
                                "max_exclusive": "1.0.0",
                            }
                        )
                    )
                )
            ),
            ("protocol-version-bounds-invalid",),
        )

    def test_source_fields_fail_closed_with_stable_diagnostics(self):
        from agent_artifacts.protocol.native_schema import parse_source_manifest

        cases = (
            ([], "source-invalid"),
            ("{not-json", "protocol-json-invalid"),
            (_source_document(protocol_version=True), "source-invalid"),
            (_source_document(protocol_version=2), "source-invalid"),
            (_source_document(source_id="Team-A"), "source-invalid"),
            (_source_document(display_name="two\nlines"), "source-invalid"),
            (_source_document(requires_aart=[]), "source-invalid"),
            (
                _source_document(requires_aart={"unexpected": "1.0.0"}),
                "protocol-schema-unknown-field",
            ),
            (_source_document(requires_aart={"min_inclusive": 1}), "source-invalid"),
            (
                _source_document(requires_aart={"max_exclusive": "latest"}),
                "protocol-semver-invalid",
            ),
            (_source_document(required_capabilities="none"), "source-invalid"),
            (_source_document(required_capabilities=[1]), "source-invalid"),
            (_source_document(required_capabilities=["UPPER"]), "protocol-capability-invalid"),
            (_source_document(artifact_roots=[]), "source-invalid"),
            (_source_document(artifact_roots=["../outside"]), "protocol-path-invalid"),
            (
                _source_document(
                    artifact_roots=["content"],
                    collection_roots=["content/collections"],
                ),
                "source-invalid",
            ),
        )
        for document, expected in cases:
            with self.subTest(document=document):
                data = document if isinstance(document, str) else json.dumps(document)
                self.assertEqual(_codes(parse_source_manifest(data)), (expected,))

        extension = _source_document(**{"com.acme.channel": "preview"})
        manifest = _unwrap(parse_source_manifest(json.dumps(extension)))
        self.assertEqual(manifest.extensions, (("com.acme.channel", "preview"),))


class ArtifactManifestTest(unittest.TestCase):
    def test_all_canonical_artifact_types_parse_with_normalized_install_metadata(self):
        from agent_artifacts.protocol.native_models import PAYLOAD_FORMATS
        from agent_artifacts.protocol.native_schema import parse_artifact_manifest

        for artifact_type, payload_format in PAYLOAD_FORMATS:
            with self.subTest(artifact_type=artifact_type):
                document = _artifact_document(artifact_type, payload_format)
                if artifact_type == "mcp":
                    document["setup"] = {
                        "recipe": "setup/installer.json",
                        "platforms": ["darwin"],
                    }
                manifest = _unwrap(parse_artifact_manifest(json.dumps(document)))
                self.assertEqual(str(manifest.identity), f"{artifact_type}/example-{artifact_type}")
                self.assertEqual(str(manifest.version), "1.2.3")
                self.assertEqual(manifest.payload.format, payload_format)
                self.assertEqual(manifest.compatibility.profiles, ("claude", "tabnine"))
                self.assertEqual(manifest.install.scopes, ("project", "user"))
                self.assertEqual(manifest.install.modes, ("copy", "symlink"))

    def test_manifest_rejects_wrong_format_multiline_summary_and_trust(self):
        from agent_artifacts.protocol.native_schema import parse_artifact_manifest

        wrong_format = _artifact_document("skill", "aart-mcp-v1")
        self.assertEqual(
            _codes(parse_artifact_manifest(json.dumps(wrong_format))),
            ("artifact-invalid",),
        )
        multiline = _artifact_document("skill", "aart-skill-v1", summary="first\nsecond")
        self.assertEqual(
            _codes(parse_artifact_manifest(json.dumps(multiline))),
            ("artifact-invalid",),
        )
        with_trust = _artifact_document("skill", "aart-skill-v1", trust="local")
        self.assertEqual(
            _codes(parse_artifact_manifest(json.dumps(with_trust))),
            ("protocol-schema-unknown-field",),
        )

    def test_setup_and_install_values_are_bounded_and_explicit(self):
        from agent_artifacts.protocol.native_schema import parse_artifact_manifest

        bad_scope = _artifact_document("mcp", "aart-mcp-v1")
        bad_scope["install"]["scopes"] = ["machine"]
        self.assertEqual(
            _codes(parse_artifact_manifest(json.dumps(bad_scope))),
            ("artifact-invalid",),
        )

        bad_setup = _artifact_document("mcp", "aart-mcp-v1")
        bad_setup["setup"] = {"recipe": "../install.sh", "platforms": ["darwin"]}
        self.assertEqual(
            _codes(parse_artifact_manifest(json.dumps(bad_setup))),
            ("protocol-path-invalid",),
        )

        wrong_effect = _artifact_document("skill", "aart-skill-v1")
        wrong_effect["install"]["effects"] = ["merge-json"]
        self.assertEqual(
            _codes(parse_artifact_manifest(json.dumps(wrong_effect))),
            ("artifact-invalid",),
        )

    def test_nested_artifact_fields_are_strict_and_optional_metadata_round_trips(self):
        from agent_artifacts.protocol.json import canonical_json_bytes
        from agent_artifacts.protocol.native_schema import (
            artifact_manifest_to_json,
            parse_artifact_manifest,
        )

        unsupported_type = _artifact_document("skill", "aart-skill-v1")
        unsupported_type["type"] = "widget"

        cases = (
            ([], "artifact-invalid"),
            ("{not-json", "protocol-json-invalid"),
            (_artifact_document("skill", "aart-skill-v1", schema_version=2), "artifact-invalid"),
            (unsupported_type, "artifact-invalid"),
            (_artifact_document("skill", "aart-skill-v1", name="Bad_Name"), "artifact-invalid"),
            (
                _artifact_document("skill", "aart-skill-v1", version="next"),
                "protocol-semver-invalid",
            ),
            (_artifact_document("skill", "aart-skill-v1", payload=[]), "artifact-invalid"),
            (
                _artifact_document(
                    "skill",
                    "aart-skill-v1",
                    payload={"root": "payload"},
                ),
                "protocol-schema-missing-field",
            ),
            (
                _artifact_document(
                    "skill",
                    "aart-skill-v1",
                    payload={"root": "nested/payload", "format": "aart-skill-v1"},
                ),
                "artifact-invalid",
            ),
            (
                _artifact_document(
                    "skill",
                    "aart-skill-v1",
                    compatibility={"profiles": [], "platforms": ["darwin"]},
                ),
                "artifact-invalid",
            ),
            (
                _artifact_document(
                    "skill",
                    "aart-skill-v1",
                    compatibility={"profiles": ["UPPER"], "platforms": ["darwin"]},
                ),
                "artifact-invalid",
            ),
            (_artifact_document("skill", "aart-skill-v1", authors="Ada"), "artifact-invalid"),
            (_artifact_document("skill", "aart-skill-v1", license="MIT\nGPL"), "artifact-invalid"),
            (
                _artifact_document("skill", "aart-skill-v1", homepage="http://example.test"),
                "artifact-invalid",
            ),
            (
                _artifact_document(
                    "mcp",
                    "aart-mcp-v1",
                    setup={"recipe": "setup/installer.json", "platforms": ["windows"]},
                ),
                "artifact-invalid",
            ),
        )
        for document, expected in cases:
            with self.subTest(document=document):
                data = document if isinstance(document, str) else json.dumps(document)
                self.assertEqual(_codes(parse_artifact_manifest(data)), (expected,))

        complete = _artifact_document(
            "mcp",
            "aart-mcp-v1",
            requires_aart={"min_inclusive": "1.1.0", "max_exclusive": "2.0.0"},
            setup={"recipe": "setup/installer.json", "platforms": ["darwin"]},
            authors=["Ada", "Bob"],
            license="Apache-2.0",
            homepage="https://example.test/mcp",
            **{"com.acme.tier": "gold"},
        )
        manifest = _unwrap(parse_artifact_manifest(json.dumps(complete)))
        self.assertEqual(str(manifest.requires_aart.min_inclusive), "1.1.0")
        self.assertEqual(str(manifest.requires_aart.max_exclusive), "2.0.0")
        projected = artifact_manifest_to_json(manifest)
        self.assertEqual(
            _unwrap(parse_artifact_manifest(canonical_json_bytes(projected))), manifest
        )

    def test_artifact_requires_aart_is_optional_and_strict(self):
        from agent_artifacts.protocol.native_schema import parse_artifact_manifest

        without_bounds = _unwrap(
            parse_artifact_manifest(json.dumps(_artifact_document("skill", "aart-skill-v1")))
        )
        self.assertIsNone(without_bounds.requires_aart.min_inclusive)
        self.assertIsNone(without_bounds.requires_aart.max_exclusive)

        invalid = _artifact_document(
            "skill",
            "aart-skill-v1",
            requires_aart={"min_inclusive": "2.0.0", "max_exclusive": "1.1.0"},
        )
        self.assertEqual(
            _codes(parse_artifact_manifest(json.dumps(invalid))),
            ("protocol-version-bounds-invalid",),
        )

    def test_requires_are_canonical_unique_and_never_self_referential(self):
        from agent_artifacts.protocol.json import canonical_json_bytes
        from agent_artifacts.protocol.native_schema import (
            artifact_manifest_to_json,
            parse_artifact_manifest,
        )

        document = _artifact_document(
            "skill",
            "aart-skill-v1",
            name="residual-stage",
            requires=[
                {
                    "type": "skill",
                    "name": "using-residues",
                    "version": {"min_inclusive": "1.2.0", "max_exclusive": "2.0.0"},
                }
            ],
        )
        manifest = _unwrap(parse_artifact_manifest(json.dumps(document)))
        self.assertEqual(str(manifest.requires[0].identity), "skill/using-residues")
        self.assertEqual(
            _unwrap(
                parse_artifact_manifest(canonical_json_bytes(artifact_manifest_to_json(manifest)))
            ),
            manifest,
        )

        cases = (
            ([{"type": "skill", "name": "residual-stage"}], "artifact-invalid"),
            (
                [
                    {"type": "skill", "name": "using-residues"},
                    {"type": "skill", "name": "using-residues"},
                ],
                "artifact-invalid",
            ),
            (
                [{"type": "skill", "name": "using-residues", "unexpected": True}],
                "protocol-schema-unknown-field",
            ),
        )
        for requires, code in cases:
            with self.subTest(requires=requires):
                invalid = _artifact_document(
                    "skill", "aart-skill-v1", name="residual-stage", requires=requires
                )
                self.assertEqual(_codes(parse_artifact_manifest(json.dumps(invalid))), (code,))


if __name__ == "__main__":
    unittest.main()
