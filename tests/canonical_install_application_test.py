from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from agent_artifacts.configuration.model import OrganizationPolicy, SourceKind
from agent_artifacts.domain.identifiers import ArtifactIdentity, SourceAlias
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.install_state.schema import parse_install_state
from agent_artifacts.installation.application import finalize_install, prepare_install
from agent_artifacts.installation.io import LocalInstallAdapter
from agent_artifacts.installation.model import InstallLocation, InstallRequest, InstallStatus
from agent_artifacts.io.object_store import publish_object
from agent_artifacts.io.reference_store import read_references
from agent_artifacts.marketplace.catalog import build_marketplace
from agent_artifacts.profiles.builtin import builtin
from agent_artifacts.protocol.hashing import file_entry, json_digest, tree_digest
from agent_artifacts.protocol.json import canonical_json_bytes
from agent_artifacts.protocol.native_models import (
    PAYLOAD_FORMAT_BY_TYPE,
    ArtifactManifest,
    CompatibilitySpec,
    InstallSpec,
    PayloadSpec,
)
from agent_artifacts.protocol.native_schema import artifact_manifest_to_json
from agent_artifacts.protocol.native_tree import SnapshotEntry, SnapshotEntryKind
from agent_artifacts.protocol.paths import parse_relative_path
from agent_artifacts.protocol.semver import SemVer, VersionBounds
from agent_artifacts.runtime_contract import EXECUTABLE_VERSION
from agent_artifacts.store.model import (
    ObjectPublishCommand,
    ReferenceKind,
    ReferenceReadRequest,
    make_object_candidate,
    object_store_paths,
)
from tests.marketplace_fixtures import (
    artifact,
    configured_source,
    effective_configuration,
    graph,
    source_state,
)


def _path(raw: str):
    parsed = parse_relative_path(raw)
    assert isinstance(parsed, Ok)
    return parsed.value


def _fixture(
    root: Path,
    kind: str,
    *,
    requires_aart: VersionBounds | None = None,
):
    payloads = {
        "skill": (("payload/SKILL.md", b"# Installed\n", False),),
        "hook": (
            (
                "payload/hook.json",
                b'{"name":"review","command":"${SCRIPT_DIR}/run.sh","matcher":"*"}\n',
                False,
            ),
            ("payload/run.sh", b"#!/bin/sh\n", True),
        ),
        "mcp": (
            (
                "payload/mcp.json",
                b'{"name":"review","server":{"command":"review-mcp"}}\n',
                False,
            ),
        ),
    }
    effects = {
        "skill": ("copy-tree",),
        "hook": ("copy-tree", "merge-json"),
        "mcp": ("merge-json",),
    }[kind]
    manifest = ArtifactManifest(
        1,
        ArtifactIdentity(kind, "review"),  # type: ignore[arg-type]
        SemVer(1, 0, 0),
        "Use review to improve agent work.",
        PayloadSpec(_path("payload"), PAYLOAD_FORMAT_BY_TYPE[kind]),  # type: ignore[index]
        CompatibilitySpec(("claude",), ("darwin",)),
        InstallSpec(("project",), ("copy",), effects),  # type: ignore[arg-type]
        requires_aart=VersionBounds() if requires_aart is None else requires_aart,
    )
    candidate_result = make_object_candidate(
        (
            SnapshotEntry(
                _path("artifact.json"),
                SnapshotEntryKind.FILE,
                canonical_json_bytes(artifact_manifest_to_json(manifest)),
            ),
            *(
                SnapshotEntry(_path(path), SnapshotEntryKind.FILE, content, executable)
                for path, content, executable in payloads[kind]
            ),
        )
    )
    assert isinstance(candidate_result, Ok)
    candidate = candidate_result.value
    payload = tree_digest(
        tuple(
            file_entry(
                _path(path.removeprefix("payload/")),
                content,
                executable=executable,
            )
            for path, content, executable in payloads[kind]
        )
    )
    assert isinstance(payload, Ok)
    source = configured_source("direct", SourceKind.SOURCE_GIT)
    indexed = replace(
        artifact(
            "direct-source",
            "review",
            kind=kind,
            requires_aart=requires_aart,
        ),
        manifest_digest=json_digest(artifact_manifest_to_json(manifest)),
        payload_digest=payload.value,
        object_digest=candidate.digest,
        compatibility=CompatibilitySpec(("claude",), ("darwin",)),
        install=InstallSpec(("project",), ("copy",), effects),
    )
    effective = effective_configuration((source,))
    catalog_result = build_marketplace(
        graph((source, "direct-source", (indexed,))),
        effective,
        (source_state(source, "direct-source", display_order=0),),
    )
    assert isinstance(catalog_result, Ok)
    project = root / "project"
    home = root / "home"
    data = root / "data"
    project.mkdir()
    home.mkdir()
    paths = object_store_paths(str(data))
    published = publish_object(ObjectPublishCommand(paths, candidate))
    assert isinstance(published, Ok), published
    location = InstallLocation(str(project), str(home), str(data))
    request = InstallRequest(
        ArtifactIdentity(kind, "review"),  # type: ignore[arg-type]
        source=SourceAlias("direct"),
        profile="claude",
        platform="darwin",
    )
    return project, paths, location, request, catalog_result.value, effective


