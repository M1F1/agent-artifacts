from __future__ import annotations

import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from agent_artifacts.configuration.model import SourceKind
from agent_artifacts.domain.identifiers import ArtifactIdentity, SourceAlias
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.install_state.schema import parse_install_state
from agent_artifacts.installation.application import finalize_install, prepare_install
from agent_artifacts.installation.io import LocalInstallAdapter
from agent_artifacts.installation.model import (
    InstallLocation,
    InstallRequest,
    InstallStatus,
    LinkOperation,
    LinkStatus,
    MergeJsonOperation,
    PathSnapshot,
    classify_link,
)
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
from agent_artifacts.protocol.semver import SemVer
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

_V1 = SemVer(1, 0, 0)


def _path(raw: str):
    parsed = parse_relative_path(raw)
    assert isinstance(parsed, Ok)
    return parsed.value


def _fixture(
    root: Path,
    kind: str,
    *,
    version: SemVer = _V1,
    skill_content: bytes = b"# Installed v1\n",
    memory_content: bytes = b"Remember reviews.\n",
    source_kind: SourceKind = SourceKind.SOURCE_GIT,
    resolved_revision: str = "a" * 40,
    scopes: tuple[str, ...] = ("project",),
):
    payloads = {
        "skill": (("payload/SKILL.md", skill_content, False),),
        "guideline": (("payload/review.md", b"Review carefully.\n", False),),
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
        "memory": (("payload/review.md", memory_content, False),),
    }
    effects = {
        "skill": ("copy-tree",),
        "guideline": ("write-file",),
        "hook": ("copy-tree", "merge-json"),
        "mcp": ("merge-json",),
        "memory": ("managed-block",),
    }[kind]
    manifest = ArtifactManifest(
        1,
        ArtifactIdentity(kind, "review"),  # type: ignore[arg-type]
        version,
        "Use review to improve agent work.",
        PayloadSpec(_path("payload"), PAYLOAD_FORMAT_BY_TYPE[kind]),  # type: ignore[index]
        CompatibilitySpec(("claude",), ("darwin",)),
        InstallSpec(scopes, ("copy", "symlink"), effects),  # type: ignore[arg-type]
    )
    entries = (
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
    candidate_result = make_object_candidate(entries)
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
    checkout = root / "checkout"
    checkout.mkdir(exist_ok=True)
    source = configured_source(
        "direct",
        source_kind,
        location=str(checkout) if source_kind is SourceKind.SOURCE_LOCAL else None,
    )
    indexed = replace(
        artifact("direct-source", "review", kind=kind),
        version=version,
        manifest_digest=json_digest(artifact_manifest_to_json(manifest)),
        payload_digest=payload.value,
        object_digest=candidate.digest,
        compatibility=CompatibilitySpec(("claude",), ("darwin",)),
        install=InstallSpec(scopes, ("copy", "symlink"), effects),  # type: ignore[arg-type]
    )
    effective = effective_configuration((source,))
    catalog_result = build_marketplace(
        graph((source, "direct-source", (indexed,))),
        effective,
        (
            source_state(
                source,
                "direct-source",
                display_order=0,
                content=f"source-{version}".encode(),
                resolved_revision=resolved_revision,
            ),
        ),
    )
    assert isinstance(catalog_result, Ok)
    project = root / "project"
    home = root / "home"
    data = root / "data"
    project.mkdir(exist_ok=True)
    home.mkdir(exist_ok=True)
    paths = object_store_paths(str(data))
    published = publish_object(ObjectPublishCommand(paths, candidate))
    assert isinstance(published, Ok), published
    location = InstallLocation(str(project), str(home), str(data))
    request = InstallRequest(
        ArtifactIdentity(kind, "review"),  # type: ignore[arg-type]
        source=SourceAlias("direct"),
        profile="claude",
        platform="darwin",
        mode="symlink",
    )
    return project, checkout, paths, location, request, catalog_result.value, effective


class CanonicalSymlinkTest(unittest.TestCase):
    def test_managed_tree_link_targets_exact_cas_and_survives_environment_removal(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, _checkout, paths, location, request, catalog, effective = _fixture(
                root, "skill"
            )
            environment = root / "python-environment"
            environment.mkdir()
            adapter = LocalInstallAdapter()

            planned = prepare_install(
                request, catalog, effective, builtin()["claude"], location, paths, adapter
            )

            assert isinstance(planned, Ok), planned
            operation = planned.value.operations[0]
            self.assertIsInstance(operation, LinkOperation)
            assert isinstance(operation, LinkOperation)
            self.assertEqual(operation.target, f"{planned.value.object_root}/payload")
            self.assertEqual(operation.semantics, "immutable-object")
            self.assertFalse(operation.target.startswith(str(environment)))
            outcome = finalize_install(
                planned.value,
                planned.value.review_digest,
                catalog,
                effective,
                adapter,
            )
            assert isinstance(outcome, Ok), outcome
            destination = project / ".claude/skills/review"
            self.assertEqual(outcome.value.status, InstallStatus.APPLIED)
            self.assertTrue(destination.is_symlink())
            self.assertEqual(destination.readlink(), Path(operation.target))

            shutil.rmtree(environment)

            self.assertEqual((destination / "SKILL.md").read_text(), "# Installed v1\n")
            state = parse_install_state((project / ".agent-artifacts/manifest.json").read_bytes())
            assert isinstance(state, Ok), state
            effect = state.value.installations[0].effects[0]
            self.assertEqual(effect.actual_mode, "symlink")
            self.assertEqual(effect.link_target, operation.target)
            self.assertEqual(effect.link_semantics, "immutable-object")

    def test_file_links_and_merge_only_fallback_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            guideline = _fixture(root, "guideline")
            project, _checkout, paths, location, request, catalog, effective = guideline
            adapter = LocalInstallAdapter()
            linked = prepare_install(
                request, catalog, effective, builtin()["claude"], location, paths, adapter
            )
            assert isinstance(linked, Ok), linked
            self.assertIsInstance(linked.value.operations[0], LinkOperation)
            file_link = linked.value.operations[0]
            assert isinstance(file_link, LinkOperation)
            self.assertEqual(file_link.target_kind, "file")
            self.assertTrue(file_link.target.endswith("/payload/review.md"))

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            mcp = _fixture(root, "mcp")
            _project, _checkout, paths, location, request, catalog, effective = mcp
            copied = prepare_install(
                request,
                catalog,
                effective,
                builtin()["claude"],
                location,
                paths,
                LocalInstallAdapter(),
            )
            assert isinstance(copied, Ok), copied
            self.assertEqual(len(copied.value.operations), 1)
            self.assertIsInstance(copied.value.operations[0], MergeJsonOperation)
            effect = copied.value.replacement_state.installations[0].effects[0]
            self.assertEqual(effect.actual_mode, "copy")
            self.assertEqual(copied.value.request.mode, "symlink")

    def test_hook_has_linked_payload_and_copied_merge(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, _checkout, paths, location, request, catalog, effective = _fixture(
                root, "hook"
            )
            adapter = LocalInstallAdapter()
            planned = prepare_install(
                request, catalog, effective, builtin()["claude"], location, paths, adapter
            )
            assert isinstance(planned, Ok), planned
            self.assertIsInstance(planned.value.operations[0], LinkOperation)
            self.assertIsInstance(planned.value.operations[1], MergeJsonOperation)

            outcome = finalize_install(
                planned.value,
                planned.value.review_digest,
                catalog,
                effective,
                adapter,
            )

            assert isinstance(outcome, Ok), outcome
            self.assertEqual(outcome.value.changed, 2)
            self.assertTrue((project / ".claude/hooks/review").is_symlink())
            self.assertFalse((project / ".claude/settings.json").is_symlink())
            record = planned.value.replacement_state.installations[0]
            self.assertEqual(
                tuple(effect.actual_mode for effect in record.effects), ("symlink", "copy")
            )

    def test_sync_does_not_retarget_until_explicit_reviewed_finalize(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            first = _fixture(root, "skill")
            project, _checkout, paths, location, request, catalog, effective = first
            adapter = LocalInstallAdapter()
            planned = prepare_install(
                request, catalog, effective, builtin()["claude"], location, paths, adapter
            )
            assert isinstance(planned, Ok), planned
            applied = finalize_install(
                planned.value,
                planned.value.review_digest,
                catalog,
                effective,
                adapter,
            )
            assert isinstance(applied, Ok), applied
            destination = project / ".claude/skills/review"
            old_target = destination.readlink()

            second = _fixture(
                root,
                "skill",
                version=SemVer(2, 0, 0),
                skill_content=b"# Installed v2\n",
                resolved_revision="b" * 40,
            )
            _project, _checkout, paths, location, request, catalog, effective = second

            self.assertEqual(destination.readlink(), old_target)
            self.assertEqual((destination / "SKILL.md").read_text(), "# Installed v1\n")
            before_update = read_references(ReferenceReadRequest(paths))
            assert isinstance(before_update, Ok), before_update
            self.assertTrue(
                any(
                    item.kind is ReferenceKind.INSTALLED
                    and item.owner == planned.value.reference_owner
                    and item.digest == planned.value.object_digest
                    for item in before_update.value.references
                )
            )
            retarget = prepare_install(
                request, catalog, effective, builtin()["claude"], location, paths, adapter
            )
            assert isinstance(retarget, Ok), retarget
            operation = retarget.value.operations[0]
            assert isinstance(operation, LinkOperation)
            self.assertNotEqual(Path(operation.target), old_target)
            self.assertEqual(destination.readlink(), old_target)

            updated = finalize_install(
                retarget.value,
                retarget.value.review_digest,
                catalog,
                effective,
                adapter,
            )

            assert isinstance(updated, Ok), updated
            self.assertEqual(updated.value.status, InstallStatus.APPLIED)
            self.assertEqual(destination.readlink(), Path(operation.target))
            self.assertEqual((destination / "SKILL.md").read_text(), "# Installed v2\n")
            references = read_references(ReferenceReadRequest(paths))
            assert isinstance(references, Ok), references
            installed = tuple(
                item.digest
                for item in references.value.references
                if item.kind is ReferenceKind.INSTALLED
                and item.owner == retarget.value.reference_owner
            )
            self.assertEqual(installed, (retarget.value.object_digest,))

    def test_link_status_distinguishes_broken_retargeted_and_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, _checkout, paths, location, request, catalog, effective = _fixture(
                root, "skill"
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
            assert isinstance(planned, Ok), planned
            operation = planned.value.operations[0]
            assert isinstance(operation, LinkOperation)
            effect = planned.value.replacement_state.installations[0].effects[0]
            destination = str(project / ".claude/skills/review")

            self.assertEqual(
                classify_link(
                    effect,
                    PathSnapshot.symlink(destination, operation.target, target_exists=True),
                ),
                LinkStatus.CURRENT,
            )
            self.assertEqual(
                classify_link(
                    effect,
                    PathSnapshot.symlink(destination, operation.target, target_exists=False),
                ),
                LinkStatus.BROKEN,
            )
            self.assertEqual(
                classify_link(
                    effect,
                    PathSnapshot.symlink(destination, "/other/target", target_exists=True),
                ),
                LinkStatus.RETARGETED,
            )
            self.assertEqual(
                classify_link(effect, PathSnapshot.file(destination, b"replacement")),
                LinkStatus.REPLACED,
            )

    def test_mutable_local_link_is_explicit_local_only_and_reflects_checkout_edits(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            local = _fixture(root, "skill", source_kind=SourceKind.SOURCE_LOCAL)
            project, checkout, paths, location, request, catalog, effective = local
            payload = checkout / "payload"
            payload.mkdir()
            (payload / "SKILL.md").write_bytes(b"# Installed v1\n")
            request = replace(request, mutable_local_payload_root=str(payload))
            adapter = LocalInstallAdapter()

            planned = prepare_install(
                request, catalog, effective, builtin()["claude"], location, paths, adapter
            )
            assert isinstance(planned, Ok), planned
            operation = planned.value.operations[0]
            assert isinstance(operation, LinkOperation)
            self.assertEqual(operation.semantics, "mutable-local")
            self.assertEqual(operation.target, str(payload))
            applied = finalize_install(
                planned.value,
                planned.value.review_digest,
                catalog,
                effective,
                adapter,
            )
            assert isinstance(applied, Ok), applied
            destination = project / ".claude/skills/review"

            (payload / "SKILL.md").write_text("# Live edit\n")

            self.assertEqual((destination / "SKILL.md").read_text(), "# Live edit\n")
            effect = planned.value.replacement_state.installations[0].effects[0]
            observed = adapter.inspect_path(str(destination))
            assert isinstance(observed, Ok), observed
            self.assertEqual(classify_link(effect, observed.value), LinkStatus.MUTABLE_LOCAL)

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            remote = _fixture(root, "skill")
            _project, checkout, paths, location, request, catalog, effective = remote
            rejected = prepare_install(
                replace(request, mutable_local_payload_root=str(checkout)),
                catalog,
                effective,
                builtin()["claude"],
                location,
                paths,
                LocalInstallAdapter(),
            )
            self.assertIsInstance(rejected, Err)

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            local = _fixture(root, "skill", source_kind=SourceKind.SOURCE_LOCAL)
            _project, checkout, paths, location, request, catalog, effective = local
            outside = root / "outside-payload"
            outside.mkdir()
            (outside / "SKILL.md").write_bytes(b"# Installed v1\n")
            payload = checkout / "payload"
            payload.symlink_to(outside, target_is_directory=True)

            escaped = prepare_install(
                replace(request, mutable_local_payload_root=str(payload)),
                catalog,
                effective,
                builtin()["claude"],
                location,
                paths,
                LocalInstallAdapter(),
            )

            self.assertIsInstance(escaped, Err)

    def test_failed_retarget_restores_old_link_and_old_installed_reference(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            first = _fixture(root, "skill")
            project, _checkout, paths, location, request, catalog, effective = first
            adapter = LocalInstallAdapter()
            planned = prepare_install(
                request, catalog, effective, builtin()["claude"], location, paths, adapter
            )
            assert isinstance(planned, Ok), planned
            applied = finalize_install(
                planned.value,
                planned.value.review_digest,
                catalog,
                effective,
                adapter,
            )
            assert isinstance(applied, Ok), applied
            destination = project / ".claude/skills/review"
            old_target = destination.readlink()

            second = _fixture(
                root,
                "skill",
                version=SemVer(2, 0, 0),
                skill_content=b"# Installed v2\n",
                resolved_revision="b" * 40,
            )
            _project, _checkout, paths, location, request, catalog, effective = second
            retarget = prepare_install(
                request, catalog, effective, builtin()["claude"], location, paths, adapter
            )
            assert isinstance(retarget, Ok), retarget
            original = __import__(
                "agent_artifacts.installation.io", fromlist=["_write_atomic"]
            )._write_atomic
            calls = 0

            def fail_state_once(path, content, *, mode=0o600):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise OSError("injected state failure")
                return original(path, content, mode=mode)

            with patch(
                "agent_artifacts.installation.io._write_atomic",
                side_effect=fail_state_once,
            ):
                failed = finalize_install(
                    retarget.value,
                    retarget.value.review_digest,
                    catalog,
                    effective,
                    adapter,
                )

            assert isinstance(failed, Ok), failed
            self.assertEqual(failed.value.status, InstallStatus.FAILED)
            self.assertEqual(destination.readlink(), old_target)
            self.assertEqual((destination / "SKILL.md").read_text(), "# Installed v1\n")
            references = read_references(ReferenceReadRequest(paths))
            assert isinstance(references, Ok), references
            installed = tuple(
                item.digest
                for item in references.value.references
                if item.kind is ReferenceKind.INSTALLED
                and item.owner == planned.value.reference_owner
            )
            self.assertEqual(installed, (planned.value.object_digest,))

    def test_retargeted_foreign_link_requires_explicit_force(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, _checkout, paths, location, request, catalog, effective = _fixture(
                root, "skill"
            )
            adapter = LocalInstallAdapter()
            planned = prepare_install(
                request, catalog, effective, builtin()["claude"], location, paths, adapter
            )
            assert isinstance(planned, Ok), planned
            applied = finalize_install(
                planned.value,
                planned.value.review_digest,
                catalog,
                effective,
                adapter,
            )
            assert isinstance(applied, Ok), applied

            destination = project / ".claude/skills/review"
            foreign = root / "foreign"
            foreign.mkdir()
            (foreign / "SKILL.md").write_text("# Foreign\n")
            destination.unlink()
            destination.symlink_to(foreign, target_is_directory=True)

            rejected = prepare_install(
                request, catalog, effective, builtin()["claude"], location, paths, adapter
            )
            self.assertIsInstance(rejected, Err)
            assert isinstance(rejected, Err)
            self.assertEqual(rejected.diagnostics[0].code.value, "install-conflict")

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
            restored = finalize_install(
                forced.value,
                forced.value.review_digest,
                catalog,
                effective,
                adapter,
            )
            assert isinstance(restored, Ok), restored
            operation = forced.value.operations[0]
            assert isinstance(operation, LinkOperation)
            self.assertEqual(destination.readlink(), Path(operation.target))

    def test_wrong_link_written_by_adapter_fails_postcondition_and_rolls_back(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, _checkout, paths, location, request, catalog, effective = _fixture(
                root, "skill"
            )
            adapter = LocalInstallAdapter()
            planned = prepare_install(
                request, catalog, effective, builtin()["claude"], location, paths, adapter
            )
            assert isinstance(planned, Ok), planned
            original = __import__(
                "agent_artifacts.installation.io", fromlist=["_write_symlink"]
            )._write_symlink
            wrong = root / "wrong-target"
            wrong.mkdir()
            calls = 0

            def write_wrong_once(path, target):
                nonlocal calls
                calls += 1
                return original(path, str(wrong) if calls == 1 else target)

            with patch(
                "agent_artifacts.installation.io._write_symlink",
                side_effect=write_wrong_once,
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
            self.assertFalse((project / ".claude/skills/review").exists())
            self.assertFalse((project / ".agent-artifacts/manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
