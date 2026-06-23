"""WP-11 tests: unified local/remote source resolver.

Covers three things (PLAN.md WP-11 "Done when"):

* LOCAL backend reads ``tests/fixtures/`` and yields the expected `Catalog`.
* REMOTE backend resolves a ``repo@ref`` to a SHA, extracts an in-memory ``.tar.gz`` via
  the snapshot cache, and yields a catalog — driven by a local ``http.server`` + injected
  ``opener``, **no live network**.
* Both backends return **identical** catalogs from the same content.
* A malformed artifact makes ``catalog()`` return ``Err``.

Run: ``python -m unittest discover -s tests -p "source_test.py" -v``
"""

import io
import json
import os
import pathlib
import tarfile
import tempfile
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

from agent_artifacts import source
from agent_artifacts.io import cache
from agent_artifacts.model import Catalog, Err, Ok, Request

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures"

CANNED_SHA = "f00dcafe1234567890abcdef0987654321fedcba"
REPO = "acme/widgets"
TARBALL_TOP = f"acme-widgets-{CANNED_SHA}"


def _fixture_files() -> dict:
    """Map of repo-relative path -> bytes, read straight from ``tests/fixtures/``.

    Building the remote tarball from the *same* on-disk content the local backend reads is
    what lets us assert the two catalogs are identical.
    """
    files = {}
    for path in FIXTURES.rglob("*"):
        if path.is_file():
            rel = path.relative_to(FIXTURES).as_posix()
            files[rel] = path.read_bytes()
    return files


def _build_tarball(files: dict) -> bytes:
    """In-memory ``.tar.gz`` mimicking a GitHub tarball: content under one top-level dir."""
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


_COMMIT_JSON = json.dumps({"sha": CANNED_SHA, "commit": {"message": "x"}}).encode()


class _Handler(BaseHTTPRequestHandler):
    tarball = b""  # set per-test-class in setUpClass

    def log_message(self, *args):  # silence test output
        pass

    def do_GET(self):  # noqa: N802 (stdlib naming)
        if "/commits/" in self.path:
            self._send(200, _COMMIT_JSON, "application/json")
        elif "/tarball/" in self.path:
            self._send(200, self.tarball, "application/gzip")
        else:
            self._send(404, b'{"message":"not found"}', "application/json")

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _expected_catalog_shape(catalog: Catalog):
    """A comparable, order-insensitive view: sets of artifact keys + bundle names."""
    return (
        frozenset(catalog.artifacts.keys()),
        frozenset(catalog.bundles.keys()),
    )


class LocalSourceTest(unittest.TestCase):
    def setUp(self):
        req = Request(command="install", source_dir=str(FIXTURES))
        result = source.open_source(req)
        self.assertIsInstance(result, Ok, getattr(result, "reason", ""))
        self.src = result.value

    def test_label_is_local_sentinel(self):
        label = self.src.label()
        self.assertTrue(label.startswith("local:"), label)
        # The recorded path is the absolute fixtures dir.
        self.assertEqual(label, f"local:{os.path.abspath(str(FIXTURES))}")

    def test_root_is_absolute_fixtures_dir(self):
        self.assertEqual(self.src.root, os.path.abspath(str(FIXTURES)))

    def test_read_returns_bytes(self):
        data = self.src.read("skills/code-review/SKILL.md")
        self.assertIsInstance(data, bytes)
        self.assertIn(b"name: code-review", data)

    def test_catalog_has_expected_artifacts_and_bundles(self):
        result = self.src.catalog()
        self.assertIsInstance(result, Ok, getattr(result, "reason", ""))
        cat = result.value
        # One of each artifact type, keyed (type, name) — "name = key" (DESIGN.md §4).
        self.assertIn(("skill", "code-review"), cat.artifacts)
        self.assertIn(("guideline", "python-style"), cat.artifacts)
        self.assertIn(("mcp", "postgres"), cat.artifacts)
        self.assertIn(("mcp", "tabnine-postgres"), cat.artifacts)
        self.assertIn(("hook", "block-secrets"), cat.artifacts)
        self.assertIn(("memory", "house"), cat.artifacts)
        self.assertEqual(len(cat.artifacts), 6)
        # Both bundles present.
        self.assertEqual(set(cat.bundles), {"base", "backend"})
        # Artifact roots are repo-relative (DESIGN.md §4).
        self.assertEqual(cat.artifacts[("skill", "code-review")].root, "skills/code-review")
        self.assertEqual(cat.artifacts[("guideline", "python-style")].root, "guidelines/python-style.md")
        self.assertEqual(cat.artifacts[("mcp", "postgres")].root, "mcp/postgres.json")
        self.assertEqual(cat.artifacts[("mcp", "tabnine-postgres")].root, "mcp/tabnine-postgres.json")
        self.assertEqual(cat.artifacts[("hook", "block-secrets")].root, "hooks/block-secrets")
        self.assertEqual(cat.artifacts[("memory", "house")].root, "memory/house.md")


class RemoteSourceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Handler.tarball = _build_tarball(_fixture_files())
        cls.server = HTTPServer(("127.0.0.1", 0), _Handler)
        cls.host, cls.port = cls.server.server_address
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://{cls.host}:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def setUp(self):
        # Redirect the snapshot cache into a fresh temp dir so the test is hermetic and
        # never touches the user's real ~/.cache.
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_cache_dir = cache.cache_dir
        tmp = self._tmp.name
        cache.cache_dir = lambda repo, sha: os.path.join(tmp, repo.replace("/", "_"), sha)

    def tearDown(self):
        cache.cache_dir = self._orig_cache_dir
        self._tmp.cleanup()

    def _opener(self):
        """Rewrite api.github.com URLs onto the local server, then call urlopen."""
        base = self.base

        def opener(request):
            url = request.full_url.replace("https://api.github.com", base)
            local = urllib.request.Request(url, headers=dict(request.header_items()))
            return urllib.request.urlopen(local)

        return opener

    def test_default_version_yields_main_label(self):
        req = Request(command="install", repo=REPO)  # no version -> tracks main
        result = source.open_source(req, opener=self._opener())
        self.assertIsInstance(result, Ok, getattr(result, "reason", ""))
        self.assertEqual(result.value.label(), f"main:{CANNED_SHA}")

    def test_explicit_version_yields_pin_label(self):
        req = Request(command="install", repo=REPO, version="v1.2.3")
        result = source.open_source(req, opener=self._opener())
        self.assertIsInstance(result, Ok, getattr(result, "reason", ""))
        self.assertEqual(result.value.label(), f"pin:{CANNED_SHA}")

    def test_remote_catalog_matches_fixtures(self):
        req = Request(command="install", repo=REPO)
        src = source.open_source(req, opener=self._opener()).value
        result = src.catalog()
        self.assertIsInstance(result, Ok, getattr(result, "reason", ""))
        cat = result.value
        self.assertEqual(set(cat.bundles), {"base", "backend"})
        self.assertIn(("skill", "code-review"), cat.artifacts)
        self.assertIn(("mcp", "postgres"), cat.artifacts)

    def test_resolve_ref_failure_propagates(self):
        def boom(request):
            raise OSError("dns")

        result = source.open_source(Request(command="install", repo=REPO), opener=boom)
        self.assertIsInstance(result, Err)
        self.assertEqual(result.code, 3)


class IdenticalCatalogTest(unittest.TestCase):
    """PLAN.md WP-11 key requirement: both backends -> identical catalogs from same content."""

    @classmethod
    def setUpClass(cls):
        _Handler.tarball = _build_tarball(_fixture_files())
        cls.server = HTTPServer(("127.0.0.1", 0), _Handler)
        cls.host, cls.port = cls.server.server_address
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://{cls.host}:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def _opener(self):
        base = self.base

        def opener(request):
            url = request.full_url.replace("https://api.github.com", base)
            return urllib.request.urlopen(
                urllib.request.Request(url, headers=dict(request.header_items()))
            )

        return opener

    def test_local_and_remote_catalogs_identical(self):
        local_cat = source.open_source(
            Request(command="install", source_dir=str(FIXTURES))
        ).value.catalog().value

        with tempfile.TemporaryDirectory() as tmp:
            orig = cache.cache_dir
            cache.cache_dir = lambda repo, sha: os.path.join(tmp, repo.replace("/", "_"), sha)
            try:
                remote_cat = source.open_source(
                    Request(command="install", repo=REPO), opener=self._opener()
                ).value.catalog().value
            finally:
                cache.cache_dir = orig

        # Identical artifact set, identical bundle set...
        self.assertEqual(_expected_catalog_shape(local_cat), _expected_catalog_shape(remote_cat))
        # ...and the artifact records themselves are equal (frozen dataclass __eq__).
        self.assertEqual(local_cat.artifacts, remote_cat.artifacts)
        self.assertEqual(local_cat.bundles, remote_cat.bundles)


class MalformedSourceTest(unittest.TestCase):
    def test_malformed_artifact_makes_catalog_err(self):
        with tempfile.TemporaryDirectory() as tmp:
            # A skill whose frontmatter name disagrees with its directory name -> parse Err.
            skill_dir = os.path.join(tmp, "skills", "broken")
            os.makedirs(skill_dir)
            with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as fh:
                fh.write("---\nname: not-broken\n---\nbody\n")

            result = source.open_source(Request(command="install", source_dir=tmp))
            self.assertIsInstance(result, Ok)
            cat = result.value.catalog()
            self.assertIsInstance(cat, Err)
            self.assertIn("broken", cat.reason)

    def test_malformed_bundle_makes_catalog_err(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "bundles"))
            with open(os.path.join(tmp, "bundles", "bad.json"), "w", encoding="utf-8") as fh:
                fh.write("{ not valid json")
            cat = source.open_source(Request(command="install", source_dir=tmp)).value.catalog()
            self.assertIsInstance(cat, Err)


if __name__ == "__main__":
    unittest.main()
