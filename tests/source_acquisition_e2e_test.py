from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_artifacts.application.sources import SourceSyncPorts, SourceSyncRequest, sync_source
from agent_artifacts.configuration.model import ConfiguredSource, SourceKind
from agent_artifacts.domain.identifiers import SourceAlias
from agent_artifacts.domain.result import Ok
from agent_artifacts.io.source_store import (
    acquire_source_lock,
    publish_source_snapshot,
    read_current_source,
    release_source_lock,
)
from agent_artifacts.protocol.capabilities import parse_capability
from agent_artifacts.protocol.semver import parse_semver
from agent_artifacts.sources.git import acquire_git_snapshot
from agent_artifacts.sources.local import read_local_snapshot
from agent_artifacts.sources.model import SyncDisposition, SyncFallback
from agent_artifacts.sources.validation import validate_source_candidate

_FIXTURE = Path(__file__).parent / "fixtures" / "protocol" / "native-source-v1"


def _unwrap(result):
    assert isinstance(result, Ok), result
    return result.value


class SourceAcquisitionE2ETest(unittest.TestCase):
    def test_local_source_sync_validates_publishes_rereads_and_becomes_unchanged(self) -> None:
        ports = SourceSyncPorts(
            acquire_source_lock,
            release_source_lock,
            read_current_source,
            read_local_snapshot,
            acquire_git_snapshot,
            validate_source_candidate,
            publish_source_snapshot,
        )
        source = ConfiguredSource(
            SourceAlias("reference"),
            SourceKind.SOURCE_LOCAL,
            str(_FIXTURE.resolve()),
            None,
            True,
        )
        with tempfile.TemporaryDirectory() as data_root:
            request = SourceSyncRequest(
                source,
                data_root,
                _unwrap(parse_semver("1.0.0")),
                (_unwrap(parse_capability("artifact-manifest-v1")),),
                observed_at_epoch_seconds=100,
                fallback=SyncFallback.REQUIRE_FRESH,
                offline=False,
                timeout_seconds=30,
            )

            first = sync_source(request, ports)
            second = sync_source(request, ports)

            self.assertIsInstance(first, Ok)
            self.assertIsInstance(second, Ok)
            assert isinstance(first, Ok)
            assert isinstance(second, Ok)
            self.assertIs(first.value.disposition, SyncDisposition.PUBLISHED)
            self.assertIs(second.value.disposition, SyncDisposition.UNCHANGED)
            self.assertEqual(first.value.current, second.value.current)
            self.assertEqual(
                first.value.current.declared_source_id.value, "reference-native-source"
            )
            self.assertTrue(Path(first.value.current.snapshot_root).is_dir())


if __name__ == "__main__":
    unittest.main()
