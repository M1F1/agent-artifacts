from __future__ import annotations

import unittest

from agent_artifacts.configuration.model import (
    OrganizationPolicy,
    ReportingMode,
    ReportingSettings,
    SourceKind,
    SyncSettings,
    UserConfiguration,
)
from agent_artifacts.configuration.policy import EffectiveConfiguration
from agent_artifacts.domain.identifiers import SourceAlias, SourceId
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.reporting.runtime import reporting_destination_from_current
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
