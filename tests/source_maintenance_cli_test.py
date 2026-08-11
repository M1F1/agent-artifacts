"""`aart source sync|health|doctor` against a real home, store, and local source (SRC02).

These commands exist so nobody has to re-add an existing alias to refresh it. The tests therefore
pin the property that matters most: none of them may change source identity, configuration, or
policy — only managed snapshots and the store layout.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_artifacts import cli
from agent_artifacts.configuration.model import (
    ConfiguredSource,
    ReportingSettings,
    SourceKind,
    SyncSettings,
    UserConfiguration,
)
from agent_artifacts.configuration.paths import Platform, resolve_config_paths
from agent_artifacts.configuration.schema import user_configuration_bytes
from agent_artifacts.domain.identifiers import SourceAlias
from agent_artifacts.io.source_migration import existing_source_directories, stored_schema_version
from agent_artifacts.sources.migration import SOURCE_STORE_SCHEMA_VERSION
from agent_artifacts.sources.model import legacy_source_instance_id, source_instance_id

_FIXTURE = Path(__file__).parent / "fixtures" / "protocol" / "native-source-v1"


class _Environment:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.home = root / "home"
        self.home.mkdir()
        self.environ = {
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "XDG_DATA_HOME": str(self.home / ".local" / "share"),
            "XDG_CACHE_HOME": str(self.home / ".cache"),
        }
        platform = Platform.DARWIN if os.sys.platform == "darwin" else Platform.LINUX
        self.paths = resolve_config_paths(
            platform,
            home=str(self.home),
            xdg_config_home=self.environ["XDG_CONFIG_HOME"],
            xdg_data_home=self.environ["XDG_DATA_HOME"],
            xdg_cache_home=self.environ["XDG_CACHE_HOME"],
        )
        self.source = ConfiguredSource(
            SourceAlias("reference"),
            SourceKind.SOURCE_LOCAL,
            str(_FIXTURE.resolve()),
            None,
            True,
        )
        self.config_path = Path(self.paths.user_config_file)
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.write(self.source)

    def write(self, *sources: ConfiguredSource) -> None:
        self.config_path.write_bytes(
            user_configuration_bytes(
                UserConfiguration(1, sources, None, SyncSettings(), ReportingSettings())
            )
        )

    def run(self, *argv: str):
        stdout = io.StringIO()
        with (
            mock.patch.dict(os.environ, self.environ, clear=False),
            contextlib.redirect_stdout(stdout),
        ):
            code = cli.main([*argv, "--json"])
        raw = stdout.getvalue()
        return code, (json.loads(raw) if raw.strip() else None)


@contextlib.contextmanager
def _environment():
    with tempfile.TemporaryDirectory() as raw:
        yield _Environment(Path(raw).resolve())


class SourceSyncCommandTest(unittest.TestCase):
    def test_sync_publishes_a_snapshot_without_touching_configuration(self) -> None:
        with _environment() as env:
            before = env.config_path.read_bytes()

            code, payload = env.run("source", "sync")

            self.assertEqual(code, 0, payload)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["sources"][0]["alias"], "reference")
            self.assertEqual(payload["sources"][0]["disposition"], "published")
            self.assertEqual(env.config_path.read_bytes(), before)

    def test_a_second_sync_reports_unchanged(self) -> None:
        with _environment() as env:
            env.run("source", "sync")

            code, payload = env.run("source", "sync")

            self.assertEqual(code, 0, payload)
            self.assertEqual(payload["sources"][0]["disposition"], "unchanged")

    def test_sync_can_select_one_alias(self) -> None:
        with _environment() as env:
            code, payload = env.run("source", "sync", "--alias", "reference")

            self.assertEqual(code, 0, payload)
            self.assertEqual(len(payload["sources"]), 1)

    def test_an_unknown_alias_is_a_structured_error_and_syncs_nothing(self) -> None:
        with _environment() as env:
            code, payload = env.run("source", "sync", "--alias", "absent")

            self.assertEqual(code, 1)
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["diagnostics"][0]["code"], "source-not-configured")


class SourceHealthCommandTest(unittest.TestCase):
    def test_health_reports_missing_before_a_sync(self) -> None:
        with _environment() as env:
            code, payload = env.run("source", "health")

            self.assertEqual(code, 1, payload)
            self.assertEqual(payload["sources"][0]["health"], "missing")
            self.assertIsNone(payload["sources"][0]["resolved_revision"])

    def test_health_reports_healthy_after_a_sync(self) -> None:
        with _environment() as env:
            env.run("source", "sync")

            code, payload = env.run("source", "health")

            self.assertEqual(code, 0, payload)
            self.assertEqual(payload["sources"][0]["health"], "healthy")
            self.assertIsNotNone(payload["sources"][0]["resolved_revision"])
            self.assertEqual(
                payload["sources"][0]["instance_id"],
                source_instance_id(env.source).value,
            )

    def test_health_never_writes_configuration_or_snapshots(self) -> None:
        with _environment() as env:
            env.run("source", "sync")
            before_config = env.config_path.read_bytes()
            before_store = existing_source_directories(env.paths.data_root)

            env.run("source", "health")

            self.assertEqual(env.config_path.read_bytes(), before_config)
            self.assertEqual(existing_source_directories(env.paths.data_root), before_store)


class SourceDoctorCommandTest(unittest.TestCase):
    def _legacy_git_store(self, env: _Environment) -> ConfiguredSource:
        """Configure a Git source and plant a directory under its pre-SRC02 identity."""

        git = ConfiguredSource(
            SourceAlias("team"),
            SourceKind.SOURCE_GIT,
            "https://git.example/team/artifacts.git",
            "main",
            True,
        )
        env.write(git)
        legacy = Path(env.paths.data_root) / "sources" / legacy_source_instance_id(git).value
        legacy.mkdir(parents=True)
        (legacy / "current.json").write_text("legacy pointer", encoding="utf-8")
        return git

    def test_doctor_reports_a_pending_migration_without_applying_it(self) -> None:
        with _environment() as env:
            git = self._legacy_git_store(env)

            code, payload = env.run("source", "doctor")

            self.assertEqual(code, 0, payload)
            self.assertTrue(payload["migration_required"])
            self.assertFalse(payload["applied"])
            self.assertEqual(payload["rebinds"][0]["alias"], "team")
            self.assertEqual(payload["rebinds"][0]["to"], source_instance_id(git).value)
            # Nothing moved.
            self.assertIn(
                legacy_source_instance_id(git).value,
                existing_source_directories(env.paths.data_root),
            )

    def test_doctor_apply_rebinds_and_records_the_layout_version(self) -> None:
        with _environment() as env:
            git = self._legacy_git_store(env)

            code, payload = env.run("source", "doctor", "--apply")

            self.assertEqual(code, 0, payload)
            self.assertTrue(payload["applied"])
            self.assertEqual(payload["rebound"], ["team"])
            target = Path(env.paths.data_root) / "sources" / source_instance_id(git).value
            self.assertEqual(
                (target / "current.json").read_text(encoding="utf-8"), "legacy pointer"
            )
            self.assertEqual(
                stored_schema_version(env.paths.data_root), SOURCE_STORE_SCHEMA_VERSION
            )

    def test_doctor_apply_is_idempotent(self) -> None:
        with _environment() as env:
            self._legacy_git_store(env)
            env.run("source", "doctor", "--apply")

            code, payload = env.run("source", "doctor", "--apply")

            self.assertEqual(code, 0, payload)
            self.assertFalse(payload["migration_required"])

    def test_doctor_reports_an_unattributable_legacy_directory_instead_of_guessing(self) -> None:
        with _environment() as env:
            origin = "https://git.example/team/artifacts.git"
            main = ConfiguredSource(
                SourceAlias("main-track"), SourceKind.SOURCE_GIT, origin, "main", True
            )
            release = ConfiguredSource(
                SourceAlias("release-track"), SourceKind.SOURCE_GIT, origin, "release", True
            )
            env.write(main, release)
            legacy = Path(env.paths.data_root) / "sources" / legacy_source_instance_id(main).value
            legacy.mkdir(parents=True)

            code, payload = env.run("source", "doctor", "--apply")

            self.assertEqual(code, 1)
            self.assertEqual(payload["diagnostics"][0]["code"], "source-store-ambiguous")
            self.assertTrue(legacy.is_dir(), "an ambiguous directory must be left untouched")

    def test_doctor_on_a_current_store_reports_no_work(self) -> None:
        with _environment() as env:
            env.run("source", "sync")

            code, payload = env.run("source", "doctor", "--apply")

            self.assertEqual(code, 0, payload)
            self.assertEqual(payload["rebinds"], [])


if __name__ == "__main__":  # pragma: no cover - unittest entry point
    unittest.main()
