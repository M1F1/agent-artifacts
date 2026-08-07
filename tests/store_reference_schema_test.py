from __future__ import annotations

import json
import unittest

from agent_artifacts.domain.identifiers import ObjectDigest
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.store.model import ObjectReference, ReferenceIndex, ReferenceKind
from agent_artifacts.store.references import parse_reference_index, reference_index_bytes


class StoreReferenceSchemaTest(unittest.TestCase):
    def test_reference_index_has_one_canonical_round_trip(self) -> None:
        index = ReferenceIndex(
            1,
            (
                ObjectReference(
                    ReferenceKind.INSTALLED, "project/demo", ObjectDigest("sha256", "a" * 64)
                ),
            ),
        )

        encoded = reference_index_bytes(index)

        self.assertEqual(parse_reference_index(encoded), Ok(index))
        self.assertEqual(reference_index_bytes(index), encoded)

    def test_malformed_reference_indexes_fail_closed(self) -> None:
        valid = json.loads(
            reference_index_bytes(
                ReferenceIndex(
                    1,
                    (
                        ObjectReference(
                            ReferenceKind.SETUP,
                            "setup/demo",
                            ObjectDigest("sha256", "b" * 64),
                        ),
                    ),
                )
            )
        )
        reference = valid["references"][0]
        variants = (
            b"not-json",
            b"[]",
            json.dumps({}).encode(),
            json.dumps({**valid, "schema_version": 2}).encode(),
            json.dumps({**valid, "references": {}}).encode(),
            json.dumps({**valid, "references": ["bad"]}).encode(),
            json.dumps({**valid, "references": [{}]}).encode(),
            json.dumps({**valid, "references": [{**reference, "kind": 1}]}).encode(),
            json.dumps({**valid, "references": [{**reference, "digest": 1}]}).encode(),
            json.dumps({**valid, "references": [{**reference, "digest": "sha256:nope"}]}).encode(),
            json.dumps({**valid, "references": [{**reference, "kind": "unknown"}]}).encode(),
            json.dumps({**valid, "references": [reference, reference]}).encode(),
            json.dumps(valid, indent=2).encode(),
        )
        for payload in variants:
            with self.subTest(payload=payload):
                self.assertIsInstance(parse_reference_index(payload), Err)


if __name__ == "__main__":
    unittest.main()
