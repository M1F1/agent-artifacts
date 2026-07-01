"""Tests for agent_artifacts.io.fs (WP-6)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from agent_artifacts.io.fs import (
    copy_tree,
    exists,
    listdir,
    read_bytes,
    read_json,
    read_text,
    remove_path,
    write_atomic,
)


class TestWriteAtomic(unittest.TestCase):
    """write_atomic: creates parents, overwrites, no leftover temp files."""

    def test_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "a", "b", "c", "file.txt")
            write_atomic(path, b"hello")
            self.assertTrue(os.path.isfile(path))
            with open(path, "rb") as f:
                self.assertEqual(f.read(), b"hello")

    def test_overwrites_existing(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "file.txt")
            write_atomic(path, b"first")
            write_atomic(path, b"second")
            with open(path, "rb") as f:
                self.assertEqual(f.read(), b"second")

    def test_no_partial_temp_files_on_success(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "file.txt")
            write_atomic(path, b"data")
            entries = os.listdir(td)
            self.assertEqual(entries, ["file.txt"])

    @unittest.skipIf(
        hasattr(os, "geteuid") and os.geteuid() == 0,
        "root bypasses directory permission bits, so a read-only dir does not fail the write "
        "(e.g. tests run as root inside a CI container)",
    )
    def test_no_partial_temp_files_on_error(self):
        """If write_atomic fails, no temp files should be left behind."""
        with tempfile.TemporaryDirectory() as td:
            # Make the directory read-only so os.replace will fail
            # after the temp file is created.
            subdir = os.path.join(td, "locked")
            os.makedirs(subdir)
            path = os.path.join(subdir, "file.txt")

            # Write a file first, then make the dir read-only
            write_atomic(path, b"original")

            # Now make the directory read-only — creating temp files will fail
            os.chmod(subdir, 0o444)
            try:
                with self.assertRaises(OSError):
                    write_atomic(path, b"should-fail")
            finally:
                os.chmod(subdir, 0o755)

            # Only the original file should remain
            entries = os.listdir(subdir)
            self.assertEqual(entries, ["file.txt"])


class TestRoundTrip(unittest.TestCase):
    """write_atomic -> read_bytes / read_text / read_json round-trips."""

    def test_bytes_round_trip(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "data.bin")
            data = b"\x00\x01\x02\xff"
            write_atomic(path, data)
            self.assertEqual(read_bytes(path), data)

    def test_text_round_trip(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "data.txt")
            text = "hello\nworld\n"
            write_atomic(path, text.encode("utf-8"))
            self.assertEqual(read_text(path), text)

    def test_json_round_trip(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "data.json")
            obj = {"key": [1, 2, 3], "nested": {"a": True}}
            write_atomic(path, json.dumps(obj).encode("utf-8"))
            self.assertEqual(read_json(path), obj)

    def test_text_utf8(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "utf8.txt")
            text = "café ☕ 日本語"
            write_atomic(path, text.encode("utf-8"))
            self.assertEqual(read_text(path), text)


class TestCopyTree(unittest.TestCase):
    """copy_tree: recursive copy, idempotent on re-copy."""

    def _make_tree(self, root: str) -> None:
        """Create a small nested directory tree."""
        os.makedirs(os.path.join(root, "sub", "deep"))
        with open(os.path.join(root, "a.txt"), "w") as f:
            f.write("A")
        with open(os.path.join(root, "sub", "b.txt"), "w") as f:
            f.write("B")
        with open(os.path.join(root, "sub", "deep", "c.txt"), "w") as f:
            f.write("C")

    def test_copies_nested_files(self):
        with tempfile.TemporaryDirectory() as td:
            src = os.path.join(td, "src")
            dst = os.path.join(td, "dst")
            self._make_tree(src)
            copy_tree(src, dst)

            self.assertEqual(read_text(os.path.join(dst, "a.txt")), "A")
            self.assertEqual(read_text(os.path.join(dst, "sub", "b.txt")), "B")
            self.assertEqual(read_text(os.path.join(dst, "sub", "deep", "c.txt")), "C")

    def test_idempotent_re_copy(self):
        with tempfile.TemporaryDirectory() as td:
            src = os.path.join(td, "src")
            dst = os.path.join(td, "dst")
            self._make_tree(src)
            copy_tree(src, dst)
            # Modify a file in src
            with open(os.path.join(src, "a.txt"), "w") as f:
                f.write("A2")
            # Re-copy should overwrite
            copy_tree(src, dst)
            self.assertEqual(read_text(os.path.join(dst, "a.txt")), "A2")
            # Previously copied files still present
            self.assertEqual(read_text(os.path.join(dst, "sub", "b.txt")), "B")

    def test_creates_parent_of_dst(self):
        with tempfile.TemporaryDirectory() as td:
            src = os.path.join(td, "src")
            dst = os.path.join(td, "x", "y", "dst")
            self._make_tree(src)
            copy_tree(src, dst)
            self.assertTrue(os.path.isfile(os.path.join(dst, "a.txt")))


class TestRemovePath(unittest.TestCase):
    """remove_path: file, dir tree, missing -> no-op."""

    def test_removes_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "file.txt")
            write_atomic(path, b"data")
            self.assertTrue(os.path.isfile(path))
            remove_path(path)
            self.assertFalse(os.path.exists(path))

    def test_removes_dir_tree(self):
        with tempfile.TemporaryDirectory() as td:
            tree = os.path.join(td, "tree")
            os.makedirs(os.path.join(tree, "a", "b"))
            with open(os.path.join(tree, "a", "b", "c.txt"), "w") as f:
                f.write("C")
            remove_path(tree)
            self.assertFalse(os.path.exists(tree))

    def test_missing_path_is_noop(self):
        # Should not raise
        remove_path("/nonexistent/path/that/does/not/exist")


class TestExists(unittest.TestCase):
    def test_existing_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "file.txt")
            write_atomic(path, b"x")
            self.assertTrue(exists(path))

    def test_existing_dir(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertTrue(exists(td))

    def test_missing(self):
        self.assertFalse(exists("/nonexistent/path/xyz"))


class TestListdir(unittest.TestCase):
    def test_sorted_entries(self):
        with tempfile.TemporaryDirectory() as td:
            for name in ("c.txt", "a.txt", "b.txt"):
                with open(os.path.join(td, name), "w") as f:
                    f.write("")
            self.assertEqual(listdir(td), ("a.txt", "b.txt", "c.txt"))

    def test_includes_dirs(self):
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, "subdir"))
            with open(os.path.join(td, "file.txt"), "w") as f:
                f.write("")
            result = listdir(td)
            self.assertIn("subdir", result)
            self.assertIn("file.txt", result)

    def test_missing_dir_returns_empty_tuple(self):
        self.assertEqual(listdir("/nonexistent/dir/xyz"), ())

    def test_empty_dir(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(listdir(td), ())


if __name__ == "__main__":
    unittest.main()
