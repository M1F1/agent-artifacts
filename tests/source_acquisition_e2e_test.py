from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from agent_artifacts.application.sources import SourceSyncPorts, SourceSyncRequest, sync_source
from agent_artifacts.configuration.model import ConfiguredSource, SourceKind
from agent_artifacts.domain.identifiers import SourceAlias
from agent_artifacts.domain.result import Err, Ok
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
from agent_artifacts.sources.runtime import discard_configured_source
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


class SourceIdentityChangeRecoveryTest(unittest.TestCase):
    """SL-7: the dead end an origin re-declaring its identity used to create, and its way out.

    A republished registry that changes ``source_id`` makes every sync of the old subscription
    refuse: the managed snapshot still binds the origin to the identity it used to declare.  The
    only correct repair is to end the subscription — snapshot included — and subscribe again.
    """

    def _ports(self) -> SourceSyncPorts:
        return SourceSyncPorts(
            acquire_source_lock,
            release_source_lock,
            read_current_source,
            read_local_snapshot,
            acquire_git_snapshot,
            validate_source_candidate,
            publish_source_snapshot,
        )

    def _request(self, source: ConfiguredSource, data_root: str) -> SourceSyncRequest:
        return SourceSyncRequest(
            source,
            data_root,
            _unwrap(parse_semver("1.0.0")),
            (_unwrap(parse_capability("artifact-manifest-v1")),),
            observed_at_epoch_seconds=100,
            fallback=SyncFallback.REQUIRE_FRESH,
            offline=False,
            timeout_seconds=30,
        )

    def test_a_republished_identity_refuses_until_the_subscription_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            origin = root / "origin"
            shutil.copytree(_FIXTURE, origin)
            data_root = root / "data"
            data_root.mkdir()
            source = ConfiguredSource(
                SourceAlias("registry"),
                SourceKind.SOURCE_LOCAL,
                str(origin.resolve()),
                None,
                True,
            )
            request = self._request(source, str(data_root))
            self.assertIsInstance(sync_source(request, self._ports()), Ok)

            descriptor = origin / "aart-source.json"
            document = json.loads(descriptor.read_text(encoding="utf-8"))
            document["source_id"] = "republished-native-source"
            descriptor.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

            refused = sync_source(request, self._ports())

            self.assertIsInstance(refused, Err)
            assert isinstance(refused, Err)
            self.assertIn("declared source identity", refused.diagnostics[0].message)
            self.assertIn(
                "aart source remove --alias registry",
                refused.diagnostics[0].remediation[0],
            )

            discarded = discard_configured_source(source, data_root=str(data_root))

            self.assertIsInstance(discarded, Ok)
            assert isinstance(discarded, Ok)
            self.assertTrue(discarded.value.existed)

            resubscribed = sync_source(request, self._ports())

            self.assertIsInstance(resubscribed, Ok)
            assert isinstance(resubscribed, Ok)
            self.assertIs(resubscribed.value.disposition, SyncDisposition.PUBLISHED)
            self.assertEqual(
                resubscribed.value.current.declared_source_id.value,
                "republished-native-source",
            )


if __name__ == "__main__":
    unittest.main()
