from __future__ import annotations

import posixpath
import unittest
from dataclasses import replace

from agent_artifacts.configuration.model import OrganizationPolicy, SourceKind
from agent_artifacts.domain.identifiers import ArtifactIdentity, ObjectDigest, SourceAlias
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.installation.application import InstallReadPorts, prepare_install
from agent_artifacts.installation.model import (
    CopyTreeOperation,
    InstallLocation,
    InstallRequest,
    MergeJsonOperation,
    PathSnapshot,
    WriteFileOperation,
)
from agent_artifacts.marketplace.catalog import build_marketplace
from agent_artifacts.profiles.builtin import builtin
from agent_artifacts.protocol.hashing import file_entry, json_digest, tree_digest
from agent_artifacts.protocol.json import canonical_json_bytes
from agent_artifacts.protocol.native_models import (
    PAYLOAD_FORMAT_BY_TYPE,
    ArtifactManifest,
    CompatibilitySpec,
    ImporterProvenance,
    InstallSpec,
    OriginProvenance,
    PayloadSpec,
    Provenance,
)
from agent_artifacts.protocol.native_schema import (
    artifact_manifest_to_json,
    parse_artifact_manifest,
    provenance_to_json,
)
from agent_artifacts.protocol.native_tree import SnapshotEntry, SnapshotEntryKind
from agent_artifacts.protocol.paths import parse_relative_path
from agent_artifacts.protocol.semver import SemVer
from agent_artifacts.store.model import StoredObject, make_object_candidate, object_store_paths
from tests.marketplace_fixtures import (
    artifact,
    configured_source,
    effective_configuration,
    graph,
    provenance,
    source_state,
)


def _path(raw: str):
    parsed = parse_relative_path(raw)
    assert isinstance(parsed, Ok)
    return parsed.value


def _candidate(kind: str, *, artifact_provenance: Provenance | None = None):
    primary = {
        "skill": ("payload/SKILL.md", b"# Review\n"),
        "guideline": ("payload/review.md", b"Review carefully.\n"),
        "mcp": (
            "payload/mcp.json",
            b'{"name":"review","server":{"command":"review-mcp"}}\n',
        ),
        "memory": ("payload/review.md", b"Remember reviews.\n"),
    }[kind]
    effects = {
        "skill": ("copy-tree",),
        "guideline": ("write-file",),
        "mcp": ("merge-json",),
        "memory": ("managed-block",),
    }[kind]
    manifest = ArtifactManifest(
        1,
        ArtifactIdentity(kind, "review"),  # type: ignore[arg-type]
        SemVer(1, 0, 0),
        "Use review to improve agent work.",
        PayloadSpec(_path("payload"), PAYLOAD_FORMAT_BY_TYPE[kind]),  # type: ignore[index]
        CompatibilitySpec(("claude",), ("darwin",)),
        InstallSpec(("project", "user"), ("copy",), effects),  # type: ignore[arg-type]
    )
    entries = [
        SnapshotEntry(
            _path("artifact.json"),
            SnapshotEntryKind.FILE,
            canonical_json_bytes(artifact_manifest_to_json(manifest)),
        ),
        SnapshotEntry(_path(primary[0]), SnapshotEntryKind.FILE, primary[1]),
    ]
    if artifact_provenance is not None:
        entries.append(
            SnapshotEntry(
                _path("provenance.json"),
                SnapshotEntryKind.FILE,
                canonical_json_bytes(provenance_to_json(artifact_provenance)),
            )
        )
    result = make_object_candidate(tuple(entries))
    assert isinstance(result, Ok)
    return result.value


def _evidence(candidate):
    manifest_entry = next(
        entry for entry in candidate.entries if str(entry.path) == "artifact.json"
    )
    manifest = parse_artifact_manifest(manifest_entry.content)
    assert isinstance(manifest, Ok)
    payload_entries = []
    for entry in candidate.entries:
        raw = str(entry.path)
        if entry.kind is SnapshotEntryKind.FILE and raw.startswith("payload/"):
            payload_entries.append(
                file_entry(
                    _path(raw.removeprefix("payload/")),
                    entry.content,
                    executable=entry.executable,
                )
            )
    payload = tree_digest(payload_entries)
    assert isinstance(payload, Ok)
    return json_digest(artifact_manifest_to_json(manifest.value)), payload.value


