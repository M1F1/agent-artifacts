from __future__ import annotations

import unittest

from agent_artifacts.compiler.graph import (
    ArtifactLifecycle,
    CompatibilityTarget,
    GraphSource,
    SelectionMode,
    SelectionRequest,
    compile_marketplace_graph,
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
from agent_artifacts.protocol.native_models import CompatibilitySpec, InstallSpec
from agent_artifacts.protocol.registry_models import IndexArtifact
from agent_artifacts.protocol.semver import SemVer


def _digest(character: str) -> ObjectDigest:
    return ObjectDigest("sha256", character * 64)


def _artifact(
    *,
    version: SemVer,
    payload: str,
    manifest: str = "1",
    object_digest: str = "3",
    effects: tuple[str, ...] = ("copy-tree",),
) -> IndexArtifact:
    return IndexArtifact(
        SourceId("team-source"),
        ArtifactIdentity("skill", "review"),
        version,
        "Review code changes.",
        _digest(manifest),
        _digest(payload),
        _digest(object_digest),
        CompatibilitySpec(("claude",), ("darwin",)),
        InstallSpec(("project",), ("copy",), effects),  # type: ignore[arg-type]
    )


def _source(*artifacts: IndexArtifact) -> GraphSource:
    return GraphSource(
        SourceAlias("team"),
        SourceId("team-source"),
        (),
        artifacts,
        (),
    )


def _target() -> CompatibilityTarget:
    return CompatibilityTarget(
        "claude",
        "darwin",
        "project",
        "copy",
        ("copy-tree",),
    )


class CompilerGraphHistoryTest(unittest.TestCase):
    def test_semantic_content_change_requires_version_precedence_change(self) -> None:
        previous = compile_marketplace_graph(
            (_source(_artifact(version=SemVer(1, 0, 0), payload="2")),),
            available_capabilities=(),
        )
        assert isinstance(previous, Ok)

        same_version_payload = compile_marketplace_graph(
            (_source(_artifact(version=SemVer(1, 0, 0), payload="4")),),
            available_capabilities=(),
            previous=previous.value,
        )
        build_metadata_only = compile_marketplace_graph(
            (
                _source(
                    _artifact(
                        version=SemVer(1, 0, 0, build=("rebuilt",)),
                        payload="4",
                    )
                ),
            ),
            available_capabilities=(),
            previous=previous.value,
        )
        same_version_effect = compile_marketplace_graph(
            (
                _source(
                    _artifact(
                        version=SemVer(1, 0, 0),
                        payload="2",
                        effects=("merge-json",),
                    )
                ),
            ),
            available_capabilities=(),
            previous=previous.value,
        )
        same_version_object = compile_marketplace_graph(
            (
                _source(
                    _artifact(
                        version=SemVer(1, 0, 0),
                        payload="2",
                        object_digest="5",
                    )
                ),
            ),
            available_capabilities=(),
            previous=previous.value,
        )

        for result in (
            same_version_payload,
            build_metadata_only,
            same_version_effect,
            same_version_object,
        ):
            with self.subTest(result=result):
                self.assertIsInstance(result, Err)
                assert isinstance(result, Err)
                self.assertEqual(
                    result.diagnostics[0].code.value,
                    "artifact-version-unchanged",
                )

    def test_version_regression_fails_and_version_without_content_warns(self) -> None:
        previous = compile_marketplace_graph(
            (_source(_artifact(version=SemVer(2, 0, 0), payload="2")),),
            available_capabilities=(),
        )
        assert isinstance(previous, Ok)

        regression = compile_marketplace_graph(
            (_source(_artifact(version=SemVer(1, 9, 0), payload="4")),),
            available_capabilities=(),
            previous=previous.value,
        )
        version_only = compile_marketplace_graph(
            (_source(_artifact(version=SemVer(2, 1, 0), payload="2")),),
            available_capabilities=(),
            previous=previous.value,
        )

        self.assertIsInstance(regression, Err)
        assert isinstance(regression, Err)
        self.assertEqual(regression.diagnostics[0].code.value, "artifact-version-regressed")
        self.assertIsInstance(version_only, Ok)
        assert isinstance(version_only, Ok)
        self.assertEqual(
            tuple(item.code.value for item in version_only.value.diagnostics),
            ("artifact-version-without-content",),
        )

    def test_removed_artifact_is_a_tombstone_and_cannot_be_selected(self) -> None:
        previous = compile_marketplace_graph(
            (_source(_artifact(version=SemVer(1, 0, 0), payload="2")),),
            available_capabilities=(),
        )
        assert isinstance(previous, Ok)

        current = compile_marketplace_graph(
            (_source(),),
            available_capabilities=(),
            previous=previous.value,
        )

        self.assertIsInstance(current, Ok)
        assert isinstance(current, Ok)
        self.assertEqual(len(current.value.artifacts), 1)
        self.assertIs(current.value.artifacts[0].lifecycle, ArtifactLifecycle.REMOVED)
        explicit = select_artifacts(
            current.value,
            SelectionRequest(
                SelectionMode.EXPLICIT,
                _target(),
                artifacts=(
                    ArtifactCoordinate(
                        SourceAlias("team"),
                        ArtifactIdentity("skill", "review"),
                    ),
                ),
            ),
        )
        broad = select_artifacts(
            current.value,
            SelectionRequest(SelectionMode.BROAD, _target()),
        )

        self.assertIsInstance(explicit, Err)
        assert isinstance(explicit, Err)
        self.assertEqual(explicit.diagnostics[0].code.value, "artifact-not-found")
        self.assertIsInstance(broad, Ok)
        assert isinstance(broad, Ok)
        self.assertEqual(broad.value.selected, ())
        self.assertEqual(broad.value.skipped[0].reasons[0].code, "artifact-removed")


if __name__ == "__main__":
    unittest.main()
