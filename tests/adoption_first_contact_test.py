from __future__ import annotations

import unittest
from pathlib import Path

from agent_artifacts import __version__, model, tui, wizard

_ROOT = Path(__file__).resolve().parents[1]
_README = (_ROOT / "README.md").read_text(encoding="utf-8")


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
