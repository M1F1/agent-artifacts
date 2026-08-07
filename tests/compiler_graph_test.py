from __future__ import annotations

import unittest
from typing import cast

from agent_artifacts.compiler.graph import (
    ArtifactLifecycle,
    CollectionCoordinate,
    CompatibilityReason,
    CompatibilityTarget,
    GraphSource,
    MarketplaceArtifact,
    MarketplaceCollection,
    MarketplaceGraph,
    SelectionMode,
    SelectionRequest,
    compile_marketplace_graph,
    compile_marketplace_graph_phase,
    evaluate_compatibility,
    expand_collection,
    marketplace_graph_bytes,
    select_artifacts,
)
from agent_artifacts.domain.identifiers import (
    ArtifactCoordinate,
    ArtifactIdentity,
    ObjectDigest,
    SourceAlias,
    SourceId,
)
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.protocol.capabilities import Capability
from agent_artifacts.protocol.hashing import sha256_bytes
from agent_artifacts.protocol.native_models import (
    ArtifactSelector,
    CollectionManifest,
    CompatibilitySpec,
    InstallSpec,
)
from agent_artifacts.protocol.paths import SafeRelativePath
from agent_artifacts.protocol.registry_models import (
    IndexArtifact,
    IndexProvenance,
    IndexSetup,
    ReviewRecord,
)
from agent_artifacts.protocol.semver import SemVer, VersionBounds


def _digest(character: str) -> ObjectDigest:
    return ObjectDigest("sha256", character * 64)


def _artifact(
    name: str,
    *,
    source_id: str = "company-registry",
    version: SemVer | None = None,
    payload: str = "2",
    profiles: tuple[str, ...] = ("claude",),
    platforms: tuple[str, ...] = ("darwin",),
    scopes: tuple[str, ...] = ("project",),
    modes: tuple[str, ...] = ("copy",),
    effects: tuple[str, ...] = ("copy-tree",),
    setup: IndexSetup | None = None,
    provenance: IndexProvenance | None = None,
) -> IndexArtifact:
    return IndexArtifact(
        SourceId(source_id),
        ArtifactIdentity("skill", name),
        version or SemVer(1, 0, 0),
        f"Use {name} during agent work.",
        _digest("1"),
        _digest(payload),
        _digest("3"),
        CompatibilitySpec(profiles, platforms),
        InstallSpec(scopes, modes, effects),  # type: ignore[arg-type]
        setup,
        ReviewRecord("approved", "company-v1"),
        provenance,
    )


def _collection(
    name: str,
    *,
    artifacts: tuple[ArtifactSelector, ...] = (),
    collections: tuple[str, ...] = (),
) -> CollectionManifest:
    return CollectionManifest(1, name, f"The {name} collection.", artifacts, collections)


def _source(
    alias: str,
    *,
    artifacts: tuple[IndexArtifact, ...],
    collections: tuple[CollectionManifest, ...] = (),
    required_capabilities: tuple[Capability, ...] = (),
    source_id: str = "company-registry",
) -> GraphSource:
    return GraphSource(
        SourceAlias(alias),
        SourceId(source_id),
        required_capabilities,
        artifacts,
        collections,
    )


def _target(**changes: object) -> CompatibilityTarget:
    values: dict[str, object] = {
        "profile": "claude",
        "platform": "darwin",
        "scope": "project",
        "mode": "copy",
        "effects": ("copy-tree",),
        "setup_capabilities": (Capability("keychain-secret"),),
        "require_setup": True,
    }
    values.update(changes)
    return CompatibilityTarget(**values)  # type: ignore[arg-type]


