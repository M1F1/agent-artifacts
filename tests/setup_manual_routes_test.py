"""ERR09-D: representative v2 packages and the three manual routes they can produce."""

from __future__ import annotations

import pathlib
import unittest

from agent_artifacts.model import Ok, Request
from agent_artifacts.setup import build_queue, manual_reference, render_manual_alternative
from agent_artifacts.source import open_source

FIXTURE_ROOT = pathlib.Path(__file__).resolve().parent / "fixtures" / "setup-routes"
PINNED = "https://github.com/acme/catalog/blob/" + "0" * 40


class SetupManualRouteFixtureTests(unittest.TestCase):
    def catalog(self):
        result = open_source(Request(command="list", source_dir=str(FIXTURE_ROOT))).value.catalog()
        assert isinstance(result, Ok), getattr(result, "reason", "")
        return result.value

    def queue(self, key: tuple[str, str], *, source_url: str):
        artifact = self.catalog().artifacts[key]
        return build_queue(
            (artifact,),
            ("claude",),
            scope="project",
            source_label="pin:0000000",
            source_root=str(FIXTURE_ROOT),
            source_url=source_url,
        )

    def test_representative_packages_are_valid_v2_sources_that_are_never_executed(self) -> None:
        catalog = self.catalog()

        static = catalog.artifacts[("mcp", "atlassian")].setup
        custom = catalog.artifacts[("skill", "onboarding")].setup

        assert static is not None and custom is not None
        self.assertEqual(static.protocol_version, 2)
        self.assertEqual(custom.protocol_version, 2)
        self.assertIsNone(static.custom_entrypoint)
        self.assertEqual(custom.custom_entrypoint, "install.sh")
        self.assertEqual(static.manual_path, "mcp/atlassian/SETUP.md")
        self.assertEqual(custom.manual_path, "skills/onboarding/SETUP.md")

    def test_static_mcp_route_is_the_commit_pinned_document_of_the_reviewed_source(self) -> None:
        (item,) = self.queue(("mcp", "atlassian"), source_url=PINNED)

        reference = manual_reference(item)

        self.assertEqual(reference.relative_path, "mcp/atlassian/SETUP.md")
        self.assertEqual(reference.source, f"{PINNED}/mcp/atlassian/SETUP.md")
        rendered = "\n".join(render_manual_alternative(reference))
        self.assertIn("Manual alternative", rendered)
        self.assertIn("No setup effect has run.", rendered)

    def test_custom_non_mcp_route_is_the_same_package_document(self) -> None:
        (item,) = self.queue(("skill", "onboarding"), source_url=PINNED)

        reference = manual_reference(item)

        self.assertEqual(reference.relative_path, "skills/onboarding/SETUP.md")
        self.assertEqual(reference.source, f"{PINNED}/skills/onboarding/SETUP.md")

    def test_an_unpinned_source_falls_back_to_the_contained_local_document(self) -> None:
        (item,) = self.queue(("mcp", "atlassian"), source_url="")

        reference = manual_reference(item)

        self.assertEqual(reference.relative_path, "mcp/atlassian/SETUP.md")
        self.assertEqual(reference.source, str(FIXTURE_ROOT / "mcp" / "atlassian" / "SETUP.md"))
        self.assertTrue(pathlib.Path(reference.source).is_file())

    def test_every_representative_document_is_readable_prose_without_a_credential(self) -> None:
        documents = sorted(FIXTURE_ROOT.rglob("SETUP.md"))

        self.assertEqual(len(documents), 2)
        for document in documents:
            with self.subTest(document=document.name):
                text = document.read_text(encoding="utf-8")
                self.assertTrue(text.strip())
                for shape in ("token=", "password=", "secret=", "api_key="):
                    self.assertNotIn(shape, text.casefold())


if __name__ == "__main__":
    unittest.main()
