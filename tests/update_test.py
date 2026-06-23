"""WP-13 update-command tests: the three §9 update paths + --prune.

Run: ``python -m unittest discover -s tests -p "update_test.py" -v``

These are integration tests against a real temp filesystem (stdlib ``tempfile``):
each test FIRST installs ``python-style`` (a copy-mode guideline, so it lands as a single
standalone ``WriteFile`` whose per-file §9 policy we can exercise cleanly) from a copy of
``tests/fixtures`` into a temp project, then points ``--source`` at a *mutated* copy of the
fixtures and runs ``update.run`` to assert the clean / drift-keep / conflict behaviour.

We drive the install via the same pure ``planners.plan_install`` + ``executor`` + ``_common``
glue the real install command uses, so the manifest base hashes are produced exactly as in
production (no test-only shortcuts that could mask a hashing/format mismatch).
"""

from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout

from agent_artifacts import planners
from agent_artifacts.commands import _common, update
from agent_artifacts.executor import execute
from agent_artifacts.hashing import sha256_file
from agent_artifacts.io import fs
from agent_artifacts.manifest import upsert
from agent_artifacts.model import Manifest, ManifestEntry, Request
from agent_artifacts.policy import NEW_SUFFIX
from agent_artifacts.profiles.loader import load_profiles
from agent_artifacts.source import open_source

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")

# Guidelines are always copied as one standalone file we can edit and diff per the §9
# WriteFile policy — they are never merged into a shared memory file.
PROFILE = "tabnine"
GUIDELINE_DEST = os.path.join(".tabnine", "guidelines", "python-style.md")


# --------------------------------------------------------------------------- #
# Helpers                                                                       #
# --------------------------------------------------------------------------- #
def _install(source_dir: str, project: str, name: str = "python-style") -> Manifest:
    """Install one guideline into `project` from `source_dir`, exactly like the install command.

    Returns the persisted `Manifest` (also written to disk) so callers can inspect base hashes.
    """
    req = Request(
        command="install",
        names=(name,),
        profiles=(PROFILE,),
        source_dir=source_dir,
        project=project,
    )
    src = open_source(req).value
    catalog = src.catalog().value
    profiles = load_profiles(project)

    artifact = catalog.artifacts[("guideline", name)]
    text = src.read(artifact.root).decode("utf-8")
    from agent_artifacts.catalog import _split_frontmatter

    _found, _fields, stripped_text = _split_frontmatter(text)
    files = {
        "__targets__": [(artifact, PROFILE)],
        "__installed_at__": "2026-06-20T00:00:00Z",
        f"guideline:{name}": stripped_text,
        f"source:{name}": src.label(),
    }
    plan = planners.plan_install(req, catalog, files, profiles, manifest=None, configs={}).value
    file_actions, entries = _common.split_manifest(plan)
    rebased = _common.rebase_plan(file_actions, source_root=src.root, project_root=project)
    execute(rebased)

    # Upsert into the on-disk manifest (so repeated _install calls accumulate, like install).
    manifest = _common.load_manifest(req).value
    for e in entries:
        manifest = upsert(
            manifest,
            ManifestEntry(
                artifact=e.artifact,
                type=e.type,
                profile=e.profile,
                source=src.label(),
                bundle=e.bundle,
                files=e.files,
                merge=e.merge,
                installed_at=e.installed_at,
            ),
        )
    _common.save_manifest(project, manifest)
    return manifest


def _mutated_source(base_fixtures: str, dst: str, new_body: str, name: str = "python-style") -> str:
    """Copy the fixtures to `dst` and rewrite the guideline body. Returns `dst`."""
    shutil.copytree(base_fixtures, dst, dirs_exist_ok=True)
    fs.write_atomic(os.path.join(dst, "guidelines", f"{name}.md"), new_body.encode("utf-8"))
    return dst


def _update_request(source_dir: str, project: str, **kw) -> Request:
    return Request(command="update", source_dir=source_dir, project=project, **kw)


# --------------------------------------------------------------------------- #
# Tests                                                                         #
# --------------------------------------------------------------------------- #
class UpdateCleanTests(unittest.TestCase):
    """File changed upstream, untouched locally -> overwritten to the new content."""

    def test_clean_update_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = os.path.join(tmp, "proj")
            source = os.path.join(tmp, "src")
            shutil.copytree(FIXTURES, source)
            _install(source, project)

            dest = os.path.join(project, GUIDELINE_DEST)
            self.assertTrue(os.path.exists(dest))

            new_body = "---\ndescription: x\n---\n\n# Updated upstream\n"
            mutated = _mutated_source(FIXTURES, os.path.join(tmp, "src2"), new_body)

            code = update.run(_update_request(mutated, project))
            self.assertEqual(code, _common.OK)
            with open(dest, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), "\n# Updated upstream")

            # Manifest base hash refreshed to the new content (so a re-update is a no-op).
            man = _common.load_manifest(_update_request(mutated, project)).value
            entry = man.installed[0]
            self.assertEqual(entry.files[GUIDELINE_DEST], sha256_file(dest))


