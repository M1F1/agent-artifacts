from __future__ import annotations

import unittest
from unittest.mock import patch

from agent_artifacts.domain.identifiers import ObjectDigest
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.protocol.native_tree import SnapshotEntry, SnapshotEntryKind
from agent_artifacts.protocol.paths import parse_relative_path
from agent_artifacts.store.model import (
    GcOutcome,
    GcPlan,
    GcRequest,
    ObjectCandidate,
    ObjectDeleteCommand,
    ObjectInventory,
    ObjectReadRequest,
    ObjectReference,
    ObjectStatus,
    ObjectStatusKind,
    ReferenceIndex,
    ReferenceKind,
    StoredObject,
    StoreLockLease,
    StoreLockRequest,
    make_object_candidate,
    object_store_paths,
    parse_object_candidate,
)


def _path(raw: str):
    parsed = parse_relative_path(raw)
    assert isinstance(parsed, Ok)
    return parsed.value


def _entries() -> tuple[SnapshotEntry, ...]:
    return (
        SnapshotEntry(_path("payload/SKILL.md"), SnapshotEntryKind.FILE, b"# Skill\n"),
        SnapshotEntry(_path("artifact.json"), SnapshotEntryKind.FILE, b'{"schema_version":1}\n'),
    )


class StoreModelTest(unittest.TestCase):
    def test_candidate_is_canonical_order_independent_and_round_trips(self) -> None:
        first = make_object_candidate(_entries())
        second = make_object_candidate(tuple(reversed(_entries())))

        self.assertIsInstance(first, Ok)
        self.assertEqual(first, second)
        assert isinstance(first, Ok)
        self.assertEqual(
            tuple(str(entry.path) for entry in first.value.entries),
            ("artifact.json", "payload", "payload/SKILL.md"),
        )
        self.assertEqual(
            parse_object_candidate(first.value.canonical_bytes, first.value.digest), first
        )

    def test_expected_digest_traversal_links_specials_and_duplicates_fail_closed(self) -> None:
        valid = make_object_candidate(_entries())
        assert isinstance(valid, Ok)
        wrong = ObjectDigest("sha256", "f" * 64)
        self.assertIsInstance(make_object_candidate(_entries(), expected_digest=wrong), Err)
        invalid = (
            (*_entries(), _entries()[0]),
            (SnapshotEntry(_path("link"), SnapshotEntryKind.SYMLINK),),
            (SnapshotEntry(_path("device"), SnapshotEntryKind.SPECIAL),),
        )
        for entries in invalid:
            with self.subTest(entries=entries):
                self.assertIsInstance(make_object_candidate(entries), Err)
        traversal = b'{"entries":[{"content_base64":"eA==","executable":false,"kind":"file","path":"../x"}],"schema_version":1}\n'
        self.assertIsInstance(parse_object_candidate(traversal), Err)
        self.assertIsInstance(parse_object_candidate(b"not-json"), Err)

    def test_paths_references_and_gc_defaults_are_frozen_and_deterministic(self) -> None:
        paths = object_store_paths("/managed")
        digest = ObjectDigest("sha256", "a" * 64)
        references = ReferenceIndex(
            1,
            (
                ObjectReference(ReferenceKind.SETUP, "setup/z", digest),
                ObjectReference(ReferenceKind.INSTALLED, "project/a", digest),
            ),
        )

        self.assertEqual(paths.objects, "/managed/objects/sha256")
        self.assertEqual(
            tuple(reference.kind for reference in references.references),
            (ReferenceKind.INSTALLED, ReferenceKind.SETUP),
        )
        self.assertFalse(GcRequest(paths).execute)
        with self.assertRaises(ValueError):
            object_store_paths("relative")
        with self.assertRaises(ValueError):
            object_store_paths("/")
        with self.assertRaises(ValueError):
            ReferenceIndex(1, (references.references[0], references.references[0]))

    def test_entry_and_envelope_shape_bounds_fail_closed(self) -> None:
        directory = _path("directory")
        deep = _path("/".join("x" for _index in range(65)))
        invalid_entries = (
            (),
            (SnapshotEntry(directory, SnapshotEntryKind.DIRECTORY, b"metadata"),),
            (SnapshotEntry(directory, SnapshotEntryKind.FILE, "text"),),  # type: ignore[arg-type]
            (SnapshotEntry(deep, SnapshotEntryKind.FILE, b"x"),),
            (
                SnapshotEntry(directory, SnapshotEntryKind.FILE, b"file"),
                SnapshotEntry(_path("directory/file"), SnapshotEntryKind.FILE, b"child"),
            ),
            (SnapshotEntry(_path("large"), SnapshotEntryKind.FILE, b"x" * (10 * 1024 * 1024 + 1)),),
        )
        for entries in invalid_entries:
            with self.subTest(entries=len(entries)):
                self.assertIsInstance(make_object_candidate(entries), Err)

        candidate = make_object_candidate(_entries())
        assert isinstance(candidate, Ok)
        raw = candidate.value.canonical_bytes
        malformed = (
            b"[]",
            b'{"entries":[],"schema_version":2}\n',
            b'{"entries":{},"schema_version":1}\n',
            b'{"entries":[1],"schema_version":1}\n',
            b'{"entries":[{}],"schema_version":1}\n',
            b'{"entries":[{"executable":false,"kind":"unknown","path":"x"}],"schema_version":1}\n',
            b'{"entries":[{"content_base64":"***","executable":false,"kind":"file","path":"x"}],"schema_version":1}\n',
            b'{"entries":[{"executable":true,"kind":"directory","path":"x"}],"schema_version":1}\n',
            raw.rstrip(b"\n") + b" \n",
        )
        for payload in malformed:
            with self.subTest(payload=payload[:40]):
                self.assertIsInstance(parse_object_candidate(payload), Err)

        with patch("agent_artifacts.store.model._MAX_ENTRIES", 1):
            self.assertIsInstance(make_object_candidate(_entries()), Err)
            self.assertIsInstance(parse_object_candidate(raw), Err)

    def test_value_objects_reject_invalid_digests_references_and_gc_partitions(self) -> None:
        candidate = make_object_candidate(_entries())
        assert isinstance(candidate, Ok)
        valid = candidate.value.digest
        invalid = ObjectDigest("sha256", "nope")
        constructors = (
            lambda: ObjectCandidate(
                invalid, candidate.value.entries, candidate.value.canonical_bytes
            ),
            lambda: ObjectCandidate(
                valid, tuple(reversed(candidate.value.entries)), candidate.value.canonical_bytes
            ),
            lambda: ObjectCandidate(
                valid,
                (SnapshotEntry(_path("link"), SnapshotEntryKind.SYMLINK),),
                candidate.value.canonical_bytes,
            ),
            lambda: type(object_store_paths("/managed"))(
                "/managed",
                "/outside/objects",
                "/managed/state",
                "/managed/state/object-references.json",
                "/managed/locks/store.lock",
                "/managed/tmp/objects",
                "/managed/objects/quarantine",
            ),
            lambda: StoredObject(candidate.value, "relative"),
            lambda: ObjectReadRequest(object_store_paths("/managed"), invalid),
            lambda: ObjectDeleteCommand(object_store_paths("/managed"), invalid),
            lambda: ObjectReference(ReferenceKind.INSTALLED, "bad owner", valid),
            lambda: ReferenceIndex(2, ()),
            lambda: StoreLockRequest("relative"),
            lambda: StoreLockRequest("/lock", timeout_seconds=0),
            lambda: StoreLockLease("relative", "token"),
            lambda: ObjectInventory((valid, valid)),
            lambda: GcRequest(object_store_paths("/managed"), execute=1),  # type: ignore[arg-type]
            lambda: GcPlan((valid,), (valid,)),
            lambda: GcOutcome(GcPlan((), (valid,)), False, (valid,)),
            lambda: GcOutcome(GcPlan((), ()), True, (valid,)),
            lambda: GcOutcome(GcPlan((), (valid,)), True, (valid, valid)),
            lambda: ObjectStatus("verified", valid),  # type: ignore[arg-type]
            lambda: ObjectStatus(ObjectStatusKind.VERIFIED, valid),
            lambda: ObjectStatus(
                ObjectStatusKind.MISSING,
                valid,
                StoredObject(candidate.value, "/managed/object"),
            ),
            lambda: ObjectStatus(
                ObjectStatusKind.VERIFIED,
                ObjectDigest("sha256", "b" * 64),
                StoredObject(candidate.value, "/managed/object"),
            ),
        )
        for constructor in constructors:
            with self.subTest(constructor=constructor), self.assertRaises(ValueError):
                constructor()


if __name__ == "__main__":
    unittest.main()
