from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from agent_artifacts.compiler.graph import compile_marketplace_graph
from agent_artifacts.configuration.model import SourceKind
from agent_artifacts.configuration.paths import Platform, resolve_config_paths
from agent_artifacts.configuration.schema import user_configuration_bytes
from agent_artifacts.consumer import ConsumerActionRequest
from agent_artifacts.consumer.runtime import (
    _CAPABILITIES,
    _graph_source,
    _registry_security_evidence,
    load_local_consumer_service,
)
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import SourceId
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.io.source_store import publish_source_snapshot
from agent_artifacts.marketplace.catalog import build_marketplace
from agent_artifacts.marketplace.model import MarketplaceSourceState
from agent_artifacts.protocol.capabilities import Capability
from agent_artifacts.protocol.hashing import json_digest
from agent_artifacts.protocol.json import JsonObject
from agent_artifacts.protocol.native_tree import SnapshotOrigin, SourceSnapshot
from agent_artifacts.protocol.paths import parse_relative_path
from agent_artifacts.protocol.registry_schema import parse_registry_index
from agent_artifacts.protocol.semver import SemVer
from agent_artifacts.registry_maintenance.model import NativeReferenceAcquisition
from agent_artifacts.registry_maintenance.planning import (
    plan_native_promotion,
    project_registry_mutation,
)
from agent_artifacts.security.attestation_schema import attestation_bytes, security_index_bytes
from agent_artifacts.security.attestations import (
    AssessmentCacheKey,
    AttestationOrigin,
    AttestationOriginKind,
    AttestationTrust,
    SecurityAttestation,
    SecurityIndex,
    SecurityIndexEntry,
    attestation_digest,
)
from agent_artifacts.security.baseline import BASELINE_RULES_DIGEST, not_scanned_assessment
from agent_artifacts.sources.model import (
    CurrentSource,
    SourcePublishCommand,
    ValidatedSourceCandidate,
    assess_source_health,
    make_source_candidate,
    source_instance_id,
    source_store_paths,
)
from agent_artifacts.store.model import make_object_candidate, object_store_paths
from agent_artifacts.tui_marketplace import MarketplaceTarget
from tests.marketplace_fixtures import configured_source, effective_configuration
from tests.registry_fixture_test import _snapshot as registry_snapshot
from tests.registry_maintenance_fixtures import (
    append_snapshot_file,
    empty_registry_snapshot,
    native_snapshot,
    registry_entry,
    renamed_native_snapshot,
    replace_snapshot_file,
    snapshot_file,
    without_snapshot_paths,
)


def _current(source, source_id: str, snapshot) -> CurrentSource:
    candidate = make_source_candidate(
        source_instance_id(source),
        source.alias,
        "a" * 40,
        snapshot,
    )
    assert isinstance(candidate, Ok), candidate
    return CurrentSource(candidate.value, SourceId(source_id), 90, "/managed/source")


def _promoted_registry_snapshot(*, include_owned: bool = True):
    base = empty_registry_snapshot()
    initial = (
        SourceSnapshot(
            base.origin,
            (
                *base.entries,
                *(
                    item
                    for item in renamed_native_snapshot("owned").entries
                    if str(item.path).startswith("artifacts/")
                ),
            ),
        )
        if include_owned
        else base
    )
    planned = plan_native_promotion(
        initial,
        registry_entry(),
        NativeReferenceAcquisition(
            "https://github.com/example/reference-skills.git",
            "main",
            "a" * 40,
            native_snapshot(),
        ),
        executable_version=SemVer(1, 0, 0),
        available_capabilities=(Capability("artifact-manifest-v1"),),
    )
    assert isinstance(planned, Ok), planned
    projected = project_registry_mutation(initial, planned.value)
    assert isinstance(projected, Ok), projected
    normalized = make_object_candidate(projected.value.entries)
    assert isinstance(normalized, Ok), normalized
    return SourceSnapshot(SnapshotOrigin.IMMUTABLE_GIT, normalized.value.entries)


