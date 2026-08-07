"""P01 contracts for canonical SHA-256 document and tree identities."""

from __future__ import annotations

import re
import unittest
from typing import cast


def _unwrap(result):
    from agent_artifacts.domain.result import Ok

    if not isinstance(result, Ok):
        raise AssertionError(f"expected Ok, got {result!r}")
    return result.value


def _code(result) -> str:
    from agent_artifacts.domain.result import Err

    if not isinstance(result, Err):
        raise AssertionError(f"expected Err, got {result!r}")
    return result.diagnostics[0].code.value


class CanonicalDigestTest(unittest.TestCase):
    def test_json_digest_is_order_and_whitespace_independent(self):
        from agent_artifacts.protocol.hashing import json_digest
        from agent_artifacts.protocol.json import parse_json

        first = _unwrap(parse_json('{"b": 2, "a": [1, true]}'))
        second = _unwrap(parse_json('{\n  "a": [1,true],\n  "b": 2\n}'))

        self.assertEqual(json_digest(first), json_digest(second))
        self.assertRegex(str(json_digest(first)), r"^sha256:[0-9a-f]{64}$")

    def test_sha256_values_are_lowercase_canonical_and_strictly_parsed(self):
        from agent_artifacts.protocol.hashing import parse_sha256, sha256_bytes

        digest = sha256_bytes(b"aart")
        self.assertEqual(_unwrap(parse_sha256(str(digest))), digest)
        for raw in (
            "sha256:ABCDEF" + "0" * 58,
            "sha256:" + "0" * 63,
            "md5:" + "0" * 64,
            "0" * 64,
        ):
            with self.subTest(raw=raw):
                self.assertEqual(_code(parse_sha256(raw)), "protocol-digest-invalid")


class TreeDigestTest(unittest.TestCase):
    def test_tree_digest_is_input_order_independent_and_content_sensitive(self):
        from agent_artifacts.protocol.hashing import directory_entry, file_entry, tree_digest
        from agent_artifacts.protocol.paths import parse_relative_path

        root = _unwrap(parse_relative_path("payload"))
        first_path = _unwrap(parse_relative_path("payload/a.txt"))
        second_path = _unwrap(parse_relative_path("payload/b.txt"))
        directory = directory_entry(root)
        first = file_entry(first_path, b"alpha")
        second = file_entry(second_path, b"beta")

        baseline = _unwrap(tree_digest((directory, first, second)))
        self.assertEqual(
            str(baseline),
            "sha256:c3b661e6b0f350607781ddc02ba00acdb21608fdf7baecd6c66761ef8231024d",
        )
        self.assertEqual(baseline, _unwrap(tree_digest((second, directory, first))))
        self.assertNotEqual(
            baseline,
            _unwrap(tree_digest((directory, file_entry(first_path, b"changed"), second))),
        )
        self.assertTrue(re.fullmatch(r"sha256:[0-9a-f]{64}", str(baseline)))

    def test_executable_bit_directory_presence_and_duplicate_paths_change_or_reject(self):
        from agent_artifacts.protocol.hashing import (
            EntryKind,
            TreeEntry,
            directory_entry,
            file_entry,
            sha256_bytes,
            tree_digest,
        )
        from agent_artifacts.protocol.paths import parse_relative_path

        directory = directory_entry(_unwrap(parse_relative_path("payload")))
        path = _unwrap(parse_relative_path("payload/run.sh"))
        regular = file_entry(path, b"#!/bin/sh\n", executable=False)
        executable = file_entry(path, b"#!/bin/sh\n", executable=True)

        self.assertNotEqual(_unwrap(tree_digest((regular,))), _unwrap(tree_digest((executable,))))
        self.assertNotEqual(
            _unwrap(tree_digest((regular,))),
            _unwrap(tree_digest((directory, regular))),
        )
        self.assertEqual(_code(tree_digest((regular, executable))), "protocol-tree-invalid")
        oversized = TreeEntry(path, EntryKind.FILE, size=2**64, content_digest=sha256_bytes(b""))
        self.assertEqual(_code(tree_digest((oversized,))), "protocol-tree-invalid")
        special = TreeEntry(
            path,
            cast(EntryKind, "special"),
            size=0,
            content_digest=sha256_bytes(b""),
        )
        self.assertEqual(_code(tree_digest((special,))), "protocol-tree-invalid")


if __name__ == "__main__":
    unittest.main()
