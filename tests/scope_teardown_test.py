"""SI-7 contracts: the uninstall that empties a scope leaves the repository as it found it.

`LAF-17` failed twice by hand — a checkout that was clean before an install was dirty after
uninstalling everything, because the emptied manifest, its lock, and the harness directories the
install created all survived.  The assertions here are the ones that run was making with `git
status --porcelain`, plus the boundary that keeps the reclamation honest: a directory holding
anything the install did not put there is never removed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from agent_artifacts.domain.result import Ok
from agent_artifacts.lifecycle import (
    LifecycleStatus,
    finalize_uninstall,
    prepare_uninstall,
)
from agent_artifacts.lifecycle.io import _tear_down
from agent_artifacts.lifecycle.model import ScopeTeardown
from tests.canonical_lifecycle_test import _install, _state
from tests.canonical_symlink_test import _fixture
from tests.marketplace_lifecycle_e2e_test import _COORDINATE, _environment

_MEMORY = "reference/memory/house"


def _uninstall(project: Path, paths, location, adapter, record=None):
    state = _state(project)
    record = record or state.installations[0]
    planned = prepare_uninstall(record, state, location, paths, adapter)
    assert isinstance(planned, Ok), planned
    return planned.value


def _git(project: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ("git", "-C", str(project), *arguments),
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout


class ScopeTeardownValueTest(unittest.TestCase):
    def test_directories_are_bound_deepest_first_and_beneath_one_state_root(self) -> None:
        teardown = ScopeTeardown(
            "/p/.agent-artifacts/manifest.json",
            "/p/.agent-artifacts/state.lock",
            "/p/.agent-artifacts",
            ("/p/.tabnine/agent/skills", "/p/.tabnine/agent"),
        )

        self.assertEqual(teardown.state_root, "/p/.agent-artifacts")
        # Shallow-first would try to remove a parent while its child still stands, so the order is
        # part of the value rather than of whoever applies it.
        for directories in (
            ("/p/.tabnine/agent", "/p/.tabnine/agent/skills"),
            ("/p/.claude/skills", "/p/.claude/skills"),
            ("relative/skills",),
        ):
            with self.subTest(directories=directories), self.assertRaises(ValueError):
                ScopeTeardown(
                    "/p/.agent-artifacts/manifest.json",
                    "/p/.agent-artifacts/state.lock",
                    "/p/.agent-artifacts",
                    directories,
                )

    def test_the_state_root_must_hold_both_the_manifest_and_its_lock(self) -> None:
        with self.assertRaises(ValueError):
            ScopeTeardown(
                "/p/.agent-artifacts/manifest.json",
                "/p/elsewhere/state.lock",
                "/p/.agent-artifacts",
            )


class ScopeTeardownPlanTest(unittest.TestCase):
    def test_the_last_uninstall_names_the_state_and_the_directory_it_empties(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, paths, location, _request, _catalog, _effective, adapter = _install(
                _fixture(root, "skill")
            )

            plan = _uninstall(project, paths, location, adapter)

            assert plan.teardown is not None
            self.assertEqual(plan.teardown.state_root, str(project / ".agent-artifacts"))
            self.assertEqual(plan.teardown.directories, (str(project / ".claude" / "skills"),))
            self.assertTrue(plan.teardown.reclaims_state)

    def test_the_harness_root_is_never_a_teardown_candidate(self) -> None:
        # ``.claude`` is the agent's own directory: an install may have created it, and nothing in
        # the record proves it did.  Reclaiming it would be this project inventing evidence.
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, paths, location, _request, _catalog, _effective, adapter = _install(
                _fixture(root, "skill")
            )

            plan = _uninstall(project, paths, location, adapter)

            assert plan.teardown is not None
            self.assertNotIn(str(project / ".claude"), plan.teardown.directories)

    def test_a_rewritten_file_at_the_project_root_contributes_no_directory(self) -> None:
        # A memory block is edited out of ``CLAUDE.md`` in the worktree the operator owns: nothing
        # is removed, so there is nothing above it that this uninstall emptied.
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, paths, location, _request, _catalog, _effective, adapter = _install(
                _fixture(root, "memory")
            )

            plan = _uninstall(project, paths, location, adapter)

            assert plan.teardown is not None
            self.assertEqual(plan.teardown.directories, ())
            self.assertTrue(plan.teardown.reclaims_state)


class ScopeTeardownApplyTest(unittest.TestCase):
    def test_the_emptied_manifest_its_lock_and_their_directory_are_reclaimed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, paths, location, _request, _catalog, _effective, adapter = _install(
                _fixture(root, "skill")
            )
            plan = _uninstall(project, paths, location, adapter)

            removed = finalize_uninstall(plan, plan.review_digest, adapter)

            assert isinstance(removed, Ok), removed
            self.assertEqual(removed.value.status, LifecycleStatus.REMOVED)
            self.assertEqual(removed.value.detail, "")
            self.assertFalse((project / ".agent-artifacts").exists())
            self.assertFalse((project / ".claude" / "skills").exists())
            self.assertTrue((project / ".claude").is_dir())

    def test_a_harness_directory_holding_foreign_content_survives(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, paths, location, _request, _catalog, _effective, adapter = _install(
                _fixture(root, "skill")
            )
            foreign = project / ".claude" / "skills" / "hand-written" / "SKILL.md"
            foreign.parent.mkdir(parents=True)
            foreign.write_text("# not ours\n", encoding="utf-8")
            plan = _uninstall(project, paths, location, adapter)

            removed = finalize_uninstall(plan, plan.review_digest, adapter)

            assert isinstance(removed, Ok), removed
            self.assertEqual(removed.value.status, LifecycleStatus.REMOVED)
            self.assertEqual(foreign.read_text(encoding="utf-8"), "# not ours\n")
            self.assertFalse((project / ".claude" / "skills" / "review").exists())
            # The scope's own directory is empty and goes; the one with a stranger in it stays.
            self.assertFalse((project / ".agent-artifacts").exists())

    def test_a_state_directory_holding_something_else_is_left_alone(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, paths, location, _request, _catalog, _effective, adapter = _install(
                _fixture(root, "skill")
            )
            note = project / ".agent-artifacts" / "operator-note.txt"
            note.write_text("keep\n", encoding="utf-8")
            plan = _uninstall(project, paths, location, adapter)

            removed = finalize_uninstall(plan, plan.review_digest, adapter)

            assert isinstance(removed, Ok), removed
            self.assertEqual(removed.value.status, LifecycleStatus.REMOVED)
            self.assertFalse((project / ".agent-artifacts" / "manifest.json").exists())
            self.assertEqual(note.read_text(encoding="utf-8"), "keep\n")


@unittest.skipIf(os.geteuid() == 0, "root ignores the directory permissions this test relies on")
class ScopeTeardownFailureTest(unittest.TestCase):
    def test_state_that_cannot_be_reclaimed_is_reported_rather_than_raised(self) -> None:
        # The uninstall is already proven when teardown runs.  Litter it cannot clear is the
        # operator's to know about, never a reason to fail a removal that succeeded.
        with tempfile.TemporaryDirectory() as raw:
            state_root = Path(raw) / ".agent-artifacts"
            state_root.mkdir()
            manifest = state_root / "manifest.json"
            manifest.write_text('{"installations": [], "schema_version": 2}\n', encoding="utf-8")
            (state_root / "state.lock").touch()
            state_root.chmod(0o500)

            try:
                detail = _tear_down(
                    ScopeTeardown(
                        str(manifest),
                        str(state_root / "state.lock"),
                        str(state_root),
                        (),
                        True,
                    )
                )
            finally:
                state_root.chmod(0o700)

            self.assertIn("installation state left in place", detail)
            self.assertTrue(manifest.is_file())


@unittest.skipIf(shutil.which("git") is None, "git is required to observe checkout cleanliness")
class ScopeTeardownEndToEndTest(unittest.TestCase):
    def test_a_checkout_that_was_clean_before_the_install_is_clean_after_teardown(self) -> None:
        with _environment() as env:
            _git(env.project, "init", "-q")
            _git(env.project, "config", "user.email", "acceptance@example.invalid")
            _git(env.project, "config", "user.name", "Acceptance")
            (env.project / "README.md").write_text("# project\n", encoding="utf-8")
            _git(env.project, "add", "-A")
            _git(env.project, "commit", "-qm", "initial")
            self.assertEqual(_git(env.project, "status", "--porcelain"), "")
            install_code, installed = env.run(
                "marketplace", "install", _COORDINATE, "--profile", "claude", "--yes"
            )
            self.assertEqual(install_code, 0, installed)
            self.assertNotEqual(_git(env.project, "status", "--porcelain"), "")

            code, payload = env.run(
                "marketplace", "uninstall", _COORDINATE, "--profile", "claude", "--yes"
            )

            self.assertEqual(code, 0, payload)
            self.assertEqual(payload["items"][0]["status"], "removed")
            self.assertEqual(
                _git(env.project, "status", "--porcelain"),
                "",
                sorted(map(str, env.project.rglob("*"))),
            )

    def test_the_manifest_waits_for_the_last_installation_in_the_scope(self) -> None:
        # Each uninstall reclaims the directories its own payload emptied; the manifest belongs to
        # the scope, so it survives every uninstall but the last.
        with _environment() as env:
            env.run("marketplace", "install", _COORDINATE, "--profile", "claude", "--yes")
            env.run("marketplace", "install", _MEMORY, "--profile", "claude", "--yes")

            code, payload = env.run(
                "marketplace", "uninstall", _COORDINATE, "--profile", "claude", "--yes"
            )

            self.assertEqual(code, 0, payload)
            self.assertTrue((env.project / ".agent-artifacts" / "manifest.json").is_file())
            self.assertFalse((env.project / ".claude" / "skills").exists())

            last_code, last = env.run(
                "marketplace", "uninstall", _MEMORY, "--profile", "claude", "--yes"
            )

            self.assertEqual(last_code, 0, last)
            self.assertFalse((env.project / ".agent-artifacts").exists())

    def test_user_scope_reclaims_its_manifest_and_the_directory_it_emptied(self) -> None:
        # The user state root is shared with the object-reference index, so it stays: what the
        # uninstall owns there is the manifest and its lock, and those go.
        with _environment() as env:
            install_code, installed = env.run(
                "marketplace",
                "install",
                _COORDINATE,
                "--profile",
                "claude",
                "--scope",
                "user",
                "--yes",
            )
            self.assertEqual(install_code, 0, installed)
            state_root = Path(env.paths.data_root) / "state"
            self.assertTrue((state_root / "manifest.json").is_file())

            code, payload = env.run(
                "marketplace",
                "uninstall",
                _COORDINATE,
                "--profile",
                "claude",
                "--scope",
                "user",
                "--yes",
            )

            self.assertEqual(code, 0, payload)
            self.assertFalse((state_root / "manifest.json").exists())
            self.assertFalse((state_root / "state.lock").exists())
            self.assertTrue((state_root / "object-references.json").is_file())
            self.assertFalse((env.home / ".claude" / "skills").exists())
            self.assertTrue((env.home / ".claude").is_dir())


if __name__ == "__main__":
    unittest.main()
