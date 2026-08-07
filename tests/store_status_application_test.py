from __future__ import annotations

import unittest

from agent_artifacts.application.store import object_status
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import ObjectDigest
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.store.model import (
    ObjectReadRequest,
    ObjectStatusKind,
    object_store_paths,
)


class StoreStatusApplicationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.request = ObjectReadRequest(
            object_store_paths("/managed"), ObjectDigest("sha256", "a" * 64)
        )

    def test_missing_and_degraded_statuses_are_explicit(self) -> None:
        missing = object_status(self.request, lambda _request: Ok(None))
        failure = Err(
            (Diagnostic(DiagnosticCode("digest-mismatch"), Severity.ERROR, "object is corrupt"),)
        )
        degraded = object_status(self.request, lambda _request: failure)

        self.assertIs(missing.kind, ObjectStatusKind.MISSING)
        self.assertIs(degraded.kind, ObjectStatusKind.DEGRADED)
        self.assertEqual(degraded.diagnostics, failure.diagnostics)


if __name__ == "__main__":
    unittest.main()
