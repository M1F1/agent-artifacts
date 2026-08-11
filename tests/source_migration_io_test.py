"""Applying the ref-aware store migration against a real filesystem (SRC02).

This moves real user data, so the tests use real directories: no mocked rename, no fake tree.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_artifacts.configuration.model import (
    ConfiguredSource,
    ReportingSettings,
    SourceKind,
    SyncSettings,
    UserConfiguration,
)
from agent_artifacts.domain.identifiers import SourceAlias
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.io.source_migration import (
    apply_source_store_migration,
    existing_source_directories,
    stored_schema_version,
)
from agent_artifacts.sources.migration import (
    SOURCE_STORE_SCHEMA_VERSION,
    plan_source_store_migration,
)
from agent_artifacts.sources.model import legacy_source_instance_id, source_instance_id

ORIGIN = "https://git.example/team/artifacts.git"


def _git(alias: str, ref: str) -> ConfiguredSource:
    return ConfiguredSource(SourceAlias(alias), SourceKind.SOURCE_GIT, ORIGIN, ref, True)


def _configuration(*sources: ConfiguredSource) -> UserConfiguration:
    return UserConfiguration(1, sources, None, SyncSettings(), ReportingSettings())


class SourceMigrationIOTest(unittest.TestCase):
    def _store(self, root: Path, *directories: str) -> str:
        data_root = str(root / "data")
        sources = Path(data_root) / "sources"
        for name in directories:
            (sources / name).mkdir(parents=True)
            (sources / name / "current.json").write_text(f"pointer for {name}", encoding="utf-8")
        sources.mkdir(parents=True, exist_ok=True)
        return data_root

    def test_a_legacy_directory_is_rebound_with_its_contents_intact(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = _git("team", "main")
            legacy = legacy_source_instance_id(source).value
            data_root = self._store(Path(raw).resolve(), legacy)
            configuration = _configuration(source)

            planned = plan_source_store_migration(
                configuration,
                existing=existing_source_directories(data_root),
                stored_schema_version=stored_schema_version(data_root),
            )
            assert isinstance(planned, Ok), planned
            applied = apply_source_store_migration(planned.value, data_root=data_root)

            self.assertIsInstance(applied, Ok)
            assert isinstance(applied, Ok)
            self.assertEqual(applied.value, ("team",))
            target = Path(data_root) / "sources" / source_instance_id(source).value
            self.assertTrue(target.is_dir())
            self.assertEqual(
                (target / "current.json").read_text(encoding="utf-8"),
                f"pointer for {legacy}",
            )
            self.assertFalse((Path(data_root) / "sources" / legacy).exists())

    def test_the_layout_version_is_recorded_only_after_rebinding(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = _git("team", "main")
            data_root = self._store(Path(raw).resolve(), legacy_source_instance_id(source).value)

            self.assertIsNone(stored_schema_version(data_root))
            planned = plan_source_store_migration(
                _configuration(source),
                existing=existing_source_directories(data_root),
            )
            assert isinstance(planned, Ok), planned
            apply_source_store_migration(planned.value, data_root=data_root)

            self.assertEqual(stored_schema_version(data_root), SOURCE_STORE_SCHEMA_VERSION)

    def test_applying_twice_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = _git("team", "main")
            data_root = self._store(Path(raw).resolve(), legacy_source_instance_id(source).value)

            for _ in range(2):
                planned = plan_source_store_migration(
                    _configuration(source),
                    existing=existing_source_directories(data_root),
                    stored_schema_version=stored_schema_version(data_root),
                )
                assert isinstance(planned, Ok), planned
                applied = apply_source_store_migration(planned.value, data_root=data_root)
                self.assertIsInstance(applied, Ok)

            self.assertEqual(
                existing_source_directories(data_root),
                (source_instance_id(source).value,),
            )

    def test_a_partially_applied_migration_resumes_correctly(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            first = ConfiguredSource(
                SourceAlias("alpha"),
                SourceKind.SOURCE_GIT,
                "https://git.example/a.git",
                "main",
                True,
            )
            second = ConfiguredSource(
                SourceAlias("beta"),
                SourceKind.SOURCE_GIT,
                "https://git.example/b.git",
                "main",
                True,
            )
            # Simulate a crash after the first rename: one new name, one still legacy.
            data_root = self._store(
                Path(raw).resolve(),
                source_instance_id(first).value,
                legacy_source_instance_id(second).value,
            )

            planned = plan_source_store_migration(
                _configuration(first, second),
                existing=existing_source_directories(data_root),
                stored_schema_version=stored_schema_version(data_root),
            )
            assert isinstance(planned, Ok), planned
            applied = apply_source_store_migration(planned.value, data_root=data_root)

            self.assertIsInstance(applied, Ok)
            assert isinstance(applied, Ok)
            self.assertEqual(applied.value, ("beta",))
            self.assertEqual(
                existing_source_directories(data_root),
                tuple(sorted((source_instance_id(first).value, source_instance_id(second).value))),
            )

    def test_a_migration_never_renames_onto_an_existing_directory(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = _git("team", "main")
            data_root = self._store(
                Path(raw).resolve(),
                legacy_source_instance_id(source).value,
                source_instance_id(source).value,
            )

            planned = plan_source_store_migration(
                _configuration(source),
                existing=existing_source_directories(data_root),
                stored_schema_version=stored_schema_version(data_root),
            )

            self.assertIsInstance(planned, Err)
            assert isinstance(planned, Err)
            self.assertEqual(planned.diagnostics[0].code.value, "source-store-conflict")
            # Both pointers survive an unapplied plan.
            self.assertEqual(len(existing_source_directories(data_root)), 2)

    def test_an_unreadable_version_file_is_treated_as_an_unmarked_layout(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            data_root = self._store(Path(raw).resolve())
            (Path(data_root) / "sources" / "store.json").write_text("{not json", encoding="utf-8")

            self.assertIsNone(stored_schema_version(data_root))

    def test_a_missing_store_reports_no_directories_rather_than_failing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            data_root = str(Path(raw).resolve() / "absent")

            self.assertEqual(existing_source_directories(data_root), ())
            self.assertIsNone(stored_schema_version(data_root))

    def test_the_recorded_version_file_is_canonical_json(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = _git("team", "main")
            data_root = self._store(Path(raw).resolve(), legacy_source_instance_id(source).value)
            planned = plan_source_store_migration(
                _configuration(source),
                existing=existing_source_directories(data_root),
            )
            assert isinstance(planned, Ok), planned
            apply_source_store_migration(planned.value, data_root=data_root)

            recorded = json.loads(
                (Path(data_root) / "sources" / "store.json").read_text(encoding="utf-8")
            )

            self.assertEqual(recorded, {"schema_version": SOURCE_STORE_SCHEMA_VERSION})


if __name__ == "__main__":  # pragma: no cover - unittest entry point
    unittest.main()