class ConsumerRuntimeTest(unittest.TestCase):
    def test_reference_only_registry_is_a_valid_marketplace_source(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = configured_source("company", SourceKind.REGISTRY_GIT)
            projected = _graph_source(
                source,
                _current(source, "test-registry", _promoted_registry_snapshot(include_owned=False)),
                object_store_paths(str(Path(raw) / "data")),
            )

            assert isinstance(projected, Ok), projected
            self.assertEqual(
                tuple(str(item.identity) for item in projected.value.artifacts),
                ("skill/code-review",),
            )

    def test_registry_reference_is_fetched_by_locked_commit_only_for_selected_content(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            home = root / "home"
            project = root / "project"
            home.mkdir()
            project.mkdir()
            xdg = {
                "XDG_CONFIG_HOME": str(home / ".config"),
                "XDG_DATA_HOME": str(home / ".local/share"),
                "XDG_CACHE_HOME": str(home / ".cache"),
            }
            platform = Platform.DARWIN if sys.platform == "darwin" else Platform.LINUX
            config_paths = resolve_config_paths(
                platform,
                home=str(home),
                xdg_config_home=xdg["XDG_CONFIG_HOME"],
                xdg_data_home=xdg["XDG_DATA_HOME"],
                xdg_cache_home=xdg["XDG_CACHE_HOME"],
            )
            source = configured_source("company", SourceKind.REGISTRY_GIT)
            configuration = effective_configuration(
                (source,), default_registry="company"
            ).configuration
            config_file = Path(config_paths.user_config_file)
            config_file.parent.mkdir(parents=True)
            config_file.write_bytes(user_configuration_bytes(configuration))
            candidate = make_source_candidate(
                source_instance_id(source),
                source.alias,
                "b" * 40,
                _promoted_registry_snapshot(),
            )
            assert isinstance(candidate, Ok), candidate
            published = publish_source_snapshot(
                SourcePublishCommand(
                    source_store_paths(config_paths.data_root, source_instance_id(source)),
                    ValidatedSourceCandidate(candidate.value, SourceId("test-registry")),
                    90,
                )
            )
            assert isinstance(published, Ok), published

            acquired_requests = []

            def acquire(request):
                acquired_requests.append(request)
                if len(acquired_requests) == 1:
                    return Err(
                        (
                            Diagnostic(
                                DiagnosticCode("source-unavailable"),
                                Severity.ERROR,
                                "synthetic acquisition failure",
                            ),
                        )
                    )
                return make_source_candidate(
                    request.instance_id,
                    request.alias,
                    "a" * 40,
                    native_snapshot(),
                )

            with (
                mock.patch.dict(os.environ, xdg, clear=False),
                mock.patch(
                    "agent_artifacts.consumer.runtime.acquire_git_snapshot",
                    side_effect=acquire,
                ),
            ):
                loaded = load_local_consumer_service(
                    project=str(project),
                    user_home=str(home),
                )
                assert isinstance(loaded, Ok), loaded
                self.assertEqual(acquired_requests, [])
                self.assertEqual(
                    len(loaded.value.context.catalog.items),
                    2,
                    loaded.value.context.catalog,
                )
                coordinate = next(
                    item.coordinate
                    for item in loaded.value.context.catalog.items
                    if item.coordinate.artifact.name == "code-review"
                )
                offline = loaded.value.prepare(
                    ConsumerActionRequest(
                        "install",
                        (coordinate,),
                        ("claude",),
                        offline=True,
                    )
                )
                self.assertNotIsInstance(offline, Ok)
                assert isinstance(offline, Err), offline
                self.assertEqual(offline.diagnostics[0].code.value, "offline-object-missing")
                self.assertEqual(acquired_requests, [])

                unavailable = loaded.value.prepare(
                    ConsumerActionRequest("install", (coordinate,), ("claude",))
                )
                assert isinstance(unavailable, Err), unavailable
                self.assertEqual(unavailable.diagnostics[0].code.value, "source-unavailable")
                self.assertEqual(len(acquired_requests), 1)

                reviewed = loaded.value.prepare(
                    ConsumerActionRequest("install", (coordinate,), ("claude",))
                )
                assert isinstance(reviewed, Ok), reviewed
                self.assertEqual(len(acquired_requests), 2)
                self.assertEqual(acquired_requests[1].ref, "a" * 40)
                self.assertEqual(
                    acquired_requests[1].location,
                    "https://github.com/example/reference-skills.git",
                )
                cached = loaded.value.prepare(
                    ConsumerActionRequest("install", (coordinate,), ("claude",))
                )
                self.assertIsInstance(cached, Ok)
                self.assertEqual(len(acquired_requests), 2)
                self.assertIsInstance(
                    loaded.value.ensure_content(ConsumerActionRequest("status", (), ("claude",))),
                    Ok,
                )
                self.assertIsInstance(
                    loaded.value.ensure_content(
                        ConsumerActionRequest("update", (coordinate,), ("claude",))
                    ),
                    Ok,
                )
                self.assertEqual(len(acquired_requests), 2)

    def test_invalid_native_or_registry_snapshots_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            paths = object_store_paths(str(Path(raw) / "data"))
            direct = configured_source("team", SourceKind.SOURCE_GIT)
            empty = SourceSnapshot(native_snapshot().origin, ())
            invalid_native = _graph_source(
                direct,
                _current(direct, "reference-native-source", empty),
                paths,
            )
            registry = configured_source("company", SourceKind.REGISTRY_GIT)
            missing_index = _graph_source(
                registry,
                _current(registry, "reference-native-source", native_snapshot()),
                paths,
            )
            malformed_snapshot = append_snapshot_file(
                native_snapshot(),
                "aart.index.json",
                b"{}\n",
            )
            malformed_index = _graph_source(
                registry,
                _current(registry, "reference-native-source", malformed_snapshot),
                paths,
            )

            self.assertNotIsInstance(invalid_native, Ok)
            self.assertNotIsInstance(missing_index, Ok)
            self.assertNotIsInstance(malformed_index, Ok)

    def test_registry_runtime_rejects_missing_or_stale_lock_index_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            paths = object_store_paths(str(Path(raw) / "data"))
            source = configured_source("company", SourceKind.REGISTRY_GIT)
            snapshot = _promoted_registry_snapshot(include_owned=False)
            missing_lock = _graph_source(
                source,
                _current(
                    source,
                    "test-registry",
                    without_snapshot_paths(snapshot, "aart.lock.json"),
                ),
                paths,
            )
            stale_index_document = json.loads(snapshot_file(snapshot, "aart.index.json"))
            stale_index_document["registry_inputs_digest"] = f"sha256:{'0' * 64}"
            stale_index = replace_snapshot_file(
                snapshot,
                "aart.index.json",
                json.dumps(stale_index_document).encode(),
            )
            stale = _graph_source(
                source,
                _current(source, "test-registry", stale_index),
                paths,
            )
            mismatched_identity = _graph_source(
                source,
                _current(source, "other-registry", snapshot),
                paths,
            )
            disagreeing_document = json.loads(snapshot_file(snapshot, "aart.index.json"))
            disagreeing_document["artifacts"][0]["object_digest"] = f"sha256:{'f' * 64}"
            disagreeing_index = replace_snapshot_file(
                snapshot,
                "aart.index.json",
                json.dumps(disagreeing_document).encode(),
            )
            disagreement = _graph_source(
                source,
                _current(source, "test-registry", disagreeing_index),
                paths,
            )

            for result in (missing_lock, stale, mismatched_identity, disagreement):
                self.assertNotIsInstance(result, Ok)

    def test_local_composition_loads_persisted_and_reviewed_prospective_configuration(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            home = root / "home"
            project = root / "project"
            home.mkdir()
            project.mkdir()
            xdg = {
                "XDG_CONFIG_HOME": str(home / ".config"),
                "XDG_DATA_HOME": str(home / ".local/share"),
                "XDG_CACHE_HOME": str(home / ".cache"),
            }
            platform = Platform.DARWIN if sys.platform == "darwin" else Platform.LINUX
            config_paths = resolve_config_paths(
                platform,
                home=str(home),
                xdg_config_home=xdg["XDG_CONFIG_HOME"],
                xdg_data_home=xdg["XDG_DATA_HOME"],
                xdg_cache_home=xdg["XDG_CACHE_HOME"],
            )
            source = configured_source("team", SourceKind.SOURCE_GIT)
            configuration = effective_configuration((source,)).configuration
            config_file = Path(config_paths.user_config_file)
            config_file.parent.mkdir(parents=True)
            config_file.write_bytes(user_configuration_bytes(configuration))
            with mock.patch.dict(os.environ, xdg, clear=False):
                missing_snapshot = load_local_consumer_service(
                    project=str(project),
                    user_home=str(home),
                )
            assert isinstance(missing_snapshot, Ok), missing_snapshot
            self.assertEqual(missing_snapshot.value.context.catalog.items, ())
            candidate = make_source_candidate(
                source_instance_id(source),
                source.alias,
                "a" * 40,
                native_snapshot(),
            )
            assert isinstance(candidate, Ok), candidate
            published = publish_source_snapshot(
                SourcePublishCommand(
                    source_store_paths(config_paths.data_root, source_instance_id(source)),
                    ValidatedSourceCandidate(candidate.value, SourceId("reference-native-source")),
                    90,
                )
            )
            assert isinstance(published, Ok), published

            with mock.patch.dict(os.environ, xdg, clear=False):
                persisted = load_local_consumer_service(
                    project=str(project),
                    user_home=str(home),
                )
                disabled = replace(
                    configuration,
                    sources=(replace(source, enabled=False),),
                )
                config_file.write_bytes(user_configuration_bytes(disabled))
                prospective = load_local_consumer_service(
                    project=str(project),
                    user_home=str(home),
                    configuration=configuration,
                )

            assert isinstance(persisted, Ok), persisted
            assert isinstance(prospective, Ok), prospective
            for loaded in (persisted.value, prospective.value):
                rows = loaded.browse(MarketplaceTarget(("claude",), "darwin", "project", "copy"))
                assert isinstance(rows, Ok), rows
                self.assertEqual(
                    tuple(row.key for row in rows.value),
                    ("team/skill/code-review@1.0.0",),
                )
                digest = loaded.context.catalog.items[0].artifact.artifact.object_digest.value
                self.assertTrue(
                    (Path(loaded.context.store_paths.objects) / digest[:2] / digest[2:]).is_dir()
                )

    def test_verified_registry_security_index_is_bound_to_exact_marketplace_coordinates(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = configured_source("company", SourceKind.REGISTRY_GIT)
            snapshot = registry_snapshot()
            compiled = parse_registry_index(snapshot_file(snapshot, "aart.index.json"))
            assert isinstance(compiled, Ok), compiled
            empty_digest = json_digest(JsonObject(()))
            entries = []
            for artifact in compiled.value.artifacts:
                attestation = SecurityAttestation(
                    1,
                    AssessmentCacheKey(
                        1,
                        artifact.object_digest,
                        "aart-baseline",
                        "1",
                        BASELINE_RULES_DIGEST,
                        empty_digest,
                        empty_digest,
                    ),
                    AttestationOrigin(
                        AttestationOriginKind.REGISTRY_CI,
                        compiled.value.registry_id,
                        "a" * 40,
                        compiled.value.registry_inputs_digest,
                    ),
                    not_scanned_assessment(
                        artifact.object_digest,
                        "Registry CI recorded explicit baseline coverage.",
                    ),
                )
                digest = attestation_digest(attestation)
                path = parse_relative_path(f"security/attestations/{digest.value}.json")
                assert isinstance(path, Ok), path
                entries.append(SecurityIndexEntry(attestation.cache_key, digest, path.value))
                snapshot = append_snapshot_file(
                    snapshot,
                    str(path.value),
                    attestation_bytes(attestation),
                )
            index = SecurityIndex(
                1,
                compiled.value.registry_id,
                compiled.value.registry_inputs_digest,
                tuple(entries),
            )
            snapshot = append_snapshot_file(
                snapshot,
                "security/index.json",
                security_index_bytes(index),
            )
            current = _current(source, "reference-registry", snapshot)
            paths = object_store_paths(str(Path(raw) / "data"))
            projected = _graph_source(source, current, paths)
            assert isinstance(projected, Ok), projected
            graph = compile_marketplace_graph(
                (projected.value,),
                available_capabilities=_CAPABILITIES,
            )
            assert isinstance(graph, Ok), graph
            effective = effective_configuration((source,), default_registry="company")
            catalog = build_marketplace(
                graph.value,
                effective,
                (
                    MarketplaceSourceState(
                        source,
                        assess_source_health(current, now=100, max_age_seconds=30),
                        0,
                    ),
                ),
            )
            assert isinstance(catalog, Ok), catalog

            evidence = _registry_security_evidence(
                catalog.value,
                ((source, current),),
                now=100,
            )

            self.assertEqual(len(evidence), 2)
            self.assertEqual({item.evidence_age_seconds for item in evidence}, {10})
            trust = {item.coordinate.artifact.name: item.attestation_trust for item in evidence}
            self.assertEqual(trust["atlassian"], AttestationTrust.REGISTRY_REVIEWED)
            self.assertEqual(trust["code-review"], AttestationTrust.UNVERIFIED)
            self.assertTrue(
                all(item.assessment.providers[0].id == "aart-baseline" for item in evidence)
            )

            missing_documents = append_snapshot_file(
                registry_snapshot(),
                "security/index.json",
                security_index_bytes(index),
            )
            missing_current = _current(source, "reference-registry", missing_documents)
            self.assertEqual(
                _registry_security_evidence(
                    catalog.value,
                    ((source, missing_current),),
                    now=100,
                ),
                (),
            )
            tampered = registry_snapshot()
            for entry in entries:
                tampered = append_snapshot_file(tampered, str(entry.path), b"{}\n")
            tampered = append_snapshot_file(
                tampered,
                "security/index.json",
                security_index_bytes(index),
            )
            tampered_current = _current(source, "reference-registry", tampered)
            self.assertEqual(
                _registry_security_evidence(
                    catalog.value,
                    ((source, tampered_current),),
                    now=100,
                ),
                (),
            )
            malformed = append_snapshot_file(
                registry_snapshot(),
                "security/index.json",
                b"{}\n",
            )
            malformed_current = _current(source, "reference-registry", malformed)
            mismatched_index = SecurityIndex(
                1,
                SourceId("other-registry"),
                compiled.value.registry_inputs_digest,
                (),
            )
            mismatched = append_snapshot_file(
                registry_snapshot(),
                "security/index.json",
                security_index_bytes(mismatched_index),
            )
            mismatched_current = _current(source, "reference-registry", mismatched)
            for degraded in (malformed_current, mismatched_current):
                self.assertEqual(
                    _registry_security_evidence(
                        catalog.value,
                        ((source, degraded),),
                        now=100,
                    ),
                    (),
                )

    def test_direct_native_snapshot_materializes_objects_and_builds_qualified_graph(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = configured_source("team", SourceKind.SOURCE_GIT)
            current = _current(source, "reference-native-source", native_snapshot())
            paths = object_store_paths(str(Path(raw) / "data"))

            projected = _graph_source(source, current, paths)

            assert isinstance(projected, Ok), projected
            self.assertEqual(projected.value.alias, source.alias)
            self.assertEqual(len(projected.value.artifacts), 1)
            self.assertTrue(
                all(
                    (
                        Path(paths.objects)
                        / artifact.object_digest.value[:2]
                        / artifact.object_digest.value[2:]
                    ).is_dir()
                    for artifact in projected.value.artifacts
                )
            )

    def test_registry_index_rebinds_runtime_source_identity_and_preserves_review_trust(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = configured_source("company", SourceKind.REGISTRY_GIT)
            current = _current(source, "reference-registry", registry_snapshot())
            paths = object_store_paths(str(Path(raw) / "data"))
            projected = _graph_source(source, current, paths)
            assert isinstance(projected, Ok), projected
            graph = compile_marketplace_graph(
                (projected.value,),
                available_capabilities=_CAPABILITIES,
            )
            assert isinstance(graph, Ok), graph
            effective = effective_configuration((source,), default_registry="company")
            catalog = build_marketplace(
                graph.value,
                effective,
                (
                    MarketplaceSourceState(
                        source,
                        assess_source_health(current, now=100, max_age_seconds=30),
                        0,
                    ),
                ),
            )

            assert isinstance(catalog, Ok), catalog
            self.assertEqual(len(catalog.value.items), 2)
            self.assertTrue(
                all(
                    item.artifact.source_id == SourceId("reference-registry")
                    for item in catalog.value.items
                )
            )
            trust = {
                item.coordinate.artifact.name: item.trust.kind.value for item in catalog.value.items
            }
            self.assertEqual(trust, {"atlassian": "registry-reviewed", "code-review": "unverified"})
            self.assertEqual(
                _registry_security_evidence(
                    catalog.value,
                    ((source, current),),
                    now=100,
                ),
                (),
            )


if __name__ == "__main__":
    unittest.main()
