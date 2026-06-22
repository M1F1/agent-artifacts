"""Sanity-gate tests for seed content.

Validates that all artifact files conform to their expected formats
without importing any application code (the catalog module is still
stubbed at this point).

Stdlib only — no external test dependencies.
"""

import json
import pathlib
import unittest

# Repo root: tests/ is one level below the root.
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

SKILLS_DIR = REPO_ROOT / "skills"
GUIDELINES_DIR = REPO_ROOT / "guidelines"
MCP_DIR = REPO_ROOT / "mcp"
HOOKS_DIR = REPO_ROOT / "hooks"
AGENTS_DIR = REPO_ROOT / "agents"
BUNDLES_DIR = REPO_ROOT / "bundles"


def _read_text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_json(path: pathlib.Path) -> dict:
    return json.loads(_read_text(path))


class TestMcpJsonFiles(unittest.TestCase):
    """Every mcp/*.json must be valid JSON with 'name' and 'server' keys."""

    def test_all_mcp_files_valid(self) -> None:
        mcp_files = list(MCP_DIR.glob("*.json"))
        self.assertGreater(len(mcp_files), 0, "No MCP JSON files found")
        for path in mcp_files:
            with self.subTest(file=path.name):
                data = _load_json(path)
                self.assertIn("name", data, f"{path.name} missing 'name'")
                self.assertIn("server", data, f"{path.name} missing 'server'")
                # server must have at least 'command'
                self.assertIn("command", data["server"],
                              f"{path.name} server missing 'command'")


class TestHookJsonFiles(unittest.TestCase):
    """Every hooks/*/hook.json must be valid JSON with required keys."""

    def test_all_hook_files_valid(self) -> None:
        hook_files = list(HOOKS_DIR.glob("*/hook.json"))
        self.assertGreater(len(hook_files), 0, "No hook.json files found")
        for path in hook_files:
            with self.subTest(file=str(path.relative_to(REPO_ROOT))):
                data = _load_json(path)
                self.assertIn("name", data, f"missing 'name'")
                self.assertIn("events", data, f"missing 'events'")
                self.assertIsInstance(data["events"], list)
                self.assertGreater(len(data["events"]), 0,
                                   "events must be non-empty")
                self.assertIn("command", data, f"missing 'command'")

    def test_hook_script_files_exist(self) -> None:
        """If a hook declares 'files', each must exist on disk."""
        for path in HOOKS_DIR.glob("*/hook.json"):
            data = _load_json(path)
            hook_dir = path.parent
            for rel in data.get("files", []):
                with self.subTest(hook=data["name"], file=rel):
                    full = hook_dir / rel
                    self.assertTrue(full.exists(),
                                    f"Declared file '{rel}' not found at {full}")


class TestBundleJsonFiles(unittest.TestCase):
    """Every bundles/*.json must be valid JSON with required keys."""

    def test_all_bundle_files_valid(self) -> None:
        bundle_files = list(BUNDLES_DIR.glob("*.json"))
        self.assertGreater(len(bundle_files), 0, "No bundle JSON files found")
        for path in bundle_files:
            with self.subTest(file=path.name):
                data = _load_json(path)
                self.assertIn("name", data, f"{path.name} missing 'name'")
                # A bundle must have 'includes' or 'extends' (or both)
                has_content = "includes" in data or "extends" in data
                self.assertTrue(has_content,
                                f"{path.name} has neither 'includes' nor 'extends'")


class TestSkillFiles(unittest.TestCase):
    """Every skills/*/SKILL.md must start with YAML frontmatter containing 'name:'."""

    def test_all_skill_files_have_frontmatter(self) -> None:
        skill_files = list(SKILLS_DIR.glob("*/SKILL.md"))
        self.assertGreater(len(skill_files), 0, "No SKILL.md files found")
        for path in skill_files:
            with self.subTest(file=str(path.relative_to(REPO_ROOT))):
                text = _read_text(path)
                self.assertTrue(text.startswith("---"),
                                f"{path} does not start with '---' frontmatter")
                # Find closing '---'
                end = text.index("---", 3)
                frontmatter = text[3:end]
                self.assertIn("name:", frontmatter,
                              f"{path} frontmatter missing 'name:'")


