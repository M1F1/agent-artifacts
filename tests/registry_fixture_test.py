from __future__ import annotations

import unittest
from pathlib import Path

from agent_artifacts.domain.result import Ok
from agent_artifacts.protocol.capabilities import Capability
from agent_artifacts.protocol.native_tree import (
    SnapshotEntry,
    SnapshotEntryKind,
    SnapshotOrigin,
    SourceSnapshot,
    load_native_source,
)
from agent_artifacts.protocol.paths import parse_relative_path
from agent_artifacts.protocol.registry_schema import (
    parse_registry_entry,
    parse_registry_index,
    parse_registry_lock,
    parse_registry_manifest,
)
from agent_artifacts.protocol.registry_tree import (
    registry_inputs_digest,
    resolve_locked_references,
)
from agent_artifacts.protocol.semver import parse_semver

_FIXTURE = Path(__file__).parent / "fixtures" / "protocol" / "registry-v1"


def _snapshot() -> SourceSnapshot:
    entries: list[SnapshotEntry] = []
    for file_path in sorted(path for path in _FIXTURE.rglob("*") if path.is_file()):
        relative = file_path.relative_to(_FIXTURE).as_posix()
        parsed_path = parse_relative_path(relative)
        assert isinstance(parsed_path, Ok)
        entries.append(
            SnapshotEntry(
                parsed_path.value,
                SnapshotEntryKind.FILE,
                file_path.read_bytes(),
            )
        )
    return SourceSnapshot(SnapshotOrigin.LOCAL, tuple(entries))


class RegistryFixtureTest(unittest.TestCase):
    def test_documented_registry_fixture_is_native_locked_and_consumer_valid(self) -> None:
        snapshot = _snapshot()
        digest = registry_inputs_digest(snapshot)
        registry = parse_registry_manifest((_FIXTURE / "aart-registry.json").read_bytes())
        entry = parse_registry_entry((_FIXTURE / "entries" / "mcp" / "atlassian.json").read_bytes())
        lock = parse_registry_lock((_FIXTURE / "aart.lock.json").read_bytes())
        index = parse_registry_index((_FIXTURE / "aart.index.json").read_bytes())
        version = parse_semver("1.0.0")
        for result in (digest, registry, entry, lock, index, version):
            self.assertIsInstance(result, Ok)
        assert isinstance(digest, Ok)
        assert isinstance(entry, Ok)
        assert isinstance(lock, Ok)
        assert isinstance(index, Ok)
        assert isinstance(version, Ok)

        self.assertEqual(lock.value.registry_inputs_digest, digest.value)
        self.assertEqual(index.value.registry_inputs_digest, digest.value)
        resolved = resolve_locked_references(
            (entry.value,),
            lock.value,
            expected_inputs_digest=digest.value,
        )
        self.assertIsInstance(resolved, Ok)
        assert isinstance(resolved, Ok)
        self.assertEqual(resolved.value[0].resolved_commit, "a" * 40)

        native = load_native_source(
            snapshot,
            executable_version=version.value,
            available_capabilities=(Capability("artifact-manifest-v1"),),
        )
        self.assertIsInstance(native, Ok)
        assert isinstance(native, Ok)
        self.assertEqual(
            tuple(str(package.manifest.identity) for package in native.value.artifacts),
            ("skill/code-review",),
        )
        self.assertEqual(
            tuple(str(artifact.identity) for artifact in index.value.artifacts),
            ("mcp/atlassian", "skill/code-review"),
        )


if __name__ == "__main__":
    unittest.main()
