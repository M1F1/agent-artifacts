"""Where each heading lands, and what stops a placeholder from shipping.

The point of the script is not typing speed.  It is that the four documents a release needs get
their sections in the right places, in the right order, without anyone holding the layout in their
head -- and that the gaps it leaves are visible enough to be caught before they are published.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import release_docs  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _fixture(raw: str) -> Path:
    root = Path(raw)
    (root / "scripts").mkdir()
    (root / "scripts" / "release.py").write_text(
        "RELEASE_CONTRACT_VERSION = 18\n", encoding="utf-8"
    )
    (root / "docs" / "release").mkdir(parents=True)
    (root / "CHANGELOG.md").write_text(
        "# Changelog\n\nA preamble that is not a release section.\n\n"
        "## 2.8.5 — 2026-08-21\n\nThe previous release.\n",
        encoding="utf-8",
    )
    for name in ("compatibility-v18.md", "release-checklist-v18.md"):
        (root / "docs" / "release" / name).write_text(
            f"# AART v18 {name} — 2.8.0 through 2.8.5\n\nThe 2.8.5 record.\n", encoding="utf-8"
        )
    return root


class PlacementTest(unittest.TestCase):
    def test_the_changelog_entry_goes_above_the_previous_release_not_at_the_end(self) -> None:
        """A changelog reads newest first, and a section appended to the end reads as oldest."""

        with tempfile.TemporaryDirectory() as raw:
            root = _fixture(raw)
            for document in release_docs.plan("2.8.6", "A headline.", root):
                release_docs.apply(document, "2.8.6")

            text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
            self.assertLess(text.index("## 2.8.6"), text.index("## 2.8.5"))
            # And below the file's own preamble, which is not a release section.
            self.assertLess(text.index("A preamble"), text.index("## 2.8.6"))

    def test_only_the_upper_bound_of_the_span_moves(self) -> None:
        """`2.8.0 through 2.8.5` becomes `through 2.8.6`.

        The lower bound is the release the contract opened with.  It is not this release's to
        rewrite, for the same reason the dated sections below it are appended to rather than
        edited: a dated record is not changed to agree with today.
        """

        with tempfile.TemporaryDirectory() as raw:
            root = _fixture(raw)
            for document in release_docs.plan("2.8.6", "A headline.", root):
                release_docs.apply(document, "2.8.6")

            title = (root / "docs" / "release" / "compatibility-v18.md").read_text(encoding="utf-8")
            self.assertIn("2.8.0 through 2.8.6", title)
            self.assertIn("The 2.8.5 record.", title)

    def test_running_it_twice_changes_nothing(self) -> None:
        """A half-written document must survive a second run; overwriting it would lose prose."""

        with tempfile.TemporaryDirectory() as raw:
            root = _fixture(raw)
            for document in release_docs.plan("2.8.6", "A headline.", root):
                release_docs.apply(document, "2.8.6")
            notes = root / "docs" / "release" / "github-release-v2.8.6.md"
            notes.write_text("# AART 2.8.6\n\nProse someone wrote.\n", encoding="utf-8")
            before = (root / "CHANGELOG.md").read_bytes()

            for document in release_docs.plan("2.8.6", "A headline.", root):
                release_docs.apply(document, "2.8.6")

            self.assertEqual((root / "CHANGELOG.md").read_bytes(), before)
            self.assertIn("Prose someone wrote.", notes.read_text(encoding="utf-8"))


class OpenMarkerTest(unittest.TestCase):
    def test_the_placeholders_are_visible_text_not_an_html_comment(self) -> None:
        """A placeholder that renders invisibly is a placeholder that ships."""

        with tempfile.TemporaryDirectory() as raw:
            root = _fixture(raw)
            for document in release_docs.plan("2.8.6", "A headline.", root):
                release_docs.apply(document, "2.8.6")

            open_ones = release_docs.open_markers("2.8.6", root)
            self.assertTrue(open_ones)
            for line in open_ones:
                self.assertIn("TODO(2.8.6)", line)
                self.assertNotIn("<!--", line)

    def test_a_finished_set_reports_nothing_open(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = _fixture(raw)
            for document in release_docs.plan("2.8.6", "A headline.", root):
                release_docs.apply(document, "2.8.6")
            for document in release_docs.plan("2.8.6", "", root):
                text = document.path.read_text(encoding="utf-8")
                kept = [line for line in text.splitlines() if "TODO(2.8.6)" not in line]
                document.path.write_text("\n".join(kept) + "\n", encoding="utf-8")

            self.assertEqual(release_docs.open_markers("2.8.6", root), ())


class ContractTest(unittest.TestCase):
    def test_the_contract_version_is_read_from_the_release_script(self) -> None:
        """Written down twice, the two spellings drift; the checklist owns this number."""

        self.assertEqual(release_docs.contract_version(ROOT), "18")


if __name__ == "__main__":
    unittest.main()
