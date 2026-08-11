"""Sanity checks for intentionally small legacy-catalog fixtures.

Operational artifacts belong to configured external sources and registries, never to the
executable AART checkout.  These fixtures retain the legacy 0.1 format required to exercise
the importer and compatibility adapters without turning the tool repository into a catalog.
"""

from __future__ import annotations

import json
import pathlib
import unittest

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"


def _read_text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_json(path: pathlib.Path) -> dict[str, object]:
    return json.loads(_read_text(path))


class LegacyCatalogFixtureTests(unittest.TestCase):
    """Keep fixture content valid while enforcing the code-only repository boundary."""

    def test_mcp_descriptors_are_directory_shaped_and_well_formed(self) -> None:
        descriptors = tuple(sorted((FIXTURES / "mcp").glob("*/mcp.json")))
        self.assertGreater(len(descriptors), 0, "No legacy MCP fixture descriptors found")
        for descriptor in descriptors:
            with self.subTest(descriptor=descriptor):
                data = _load_json(descriptor)
                self.assertEqual(data["name"], descriptor.parent.name)
                self.assertIsInstance(data.get("description"), str)
                server = data.get("server")
                self.assertIsInstance(server, dict)
                assert isinstance(server, dict)
                self.assertTrue("command" in server or "url" in server)

    def test_hook_descriptors_reference_their_payload_files(self) -> None:
        descriptors = tuple(sorted((FIXTURES / "hooks").glob("*/hook.json")))
        self.assertGreater(len(descriptors), 0, "No legacy hook fixture descriptors found")
        for descriptor in descriptors:
            with self.subTest(descriptor=descriptor):
                data = _load_json(descriptor)
                self.assertEqual(data["name"], descriptor.parent.name)
                self.assertIsInstance(data.get("description"), str)
                self.assertIsInstance(data.get("events"), list)
                self.assertTrue(data["events"])
                self.assertIsInstance(data.get("command"), str)
                files = data.get("files", [])
                self.assertIsInstance(files, list)
                assert isinstance(files, list)
                for relative in files:
                    self.assertIsInstance(relative, str)
                    assert isinstance(relative, str)
                    self.assertTrue(
                        (descriptor.parent / relative).is_file(),
                        f"missing fixture payload {relative!r}",
                    )

    def test_skill_and_memory_fixtures_have_expected_frontmatter(self) -> None:
        expected_fields = {
            FIXTURES / "skills" / "code-review" / "SKILL.md": ("name:", "description:"),
            FIXTURES / "memory" / "house.md": ("description:",),
        }
        for path, fields in expected_fields.items():
            with self.subTest(path=path):
                text = _read_text(path)
                self.assertTrue(text.startswith("---"))
                for field in fields:
                    self.assertIn(field, text)

    def test_legacy_bundles_reference_available_legacy_fixture_content(self) -> None:
        bundle_paths = tuple(sorted((FIXTURES / "bundles").glob("*.json")))
        bundles = {path.stem: _load_json(path) for path in bundle_paths}
        self.assertGreater(len(bundles), 0, "No legacy bundle fixtures found")
        artifact_paths = {
            "skills": lambda name: FIXTURES / "skills" / name / "SKILL.md",
            "guidelines": lambda name: FIXTURES / "guidelines" / f"{name}.md",
            "mcp": lambda name: FIXTURES / "mcp" / name / "mcp.json",
            "hooks": lambda name: FIXTURES / "hooks" / name / "hook.json",
            "memory": lambda name: FIXTURES / "memory" / f"{name}.md",
        }
        for name, bundle in bundles.items():
            with self.subTest(bundle=name):
                self.assertEqual(bundle["name"], name)
                self.assertIsInstance(bundle.get("description"), str)
                extends = bundle.get("extends", [])
                self.assertIsInstance(extends, list)
                assert isinstance(extends, list)
                for parent in extends:
                    self.assertIn(parent, bundles)
                includes = bundle.get("includes", {})
                self.assertIsInstance(includes, dict)
                assert isinstance(includes, dict)
                for artifact_type, artifact_names in includes.items():
                    self.assertIn(artifact_type, artifact_paths)
                    assert isinstance(artifact_type, str)
                    self.assertIsInstance(artifact_names, list)
                    assert isinstance(artifact_names, list)
                    for artifact_name in artifact_names:
                        self.assertIsInstance(artifact_name, str)
                        assert isinstance(artifact_name, str)
                        self.assertTrue(
                            artifact_paths[artifact_type](artifact_name).is_file(),
                            f"{name} references missing {artifact_type}/{artifact_name}",
                        )


if __name__ == "__main__":
    unittest.main()
