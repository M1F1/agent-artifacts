from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from shutil import copytree

from agent_artifacts.configuration.model import ConfiguredSource, SourceKind, SyncMode
from agent_artifacts.domain.identifiers import SourceAlias
from agent_artifacts.domain.result import Ok
from agent_artifacts.sources.model import HealthStatus, SyncDisposition
from agent_artifacts.sources.runtime import observe_configured_source, sync_configured_source

_FIXTURE = Path(__file__).parent / "fixtures" / "protocol" / "native-source-v1"


class SourceRuntimeTest(unittest.TestCase):
    def test_local_source_sync_publishes_current_snapshot_without_configuration_write(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            data_root = root / "data"
            configuration_file = root / "config.json"
            source_root = root / "source"
            copytree(_FIXTURE, source_root)
            source = ConfiguredSource(
                SourceAlias("reference"),
                SourceKind.SOURCE_LOCAL,
                str(source_root),
                None,
                True,
            )

            first = sync_configured_source(
                source,
                data_root=str(data_root),
                observed_at_epoch_seconds=100,
            )
            second = sync_configured_source(
                source,
                data_root=str(data_root),
                observed_at_epoch_seconds=101,
            )

            self.assertIsInstance(first, Ok)
            self.assertIsInstance(second, Ok)
            assert isinstance(first, Ok)
            assert isinstance(second, Ok)
            self.assertIs(first.value.disposition, SyncDisposition.PUBLISHED)
            self.assertIs(second.value.disposition, SyncDisposition.UNCHANGED)
            self.assertEqual(
                first.value.current.declared_source_id.value, "reference-native-source"
            )
            self.assertTrue(Path(first.value.current.snapshot_root).is_dir())
            self.assertFalse(configuration_file.exists())

            # Age is informational: an old publication that still equals its origin is current.
            old_but_current = observe_configured_source(
                source,
                data_root=str(data_root),
                mode=SyncMode.MANUAL,
                observed_at_epoch_seconds=10_000,
            )
            self.assertIs(old_but_current.status, HealthStatus.HEALTHY)

            collection = source_root / "collections" / "essentials.json"
            collection.write_text(collection.read_text() + "\n")
            manual = observe_configured_source(
                source,
                data_root=str(data_root),
                mode=SyncMode.MANUAL,
                observed_at_epoch_seconds=10_001,
            )
            self.assertIs(manual.status, HealthStatus.NOT_SYNCHRONIZED)
            self.assertEqual(manual.current, second.value.current)

            automatic = observe_configured_source(
                source,
                data_root=str(data_root),
                mode=SyncMode.AUTO,
                observed_at_epoch_seconds=10_002,
            )
            self.assertIs(automatic.status, HealthStatus.HEALTHY)
            self.assertNotEqual(
                automatic.current.candidate.snapshot_digest,
                second.value.current.candidate.snapshot_digest,
            )

            third = sync_configured_source(
                source,
                data_root=str(data_root),
                observed_at_epoch_seconds=10_003,
            )
            self.assertIsInstance(third, Ok)
            assert isinstance(third, Ok)
            self.assertIs(third.value.disposition, SyncDisposition.UNCHANGED)


if __name__ == "__main__":
    unittest.main()
