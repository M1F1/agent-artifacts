from __future__ import annotations

import unittest

from agent_artifacts.configuration.model import (
    ConfiguredSource,
    OrganizationPolicy,
    ReportingMode,
    ReportingSettings,
    SourceKind,
    SyncSettings,
    UserConfiguration,
)
from agent_artifacts.configuration.policy import EffectiveConfiguration
from agent_artifacts.domain.identifiers import SourceAlias
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.protocol.registry_models import ServiceAdvertisement
from agent_artifacts.reporting.destination import (
    configured_reporting_source,
    destination_from_services,
)


def _source(alias: str, kind: SourceKind, location: str) -> ConfiguredSource:
    return ConfiguredSource(SourceAlias(alias), kind, location, "main", True)


def _effective(mode: ReportingMode, destination: str | None) -> EffectiveConfiguration:
    sources = (
        _source("artifact-upstream", SourceKind.SOURCE_GIT, "https://github.com/other/tools.git"),
        _source(
            "company",
            SourceKind.REGISTRY_GIT,
            "git@github.company.example:agents/company-registry.git",
        ),
        _source("public", SourceKind.REGISTRY_GIT, "https://github.com/public/registry.git"),
    )
    return EffectiveConfiguration(
        UserConfiguration(
            1,
            sources,
            SourceAlias("company"),
            SyncSettings(),
            ReportingSettings(
                mode,
                None if destination is None else SourceAlias(destination),
            ),
        ),
        OrganizationPolicy(1),
        (),
    )


class ReportingDestinationTest(unittest.TestCase):
    def test_disabled_short_circuits_without_selecting_or_loading_a_registry(self) -> None:
        selected = configured_reporting_source(_effective(ReportingMode.DISABLED, None))

        assert isinstance(selected, Ok), selected
        self.assertIsNone(selected.value)

    def test_only_explicit_registry_alias_supplies_the_service_and_git_host(self) -> None:
        selected = configured_reporting_source(_effective(ReportingMode.PROMPT, "company"))
        assert isinstance(selected, Ok) and selected.value is not None, selected

        resolved = destination_from_services(
            ReportingMode.PROMPT,
            selected.value,
            (
                ServiceAdvertisement(
                    "usage_reporting",
                    "github-issues",
                    "analytics/company-usage",
                ),
            ),
        )

        assert isinstance(resolved, Ok), resolved
        self.assertEqual(resolved.value.host, "github.company.example")
        self.assertEqual(resolved.value.repository, "analytics/company-usage")

    def test_missing_unsupported_or_ambiguous_service_fails_closed(self) -> None:
        selected = configured_reporting_source(_effective(ReportingMode.AUTOMATIC, "company"))
        assert isinstance(selected, Ok) and selected.value is not None
        for services in (
            (),
            (ServiceAdvertisement("usage_reporting", "custom", "org/repo"),),
            (
                ServiceAdvertisement("usage_reporting", "github-issues", "org/one"),
                ServiceAdvertisement("usage_reporting", "github-issues", "org/two"),
            ),
        ):
            with self.subTest(services=services):
                self.assertIsInstance(
                    destination_from_services(ReportingMode.AUTOMATIC, selected.value, services),
                    Err,
                )

    def test_direct_source_or_unknown_alias_cannot_be_a_destination(self) -> None:
        for alias in ("artifact-upstream", "absent"):
            with self.subTest(alias=alias):
                self.assertIsInstance(
                    configured_reporting_source(_effective(ReportingMode.PROMPT, alias)),
                    Err,
                )


if __name__ == "__main__":
    unittest.main()
