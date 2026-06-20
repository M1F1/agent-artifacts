"""WP-16 tests: the ``check`` command (remote freshness, fail-soft).

No live network. A fake ``opener`` (an ``(urllib.request.Request) -> file-like`` callable)
serves canned ``commits/<ref>`` and ``compare/<base>...<head>`` JSON, exactly like the
contract in ``agent_artifacts.io.net``. A temp project carries a manifest installed from an
older base SHA so the compare reports real movement.

Run: ``python -m unittest discover -s tests -p "check_test.py" -v``
"""

import io
import json
import os
import tempfile
import unittest
import urllib.error

from agent_artifacts.commands import check
from agent_artifacts.manifest import dump_manifest
from agent_artifacts.model import Manifest, ManifestEntry, Request

OLD_BASE = "0000000000000000000000000000000000000000"
HEAD_SHA = "ffffffffffffffffffffffffffffffffffffffff"
REPO = "org/agent-artifacts"


class _Resp(io.BytesIO):
    """A ``BytesIO`` that is also a context manager — matches the net.opener contract."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _fake_opener(commit_json: bytes, compare_json: bytes):
    """Route ``/commits/`` -> commit_json and ``/compare/`` -> compare_json; everything else 404s."""

    def opener(request):
        url = request.full_url
        if "/commits/" in url:
            return _Resp(commit_json)
        if "/compare/" in url:
            return _Resp(compare_json)
        raise urllib.error.HTTPError(url, 404, "not found", {}, None)

    return opener


def _commit_json(sha: str = HEAD_SHA) -> bytes:
    return json.dumps({"sha": sha}).encode()


def _compare_json(*filenames: str) -> bytes:
    return json.dumps({"files": [{"filename": f} for f in filenames]}).encode()


class CheckTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def _write_manifest(self, *entries: ManifestEntry) -> None:
        path = os.path.join(self.project, ".agent-artifacts", "manifest.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        manifest = Manifest(repo=REPO, installed=tuple(entries))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(dump_manifest(manifest))

    def _request(self, *, json_out: bool = False) -> Request:
        return Request(command="check", repo=REPO, project=self.project, json=json_out)

    def _entry(self, **kw) -> ManifestEntry:
        base = dict(
            artifact="code-review",
            type="skill",
            profile="claude",
            source=f"main:{OLD_BASE}",
            files={".claude/skills/code-review/SKILL.md": "sha256:x"},
            installed_at="2026-01-01T00:00:00Z",
        )
        base.update(kw)
        return ManifestEntry(**base)

    # --- happy path: artifact moved + CLI moved --------------------------- #
    def test_reports_changed_artifact_and_cli_moved(self):
        self._write_manifest(self._entry())
        opener = _fake_opener(
            _commit_json(HEAD_SHA),
            _compare_json("skills/code-review/SKILL.md", "agent_artifacts/cli.py"),
        )
        out = io.StringIO()
        import contextlib

        with contextlib.redirect_stdout(out):
            rc = check._check(self._request(json_out=True), opener=opener)

        self.assertEqual(rc, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["repo"], REPO)
        self.assertEqual(payload["head"], HEAD_SHA)
        self.assertEqual(payload["artifacts_changed"], ["skills/code-review"])
        self.assertTrue(payload["cli_changed"])
        self.assertIn("agent-artifacts update", payload["suggestion"])
        self.assertIn("agent-artifacts upgrade", payload["suggestion"])

    # --- artifact NOT among installed -> not reported --------------------- #
    def test_unrelated_artifact_change_is_ignored(self):
        self._write_manifest(self._entry())
        opener = _fake_opener(
            _commit_json(HEAD_SHA),
            _compare_json("skills/some-other-skill/SKILL.md"),
        )
        out = io.StringIO()
        import contextlib

        with contextlib.redirect_stdout(out):
            rc = check._check(self._request(json_out=True), opener=opener)

        self.assertEqual(rc, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["artifacts_changed"], [])
        # The CLI build commit is "unknown" for a dev install, so it differs from head.
        self.assertTrue(payload["cli_changed"])

    # --- everything already at head: no compare needed -------------------- #
    def test_installed_at_head_no_artifacts_changed(self):
        self._write_manifest(self._entry(source=f"main:{HEAD_SHA}"))

        def opener(request):
            url = request.full_url
            if "/commits/" in url:
                return _Resp(_commit_json(HEAD_SHA))
            raise AssertionError(f"compare should not be called: {url}")

        out = io.StringIO()
        import contextlib

        with contextlib.redirect_stdout(out):
            rc = check._check(self._request(json_out=True), opener=opener)

        self.assertEqual(rc, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["artifacts_changed"], [])

    # --- fail-soft: resolve_ref network error ----------------------------- #
    def test_failsoft_on_resolve_ref_error(self):
        self._write_manifest(self._entry())

        def boom(request):
            raise urllib.error.URLError("connection refused")

        err = io.StringIO()
        import contextlib

        with contextlib.redirect_stderr(err):
            rc = check._check(self._request(), opener=boom)

        self.assertEqual(rc, 3)
        lines = [ln for ln in err.getvalue().splitlines() if ln.strip()]
        self.assertEqual(len(lines), 1)
        self.assertIn("check:", lines[0])

    # --- fail-soft: compare network error --------------------------------- #
    def test_failsoft_on_compare_error(self):
        self._write_manifest(self._entry())

        def opener(request):
            url = request.full_url
            if "/commits/" in url:
                return _Resp(_commit_json(HEAD_SHA))
            raise urllib.error.URLError("dns failure")

        err = io.StringIO()
        import contextlib

        with contextlib.redirect_stderr(err):
            rc = check._check(self._request(), opener=opener)

        self.assertEqual(rc, 3)
        lines = [ln for ln in err.getvalue().splitlines() if ln.strip()]
        self.assertEqual(len(lines), 1)

    # --- run() delegates to _check (no live network) ---------------------- #
    def test_run_delegates_to_check(self):
        # Stub net.resolve_ref so run() exercises the fail-soft path without any socket.
        self._write_manifest(self._entry())
        from agent_artifacts.io import net
        from agent_artifacts.model import Err

        orig = net.resolve_ref
        net.resolve_ref = lambda repo, ref, token=None, opener=None: Err("offline", code=3)
        err = io.StringIO()
        import contextlib

        try:
            with contextlib.redirect_stderr(err):
                rc = check.run(self._request())
        finally:
            net.resolve_ref = orig

        self.assertEqual(rc, 3)
        self.assertIn("check:", err.getvalue())

    # --- human (non-JSON) summary path also returns 0 --------------------- #
    def test_text_summary_returns_zero(self):
        self._write_manifest(self._entry())
        opener = _fake_opener(
            _commit_json(HEAD_SHA),
            _compare_json("skills/code-review/SKILL.md"),
        )
        out = io.StringIO()
        import contextlib

        with contextlib.redirect_stdout(out):
            rc = check._check(self._request(json_out=False), opener=opener)

        self.assertEqual(rc, 0)
        text = out.getvalue()
        self.assertIn("skills/code-review", text)
        self.assertIn(HEAD_SHA, text)


if __name__ == "__main__":
    unittest.main()
