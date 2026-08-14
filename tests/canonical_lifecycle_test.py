from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from agent_artifacts.configuration.model import SourceKind
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import ArtifactCoordinate
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.install_state.model import InstallState
from agent_artifacts.install_state.schema import install_state_bytes, parse_install_state
from agent_artifacts.installation.application import finalize_install, prepare_install
from agent_artifacts.installation.model import InstallStatus
from agent_artifacts.io.reference_store import read_references
from agent_artifacts.lifecycle import (
    LifecycleSelection,
    LifecycleStatus,
    LocalLifecycleAdapter,
    check_installations,
    finalize_uninstall,
    finalize_update,
    prepare_uninstall,
    prepare_update,
    reconcile_installations,
    status_installations,
)
from agent_artifacts.marketplace.catalog import build_marketplace
from agent_artifacts.profiles.builtin import builtin
from agent_artifacts.protocol.hashing import json_digest
from agent_artifacts.protocol.semver import SemVer
from agent_artifacts.store.model import ReferenceKind, ReferenceReadRequest
from tests.canonical_symlink_test import _fixture
from tests.marketplace_fixtures import (
    artifact,
    configured_source,
    effective_configuration,
    graph,
    missing_source_state,
    source_state,
)


def _state(project: Path) -> InstallState:
    parsed = parse_install_state((project / ".agent-artifacts/manifest.json").read_bytes())
    assert isinstance(parsed, Ok), parsed
    return parsed.value


def _install(fixture, *, mode: str | None = None, memory_mode: str | None = None):
    project, _checkout, paths, location, request, catalog, effective = fixture
    if mode is not None:
        request = replace(request, mode=mode)
    if memory_mode is not None:
        request = replace(request, memory_mode=memory_mode)
    adapter = LocalLifecycleAdapter()
    planned = prepare_install(
        request, catalog, effective, builtin()["claude"], location, paths, adapter
    )
    assert isinstance(planned, Ok), planned
    outcome = finalize_install(
        planned.value,
        planned.value.review_digest,
        catalog,
        effective,
        adapter,
    )
    assert isinstance(outcome, Ok), outcome
    assert outcome.value.status is InstallStatus.APPLIED
    return project, paths, location, request, catalog, effective, adapter


