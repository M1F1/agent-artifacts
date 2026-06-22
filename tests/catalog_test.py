"""WP-1 unit tests: catalog parsing & bundle resolution (pure, stdlib only).

Run: ``python -m unittest discover -s tests -p "catalog_test.py" -v``

All fixtures are inline strings/dicts — nothing touches disk.
"""

import json
import unittest

from agent_artifacts import catalog
from agent_artifacts.model import Artifact, Bundle, Catalog, Err, Ok


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
# Artifact parsing — all 4 types, happy + one malformed each.                  #
# --------------------------------------------------------------------------- #
class SkillParsingTests(unittest.TestCase):
    def test_happy(self):
        text = "---\nname: code-review\ndescription: Reviews code\n---\n# Body\n"
        res = catalog.parse_skill(text, "code-review")
        self.assertEqual(res, Ok(Artifact("skill", "code-review", "skills/code-review")))

    def test_quoted_name_matches(self):
        text = '---\nname: "code-review"\n---\nbody'
        self.assertIsInstance(catalog.parse_skill(text, "code-review"), Ok)

    def test_missing_frontmatter_is_err(self):
        res = catalog.parse_skill("# Just a heading, no frontmatter\n", "code-review")
        self.assertIsInstance(res, Err)

    def test_unterminated_frontmatter_is_err(self):
        res = catalog.parse_skill("---\nname: code-review\n# never closed\n", "code-review")
        self.assertIsInstance(res, Err)

    def test_missing_name_key_is_err(self):
        res = catalog.parse_skill("---\ndescription: no name\n---\n", "code-review")
        self.assertIsInstance(res, Err)

    def test_name_mismatch_is_err(self):
        res = catalog.parse_skill("---\nname: other\n---\n", "code-review")
        self.assertIsInstance(res, Err)


class GuidelineParsingTests(unittest.TestCase):
    def test_happy_no_frontmatter(self):
        res = catalog.parse_guideline("# Python style\nUse black.\n", "python-style")
        self.assertEqual(
            res, Ok(Artifact("guideline", "python-style", "guidelines/python-style.md"))
        )

    def test_happy_with_optional_frontmatter(self):
        text = "---\ndescription: Our Python rules\n---\nUse black.\n"
        res = catalog.parse_guideline(text, "python-style")
        self.assertIsInstance(res, Ok)
        self.assertEqual(res.value.root, "guidelines/python-style.md")

    def test_unterminated_frontmatter_is_err(self):
        res = catalog.parse_guideline("---\ndescription: oops\nno close\n", "python-style")
        self.assertIsInstance(res, Err)

    def test_name_mismatch_in_frontmatter_is_err(self):
        res = catalog.parse_guideline("---\nname: wrong\n---\nbody", "python-style")
        self.assertIsInstance(res, Err)


class McpParsingTests(unittest.TestCase):
    def test_happy(self):
        text = json.dumps(
            {"name": "postgres", "description": "PG", "server": {"command": "npx"}}
        )
        res = catalog.parse_mcp(text, "postgres")
        self.assertEqual(res, Ok(Artifact("mcp", "postgres", "mcp/postgres.json")))

    def test_bad_json_is_err(self):
        res = catalog.parse_mcp("{not valid json", "postgres")
        self.assertIsInstance(res, Err)

    def test_missing_server_is_err(self):
        res = catalog.parse_mcp(json.dumps({"name": "postgres"}), "postgres")
        self.assertIsInstance(res, Err)

    def test_name_mismatch_is_err(self):
        text = json.dumps({"name": "other", "server": {}})
        self.assertIsInstance(catalog.parse_mcp(text, "postgres"), Err)