def _catalog(kind: str, candidate, *, second: bool = False, now: int = 100):
    effects = {
        "skill": ("copy-tree",),
        "guideline": ("write-file",),
        "mcp": ("merge-json",),
        "memory": ("managed-block",),
    }[kind]
    direct = configured_source("direct", SourceKind.SOURCE_GIT)
    manifest_digest, payload_digest = _evidence(candidate)
    indexed = replace(
        artifact("direct-source", "review", kind=kind),
        manifest_digest=manifest_digest,
        payload_digest=payload_digest,
        object_digest=candidate.digest,
        compatibility=CompatibilitySpec(("claude",), ("darwin",)),
        install=InstallSpec(("project", "user"), ("copy",), effects),
    )
    definitions = [(direct, "direct-source", (indexed,))]
    states = [source_state(direct, "direct-source", display_order=0, now=now)]
    sources = [direct]
    if second:
        other = configured_source("other", SourceKind.SOURCE_GIT)
        other_index = replace(indexed, source_id=artifact("other-source", "review").source_id)
        definitions.append((other, "other-source", (other_index,)))
        states.append(source_state(other, "other-source", display_order=1, now=now))
        sources.append(other)
    effective = effective_configuration(tuple(sources))
    built = build_marketplace(graph(*definitions), effective, tuple(states))
    assert isinstance(built, Ok)
    return built.value, effective


class _MemoryReads(InstallReadPorts):
    def __init__(self, stored: StoredObject | None) -> None:
        self.stored = stored

    def read_object(self, request):
        if self.stored is None or self.stored.candidate.digest != request.digest:
            return Ok(None)
        return Ok(self.stored)

    def read_state(self, path: str):
        return Ok(None)

    def inspect_path(self, path: str):
        return Ok(PathSnapshot.absent(path))


