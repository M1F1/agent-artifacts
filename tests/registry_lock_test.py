from __future__ import annotations

import json
import unittest
from dataclasses import replace
from typing import cast

from agent_artifacts.domain.identifiers import ArtifactIdentity
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.protocol.native_tree import (
    SnapshotEntry,
    SnapshotEntryKind,
    SnapshotOrigin,
    SourceSnapshot,
)
from agent_artifacts.protocol.paths import SafeRelativePath, parse_relative_path
from agent_artifacts.protocol.registry_schema import parse_registry_entry, parse_registry_lock
from agent_artifacts.protocol.registry_tree import (
    registry_inputs_digest,
    resolve_locked_references,
)


def _path(raw: str):
    result = parse_relative_path(raw)
    assert isinstance(result, Ok)
    return result.value


def _file(path: str, content: str, *, executable: bool = False) -> SnapshotEntry:
    return SnapshotEntry(_path(path), SnapshotEntryKind.FILE, content.encode(), executable)


def _directory(path: str) -> SnapshotEntry:
    return SnapshotEntry(_path(path), SnapshotEntryKind.DIRECTORY)


def _digest(character: str) -> str:
    return f"sha256:{character * 64}"


def _entry_document(*, ref: str = "main") -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "type": "mcp",
            "name": "atlassian",
            "source": {
                "kind": "git",
                "url": "https://github.example/platform/atlassian-tools.git",
                "ref": ref,
                "path": "artifacts/mcp/atlassian",
            },
            "review": {"status": "approved", "policy": "review-v1"},
        }
    )


def _lock_document(inputs_digest: str, *, requested_ref: str = "main") -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "registry_inputs_digest": inputs_digest,
            "entries": {
                "mcp/atlassian": {
                    "origin_url": "https://github.example/platform/atlassian-tools.git",
                    "requested_ref": requested_ref,
                    "resolved_commit": "a" * 40,
                    "path": "artifacts/mcp/atlassian",
                    "manifest_digest": _digest("1"),
                    "payload_digest": _digest("2"),
                    "object_digest": _digest("3"),
                    "artifact_version": "2.1.0",
                    "review": {"status": "approved", "policy": "review-v1"},
                }
            },
        }
    )


def _snapshot(*extra: SnapshotEntry) -> SourceSnapshot:
    return SourceSnapshot(
        SnapshotOrigin.LOCAL,
        (
            _file("aart-registry.json", '{"schema_version":1,"registry_id":"registry"}'),
            _file("entries/mcp/atlassian.json", _entry_document()),
            _file("artifacts/skill/code-review/artifact.json", '{"schema_version":1}'),
            _file("artifacts/skill/code-review/payload/SKILL.md", "# Review\n"),
            _file("collections/essentials.json", '{"schema_version":1}'),
            *extra,
        ),
    )


