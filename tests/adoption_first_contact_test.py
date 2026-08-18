from __future__ import annotations

import unittest
from pathlib import Path

from agent_artifacts import model, tui, wizard

_ROOT = Path(__file__).resolve().parents[1]
_README = (_ROOT / "README.md").read_text(encoding="utf-8")


class ReadmeAdoptionTest(unittest.TestCase):
    def test_install_grid_covers_three_installers_and_three_checkout_free_sources(self) -> None:
        for installer in ("python -m pip install", "pipx install", "uv tool install"):
            with self.subTest(installer=installer):
                self.assertGreaterEqual(_README.count(installer), 3)
        for source in (
            "./agent_artifacts-2.7.1-py3-none-any.whl",
            "releases/download/v2.7.1/agent_artifacts-2.7.1-py3-none-any.whl",
            "git+https://github.com/M1F1/agent-artifacts.git@v2.7.1",
        ):
            with self.subTest(source=source):
                self.assertGreaterEqual(_README.count(source), 3)
        self.assertIn("The editable install is for working on AART itself", _README)

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
