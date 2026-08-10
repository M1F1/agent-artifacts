from __future__ import annotations

import contextlib
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_artifacts import cli
from agent_artifacts.commands import registry as registry_command
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.protocol.native_tree import SnapshotEntryKind
from agent_artifacts.protocol.registry_schema import parse_registry_index
from agent_artifacts.registry_maintenance.model import NativeReferenceAcquisition
from agent_artifacts.registry_maintenance.planning import (
    plan_registry_entry_add,
    project_registry_mutation,
)
from tests.registry_maintenance_fixtures import (
    empty_registry_snapshot,
    native_snapshot,
    registry_entry,
)

ROOT = Path(__file__).resolve().parents[1]


def _run(*arguments: str) -> tuple[int, str]:
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = cli.main(list(arguments))
    return code, output.getvalue()


def _git(root: Path, *arguments: str) -> None:
    subprocess.run(
        ("git", "-C", str(root), *arguments),
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _tree_bytes(root: Path) -> tuple[tuple[str, bytes], ...]:
    return tuple(
        (path.relative_to(root).as_posix(), path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file() and ".git" not in path.relative_to(root).parts
    )


def _write_snapshot(root: Path, snapshot) -> None:
    for entry in snapshot.entries:
        target = root.joinpath(*entry.path.parts)
        if entry.kind is SnapshotEntryKind.DIRECTORY:
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(entry.content)


class RegistryCliIntegrationTest(unittest.TestCase):
    def test_registry_lifecycle_has_non_mutating_check_and_quality_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "registry"
            root.mkdir()
            _git(root, "init", "-q")

            code, output = _run(
                "registry",
                "init",
                "--source",
                str(root),
                "--source-id",
                "company-registry",
                "--display-name",
                "Company Registry",
                "--json",
            )
            self.assertEqual(code, 0, output)
            self.assertTrue((root / ".github/workflows/aart-registry.yml").is_file())

            before_reads = _tree_bytes(root)
            for arguments in (
                ("validate", "--strict"),
                ("audit",),
                ("diff",),
            ):
                code, output = _run("registry", *arguments, "--source", str(root), "--json")
                if arguments[0] == "validate":
                    self.assertEqual(code, 1, output)
                else:
                    self.assertEqual(code, 0, output)
                self.assertEqual(_tree_bytes(root), before_reads)

            code, output = _run("registry", "lock", "--source", str(root), "--check", "--json")
            self.assertEqual(code, 1, output)
            self.assertFalse((root / "aart.lock.json").exists())
            self.assertEqual(_run("registry", "lock", "--source", str(root))[0], 0)

            code, output = _run("registry", "build", "--source", str(root), "--check", "--json")
            self.assertEqual(code, 1, output)
            self.assertFalse((root / "aart.index.json").exists())
            self.assertEqual(_run("registry", "build", "--source", str(root))[0], 0)

            self.assertEqual(
                _run(
                    "registry",
                    "scaffold",
                    "--source",
                    str(root),
                    "skill",
                    "review-python",
                    "--summary",
                    "Review Python changes against the company checklist.",
                    "--profile",
                    "codex",
                    "--platform",
                    "darwin",
                )[0],
                0,
            )
            self.assertTrue((root / "artifacts/skill/review-python/payload/SKILL.md").is_file())

            marker = root / "aart-registry.json"
            marker.write_text("{ " + marker.read_text(encoding="utf-8")[1:], encoding="utf-8")
            noncanonical = marker.read_bytes()
            code, output = _run("registry", "format", "--source", str(root), "--check", "--json")
            self.assertEqual(code, 1, output)
            self.assertEqual(marker.read_bytes(), noncanonical)
            self.assertEqual(_run("registry", "format", "--source", str(root))[0], 0)
            self.assertNotEqual(marker.read_bytes(), noncanonical)

    def test_quality_commands_accept_a_read_only_registry_snapshot_without_git(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "snapshot"
            shutil.copytree(ROOT / "tests/fixtures/protocol/registry-v1", root)
            before = _tree_bytes(root)
            for arguments in (
                ("validate", "--strict", "--frozen"),
                ("audit",),
                ("test", "--compatibility", "all", "--latest-version", "1.9.9"),
            ):
                code, output = _run("registry", *arguments, "--source", str(root), "--json")
                self.assertEqual(code, 0, output)
                self.assertEqual(_tree_bytes(root), before)

    def test_lock_and_build_commands_compile_an_acquired_native_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "registry"
            root.mkdir()
            _git(root, "init", "-q")
            authored = plan_registry_entry_add(empty_registry_snapshot(), registry_entry())
            assert isinstance(authored, Ok)
            projected = project_registry_mutation(empty_registry_snapshot(), authored.value)
            assert isinstance(projected, Ok)
            _write_snapshot(root, projected.value)
            acquisition = NativeReferenceAcquisition(
                "https://github.com/example/reference-skills.git",
                "main",
                "a" * 40,
                native_snapshot(),
            )

            with patch(
                "agent_artifacts.commands.registry._acquire_references",
                return_value=Ok((acquisition,)),
            ):
                self.assertEqual(_run("registry", "lock", "--source", str(root))[0], 0)
                self.assertEqual(_run("registry", "build", "--source", str(root))[0], 0)
                before = _tree_bytes(root)
                self.assertEqual(
                    _run("registry", "lock", "--source", str(root), "--check")[0],
                    0,
                )
                self.assertEqual(
                    _run("registry", "build", "--source", str(root), "--check")[0],
                    0,
                )
                self.assertEqual(_tree_bytes(root), before)

            parsed = parse_registry_index((root / "aart.index.json").read_bytes())
            assert isinstance(parsed, Ok)
            self.assertEqual(str(parsed.value.artifacts[0].source_id), "reference-native-source")

    def test_unapproved_reference_is_rejected_before_any_network_acquisition(self) -> None:
        entry = plan_registry_entry_add(
            empty_registry_snapshot(),
            registry_entry(review_status="pending"),
        )
        assert isinstance(entry, Ok)
        authored = project_registry_mutation(empty_registry_snapshot(), entry.value)
        assert isinstance(authored, Ok)

        with patch("agent_artifacts.commands.registry.acquire_git_snapshot") as acquire:
            result = registry_command._acquire_references(authored.value)

        self.assertIsInstance(result, Err)
        acquire.assert_not_called()

    def test_migration_is_preview_first_and_apply_requires_explicit_flag(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            legacy = Path(temporary) / "legacy"
            destination = Path(temporary) / "registry"
            shutil.copytree(ROOT / "tests/fixtures/importers/legacy_catalog", legacy)
            destination.mkdir()
            _git(legacy, "init", "-q", "-b", "main")
            _git(legacy, "config", "user.name", "AART Test")
            _git(legacy, "config", "user.email", "aart@example.invalid")
            _git(legacy, "add", ".")
            _git(legacy, "commit", "-q", "-m", "fixture")
            _git(destination, "init", "-q")
            base = (
                "registry",
                "migrate",
                "--legacy-source",
                str(legacy),
                "--origin-url",
                "https://github.com/example/legacy-catalog.git",
                "--ref",
                "main",
                "--source",
                str(destination),
                "--source-id",
                "company-registry",
                "--display-name",
                "Company Registry",
                "--profile",
                "codex",
                "--json",
            )

            code, output = _run(*base)
            self.assertEqual(code, 0, output)
            self.assertGreater(json.loads(output)["changed_paths"], 0)
            self.assertEqual(_tree_bytes(destination), ())

            code, output = _run(*base, "--apply")
            self.assertEqual(code, 0, output)
            self.assertTrue((destination / "aart-registry.json").is_file())
            self.assertTrue((destination / "artifacts/skill/demo/artifact.json").is_file())


if __name__ == "__main__":
    unittest.main()
