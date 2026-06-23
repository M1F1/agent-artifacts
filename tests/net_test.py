"""WP-7 tests: GitHub net IO + immutable snapshot cache, driven by a local http.server.

No live network. A background ``http.server.HTTPServer`` on ``127.0.0.1:0`` serves canned
commit JSON, canned compare JSON, and an in-memory ``.tar.gz`` built with ``tarfile``. An
injected ``opener`` routes the real GitHub URLs to that local server.

Run: ``python -m unittest discover -s tests -p "net_test.py" -v``
"""

import io
import json
import tarfile
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch

from agent_artifacts.io import cache, net
from agent_artifacts.model import Err, Ok

CANNED_SHA = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"
REPO = "acme/widgets"
TARBALL_TOP = f"acme-widgets-{CANNED_SHA}"


def _build_tarball() -> bytes:
    """An in-memory ``.tar.gz`` mimicking a GitHub tarball: one top-level dir wrapping content."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:

        def add(path: str, data: bytes) -> None:
            info = tarfile.TarInfo(f"{TARBALL_TOP}/{path}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

        # The top-level directory entry, then content under it.
        top = tarfile.TarInfo(TARBALL_TOP + "/")
        top.type = tarfile.DIRTYPE
        tar.addfile(top)
        add("skills/code-review/SKILL.md", b"# code review\n")
        add("guidelines/style.md", b"be nice\n")
        add("README.md", b"hello\n")
    return buf.getvalue()


_TARBALL = _build_tarball()
_COMMIT_JSON = json.dumps({"sha": CANNED_SHA, "commit": {"message": "x"}}).encode()
_COMPARE_JSON = json.dumps(
    {"status": "ahead", "ahead_by": 2, "files": [{"filename": "skills/code-review/SKILL.md"}]}
).encode()


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence test output
        pass

    def do_GET(self):  # noqa: N802 (stdlib naming)
        path = self.path
        if "/commits/" in path:
            self._send(200, _COMMIT_JSON, "application/json")
        elif "/compare/" in path:
            self._send(200, _COMPARE_JSON, "application/json")
        elif "/tarball/" in path:
            self._send(200, _TARBALL, "application/gzip")
        else:
            self._send(404, b'{"message":"not found"}', "application/json")

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class NetCacheTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
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
        """Rewrite api.github.com URLs onto the local server, then call urlopen."""
        base = self.base

        def opener(request):
            url = request.full_url
            local = url.replace("https://api.github.com", base)
            local_req = urllib.request.Request(local, headers=dict(request.header_items()))
            return urllib.request.urlopen(local_req)

        return opener

    # --- net.resolve_ref -------------------------------------------------- #
    def test_resolve_ref_returns_sha(self):
        result = net.resolve_ref(REPO, "main", opener=self._opener())
        self.assertIsInstance(result, Ok)
        self.assertEqual(result.value, CANNED_SHA)

    def test_resolve_ref_network_failure_is_err(self):
        def boom(request):
            raise urllib.error.URLError("connection refused")

        result = net.resolve_ref(REPO, "main", opener=boom)
        self.assertIsInstance(result, Err)
        self.assertEqual(result.code, 3)

    def test_resolve_ref_bad_json_is_err(self):
        def junk(request):
            return io.BytesIO(b"not json")

        result = net.resolve_ref(REPO, "main", opener=junk)
        self.assertIsInstance(result, Err)
        self.assertEqual(result.code, 3)

    def test_resolve_ref_attaches_auth_header(self):
        seen = {}

        def capture(request):
            seen["auth"] = request.get_header("Authorization")
            seen["accept"] = request.get_header("Accept")
            return io.BytesIO(_COMMIT_JSON)

        net.resolve_ref(REPO, "main", token="secret-token", opener=capture)
        self.assertEqual(seen["auth"], "Bearer secret-token")
        self.assertEqual(seen["accept"], "application/vnd.github+json")

    def test_resolve_ref_uses_per_call_api_url(self):
        seen = {}

        def capture(request):
            seen["url"] = request.full_url
            return io.BytesIO(_COMMIT_JSON)

        result = net.resolve_ref(
            REPO,
            "main",
            api_url="https://github.my-company.com/api/v3",
            opener=capture,
        )

        self.assertIsInstance(result, Ok)
        self.assertEqual(
            seen["url"],
            "https://github.my-company.com/api/v3/repos/acme/widgets/commits/main",
        )

    def test_resolve_ref_reads_global_api_url_at_call_time(self):
        seen = {}

        def capture(request):
            seen["url"] = request.full_url
            return io.BytesIO(_COMMIT_JSON)

        with patch.dict("os.environ", {"GITHUB_API_URL": "https://github.env/api/v3"}):
            result = net.resolve_ref(REPO, "main", opener=capture)

        self.assertIsInstance(result, Ok)
        self.assertEqual(seen["url"], "https://github.env/api/v3/repos/acme/widgets/commits/main")

    # --- net.compare ------------------------------------------------------ #
    def test_compare_returns_dict(self):
        result = net.compare(REPO, "base123", CANNED_SHA, opener=self._opener())
        self.assertIsInstance(result, Ok)
        self.assertEqual(result.value["status"], "ahead")
        self.assertEqual(result.value["ahead_by"], 2)

    def test_compare_uses_per_call_api_url(self):
        seen = {}

        def capture(request):
            seen["url"] = request.full_url
            return io.BytesIO(_COMPARE_JSON)

        result = net.compare(
            REPO,
            "base123",
            CANNED_SHA,
            api_url="https://github.my-company.com/api/v3",
            opener=capture,
        )

        self.assertIsInstance(result, Ok)
        self.assertEqual(
            seen["url"],
            (
                "https://github.my-company.com/api/v3/repos/acme/widgets/compare/"
                f"base123...{CANNED_SHA}"
            ),
        )

    def test_compare_failure_is_err(self):
        def boom(request):
            raise OSError("dns")

        result = net.compare(REPO, "a", "b", opener=boom)
        self.assertIsInstance(result, Err)
        self.assertEqual(result.code, 3)

    # --- net.fetch_tarball ------------------------------------------------ #
    def test_fetch_tarball_returns_bytes(self):
        raw = net.fetch_tarball(REPO, CANNED_SHA, opener=self._opener())
        self.assertEqual(raw, _TARBALL)
        # And it is a valid gzip tarball.
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:*") as tar:
            self.assertIn(f"{TARBALL_TOP}/README.md", tar.getnames())

    def test_fetch_tarball_uses_per_call_api_url(self):
        seen = {}

        def capture(request):
            seen["url"] = request.full_url
            return io.BytesIO(_TARBALL)

        raw = net.fetch_tarball(
            REPO,
            CANNED_SHA,
            api_url="https://github.my-company.com/api/v3",
            opener=capture,
        )

        self.assertEqual(raw, _TARBALL)
        self.assertEqual(
            seen["url"],
            f"https://github.my-company.com/api/v3/repos/acme/widgets/tarball/{CANNED_SHA}",
        )

    # --- cache.cache_dir -------------------------------------------------- #
    def test_cache_dir_layout(self):
        path = cache.cache_dir("acme/widgets", CANNED_SHA)
        self.assertTrue(path.endswith(f"agent-artifacts/acme_widgets/{CANNED_SHA}"))
        self.assertNotIn("~", path)

    # --- cache.ensure_snapshot -------------------------------------------- #
    def test_ensure_snapshot_extracts_once_and_strips_top_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = {"n": 0}

            def fetch():
                calls["n"] += 1
                return net.fetch_tarball(REPO, CANNED_SHA, opener=self._opener())

            # Pin the cache root into the temp dir.
            import os

            orig = cache.cache_dir
            dest = os.path.join(tmp, "acme_widgets", CANNED_SHA)
            cache.cache_dir = lambda repo, sha: dest
            try:
                path1 = cache.ensure_snapshot(REPO, CANNED_SHA, fetch)
                path2 = cache.ensure_snapshot(REPO, CANNED_SHA, fetch)
            finally:
                cache.cache_dir = orig

            self.assertEqual(path1, dest)
            self.assertEqual(path2, dest)
            # Extracted exactly once — second call reuses the immutable snapshot.
            self.assertEqual(calls["n"], 1)
            # Top-level <owner>-<repo>-<sha>/ stripped: content sits at the root.
            self.assertTrue(os.path.isdir(os.path.join(dest, "skills", "code-review")))
            self.assertTrue(os.path.isfile(os.path.join(dest, "README.md")))
            self.assertFalse(os.path.exists(os.path.join(dest, TARBALL_TOP)))
            with open(os.path.join(dest, "README.md"), "rb") as fh:
                self.assertEqual(fh.read(), b"hello\n")


if __name__ == "__main__":
    unittest.main()