class HookParsingTests(unittest.TestCase):
    def test_happy(self):
        text = json.dumps(
            {
                "name": "block-secrets",
                "description": "Block secrets",
                "events": ["PreToolUse"],
                "command": "python3 guard.py",
            }
        )
        res = catalog.parse_hook(text, "block-secrets")
        self.assertEqual(res, Ok(Artifact("hook", "block-secrets", "hooks/block-secrets")))

    def test_bad_json_is_err(self):
        self.assertIsInstance(catalog.parse_hook("nope", "block-secrets"), Err)

    def test_missing_events_is_err(self):
        text = json.dumps({"name": "block-secrets", "command": "x"})
        self.assertIsInstance(catalog.parse_hook(text, "block-secrets"), Err)

    def test_missing_command_is_err(self):
        text = json.dumps({"name": "block-secrets", "events": ["PreToolUse"]})
        self.assertIsInstance(catalog.parse_hook(text, "block-secrets"), Err)


class BundleParsingTests(unittest.TestCase):
    def test_happy_full(self):
        text = json.dumps(
            {
                "name": "backend",
                "description": "Backend set",
                "extends": ["base"],
                "includes": {
                    "skills": ["code-review", "db-migrations"],
                    "guidelines": ["python-style"],
                    "mcp": ["postgres"],
                    "hooks": ["block-secrets"],
                },
                "pins": {"code-review": "a1b2c3d"},
            }
        )
        res = catalog.parse_bundle(text, "backend")
        self.assertIsInstance(res, Ok)
        b = res.value
        self.assertEqual(b.extends, ("base",))
        self.assertEqual(b.includes["skill"], ("code-review", "db-migrations"))
        self.assertEqual(b.includes["guideline"], ("python-style",))
        self.assertEqual(b.includes["mcp"], ("postgres",))
        self.assertEqual(b.includes["hook"], ("block-secrets",))
        self.assertEqual(b.pins, {"code-review": "a1b2c3d"})

    def test_missing_optionals_default_empty(self):
        res = catalog.parse_bundle(json.dumps({"name": "base"}), "base")
        self.assertIsInstance(res, Ok)
        self.assertEqual(res.value.extends, ())
        self.assertEqual(res.value.includes, {})
        self.assertEqual(res.value.pins, {})

    def test_bad_json_is_err(self):
        self.assertIsInstance(catalog.parse_bundle("{bad", "base"), Err)

    def test_unknown_section_is_err(self):
        text = json.dumps({"name": "base", "includes": {"widgets": ["x"]}})
        self.assertIsInstance(catalog.parse_bundle(text, "base"), Err)


# --------------------------------------------------------------------------- #
# Bundle resolution.                                                           #
# --------------------------------------------------------------------------- #
class ResolveExtendsUnionTests(unittest.TestCase):
    def test_extends_union_with_ordered_dedup(self):
        artifacts = [
            Artifact("skill", "code-review", "skills/code-review"),
            Artifact("skill", "db-migrations", "skills/db-migrations"),
            Artifact("guideline", "python-style", "guidelines/python-style.md"),
            Artifact("mcp", "postgres", "mcp/postgres.json"),
        ]
        base = _bundle(
            "base",
            includes={"skill": ("code-review",), "guideline": ("python-style",)},
        )
        backend = _bundle(
            "backend",
            extends=("base",),
            # `code-review` repeats — must be de-duplicated, keeping base's position.
            includes={"skill": ("code-review", "db-migrations"), "mcp": ("postgres",)},
        )
        cat = _catalog(artifacts, (base, backend))

        res = catalog.resolve_bundle(cat, "backend")
        self.assertIsInstance(res, Ok)
        # Base contributes first (skill+guideline), then derived's new entries in order.
        self.assertEqual(
            res.value.artifacts,
            (
                ("skill", "code-review"),
                ("guideline", "python-style"),
                ("skill", "db-migrations"),
                ("mcp", "postgres"),
            ),
        )
        # No duplicate of code-review.
        self.assertEqual(
            sum(1 for k in res.value.artifacts if k == ("skill", "code-review")), 1
        )

    def test_missing_bundle_name_is_err(self):
        res = catalog.resolve_bundle(_catalog(), "nope")
        self.assertIsInstance(res, Err)