class TestBackendBundleReferences(unittest.TestCase):
    """backend.json 'extends' references must exist; 'includes' must resolve to files."""

    def setUp(self) -> None:
        self.backend = _load_json(BUNDLES_DIR / "backend.json")

    def test_extends_references_existing_bundles(self) -> None:
        existing_bundles = {
            p.stem for p in BUNDLES_DIR.glob("*.json")
        }
        for ref in self.backend.get("extends", []):
            with self.subTest(extends=ref):
                self.assertIn(ref, existing_bundles,
                              f"extends '{ref}' does not match any bundle file")

    def test_includes_reference_existing_artifacts(self) -> None:
        """Each name in 'includes' must correspond to an on-disk artifact."""
        type_dirs = {
            "skills": SKILLS_DIR,
            "guidelines": GUIDELINES_DIR,
            "mcp": MCP_DIR,
            "hooks": HOOKS_DIR,
            "agents": AGENTS_DIR,
        }
        includes = self.backend.get("includes", {})
        for art_type, names in includes.items():
            base_dir = type_dirs.get(art_type)
            self.assertIsNotNone(base_dir,
                                 f"Unknown artifact type '{art_type}'")
            for name in names:
                with self.subTest(type=art_type, name=name):
                    if art_type == "skills":
                        target = base_dir / name / "SKILL.md"
                    elif art_type == "guidelines":
                        target = base_dir / f"{name}.md"
                    elif art_type == "mcp":
                        target = base_dir / f"{name}.json"
                    elif art_type == "hooks":
                        target = base_dir / name / "hook.json"
                    elif art_type == "agents":
                        target = base_dir / f"{name}.md"
                    else:
                        self.fail(f"Unhandled type {art_type}")
                    self.assertTrue(target.exists(),
                                    f"Artifact '{name}' ({art_type}) not found at {target}")

    def test_base_bundle_includes_also_resolve(self) -> None:
        """Transitively: base bundle's includes must also resolve."""
        for ref in self.backend.get("extends", []):
            base_data = _load_json(BUNDLES_DIR / f"{ref}.json")
            type_dirs = {
                "skills": SKILLS_DIR,
                "guidelines": GUIDELINES_DIR,
                "mcp": MCP_DIR,
                "hooks": HOOKS_DIR,
                "agents": AGENTS_DIR,
            }
            for art_type, names in base_data.get("includes", {}).items():
                base_dir = type_dirs.get(art_type)
                self.assertIsNotNone(base_dir)
                for name in names:
                    with self.subTest(bundle=ref, type=art_type, name=name):
                        if art_type == "skills":
                            target = base_dir / name / "SKILL.md"
                        elif art_type == "guidelines":
                            target = base_dir / f"{name}.md"
                        elif art_type == "mcp":
                            target = base_dir / f"{name}.json"
                        elif art_type == "hooks":
                            target = base_dir / name / "hook.json"
                        elif art_type == "agents":
                            target = base_dir / f"{name}.md"
                        else:
                            self.fail(f"Unhandled type {art_type}")
                        self.assertTrue(target.exists(),
                                        f"Artifact '{name}' ({art_type}) from bundle '{ref}' "
                                        f"not found at {target}")


class TestFixturesMirror(unittest.TestCase):
    """The tests/fixtures/ tree must have the same shape as the repo content."""

    FIXTURES = REPO_ROOT / "tests" / "fixtures"

    def test_fixture_skill_exists(self) -> None:
        path = self.FIXTURES / "skills" / "code-review" / "SKILL.md"
        self.assertTrue(path.exists())
        text = _read_text(path)
        self.assertTrue(text.startswith("---"))
        self.assertIn("name:", text)

    def test_fixture_guideline_exists(self) -> None:
        path = self.FIXTURES / "guidelines" / "python-style.md"
        self.assertTrue(path.exists())

    def test_fixture_mcp_exists(self) -> None:
        path = self.FIXTURES / "mcp" / "postgres.json"
        self.assertTrue(path.exists())
        data = _load_json(path)
        self.assertIn("name", data)
        self.assertIn("server", data)

    def test_fixture_hook_exists(self) -> None:
        path = self.FIXTURES / "hooks" / "block-secrets" / "hook.json"
        self.assertTrue(path.exists())
        data = _load_json(path)
        self.assertIn("name", data)
        self.assertIn("events", data)
        self.assertIn("command", data)

    def test_fixture_bundles_exist(self) -> None:
        for name in ("base.json", "backend.json"):
            path = self.FIXTURES / "bundles" / name
            with self.subTest(bundle=name):
                self.assertTrue(path.exists())
                data = _load_json(path)
                self.assertIn("name", data)


if __name__ == "__main__":
    unittest.main()
