from __future__ import annotations

import unittest
from pathlib import Path

from agent_artifacts.configuration.model import ConfiguredSource, SourceKind
from agent_artifacts.domain.identifiers import SourceAlias, SourceId
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.protocol.native_tree import SnapshotEntry, SourceSnapshot
from agent_artifacts.runtime_contract import EXECUTABLE_CAPABILITIES, EXECUTABLE_VERSION
from agent_artifacts.sources.local import read_local_snapshot
from agent_artifacts.sources.model import (
    LocalSnapshotRequest,
    SnapshotLimits,
    SourceValidationRequest,
    make_source_candidate,
    source_instance_id,
)
from agent_artifacts.sources.validation import validate_configured_source_candidate

_FIXTURE = Path(__file__).parent / "fixtures" / "protocol" / "registry-v1"


def _unwrap(result):
    assert isinstance(result, Ok), result
    return result.value


def _registry_source() -> ConfiguredSource:
    return ConfiguredSource(
        SourceAlias("reference"),
        SourceKind.REGISTRY_GIT,
        "https://github.com/example/reference-registry.git",
        "main",
        True,
    )


def _candidate(source: ConfiguredSource, root: Path = _FIXTURE):
    return _unwrap(
        read_local_snapshot(
            LocalSnapshotRequest(
                source_instance_id(source),
                source.alias,
                str(root.resolve()),
                SnapshotLimits(),
            )
        )
    )


class RegistrySourceValidationTest(unittest.TestCase):
    def test_compiled_registry_fixture_is_accepted_with_registry_identity(self) -> None:
        source = _registry_source()
        candidate = _candidate(source)

        result = validate_configured_source_candidate(
            source,
            SourceValidationRequest(candidate, EXECUTABLE_VERSION, EXECUTABLE_CAPABILITIES),
        )

        self.assertIsInstance(result, Ok)
        assert isinstance(result, Ok)
        self.assertEqual(result.value.candidate, candidate)
        self.assertEqual(result.value.declared_source_id, SourceId("reference-registry"))

    def test_registry_validator_rejects_a_missing_compiled_index(self) -> None:
        source = _registry_source()
        candidate = _candidate(source)
        snapshot = SourceSnapshot(
            candidate.snapshot.origin,
            tuple(
                entry
                for entry in candidate.snapshot.entries
                if str(entry.path) != "aart.index.json"
            ),
        )
        incomplete = _unwrap(
            make_source_candidate(
                candidate.instance_id,
                candidate.alias,
                candidate.resolved_revision,
                snapshot,
            )
        )

        result = validate_configured_source_candidate(
            source,
            SourceValidationRequest(incomplete, EXECUTABLE_VERSION, EXECUTABLE_CAPABILITIES),
        )

        self.assertIsInstance(result, Err)
        assert isinstance(result, Err)
        self.assertIn("compiled registry requires lock and index", result.diagnostics[0].message)

    def test_registry_validator_rejects_source_registry_identity_mismatch(self) -> None:
        source = _registry_source()
        candidate = _candidate(source)
        mismatched_source = b"".join(
            (
                b'{"artifact_roots":["artifacts"],"collection_roots":["collections"],',
                b'"display_name":"Reference Registry","protocol_version":1,',
                b'"required_capabilities":["artifact-manifest-v1"],',
                b'"requires_aart":{"max_exclusive":"2.0.0","min_inclusive":"1.0.0"},',
                b'"schema_version":1,"source_id":"different-registry"}',
            )
        )
        snapshot = SourceSnapshot(
            candidate.snapshot.origin,
            tuple(
                SnapshotEntry(entry.path, entry.kind, mismatched_source, entry.executable)
                if str(entry.path) == "aart-source.json"
                else entry
                for entry in candidate.snapshot.entries
            ),
        )
        mismatched = _unwrap(
            make_source_candidate(
                candidate.instance_id,
                candidate.alias,
                candidate.resolved_revision,
                snapshot,
            )
        )

        result = validate_configured_source_candidate(
            source,
            SourceValidationRequest(mismatched, EXECUTABLE_VERSION, EXECUTABLE_CAPABILITIES),
        )

        self.assertIsInstance(result, Err)
        assert isinstance(result, Err)
        self.assertIn("registry and source identities differ", result.diagnostics[0].message)


if __name__ == "__main__":
    unittest.main()
