from __future__ import annotations

import unittest

from agent_artifacts.configuration.model import (
    ReportingMode,
    SourceKind,
    SyncMode,
)
from agent_artifacts.configuration.schema import (
    organization_policy_bytes,
    parse_organization_policy,
    parse_user_configuration,
    user_configuration_bytes,
)
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.protocol.capabilities import Capability


class ConfigurationSchemaTest(unittest.TestCase):
    def test_minimal_configuration_allows_zero_sources_and_no_registry(self) -> None:
        result = parse_user_configuration('{"schema_version":1}')
        explicit_null = parse_user_configuration(
            '{"schema_version":1,"sources":[],"default_registry":null}'
        )

        self.assertIsInstance(result, Ok)
        assert isinstance(result, Ok)
        self.assertEqual(result.value.sources, ())
        self.assertIsNone(result.value.default_registry)
        self.assertIs(result.value.sync.mode, SyncMode.AUTO)
        self.assertEqual(result.value.sync.max_age_seconds, 900)
        self.assertIs(result.value.reporting.mode, ReportingMode.PROMPT)
        self.assertIsNone(result.value.reporting.destination)
        self.assertEqual(
            parse_user_configuration(user_configuration_bytes(result.value)),
            result,
        )
        self.assertEqual(explicit_null, result)

    def test_all_source_kinds_and_optional_default_registry_round_trip(self) -> None:
        result = parse_user_configuration(
            """{
              "schema_version": 1,
              "sources": [
                {"alias":"company","kind":"registry-git","url":"git@github.company.example:agents/registry.git","ref":"main","enabled":true},
                {"alias":"public","kind":"source-git","url":"https://github.com/example/artifacts.git","ref":"v1","enabled":true},
                {"alias":"local-dev","kind":"source-local","path":"/work/artifacts","enabled":false}
              ],
              "default_registry": "company",
              "sync": {"mode":"manual","max_age_seconds":42},
              "reporting": {"mode":"prompt","destination":"company"}
            }"""
        )

        self.assertIsInstance(result, Ok)
        assert isinstance(result, Ok)
        self.assertEqual(
            tuple(source.kind for source in result.value.sources),
            (SourceKind.REGISTRY_GIT, SourceKind.SOURCE_LOCAL, SourceKind.SOURCE_GIT),
        )
        self.assertEqual(str(result.value.default_registry), "company")
        self.assertEqual(
            parse_user_configuration(user_configuration_bytes(result.value)),
            result,
        )

    def test_user_configuration_rejects_ambiguous_or_unsafe_values(self) -> None:
        cases = (
            "{}",
            '{"schema_version":2}',
            '{"schema_version":1,"unknown":true}',
            '{"schema_version":1,"sources":[{"alias":"same","kind":"source-local","path":"/a","enabled":true},{"alias":"same","kind":"source-local","path":"/b","enabled":true}]}',
            # SRC02: two refs of one origin are legitimate; the same origin at the *same* ref,
            # including across equivalent transport spellings, still collides on one pointer.
            '{"schema_version":1,"sources":[{"alias":"main","kind":"source-git","url":"https://example.test/team/artifacts.git","ref":"main","enabled":true},{"alias":"duplicate","kind":"source-git","url":"git@EXAMPLE.test:team/artifacts","ref":"main","enabled":true}]}',
            '{"schema_version":1,"sources":[{"alias":"local","kind":"source-local","path":"relative","enabled":true}]}',
            '{"schema_version":1,"sources":[{"alias":"secret","kind":"source-git","url":"https://user:token@example.test/repo.git","ref":"main","enabled":true}]}',
            '{"schema_version":1,"sources":[{"alias":"git","kind":"source-git","url":"https://example.test/repo.git","ref":"bad ref","enabled":true}]}',
            '{"schema_version":1,"sources":[{"alias":"direct","kind":"source-git","url":"https://example.test/repo.git","ref":"main","enabled":true}],"default_registry":"direct"}',
            '{"schema_version":1,"reporting":{"mode":"automatic"}}',
        )
        for document in cases:
            with self.subTest(document=document):
                self.assertIsInstance(parse_user_configuration(document), Err)

    def test_user_configuration_strict_type_and_nested_field_matrix(self) -> None:
        invalid = (
            "[]",
            '{"schema_version":true}',
            '{"schema_version":1,"sources":{}}',
            '{"schema_version":1,"sources":[1]}',
            '{"schema_version":1,"sources":[{"alias":"a","enabled":true,"url":"https://example.test/a"}]}',
            '{"schema_version":1,"sources":[{"alias":"a","kind":"unknown","enabled":true,"url":"https://example.test/a"}]}',
            '{"schema_version":1,"sources":[{"alias":"Bad_Alias","kind":"source-local","path":"/a","enabled":true}]}',
            '{"schema_version":1,"sources":[{"alias":"a","kind":"source-local","path":"/a","enabled":"yes"}]}',
            '{"schema_version":1,"sources":[{"alias":"a","kind":"source-local","path":1,"enabled":true}]}',
            '{"schema_version":1,"sources":[{"alias":"a","kind":"source-local","path":"/a","enabled":true,"url":"https://example.test/a"}]}',
            '{"schema_version":1,"sources":[{"alias":"a","kind":"source-git","url":1,"enabled":true}]}',
            '{"schema_version":1,"sources":[{"alias":"a","kind":"source-git","url":"https://example.test/a","ref":1,"enabled":true}]}',
            '{"schema_version":1,"sync":1}',
            '{"schema_version":1,"sync":{"unknown":1}}',
            '{"schema_version":1,"sync":{"mode":"sometimes"}}',
            '{"schema_version":1,"sync":{"max_age_seconds":"soon"}}',
            '{"schema_version":1,"sync":{"max_age_seconds":-1}}',
            '{"schema_version":1,"reporting":1}',
            '{"schema_version":1,"reporting":{"unknown":1}}',
            '{"schema_version":1,"reporting":{"mode":"sometimes"}}',
            '{"schema_version":1,"reporting":{"destination":"Bad_Alias"}}',
            '{"schema_version":1,"default_registry":"Bad_Alias"}',
            '{"schema_version":1,"sources":[{"alias":"disabled","kind":"registry-git","url":"https://example.test/a","enabled":false}],"default_registry":"disabled"}',
            '{"schema_version":1,"reporting":{"mode":"prompt","destination":"missing"}}',
        )

        for document in invalid:
            with self.subTest(document=document):
                self.assertIsInstance(parse_user_configuration(document), Err)

    def test_git_ref_default_and_ssh_location_are_canonical(self) -> None:
        parsed = parse_user_configuration(
            '{"schema_version":1,"sources":[{"alias":"ssh","kind":"source-git","url":"ssh://git@example.test/team/repo.git","enabled":true}]}'
        )

        self.assertIsInstance(parsed, Ok)
        assert isinstance(parsed, Ok)
        self.assertEqual(parsed.value.sources[0].ref, "main")
        self.assertEqual(parse_user_configuration(user_configuration_bytes(parsed.value)), parsed)

    def test_organization_policy_is_optional_strict_and_canonical(self) -> None:
        minimal = parse_organization_policy('{"schema_version":1}')
        full = parse_organization_policy(
            """{
              "schema_version": 1,
              "recommended_sources": ["company"],
              "required_sources": [],
              "allowed_git_hosts": ["github.company.example"],
              "allowed_repository_prefixes": ["agents/", "platform/"],
              "allow_direct_sources": false,
              "minimum_trust_for_user_scope": "direct-source",
              "allowed_setup_capabilities": ["managed-file", "keychain"],
              "allow_custom_setup_entrypoints": false,
              "reporting": {"mode":"prompt","destination":"company","deny_public_destinations":true}
            }"""
        )

        self.assertIsInstance(minimal, Ok)
        self.assertIsInstance(full, Ok)
        assert isinstance(full, Ok)
        self.assertEqual(
            full.value.allowed_setup_capabilities,
            (Capability("keychain"), Capability("managed-file")),
        )
        self.assertEqual(
            parse_organization_policy(organization_policy_bytes(full.value)),
            full,
        )

        invalid = (
            '{"schema_version":1,"allowed_git_hosts":["https://github.example"]}',
            '{"schema_version":1,"allowed_repository_prefixes":["../agents/"]}',
            '{"schema_version":1,"recommended_sources":["same"],"required_sources":["same"]}',
            '{"schema_version":1,"reporting":{"deny_public_destinations":"yes"}}',
        )
        for document in invalid:
            with self.subTest(document=document):
                self.assertIsInstance(parse_organization_policy(document), Err)

    def test_organization_policy_strict_type_matrix(self) -> None:
        invalid = (
            "[]",
            "{}",
            '{"schema_version":true}',
            '{"schema_version":2}',
            '{"schema_version":1,"unknown":true}',
            '{"schema_version":1,"recommended_sources":1}',
            '{"schema_version":1,"recommended_sources":["Bad_Alias"]}',
            '{"schema_version":1,"required_sources":["same","same"]}',
            '{"schema_version":1,"allowed_git_hosts":1}',
            '{"schema_version":1,"allowed_git_hosts":[1]}',
            '{"schema_version":1,"allowed_repository_prefixes":1}',
            '{"schema_version":1,"allow_direct_sources":"yes"}',
            '{"schema_version":1,"allow_custom_setup_entrypoints":"yes"}',
            '{"schema_version":1,"minimum_trust_for_user_scope":1}',
            '{"schema_version":1,"minimum_trust_for_user_scope":"trusted-by-name"}',
            '{"schema_version":1,"allowed_setup_capabilities":1}',
            '{"schema_version":1,"allowed_setup_capabilities":[1]}',
            '{"schema_version":1,"allowed_setup_capabilities":["Bad Capability"]}',
            '{"schema_version":1,"reporting":1}',
            '{"schema_version":1,"reporting":{"unknown":true}}',
            '{"schema_version":1,"reporting":{"mode":"sometimes"}}',
            '{"schema_version":1,"reporting":{"destination":"Bad_Alias"}}',
        )
        for document in invalid:
            with self.subTest(document=document):
                self.assertIsInstance(parse_organization_policy(document), Err)

    def test_policy_normalizes_duplicate_constraints_and_accepts_trust_classes(self) -> None:
        for trust in (
            "unverified",
            "local",
            "direct-source",
            "registry-reviewed",
            "company-reviewed",
        ):
            document = (
                '{"schema_version":1,"allowed_git_hosts":["EXAMPLE.TEST","example.test"],'
                '"allowed_repository_prefixes":["team/","team/"],'
                f'"minimum_trust_for_user_scope":"{trust}"}}'
            )
            parsed = parse_organization_policy(document)
            self.assertIsInstance(parsed, Ok)
            assert isinstance(parsed, Ok)
            self.assertEqual(parsed.value.allowed_git_hosts, ("example.test",))
            self.assertEqual(parsed.value.allowed_repository_prefixes, ("team/",))


if __name__ == "__main__":
    unittest.main()