class RegistryLockTest(unittest.TestCase):
    def test_inputs_digest_is_origin_and_directory_representation_independent(self) -> None:
        local = _snapshot()
        git = SourceSnapshot(
            SnapshotOrigin.IMMUTABLE_GIT,
            (*local.entries, _directory("entries"), _directory("artifacts/skill")),
        )

        local_result = registry_inputs_digest(local)
        git_result = registry_inputs_digest(git)

        self.assertIsInstance(local_result, Ok)
        self.assertEqual(local_result, git_result)

    def test_inputs_digest_excludes_generated_lock_index_and_unrelated_repo_files(self) -> None:
        baseline = registry_inputs_digest(_snapshot())
        with_outputs = registry_inputs_digest(
            _snapshot(
                _file("aart.lock.json", '{"generated":"one"}'),
                _file("aart.index.json", '{"generated":"two"}'),
                _file("src/application.py", "unrelated"),
            )
        )

        self.assertEqual(baseline, with_outputs)

    def test_inputs_digest_canonicalizes_json_but_binds_payload_and_review(self) -> None:
        ordered = registry_inputs_digest(_snapshot())
        reordered = SourceSnapshot(
            SnapshotOrigin.LOCAL,
            tuple(
                _file(str(entry.path), json.dumps(json.loads(entry.content), sort_keys=True))
                if entry.kind is SnapshotEntryKind.FILE and str(entry.path).endswith(".json")
                else entry
                for entry in _snapshot().entries
            ),
        )
        changed_payload = registry_inputs_digest(
            _snapshot(_file("artifacts/skill/code-review/payload/EXTRA.md", "changed\n"))
        )

        self.assertEqual(ordered, registry_inputs_digest(reordered))
        self.assertNotEqual(ordered, changed_payload)

    def test_inputs_digest_rejects_links_or_special_files_in_registry_content(self) -> None:
        for kind in (SnapshotEntryKind.SYMLINK, SnapshotEntryKind.SPECIAL):
            with self.subTest(kind=kind):
                snapshot = _snapshot(SnapshotEntry(_path("entries/unsafe"), kind))
                self.assertIsInstance(registry_inputs_digest(snapshot), Err)

    def test_inputs_digest_rejects_invalid_snapshot_boundaries_and_json(self) -> None:
        cases = (
            SourceSnapshot(cast(SnapshotOrigin, "mutable-git"), _snapshot().entries),
            SourceSnapshot(
                SnapshotOrigin.LOCAL,
                (_file("aart-registry.json", "{}"), _file("aart-registry.json", "{}")),
            ),
            SourceSnapshot(
                SnapshotOrigin.LOCAL,
                (
                    SnapshotEntry(
                        SafeRelativePath(("entries", "..", "bad")),
                        SnapshotEntryKind.FILE,
                        b"{}",
                    ),
                ),
            ),
            SourceSnapshot(
                SnapshotOrigin.LOCAL,
                (
                    _file("aart-registry.json", "{}"),
                    SnapshotEntry(
                        _path("entries/bad"),
                        cast(SnapshotEntryKind, "unknown"),
                    ),
                ),
            ),
            SourceSnapshot(
                SnapshotOrigin.LOCAL,
                (
                    _file("aart-registry.json", "{}"),
                    SnapshotEntry(
                        _path("entries/bad"),
                        SnapshotEntryKind.FILE,
                        cast(bytes, "not-bytes"),
                    ),
                ),
            ),
            SourceSnapshot(SnapshotOrigin.LOCAL, (_file("README.md", "unrelated"),)),
            SourceSnapshot(
                SnapshotOrigin.LOCAL,
                (_file("aart-registry.json", "{"),),
            ),
        )
        for snapshot in cases:
            with self.subTest(snapshot=snapshot):
                self.assertIsInstance(registry_inputs_digest(snapshot), Err)

    def test_consumer_resolution_uses_committed_lock_not_moving_ref(self) -> None:
        digest_result = registry_inputs_digest(_snapshot())
        self.assertIsInstance(digest_result, Ok)
        assert isinstance(digest_result, Ok)
        entry = parse_registry_entry(_entry_document(ref="main"))
        lock = parse_registry_lock(_lock_document(str(digest_result.value)))
        assert isinstance(entry, Ok)
        assert isinstance(lock, Ok)

        resolved = resolve_locked_references(
            (entry.value,), lock.value, expected_inputs_digest=digest_result.value
        )

        self.assertIsInstance(resolved, Ok)
        assert isinstance(resolved, Ok)
        self.assertEqual(resolved.value[0].resolved_commit, "a" * 40)
        self.assertEqual(resolved.value[0].identity, ArtifactIdentity("mcp", "atlassian"))

    def test_stale_mismatched_or_self_referential_lock_never_resolves(self) -> None:
        digest_result = registry_inputs_digest(_snapshot())
        assert isinstance(digest_result, Ok)
        entry = parse_registry_entry(_entry_document())
        assert isinstance(entry, Ok)
        stale_lock = parse_registry_lock(_lock_document(_digest("f")))
        wrong_ref_lock = parse_registry_lock(
            _lock_document(str(digest_result.value), requested_ref="release")
        )
        valid_lock = parse_registry_lock(_lock_document(str(digest_result.value)))
        assert isinstance(stale_lock, Ok)
        assert isinstance(wrong_ref_lock, Ok)
        assert isinstance(valid_lock, Ok)

        self.assertIsInstance(
            resolve_locked_references(
                (entry.value,), stale_lock.value, expected_inputs_digest=digest_result.value
            ),
            Err,
        )
        different_case_path = "https://GITHUB.EXAMPLE/platform/Atlassian-Tools.git"
        self.assertIsInstance(
            resolve_locked_references(
                (entry.value,),
                valid_lock.value,
                expected_inputs_digest=digest_result.value,
                registry_origin_url=different_case_path,
            ),
            Ok,
        )
        self.assertIsInstance(
            resolve_locked_references(
                (entry.value,), wrong_ref_lock.value, expected_inputs_digest=digest_result.value
            ),
            Err,
        )
        self.assertIsInstance(
            resolve_locked_references(
                (entry.value,),
                valid_lock.value,
                expected_inputs_digest=digest_result.value,
                registry_origin_url="https://github.example/platform/atlassian-tools.git",
            ),
            Err,
        )

    def test_duplicate_missing_and_unapproved_references_never_resolve(self) -> None:
        digest_result = registry_inputs_digest(_snapshot())
        assert isinstance(digest_result, Ok)
        entry = parse_registry_entry(_entry_document())
        lock = parse_registry_lock(_lock_document(str(digest_result.value)))
        assert isinstance(entry, Ok)
        assert isinstance(lock, Ok)

        self.assertIsInstance(
            resolve_locked_references(
                (entry.value, entry.value),
                lock.value,
                expected_inputs_digest=digest_result.value,
            ),
            Err,
        )
        self.assertIsInstance(
            resolve_locked_references(
                (entry.value,),
                replace(lock.value, entries=()),
                expected_inputs_digest=digest_result.value,
            ),
            Err,
        )
        pending_review = replace(entry.value.review, status="pending")
        pending_entry = replace(entry.value, review=pending_review)
        pending_locked = replace(lock.value.entries[0][1], review=pending_review)
        pending_lock = replace(lock.value, entries=((entry.value.identity, pending_locked),))
        self.assertIsInstance(
            resolve_locked_references(
                (pending_entry,),
                pending_lock,
                expected_inputs_digest=digest_result.value,
            ),
            Err,
        )


if __name__ == "__main__":
    unittest.main()
