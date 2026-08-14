from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_artifacts.curation import runtime as curation_runtime
from agent_artifacts.curation.model import CurationAction, CurationRequest
from agent_artifacts.curation.runtime import LocalCurationService
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import ObjectDigest, SourceAlias
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.registry_maintenance.model import NativeReferenceAcquisition
from agent_artifacts.sources.model import SourceInstanceId, make_source_candidate
from tests.registry_maintenance_fixtures import (
    append_snapshot_file,
    native_snapshot,
    replace_snapshot_file,
    snapshot_file,
)


def _git_checkout(root: Path) -> None:
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)


def _failure(message: str = "injected failure") -> Err:
    return Err((Diagnostic(DiagnosticCode("test-failure"), Severity.ERROR, message),))


def _setup_v1_native_snapshot():
    """A retired recipe must fail at promotion, before a registry entry can exist."""

    manifest_path = "artifacts/skill/code-review/artifact.json"
    manifest = json.loads(snapshot_file(native_snapshot(), manifest_path))
    manifest["setup"] = {"recipe": "setup/installer.json", "platforms": ["darwin"]}
    with_recipe = replace_snapshot_file(
        native_snapshot(),
        manifest_path,
        json.dumps(manifest, sort_keys=True).encode("utf-8"),
    )
    return append_snapshot_file(
        with_recipe,
        "artifacts/skill/code-review/setup/installer.json",
        json.dumps({"schema_version": 1, "protocol_version": 1}, sort_keys=True).encode("utf-8"),
    )


