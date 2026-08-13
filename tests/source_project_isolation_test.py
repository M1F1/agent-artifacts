"""SL-4: no source operation writes anything beneath a project directory.

Design §3 draws the boundary that makes `source remove` safe to offer at all: a subscription, its
managed snapshot, the object store, and installed files are four different things, and source
operations own only the first two.  That claim is what stops unsubscribing from silently deleting a
skill out of someone's repository, so it is asserted here against the real CLI over a real project
with real installed artifacts rather than left to inspection.

The whole `source` family runs against a project that already holds an installed payload and a
durable manifest.  Every file beneath the project is compared byte for byte, including modification
times: these operations should not so much as open a project file.  The managed-symlink case gets
its own test because it is the installation shape that reaches back into the data root, and so the
one a snapshot-owning removal could break from a distance.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import unittest
from pathlib import Path
from unittest import mock

from agent_artifacts import cli
from tests.marketplace_lifecycle_e2e_test import _COORDINATE, _FIXTURE, _environment

_MANIFEST = Path(".agent-artifacts") / "manifest.json"
_INSTALLED = Path(".claude") / "skills" / "code-review"


def _source(env, *argv):
    """Run one `source` subcommand and return ``(exit_code, parsed_json)``.

    The source family takes no ``--project``: sources are user-scope state, which is exactly the
    property under test, so these commands cannot even name a project to write into.
    """

    stdout = io.StringIO()
    with (
        mock.patch.dict(os.environ, env.xdg, clear=False),
        contextlib.redirect_stdout(stdout),
        mock.patch("os.getcwd", return_value=str(env.project)),
    ):
        code = cli.main([*argv, "--json"])
    raw = stdout.getvalue()
    return code, (json.loads(raw) if raw.strip() else None)


def _entry(path: Path) -> tuple[str, ...]:
    """Describe one path completely enough that any write to it changes the description."""

    if path.is_symlink():
        return ("symlink", os.readlink(path))
    stat = path.stat()
    if path.is_dir():
        return ("dir", str(stat.st_mode))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return ("file", str(stat.st_mode), str(stat.st_mtime_ns), digest)


def _project_snapshot(project: Path) -> dict[str, tuple[str, ...]]:
    return {str(path.relative_to(project)): _entry(path) for path in sorted(project.rglob("*"))}


class SourceOperationProjectIsolationTest(unittest.TestCase):
    def test_no_source_operation_writes_beneath_the_project(self) -> None:
        with _environment() as env:
            install_code, installed = env.run(
                "marketplace", "install", _COORDINATE, "--profile", "claude", "--yes"
            )
            self.assertEqual(install_code, 0, installed)
            self.assertTrue((env.project / _MANIFEST).is_file())
            self.assertTrue((env.project / _INSTALLED / "SKILL.md").is_file())

            # A second origin, so `add` has somewhere to point and `remove` leaves a source behind.
            mirror = env.root / "mirror-source"
            shutil.copytree(_FIXTURE, mirror)

            before = _project_snapshot(env.project)
            self.assertIn(str(_MANIFEST), before)

            operations = (
                (
                    "source",
                    "add",
                    "--alias",
                    "mirror",
                    "--kind",
                    "source-local",
                    "--location",
                    str(mirror),
                ),
                ("source", "list"),
                ("source", "sync"),
                ("source", "health"),
                ("source", "remove", "--alias", "reference"),
                ("source", "remove", "--alias", "reference", "--yes"),
            )
            for operation in operations:
                code, payload = _source(env, *operation)
                self.assertEqual(code, 0, (operation, payload))
                self.assertEqual(
                    _project_snapshot(env.project),
                    before,
                    f"`aart {' '.join(operation)}` changed the project tree",
                )

    def test_a_managed_symlink_survives_the_removal_of_the_source_that_supplied_it(self) -> None:
        """Design §4: removal invalidates the snapshot and leaves the object store alone.

        A managed symlink points into the object store, so this is the installation that a
        snapshot-owning removal would break if it reclaimed objects on the way out.
        """

        with _environment() as env:
            code, payload = env.run(
                "marketplace",
                "install",
                _COORDINATE,
                "--profile",
                "claude",
                "--mode",
                "symlink",
                "--yes",
            )
            self.assertEqual(code, 0, payload)
            link = env.project / _INSTALLED
            self.assertTrue(link.is_symlink())
            payload_bytes = (link / "SKILL.md").read_bytes()

            removed_code, removed = _source(
                env, "source", "remove", "--alias", "reference", "--yes"
            )

            self.assertEqual(removed_code, 0, removed)
            self.assertTrue(removed["snapshot_discarded"])
            self.assertTrue(link.is_symlink())
            self.assertTrue(
                link.resolve().is_dir(), f"dangling managed symlink: {os.readlink(link)}"
            )
            self.assertEqual((link / "SKILL.md").read_bytes(), payload_bytes)

    def test_the_durable_manifest_outlives_the_subscription_and_reconciles_as_unavailable(
        self,
    ) -> None:
        """Design §4: a project naming a removed alias reports it, rather than losing the record."""

        with _environment() as env:
            env.run("marketplace", "install", _COORDINATE, "--profile", "claude", "--yes")
            mirror = env.root / "mirror-source"
            shutil.copytree(_FIXTURE, mirror)
            _source(
                env,
                "source",
                "add",
                "--alias",
                "mirror",
                "--kind",
                "source-local",
                "--location",
                str(mirror),
            )
            manifest_before = (env.project / _MANIFEST).read_bytes()

            _source(env, "source", "remove", "--alias", "reference", "--yes")

            self.assertEqual((env.project / _MANIFEST).read_bytes(), manifest_before)
            code, status = env.run("marketplace", "status", "--profile", "claude")
            self.assertEqual(code, 0, status)
            self.assertEqual([item["status"] for item in status["items"]], ["source-unavailable"])
            self.assertEqual(status["items"][0]["key"], f"{_COORDINATE}@1.0.0#claude/project")


if __name__ == "__main__":
    unittest.main()
