from __future__ import annotations

import unittest

from agent_artifacts.application.sources import SourceStatusRequest, source_status
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import SourceAlias
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.sources.model import (
    CurrentSourceRequest,
    HealthStatus,
    SourceInstanceId,
    source_store_paths,
)


class SourceStatusApplicationTest(unittest.TestCase):
    def setUp(self) -> None:
        paths = source_store_paths("/managed", SourceInstanceId("local-" + "a" * 32))
        self.request = SourceStatusRequest(
            CurrentSourceRequest(paths, SourceAlias("local")),
            now_epoch_seconds=100,
            max_age_seconds=30,
        )

    def test_missing_source_has_explicit_status(self) -> None:
        health = source_status(self.request, lambda _request: Ok(None))

        self.assertIs(health.status, HealthStatus.MISSING)
        self.assertIsNone(health.current)

    def test_corrupt_durable_state_is_degraded_with_diagnostics(self) -> None:
        failure = Err(
            (
                Diagnostic(
                    DiagnosticCode("source-invalid"),
                    Severity.ERROR,
                    "current pointer is corrupt",
                ),
            )
        )

        health = source_status(self.request, lambda _request: failure)

        self.assertIs(health.status, HealthStatus.DEGRADED)
        self.assertEqual(health.diagnostics, failure.diagnostics)


if __name__ == "__main__":
    unittest.main()
