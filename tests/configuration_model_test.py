from __future__ import annotations

import unittest

from agent_artifacts.configuration.model import (
    ConfiguredSource,
    OrganizationPolicy,
    ReportingMode,
    ReportingPolicy,
    ReportingSettings,
    SourceKind,
    SyncMode,
    SyncSettings,
    UserConfiguration,
    git_location_parts,
)
from agent_artifacts.domain.identifiers import SourceAlias


class ConfigurationModelTest(unittest.TestCase):
    def test_domain_values_reject_invalid_direct_construction(self) -> None:
        source = ConfiguredSource(
            SourceAlias("valid"), SourceKind.SOURCE_LOCAL, "/valid", None, True
        )
        invalid_constructors = (
            lambda: ConfiguredSource(SourceAlias(""), SourceKind.SOURCE_LOCAL, "/a", None, True),
            lambda: ConfiguredSource(SourceAlias("a"), "local", "/a", None, True),  # type: ignore[arg-type]
            lambda: ConfiguredSource(SourceAlias("a"), SourceKind.SOURCE_LOCAL, "/a", "main", True),
            lambda: ConfiguredSource(
                SourceAlias("a"), SourceKind.SOURCE_GIT, "https://example.test/a", None, True
            ),
            lambda: SyncSettings("auto", 1),  # type: ignore[arg-type]
            lambda: SyncSettings(SyncMode.AUTO, -1),
            lambda: SyncSettings(SyncMode.AUTO, True),
            lambda: ReportingSettings("disabled", None),  # type: ignore[arg-type]
            lambda: ReportingSettings(ReportingMode.PROMPT, None),
            lambda: ReportingSettings(ReportingMode.DISABLED, SourceAlias("")),
            lambda: UserConfiguration(2, (source,), None, SyncSettings(), ReportingSettings()),
            lambda: UserConfiguration(
                1, (source, source), None, SyncSettings(), ReportingSettings()
            ),
            lambda: ReportingPolicy("prompt"),  # type: ignore[arg-type]
            lambda: ReportingPolicy(destination=SourceAlias("")),
            lambda: ReportingPolicy(deny_public_destinations="yes"),  # type: ignore[arg-type]
            lambda: OrganizationPolicy(2),
            lambda: OrganizationPolicy(1, allow_direct_sources="yes"),  # type: ignore[arg-type]
            lambda: OrganizationPolicy(1, minimum_trust_for_user_scope="trusted-by-name"),
            lambda: OrganizationPolicy(1, reporting="prompt"),  # type: ignore[arg-type]
            lambda: OrganizationPolicy(1, allowed_setup_capabilities=("keychain",)),  # type: ignore[arg-type]
            lambda: OrganizationPolicy(
                1,
                recommended_sources=(SourceAlias("same"),),
                required_sources=(SourceAlias("same"),),
            ),
        )

        for constructor in invalid_constructors:
            with self.subTest(constructor=constructor), self.assertRaises(ValueError):
                constructor()

    def test_git_locations_are_normalized_and_credentials_are_rejected(self) -> None:
        accepted = {
            "git@GitHub.Example:agents/repo.git": ("github.example", "agents/repo"),
            "https://GitHub.Example/agents/repo.git": ("github.example", "agents/repo"),
            "ssh://git@GitHub.Example/agents/repo.git": ("github.example", "agents/repo"),
        }
        for location, expected in accepted.items():
            with self.subTest(location=location):
                self.assertEqual(git_location_parts(location), expected)

        rejected = (
            "",
            "file:///work/repo",
            "https://example.test/",
            "https://example.test/a/../b",
            "https://example.test/a//b",
            "https://example.test/a repo",
            "https://example.test/a%20repo",
            "https://example.test/a\\repo",
            "https://example.test/repo?ref=main",
            "https://example.test/repo#main",
            "https://user@example.test/repo",
            "https://user:secret@example.test/repo",
            "ssh://admin@example.test/repo",
            "https://[invalid/repo",
            "git@example.test:repo/",
        )
        for location in rejected:
            with self.subTest(location=location):
                self.assertIsNone(git_location_parts(location))


if __name__ == "__main__":
    unittest.main()