class CanonicalLifecycleTest(unittest.TestCase):
    def test_status_reports_copy_current_drift_and_missing_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, _paths, location, _request, _catalog, _effective, adapter = _install(
                _fixture(root, "skill"), mode="copy"
            )
            state = _state(project)
            selection = LifecycleSelection("project")

            current = status_installations(state, selection, location, adapter)

            assert isinstance(current, Ok), current
            self.assertEqual(current.value.selected, 1)
            self.assertEqual(current.value.items[0].status, LifecycleStatus.CURRENT)

            installed = project / ".claude/skills/review/SKILL.md"
            installed.write_text("# local edit\n")
            drifted = status_installations(state, selection, location, adapter)
            assert isinstance(drifted, Ok), drifted
            self.assertEqual(drifted.value.items[0].status, LifecycleStatus.DRIFTED)

            shutil.rmtree(installed.parent)
            missing = status_installations(state, selection, location, adapter)
            assert isinstance(missing, Ok), missing
            self.assertEqual(missing.value.items[0].status, LifecycleStatus.MISSING)

    def test_status_reports_managed_link_current_broken_retargeted_and_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, _paths, location, _request, _catalog, _effective, adapter = _install(
                _fixture(root, "skill")
            )
            state = _state(project)
            selection = LifecycleSelection("project")
            destination = project / ".claude/skills/review"
            target = destination.readlink()

            current = status_installations(state, selection, location, adapter)
            assert isinstance(current, Ok), current
            self.assertEqual(current.value.items[0].status, LifecycleStatus.CURRENT)

            target.parent.chmod(0o700)
            target.chmod(0o700)
            shutil.rmtree(target)
            broken = status_installations(state, selection, location, adapter)
            assert isinstance(broken, Ok), broken
            self.assertEqual(broken.value.items[0].status, LifecycleStatus.BROKEN)

            foreign = root / "foreign"
            foreign.mkdir()
            destination.unlink()
            destination.symlink_to(foreign, target_is_directory=True)
            retargeted = status_installations(state, selection, location, adapter)
            assert isinstance(retargeted, Ok), retargeted
            self.assertEqual(retargeted.value.items[0].status, LifecycleStatus.RETARGETED)

            destination.unlink()
            destination.write_text("replacement\n")
            replaced = status_installations(state, selection, location, adapter)
            assert isinstance(replaced, Ok), replaced
            self.assertEqual(replaced.value.items[0].status, LifecycleStatus.REPLACED)

    def test_status_and_uninstall_use_merge_identity_and_preserve_foreign_json(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, paths, location, _request, _catalog, _effective, adapter = _install(
                _fixture(root, "mcp")
            )
            state = _state(project)
            record = state.installations[0]
            effect = record.effects[0]
            self.assertIsNotNone(effect.identity_evidence)
            config_path = project / ".mcp.json"
            config = json.loads(config_path.read_text())
            config["mcpServers"]["foreign"] = {"command": "keep-me"}
            config_path.write_text(json.dumps(config))

            status = status_installations(state, LifecycleSelection("project"), location, adapter)

            assert isinstance(status, Ok), status
            self.assertEqual(status.value.items[0].status, LifecycleStatus.CURRENT)
            planned = prepare_uninstall(record, state, location, paths, adapter)
            assert isinstance(planned, Ok), planned
            removed = finalize_uninstall(planned.value, planned.value.review_digest, adapter)
            assert isinstance(removed, Ok), removed
            self.assertEqual(removed.value.status, LifecycleStatus.REMOVED)
            remaining = json.loads(config_path.read_text())
            self.assertEqual(remaining, {"mcpServers": {"foreign": {"command": "keep-me"}}})
            # The last record out of the scope takes the manifest with it (SI-7), so "no
            # installations remain" is now read from the absence of the state itself.
            self.assertFalse((project / ".agent-artifacts").exists())

    def test_check_is_fetch_free_and_compares_only_the_recorded_subscription(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, _paths, _location, _request, catalog, effective, _adapter = _install(
                _fixture(root, "skill"), mode="copy"
            )
            state = _state(project)

            current = check_installations(state, LifecycleSelection("project"), catalog, effective)

            self.assertEqual(current.items[0].status, LifecycleStatus.CURRENT)

            second = _fixture(
                root,
                "skill",
                version=SemVer(2, 0, 0),
                skill_content=b"# Installed v2\n",
                resolved_revision="b" * 40,
            )
            updated_catalog, updated_effective = second[-2:]
            available = check_installations(
                state,
                LifecycleSelection("project"),
                updated_catalog,
                updated_effective,
            )
            self.assertEqual(available.items[0].status, LifecycleStatus.UPDATE_AVAILABLE)

            direct = effective.configuration.sources[0]
            other = configured_source("other", SourceKind.SOURCE_GIT)
            other_artifact = artifact("other-source", "review", kind="skill")
            federated = effective_configuration((direct, other))
            foreign_catalog = build_marketplace(
                graph((other, "other-source", (other_artifact,))),
                federated,
                (
                    missing_source_state(direct, display_order=0),
                    source_state(other, "other-source", display_order=1),
                ),
            )
            assert isinstance(foreign_catalog, Ok), foreign_catalog

            unavailable = check_installations(
                state,
                LifecycleSelection("project"),
                foreign_catalog.value,
                federated,
            )
            self.assertEqual(unavailable.items[0].status, LifecycleStatus.SOURCE_UNAVAILABLE)

    def test_reconcile_surfaces_upstream_changes_while_retaining_local_effect_detail(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, _paths, location, _request, catalog, effective, adapter = _install(
                _fixture(root, "skill"), mode="copy"
            )
            state = _state(project)
            newer = _fixture(
                root,
                "skill",
                version=SemVer(2, 0, 0),
                skill_content=b"# Installed v2\n",
                resolved_revision="b" * 40,
            )
            updated_catalog, updated_effective = newer[-2:]

            reconciled = reconcile_installations(
                state,
                LifecycleSelection("project"),
                updated_catalog,
                updated_effective,
                location,
                adapter,
            )
            assert isinstance(reconciled, Ok), reconciled
            self.assertEqual(reconciled.value.items[0].status, LifecycleStatus.UPDATE_AVAILABLE)

            (project / ".claude/skills/review/SKILL.md").write_text("# local edit\n")
            drifted = reconcile_installations(
                state,
                LifecycleSelection("project"),
                updated_catalog,
                updated_effective,
                location,
                adapter,
            )
            assert isinstance(drifted, Ok), drifted
            self.assertEqual(drifted.value.items[0].status, LifecycleStatus.DRIFTED)
            self.assertIn("upstream", drifted.value.items[0].detail)

    def test_update_retargets_only_after_review_and_replaces_recorded_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, paths, location, _request, _catalog, _effective, adapter = _install(
                _fixture(root, "skill")
            )
            first_state = _state(project)
            old_record = first_state.installations[0]
            destination = project / ".claude/skills/review"
            old_target = destination.readlink()
            second = _fixture(
                root,
                "skill",
                version=SemVer(2, 0, 0),
                skill_content=b"# Installed v2\n",
                resolved_revision="b" * 40,
            )
            _project, _checkout, paths, location, _request, catalog, effective = second

            planned = prepare_update(
                old_record,
                catalog,
                effective,
                builtin()["claude"],
                location,
                paths,
                adapter,
            )

            assert isinstance(planned, Ok), planned
            self.assertEqual(destination.readlink(), old_target)
            updated = finalize_update(
                planned.value,
                planned.value.review_digest,
                catalog,
                effective,
                adapter,
            )
            assert isinstance(updated, Ok), updated
            self.assertEqual(updated.value.status, LifecycleStatus.CHANGED)
            self.assertNotEqual(destination.readlink(), old_target)
            self.assertEqual((destination / "SKILL.md").read_text(), "# Installed v2\n")
            self.assertEqual(_state(project).installations[0].artifact.version, SemVer(2, 0, 0))

    def test_upstream_removal_is_terminal_and_requires_prune_to_uninstall(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, paths, location, _request, _catalog, effective, adapter = _install(
                _fixture(root, "skill"), mode="copy"
            )
            state = _state(project)
            record = state.installations[0]
            source = effective.configuration.sources[0]
            empty_catalog = build_marketplace(
                graph((source, "direct-source", ())),
                effective,
                (source_state(source, "direct-source", display_order=0, content=b"empty"),),
            )
            assert isinstance(empty_catalog, Ok), empty_catalog

            retained_plan = prepare_update(
                record,
                empty_catalog.value,
                effective,
                builtin()["claude"],
                location,
                paths,
                adapter,
            )
            assert isinstance(retained_plan, Ok), retained_plan
            retained = finalize_update(
                retained_plan.value,
                retained_plan.value.review_digest,
                empty_catalog.value,
                effective,
                adapter,
            )
            assert isinstance(retained, Ok), retained
            self.assertEqual(retained.value.status, LifecycleStatus.REMOVED_UPSTREAM)
            self.assertTrue((project / ".claude/skills/review").exists())

            prune_plan = prepare_update(
                record,
                empty_catalog.value,
                effective,
                builtin()["claude"],
                location,
                paths,
                adapter,
                prune=True,
            )
            assert isinstance(prune_plan, Ok), prune_plan
            pruned = finalize_update(
                prune_plan.value,
                prune_plan.value.review_digest,
                empty_catalog.value,
                effective,
                adapter,
            )
            assert isinstance(pruned, Ok), pruned
            self.assertEqual(pruned.value.status, LifecycleStatus.REMOVED)
            self.assertFalse((project / ".claude/skills/review").exists())
            references = read_references(ReferenceReadRequest(paths))
            assert isinstance(references, Ok), references
            self.assertFalse(
                any(
                    reference.kind is ReferenceKind.INSTALLED
                    for reference in references.value.references
                )
            )

    def test_uninstall_conflict_requires_force_and_never_crosses_record_scope(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, paths, location, _request, _catalog, _effective, adapter = _install(
                _fixture(root, "skill"), mode="copy"
            )
            state = _state(project)
            record = state.installations[0]
            destination = project / ".claude/skills/review/SKILL.md"
            destination.write_text("# User content\n")

            conflicted_plan = prepare_uninstall(record, state, location, paths, adapter)
            assert isinstance(conflicted_plan, Ok), conflicted_plan
            conflicted = finalize_uninstall(
                conflicted_plan.value,
                conflicted_plan.value.review_digest,
                adapter,
            )
            assert isinstance(conflicted, Ok), conflicted
            self.assertEqual(conflicted.value.status, LifecycleStatus.CONFLICT)
            self.assertEqual(destination.read_text(), "# User content\n")
            self.assertEqual(_state(project), state)

            forced_plan = prepare_uninstall(record, state, location, paths, adapter, force=True)
            assert isinstance(forced_plan, Ok), forced_plan
            forced = finalize_uninstall(
                forced_plan.value,
                forced_plan.value.review_digest,
                adapter,
            )
            assert isinstance(forced, Ok), forced
            self.assertEqual(forced.value.status, LifecycleStatus.REMOVED)
            self.assertFalse((project / ".claude/skills/review").exists())

    def test_uninstall_state_write_failure_rolls_back_effect_and_reference(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, paths, location, _request, _catalog, _effective, adapter = _install(
                _fixture(root, "skill"), mode="copy"
            )
            state = _state(project)
            record = state.installations[0]
            planned = prepare_uninstall(record, state, location, paths, adapter)
            assert isinstance(planned, Ok), planned
            original = __import__(
                "agent_artifacts.lifecycle.io", fromlist=["_write_atomic"]
            )._write_atomic
            calls = 0

            def fail_state_once(path, content, *, mode=0o600):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise OSError("injected state failure")
                return original(path, content, mode=mode)

            with patch(
                "agent_artifacts.lifecycle.io._write_atomic",
                side_effect=fail_state_once,
            ):
                failed = finalize_uninstall(
                    planned.value,
                    planned.value.review_digest,
                    adapter,
                )

            assert isinstance(failed, Ok), failed
            self.assertEqual(failed.value.status, LifecycleStatus.FAILED)
            self.assertTrue((project / ".claude/skills/review/SKILL.md").exists())
            self.assertEqual(_state(project), state)
            references = read_references(ReferenceReadRequest(paths))
            assert isinstance(references, Ok), references
            installed = tuple(
                reference
                for reference in references.value.references
                if reference.kind is ReferenceKind.INSTALLED
            )
            self.assertEqual(len(installed), 1)

    def test_uninstall_detects_a_noop_state_write_and_rolls_back(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, paths, location, _request, _catalog, _effective, adapter = _install(
                _fixture(root, "skill"), mode="copy"
            )
            state = _state(project)
            planned = prepare_uninstall(state.installations[0], state, location, paths, adapter)
            assert isinstance(planned, Ok), planned
            module = __import__("agent_artifacts.lifecycle.io", fromlist=["_write_atomic"])
            original = module._write_atomic
            calls = 0

            def ignore_first_write(path, content, *, mode=0o600):
                nonlocal calls
                calls += 1
                if calls > 1:
                    return original(path, content, mode=mode)
                return None

            with patch(
                "agent_artifacts.lifecycle.io._write_atomic", side_effect=ignore_first_write
            ):
                outcome = finalize_uninstall(planned.value, planned.value.review_digest, adapter)

            assert isinstance(outcome, Ok), outcome
            self.assertEqual(outcome.value.status, LifecycleStatus.FAILED)
            self.assertEqual(_state(project), state)
            self.assertTrue((project / ".claude/skills/review/SKILL.md").exists())

    def test_merge_drift_conflicts_without_force_and_force_removes_only_its_identity(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, paths, location, _request, _catalog, _effective, adapter = _install(
                _fixture(root, "mcp")
            )
            state = _state(project)
            record = state.installations[0]
            config_path = project / ".mcp.json"
            config = json.loads(config_path.read_text())
            config["mcpServers"]["review"]["command"] = "locally-modified"
            config["mcpServers"]["foreign"] = {"command": "keep-me"}
            config_path.write_text(json.dumps(config))

            observed = status_installations(state, LifecycleSelection("project"), location, adapter)
            assert isinstance(observed, Ok), observed
            self.assertEqual(observed.value.items[0].status, LifecycleStatus.DRIFTED)

            conflicted_plan = prepare_uninstall(record, state, location, paths, adapter)
            assert isinstance(conflicted_plan, Ok), conflicted_plan
            conflicted = finalize_uninstall(
                conflicted_plan.value,
                conflicted_plan.value.review_digest,
                adapter,
            )
            assert isinstance(conflicted, Ok), conflicted
            self.assertEqual(conflicted.value.status, LifecycleStatus.CONFLICT)
            self.assertIn("review", json.loads(config_path.read_text())["mcpServers"])

            forced_plan = prepare_uninstall(record, state, location, paths, adapter, force=True)
            assert isinstance(forced_plan, Ok), forced_plan
            forced = finalize_uninstall(
                forced_plan.value,
                forced_plan.value.review_digest,
                adapter,
            )
            assert isinstance(forced, Ok), forced
            self.assertEqual(forced.value.status, LifecycleStatus.REMOVED)
            self.assertEqual(
                json.loads(config_path.read_text()),
                {"mcpServers": {"foreign": {"command": "keep-me"}}},
            )

    def test_update_disabled_recorded_source_is_terminal_and_does_not_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, paths, location, _request, catalog, effective, adapter = _install(
                _fixture(root, "skill"), mode="copy"
            )
            record = _state(project).installations[0]
            direct = replace(effective.configuration.sources[0], enabled=False)
            disabled = effective_configuration((direct,))

            planned = prepare_update(
                record,
                catalog,
                disabled,
                builtin()["claude"],
                location,
                paths,
                adapter,
            )
            assert isinstance(planned, Ok), planned
            outcome = finalize_update(
                planned.value,
                planned.value.review_digest,
                catalog,
                disabled,
                adapter,
            )
            assert isinstance(outcome, Ok), outcome
            self.assertEqual(outcome.value.status, LifecycleStatus.SOURCE_UNAVAILABLE)
            self.assertTrue((project / ".claude/skills/review/SKILL.md").exists())

    def test_copy_update_conflict_and_force_follow_recorded_drift_policy(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, paths, location, _request, _catalog, _effective, adapter = _install(
                _fixture(root, "skill"), mode="copy"
            )
            record = _state(project).installations[0]
            destination = project / ".claude/skills/review/SKILL.md"
            destination.write_text("# Local and upstream edit\n")
            second = _fixture(
                root,
                "skill",
                version=SemVer(2, 0, 0),
                skill_content=b"# Installed v2\n",
                resolved_revision="b" * 40,
            )
            _project, _checkout, paths, location, _request, catalog, effective = second

            conflicted_plan = prepare_update(
                record,
                catalog,
                effective,
                builtin()["claude"],
                location,
                paths,
                adapter,
            )
            assert isinstance(conflicted_plan, Ok), conflicted_plan
            conflicted = finalize_update(
                conflicted_plan.value,
                conflicted_plan.value.review_digest,
                catalog,
                effective,
                adapter,
            )
            assert isinstance(conflicted, Ok), conflicted
            self.assertEqual(conflicted.value.status, LifecycleStatus.CONFLICT)
            self.assertEqual(destination.read_text(), "# Local and upstream edit\n")

            forced_plan = prepare_update(
                record,
                catalog,
                effective,
                builtin()["claude"],
                location,
                paths,
                adapter,
                force=True,
            )
            assert isinstance(forced_plan, Ok), forced_plan
            forced = finalize_update(
                forced_plan.value,
                forced_plan.value.review_digest,
                catalog,
                effective,
                adapter,
            )
            assert isinstance(forced, Ok), forced
            self.assertEqual(forced.value.status, LifecycleStatus.CHANGED)
            self.assertEqual(destination.read_text(), "# Installed v2\n")

    def test_uninstall_revalidates_reviewed_destination_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, paths, location, _request, _catalog, _effective, adapter = _install(
                _fixture(root, "skill"), mode="copy"
            )
            state = _state(project)
            record = state.installations[0]
            planned = prepare_uninstall(record, state, location, paths, adapter)
            assert isinstance(planned, Ok), planned
            destination = project / ".claude/skills/review/SKILL.md"
            destination.write_text("# Changed after review\n")

            outcome = finalize_uninstall(
                planned.value,
                planned.value.review_digest,
                adapter,
            )

            assert isinstance(outcome, Ok), outcome
            self.assertEqual(outcome.value.status, LifecycleStatus.CONFLICT)
            self.assertEqual(destination.read_text(), "# Changed after review\n")
            self.assertEqual(_state(project), state)

    def test_mixed_hook_uninstall_requires_force_for_retarget_and_preserves_foreign_list(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, paths, location, _request, _catalog, _effective, adapter = _install(
                _fixture(root, "hook")
            )
            state = _state(project)
            record = state.installations[0]
            link = project / ".claude/hooks/review"
            foreign_target = root / "foreign-hook"
            foreign_target.mkdir()
            link.unlink()
            link.symlink_to(foreign_target, target_is_directory=True)
            settings_path = project / ".claude/settings.json"
            settings = json.loads(settings_path.read_text())
            settings["hooks"]["PreToolUse"].append(
                {"matcher": "foreign", "hooks": [{"command": "keep-me"}]}
            )
            settings_path.write_text(json.dumps(settings))

            conflicted_plan = prepare_uninstall(record, state, location, paths, adapter)
            assert isinstance(conflicted_plan, Ok), conflicted_plan
            conflicted = finalize_uninstall(
                conflicted_plan.value,
                conflicted_plan.value.review_digest,
                adapter,
            )
            assert isinstance(conflicted, Ok), conflicted
            self.assertEqual(conflicted.value.status, LifecycleStatus.CONFLICT)
            self.assertTrue(link.is_symlink())

            forced_plan = prepare_uninstall(record, state, location, paths, adapter, force=True)
            assert isinstance(forced_plan, Ok), forced_plan
            forced = finalize_uninstall(
                forced_plan.value,
                forced_plan.value.review_digest,
                adapter,
            )
            assert isinstance(forced, Ok), forced
            self.assertEqual(forced.value.status, LifecycleStatus.REMOVED)
            self.assertFalse(link.exists())
            remaining = json.loads(settings_path.read_text())
            self.assertEqual(
                remaining["hooks"]["PreToolUse"],
                [{"hooks": [{"command": "keep-me"}], "matcher": "foreign"}],
            )

    def test_project_uninstall_does_not_touch_user_scope_state_effect_or_reference(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            fixture = _fixture(root, "skill", scopes=("project", "user"))
            project, paths, location, request, catalog, effective, adapter = _install(
                fixture, mode="copy"
            )
            user_request = replace(request, scope="user", mode="copy")
            user_plan = prepare_install(
                user_request,
                catalog,
                effective,
                builtin()["claude"],
                location,
                paths,
                adapter,
            )
            assert isinstance(user_plan, Ok), user_plan
            user_install = finalize_install(
                user_plan.value,
                user_plan.value.review_digest,
                catalog,
                effective,
                adapter,
            )
            assert isinstance(user_install, Ok), user_install
            project_state = _state(project)
            user_state_path = Path(location.data_root) / "state/manifest.json"
            parsed_user = parse_install_state(user_state_path.read_bytes())
            assert isinstance(parsed_user, Ok), parsed_user
            user_destination = Path(location.user_home) / ".claude/skills/review/SKILL.md"

            planned = prepare_uninstall(
                project_state.installations[0],
                project_state,
                location,
                paths,
                adapter,
            )
            assert isinstance(planned, Ok), planned
            removed = finalize_uninstall(
                planned.value,
                planned.value.review_digest,
                adapter,
            )

            assert isinstance(removed, Ok), removed
            self.assertEqual(removed.value.status, LifecycleStatus.REMOVED)
            self.assertTrue(user_destination.exists())
            self.assertEqual(parse_install_state(user_state_path.read_bytes()), parsed_user)
            references = read_references(ReferenceReadRequest(paths))
            assert isinstance(references, Ok), references
            owners = tuple(
                reference.owner
                for reference in references.value.references
                if reference.kind is ReferenceKind.INSTALLED
            )
            self.assertEqual(owners, (user_plan.value.reference_owner,))

    def test_selection_is_exact_and_every_selected_record_has_one_terminal_item(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, _paths, location, _request, _catalog, _effective, adapter = _install(
                _fixture(root, "skill"), mode="copy"
            )
            record = _state(project).installations[0]
            other = replace(
                record,
                coordinate=ArtifactCoordinate(
                    record.coordinate.source,
                    replace(record.coordinate.artifact, name="other"),
                ),
                artifact=replace(
                    record.artifact,
                    identity=replace(record.artifact.identity, name="other"),
                ),
                profile="tabnine",
                effects=(
                    replace(
                        record.effects[0],
                        destination=".tabnine/skills/other",
                    ),
                ),
            )
            state = InstallState(2, (record, other))
            selection = LifecycleSelection(
                "project",
                coordinates=(record.coordinate,),
                profiles=("claude",),
            )

            outcome = status_installations(state, selection, location, adapter)

            assert isinstance(outcome, Ok), outcome
            self.assertEqual(outcome.value.selected, 1)
            self.assertEqual(len(outcome.value.items), 1)
            self.assertEqual(outcome.value.items[0].key.coordinate, record.coordinate)
            all_items = status_installations(
                state, LifecycleSelection("project"), location, adapter
            )
            assert isinstance(all_items, Ok), all_items
            self.assertEqual(all_items.value.selected, 2)
            self.assertEqual(len(all_items.value.items), 2)

    def test_key_merge_with_json_null_is_present_and_can_be_removed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, paths, location, _request, _catalog, _effective, adapter = _install(
                _fixture(root, "mcp")
            )
            original = _state(project).installations[0]
            record = replace(
                original,
                effects=(replace(original.effects[0], installed_digest=json_digest(None)),),
            )
            state = InstallState(2, (record,))
            state_path = project / ".agent-artifacts/manifest.json"
            state_path.write_bytes(install_state_bytes(state))
            config_path = project / ".mcp.json"
            config = json.loads(config_path.read_text())
            config["mcpServers"]["review"] = None
            config_path.write_text(json.dumps(config))

            observed = status_installations(state, LifecycleSelection("project"), location, adapter)
            assert isinstance(observed, Ok), observed
            self.assertEqual(observed.value.items[0].status, LifecycleStatus.CURRENT)
            planned = prepare_uninstall(record, state, location, paths, adapter)
            assert isinstance(planned, Ok), planned
            removed = finalize_uninstall(planned.value, planned.value.review_digest, adapter)

            assert isinstance(removed, Ok), removed
            self.assertEqual(removed.value.status, LifecycleStatus.REMOVED)
            self.assertEqual(json.loads(config_path.read_text()), {"mcpServers": {}})

    def test_install_does_not_treat_an_existing_json_null_key_as_absent(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, _checkout, paths, location, request, catalog, effective = _fixture(root, "mcp")
            (project / ".mcp.json").write_text('{"mcpServers":{"review":null}}')

            planned = prepare_install(
                request,
                catalog,
                effective,
                builtin()["claude"],
                location,
                paths,
                LocalLifecycleAdapter(),
            )

            self.assertIsInstance(planned, Err)

    def test_merge_container_type_drift_conflicts_instead_of_releasing_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, paths, location, _request, _catalog, _effective, adapter = _install(
                _fixture(root, "mcp")
            )
            state = _state(project)
            config_path = project / ".mcp.json"
            config_path.write_text('{"mcpServers":null}')

            observed = status_installations(state, LifecycleSelection("project"), location, adapter)
            assert isinstance(observed, Ok), observed
            self.assertEqual(observed.value.items[0].status, LifecycleStatus.DRIFTED)
            planned = prepare_uninstall(state.installations[0], state, location, paths, adapter)
            assert isinstance(planned, Ok), planned
            self.assertEqual(planned.value.terminal, LifecycleStatus.CONFLICT)

    def test_list_identity_drift_conflicts_and_force_preserves_unknown_entry(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, paths, location, _request, _catalog, _effective, adapter = _install(
                _fixture(root, "hook")
            )
            state = _state(project)
            record = state.installations[0]
            settings_path = project / ".claude/settings.json"
            settings = json.loads(settings_path.read_text())
            settings["hooks"]["PreToolUse"][0]["matcher"] = "locally-retargeted"
            settings_path.write_text(json.dumps(settings))

            observed = status_installations(state, LifecycleSelection("project"), location, adapter)
            assert isinstance(observed, Ok), observed
            self.assertEqual(observed.value.items[0].status, LifecycleStatus.DRIFTED)
            conflicted = prepare_uninstall(record, state, location, paths, adapter)
            assert isinstance(conflicted, Ok), conflicted
            self.assertEqual(conflicted.value.terminal, LifecycleStatus.CONFLICT)

            forced = prepare_uninstall(record, state, location, paths, adapter, force=True)
            assert isinstance(forced, Ok), forced
            outcome = finalize_uninstall(forced.value, forced.value.review_digest, adapter)

            assert isinstance(outcome, Ok), outcome
            self.assertEqual(outcome.value.status, LifecycleStatus.REMOVED)
            self.assertEqual(
                json.loads(settings_path.read_text())["hooks"]["PreToolUse"][0]["matcher"],
                "locally-retargeted",
            )

    def test_reversed_memory_markers_are_drift_not_an_exception(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, paths, location, _request, _catalog, _effective, adapter = _install(
                _fixture(root, "memory"), mode="copy", memory_mode="append"
            )
            state = _state(project)
            record = state.installations[0]
            destination = project / "CLAUDE.md"
            content = destination.read_text()
            begin = "<!-- >>> agent-artifacts memory:review >>> -->"
            end = "<!-- <<< agent-artifacts memory:review <<< -->"
            destination.write_text(
                content.replace(begin, "TOKEN").replace(end, begin).replace("TOKEN", end)
            )

            observed = status_installations(state, LifecycleSelection("project"), location, adapter)
            assert isinstance(observed, Ok), observed
            self.assertEqual(observed.value.items[0].status, LifecycleStatus.DRIFTED)
            planned = prepare_uninstall(record, state, location, paths, adapter)
            assert isinstance(planned, Ok), planned
            self.assertEqual(planned.value.terminal, LifecycleStatus.CONFLICT)

    def test_memory_update_preserves_recorded_install_mode(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, paths, location, _request, _catalog, _effective, adapter = _install(
                _fixture(root, "memory"), mode="copy", memory_mode="append"
            )
            record = _state(project).installations[0]
            self.assertEqual(record.memory_mode, "append")
            second = _fixture(
                root,
                "memory",
                version=SemVer(2, 0, 0),
                memory_content=b"Remember reviews in v2.\n",
                resolved_revision="b" * 40,
            )
            _project, _checkout, paths, location, _request, catalog, effective = second

            planned = prepare_update(
                record,
                catalog,
                effective,
                builtin()["claude"],
                location,
                paths,
                adapter,
            )

            assert isinstance(planned, Ok), planned
            assert planned.value.install_plan is not None
            self.assertEqual(planned.value.install_plan.request.memory_mode, "append")
            updated = finalize_update(
                planned.value,
                planned.value.review_digest,
                catalog,
                effective,
                adapter,
            )
            assert isinstance(updated, Ok), updated
            self.assertEqual(updated.value.status, LifecycleStatus.CHANGED)
            self.assertEqual(_state(project).installations[0].memory_mode, "append")

    def test_update_rejects_a_profile_other_than_the_recorded_profile(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, paths, location, _request, catalog, effective, adapter = _install(
                _fixture(root, "skill"), mode="copy"
            )

            planned = prepare_update(
                _state(project).installations[0],
                catalog,
                effective,
                builtin()["tabnine"],
                location,
                paths,
                adapter,
            )

            self.assertIsInstance(planned, Err)

    def test_update_rejects_changed_configured_source_location_even_with_old_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, paths, location, _request, catalog, effective, adapter = _install(
                _fixture(root, "skill"), mode="copy"
            )
            changed_source = replace(
                effective.configuration.sources[0],
                location="https://replacement.example/agents/replacement.git",
            )
            changed_effective = effective_configuration((changed_source,))

            planned = prepare_update(
                _state(project).installations[0],
                catalog,
                changed_effective,
                builtin()["claude"],
                location,
                paths,
                adapter,
            )

            assert isinstance(planned, Ok), planned
            self.assertIsNotNone(planned.value.terminal)
            assert planned.value.terminal is not None
            self.assertEqual(planned.value.terminal.status, LifecycleStatus.SOURCE_UNAVAILABLE)

    def test_status_turns_inspection_errors_into_one_terminal_result(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, _paths, location, _request, _catalog, _effective, adapter = _install(
                _fixture(root, "skill"), mode="copy"
            )
            state = _state(project)
            failure = Err(
                (
                    Diagnostic(
                        DiagnosticCode("injected-inspection-failure"),
                        Severity.ERROR,
                        "injected inspection failure",
                    ),
                )
            )

            with patch.object(adapter, "inspect_path", return_value=failure):
                outcome = status_installations(
                    state, LifecycleSelection("project"), location, adapter
                )

            assert isinstance(outcome, Ok), outcome
            self.assertEqual(outcome.value.selected, 1)
            self.assertEqual(outcome.value.items[0].status, LifecycleStatus.FAILED)

    def test_uninstall_detects_noop_destination_mutations_and_rolls_back(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, paths, location, _request, _catalog, _effective, adapter = _install(
                _fixture(root, "skill"), mode="copy"
            )
            state = _state(project)
            planned = prepare_uninstall(state.installations[0], state, location, paths, adapter)
            assert isinstance(planned, Ok), planned
            module = __import__("agent_artifacts.lifecycle.io", fromlist=["_remove"])
            original = module._remove
            calls = 0

            def ignore_first_remove(path):
                nonlocal calls
                calls += 1
                if calls > 1:
                    return original(path)
                return None

            with patch("agent_artifacts.lifecycle.io._remove", side_effect=ignore_first_remove):
                outcome = finalize_uninstall(planned.value, planned.value.review_digest, adapter)

            assert isinstance(outcome, Ok), outcome
            self.assertEqual(outcome.value.status, LifecycleStatus.FAILED)
            self.assertEqual(_state(project), state)
            self.assertTrue((project / ".claude/skills/review/SKILL.md").exists())

    def test_uninstall_detects_noop_content_write_and_rolls_back(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, paths, location, _request, _catalog, _effective, adapter = _install(
                _fixture(root, "mcp")
            )
            state = _state(project)
            config_path = project / ".mcp.json"
            config = json.loads(config_path.read_text())
            config["mcpServers"]["foreign"] = {"command": "keep"}
            config_path.write_text(json.dumps(config))
            planned = prepare_uninstall(state.installations[0], state, location, paths, adapter)
            assert isinstance(planned, Ok), planned
            module = __import__("agent_artifacts.lifecycle.io", fromlist=["_write_atomic"])
            original = module._write_atomic
            calls = 0

            def ignore_first_write(path, content, *, mode=0o600):
                nonlocal calls
                calls += 1
                if calls > 1:
                    return original(path, content, mode=mode)
                return None

            with patch(
                "agent_artifacts.lifecycle.io._write_atomic", side_effect=ignore_first_write
            ):
                outcome = finalize_uninstall(planned.value, planned.value.review_digest, adapter)

            assert isinstance(outcome, Ok), outcome
            self.assertEqual(outcome.value.status, LifecycleStatus.FAILED)
            self.assertEqual(_state(project), state)
            self.assertIn("review", json.loads(config_path.read_text())["mcpServers"])

    def test_uninstall_reference_failure_rolls_back_effect_and_state(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, paths, location, _request, _catalog, _effective, adapter = _install(
                _fixture(root, "skill"), mode="copy"
            )
            state = _state(project)
            planned = prepare_uninstall(state.installations[0], state, location, paths, adapter)
            assert isinstance(planned, Ok), planned
            failure = Err(
                (
                    Diagnostic(
                        DiagnosticCode("injected-reference-failure"),
                        Severity.ERROR,
                        "injected reference failure",
                    ),
                )
            )

            with patch(
                "agent_artifacts.lifecycle.io._replace_installed_reference",
                return_value=failure,
            ):
                outcome = finalize_uninstall(planned.value, planned.value.review_digest, adapter)

            assert isinstance(outcome, Ok), outcome
            self.assertEqual(outcome.value.status, LifecycleStatus.FAILED)
            self.assertEqual(_state(project), state)
            self.assertTrue((project / ".claude/skills/review/SKILL.md").exists())
            references = read_references(ReferenceReadRequest(paths))
            assert isinstance(references, Ok), references
            self.assertTrue(
                any(
                    reference.kind is ReferenceKind.INSTALLED
                    for reference in references.value.references
                )
            )

    def test_uninstall_verifies_reference_release_reached_durable_state(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, paths, location, _request, _catalog, _effective, adapter = _install(
                _fixture(root, "skill"), mode="copy"
            )
            state = _state(project)
            planned = prepare_uninstall(state.installations[0], state, location, paths, adapter)
            assert isinstance(planned, Ok), planned

            with patch(
                "agent_artifacts.lifecycle.io._replace_installed_reference",
                return_value=Ok(planned.value.reference_replacement),
            ):
                outcome = finalize_uninstall(planned.value, planned.value.review_digest, adapter)

            assert isinstance(outcome, Ok), outcome
            self.assertEqual(outcome.value.status, LifecycleStatus.FAILED)
            self.assertEqual(_state(project), state)
            self.assertTrue((project / ".claude/skills/review/SKILL.md").exists())

    def test_uninstall_plan_rejects_an_operation_outside_record_scope(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, paths, location, _request, _catalog, _effective, adapter = _install(
                _fixture(root, "skill"), mode="copy"
            )
            state = _state(project)
            planned = prepare_uninstall(state.installations[0], state, location, paths, adapter)
            assert isinstance(planned, Ok), planned
            operation = planned.value.operations[0]
            outside = str(root / "outside")
            forged = replace(
                operation,
                absolute_destination=outside,
                precondition=replace(operation.precondition, path=outside),
            )

            with self.assertRaisesRegex(ValueError, "exactly bound"):
                replace(planned.value, operations=(forged,))


if __name__ == "__main__":
    unittest.main()
