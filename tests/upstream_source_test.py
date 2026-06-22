"""Tests for upstream source resolution and deterministic upstream content hashes.

Run: ``python -m unittest discover -s tests -p "upstream_source_test.py" -v``
"""

import io
import json
import os
import tarfile
import tempfile
import unittest

from agent_artifacts.io import cache
from agent_artifacts.model import Err, Ok
from agent_artifacts.upstream_source import hash_upstream_path, resolve_upstream_source
from agent_artifacts.upstreams import UpstreamEntry, UpstreamKey, UpstreamSource

CANNED_SHA = "1234567890abcdef1234567890abcdef12345678"
REPO = "acme/widgets"
TARBALL_TOP = f"acme-widgets-{CANNED_SHA}"


def _entry(path: str = "skills/demo") -> UpstreamEntry:
    return UpstreamEntry(
        key=UpstreamKey("skill", "demo"),
        source=UpstreamSource("github", REPO, "main", path),
    )


def _tarball(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        top = tarfile.TarInfo(TARBALL_TOP + "/")
        top.type = tarfile.DIRTYPE
        tar.addfile(top)
        for rel, data in sorted(files.items()):
            info = tarfile.TarInfo(f"{TARBALL_TOP}/{rel}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class FakeGithub:
    def __init__(self, files: dict[str, bytes]):
        self.tarball = _tarball(files)
        self.urls: list[str] = []

    def opener(self, request):
        self.urls.append(request.full_url)
        if "/commits/" in request.full_url:
            return io.BytesIO(json.dumps({"sha": CANNED_SHA}).encode("utf-8"))
        if "/tarball/" in request.full_url:
            return io.BytesIO(self.tarball)
        raise AssertionError(f"unexpected URL: {request.full_url}")

    @property
    def commit_requests(self) -> int:
        return sum(1 for url in self.urls if "/commits/" in url)

    @property
    def tarball_requests(self) -> int:
        return sum(1 for url in self.urls if "/tarball/" in url)


class TempCacheTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.orig_cache_dir = cache.cache_dir
        root = self.tmp.name
        cache.cache_dir = lambda repo, sha: os.path.join(root, repo.replace("/", "_"), sha)

    def tearDown(self):
        cache.cache_dir = self.orig_cache_dir
        self.tmp.cleanup()


class UpstreamHashTests(unittest.TestCase):
    def test_file_hash_depends_on_file_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = os.path.join(tmp, "a.txt")
            b = os.path.join(tmp, "b.txt")
            c = os.path.join(tmp, "c.txt")
            with open(a, "wb") as fh:
                fh.write(b"same\n")
            with open(b, "wb") as fh:
                fh.write(b"same\n")
            with open(c, "wb") as fh:
                fh.write(b"different\n")

            self.assertEqual(hash_upstream_path(a), hash_upstream_path(b))
            self.assertNotEqual(hash_upstream_path(a), hash_upstream_path(c))
            self.assertTrue(hash_upstream_path(a).startswith("sha256:"))

    def test_tree_hash_is_deterministic_and_tracks_names_and_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            left = os.path.join(tmp, "left")
            right = os.path.join(tmp, "right")
            renamed = os.path.join(tmp, "renamed")
            changed = os.path.join(tmp, "changed")

            for root in (left, right, renamed, changed):
                os.makedirs(os.path.join(root, "nested"))

            with open(os.path.join(left, "b.txt"), "wb") as fh:
                fh.write(b"b\n")
            with open(os.path.join(left, "nested", "a.txt"), "wb") as fh:
                fh.write(b"a\n")

            with open(os.path.join(right, "nested", "a.txt"), "wb") as fh:
                fh.write(b"a\n")
            with open(os.path.join(right, "b.txt"), "wb") as fh:
                fh.write(b"b\n")

            with open(os.path.join(renamed, "c.txt"), "wb") as fh:
                fh.write(b"b\n")
            with open(os.path.join(renamed, "nested", "a.txt"), "wb") as fh:
                fh.write(b"a\n")

            with open(os.path.join(changed, "b.txt"), "wb") as fh:
                fh.write(b"B\n")
            with open(os.path.join(changed, "nested", "a.txt"), "wb") as fh:
                fh.write(b"a\n")

            self.assertEqual(hash_upstream_path(left), hash_upstream_path(right))
            self.assertNotEqual(hash_upstream_path(left), hash_upstream_path(renamed))
            self.assertNotEqual(hash_upstream_path(left), hash_upstream_path(changed))


class ResolveUpstreamSourceTests(TempCacheTestCase):
    def test_resolves_github_upstream_with_injected_opener(self):
        fake = FakeGithub(
            {
                "skills/demo/SKILL.md": b"---\nname: demo\n---\nbody\n",
                "skills/demo/lib.py": b"print('hello')\n",
                "README.md": b"not tracked\n",
            }
        )

        result = resolve_upstream_source(_entry(), opener=fake.opener)

        self.assertIsInstance(result, Ok, getattr(result, "reason", ""))
        resolved = result.value
        self.assertEqual(resolved.entry, _entry())
        self.assertEqual(resolved.sha, CANNED_SHA)
        self.assertEqual(resolved.root, cache.cache_dir(REPO, CANNED_SHA))
        self.assertEqual(resolved.path, os.path.join(resolved.root, "skills", "demo"))
        self.assertEqual(resolved.content_hash, hash_upstream_path(resolved.path))
        self.assertEqual(fake.commit_requests, 1)
        self.assertEqual(fake.tarball_requests, 1)

    def test_reuses_cached_snapshot_for_same_repo_and_sha(self):
        fake = FakeGithub({"skills/demo/SKILL.md": b"---\nname: demo\n---\nbody\n"})

        first = resolve_upstream_source(_entry(), opener=fake.opener)
        second = resolve_upstream_source(_entry(), opener=fake.opener)

        self.assertIsInstance(first, Ok, getattr(first, "reason", ""))
        self.assertIsInstance(second, Ok, getattr(second, "reason", ""))
        self.assertEqual(first.value.root, second.value.root)
        self.assertEqual(first.value.content_hash, second.value.content_hash)
        self.assertEqual(fake.commit_requests, 2)
        self.assertEqual(fake.tarball_requests, 1)

    def test_missing_upstream_path_is_err(self):
        fake = FakeGithub({"README.md": b"nothing tracked here\n"})

        result = resolve_upstream_source(_entry("skills/missing"), opener=fake.opener)

        self.assertIsInstance(result, Err)
        self.assertEqual(result.code, 3)
        self.assertIn("missing_upstream", result.reason)
        self.assertIn("skills/missing", result.reason)


if __name__ == "__main__":
    unittest.main()
