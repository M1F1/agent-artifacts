from __future__ import annotations

import json
import unittest

from agent_artifacts.domain.identifiers import ObjectDigest, SourceId
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.protocol.native_tree import SnapshotOrigin
from agent_artifacts.sources.model import SourceInstanceId
from agent_artifacts.sources.pointer import (
    CurrentPointer,
    current_pointer_bytes,
    parse_current_pointer,
)


class SourcePointerTest(unittest.TestCase):
    def test_current_pointer_has_one_canonical_round_trip(self) -> None:
        pointer = CurrentPointer(
            SourceInstanceId("git-" + "a" * 32),
            "b" * 40,
            ObjectDigest("sha256", "c" * 64),
            SourceId("reference-source"),
            SnapshotOrigin.IMMUTABLE_GIT,
            123,
        )

        encoded = current_pointer_bytes(pointer)

        self.assertEqual(parse_current_pointer(encoded), Ok(pointer))
        self.assertEqual(encoded, current_pointer_bytes(pointer))
        self.assertTrue(encoded.endswith(b"\n"))

    def test_malformed_pointer_variants_fail_closed(self) -> None:
        valid = json.loads(
            current_pointer_bytes(
                CurrentPointer(
                    SourceInstanceId("local-" + "a" * 32),
                    "local:" + "b" * 64,
                    ObjectDigest("sha256", "b" * 64),
                    SourceId("reference-source"),
                    SnapshotOrigin.LOCAL,
                    123,
                )
            )
        )
        variants = [
            b"not-json",
            b"[]",
            json.dumps({}).encode(),
            json.dumps({**valid, "schema_version": 2}).encode(),
            json.dumps({**valid, "published_at_epoch_seconds": True}).encode(),
            json.dumps({**valid, "resolved_revision": " "}).encode(),
            json.dumps({**valid, "snapshot_digest": "sha256:nope"}).encode(),
            json.dumps({**valid, "source_instance_id": "invalid"}).encode(),
            json.dumps({**valid, "declared_source_id": "Not A Slug"}).encode(),
            json.dumps({**valid, "resolved_revision": "not-the-local-digest"}).encode(),
            json.dumps({**valid, "origin": "unknown"}).encode(),
        ]

        for payload in variants:
            with self.subTest(payload=payload):
                result = parse_current_pointer(payload)
                self.assertIsInstance(result, Err)


if __name__ == "__main__":
    unittest.main()
