"""`io/cache.py`: an immutable snapshot is extracted once and reused.

These tests were part of `net_test.py`, which `VN-7` deleted with the GitHub API client it covered.
The cache itself is not that client: it takes a `fetch` callable and never knows where the bytes
came from, so the tarball here is built in memory and no server, opener, or token is involved.
"""

from __future__ import annotations

import io
import os
import tarfile
import tempfile
import unittest

from agent_artifacts.io import cache

_SHA = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"
_REPO = "acme/widgets"
_TOP = f"acme-widgets-{_SHA}"


def _tarball() -> bytes:
    """A `.tar.gz` shaped like a Git host's: one top-level directory wrapping the content."""

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        top = tarfile.TarInfo(f"{_TOP}/")
        top.type = tarfile.DIRTYPE
        archive.addfile(top)
        for path, data in (
            ("skills/code-review/SKILL.md", b"# code review\n"),
            ("guidelines/style.md", b"be nice\n"),
            ("README.md", b"hello\n"),
        ):
            info = tarfile.TarInfo(f"{_TOP}/{path}")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


class SnapshotCacheTest(unittest.TestCase):
    def test_cache_dir_layout(self) -> None:
        path = cache.cache_dir(_REPO, _SHA)

        self.assertTrue(path.endswith(f"agent-artifacts/acme_widgets/{_SHA}"))
        self.assertNotIn("~", path)

    def test_ensure_snapshot_extracts_once_and_strips_the_top_directory(self) -> None:
        archive = _tarball()
        calls = {"n": 0}

        def fetch() -> bytes:
            calls["n"] += 1
            return archive

        with tempfile.TemporaryDirectory() as temporary:
            destination = os.path.join(temporary, "acme_widgets", _SHA)
            original = cache.cache_dir
            cache.cache_dir = lambda _repo, _sha: destination
            try:
                first = cache.ensure_snapshot(_REPO, _SHA, fetch)
                second = cache.ensure_snapshot(_REPO, _SHA, fetch)
            finally:
                cache.cache_dir = original

            self.assertEqual((first, second), (destination, destination))
            # A commit is immutable, so the second call reuses what the first extracted.
            self.assertEqual(calls["n"], 1)
            self.assertTrue(os.path.isdir(os.path.join(destination, "skills", "code-review")))
            self.assertFalse(os.path.exists(os.path.join(destination, _TOP)))
            with open(os.path.join(destination, "README.md"), "rb") as handle:
                self.assertEqual(handle.read(), b"hello\n")


if __name__ == "__main__":
    unittest.main()
