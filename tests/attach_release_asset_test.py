"""What the attach step reads rather than guesses, and what it does when told no.

The step is small, but it is the last one in a release and it has already failed twice on a real
Enterprise instance for reasons no test could have caught -- a missing `gh`, then a missing `curl`.
What a test *can* hold is the part that is logic rather than tooling: that the upload host comes
out of the release object instead of being assembled from the API host, that a same-named asset is
replaced rather than collided with, and that a refusal reaches the log with the API's own words.
"""

from __future__ import annotations

import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import attach_release_asset  # noqa: E402

API = "https://ghe.example/api/v3"
UPLOAD = "https://uploads.ghe.example/repos/org/aart/releases/7/assets"
WHEEL = "agent_artifacts-2.8.5-py3-none-any.whl"

ENVIRONMENT = {
    "GITHUB_API_URL": API,
    "GITHUB_REPOSITORY": "org/aart",
    "GITHUB_TOKEN": "unused-by-the-fake",
}


def _release(assets: tuple[dict[str, object], ...] = ()) -> bytes:
    return json.dumps({"upload_url": UPLOAD + "{?name,label}", "assets": list(assets)}).encode()


class _Calls:
    """A stand-in for `urlopen` that records the request and replays a queued response."""

    def __init__(self, *responses: bytes) -> None:
        self.responses = list(responses)
        self.seen: list[tuple[str, str, int]] = []

    def __call__(self, request, *_args, **_kwargs):  # noqa: ANN001 - urllib's own shape
        body = request.data or b""
        self.seen.append((request.get_method(), request.full_url, len(body)))
        payload = self.responses.pop(0) if self.responses else b""
        return io.BytesIO(payload)


class AttachTest(unittest.TestCase):
    def setUp(self) -> None:
        self.wheel = mock.patch.object(attach_release_asset, "_wheel", lambda: _StubWheel())
        self.wheel.start()
        self.addCleanup(self.wheel.stop)

    def test_the_upload_host_comes_from_the_release_not_the_api_url(self) -> None:
        """On an Enterprise instance uploads land on a hostname of their own.

        Assembling the address from `GITHUB_API_URL` works on github.com and fails everywhere
        else, which is the worst possible split: it passes on the machine that wrote it.
        """

        calls = _Calls(_release())
        with mock.patch.dict("os.environ", ENVIRONMENT, clear=False):
            with mock.patch("urllib.request.urlopen", calls):
                attach_release_asset.main(["attach", "v2.8.5"])

        methods = [method for method, _url, _size in calls.seen]
        self.assertEqual(methods, ["GET", "POST"])
        self.assertEqual(calls.seen[0][1], f"{API}/repos/org/aart/releases/tags/v2.8.5")
        # The template suffix is dropped and the name goes on as a query, not as a path segment.
        self.assertEqual(calls.seen[1][1], f"{UPLOAD}?name={WHEEL}")
        self.assertEqual(calls.seen[1][2], len(b"wheel bytes"))

    def test_an_asset_of_the_same_name_is_replaced_rather_than_collided_with(self) -> None:
        """This is the whole of what `--clobber` was doing, and why a re-run is not a dead end."""

        calls = _Calls(_release(({"id": 42, "name": WHEEL},)), b"", b"")
        with mock.patch.dict("os.environ", ENVIRONMENT, clear=False):
            with mock.patch("urllib.request.urlopen", calls):
                attach_release_asset.main(["attach", "v2.8.5"])

        self.assertEqual([method for method, _u, _s in calls.seen], ["GET", "DELETE", "POST"])
        self.assertEqual(calls.seen[1][1], f"{API}/repos/org/aart/releases/assets/42")

    def test_a_differently_named_asset_is_left_alone(self) -> None:
        calls = _Calls(_release(({"id": 42, "name": "notes.txt"},)))
        with mock.patch.dict("os.environ", ENVIRONMENT, clear=False):
            with mock.patch("urllib.request.urlopen", calls):
                attach_release_asset.main(["attach", "v2.8.5"])

        self.assertNotIn("DELETE", [method for method, _u, _s in calls.seen])

    def test_a_refusal_reaches_the_log_with_the_api_s_own_words(self) -> None:
        """The lesson this walk taught three separate times: print what the other side said."""

        def refuse(request, *_args, **_kwargs):  # noqa: ANN001 - urllib's own shape
            raise urllib.error.HTTPError(
                request.full_url, 404, "Not Found", {}, io.BytesIO(b'{"message":"Not Found"}')
            )

        with mock.patch.dict("os.environ", ENVIRONMENT, clear=False):
            with mock.patch("urllib.request.urlopen", refuse):
                with self.assertRaises(SystemExit) as raised:
                    attach_release_asset.main(["attach", "v2.8.5"])

        said = str(raised.exception)
        self.assertIn("404", said)
        self.assertIn("Not Found", said)
        self.assertIn("releases/tags/v2.8.5", said)

    def test_a_missing_environment_names_what_is_missing(self) -> None:
        with mock.patch.dict("os.environ", {**ENVIRONMENT, "GITHUB_TOKEN": ""}, clear=False):
            with self.assertRaises(SystemExit) as raised:
                attach_release_asset.main(["attach", "v2.8.5"])
        self.assertIn("GITHUB_TOKEN", str(raised.exception))


class _StubWheel:
    name = WHEEL

    def read_bytes(self) -> bytes:
        return b"wheel bytes"

    def stat(self):  # noqa: ANN201 - only `st_size` is read
        return type("Stat", (), {"st_size": len(b"wheel bytes")})()


if __name__ == "__main__":
    unittest.main()