class CanonicalInstallApplicationTest(unittest.TestCase):
    def test_prepare_rejects_only_a_selected_artifact_that_needs_a_newer_aart(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project, paths, location, request, catalog, effective = _fixture(
                Path(raw),
                "skill",
                requires_aart=VersionBounds(
                    min_inclusive=SemVer(EXECUTABLE_VERSION.major + 1, 0, 0)
                ),
            )

            planned = prepare_install(
                request,
                catalog,
                effective,
                builtin()["claude"],
                location,
                paths,
                LocalInstallAdapter(),
            )

            self.assertIsInstance(planned, Err)
            assert isinstance(planned, Err)
            self.assertEqual(planned.diagnostics[0].code.value, "artifact-incompatible")
            self.assertIn(
                f"requires AART >={EXECUTABLE_VERSION.major + 1}.0.0",
                planned.diagnostics[0].message,
            )
            self.assertIn("may not support behavior", planned.diagnostics[0].message)
            self.assertIn("installation is disabled", planned.diagnostics[0].message)
            self.assertFalse((project / ".claude/skills/review").exists())

    def test_finalize_applies_reviewed_copy_and_pins_manifest_v2_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project, paths, location, request, catalog, effective = _fixture(Path(raw), "skill")
            adapter = LocalInstallAdapter()
            planned = prepare_install(
                request,
                catalog,
                effective,
                builtin()["claude"],
                location,
                paths,
                adapter,
            )
            assert isinstance(planned, Ok), planned

            outcome = finalize_install(
                planned.value,
                planned.value.review_digest,
                catalog,
                effective,
                adapter,
            )

            self.assertIsInstance(outcome, Ok)
            assert isinstance(outcome, Ok)
            self.assertEqual(outcome.value.status, InstallStatus.APPLIED)
            self.assertEqual(outcome.value.changed, 1)
            self.assertEqual(
                (project / ".claude/skills/review/SKILL.md").read_text(),
                "# Installed\n",
            )
            state_path = project / ".agent-artifacts/manifest.json"
            state = parse_install_state(state_path.read_bytes(), path=str(state_path))
            assert isinstance(state, Ok), state
            record = state.value.installations[0]
            self.assertEqual(record.coordinate.source, SourceAlias("direct"))
            self.assertEqual(record.source.resolved_commit, "a" * 40)
            self.assertEqual(record.artifact.object_digest, planned.value.object_digest)
            self.assertEqual(record.effects[0].actual_mode, "copy")
            references = read_references(ReferenceReadRequest(paths))
            assert isinstance(references, Ok), references
            self.assertTrue(
                any(
                    reference.kind is ReferenceKind.INSTALLED
                    and reference.digest == planned.value.object_digest
                    for reference in references.value.references
                )
            )

            second = prepare_install(
                request,
                catalog,
                effective,
                builtin()["claude"],
                location,
                paths,
                adapter,
            )
            assert isinstance(second, Ok), second
            current = finalize_install(
                second.value,
                second.value.review_digest,
                catalog,
                effective,
                adapter,
            )
            assert isinstance(current, Ok), current
            self.assertEqual(current.value.status, InstallStatus.CURRENT)
            self.assertEqual(current.value.changed, 0)

    def test_finalize_rejects_stale_review_without_overwriting_new_content(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project, paths, location, request, catalog, effective = _fixture(Path(raw), "skill")
            adapter = LocalInstallAdapter()
            planned = prepare_install(
                request,
                catalog,
                effective,
                builtin()["claude"],
                location,
                paths,
                adapter,
            )
            assert isinstance(planned, Ok), planned
            destination = project / ".claude/skills/review"
            destination.mkdir(parents=True)
            (destination / "foreign.txt").write_text("new after review\n")

            outcome = finalize_install(
                planned.value,
                planned.value.review_digest,
                catalog,
                effective,
                adapter,
            )

            assert isinstance(outcome, Ok), outcome
            self.assertEqual(outcome.value.status, InstallStatus.CONFLICTED)
            self.assertEqual(outcome.value.changed, 0)
            self.assertEqual((destination / "foreign.txt").read_text(), "new after review\n")
            self.assertFalse((project / ".agent-artifacts/manifest.json").exists())

    def test_finalize_rejects_organization_policy_change_after_review(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project, paths, location, request, catalog, effective = _fixture(Path(raw), "skill")
            adapter = LocalInstallAdapter()
            planned = prepare_install(
                request,
                catalog,
                effective,
                builtin()["claude"],
                location,
                paths,
                adapter,
            )
            assert isinstance(planned, Ok), planned
            changed_policy = replace(
                effective,
                policy=OrganizationPolicy(
                    1,
                    minimum_trust_for_user_scope="direct-source",
                ),
            )

            outcome = finalize_install(
                planned.value,
                planned.value.review_digest,
                catalog,
                changed_policy,
                adapter,
            )

            assert isinstance(outcome, Ok), outcome
            self.assertEqual(outcome.value.status, InstallStatus.CONFLICTED)
            self.assertFalse((project / ".claude/skills/review").exists())

    def test_drift_conflicts_without_force_and_force_replaces_it(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project, paths, location, request, catalog, effective = _fixture(Path(raw), "skill")
            destination = project / ".claude/skills/review"
            destination.mkdir(parents=True)
            (destination / "SKILL.md").write_text("user content\n")
            adapter = LocalInstallAdapter()

            conflict = prepare_install(
                request,
                catalog,
                effective,
                builtin()["claude"],
                location,
                paths,
                adapter,
            )
            forced = prepare_install(
                replace(request, force=True),
                catalog,
                effective,
                builtin()["claude"],
                location,
                paths,
                adapter,
            )

            self.assertNotIsInstance(conflict, Ok)
            assert isinstance(forced, Ok), forced
            outcome = finalize_install(
                forced.value,
                forced.value.review_digest,
                catalog,
                effective,
                adapter,
            )
            assert isinstance(outcome, Ok), outcome
            self.assertEqual(outcome.value.status, InstallStatus.APPLIED)
            self.assertEqual((destination / "SKILL.md").read_text(), "# Installed\n")

    def test_partial_effect_failure_rolls_back_payload_and_does_not_write_state(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project, paths, location, request, catalog, effective = _fixture(Path(raw), "hook")
            settings = project / ".claude/settings.json"
            settings.parent.mkdir(parents=True)
            original_settings = b'{"foreign":true}\n'
            settings.write_bytes(original_settings)
            adapter = LocalInstallAdapter()
            planned = prepare_install(
                request,
                catalog,
                effective,
                builtin()["claude"],
                location,
                paths,
                adapter,
            )
            assert isinstance(planned, Ok), planned
            original = __import__(
                "agent_artifacts.installation.io",
                fromlist=["_write_atomic"],
            )._write_atomic
            calls = 0

            def fail_first_write(path, content, *, mode=0o600):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise OSError("injected merge failure")
                return original(path, content, mode=mode)

            with patch(
                "agent_artifacts.installation.io._write_atomic",
                side_effect=fail_first_write,
            ):
                outcome = finalize_install(
                    planned.value,
                    planned.value.review_digest,
                    catalog,
                    effective,
                    adapter,
                )

            assert isinstance(outcome, Ok), outcome
            self.assertEqual(outcome.value.status, InstallStatus.FAILED)
            self.assertTrue(any(item.status == "rolled-back" for item in outcome.value.effects))
            self.assertFalse((project / ".claude/hooks/review").exists())
            self.assertEqual(settings.read_bytes(), original_settings)
            self.assertFalse((project / ".agent-artifacts/manifest.json").exists())

    def test_merge_preserves_foreign_configuration_and_becomes_a_no_op(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project, paths, location, request, catalog, effective = _fixture(Path(raw), "mcp")
            config = project / ".mcp.json"
            config.write_text('{"foreign":{"command":"keep"}}\n')
            adapter = LocalInstallAdapter()
            planned = prepare_install(
                request,
                catalog,
                effective,
                builtin()["claude"],
                location,
                paths,
                adapter,
            )
            assert isinstance(planned, Ok), planned

            first = finalize_install(
                planned.value,
                planned.value.review_digest,
                catalog,
                effective,
                adapter,
            )
            assert isinstance(first, Ok), first
            self.assertEqual(first.value.status, InstallStatus.APPLIED)
            document = __import__("json").loads(config.read_text())
            self.assertEqual(document["foreign"], {"command": "keep"})
            self.assertEqual(document["mcpServers"]["review"]["command"], "review-mcp")

            again = prepare_install(
                request,
                catalog,
                effective,
                builtin()["claude"],
                location,
                paths,
                adapter,
            )
            assert isinstance(again, Ok), again
            current = finalize_install(
                again.value,
                again.value.review_digest,
                catalog,
                effective,
                adapter,
            )
            assert isinstance(current, Ok), current
            self.assertEqual(current.value.status, InstallStatus.CURRENT)

    def test_hook_merge_rejects_identity_collision_unless_force_is_reviewed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project, paths, location, request, catalog, effective = _fixture(Path(raw), "hook")
            settings = project / ".claude/settings.json"
            settings.parent.mkdir(parents=True)
            command = ".claude/hooks/review/run.sh"
            settings.write_text(
                '{"hooks":{"PreToolUse":['
                f'{{"matcher":"*","hooks":[{{"type":"prompt","command":"{command}"}}]}}'
                ']},"foreign":true}\n'
            )
            adapter = LocalInstallAdapter()

            conflicted = prepare_install(
                request,
                catalog,
                effective,
                builtin()["claude"],
                location,
                paths,
                adapter,
            )

            self.assertIsInstance(conflicted, Err)
            forced = prepare_install(
                replace(request, force=True),
                catalog,
                effective,
                builtin()["claude"],
                location,
                paths,
                adapter,
            )
            assert isinstance(forced, Ok), forced
            merge = forced.value.operations[1]
            document = __import__("json").loads(merge.content)
            entries = document["hooks"]["PreToolUse"]
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["hooks"][0]["type"], "command")
            self.assertTrue(document["foreign"])

    def test_state_write_failure_rolls_back_copy_and_releases_transaction_reference(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project, paths, location, request, catalog, effective = _fixture(Path(raw), "skill")
            adapter = LocalInstallAdapter()
            planned = prepare_install(
                request,
                catalog,
                effective,
                builtin()["claude"],
                location,
                paths,
                adapter,
            )
            assert isinstance(planned, Ok), planned
            original = __import__(
                "agent_artifacts.installation.io",
                fromlist=["_write_atomic"],
            )._write_atomic

            def fail_state(path, content, *, mode=0o600):
                if str(path) == planned.value.state_path:
                    raise OSError("injected state failure")
                return original(path, content, mode=mode)

            with patch(
                "agent_artifacts.installation.io._write_atomic",
                side_effect=fail_state,
            ):
                outcome = finalize_install(
                    planned.value,
                    planned.value.review_digest,
                    catalog,
                    effective,
                    adapter,
                )

            assert isinstance(outcome, Ok), outcome
            self.assertEqual(outcome.value.status, InstallStatus.FAILED)
            self.assertEqual(outcome.value.effects[0].status, "rolled-back")
            self.assertFalse((project / ".claude/skills/review").exists())
            self.assertFalse(Path(planned.value.state_path).exists())
            references = read_references(ReferenceReadRequest(paths))
            assert isinstance(references, Ok), references
            self.assertFalse(
                any(
                    reference.kind in {ReferenceKind.INSTALLED, ReferenceKind.TRANSACTION}
                    for reference in references.value.references
                )
            )

    def test_existing_symlink_destination_is_rejected_even_with_force(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project, paths, location, request, catalog, effective = _fixture(Path(raw), "skill")
            outside = Path(raw) / "outside"
            outside.mkdir()
            destination = project / ".claude/skills/review"
            destination.parent.mkdir(parents=True)
            destination.symlink_to(outside, target_is_directory=True)

            planned = prepare_install(
                replace(request, force=True),
                catalog,
                effective,
                builtin()["claude"],
                location,
                paths,
                LocalInstallAdapter(),
            )

            assert isinstance(planned, Err)
            self.assertEqual(planned.diagnostics[0].code.value, "install-conflict")
            self.assertEqual(tuple(outside.iterdir()), ())


if __name__ == "__main__":
    unittest.main()
