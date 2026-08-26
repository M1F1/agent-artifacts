from __future__ import annotations

import unittest
from pathlib import Path

from agent_artifacts import __version__, model, tui, wizard

_ROOT = Path(__file__).resolve().parents[1]
_README = (_ROOT / "README.md").read_text(encoding="utf-8")
_SPELLED = {9: "nine", 10: "ten", 11: "eleven", 12: "twelve"}


class ReadmeAdoptionTest(unittest.TestCase):
    def test_install_grid_covers_three_installers_and_three_checkout_free_sources(self) -> None:
        for installer in ("python -m pip install", "pipx install", "uv tool install"):
            with self.subTest(installer=installer):
                self.assertGreaterEqual(_README.count(installer), 3)
        # Taken from the executable, not written here: a literal passes while the README goes
        # stale, which is exactly how 2.8.0 nearly shipped a matrix still naming 2.7.1.
        for source in (
            f"./agent_artifacts-{__version__}-py3-none-any.whl",
            f"releases/download/v{__version__}/agent_artifacts-{__version__}-py3-none-any.whl",
            f"git+https://github.com/M1F1/agent-artifacts.git@v{__version__}",
        ):
            with self.subTest(source=source):
                self.assertGreaterEqual(_README.count(source), 3)
        self.assertIn("The editable install is for working on AART itself", _README)

    def test_the_enterprise_grid_covers_the_same_three_installers_at_this_version(self) -> None:
        """A private instance narrows the grid, and the narrowing has to be written down.

        Only the Git row carries credentials there: `pip`, `pipx` and `uv` send no token when they
        fetch a URL, so a release asset on a private repository answers with a sign-in page and the
        installer fails on a corrupt archive rather than on a refusal.  A reader who copies the
        public table and swaps the host gets that failure with no clue in it.

        The version comes from the executable for the reason the grid above does: a literal keeps
        passing while the page goes stale.
        """

        start = _README.index("### On a private Enterprise instance")
        section = _README[start : _README.index("The editable install is", start)]
        for installer in ("python -m pip install", "pipx install", "uv tool install"):
            with self.subTest(installer=installer):
                self.assertGreaterEqual(section.count(installer), 3)
        self.assertIn(f"agent-artifacts.git@v{__version__}", section)
        self.assertIn(f'"agent-artifacts=={__version__}"', section)
        self.assertIn(f"./agent_artifacts-{__version__}-py3-none-any.whl", section)
        self.assertIn("not available", section)

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

        The button is the documented route and the script is the same sequence from a terminal, so
        both spellings of the registry choice have to appear -- a release that verifies seven
        checks fewer must be something an operator typed, never something a page implied.
        """

        section = _README[_README.index("## Releasing") : _README.index("## License")]
        for command in (
            "python scripts/version.py set 2.9.0 --write",
            "python scripts/cut_release.py 2.9.0 --registry",
            "python scripts/cut_release.py 2.9.0 --without-registry",
        ):
            with self.subTest(command=command):
                self.assertIn(command, section)
        # The one thing this walk proved the hard way, and the reason a re-run looks like a no-op.
        self.assertIn("read from the tag, not from `main`", section)

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