class CurationRuntimeTest(unittest.TestCase):
    def test_default_native_acquisition_binds_a_pinned_immutable_candidate(self) -> None:
        native_candidate = make_source_candidate(
            SourceInstanceId("git-" + "a" * 32),
            SourceAlias("curation-native"),
            "a" * 40,
            native_snapshot(),
        )
        assert isinstance(native_candidate, Ok)
        with mock.patch.object(
            curation_runtime,
            "_candidate",
            return_value=native_candidate,
        ):
            native = curation_runtime.default_native_acquirer(
                "https://github.com/example/reference-skills.git",
                "main",
            )
        assert isinstance(native, Ok), native
        self.assertEqual(native.value.resolved_commit, "a" * 40)

        with mock.patch.object(curation_runtime, "_candidate", return_value=_failure()):
            self.assertIsInstance(
                curation_runtime.default_native_acquirer(
                    "https://github.com/example/reference-skills.git",
                    "main",
                ),
                Err,
            )
        invalid_revision = make_source_candidate(
            SourceInstanceId("git-" + "b" * 32),
            SourceAlias("curation-native"),
            "not-a-commit",
            native_snapshot(),
        )
        assert isinstance(invalid_revision, Ok)
        with mock.patch.object(
            curation_runtime,
            "_candidate",
            return_value=invalid_revision,
        ):
            self.assertIsInstance(
                curation_runtime.default_native_acquirer(
                    "https://github.com/example/reference-skills.git",
                    "main",
                ),
                Err,
            )

    def test_local_git_candidate_is_acquired_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "source"
            _git_checkout(root)
            (root / "README.md").write_text("source", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "README.md"], check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=AART Test",
                    "-c",
                    "user.email=aart@example.invalid",
                    "-C",
                    str(root),
                    "commit",
                    "-qm",
                    "fixture",
                ],
                check=True,
            )
            acquired = curation_runtime._candidate(
                str(root),
                "HEAD",
                alias="curation-local",
                allow_local_transport=True,
            )
            assert isinstance(acquired, Ok), acquired
            self.assertRegex(acquired.value.resolved_revision, r"^[0-9a-f]{40}$")

    def test_mutation_is_rejected_before_preview_without_a_local_git_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "plain"
            root.mkdir()
            service = LocalCurationService(str(root))
            prepared = service.prepare(
                CurationRequest(
                    CurationAction.INIT,
                    str(root),
                    source_id="test-registry",
                    display_name="Test Registry",
                )
            )
            self.assertIsInstance(prepared, Err)
            self.assertEqual(tuple(root.iterdir()), ())
            missing = Path(temporary) / "missing"
            read_only = LocalCurationService(str(missing)).prepare(
                CurationRequest(CurationAction.VALIDATE, str(missing))
            )
            self.assertIsInstance(read_only, Err)

    def test_invalid_or_incomplete_requests_fail_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "registry"
            other = Path(temporary) / "other"
            _git_checkout(root)
            other.mkdir()
            service = LocalCurationService(
                str(root),
                native_acquirer=lambda _url, _ref: _failure(),
            )
            requests = (
                CurationRequest(CurationAction.INIT, str(root)),
                CurationRequest(
                    CurationAction.INIT,
                    str(root),
                    source_id="registry",
                    display_name="Registry",
                    minimum_version="not-semver",
                ),
                CurationRequest(
                    CurationAction.INIT,
                    str(root),
                    source_id="registry",
                    display_name="Registry",
                    maximum_version="not-semver",
                ),
                CurationRequest(
                    CurationAction.INIT,
                    str(root),
                    source_id="registry",
                    display_name="Registry",
                    minimum_version="2.0.0",
                    maximum_version="1.0.0",
                ),
                CurationRequest(CurationAction.SCAFFOLD, str(root)),
                CurationRequest(
                    CurationAction.SCAFFOLD,
                    str(root),
                    kind="skill",
                    name="demo",
                    summary="Demo.",
                    artifact_version="not-semver",
                    profiles=("codex",),
                    platforms=("darwin",),
                ),
                CurationRequest(CurationAction.PROMOTE_NATIVE, str(root)),
                CurationRequest(
                    CurationAction.PROMOTE_NATIVE,
                    str(root),
                    kind="skill",
                    name="demo",
                    url="https://github.com/example/repo.git",
                    path="artifacts/skill/demo",
                ),
                CurationRequest(
                    CurationAction.PROMOTE_NATIVE,
                    str(root),
                    kind="skill",
                    name="demo",
                    url="http://insecure.example/repo.git",
                    path="artifacts/skill/demo",
                ),
                CurationRequest(CurationAction.REFRESH_NATIVE, str(root)),
                CurationRequest(
                    CurationAction.REFRESH_NATIVE,
                    str(root),
                    kind="skill",
                    name="missing",
                ),
                CurationRequest(CurationAction.VALIDATE, str(other)),
            )
            for request in requests:
                with self.subTest(action=request.action, request=request):
                    self.assertIsInstance(service.prepare(request), Err)
            self.assertEqual(tuple(root.iterdir()), (root / ".git",))
            with self.assertRaises(ValueError):
                LocalCurationService("relative")

    def test_init_and_scaffold_are_previewed_then_exactly_finalized(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "registry"
            _git_checkout(root)
            service = LocalCurationService(str(root))
            initialized = service.prepare(
                CurationRequest(
                    CurationAction.INIT,
                    str(root),
                    source_id="test-registry",
                    display_name="Test Registry",
                )
            )
            assert isinstance(initialized, Ok), initialized
            self.assertIn(
                f"aart registry validate --source {root}",
                initialized.value.review.follow_up_commands,
            )
            self.assertFalse(
                any(
                    "validate" in command and "--strict" in command
                    for command in initialized.value.review.follow_up_commands
                )
            )
            self.assertTrue(
                any(
                    "registry lock" in command
                    for command in initialized.value.review.follow_up_commands
                )
            )
            self.assertTrue(
                any(
                    "registry build" in command
                    for command in initialized.value.review.follow_up_commands
                )
            )
            self.assertFalse((root / "aart-registry.json").exists())
            wrong = service.finalize(
                initialized.value,
                ObjectDigest("sha256", "f" * 64),
            )
            self.assertIsInstance(wrong, Err)
            applied = service.finalize(
                initialized.value,
                initialized.value.review.review_digest,
            )
            assert isinstance(applied, Ok), applied
            self.assertTrue((root / "aart-registry.json").is_file())
            duplicate_init = service.prepare(
                CurationRequest(
                    CurationAction.INIT,
                    str(root),
                    source_id="test-registry",
                    display_name="Test Registry",
                )
            )
            self.assertIsInstance(duplicate_init, Err)

            scaffold = service.prepare(
                CurationRequest(
                    CurationAction.SCAFFOLD,
                    str(root),
                    kind="skill",
                    name="demo",
                    summary="Explain the reviewed demo workflow.",
                    profiles=("codex",),
                    platforms=("darwin", "linux"),
                )
            )
            assert isinstance(scaffold, Ok), scaffold
            target = root / "artifacts" / "skill" / "demo" / "artifact.json"
            self.assertFalse(target.exists())
            result = service.finalize(scaffold.value, scaffold.value.review.review_digest)
            assert isinstance(result, Ok), result
            self.assertEqual(result.value.changed_paths, 2)
            self.assertTrue(target.is_file())
            self.assertTrue(any("git -C" in item for item in result.value.follow_up_commands))
            duplicate_scaffold = service.prepare(
                CurationRequest(
                    CurationAction.SCAFFOLD,
                    str(root),
                    kind="skill",
                    name="demo",
                    summary="Explain the reviewed demo workflow.",
                    profiles=("codex",),
                    platforms=("darwin", "linux"),
                )
            )
            self.assertIsInstance(duplicate_scaffold, Err)
            invalid_options = service.prepare(
                CurationRequest(
                    CurationAction.SCAFFOLD,
                    str(root),
                    kind="skill",
                    name="invalid-options",
                    summary="Invalid empty install options.",
                    profiles=("codex",),
                    platforms=("darwin",),
                    scopes=(),
                    modes=(),
                )
            )
            self.assertIsInstance(invalid_options, Err)

            stale_plan = service.prepare(
                CurationRequest(
                    CurationAction.SCAFFOLD,
                    str(root),
                    kind="skill",
                    name="stale-demo",
                    summary="Demonstrate stale review rejection.",
                    profiles=("codex",),
                    platforms=("darwin",),
                )
            )
            assert isinstance(stale_plan, Ok), stale_plan
            stale_target = root / "artifacts" / "skill" / "stale-demo" / "artifact.json"
            stale_target.parent.mkdir(parents=True)
            stale_target.write_text("maintainer edit", encoding="utf-8")
            stale = service.finalize(
                stale_plan.value,
                stale_plan.value.review.review_digest,
            )
            self.assertIsInstance(stale, Err)
            self.assertEqual(stale_target.read_text(encoding="utf-8"), "maintainer edit")

    def test_read_only_validate_audit_and_diff_never_require_a_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "snapshot"
            _git_checkout(root)
            service = LocalCurationService(str(root))
            initialized = service.prepare(
                CurationRequest(
                    CurationAction.INIT,
                    str(root),
                    source_id="test-registry",
                    display_name="Test Registry",
                )
            )
            assert isinstance(initialized, Ok)
            assert isinstance(
                service.finalize(initialized.value, initialized.value.review.review_digest), Ok
            )
            shutil.rmtree(root / ".git")
            for action in (CurationAction.VALIDATE, CurationAction.AUDIT, CurationAction.DIFF):
                with self.subTest(action=action):
                    prepared = service.prepare(CurationRequest(action, str(root)))
                    assert isinstance(prepared, Ok), prepared
                    self.assertFalse(prepared.value.review.mutating)
                    before = tuple(sorted(path.relative_to(root) for path in root.rglob("*")))
                    outcome = service.finalize(
                        prepared.value,
                        prepared.value.review.review_digest,
                    )
                    assert isinstance(outcome, Ok), outcome
                    after = tuple(sorted(path.relative_to(root) for path in root.rglob("*")))
                    self.assertEqual(before, after)

    def test_read_only_review_is_stale_if_the_workspace_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "registry"
            _git_checkout(root)
            service = LocalCurationService(str(root))
            initialized = service.prepare(
                CurationRequest(
                    CurationAction.INIT,
                    str(root),
                    source_id="test-registry",
                    display_name="Test Registry",
                )
            )
            assert isinstance(initialized, Ok)
            assert isinstance(
                service.finalize(initialized.value, initialized.value.review.review_digest), Ok
            )
            reviewed = service.prepare(CurationRequest(CurationAction.VALIDATE, str(root)))
            assert isinstance(reviewed, Ok), reviewed
            marker = root / "aart-registry.json"
            marker.write_bytes(marker.read_bytes() + b" ")
            stale = service.finalize(reviewed.value, reviewed.value.review.review_digest)
            self.assertIsInstance(stale, Err)

            second = service.prepare(CurationRequest(CurationAction.VALIDATE, str(root)))
            assert isinstance(second, Ok), second
            shutil.rmtree(root)
            missing = service.finalize(second.value, second.value.review.review_digest)
            self.assertIsInstance(missing, Err)

    def test_promote_and_refresh_use_pinned_native_acquisition(self) -> None:
        acquisitions: list[tuple[str, str]] = []

        def acquire(url: str, ref: str):
            acquisitions.append((url, ref))
            return Ok(NativeReferenceAcquisition(url, ref, "a" * 40, native_snapshot()))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "registry"
            _git_checkout(root)
            service = LocalCurationService(str(root), native_acquirer=acquire)
            initialized = service.prepare(
                CurationRequest(
                    CurationAction.INIT,
                    str(root),
                    source_id="test-registry",
                    display_name="Test Registry",
                )
            )
            assert isinstance(initialized, Ok)
            assert isinstance(
                service.finalize(initialized.value, initialized.value.review.review_digest), Ok
            )

            promote = service.prepare(
                CurationRequest(
                    CurationAction.PROMOTE_NATIVE,
                    str(root),
                    kind="skill",
                    name="code-review",
                    url="https://github.com/example/reference-skills.git",
                    ref="main",
                    path="artifacts/skill/code-review",
                    review_policy="company-review-v1",
                )
            )
            assert isinstance(promote, Ok), promote
            self.assertTrue(
                any(
                    "validate" in command and "--strict" in command
                    for command in promote.value.review.follow_up_commands
                )
            )
            self.assertEqual(
                acquisitions, [("https://github.com/example/reference-skills.git", "main")]
            )
            promoted = service.finalize(promote.value, promote.value.review.review_digest)
            assert isinstance(promoted, Ok), promoted
            self.assertEqual(promoted.value.changed_paths, 3)

            failing_update_service = LocalCurationService(
                str(root),
                native_acquirer=lambda _url, _ref: _failure(),
            )
            failed_update = failing_update_service.prepare(
                CurationRequest(
                    CurationAction.REFRESH_NATIVE,
                    str(root),
                    kind="skill",
                    name="code-review",
                )
            )
            self.assertIsInstance(failed_update, Err)

            checked = service.prepare(
                CurationRequest(
                    CurationAction.REFRESH_NATIVE,
                    str(root),
                    kind="skill",
                    name="code-review",
                )
            )
            assert isinstance(checked, Ok), checked
            self.assertEqual(checked.value.review.changes[0].status, "unchanged")
            no_op = service.finalize(checked.value, checked.value.review.review_digest)
            assert isinstance(no_op, Ok), no_op
            self.assertEqual(no_op.value.status, "no-op")

            for action in (CurationAction.LOCK, CurationAction.BUILD):
                with self.subTest(action=action):
                    generated = service.prepare(CurationRequest(action, str(root)))
                    assert isinstance(generated, Ok), generated
                    generated_outcome = service.finalize(
                        generated.value,
                        generated.value.review.review_digest,
                    )
                    assert isinstance(generated_outcome, Ok), generated_outcome
            audit = service.prepare(CurationRequest(CurationAction.AUDIT, str(root)))
            assert isinstance(audit, Ok), audit
            self.assertIn("security evidence", " ".join(audit.value.review.warnings))

            marker = root / "aart-registry.json"
            marker.write_bytes(marker.read_bytes() + b" ")
            diff = service.prepare(CurationRequest(CurationAction.DIFF, str(root)))
            assert isinstance(diff, Ok), diff
            self.assertTrue(any(item.status == "changed" for item in diff.value.review.changes))
            observed = service.finalize(diff.value, diff.value.review.review_digest)
            assert isinstance(observed, Ok), observed
            self.assertEqual(observed.value.changed_paths, 0)
            self.assertGreater(observed.value.observed_paths, 0)
            self.assertTrue(marker.read_bytes().endswith(b" "))

            reviewed_update = service.prepare(
                CurationRequest(
                    CurationAction.REFRESH_NATIVE,
                    str(root),
                    kind="skill",
                    name="code-review",
                )
            )
            assert isinstance(reviewed_update, Ok), reviewed_update
            workflow = root / ".github/workflows/aart-registry.yml"
            workflow_before = workflow.read_bytes()
            workflow.write_bytes(workflow_before + b"\n")
            stale_whole_snapshot = service.finalize(
                reviewed_update.value,
                reviewed_update.value.review.review_digest,
            )
            self.assertIsInstance(stale_whole_snapshot, Err)
            workflow.write_bytes(workflow_before)

            reviewed_update = service.prepare(
                CurationRequest(
                    CurationAction.REFRESH_NATIVE,
                    str(root),
                    kind="skill",
                    name="code-review",
                )
            )
            assert isinstance(reviewed_update, Ok), reviewed_update
            entry = root / "entries/skill/code-review.json"
            entry.write_bytes(entry.read_bytes() + b" ")
            stale_update = service.finalize(
                reviewed_update.value,
                reviewed_update.value.review.review_digest,
            )
            self.assertIsInstance(stale_update, Err)

            mismatched = root / "entries/skill/wrong.json"
            mismatched.write_bytes(entry.read_bytes())
            invalid_identity = service.prepare(CurationRequest(CurationAction.LOCK, str(root)))
            self.assertIsInstance(invalid_identity, Err)

    def test_promote_rejects_retired_setup_v1_before_registry_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "registry"
            _git_checkout(root)
            service = LocalCurationService(
                str(root),
                native_acquirer=lambda url, ref: Ok(
                    NativeReferenceAcquisition(url, ref, "a" * 40, _setup_v1_native_snapshot())
                ),
            )
            initialized = service.prepare(
                CurationRequest(
                    CurationAction.INIT,
                    str(root),
                    source_id="test-registry",
                    display_name="Test Registry",
                )
            )
            assert isinstance(initialized, Ok), initialized
            assert isinstance(
                service.finalize(initialized.value, initialized.value.review.review_digest), Ok
            )

            promoted = service.prepare(
                CurationRequest(
                    CurationAction.PROMOTE_NATIVE,
                    str(root),
                    kind="skill",
                    name="code-review",
                    url="https://github.com/example/reference-skills.git",
                    path="artifacts/skill/code-review",
                )
            )

            self.assertIsInstance(promoted, Err)
            self.assertFalse((root / "entries" / "skill" / "code-review.json").exists())


if __name__ == "__main__":
    unittest.main()
