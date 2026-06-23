"""WP-15 tests: status command — local drift detection, no network.

Run: ``python -m unittest discover -s tests -p "status_test.py" -v``
"""

import importlib
import json
import os
import sys
import tempfile
import unittest

from agent_artifacts.hashing import sha256_bytes
from agent_artifacts.manifest import dump_manifest
from agent_artifacts.model import Manifest, ManifestEntry, Request


def _make_request(project: str, *, use_json: bool = False) -> Request:
    return Request(command="status", project=project, json=use_json)


def _write(path: str, content: bytes) -> str:
    """Write *content* to *path*, creating parent dirs. Return the sha256 hash."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)
    return sha256_bytes(content)


def _setup_project(tmp: str, entries: tuple, file_contents: dict | None = None):
    """Create a project dir with a manifest and optional on-disk files.

    *file_contents*: mapping of project-relative path -> bytes to write on disk.
    Returns the manifest that was written.
    """
    manifest = Manifest(repo="org/agent-artifacts", installed=entries)
    manifest_dir = os.path.join(tmp, ".agent-artifacts")
    os.makedirs(manifest_dir, exist_ok=True)
    with open(os.path.join(manifest_dir, "manifest.json"), "w") as f:
        f.write(dump_manifest(manifest))

    if file_contents:
        for rel_path, content in file_contents.items():
            _write(os.path.join(tmp, rel_path), content)

    return manifest


class TestStatusAllOk(unittest.TestCase):
    """All installed files match their recorded hashes → every file reports "ok"."""

    def test_all_ok(self):
        from agent_artifacts.commands.status import run

        with tempfile.TemporaryDirectory() as tmp:
            content_a = b"skill content A"
            content_b = b"guideline content B"
            hash_a = sha256_bytes(content_a)
            hash_b = sha256_bytes(content_b)

            entries = (
                ManifestEntry(
                    artifact="code-review",
                    type="skill",
                    profile="claude",
                    source="main:abc1234",
                    files={".claude/skills/code-review/SKILL.md": hash_a},
                ),
                ManifestEntry(
                    artifact="style",
                    type="guideline",
                    profile="claude",
                    source="pin:def5678",
                    files={".claude/guidelines/style.md": hash_b},
                ),
            )

            _setup_project(
                tmp,
                entries,
                {
                    ".claude/skills/code-review/SKILL.md": content_a,
                    ".claude/guidelines/style.md": content_b,
                },
            )

            req = _make_request(tmp, use_json=True)
            rc = run(req)
            self.assertEqual(rc, 0)


class TestStatusDrift(unittest.TestCase):
    """Modifying a file on disk → status reports "drift" for it."""

    def test_drift_detected(self):
        from agent_artifacts.commands.status import run

        with tempfile.TemporaryDirectory() as tmp:
            original = b"original content"
            original_hash = sha256_bytes(original)

            entries = (
                ManifestEntry(
                    artifact="code-review",
                    type="skill",
                    profile="claude",
                    source="main:abc1234",
                    files={".claude/skills/code-review/SKILL.md": original_hash},
                ),
            )

            _setup_project(
                tmp,
                entries,
                {
                    ".claude/skills/code-review/SKILL.md": original,
                },
            )

            # Modify the file on disk.
            with open(os.path.join(tmp, ".claude/skills/code-review/SKILL.md"), "wb") as f:
                f.write(b"modified content")

            req = _make_request(tmp, use_json=True)
            rc = run(req)
            self.assertEqual(rc, 0)  # drift is informational, not an error

            # Re-run capturing JSON to verify drift state.
            import contextlib
            import io

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                run(req)
            output = json.loads(buf.getvalue())
            file_states = {
                f["path"]: f["state"] for entry in output["installed"] for f in entry["files"]
            }
            self.assertEqual(
                file_states[".claude/skills/code-review/SKILL.md"],
                "drift",
            )


class TestStatusMissing(unittest.TestCase):
    """Deleting a tracked file → status reports "missing"."""

    def test_missing_detected(self):
        from agent_artifacts.commands.status import run

        with tempfile.TemporaryDirectory() as tmp:
            content = b"some content"
            content_hash = sha256_bytes(content)

            entries = (
                ManifestEntry(
                    artifact="code-review",
                    type="skill",
                    profile="claude",
                    source="main:abc1234",
                    files={".claude/skills/code-review/SKILL.md": content_hash},
                ),
            )

            # Write the manifest but do NOT create the file on disk.
            _setup_project(tmp, entries)

            import contextlib
            import io

            buf = io.StringIO()
            req = _make_request(tmp, use_json=True)
            with contextlib.redirect_stdout(buf):
                run(req)
            output = json.loads(buf.getvalue())
            file_states = {
                f["path"]: f["state"] for entry in output["installed"] for f in entry["files"]
            }
            self.assertEqual(
                file_states[".claude/skills/code-review/SKILL.md"],
                "missing",
            )


class TestStatusDriftAndMissing(unittest.TestCase):
    """Mixed scenario: one file ok, one drifted, one missing."""

    def test_mixed(self):
        from agent_artifacts.commands.status import run

        with tempfile.TemporaryDirectory() as tmp:
            ok_content = b"ok file"
            drift_content = b"will drift"
            missing_content = b"will vanish"

            ok_hash = sha256_bytes(ok_content)
            drift_hash = sha256_bytes(drift_content)
            missing_hash = sha256_bytes(missing_content)

            entries = (
                ManifestEntry(
                    artifact="multi",
                    type="skill",
                    profile="claude",
                    source="main:abc1234",
                    files={
                        "a.md": ok_hash,
                        "b.md": drift_hash,
                        "c.md": missing_hash,
                    },
                ),
            )

            _setup_project(
                tmp,
                entries,
                {
                    "a.md": ok_content,
                    "b.md": drift_content,  # will be modified
                    # c.md deliberately not created
                },
            )

            # Modify b.md.
            with open(os.path.join(tmp, "b.md"), "wb") as f:
                f.write(b"drifted content")

            import contextlib
            import io

            buf = io.StringIO()
            req = _make_request(tmp, use_json=True)
            with contextlib.redirect_stdout(buf):
                run(req)
            output = json.loads(buf.getvalue())
            states = {
                f["path"]: f["state"] for entry in output["installed"] for f in entry["files"]
            }
            self.assertEqual(states["a.md"], "ok")
            self.assertEqual(states["b.md"], "drift")
            self.assertEqual(states["c.md"], "missing")


class TestStatusCopyTreeDirectory(unittest.TestCase):
    """Copy-tree entries record a directory path with base_hash == ""."""

    def test_tree_ok(self):
        from agent_artifacts.commands.status import run

        with tempfile.TemporaryDirectory() as tmp:
            entries = (
                ManifestEntry(
                    artifact="my-hook",
                    type="hook",
                    profile="claude",
                    source="main:abc1234",
                    files={".claude/hooks/my-hook": ""},  # directory, empty hash
                ),
            )
            _setup_project(tmp, entries)
            # Create the directory on disk.
            os.makedirs(os.path.join(tmp, ".claude/hooks/my-hook"), exist_ok=True)

            import contextlib
            import io

            buf = io.StringIO()
            req = _make_request(tmp, use_json=True)
            with contextlib.redirect_stdout(buf):
                run(req)
            output = json.loads(buf.getvalue())
            state = output["installed"][0]["files"][0]["state"]
            self.assertEqual(state, "ok (tree)")

    def test_tree_missing(self):
        from agent_artifacts.commands.status import run

        with tempfile.TemporaryDirectory() as tmp:
            entries = (
                ManifestEntry(
                    artifact="my-hook",
                    type="hook",
                    profile="claude",
                    source="main:abc1234",
                    files={".claude/hooks/my-hook": ""},
                ),
            )
            _setup_project(tmp, entries)
            # Do NOT create the directory.

            import contextlib
            import io

            buf = io.StringIO()
            req = _make_request(tmp, use_json=True)
            with contextlib.redirect_stdout(buf):
                run(req)
            output = json.loads(buf.getvalue())
            state = output["installed"][0]["files"][0]["state"]
            self.assertEqual(state, "missing")


class TestStatusJsonShape(unittest.TestCase):
    """--json output parses and has the expected stable shape."""

    def test_json_shape(self):
        from agent_artifacts.commands.status import run

        with tempfile.TemporaryDirectory() as tmp:
            content = b"hello"
            h = sha256_bytes(content)

            entries = (
                ManifestEntry(
                    artifact="code-review",
                    type="skill",
                    profile="claude",
                    source="main:abc1234",
                    files={".claude/skills/code-review/SKILL.md": h},
                ),
            )
            _setup_project(
                tmp,
                entries,
                {
                    ".claude/skills/code-review/SKILL.md": content,
                },
            )

            import contextlib
            import io

            buf = io.StringIO()
            req = _make_request(tmp, use_json=True)
            with contextlib.redirect_stdout(buf):
                run(req)
            output = json.loads(buf.getvalue())

            # Top-level keys.
            self.assertIn("repo", output)
            self.assertIn("installed", output)
            self.assertIsInstance(output["installed"], list)

            entry = output["installed"][0]
            for key in ("artifact", "type", "profile", "source", "files"):
                self.assertIn(key, entry, f"missing key: {key}")

            f = entry["files"][0]
            self.assertIn("path", f)
            self.assertIn("state", f)
            self.assertIn(f["state"], ("ok", "drift", "missing", "ok (tree)"))


class TestStatusCorruptManifest(unittest.TestCase):
    """Corrupt manifest → exit code 5."""

    def test_corrupt(self):
        from agent_artifacts.commands.status import run

        with tempfile.TemporaryDirectory() as tmp:
            manifest_dir = os.path.join(tmp, ".agent-artifacts")
            os.makedirs(manifest_dir, exist_ok=True)
            with open(os.path.join(manifest_dir, "manifest.json"), "w") as f:
                f.write("NOT VALID JSON {{{")

            req = _make_request(tmp)
            import contextlib
            import io

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = run(req)
            self.assertEqual(rc, 5)


class TestStatusEmptyManifest(unittest.TestCase):
    """No manifest file → reports 0 installed, exit code 0."""

    def test_no_manifest(self):
        from agent_artifacts.commands.status import run

        with tempfile.TemporaryDirectory() as tmp:
            req = _make_request(tmp, use_json=True)

            import contextlib
            import io

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = run(req)
            self.assertEqual(rc, 0)
            output = json.loads(buf.getvalue())
            self.assertEqual(output["installed"], [])


class TestStatusNoNetwork(unittest.TestCase):
    """Hard invariant: importing status must NOT pull in agent_artifacts.io.net."""

    def test_no_net_import(self):
        # Remove any cached import of the net module.
        sys.modules.pop("agent_artifacts.io.net", None)

        # Force-reload the status module to check its import graph.
        if "agent_artifacts.commands.status" in sys.modules:
            importlib.reload(sys.modules["agent_artifacts.commands.status"])
        else:
            import agent_artifacts.commands.status  # noqa: F401

        self.assertNotIn(
            "agent_artifacts.io.net",
            sys.modules,
            "status command must not import agent_artifacts.io.net (DESIGN.md §8)",
        )

    def test_source_no_net_import(self):
        """Belt-and-suspenders: scan import lines for any reference to the net module."""
        import ast

        import agent_artifacts.commands.status as mod

        source_path = mod.__file__
        assert source_path is not None
        with open(source_path, "r") as f:
            source = f.read()

        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                # Reconstruct the import text for checking.
                if isinstance(node, ast.ImportFrom) and node.module:
                    self.assertNotIn(
                        "net",
                        node.module.split("."),
                        f"status.py imports net module via: from {node.module}",
                    )
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotIn(
                            "net",
                            alias.name.split("."),
                            f"status.py imports net module via: import {alias.name}",
                        )


if __name__ == "__main__":
    unittest.main()
