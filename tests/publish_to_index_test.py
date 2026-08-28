"""Publishing a wheel describes the wheel, and a refusal is quoted rather than summarised.

The upload is one HTTP POST written against the standard library, because `twine` would be the
fourth program this project assumed was installed and was not -- after Make, `gh` and `curl`.
What the POST carries has to be right, and "right" here means two things: every field is read out
of the wheel rather than restated, and every digest describes the bytes that actually travelled.
"""

from __future__ import annotations

import base64
import email
import hashlib
import io
import unittest
import urllib.error
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from tests.versioning_test import _load_script

publish_to_index = _load_script("publish_to_index")

_METADATA = """Metadata-Version: 2.1
Name: agent-artifacts
Version: 9.9.9
Summary: A summary only the wheel knows.

"""


def _wheel(directory: Path, name: str = "agent_artifacts-9.9.9-py3-none-any.whl") -> Path:
    """A wheel is a zip with a `.dist-info/`, and that is all this needs to be one."""

    path = directory / name
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("agent_artifacts/__init__.py", "# nothing\n")
        archive.writestr("agent_artifacts-9.9.9.dist-info/METADATA", _METADATA)
    return path


def _parts(payload: bytes, boundary: str) -> dict[str, tuple[str | None, bytes]]:
    """The multipart body, parsed the way a server parses it: field -> (filename, bytes)."""

    message = email.message_from_bytes(
        f'Content-Type: multipart/form-data; boundary="{boundary}"\r\n\r\n'.encode() + payload
    )
    found: dict[str, tuple[str | None, bytes]] = {}
    for part in message.get_payload():
        name = part.get_param("name", header="content-disposition")
        found[str(name)] = (part.get_filename(), part.get_payload(decode=True))
    return found


class FieldsComeFromTheWheelTest(unittest.TestCase):
    def test_what_is_claimed_about_the_file_is_read_out_of_the_file(self) -> None:
        """A field restated here could disagree with the wheel, and nothing would notice."""

        with TemporaryDirectory() as held:
            fields = dict(publish_to_index.form(_wheel(Path(held))))

        self.assertEqual(fields["name"], "agent-artifacts")
        self.assertEqual(fields["version"], "9.9.9")
        self.assertEqual(fields["summary"], "A summary only the wheel knows.")
        self.assertEqual(fields["metadata_version"], "2.1")
        # The interpreter tag is a property of the filename, not of the metadata.
        self.assertEqual(fields["pyversion"], "py3")
        self.assertEqual(fields[":action"], "file_upload")
        self.assertEqual(fields["protocol_version"], "1")
        self.assertEqual(fields["filetype"], "bdist_wheel")

    def test_a_wheel_missing_its_metadata_is_refused_by_name(self) -> None:
        with TemporaryDirectory() as held:
            directory = Path(held)
            path = directory / "agent_artifacts-9.9.9-py3-none-any.whl"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("agent_artifacts/__init__.py", "")
            with self.assertRaises(publish_to_index.PublishError) as refusal:
                publish_to_index.form(path)
        self.assertIn("METADATA", str(refusal.exception))

    def test_a_dist_holding_two_wheels_is_refused_rather_than_guessed(self) -> None:
        """Picking one of two would publish the wrong version quietly, which is the worst kind."""

        with TemporaryDirectory() as held:
            directory = Path(held)
            (directory / "dist").mkdir()
            _wheel(directory / "dist")
            _wheel(directory / "dist", "agent_artifacts-9.9.8-py3-none-any.whl")
            with self.assertRaises(publish_to_index.PublishError) as refusal:
                publish_to_index.wheel(directory)
        message = str(refusal.exception)
        self.assertIn("9.9.8", message)
        self.assertIn("9.9.9", message)


class TheBodyDescribesTheBytesSentTest(unittest.TestCase):
    def test_every_digest_is_of_the_file_in_the_same_request(self) -> None:
        with TemporaryDirectory() as held:
            path = _wheel(Path(held))
            on_disk = path.read_bytes()
            payload = publish_to_index.body(publish_to_index.form(path), path, "aboundary")

        parts = _parts(payload, "aboundary")
        filename, content = parts["content"]
        self.assertEqual(filename, "agent_artifacts-9.9.9-py3-none-any.whl")
        # The file that travelled is the file on disk, byte for byte -- not merely one of its size.
        self.assertEqual(content, on_disk)
        self.assertEqual(parts["sha256_digest"][1].decode(), hashlib.sha256(content).hexdigest())
        self.assertEqual(parts["md5_digest"][1].decode(), hashlib.md5(content).hexdigest())  # noqa: S324
        self.assertEqual(
            parts["blake2_256_digest"][1].decode(),
            hashlib.blake2b(content, digest_size=32).hexdigest(),
        )


class TheCredentialStaysOutOfSightTest(unittest.TestCase):
    def test_it_is_read_from_the_environment_and_never_taken_as_an_argument(self) -> None:
        """An argument is visible in a process list and kept in shell history."""

        source = Path(publish_to_index.__file__).read_text(encoding="utf-8")
        self.assertNotIn('add_argument("--credentials"', source)
        self.assertNotIn('add_argument("--password"', source)

        with mock.patch.dict("os.environ", {"AART_INDEX_PUBLISH_CREDENTIALS": "who:what"}):
            header = publish_to_index.credentials()
        self.assertEqual(base64.b64decode(header.removeprefix("Basic ")).decode(), "who:what")

    def test_a_missing_credential_names_the_variable_and_what_it_holds(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(publish_to_index.PublishError) as refusal:
                publish_to_index.credentials()
        message = str(refusal.exception)
        self.assertIn("AART_INDEX_PUBLISH_CREDENTIALS", message)
        self.assertIn("colon", message)


class ARefusalIsQuotedTest(unittest.TestCase):
    """An index refuses for reasons worth reading, and `HTTP Error 400` throws all of them away."""

    def test_the_index_own_words_reach_the_log(self) -> None:
        said = "Repository does not allow updating assets: pypi-internal"
        error = urllib.error.HTTPError(
            "https://nexus.example.org/repository/pypi-internal/",
            400,
            "Bad Request",
            {},  # type: ignore[arg-type]
            io.BytesIO(said.encode()),
        )
        with TemporaryDirectory() as held:
            directory = Path(held)
            path = _wheel(directory)
            with mock.patch.dict("os.environ", {"AART_INDEX_PUBLISH_CREDENTIALS": "who:what"}):
                with mock.patch.object(
                    publish_to_index.urllib.request, "urlopen", side_effect=error
                ):
                    with self.assertRaises(publish_to_index.PublishError) as refusal:
                        publish_to_index.publish("https://nexus.example.org/repository/x/", path)

        message = str(refusal.exception)
        self.assertIn(said, message)
        self.assertIn("400", message)

    def test_an_index_that_cannot_be_reached_says_so_rather_than_tracing(self) -> None:
        with TemporaryDirectory() as held:
            directory = Path(held)
            path = _wheel(directory)
            with mock.patch.dict("os.environ", {"AART_INDEX_PUBLISH_CREDENTIALS": "who:what"}):
                with mock.patch.object(
                    publish_to_index.urllib.request,
                    "urlopen",
                    side_effect=urllib.error.URLError("certificate verify failed"),
                ):
                    with self.assertRaises(publish_to_index.PublishError) as refusal:
                        publish_to_index.publish("https://nexus.example.org/repository/x/", path)
        self.assertIn("certificate verify failed", str(refusal.exception))


if __name__ == "__main__":
    unittest.main()
