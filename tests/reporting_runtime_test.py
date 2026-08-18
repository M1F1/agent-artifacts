from __future__ import annotations

import unittest
from dataclasses import replace

from agent_artifacts.configuration.model import (
    OrganizationPolicy,
    ReportingMode,
    ReportingPolicy,
    ReportingSettings,
    SourceKind,
    SyncSettings,
    UserConfiguration,
)
from agent_artifacts.configuration.policy import EffectiveConfiguration
from agent_artifacts.domain.identifiers import SourceAlias, SourceId
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.reporting.runtime import (
    _reporting_route_resolution_from_current,
    reporting_destination_from_current,
    reporting_routes_from_current,
)
from agent_artifacts.sources.model import CurrentSource, make_source_candidate, source_instance_id
from tests.marketplace_fixtures import configured_source
from tests.registry_fixture_test import _snapshot


class ReportingRuntimeTest(unittest.TestCase):
    def _effective(self, source, mode: ReportingMode) -> EffectiveConfiguration:
        return EffectiveConfiguration(
            UserConfiguration(
                1,
                (source,),
                source.alias,
                SyncSettings(),
                ReportingSettings(
                    mode,
                    None if mode is ReportingMode.DISABLED else SourceAlias("registry"),
                ),
            ),
            OrganizationPolicy(1),
            (),
        )

    def test_disabled_mode_does_not_read_a_current_source(self) -> None:
        calls = []
        source = configured_source("registry", SourceKind.REGISTRY_GIT)
        effective = self._effective(source, ReportingMode.DISABLED)

        result = reporting_destination_from_current(
            effective,
            "/managed/data",
            lambda request: calls.append(request) or Ok(None),
        )

        assert isinstance(result, Ok), result
        self.assertIsNone(result.value)
        self.assertEqual(calls, [])

    def test_configured_registry_snapshot_supplies_a_coherent_advertisement(self) -> None:
        source = configured_source(
            "registry",
            SourceKind.REGISTRY_GIT,
            location="https://github.company.example/agents/registry.git",
        )
        effective = self._effective(source, ReportingMode.PROMPT)
        snapshot = _snapshot()
        candidate = make_source_candidate(
            source_instance_id(source), source.alias, "a" * 40, snapshot
        )
        assert isinstance(candidate, Ok), candidate
        current = CurrentSource(candidate.value, SourceId("reference-registry"), 1, "/snapshot")

        result = reporting_destination_from_current(
            effective,
            "/managed/data",
            lambda _request: Ok(current),
        )

        assert isinstance(result, Ok) and result.value is not None, result
        self.assertEqual(result.value.host, "github.company.example")
        self.assertEqual(result.value.repository, "M1F1/agent-artifacts-registry")

    def test_default_prompt_discovers_each_registry_route_without_a_central_destination(
        self,
    ) -> None:
        source = configured_source(
            "registry",
            SourceKind.REGISTRY_GIT,
            location="https://github.company.example/agents/registry.git",
        )
        effective = EffectiveConfiguration(
            UserConfiguration(
                1,
                (source,),
                source.alias,
                SyncSettings(),
                ReportingSettings(ReportingMode.PROMPT),
            ),
            OrganizationPolicy(1),
            (),
        )
        candidate = make_source_candidate(
            source_instance_id(source), source.alias, "a" * 40, _snapshot()
        )
        assert isinstance(candidate, Ok), candidate
        current = CurrentSource(candidate.value, SourceId("reference-registry"), 1, "/snapshot")

        central = reporting_destination_from_current(
            effective, "/managed/data", lambda _request: Ok(current)
        )
        routes = reporting_routes_from_current(
            effective, "/managed/data", lambda _request: Ok(current)
        )

        assert isinstance(central, Ok), central
        self.assertIsNone(central.value)
        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0].source_alias, source.alias)
        self.assertEqual(routes[0].destination.repository, "M1F1/agent-artifacts-registry")

    def test_default_prompt_honors_public_destination_policy_without_reading_snapshot(self) -> None:
        source = configured_source(
            "public",
            SourceKind.REGISTRY_GIT,
            location="https://github.com/M1F1/agent-artifacts-registry.git",
        )
        effective = EffectiveConfiguration(
            UserConfiguration(
                1,
                (source,),
                source.alias,
                SyncSettings(),
                ReportingSettings(ReportingMode.PROMPT),
            ),
            OrganizationPolicy(
                1,
                reporting=ReportingPolicy(deny_public_destinations=True),
            ),
            (),
        )
        calls = []

        routes = reporting_routes_from_current(
            effective,
            "/managed/data",
            lambda request: calls.append(request) or Ok(None),
        )

        self.assertEqual(routes, ())
        self.assertEqual(calls, [])

    def test_default_prompt_retains_the_reason_a_registry_has_no_route(self) -> None:
        source = configured_source(
            "registry",
            SourceKind.REGISTRY_GIT,
            location="https://github.company.example/agents/registry.git",
        )
        effective = EffectiveConfiguration(
            UserConfiguration(
                1,
                (source,),
                source.alias,
                SyncSettings(),
                ReportingSettings(ReportingMode.PROMPT),
            ),
            OrganizationPolicy(1),
            (),
        )
        without_service = replace(
            _snapshot(),
            entries=tuple(
                replace(
                    entry,
                    content=entry.content.replace(
                        b'"services":{"usage_reporting":{"kind":"github-issues",'
                        b'"repository":"M1F1/agent-artifacts-registry"}}',
                        b'"services":{}',
                    ),
                )
                for entry in _snapshot().entries
            ),
        )
        candidate = make_source_candidate(
            source_instance_id(source), source.alias, "a" * 40, without_service
        )
        assert isinstance(candidate, Ok), candidate
        current = CurrentSource(candidate.value, SourceId("reference-registry"), 1, "/snapshot")

        routes, notices = _reporting_route_resolution_from_current(
            effective,
            "/managed/data",
            lambda _request: Ok(current),
        )

        self.assertEqual(routes, ())
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0].source_alias, source.alias)
        self.assertIn("does not advertise", notices[0].reason)

    def test_missing_or_incoherent_registry_snapshot_fails_closed(self) -> None:
        source = configured_source("registry", SourceKind.REGISTRY_GIT)
        effective = self._effective(source, ReportingMode.AUTOMATIC)
        self.assertIsInstance(
            reporting_destination_from_current(
                effective,
                "/managed/data",
                lambda _request: Ok(None),
            ),
            Err,
        )


if __name__ == "__main__":
    unittest.main()
