from __future__ import annotations

import unittest

from agent_artifacts.configuration.model import ConfiguredSource, SourceKind
from agent_artifacts.configuration.schema import (
    configured_source_from_input,
    validate_configured_source,
)
from agent_artifacts.domain.identifiers import SourceAlias
from agent_artifacts.domain.result import Err, Ok
from tests.credential_fixtures import credential_url


class ConfiguredSourceFromInputTest(unittest.TestCase):
    def test_accepts_registry_direct_and_local_sources(self) -> None:
        registry = configured_source_from_input(
            "company-registry",
            SourceKind.REGISTRY_GIT,
            "https://github.example/company/agent-artifacts-registry.git",
        )
        direct = configured_source_from_input(
            "team-artifacts",
            SourceKind.SOURCE_GIT,
            "git@git.example:team/agent-artifacts.git",
            "release/1.0",
        )
        local = configured_source_from_input(
            "local-dev",
            SourceKind.SOURCE_LOCAL,
            "/work/agent-artifacts",
        )

        for result in (registry, direct, local):
            self.assertIsInstance(result, Ok)

        assert isinstance(registry, Ok)
        assert isinstance(direct, Ok)
        assert isinstance(local, Ok)
        self.assertEqual(registry.value.alias.value, "company-registry")
        self.assertEqual(registry.value.ref, "main")
        self.assertEqual(direct.value.ref, "release/1.0")
        self.assertIsNone(local.value.ref)
        self.assertTrue(all(result.value.enabled for result in (registry, direct, local)))

    def test_rejects_invalid_alias_credential_url_unsafe_ref_and_relative_local_path(self) -> None:
        invalid = (
            configured_source_from_input(
                "Bad_Alias", SourceKind.REGISTRY_GIT, "https://github.example/company/registry.git"
            ),
            configured_source_from_input(
                "secret",
                SourceKind.SOURCE_GIT,
                credential_url("git.example", "/team/artifacts.git", held="token"),
            ),
            configured_source_from_input(
                "unsafe-ref",
                SourceKind.SOURCE_GIT,
                "https://git.example/team/artifacts.git",
                "--upload-pack=evil",
            ),
            configured_source_from_input("relative", SourceKind.SOURCE_LOCAL, "artifacts"),
        )

        for result in invalid:
            self.assertIsInstance(result, Err)

    def test_validates_existing_source_without_losing_its_enabled_state(self) -> None:
        source = ConfiguredSource(
            SourceAlias("disabled"),
            SourceKind.SOURCE_GIT,
            "https://git.example/team/artifacts.git",
            "main",
            False,
        )

        validated = validate_configured_source(source)

        self.assertIsInstance(validated, Ok)
        assert isinstance(validated, Ok)
        self.assertEqual(validated.value, source)

        unsafe = ConfiguredSource(
            SourceAlias("secret"),
            SourceKind.SOURCE_GIT,
            credential_url("git.example", "/team/artifacts.git", held="token"),
            "main",
            True,
        )
        self.assertIsInstance(validate_configured_source(unsafe), Err)


if __name__ == "__main__":
    unittest.main()