class CanonicalInstallPlanningTest(unittest.TestCase):
    def setUp(self) -> None:
        self.location = InstallLocation("/project", "/users/alice", "/data/aart")

    def _prepare(
        self,
        kind: str,
        *,
        source: str | None = None,
        policy=None,
        offline: bool = False,
        scope: str = "project",
        now: int = 100,
    ):
        candidate = _candidate(kind)
        catalog, effective = _catalog(kind, candidate, second=source is not None, now=now)
        if policy is not None:
            effective = replace(effective, policy=policy)
        request = InstallRequest(
            ArtifactIdentity(kind, "review"),  # type: ignore[arg-type]
            source=None if source is None else SourceAlias(source),
            profile="claude",
            platform="darwin",
            scope=scope,  # type: ignore[arg-type]
            offline=offline,
        )
        reads = _MemoryReads(
            StoredObject(
                candidate,
                f"/data/aart/objects/sha256/{candidate.digest.value[:2]}/"
                f"{candidate.digest.value[2:]}",
            )
        )
        return prepare_install(
            request,
            catalog,
            effective,
            builtin()["claude"],
            self.location,
            object_store_paths("/data/aart"),
            reads,
        )

    def test_copy_is_default_and_qualified_resolution_is_exact(self) -> None:
        result = self._prepare("skill", source="other", offline=True)

        self.assertIsInstance(result, Ok)
        assert isinstance(result, Ok)
        self.assertEqual(result.value.coordinate.source, SourceAlias("other"))
        self.assertEqual(result.value.request.mode, "copy")
        self.assertTrue(result.value.request.offline)
        self.assertEqual(result.value.source.resolved_commit, "a" * 40)
        self.assertEqual(result.value.source_health, "healthy")
        self.assertIsNotNone(result.value.source_snapshot_digest)
        self.assertEqual(result.value.artifact.object_digest, result.value.object_digest)
        self.assertEqual(len(result.value.operations), 1)
        operation = result.value.operations[0]
        self.assertIsInstance(operation, CopyTreeOperation)
        assert isinstance(operation, CopyTreeOperation)
        self.assertEqual(operation.destination, ".claude/skills/review")
        self.assertEqual(operation.absolute_destination, "/project/.claude/skills/review")
        self.assertEqual(operation.source_path, "payload")

    def test_review_digest_describes_the_plan_not_the_moment(self) -> None:
        # published_at is 90 and the freshness threshold is 30, so these three readings of one
        # unchanged workspace span the healthy/stale boundary: ages 10, 25 and 40 seconds.
        plans = []
        for now in (100, 115, 130):
            result = self._prepare("skill", source="other", offline=True, now=now)
            self.assertIsInstance(result, Ok)
            assert isinstance(result, Ok)
            plans.append(result.value)

        self.assertEqual([plan.source_age_seconds for plan in plans], [10, 25, 40])
        self.assertEqual([plan.source_health for plan in plans], ["healthy", "healthy", "stale"])
        self.assertEqual(len({str(plan.review_digest) for plan in plans}), 1)

    def test_unqualified_collision_and_missing_cached_object_fail_closed(self) -> None:
        candidate = _candidate("skill")
        catalog, effective = _catalog("skill", candidate, second=True)
        ambiguous = prepare_install(
            InstallRequest(ArtifactIdentity("skill", "review"), profile="claude"),
            catalog,
            effective,
            builtin()["claude"],
            self.location,
            object_store_paths("/data/aart"),
            _MemoryReads(
                StoredObject(
                    candidate,
                    f"/data/aart/objects/sha256/{candidate.digest.value[:2]}/"
                    f"{candidate.digest.value[2:]}",
                )
            ),
        )
        unavailable = prepare_install(
            InstallRequest(
                ArtifactIdentity("skill", "review"),
                source=SourceAlias("direct"),
                profile="claude",
                offline=True,
            ),
            catalog,
            effective,
            builtin()["claude"],
            self.location,
            object_store_paths("/data/aart"),
            _MemoryReads(None),
        )

        self.assertIsInstance(ambiguous, Err)
        self.assertIsInstance(unavailable, Err)
        assert isinstance(unavailable, Err)
        self.assertEqual(unavailable.diagnostics[0].code.value, "install-object-unavailable")
        self.assertIn("offline", unavailable.diagnostics[0].message)

        symlink = prepare_install(
            InstallRequest(
                ArtifactIdentity("skill", "review"),
                source=SourceAlias("direct"),
                profile="claude",
                mode="symlink",
            ),
            catalog,
            effective,
            builtin()["claude"],
            self.location,
            object_store_paths("/data/aart"),
            _MemoryReads(None),
        )
        assert isinstance(symlink, Err)
        self.assertEqual(symlink.diagnostics[0].code.value, "artifact-incompatible")

    def test_user_scope_minimum_trust_and_compatibility_are_enforced(self) -> None:
        candidate = _candidate("skill")
        catalog, effective = _catalog("skill", candidate)
        reads = _MemoryReads(
            StoredObject(
                candidate,
                f"/data/aart/objects/sha256/{candidate.digest.value[:2]}/"
                f"{candidate.digest.value[2:]}",
            )
        )
        denied_policy = OrganizationPolicy(
            1,
            minimum_trust_for_user_scope="company-reviewed",
        )
        denied = prepare_install(
            InstallRequest(
                ArtifactIdentity("skill", "review"),
                source=SourceAlias("direct"),
                profile="claude",
                platform="darwin",
                scope="user",
            ),
            catalog,
            replace(effective, policy=denied_policy),
            builtin()["claude"],
            self.location,
            object_store_paths("/data/aart"),
            reads,
        )
        incompatible = prepare_install(
            InstallRequest(
                ArtifactIdentity("skill", "review"),
                source=SourceAlias("direct"),
                profile="claude",
                platform="linux",
            ),
            catalog,
            effective,
            builtin()["claude"],
            self.location,
            object_store_paths("/data/aart"),
            reads,
        )

        self.assertIsInstance(denied, Err)
        self.assertIsInstance(incompatible, Err)
        assert isinstance(denied, Err)
        assert isinstance(incompatible, Err)
        self.assertEqual(denied.diagnostics[0].code.value, "install-policy-denied")
        self.assertEqual(incompatible.diagnostics[0].code.value, "artifact-incompatible")

        allowed = self._prepare(
            "skill",
            scope="user",
            policy=OrganizationPolicy(1, minimum_trust_for_user_scope="direct-source"),
        )
        assert isinstance(allowed, Ok), allowed
        operation = allowed.value.operations[0]
        self.assertEqual(operation.destination, "/users/alice/.claude/skills/review")
        self.assertEqual(operation.absolute_destination, operation.destination)
        self.assertEqual(allowed.value.state_path, "/data/aart/state/manifest.json")

    def test_file_tree_and_merge_actions_are_projected_from_canonical_payloads(self) -> None:
        guideline = self._prepare("guideline")
        mcp = self._prepare("mcp")
        memory = self._prepare("memory")

        self.assertIsInstance(guideline, Ok)
        self.assertIsInstance(mcp, Ok)
        self.assertIsInstance(memory, Ok)
        assert isinstance(guideline, Ok)
        assert isinstance(mcp, Ok)
        assert isinstance(memory, Ok)
        self.assertIsInstance(guideline.value.operations[0], WriteFileOperation)
        self.assertIsInstance(mcp.value.operations[0], MergeJsonOperation)
        self.assertIsInstance(memory.value.operations[0], WriteFileOperation)
        write = guideline.value.operations[0]
        merge = mcp.value.operations[0]
        memory_write = memory.value.operations[0]
        assert isinstance(write, WriteFileOperation)
        assert isinstance(merge, MergeJsonOperation)
        assert isinstance(memory_write, WriteFileOperation)
        self.assertEqual(write.destination, ".claude/guidelines/review.md")
        self.assertEqual(write.content, b"Review carefully.\n")
        self.assertEqual(merge.destination, ".mcp.json")
        self.assertEqual(merge.json_path, "mcpServers")
        self.assertEqual(merge.identity, ("review",))
        self.assertIn(b'"review"', merge.content)
        self.assertEqual(memory_write.destination, "CLAUDE.md")
        self.assertEqual(memory_write.effect_kind, "managed-block")

    def test_review_digest_binds_operation_and_state_preconditions(self) -> None:
        planned = self._prepare("skill")
        assert isinstance(planned, Ok)

        with self.assertRaises(ValueError):
            replace(
                planned.value,
                state_path=posixpath.join("/data/aart", "state", "other.json"),
            )
        with self.assertRaises(ValueError):
            replace(planned.value, object_root="/data/aart/objects/sha256/forged")
        with self.assertRaises(ValueError):
            replace(
                planned.value.operations[0],
                absolute_destination="/project/other",
            )

    def test_local_source_and_registry_provenance_are_review_bound(self) -> None:
        indexed_provenance = provenance("review")
        evidence_digest = ObjectDigest("sha256", "c" * 64)
        native_provenance = Provenance(
            1,
            OriginProvenance(
                "git",
                indexed_provenance.origin_url,
                indexed_provenance.resolved_commit,
                indexed_provenance.path,
                evidence_digest,
            ),
            ImporterProvenance("test-importer", SemVer(1, 0, 0), evidence_digest),
            (),
        )
        candidate = _candidate("skill", artifact_provenance=native_provenance)
        local = configured_source("local", SourceKind.SOURCE_LOCAL)
        manifest_digest, payload_digest = _evidence(candidate)
        indexed = replace(
            artifact(
                "local-source",
                "review",
                provenance=indexed_provenance,
            ),
            manifest_digest=manifest_digest,
            payload_digest=payload_digest,
            object_digest=candidate.digest,
            compatibility=CompatibilitySpec(("claude",), ("darwin",)),
            install=InstallSpec(("project", "user"), ("copy",), ("copy-tree",)),
        )
        effective = effective_configuration((local,))
        catalog = build_marketplace(
            graph((local, "local-source", (indexed,))),
            effective,
            (source_state(local, "local-source", display_order=0),),
        )
        assert isinstance(catalog, Ok)
        root = (
            f"/data/aart/objects/sha256/{candidate.digest.value[:2]}/{candidate.digest.value[2:]}"
        )

        planned = prepare_install(
            InstallRequest(
                ArtifactIdentity("skill", "review"),
                source=SourceAlias("local"),
                profile="claude",
            ),
            catalog.value,
            effective,
            builtin()["claude"],
            self.location,
            object_store_paths("/data/aart"),
            _MemoryReads(StoredObject(candidate, root)),
        )

        assert isinstance(planned, Ok), planned
        self.assertEqual(planned.value.source.resolved_commit, "local")
        self.assertEqual(planned.value.source.origin, "/work/local")
        self.assertIsNone(planned.value.source.subscription_ref)
        self.assertIsNotNone(planned.value.provenance)
        assert planned.value.provenance is not None
        self.assertEqual(planned.value.provenance.origin_url, "upstream.example/review")
        self.assertEqual(planned.value.provenance.resolved_commit, "b" * 40)
        self.assertEqual(planned.value.object_root, root)

    def test_object_bytes_must_match_indexed_manifest_and_payload_evidence(self) -> None:
        candidate = _candidate("skill")
        manifest_digest, payload_digest = _evidence(candidate)
        source = configured_source("direct", SourceKind.SOURCE_GIT)
        root = (
            f"/data/aart/objects/sha256/{candidate.digest.value[:2]}/{candidate.digest.value[2:]}"
        )
        mismatches = (
            (ObjectDigest("sha256", "f" * 64), payload_digest),
            (manifest_digest, ObjectDigest("sha256", "e" * 64)),
        )
        for bad_manifest, bad_payload in mismatches:
            with self.subTest(manifest=bad_manifest, payload=bad_payload):
                indexed = replace(
                    artifact("direct-source", "review"),
                    manifest_digest=bad_manifest,
                    payload_digest=bad_payload,
                    object_digest=candidate.digest,
                    compatibility=CompatibilitySpec(("claude",), ("darwin",)),
                    install=InstallSpec(
                        ("project", "user"),
                        ("copy",),
                        ("copy-tree",),
                    ),
                )
                effective = effective_configuration((source,))
                catalog = build_marketplace(
                    graph((source, "direct-source", (indexed,))),
                    effective,
                    (source_state(source, "direct-source", display_order=0),),
                )
                assert isinstance(catalog, Ok)

                planned = prepare_install(
                    InstallRequest(
                        ArtifactIdentity("skill", "review"),
                        source=SourceAlias("direct"),
                        profile="claude",
                    ),
                    catalog.value,
                    effective,
                    builtin()["claude"],
                    self.location,
                    object_store_paths("/data/aart"),
                    _MemoryReads(StoredObject(candidate, root)),
                )

                assert isinstance(planned, Err)
                self.assertEqual(
                    planned.diagnostics[0].code.value,
                    "install-object-evidence-invalid",
                )


if __name__ == "__main__":
    unittest.main()