class CompilerGraphTest(unittest.TestCase):
    def test_graph_is_deterministic_and_preserves_external_reference_provenance(self) -> None:
        external = _artifact(
            "atlassian",
            provenance=IndexProvenance(
                "https://github.example/team/atlassian.git",
                "a" * 40,
                SafeRelativePath(("artifacts", "skill", "atlassian")),
            ),
        )
        review = _artifact("code-review")
        child = _collection(
            "child",
            artifacts=(ArtifactSelector(review.identity), ArtifactSelector(external.identity)),
        )
        parent = _collection(
            "parent",
            artifacts=(ArtifactSelector(review.identity),),
            collections=("child",),
        )
        source = _source(
            "company",
            artifacts=(external, review),
            collections=(parent, child),
        )

        left = compile_marketplace_graph((source,), available_capabilities=())
        right = compile_marketplace_graph(
            (
                _source(
                    "company",
                    artifacts=(review, external),
                    collections=(child, parent),
                ),
            ),
            available_capabilities=(),
        )

        self.assertIsInstance(left, Ok)
        self.assertEqual(left, right)
        assert isinstance(left, Ok)
        self.assertEqual(marketplace_graph_bytes(left.value), marketplace_graph_bytes(right.value))
        preserved = next(
            item for item in left.value.artifacts if item.artifact.identity.name == "atlassian"
        )
        self.assertEqual(preserved.source_alias, SourceAlias("company"))
        self.assertEqual(preserved.artifact.provenance, external.provenance)
        encoded = marketplace_graph_bytes(left.value)
        self.assertIn(b'"resolved_commit":"' + b"a" * 40 + b'"', encoded)
        self.assertNotIn(b"payload_bytes", encoded)

        phase = compile_marketplace_graph_phase((source,), available_capabilities=())
        self.assertIsInstance(phase, Ok)
        assert isinstance(phase, Ok)
        self.assertEqual(phase.value.value, left.value)
        self.assertEqual(phase.value.digest, sha256_bytes(encoded))

        expanded = expand_collection(
            left.value,
            CollectionCoordinate(SourceAlias("company"), "parent"),
        )
        self.assertIsInstance(expanded, Ok)
        assert isinstance(expanded, Ok)
        self.assertEqual(
            tuple(str(item) for item in expanded.value),
            (
                "company/skill/atlassian@1.0.0",
                "company/skill/code-review@1.0.0",
            ),
        )

    def test_source_capabilities_and_collection_graph_fail_closed(self) -> None:
        artifact = _artifact("code-review")
        missing_capability = _source(
            "company",
            artifacts=(artifact,),
            required_capabilities=(Capability("graph-v2"),),
        )
        missing_artifact = _collection(
            "missing-artifact",
            artifacts=(ArtifactSelector(ArtifactIdentity("skill", "missing")),),
        )
        excluded_version = _collection(
            "excluded-version",
            artifacts=(
                ArtifactSelector(
                    artifact.identity,
                    VersionBounds(max_exclusive=SemVer(1, 0, 0)),
                ),
            ),
        )
        cycle_a = _collection("cycle-a", collections=("cycle-b",))
        cycle_b = _collection("cycle-b", collections=("cycle-a",))
        cases = (
            (
                (missing_capability,),
                (),
                "source-incompatible",
            ),
            (
                (_source("company", artifacts=(artifact,), collections=(missing_artifact,)),),
                (),
                "marketplace-graph-invalid",
            ),
            (
                (_source("company", artifacts=(artifact,), collections=(excluded_version,)),),
                (),
                "marketplace-graph-invalid",
            ),
            (
                (_source("company", artifacts=(artifact,), collections=(cycle_b, cycle_a)),),
                (),
                "marketplace-graph-invalid",
            ),
        )

        for sources, capabilities, code in cases:
            with self.subTest(code=code, sources=sources):
                result = compile_marketplace_graph(
                    sources,
                    available_capabilities=capabilities,
                )
                self.assertIsInstance(result, Err)
                assert isinstance(result, Err)
                self.assertEqual(result.diagnostics[0].code.value, code)

    def test_compatibility_reports_every_independent_reason(self) -> None:
        setup = IndexSetup(
            SafeRelativePath(("setup", "installer.json")),
            ("darwin",),
            (Capability("keychain-secret"), Capability("open-browser")),
        )
        source = _source("company", artifacts=(_artifact("review", setup=setup),))
        compiled = compile_marketplace_graph((source,), available_capabilities=())
        assert isinstance(compiled, Ok)
        record = compiled.value.artifacts[0]

        decision = evaluate_compatibility(
            record,
            _target(
                profile="tabnine",
                platform="linux",
                scope="user",
                mode="symlink",
                effects=("merge-json",),
                setup_capabilities=(Capability("keychain-secret"),),
            ),
        )

        self.assertFalse(decision.compatible)
        self.assertEqual(
            tuple(reason.code for reason in decision.reasons),
            (
                "effect-unsupported",
                "mode-unsupported",
                "platform-unsupported",
                "profile-unsupported",
                "scope-unsupported",
                "setup-capability-missing",
                "setup-platform-unsupported",
            ),
        )
        payload_only = evaluate_compatibility(
            record,
            _target(
                setup_capabilities=(),
                require_setup=False,
            ),
        )
        self.assertTrue(payload_only.compatible)
        self.assertFalse(payload_only.setup_compatible)
        self.assertEqual(
            tuple(reason.code for reason in payload_only.setup_reasons),
            ("setup-capability-missing",),
        )

    def test_broad_selection_skips_but_explicit_incompatible_selection_fails(self) -> None:
        compatible = _artifact("compatible")
        incompatible = _artifact("linux-only", platforms=("linux",))
        compiled = compile_marketplace_graph(
            (_source("company", artifacts=(incompatible, compatible)),),
            available_capabilities=(),
        )
        assert isinstance(compiled, Ok)

        broad = select_artifacts(
            compiled.value,
            SelectionRequest(SelectionMode.BROAD, _target()),
        )
        explicit = select_artifacts(
            compiled.value,
            SelectionRequest(
                SelectionMode.EXPLICIT,
                _target(),
                artifacts=(
                    ArtifactCoordinate(
                        SourceAlias("company"),
                        ArtifactIdentity("skill", "linux-only"),
                    ),
                ),
            ),
        )

        self.assertIsInstance(broad, Ok)
        assert isinstance(broad, Ok)
        self.assertEqual(
            tuple(item.artifact.identity.name for item in broad.value.selected),
            ("compatible",),
        )
        self.assertEqual(len(broad.value.skipped), 1)
        self.assertEqual(broad.value.skipped[0].reasons[0].code, "platform-unsupported")
        self.assertIsInstance(explicit, Err)
        assert isinstance(explicit, Err)
        self.assertEqual(explicit.diagnostics[0].code.value, "artifact-incompatible")

    def test_collection_selection_reuses_deterministic_expansion(self) -> None:
        first = _artifact("first")
        second = _artifact("second")
        child = _collection(
            "child",
            artifacts=(ArtifactSelector(first.identity), ArtifactSelector(second.identity)),
        )
        parent = _collection(
            "parent",
            artifacts=(ArtifactSelector(second.identity),),
            collections=("child",),
        )
        compiled = compile_marketplace_graph(
            (_source("company", artifacts=(second, first), collections=(parent, child)),),
            available_capabilities=(),
        )
        assert isinstance(compiled, Ok)

        selected = select_artifacts(
            compiled.value,
            SelectionRequest(
                SelectionMode.EXPLICIT,
                _target(),
                collections=(CollectionCoordinate(SourceAlias("company"), "parent"),),
            ),
        )

        self.assertIsInstance(selected, Ok)
        assert isinstance(selected, Ok)
        self.assertEqual(
            tuple(item.artifact.identity.name for item in selected.value.selected),
            ("first", "second"),
        )

    def test_value_boundaries_reject_invalid_programmer_inputs(self) -> None:
        source = _source("company", artifacts=(_artifact("review"),))
        compiled = compile_marketplace_graph((source,), available_capabilities=())
        assert isinstance(compiled, Ok)
        artifact = compiled.value.artifacts[0]
        collection = MarketplaceCollection(
            CollectionCoordinate(SourceAlias("company"), "tools"),
            "Tools.",
            (artifact.coordinate,),
        )
        invalid_target_values = (
            ("", "darwin", "project", "copy", ("copy-tree",), (), True),
            ("claude", "darwin", "invalid", "copy", ("copy-tree",), (), True),
            ("claude", "darwin", "project", "invalid", ("copy-tree",), (), True),
            ("claude", "darwin", "project", "copy", ("invalid",), (), True),
            ("claude", "darwin", "project", "copy", ("copy-tree",), (), "yes"),
        )
        factories = (
            lambda: CollectionCoordinate(SourceAlias(""), "tools"),
            lambda: GraphSource(SourceAlias(""), SourceId("source"), (), (), ()),
            lambda: MarketplaceArtifact(
                SourceAlias("other"),
                SourceId("other-source"),
                artifact.artifact,
                artifact.semantic_digest,
            ),
            lambda: MarketplaceArtifact(
                artifact.source_alias,
                artifact.source_id,
                artifact.artifact,
                _digest("f"),
            ),
            lambda: MarketplaceArtifact(
                artifact.source_alias,
                artifact.source_id,
                artifact.artifact,
                artifact.semantic_digest,
                cast(ArtifactLifecycle, "invalid"),
            ),
            lambda: MarketplaceCollection(
                CollectionCoordinate(SourceAlias("company"), "tools"),
                "Tools.",
                (
                    ArtifactCoordinate(
                        SourceAlias("other"),
                        artifact.artifact.identity,
                        str(artifact.artifact.version),
                    ),
                ),
            ),
            lambda: MarketplaceGraph((artifact, artifact), (), ()),
            lambda: MarketplaceGraph((), (collection, collection), ()),
            lambda: SelectionRequest(cast(SelectionMode, "invalid"), _target()),
        )

        for factory in factories:
            with self.subTest(factory=factory):
                with self.assertRaises(ValueError):
                    factory()
        for values in invalid_target_values:
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    CompatibilityTarget(*values)  # type: ignore[arg-type]

    def test_duplicate_or_mismatched_sources_and_collections_fail_closed(self) -> None:
        artifact = _artifact("review")
        duplicate_artifact = _source("company", artifacts=(artifact, artifact))
        wrong_source_artifact = _source(
            "company",
            artifacts=(_artifact("review", source_id="other-source"),),
        )
        duplicate_collection = _collection(
            "tools", artifacts=(ArtifactSelector(artifact.identity),)
        )
        missing_nested = _collection("tools", collections=("missing",))
        cases = (
            (_source("company", artifacts=(artifact,)), _source("company", artifacts=(artifact,))),
            (
                _source("company", artifacts=(artifact,)),
                _source(
                    "other-alias",
                    artifacts=(),
                    source_id="company-registry",
                ),
            ),
            (duplicate_artifact,),
            (wrong_source_artifact,),
            (
                _source(
                    "company",
                    artifacts=(artifact,),
                    collections=(duplicate_collection, duplicate_collection),
                ),
            ),
            (
                _source(
                    "company",
                    artifacts=(artifact,),
                    collections=(missing_nested,),
                ),
            ),
        )

        for sources in cases:
            with self.subTest(sources=sources):
                result = compile_marketplace_graph(sources, available_capabilities=())
                self.assertIsInstance(result, Err)

    def test_missing_and_empty_selection_returns_explicit_reasons(self) -> None:
        compiled = compile_marketplace_graph(
            (_source("company", artifacts=(_artifact("review"),)),),
            available_capabilities=(),
        )
        assert isinstance(compiled, Ok)
        missing = ArtifactCoordinate(
            SourceAlias("company"),
            ArtifactIdentity("skill", "missing"),
        )
        missing_version = ArtifactCoordinate(
            SourceAlias("company"),
            ArtifactIdentity("skill", "review"),
            "9.0.0",
        )

        explicit_empty = select_artifacts(
            compiled.value,
            SelectionRequest(SelectionMode.EXPLICIT, _target()),
        )
        explicit_missing_collection = select_artifacts(
            compiled.value,
            SelectionRequest(
                SelectionMode.EXPLICIT,
                _target(),
                collections=(CollectionCoordinate(SourceAlias("company"), "missing"),),
            ),
        )
        explicit_conflicting_versions = select_artifacts(
            compiled.value,
            SelectionRequest(
                SelectionMode.EXPLICIT,
                _target(),
                artifacts=(
                    ArtifactCoordinate(
                        SourceAlias("company"),
                        ArtifactIdentity("skill", "review"),
                    ),
                    missing_version,
                ),
            ),
        )
        broad = select_artifacts(
            compiled.value,
            SelectionRequest(
                SelectionMode.BROAD,
                _target(),
                artifacts=(missing, missing_version),
            ),
        )

        self.assertIsInstance(explicit_empty, Err)
        self.assertIsInstance(explicit_missing_collection, Err)
        self.assertIsInstance(explicit_conflicting_versions, Err)
        self.assertIsInstance(broad, Ok)
        assert isinstance(broad, Ok)
        self.assertEqual(broad.value.selected, ())
        self.assertEqual(
            tuple(item.reasons for item in broad.value.skipped),
            (
                (
                    CompatibilityReason(
                        "artifact-not-found", "artifact is not available: company/skill/missing"
                    ),
                ),
                (
                    CompatibilityReason(
                        "artifact-not-found",
                        "artifact is not available: company/skill/review@9.0.0",
                    ),
                ),
            ),
        )


if __name__ == "__main__":
    unittest.main()
