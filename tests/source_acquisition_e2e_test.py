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
from agent_artifacts.sources.model import (
    CurrentSourceRequest,
    SyncDisposition,
    SyncFallback,
    source_instance_id,
    source_store_paths,
)
from agent_artifacts.sources.runtime import resubscribe_configured_source
from agent_artifacts.sources.validation import validate_source_candidate

_FIXTURE = Path(__file__).parent / "fixtures" / "protocol" / "native-source-v1"


def _paths(source, data_root: Path):
    return source_store_paths(str(data_root), source_instance_id(source))


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
    repair is to review both identities and adopt the new one under the same alias, so no project
    manifest naming that alias is orphaned on the way through.
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

    def _republish(self, origin: Path, source_id: str) -> None:
        descriptor = origin / "aart-source.json"
        document = json.loads(descriptor.read_text(encoding="utf-8"))
        document["source_id"] = source_id
        descriptor.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    def test_a_republished_identity_is_adopted_by_resubscribing_under_the_same_alias(self) -> None:
        """SL-7: the 2026-08-13 dead end, resolved with shipped commands only.

        Nothing here hand-edits configuration or deletes a directory from the data root, which is
        exactly what the original reproduction required and what design §9 criterion 6 forbids.
        """

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
            first = sync_source(request, self._ports())
            self.assertIsInstance(first, Ok)
            assert isinstance(first, Ok)
            subscribed_id = first.value.current.declared_source_id

            self._republish(origin, "republished-native-source")

            refused = sync_source(request, self._ports())

            self.assertIsInstance(refused, Err)
            assert isinstance(refused, Err)
            self.assertIn("declared source identity", refused.diagnostics[0].message)
            self.assertIn(
                "aart source resubscribe --alias registry",
                refused.diagnostics[0].remediation[0],
            )

            reviewed = resubscribe_configured_source(
                source, data_root=str(data_root), observed_at_epoch_seconds=200
            )

            self.assertIsInstance(reviewed, Ok)
            assert isinstance(reviewed, Ok)
            self.assertFalse(reviewed.value.finalized)
            self.assertEqual(reviewed.value.transition.from_source_id, subscribed_id)
            self.assertEqual(
                reviewed.value.transition.to_source_id.value, "republished-native-source"
            )
            # Review publishes nothing: the alias is still bound to the identity it was subscribed
            # to, which is what makes the review safe to run before deciding.
            self.assertEqual(reviewed.value.current.declared_source_id, subscribed_id)

            adopted = resubscribe_configured_source(
                source,
                data_root=str(data_root),
                expected=reviewed.value.transition,
                observed_at_epoch_seconds=300,
            )

            self.assertIsInstance(adopted, Ok)
            assert isinstance(adopted, Ok)
            self.assertTrue(adopted.value.finalized)
            self.assertEqual(
                adopted.value.current.declared_source_id.value, "republished-native-source"
            )
            # The subscription itself is untouched — same alias, kind, origin, and ref — which is
            # the difference between adopting an identity and re-subscribing by hand.
            self.assertIs(request.source, source)
            self.assertIsInstance(sync_source(request, self._ports()), Ok)
            snapshots = data_root / "sources" / source_instance_id(source).value / "snapshots"
            self.assertEqual(
                [entry.name for entry in sorted(snapshots.iterdir())],
                [adopted.value.current.candidate.snapshot_digest.value],
                "adoption must replace the identity binding, not append beside it",
            )

    def test_an_identity_that_moved_again_after_the_review_is_refused(self) -> None:
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
            self.assertIsInstance(
                sync_source(self._request(source, str(data_root)), self._ports()), Ok
            )
            self._republish(origin, "reviewed-identity")
            reviewed = resubscribe_configured_source(
                source, data_root=str(data_root), observed_at_epoch_seconds=200
            )
            assert isinstance(reviewed, Ok)

            self._republish(origin, "a-third-identity")
            refused = resubscribe_configured_source(
                source,
                data_root=str(data_root),
                expected=reviewed.value.transition,
                observed_at_epoch_seconds=300,
            )

            self.assertIsInstance(refused, Err)
            assert isinstance(refused, Err)
            self.assertIn("no longer declares the identity", refused.diagnostics[0].message)
            current = read_current_source(
                CurrentSourceRequest(_paths(source, data_root), source.alias)
            )
            assert isinstance(current, Ok) and current.value is not None
            self.assertEqual(current.value.declared_source_id.value, "reference-native-source")

    def test_resubscribing_an_unchanged_identity_names_the_refresh_command(self) -> None:
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
            self.assertIsInstance(
                sync_source(self._request(source, str(data_root)), self._ports()), Ok
            )

            refused = resubscribe_configured_source(
                source, data_root=str(data_root), observed_at_epoch_seconds=200
            )

            self.assertIsInstance(refused, Err)
            assert isinstance(refused, Err)
            self.assertIn("already subscribed to", refused.diagnostics[0].message)
            self.assertIn(
                "aart source sync --alias registry", refused.diagnostics[0].remediation[0]
            )


if __name__ == "__main__":
    unittest.main()
