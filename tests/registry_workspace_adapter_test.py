from __future__ import annotations

import fcntl
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.io.registry_workspace import FilesystemRegistryWorkspace
from agent_artifacts.protocol.native_tree import SnapshotOrigin, SourceSnapshot
from agent_artifacts.protocol.semver import SemVer
from agent_artifacts.registry_commands.model import RegistryApplyCommand, RegistryInitOptions
from agent_artifacts.registry_commands.planning import plan_registry_init


class RegistryWorkspaceAdapterTest(unittest.TestCase):
    def test_apply_requires_real_writable_git_checkout_and_exact_preconditions(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            root.mkdir()
            empty = SourceSnapshot(SnapshotOrigin.LOCAL, ())
            plan = plan_registry_init(
                empty,
                RegistryInitOptions(
                    "company-registry",
                    "Company Registry",
                    SemVer(1, 0, 0),
                    SemVer(2, 0, 0),
                ),
            )
            assert isinstance(plan, Ok)
            adapter = FilesystemRegistryWorkspace(str(root))
            self.assertIsInstance(adapter.apply(RegistryApplyCommand(plan.value)), Err)

            (root / ".git").mkdir()
            self.assertIsInstance(adapter.apply(RegistryApplyCommand(plan.value)), Err)
            subprocess.run(
                ("git", "-C", str(root), "init", "-q"),
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            hooks_before = tuple(sorted((root / ".git" / "hooks").iterdir()))
            applied = adapter.apply(RegistryApplyCommand(plan.value))
            assert isinstance(applied, Ok), applied
            self.assertEqual(applied.value.changed_paths, plan.value.changed_paths)
            self.assertIsInstance(adapter.apply(RegistryApplyCommand(plan.value)), Err)
            self.assertEqual(tuple(sorted((root / ".git" / "hooks").iterdir())), hooks_before)

    def test_read_only_snapshot_does_not_require_git_or_write_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "managed-snapshot"
            root.mkdir()
            (root / "aart-registry.json").write_text("{}", encoding="utf-8")
            os.chmod(root, 0o500)
            try:
                result = FilesystemRegistryWorkspace(str(root)).snapshot()
                self.assertIsInstance(result, Ok)
            finally:
                os.chmod(root, 0o700)

    def test_symlinked_managed_content_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            root.mkdir()
            target = Path(temp) / "marker.json"
            target.write_text("{}", encoding="utf-8")
            (root / "aart-registry.json").symlink_to(target)
            self.assertIsInstance(FilesystemRegistryWorkspace(str(root)).snapshot(), Err)

    def test_partial_write_failure_rolls_back_files_and_created_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            root.mkdir()
            (root / ".git").mkdir()
            empty = SourceSnapshot(SnapshotOrigin.LOCAL, ())
            plan = plan_registry_init(
                empty,
                RegistryInitOptions(
                    "company-registry",
                    "Company Registry",
                    SemVer(1, 0, 0),
                    SemVer(2, 0, 0),
                ),
            )
            assert isinstance(plan, Ok)
            adapter = FilesystemRegistryWorkspace(str(root))
            original = adapter._write
            calls = 0

            def flaky(path, content, executable):
                nonlocal calls
                calls += 1
                if calls == 2:
                    return Err(
                        (
                            Diagnostic(
                                DiagnosticCode("fault-injected"),
                                Severity.ERROR,
                                "injected write failure",
                            ),
                        )
                    )
                return original(path, content, executable)

            with patch.object(adapter, "_write", side_effect=flaky):
                applied = adapter.apply(RegistryApplyCommand(plan.value))

            self.assertIsInstance(applied, Err)
            restored = adapter.snapshot()
            assert isinstance(restored, Ok)
            self.assertEqual(restored.value, empty)

    def test_change_between_initial_snapshot_and_write_is_rejected_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            root.mkdir()
            subprocess.run(
                ("git", "-C", str(root), "init", "-q"),
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            empty = SourceSnapshot(SnapshotOrigin.LOCAL, ())
            plan = plan_registry_init(
                empty,
                RegistryInitOptions(
                    "company-registry",
                    "Company Registry",
                    SemVer(1, 0, 0),
                    SemVer(2, 0, 0),
                ),
            )
            assert isinstance(plan, Ok)
            adapter = FilesystemRegistryWorkspace(str(root))
            original = adapter._backup
            raced = False

            def racing_backup(path):
                nonlocal raced
                if not raced:
                    raced = True
                    target = root.joinpath(*path.parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(b"concurrent maintainer content\n")
                return original(path)

            with patch.object(adapter, "_backup", side_effect=racing_backup):
                applied = adapter.apply(RegistryApplyCommand(plan.value))

            self.assertIsInstance(applied, Err)
            self.assertEqual(
                root.joinpath(*plan.value.changes[0].path.parts).read_bytes(),
                b"concurrent maintainer content\n",
            )

    def test_concurrent_registry_writer_is_rejected_before_read_or_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "registry"
            root.mkdir()
            subprocess.run(
                ("git", "-C", str(root), "init", "-q"),
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            plan = plan_registry_init(
                SourceSnapshot(SnapshotOrigin.LOCAL, ()),
                RegistryInitOptions(
                    "company-registry",
                    "Company Registry",
                    SemVer(1, 0, 0),
                    SemVer(2, 0, 0),
                ),
            )
            assert isinstance(plan, Ok)
            descriptor = os.open(root, os.O_RDONLY)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                applied = FilesystemRegistryWorkspace(str(root)).apply(
                    RegistryApplyCommand(plan.value)
                )
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)

            self.assertIsInstance(applied, Err)
            self.assertFalse((root / "aart-registry.json").exists())


if __name__ == "__main__":
    unittest.main()
