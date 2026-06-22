"""WP-18 tests: list command (catalog view + filters + --json).

Run: ``python -m unittest discover -s tests -p "list_test.py" -v``
"""

import io
import json
import pathlib
import sys
import unittest

from agent_artifacts.commands.list import run
from agent_artifacts.model import Request

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = str(REPO_ROOT / "tests" / "fixtures")

# The four fixture artifacts.
ALL_NAMES = {"code-review", "python-style", "postgres", "block-secrets", "house"}


def _capture(request: Request) -> tuple:
    """Run the list command, capturing stdout. Returns (exit_code, stdout_text)."""
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        rc = run(request)
    finally:
        sys.stdout = old
    return rc, buf.getvalue()


class TestListNoFilter(unittest.TestCase):
    """No --type, no --bundle: show all artifacts + bundles."""

    def test_all_artifacts_appear(self):
        req = Request(command="list", source_dir=FIXTURES)
        rc, out = _capture(req)
        self.assertEqual(rc, 0)
        for name in ALL_NAMES:
            self.assertIn(name, out)

    def test_bundles_appear(self):
        req = Request(command="list", source_dir=FIXTURES)
        rc, out = _capture(req)
        self.assertEqual(rc, 0)
        self.assertIn("base", out)
        self.assertIn("backend", out)
        self.assertIn("bundles:", out)


class TestListTypeFilter(unittest.TestCase):
    """--type restricts to one artifact type and hides bundles."""

    def test_type_mcp(self):
        req = Request(command="list", source_dir=FIXTURES, type_filter="mcp")
        rc, out = _capture(req)
        self.assertEqual(rc, 0)
        self.assertIn("postgres", out)
        # Other types absent.
        self.assertNotIn("code-review", out)
        self.assertNotIn("python-style", out)
        self.assertNotIn("block-secrets", out)

    def test_type_filter_hides_bundles(self):
        req = Request(command="list", source_dir=FIXTURES, type_filter="skill")
        rc, out = _capture(req)
        self.assertEqual(rc, 0)
        self.assertNotIn("bundles:", out)


class TestListBundleFilter(unittest.TestCase):
    """--bundle restricts to a bundle's resolved artifacts."""

    def test_bundle_backend(self):
        req = Request(command="list", source_dir=FIXTURES, bundles=("backend",))
        rc, out = _capture(req)
        self.assertEqual(rc, 0)
        # backend extends base (code-review, python-style, block-secrets) + postgres
        self.assertIn("code-review", out)
        self.assertIn("python-style", out)
        self.assertIn("postgres", out)
        self.assertIn("block-secrets", out)

    def test_bundle_base(self):
        req = Request(command="list", source_dir=FIXTURES, bundles=("base",))
        rc, out = _capture(req)
        self.assertEqual(rc, 0)
        self.assertIn("code-review", out)
        self.assertIn("python-style", out)
        self.assertIn("block-secrets", out)
        # postgres is only in backend's own includes
        self.assertNotIn("postgres", out)

    def test_unknown_bundle(self):
        req = Request(command="list", source_dir=FIXTURES, bundles=("nope",))
        rc, out = _capture(req)
        self.assertNotEqual(rc, 0)
        self.assertIn("nope", out)


class TestListBundlePlusType(unittest.TestCase):
    """--bundle + --type narrows to one type within the bundle."""

    def test_backend_plus_type_mcp(self):
        req = Request(
            command="list",
            source_dir=FIXTURES,
            bundles=("backend",),
            type_filter="mcp",
        )
        rc, out = _capture(req)
        self.assertEqual(rc, 0)
        self.assertIn("postgres", out)
        self.assertNotIn("code-review", out)


class TestListJson(unittest.TestCase):
    """--json output parses and matches the stable shape."""

    def test_json_all(self):
        req = Request(command="list", source_dir=FIXTURES, json=True)
        rc, out = _capture(req)
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertIn("version", data)
        self.assertEqual(data["version"], "main")
        self.assertIn("artifacts", data)
        self.assertIn("bundles", data)
        # All four artifacts present.
        names = {a["name"] for a in data["artifacts"]}
        self.assertEqual(names, ALL_NAMES)
        # Each artifact has the right keys.
        for art in data["artifacts"]:
            self.assertIn("type", art)
            self.assertIn("name", art)
            self.assertIn("root", art)
        # Bundles have the right keys.
        bundle_names = {b["name"] for b in data["bundles"]}
        self.assertEqual(bundle_names, {"base", "backend"})
        for b in data["bundles"]:
            self.assertIn("description", b)
            self.assertIn("extends", b)
            self.assertIn("includes", b)

    def test_json_with_version(self):
        req = Request(command="list", source_dir=FIXTURES, json=True, version="v1.2.3")
        rc, out = _capture(req)
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertEqual(data["version"], "v1.2.3")

    def test_json_type_filter_no_bundles(self):
        req = Request(command="list", source_dir=FIXTURES, json=True, type_filter="hook")
        rc, out = _capture(req)
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertNotIn("bundles", data)
        names = {a["name"] for a in data["artifacts"]}
        self.assertEqual(names, {"block-secrets"})


if __name__ == "__main__":
    unittest.main()
