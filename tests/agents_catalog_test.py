"""WP-26 unit tests: `agents` catalog parsing, bundle resolution & source scan.

Covers (PLAN-agents.md WP-26 "Done when"):

* ``catalog.parse_agents`` — valid (no frontmatter), valid (matching name + valid mode),
  name mismatch → Err, invalid mode → Err.
* Bundle resolution — a bundle with ``includes={"agents": (...)}`` resolves via
  ``resolve_bundle``; a dangling ``agents`` reference is flagged by ``validate_catalog``.
* ``source.Source._scan_agents`` — a temp dir with ``agents/house.md`` yields an
  ``Artifact(type="agents", name="house")`` from ``catalog()``.

Run: ``python -m unittest discover -s tests -p "agents_catalog_test.py" -v``

Pure-data fixtures for the parser/bundle tests (nothing touches disk); a single
``tempfile.TemporaryDirectory`` for the source-scan test.
"""

import os
import pathlib
import tempfile
import unittest

from agent_artifacts import catalog, source
from agent_artifacts.model import Artifact, Bundle, Catalog, Err, Ok, Request, ResolvedBundle


def _catalog(artifacts=(), bundles=()):
    """Build a `Catalog` from iterables of `Artifact` / `Bundle`."""
    return Catalog(
        artifacts={(a.type, a.name): a for a in artifacts},
        bundles={b.name: b for b in bundles},
    )


def _bundle(name, *, description="", extends=(), includes=None, pins=None):
    return Bundle(
        name=name,
        description=description,
        extends=tuple(extends),
        includes=dict(includes or {}),
        pins=dict(pins or {}),
    )


# --------------------------------------------------------------------------- #
# parse_agents                                                                 #
# --------------------------------------------------------------------------- #
class ParseAgentsTests(unittest.TestCase):
    def test_no_frontmatter_is_ok(self):
        res = catalog.parse_agents("# House rules\nRun make test.\n", "house")
        self.assertEqual(res, Ok(Artifact("agents", "house", "agents/house.md")))

    def test_root_is_dot_md(self):
        res = catalog.parse_agents("body only\n", "house")
        self.assertIsInstance(res, Ok)
        self.assertEqual(res.value.root, "agents/house.md")

    def test_frontmatter_matching_name_and_valid_mode_is_ok(self):
        text = "---\nname: house\ndescription: House rules\nmode: prepend\n---\n# Body\n"
        res = catalog.parse_agents(text, "house")
        self.assertEqual(res, Ok(Artifact("agents", "house", "agents/house.md")))

    def test_each_valid_mode_accepted(self):
        for mode in ("replace", "prepend", "append", "skip"):
            text = f"---\nname: house\nmode: {mode}\n---\nbody"
            self.assertIsInstance(
                catalog.parse_agents(text, "house"), Ok, f"mode {mode!r} should parse"
            )

    def test_quoted_name_matches(self):
        text = '---\nname: "house"\n---\nbody'
        self.assertIsInstance(catalog.parse_agents(text, "house"), Ok)

    def test_name_mismatch_is_err(self):
        res = catalog.parse_agents("---\nname: other\n---\nbody", "house")
        self.assertIsInstance(res, Err)

    def test_invalid_mode_is_err(self):
        res = catalog.parse_agents("---\nname: house\nmode: clobber\n---\nbody", "house")
        self.assertIsInstance(res, Err)

    def test_unterminated_frontmatter_is_err(self):
        res = catalog.parse_agents("---\nname: house\n# never closed\n", "house")
        self.assertIsInstance(res, Err)


# --------------------------------------------------------------------------- #
# Bundle resolution (includes.agents) + dangling detection                     #
# --------------------------------------------------------------------------- #
class AgentsBundleTests(unittest.TestCase):
    def test_section_to_type_maps_agents_and_agent(self):
        self.assertEqual(catalog._section_to_type("agents"), "agents")
        self.assertEqual(catalog._section_to_type("agent"), "agents")

    def test_bundle_parses_agents_section(self):
        text = '{"includes": {"agents": ["house"]}}'
        res = catalog.parse_bundle(text, "base")
        self.assertIsInstance(res, Ok)
        self.assertEqual(res.value.includes["agents"], ("house",))

    def test_resolve_bundle_with_agents_reference(self):
        cat = _catalog(
            artifacts=[Artifact("agents", "house", "agents/house.md")],
            bundles=[_bundle("base", includes={"agents": ("house",)})],
        )
        res = catalog.resolve_bundle(cat, "base")
        self.assertIsInstance(res, Ok, getattr(res, "reason", ""))
        self.assertEqual(res.value.artifacts, (("agents", "house"),))

    def test_validate_catalog_flags_dangling_agents_reference(self):
        # Bundle references an agents artifact that does not exist in the catalog.
        cat = _catalog(
            artifacts=[],
            bundles=[_bundle("base", includes={"agents": ("missing",)})],
        )
        errors = catalog.validate_catalog(cat)
        self.assertEqual(len(errors), 1)
        self.assertIn("missing", errors[0].reason)

    def test_resolve_bundle_dangling_agents_is_err(self):
        cat = _catalog(
            artifacts=[],
            bundles=[_bundle("base", includes={"agents": ("missing",)})],
        )
        res = catalog.resolve_bundle(cat, "base")
        self.assertIsInstance(res, Err)


# --------------------------------------------------------------------------- #
# source._scan_agents (real fs, temp dir)                                      #
# --------------------------------------------------------------------------- #
class ScanAgentsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        agents_dir = pathlib.Path(self.root, "agents")
        agents_dir.mkdir()
        (agents_dir / "house.md").write_text(
            "---\nname: house\nmode: prepend\n---\n# House rules\n", encoding="utf-8"
        )
        # A non-.md sibling must be ignored by the scanner.
        (agents_dir / "README.txt").write_text("ignore me", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _source(self):
        res = source.open_source(Request(command="install", source_dir=self.root))
        self.assertIsInstance(res, Ok, getattr(res, "reason", ""))
        return res.value

    def test_catalog_contains_agents_artifact(self):
        cat = self._source().catalog()
        self.assertIsInstance(cat, Ok, getattr(cat, "reason", ""))
        self.assertIn(("agents", "house"), cat.value.artifacts)
        self.assertEqual(
            cat.value.artifacts[("agents", "house")],
            Artifact("agents", "house", "agents/house.md"),
        )

    def test_scan_agents_skips_non_markdown(self):
        results = self._source()._scan_agents()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0], Ok(Artifact("agents", "house", "agents/house.md")))


if __name__ == "__main__":
    unittest.main()