class UpdateDriftKeepTests(unittest.TestCase):
    """File modified locally, unchanged upstream -> local kept, Warn emitted, no overwrite."""

    def test_drift_keeps_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = os.path.join(tmp, "proj")
            source = os.path.join(tmp, "src")
            shutil.copytree(FIXTURES, source)
            _install(source, project)

            dest = os.path.join(project, GUIDELINE_DEST)
            local_edit = "LOCALLY EDITED — keep me\n"
            fs.write_atomic(dest, local_edit.encode("utf-8"))

            # Upstream identical to the originally-installed fixture (no change).
            code = update.run(_update_request(source, project))
            self.assertEqual(code, _common.OK)

            with open(dest, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), local_edit)  # untouched
            self.assertFalse(os.path.exists(dest + NEW_SUFFIX))

    def test_drift_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = os.path.join(tmp, "proj")
            source = os.path.join(tmp, "src")
            shutil.copytree(FIXTURES, source)
            _install(source, project)

            dest = os.path.join(project, GUIDELINE_DEST)
            fs.write_atomic(dest, b"local drift\n")

            # Run with --json and capture stdout to assert a drift Warn is surfaced.
            req = _update_request(source, project, json=True)
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = update.run(req)
            self.assertEqual(code, _common.OK)

            payload = json.loads(buf.getvalue())
            self.assertTrue(
                any("drift" in w for w in payload["warnings"]),
                f"expected a drift warning, got {payload['warnings']!r}",
            )
            self.assertFalse(payload["conflict"])
            # The local file is preserved (the observable contract of a drift Warn).
            with open(dest, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), "local drift\n")


class UpdateConflictTests(unittest.TestCase):
    """File changed both locally and upstream -> sidecar without --force; overwrite with --force."""

    def test_conflict_writes_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = os.path.join(tmp, "proj")
            source = os.path.join(tmp, "src")
            shutil.copytree(FIXTURES, source)
            _install(source, project)

            dest = os.path.join(project, GUIDELINE_DEST)
            local_edit = "LOCAL conflicting change\n"
            fs.write_atomic(dest, local_edit.encode("utf-8"))

            upstream = "---\ndescription: y\n---\n\n# Upstream conflicting change\n"
            mutated = _mutated_source(FIXTURES, os.path.join(tmp, "src2"), upstream)

            code = update.run(_update_request(mutated, project))
            # Conflict without --force is surfaced as CONFLICT (sidecar still written).
            self.assertEqual(code, _common.CONFLICT)

            with open(dest, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), local_edit)  # original kept
            sidecar = dest + NEW_SUFFIX
            self.assertTrue(os.path.exists(sidecar))
            with open(sidecar, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), "\n# Upstream conflicting change")

    def test_conflict_force_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = os.path.join(tmp, "proj")
            source = os.path.join(tmp, "src")
            shutil.copytree(FIXTURES, source)
            _install(source, project)

            dest = os.path.join(project, GUIDELINE_DEST)
            fs.write_atomic(dest, b"LOCAL conflicting change\n")

            upstream = "---\ndescription: y\n---\n\n# Upstream wins\n"
            mutated = _mutated_source(FIXTURES, os.path.join(tmp, "src2"), upstream)

            code = update.run(_update_request(mutated, project, force=True))
            self.assertEqual(code, _common.OK)
            with open(dest, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), "\n# Upstream wins")  # forced overwrite
            self.assertFalse(os.path.exists(dest + NEW_SUFFIX))


class UpdateDryRunTests(unittest.TestCase):
    """--dry-run renders a plan but touches nothing on disk."""

    def test_dry_run_no_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = os.path.join(tmp, "proj")
            source = os.path.join(tmp, "src")
            shutil.copytree(FIXTURES, source)
            _install(source, project)

            dest = os.path.join(project, GUIDELINE_DEST)
            with open(dest, encoding="utf-8") as fh:
                before = fh.read()

            new_body = "---\ndescription: z\n---\n\n# Changed\n"
            mutated = _mutated_source(FIXTURES, os.path.join(tmp, "src2"), new_body)

            code = update.run(_update_request(mutated, project, dry_run=True))
            self.assertEqual(code, _common.OK)
            with open(dest, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), before)  # unchanged


class UpdatePruneTests(unittest.TestCase):
    """--prune removes a no-longer-selected entry's files + manifest record."""

    def test_prune_removes_unselected(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = os.path.join(tmp, "proj")
            source = os.path.join(tmp, "src")
            shutil.copytree(FIXTURES, source)
            # Add a second guideline to the source so we have two installable entries.
            second_body = "---\ndescription: second\n---\n\n# Second guideline\n"
            fs.write_atomic(
                os.path.join(source, "guidelines", "second.md"), second_body.encode("utf-8")
            )
            _install(source, project, name="python-style")
            man = _install(source, project, name="second")
            self.assertEqual({e.artifact for e in man.installed}, {"python-style", "second"})

            second_dest = os.path.join(project, ".tabnine", "guidelines", "second.md")
            self.assertTrue(os.path.exists(second_dest))

            # Update selecting ONLY python-style, with --prune -> second is dropped.
            req = _update_request(source, project, names=("python-style",), prune=True)
            code = update.run(req)
            self.assertEqual(code, _common.OK)

            self.assertFalse(os.path.exists(second_dest))  # files removed
            man = _common.load_manifest(req).value
            artifacts = {e.artifact for e in man.installed}
            self.assertIn("python-style", artifacts)
            self.assertNotIn("second", artifacts)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