class ResolveCycleTests(unittest.TestCase):
    def test_direct_cycle_is_err(self):
        a = _bundle("a", extends=("b",))
        b = _bundle("b", extends=("a",))
        res = catalog.resolve_bundle(_catalog((), (a, b)), "a")
        self.assertIsInstance(res, Err)
        self.assertIn("cycle", res.reason)

    def test_self_cycle_is_err(self):
        a = _bundle("a", extends=("a",))
        res = catalog.resolve_bundle(_catalog((), (a,)), "a")
        self.assertIsInstance(res, Err)
        self.assertIn("cycle", res.reason)

    def test_indirect_cycle_is_err(self):
        a = _bundle("a", extends=("b",))
        b = _bundle("b", extends=("c",))
        c = _bundle("c", extends=("a",))
        res = catalog.resolve_bundle(_catalog((), (a, b, c)), "a")
        self.assertIsInstance(res, Err)
        self.assertIn("cycle", res.reason)


class ResolveMissingRefTests(unittest.TestCase):
    def test_single_missing_ref_is_err(self):
        b = _bundle("base", includes={"skill": ("ghost",)})
        res = catalog.resolve_bundle(_catalog((), (b,)), "base")
        self.assertIsInstance(res, Err)
        self.assertIn("ghost", res.reason)

    def test_all_missing_refs_reported(self):
        b = _bundle(
            "base",
            includes={"skill": ("ghost-a", "ghost-b"), "mcp": ("ghost-c",)},
        )
        res = catalog.resolve_bundle(_catalog((), (b,)), "base")
        self.assertIsInstance(res, Err)
        # Every dangling reference must be accumulated, not just the first.
        for missing in ("ghost-a", "ghost-b", "ghost-c"):
            self.assertIn(missing, res.reason)


class ResolvePinPrecedenceTests(unittest.TestCase):
    def test_derived_pin_overrides_base(self):
        artifacts = [Artifact("skill", "code-review", "skills/code-review")]
        base = _bundle(
            "base",
            includes={"skill": ("code-review",)},
            pins={"code-review": "BASE_SHA"},
        )
        derived = _bundle(
            "derived",
            extends=("base",),
            pins={"code-review": "DERIVED_SHA"},
        )
        cat = _catalog(artifacts, (base, derived))

        res = catalog.resolve_bundle(cat, "derived")
        self.assertIsInstance(res, Ok)
        # Derived bundle wins on pin conflict.
        self.assertEqual(res.value.pins["code-review"], "DERIVED_SHA")

    def test_base_pins_kept_when_no_conflict(self):
        artifacts = [
            Artifact("skill", "code-review", "skills/code-review"),
            Artifact("skill", "test-writer", "skills/test-writer"),
        ]
        base = _bundle(
            "base",
            includes={"skill": ("code-review",)},
            pins={"code-review": "BASE_SHA"},
        )
        derived = _bundle(
            "derived",
            extends=("base",),
            includes={"skill": ("test-writer",)},
            pins={"test-writer": "DERIVED_SHA"},
        )
        res = catalog.resolve_bundle(_catalog(artifacts, (base, derived)), "derived")
        self.assertIsInstance(res, Ok)
        self.assertEqual(
            res.value.pins, {"code-review": "BASE_SHA", "test-writer": "DERIVED_SHA"}
        )


class ValidateCatalogTests(unittest.TestCase):
    def test_valid_catalog_returns_empty(self):
        artifacts = [Artifact("skill", "code-review", "skills/code-review")]
        base = _bundle("base", includes={"skill": ("code-review",)})
        derived = _bundle("derived", extends=("base",))
        self.assertEqual(
            catalog.validate_catalog(_catalog(artifacts, (base, derived))), ()
        )

    def test_reports_each_broken_bundle(self):
        good = _bundle("good")  # empty, resolves fine
        dangling = _bundle("dangling", includes={"skill": ("ghost",)})
        a = _bundle("a", extends=("b",))
        b = _bundle("b", extends=("a",))
        errors = catalog.validate_catalog(_catalog((), (good, dangling, a, b)))
        # `dangling`, `a`, and `b` each fail; `good` does not.
        self.assertTrue(all(isinstance(e, Err) for e in errors))
        self.assertGreaterEqual(len(errors), 3)


if __name__ == "__main__":
    unittest.main()
