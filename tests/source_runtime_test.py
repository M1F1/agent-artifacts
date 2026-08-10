from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_artifacts.configuration.model import ConfiguredSource, SourceKind
from agent_artifacts.domain.identifiers import SourceAlias
from agent_artifacts.domain.result import Ok
from agent_artifacts.sources.model import SyncDisposition
from agent_artifacts.sources.runtime import sync_configured_source

_FIXTURE = Path(__file__).parent / "fixtures" / "protocol" / "native-source-v1"


class SourceRuntimeTest(unittest.TestCase):
    def test_local_source_sync_publishes_current_snapshot_without_configuration_write(self) -> None:
        source = ConfiguredSource(
            SourceAlias("reference"),
            SourceKind.SOURCE_LOCAL,
            str(_FIXTURE.resolve()),
            None,
            True,
        )
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            data_root = root / "data"
            configuration_file = root / "config.json"

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


if __name__ == "__main__":
    unittest.main()
