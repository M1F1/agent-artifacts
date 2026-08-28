"""The install commands name the repository they are printed for, and never a written-down one."""

from __future__ import annotations

import contextlib
import unittest
from unittest import mock

from tests.versioning_test import ROOT, _load_script

install_commands = _load_script("install_commands")
github_api = _load_script("github_api")


class LinesTest(unittest.TestCase):
    def test_the_commands_name_the_instance_they_were_asked_about(self) -> None:
        block = install_commands.lines("https://ghe.example.org/platform/aart", "2.9.0")

        pin = '"git+https://ghe.example.org/platform/aart.git@v2.9.0"'
        for command in (
            f"pipx install {pin}",
            f"python -m pip install --no-deps {pin}",
            f"uv tool install {pin}",
        ):
            with self.subTest(command=command):
                self.assertIn(command, block)
        self.assertIn("aart_cli-2.9.0-py3-none-any.whl", block)
        # github.com must not leak into a block asked for about somewhere else.
        self.assertNotIn("github.com", block)

    def test_the_url_row_carries_the_warning_that_belongs_with_it(self) -> None:
        """The failure it prevents names neither its cause nor its fix.

        `pip`, `pipx` and `uv` send no token when they fetch a URL, so a release asset on a private
        instance answers with a sign-in page and the installer reports a corrupt archive.
        """

        block = install_commands.lines("https://ghe.example.org/platform/aart", "2.9.0")
        self.assertIn("send no token", block)
        self.assertIn("sign-in page", block)


class RepositoryUrlTest(unittest.TestCase):
    def test_an_instance_and_github_com_are_told_apart(self) -> None:
        with mock.patch.object(
            github_api, "origin", return_value=("https://api.github.com", "M1F1/agent-artifacts")
        ):
            self.assertEqual(github_api.repository_url(), "https://github.com/M1F1/agent-artifacts")
        with mock.patch.object(
            github_api, "origin", return_value=("https://ghe.example.org/api/v3", "platform/aart")
        ):
            self.assertEqual(github_api.repository_url(), "https://ghe.example.org/platform/aart")


class ReleaseBodyTest(unittest.TestCase):
    def test_the_release_body_carries_the_commands_for_that_repository(self) -> None:
        """A README cannot say this and a release can, so the release is where it is said."""

        cut_release = _load_script("cut_release")
        notes = ROOT / "docs" / "release" / "github-release-v2.8.5.md"
        published: dict = {}

        def record(url: str, **keywords: object) -> dict:
            published.update(keywords["payload"])  # type: ignore[arg-type]
            return {"html_url": "u"}

        patches = (
            mock.patch.object(cut_release, "_git"),
            mock.patch.object(
                cut_release.release_module, "wheel_digest", return_value=("w.whl", "sha256:0")
            ),
            mock.patch.object(
                cut_release.github_api,
                "origin",
                return_value=("https://ghe.example.org/api/v3", "platform/aart"),
            ),
            mock.patch.object(cut_release.github_api, "token", return_value="t"),
            mock.patch.object(cut_release.github_api, "json_request", side_effect=record),
        )
        with contextlib.ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            cut_release.publish("v2.8.5", "2.8.5", notes, "origin")

        self.assertIn(
            'pipx install "git+https://ghe.example.org/platform/aart.git@v2.8.5"',
            published["body"],
        )


if __name__ == "__main__":
    unittest.main()
