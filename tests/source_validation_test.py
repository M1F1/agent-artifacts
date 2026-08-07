from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_artifacts.domain.identifiers import SourceAlias, SourceId
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.protocol.capabilities import parse_capability
from agent_artifacts.protocol.semver import parse_semver
from agent_artifacts.sources.local import read_local_snapshot
from agent_artifacts.sources.model import (
    LocalSnapshotRequest,
    SnapshotLimits,
    SourceInstanceId,
    SourceValidationRequest,
)
from agent_artifacts.sources.validation import validate_source_candidate

_FIXTURE = Path(__file__).parent / "fixtures" / "protocol" / "native-source-v1"


def _unwrap(result):
    assert isinstance(result, Ok), result
    return result.value


def _candidate(root: Path = _FIXTURE):
    return _unwrap(
        read_local_snapshot(
            LocalSnapshotRequest(
                SourceInstanceId("local-" + "a" * 32),
                SourceAlias("reference"),
                str(root.resolve()),
                SnapshotLimits(),
            )
        )
    )


class SourceValidationTest(unittest.TestCase):
    def test_reference_native_source_is_accepted_with_declared_identity(self) -> None:
        request = SourceValidationRequest(
            _candidate(),
            _unwrap(parse_semver("1.0.0")),
            (_unwrap(parse_capability("artifact-manifest-v1")),),
        )

        result = validate_source_candidate(request)

        self.assertIsInstance(result, Ok)
        assert isinstance(result, Ok)
        self.assertEqual(result.value.candidate, request.candidate)
        self.assertEqual(result.value.declared_source_id, SourceId("reference-native-source"))

    def test_incompatible_version_or_capability_never_returns_validated_candidate(self) -> None:
        candidate = _candidate()
        requests = (
            SourceValidationRequest(candidate, _unwrap(parse_semver("2.0.0")), ()),
            SourceValidationRequest(candidate, _unwrap(parse_semver("1.0.0")), ()),
        )

        for request in requests:
            with self.subTest(request=request):
                result = validate_source_candidate(request)
                self.assertIsInstance(result, Err)
                assert isinstance(result, Err)
                self.assertEqual(result.diagnostics[0].code.value, "source-incompatible")

    def test_corrupt_source_marker_is_rejected_without_mutating_acquired_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            marker = Path(root) / "aart-source.json"
            marker.write_bytes(b'{"schema_version":1,"token":"secret"')
            candidate = _candidate(Path(root))
            before = candidate.snapshot

            result = validate_source_candidate(
                SourceValidationRequest(candidate, _unwrap(parse_semver("1.0.0")), ())
            )

            self.assertIsInstance(result, Err)
            self.assertEqual(candidate.snapshot, before)
            assert isinstance(result, Err)
            self.assertNotIn("secret", repr(result.diagnostics))


if __name__ == "__main__":
    unittest.main()
