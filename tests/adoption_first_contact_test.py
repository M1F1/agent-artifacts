from __future__ import annotations

import unittest
from pathlib import Path

from agent_artifacts import __version__, model, tui, wizard

_ROOT = Path(__file__).resolve().parents[1]
_README = (_ROOT / "README.md").read_text(encoding="utf-8")
_SPELLED = {9: "nine", 10: "ten", 11: "eleven", 12: "twelve"}


class ReadmeAdoptionTest(unittest.TestCase):
    def _install_section(self) -> str:
        start = _README.index("## Install and quick start")
        return _README[start : _README.index("The editable install is", start)]

    def test_the_page_names_no_address_a_fork_would_have_to_correct(self) -> None:
        """The exact commands belong on the release, not here.

        A README cannot know which instance it is being read on -- nothing interpolates a variable
        into a markdown file -- so an address written here is upstream's address, wrong in every
        fork, and a line every fork would have to edit and then re-edit on each merge. The release
        page can know: `cut_release.py` derives it from the remote it is publishing to.
        """

        section = self._install_section()
        for address in ("https://github.com/", "http://", "ghe.corp", "nexus.corp"):
            with self.subTest(address=address):
                self.assertNotIn(address, section)
        # Relative on purpose: it resolves inside whatever repository the file lives in.
        self.assertIn("[Releases page](../../releases)", section)
        self.assertIn("python scripts/install_commands.py", section)

    def test_install_grid_covers_three_installers_against_a_named_placeholder(self) -> None:
        section = self._install_section()
        for installer in ("python -m pip install", "pipx install", "uv tool install"):
            with self.subTest(installer=installer):
                self.assertGreaterEqual(section.count(installer), 3)
        # One placeholder, defined once, used everywhere an address would have gone.
        self.assertIn("`<repository>` is the address of the", section)
        self.assertGreaterEqual(section.count("git+<repository>.git@v"), 3)
        # Taken from the executable, not written here: a literal passes while the README goes
        # stale, which is exactly how 2.8.0 nearly shipped a matrix still naming 2.7.1.  A wheel
        # filename is not an address, so it stays whole.
        self.assertGreaterEqual(section.count(f"./aart_cli-{__version__}-py3-none-any.whl"), 3)
        self.assertIn("The editable install is for working on AART itself", _README)

    def test_the_enterprise_section_still_says_which_sources_stop_working(self) -> None:
        """A private instance narrows the grid, and the narrowing has to be written down.

        Only the Git row carries credentials there: `pip`, `pipx` and `uv` send no token when they
        fetch a URL, so a release asset on a private repository answers with a sign-in page and the
        installer fails on a corrupt archive rather than on a refusal.  A reader who copies the
        public table and swaps the host gets that failure with no clue in it.
        """

        start = _README.index("### On a private Enterprise instance")
        section = _README[start : _README.index("The editable install is", start)]
        self.assertIn(f'"aart-cli=={__version__}"', section)
        self.assertIn("Release wheel by URL", section)
        self.assertIn("**No.**", section)

    def test_the_gate_table_lists_every_gate_the_runner_actually_builds(self) -> None:
        """The heading said nine for as long as there were ten.

        `secret-shape-check` was added and the prose was not, so the page under-reported the work
        by one gate -- harmless in itself, and exactly the drift that makes a reader stop trusting
        the rest of the table.  Reading the names off `build_gates` closes it: a gate added without
        a row fails here.
        """

        import sys

        sys.path.insert(0, str(_ROOT / "scripts"))
        import quality

        names = [gate.name for gate in quality.build_gates(_ROOT / "unused")]
        for name in names:
            with self.subTest(gate=name):
                self.assertIn(f"| `{name}` |", _README)
        self.assertIn(f"### The {_SPELLED[len(names)]} gates", _README)

    def test_the_release_section_names_the_commands_a_release_actually_runs(self) -> None:
        """A release page that has drifted is worse than none: it is followed.

        Both callers of the local half have to be on the page -- a person's bare invocation and
        an agent's, which is the same script with the answers passed in.  So does each spelling of
        the registry choice: a release that verifies seven checks fewer must be something an
        operator typed, never something a page implied.
        """

        section = _README[_README.index("## Releasing") : _README.index("## License")]
        for command in (
            "python scripts/prepare_release.py",
            '--summary "One line about the release." --json',
            "python scripts/cut_release.py 2.9.0 --registry",
            "python scripts/cut_release.py 2.9.0 --without-registry",
        ):
            with self.subTest(command=command):
                self.assertIn(command, section)
        # The one thing this walk proved the hard way, and the reason a re-run looks like a no-op.
        self.assertIn("read from the tag, not from `main`", section)
        # `3` is separate from `2` on purpose, and a caller only knows that if it is written.
        self.assertIn("| `3` |", section)

    def test_registry_entrance_names_vendoring_and_links_the_walked_tutorial(self) -> None:
        for phrase in (
            "`vendor` is the foreign-repository path",
            "`provenance.json`",
            "`revendor`",
            "docs/tutorials/company-registry-tabnine-v1.md",
        ):
            self.assertIn(phrase, _README)


class CollectionVocabularyTest(unittest.TestCase):
    def test_dead_bundle_model_and_tui_vocabulary_are_gone(self) -> None:
        self.assertFalse(hasattr(model, "Bundle"))
        self.assertFalse(hasattr(model, "Catalog"))
        self.assertFalse(hasattr(model, "ResolvedBundle"))
        self.assertEqual(
            wizard.BasketItem("collection", "company/collection/base", "base").kind,
            "collection",
        )
        choice = tui._Choice("collection", "base", None, "base")
        self.assertEqual(tui._basket_item(choice).kind, "collection")
        self.assertEqual(tui._choice_label("collection", "base", None, ""), "[collection] base")


if __name__ == "__main__":
    unittest.main()
