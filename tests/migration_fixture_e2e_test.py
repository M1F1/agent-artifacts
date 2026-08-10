"""Committed complete 0.1 project/user fixtures through apply, status, and rollback."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_artifacts.application.legacy_state_migration import (
    LegacyStateMigrationRequest,
    build_legacy_migration_candidates,
)
from agent_artifacts.application.state_migration import StateMigrationService
from agent_artifacts.consumer.model import ConsumerContext
from agent_artifacts.domain.result import Ok
from agent_artifacts.install_state.paths import install_state_paths
from agent_artifacts.install_state.schema import parse_install_state
from agent_artifacts.installation.io import LocalInstallAdapter
from agent_artifacts.installation.model import LinkOperation
from agent_artifacts.io.state_store import LocalStateStore
from agent_artifacts.lifecycle.application import (
    finalize_uninstall,
    finalize_update,
    prepare_uninstall,
    prepare_update,
    status_installations,
)
from agent_artifacts.lifecycle.io import LocalLifecycleAdapter
from agent_artifacts.lifecycle.model import LifecycleSelection, LifecycleStatus
from agent_artifacts.marketplace.model import MarketplaceCatalog
from agent_artifacts.profiles.builtin import builtin
from tests.canonical_symlink_test import _fixture

FIXTURES = Path(__file__).parent / "fixtures/migrations/0.1"
GUIDELINE = b"Review carefully.\n"
MEMORY = (
    b"prefix\n<!-- >>> agent-artifacts memory:review >>> -->\nRemember reviews.\n"
    b"<!-- <<< agent-artifacts memory:review <<< -->\nsuffix\n"
)


def _context(root: Path) -> ConsumerContext:
    fixtures = tuple(
        _fixture(root, kind) for kind in ("skill", "guideline", "mcp", "hook", "memory")
    )
    first = fixtures[0]
    catalog = MarketplaceCatalog(
        first[5].sources,
        tuple(item for fixture in fixtures for item in fixture[5].items),
    )
    return ConsumerContext(catalog, first[6], builtin(), first[3], first[2])


def _write_effects(root: Path, scope: str) -> None:
    skill = root / ".claude/skills/review"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# legacy\n", encoding="utf-8")
    guideline = root / (
        ".claude/guidelines/review.md" if scope == "project" else ".claude/rules/review.md"
    )
    guideline.parent.mkdir(parents=True, exist_ok=True)
    guideline.write_bytes(GUIDELINE)
    hooks = root / ".claude/hooks/review"
    hooks.mkdir(parents=True)
    (hooks / "run.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (root / (".mcp.json" if scope == "project" else ".claude.json")).write_text(
        '{"mcpServers":{"review":{"command":"legacy-mcp"}}}', encoding="utf-8"
    )
    settings = root / ".claude/settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(
        '{"hooks":{"PreToolUse":[{"matcher":"*","command":"legacy-hook"}]}}',
        encoding="utf-8",
    )
    memory = root / ("CLAUDE.md" if scope == "project" else ".claude/CLAUDE.md")
    memory.parent.mkdir(parents=True, exist_ok=True)
    memory.write_bytes(MEMORY)


class MigrationFixtureE2ETest(unittest.TestCase):
    def _exercise(self, scope: str) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            context = _context(root)
            effect_root = (
                Path(context.location.project_root)
                if scope == "project"
                else Path(context.location.user_home)
            )
            _write_effects(effect_root, scope)
            fixture = (FIXTURES / f"manifest-{scope}-all-types.json").read_bytes()
            legacy = fixture.replace(b"/fixture-home", str(effect_root).encode())
            paths = install_state_paths(
                scope,  # type: ignore[arg-type]
                project_root=context.location.project_root,
                user_home=context.location.user_home,
                data_root=context.location.data_root,
            )
            legacy_path = Path(paths.legacy_path)
            legacy_path.parent.mkdir(parents=True, exist_ok=True)
            legacy_path.write_bytes(legacy)
            candidates = build_legacy_migration_candidates(
                LegacyStateMigrationRequest(legacy, scope),  # type: ignore[arg-type]
                context,
                LocalInstallAdapter(),
            )
            self.assertIsInstance(candidates, Ok)
            assert isinstance(candidates, Ok)
            service = StateMigrationService(LocalStateStore())
            plan = service.prepare(paths, candidates.value)
            self.assertIsInstance(plan, Ok)
            assert isinstance(plan, Ok)

            applied = service.apply(plan.value)
            self.assertIsInstance(applied, Ok)
            parsed_state = parse_install_state(Path(paths.destination_path).read_bytes())
            assert isinstance(parsed_state, Ok)
            status = status_installations(
                parsed_state.value,
                LifecycleSelection(scope),  # type: ignore[arg-type]
                context.location,
                LocalLifecycleAdapter(),
            )
            assert isinstance(status, Ok)
            self.assertEqual(
                {item.status for item in status.value.items},
                {LifecycleStatus.CURRENT},
            )
            self.assertEqual(len(candidates.value), 5)
            self.assertEqual(
                {effect.kind for candidate in candidates.value for effect in candidate.effects},
                {"copy-tree", "write-file", "merge-json", "managed-block"},
            )
            durable = StateMigrationService(LocalStateStore()).current_receipt(paths)
            self.assertIsInstance(durable, Ok)
            assert isinstance(durable, Ok)
            self.assertIsNotNone(durable.value)
            assert durable.value is not None
            rolled_back = StateMigrationService(LocalStateStore()).rollback(durable.value)
            self.assertIsInstance(rolled_back, Ok)
            self.assertEqual(legacy_path.read_bytes(), legacy)

    def test_complete_project_fixture(self) -> None:
        self._exercise("project")

    def test_complete_user_fixture_including_earliest_missing_install_metadata(self) -> None:
        self._exercise("user")

    def test_migrated_copy_updates_and_uninstalls_through_canonical_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            fixture = _fixture(root, "skill")
            project, _checkout, store_paths, location, _request, catalog, effective = fixture
            context = ConsumerContext(catalog, effective, builtin(), location, store_paths)
            destination = ".claude/skills/review"
            installed = project / destination
            installed.mkdir(parents=True)
            (installed / "SKILL.md").write_text("# legacy\n", encoding="utf-8")
            legacy = (
                b'{"repo":"M1F1/agent-artifacts","installed":[{"artifact":"review",'
                b'"type":"skill","profile":"claude","source":"main:'
                + b"7"
                * 40
                + b'","files":{".claude/skills/review":""},'
                b'"installed_at":"2025-01-01T00:00:00Z"}]}'
            )
            paths = install_state_paths(
                "project",
                project_root=str(project),
                user_home=location.user_home,
                data_root=location.data_root,
            )
            state_path = Path(paths.legacy_path)
            state_path.parent.mkdir(parents=True)
            state_path.write_bytes(legacy)
            candidates = build_legacy_migration_candidates(
                LegacyStateMigrationRequest(legacy, "project"),
                context,
                LocalInstallAdapter(),
            )
            assert isinstance(candidates, Ok)
            migration = StateMigrationService(LocalStateStore())
            plan = migration.prepare(paths, candidates.value)
            assert isinstance(plan, Ok)
            self.assertIsInstance(migration.apply(plan.value), Ok)
            migrated = parse_install_state(state_path.read_bytes())
            assert isinstance(migrated, Ok)
            record = migrated.value.installations[0]
            adapter = LocalLifecycleAdapter()

            update = prepare_update(
                record,
                catalog,
                effective,
                builtin()["claude"],
                location,
                store_paths,
                adapter,
            )
            assert isinstance(update, Ok)
            self.assertIsNotNone(update.value.install_plan)
            updated = finalize_update(
                update.value,
                update.value.review_digest,
                catalog,
                effective,
                adapter,
            )
            assert isinstance(updated, Ok)
            canonical = parse_install_state(state_path.read_bytes())
            assert isinstance(canonical, Ok)
            self.assertEqual(
                canonical.value.installations[0].artifact.object_digest,
                catalog.items[0].artifact.artifact.object_digest,
            )
            uninstall = prepare_uninstall(
                canonical.value.installations[0],
                canonical.value,
                location,
                store_paths,
                adapter,
            )
            assert isinstance(uninstall, Ok)
            removed = finalize_uninstall(uninstall.value, uninstall.value.review_digest, adapter)

            self.assertIsInstance(removed, Ok)
            self.assertFalse(installed.exists())

    def test_package_era_symlink_updates_to_immutable_git_object_link(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            fixture = _fixture(root, "skill")
            project, _checkout, store_paths, location, _request, catalog, effective = fixture
            context = ConsumerContext(catalog, effective, builtin(), location, store_paths)
            target = root / "old-environment/skills/review"
            target.mkdir(parents=True)
            (target / "SKILL.md").write_text("# legacy link\n", encoding="utf-8")
            installed = project / ".claude/skills/review"
            installed.parent.mkdir(parents=True)
            installed.symlink_to(target, target_is_directory=True)
            legacy = (
                b'{"repo":"M1F1/agent-artifacts","installed":[{"artifact":"review",'
                b'"type":"skill","profile":"claude","source":"main:'
                + b"7"
                * 40
                + b'","install":{"mode":"symlink","requested_mode":"symlink","links":['
                b'{"path":".claude/skills/review","target":"'
                + str(target).encode()
                + b'","target_kind":"dir"}]},"subscription":{"kind":"package",'
                b'"location":"/old/site-packages/agent-artifacts"},'
                b'"files":{".claude/skills/review":""},'
                b'"installed_at":"2025-01-01T00:00:00Z"}]}'
            )
            paths = install_state_paths(
                "project",
                project_root=str(project),
                user_home=location.user_home,
                data_root=location.data_root,
            )
            state_path = Path(paths.legacy_path)
            state_path.parent.mkdir(parents=True)
            state_path.write_bytes(legacy)
            candidates = build_legacy_migration_candidates(
                LegacyStateMigrationRequest(legacy, "project"),
                context,
                LocalInstallAdapter(),
            )
            assert isinstance(candidates, Ok)
            migration = StateMigrationService(LocalStateStore())
            plan = migration.prepare(paths, candidates.value)
            assert isinstance(plan, Ok)
            assert isinstance(migration.apply(plan.value), Ok)
            migrated = parse_install_state(state_path.read_bytes())
            assert isinstance(migrated, Ok)

            update = prepare_update(
                migrated.value.installations[0],
                catalog,
                effective,
                builtin()["claude"],
                location,
                store_paths,
                LocalLifecycleAdapter(),
            )

            assert isinstance(update, Ok)
            self.assertIsNotNone(update.value.install_plan)
            assert update.value.install_plan is not None
            operation = update.value.install_plan.operations[0]
            self.assertIsInstance(operation, LinkOperation)
            assert isinstance(operation, LinkOperation)
            self.assertEqual(operation.semantics, "immutable-object")
            self.assertNotEqual(operation.target, str(target))


if __name__ == "__main__":
    unittest.main()
