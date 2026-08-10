"""SET01: canonical-object, trust, policy, queue, and state setup boundary."""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from unittest.mock import patch

from agent_artifacts.configuration.model import (
    OrganizationPolicy,
    ReportingSettings,
    SourceKind,
    SyncSettings,
    UserConfiguration,
)
from agent_artifacts.configuration.policy import RuntimeOverrides, apply_configuration
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import ArtifactCoordinate, ArtifactIdentity, SourceAlias
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.install_state.model import (
    ArtifactEvidence,
    EffectProof,
    InstallationRecord,
    InstallState,
    SourceEvidence,
)
from agent_artifacts.install_state.paths import install_state_paths
from agent_artifacts.install_state.schema import install_state_bytes, parse_install_state
from agent_artifacts.installation.io import _write_atomic
from agent_artifacts.installation.model import InstallLocation
from agent_artifacts.io.object_store import publish_object
from agent_artifacts.io.reference_store import read_references
from agent_artifacts.marketplace.catalog import build_marketplace
from agent_artifacts.model import SetupState
from agent_artifacts.protocol.capabilities import Capability
from agent_artifacts.protocol.hashing import file_entry, json_digest, sha256_bytes, tree_digest
from agent_artifacts.protocol.json import canonical_json_bytes
from agent_artifacts.protocol.native_models import (
    ArtifactManifest,
    CompatibilitySpec,
    InstallSpec,
    PayloadSpec,
    SetupReference,
)
from agent_artifacts.protocol.native_schema import artifact_manifest_to_json
from agent_artifacts.protocol.native_tree import SnapshotEntry, SnapshotEntryKind
from agent_artifacts.protocol.paths import SafeRelativePath
from agent_artifacts.protocol.registry_models import IndexArtifact, IndexSetup, ReviewRecord
from agent_artifacts.protocol.semver import SemVer
from agent_artifacts.setup import dump_setup_state
from agent_artifacts.setup_engine import (
    LocalSetupAdapter,
    PayloadStatus,
    SetupExecutionStatus,
    SetupRequest,
    execute_setup_queue,
    finalize_setup,
    prepare_setup,
    retryable_plans,
    rollback_setup,
    setup_outcome_event,
)
from agent_artifacts.setup_runtime import ProcessResult, SetupRuntime
from agent_artifacts.store.model import (
    ObjectPublishCommand,
    ReferenceKind,
    ReferenceReadRequest,
    make_object_candidate,
    object_store_paths,
)
from tests.marketplace_fixtures import configured_source, graph, source_state


def _path(raw: str) -> SafeRelativePath:
    return SafeRelativePath(tuple(raw.split("/")))


def _recipe(*, custom: bool = False, secret_failure: bool = False) -> bytes:
    capabilities = ["process"] if secret_failure else ["filesystem"]
    steps: list[dict[str, object]] = (
        [
            {
                "id": "verify",
                "use": "command.verify@1",
                "with": {"argv": ["verify-tool"]},
            }
        ]
        if secret_failure
        else [
            {
                "id": "config",
                "use": "file.managed-block@1",
                "with": {"file": ".setup-config", "content": "enabled=true"},
            }
        ]
    )
    if custom:
        capabilities.extend(("custom-code", "process"))
    value: dict[str, object] = {
        "schema_version": 1,
        "protocol_version": 1,
        "artifact": "skill/review",
        "purpose": "Configure the reviewed skill.",
        "platforms": ["darwin"],
        "help_urls": [{"label": "Setup help", "url": "https://example.test/setup"}],
        "required_tools": [],
        "capabilities": list(dict.fromkeys(capabilities)),
        "inputs": [],
        "steps": steps,
    }
    if custom:
        value["custom_entrypoint"] = "install.sh"
    return json.dumps(value, sort_keys=True).encode()


def _effective(source, policy: OrganizationPolicy):
    result = apply_configuration(
        UserConfiguration(1, (source,), None, SyncSettings(), ReportingSettings()),
        RuntimeOverrides(),
        policy,
    )
    assert isinstance(result, Ok), result
    return result.value


class Fixture:
    def __init__(
        self,
        root: Path,
        *,
        source_kind: SourceKind = SourceKind.SOURCE_GIT,
        reviewed: bool = False,
        policy: OrganizationPolicy | None = None,
        custom: bool = False,
        secret_failure: bool = False,
        profiles: tuple[str, ...] = ("claude",),
        setup_platforms: tuple[str, ...] = ("darwin",),
    ) -> None:
        self.project = root / "project"
        self.home = root / "home"
        self.data = root / "data"
        self.project.mkdir()
        self.home.mkdir()
        self.location = InstallLocation(str(self.project), str(self.home), str(self.data))
        self.paths = object_store_paths(str(self.data))
        self.source = configured_source("registry", source_kind)
        self.policy = policy or OrganizationPolicy(1)
        self.effective = _effective(self.source, self.policy)
        recipe = _recipe(custom=custom, secret_failure=secret_failure)
        script = b"#!/bin/sh\nexit 0\n"
        manifest = ArtifactManifest(
            1,
            ArtifactIdentity("skill", "review"),
            SemVer(1, 0, 0),
            "Use review to improve agent work.",
            PayloadSpec(_path("payload"), "aart-skill-v1"),
            CompatibilitySpec(profiles, ("darwin",)),
            InstallSpec(("project",), ("copy",), ("copy-tree",)),
            SetupReference(_path("setup/installer.json"), setup_platforms),
        )
        entries = [
            SnapshotEntry(
                _path("artifact.json"),
                SnapshotEntryKind.FILE,
                canonical_json_bytes(artifact_manifest_to_json(manifest)),
            ),
            SnapshotEntry(_path("payload/SKILL.md"), SnapshotEntryKind.FILE, b"# Review\n"),
            SnapshotEntry(_path("setup/installer.json"), SnapshotEntryKind.FILE, recipe),
        ]
        if custom:
            entries.append(
                SnapshotEntry(_path("setup/install.sh"), SnapshotEntryKind.FILE, script, True)
            )
        candidate = make_object_candidate(entries)
        assert isinstance(candidate, Ok), candidate
        self.candidate = candidate.value
        published = publish_object(ObjectPublishCommand(self.paths, self.candidate))
        assert isinstance(published, Ok), published
        payload = tree_digest((file_entry(_path("SKILL.md"), b"# Review\n"),))
        assert isinstance(payload, Ok), payload
        indexed_capabilities = (
            (Capability("verify-command"),)
            if secret_failure
            else (
                (Capability("custom-code"), Capability("managed-file"))
                if custom
                else (Capability("managed-file"),)
            )
        )
        index_setup = IndexSetup(
            _path("setup/installer.json"),
            setup_platforms,
            indexed_capabilities,
        )
        self.indexed = IndexArtifact(
            self.source_id,
            manifest.identity,
            manifest.version,
            manifest.summary,
            json_digest(artifact_manifest_to_json(manifest)),
            payload.value,
            self.candidate.digest,
            manifest.compatibility,
            manifest.install,
            setup=index_setup,
            review=ReviewRecord("approved", "company-v1") if reviewed else None,
        )
        self.catalog = self._catalog(self.indexed)
        item = self.catalog.items[0]
        source = SourceEvidence(
            item.source.alias,
            item.source.source_id,
            item.source.kind,
            item.source.origin,
            item.source.resolved_revision,
            self.source.ref,
        )
        artifact = ArtifactEvidence(
            self.indexed.identity,
            self.indexed.version,
            self.indexed.manifest_digest,
            self.indexed.payload_digest,
            self.indexed.object_digest,
        )
        records = tuple(
            InstallationRecord(
                ArtifactCoordinate(SourceAlias("registry"), manifest.identity),
                source,
                artifact,
                profile,
                1,
                "project",
                "copy",
                (
                    EffectProof(
                        "copy-tree",
                        f".claude/skills/review-{profile}",
                        "copy",
                        payload.value,
                        source_path="payload",
                    ),
                ),
            )
            for profile in profiles
        )
        state_paths = install_state_paths(
            "project",
            project_root=str(self.project),
            user_home=str(self.home),
            data_root=str(self.data),
        )
        _write_atomic(
            Path(state_paths.destination_path), install_state_bytes(InstallState(2, records))
        )
        self.adapter = LocalSetupAdapter()

    @property
    def source_id(self):
        from agent_artifacts.domain.identifiers import SourceId

        return SourceId("review-registry")

    def _catalog(self, indexed: IndexArtifact):
        result = build_marketplace(
            graph((self.source, self.source_id.value, (indexed,))),
            self.effective,
            (source_state(self.source, self.source_id.value, display_order=0),),
        )
        assert isinstance(result, Ok), result
        return result.value

    def request(self, profile: str = "claude", **changes: bool) -> SetupRequest:
        return SetupRequest(
            ArtifactCoordinate(SourceAlias("registry"), ArtifactIdentity("skill", "review")),
            profile,
            "project",
            authorize_untrusted_source=changes.get("authorize_untrusted_source", False),
            authorize_custom_entrypoint=changes.get("authorize_custom_entrypoint", False),
            platform="linux" if changes.get("linux", False) else "darwin",
        )

    def plan(self, profile: str = "claude", **changes: bool):
        return prepare_setup(
            self.request(profile, **changes),
            self.catalog,
            self.effective,
            self.location,
            self.paths,
            self.adapter,
        )


class RecordingProcess:
    def __init__(self, *, failure: bool = False) -> None:
        self.failure = failure
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv, *, env, cwd, timeout, capture):
        args = tuple(argv)
        self.calls.append(args)
        if self.failure and args and args[0] == "verify-tool":
            return ProcessResult(1, "", "api_key=synthetic-canary")
        return ProcessResult(0)


class CustomProtocolProcess(RecordingProcess):
    def __call__(self, argv, *, env, cwd, timeout, capture):
        result = super().__call__(argv, env=env, cwd=cwd, timeout=timeout, capture=capture)
        args = tuple(argv)
        if args and args[0].endswith("install.sh"):
            phase = args[1]
            result_path = Path(args[args.index("--result") + 1])
            status = {"plan": "planned", "apply": "configured", "verify": "verified"}[phase]
            result_path.write_text(
                json.dumps({"status": status, "detail": f"{phase} complete", "reversible": True}),
                encoding="utf-8",
            )
        return result


def _runtime(process: RecordingProcess | None = None) -> SetupRuntime:
    return SetupRuntime(
        process=process or RecordingProcess(),
        platform="darwin",
        environ={},
        tool_exists=lambda _tool: True,
        clock=lambda: "2026-08-10T00:00:00Z",
        enforce_source_hash=True,
    )


class MissingObjectAdapter(LocalSetupAdapter):
    def read_object(self, request):
        return Ok(None)


class CanonicalSetupApplicationTest(unittest.TestCase):
    def test_direct_source_requires_explicit_authorization_and_plan_binds_every_identity(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = Fixture(Path(raw))

            denied = fixture.plan()
            planned = fixture.plan(authorize_untrusted_source=True)

            self.assertIsInstance(denied, Err)
            assert isinstance(denied, Err)
            self.assertEqual(denied.diagnostics[0].code.value, "setup-policy-denied")
            self.assertIsInstance(planned, Ok)
            assert isinstance(planned, Ok)
            plan = planned.value
            self.assertEqual(plan.object_digest, fixture.candidate.digest)
            self.assertEqual(str(plan.recipe_path), "setup/installer.json")
            self.assertEqual(plan.recipe_digest, sha256_bytes(_recipe()))
            self.assertEqual(tuple(str(item) for item in plan.capabilities), ("managed-file",))
            self.assertEqual(plan.legacy_plan.item.source_root, plan.object_root)
            self.assertNotEqual(plan.review_digest, plan.capability_plan_digest)
            with self.assertRaises(ValueError):
                replace(plan, recipe_digest=sha256_bytes(b"different recipe"))
            with self.assertRaises(ValueError):
                replace(plan, review_digest=sha256_bytes(b"different review"))
            with self.assertRaises(ValueError):
                replace(plan, setup_state_path="/tmp/outside-managed-data.json")
            with self.assertRaises(FrozenInstanceError):
                plan.trust = "company-reviewed"  # type: ignore[misc]

    def test_policy_denies_capability_and_custom_entrypoint_before_execution(self) -> None:
        denied_policy = OrganizationPolicy(
            1,
            allowed_setup_capabilities=(Capability("keychain"),),
        )
        custom_policy = OrganizationPolicy(1, allow_custom_setup_entrypoints=False)
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            capability = Fixture(Path(first), policy=denied_policy)
            custom = Fixture(Path(second), policy=custom_policy, custom=True)

            denied_capability = capability.plan(authorize_untrusted_source=True)
            denied_custom = custom.plan(
                authorize_untrusted_source=True,
                authorize_custom_entrypoint=True,
            )

            self.assertIsInstance(denied_capability, Err)
            self.assertIn("managed-file", denied_capability.diagnostics[0].message)
            self.assertIsInstance(denied_custom, Err)
            self.assertIn("custom", denied_custom.diagnostics[0].message)

    def test_custom_entrypoint_needs_explicit_authorization_even_without_a_policy_denial(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = Fixture(Path(raw), custom=True)

            denied = fixture.plan(authorize_untrusted_source=True)

            self.assertIsInstance(denied, Err)
            assert isinstance(denied, Err)
            self.assertIn("explicit authorization", denied.diagnostics[0].message)

    def test_prepare_requires_installed_state_cached_object_and_matching_index_capabilities(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = Fixture(Path(raw))
            state_path = install_state_paths(
                "project",
                project_root=str(fixture.project),
                user_home=str(fixture.home),
                data_root=str(fixture.data),
            ).destination_path
            Path(state_path).unlink()
            missing_state = fixture.plan(authorize_untrusted_source=True)
            self.assertIsInstance(missing_state, Err)
            self.assertIn("installed payload", missing_state.diagnostics[0].message)

        with tempfile.TemporaryDirectory() as raw:
            fixture = Fixture(Path(raw))
            missing_object = prepare_setup(
                fixture.request(authorize_untrusted_source=True),
                fixture.catalog,
                fixture.effective,
                fixture.location,
                fixture.paths,
                MissingObjectAdapter(),
            )
            self.assertIsInstance(missing_object, Err)
            self.assertEqual(missing_object.diagnostics[0].code.value, "setup-object-unavailable")

            assert fixture.indexed.setup is not None
            mismatched_index = replace(
                fixture.indexed,
                setup=replace(
                    fixture.indexed.setup,
                    capabilities=(Capability("keychain"),),
                ),
            )
            mismatched = prepare_setup(
                fixture.request(authorize_untrusted_source=True),
                fixture._catalog(mismatched_index),
                fixture.effective,
                fixture.location,
                fixture.paths,
                fixture.adapter,
            )
            self.assertIsInstance(mismatched, Err)
            self.assertIn("capability evidence", mismatched.diagnostics[0].message)

    def test_prepare_rejects_missing_selection_and_corrupt_prior_setup_state(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = Fixture(Path(raw))
            missing = fixture.plan("tabnine", authorize_untrusted_source=True)
            self.assertIsInstance(missing, Err)
            self.assertIn("artifact/profile", missing.diagnostics[0].message)

            planned = fixture.plan(authorize_untrusted_source=True)
            assert isinstance(planned, Ok), planned
            setup_state = Path(planned.value.setup_state_path)
            setup_state.parent.mkdir(parents=True)
            setup_state.write_text("not-json", encoding="utf-8")

            corrupt = fixture.plan(authorize_untrusted_source=True)
            self.assertIsInstance(corrupt, Err)
            self.assertIn("setup state is invalid", corrupt.diagnostics[0].message)

    def test_prepare_rejects_marketplace_whose_source_is_no_longer_configured(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = Fixture(Path(raw))
            without_source = replace(
                fixture.effective,
                configuration=replace(fixture.effective.configuration, sources=()),
            )

            result = prepare_setup(
                fixture.request(authorize_untrusted_source=True),
                fixture.catalog,
                without_source,
                fixture.location,
                fixture.paths,
                fixture.adapter,
            )

            self.assertIsInstance(result, Err)
            self.assertIn("no longer matches", result.diagnostics[0].message)

    def test_unsupported_setup_platform_declaration_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = Fixture(Path(raw), setup_platforms=("linux",))

            result = fixture.plan(authorize_untrusted_source=True)

            self.assertIsInstance(result, Err)
            self.assertIn("manifest is invalid", result.diagnostics[0].message)

    def test_trust_downgrade_after_review_is_terminal_and_non_mutating(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = Fixture(Path(raw), source_kind=SourceKind.REGISTRY_GIT, reviewed=True)
            planned = fixture.plan()
            assert isinstance(planned, Ok), planned
            downgraded = fixture._catalog(replace(fixture.indexed, review=None))
            process = RecordingProcess()

            outcome = finalize_setup(
                planned.value,
                planned.value.review_digest,
                downgraded,
                fixture.effective,
                fixture.adapter,
                _runtime(process),
                consent=lambda _effect: True,
            )

            self.assertIsInstance(outcome, Ok)
            assert isinstance(outcome, Ok)
            self.assertIs(outcome.value.payload_status, PayloadStatus.INSTALLED)
            self.assertIs(outcome.value.setup_status, SetupExecutionStatus.CONFLICTED)
            self.assertEqual(process.calls, [])
            self.assertFalse((fixture.project / ".setup-config").exists())

    def test_requested_platform_is_review_bound_and_non_macos_is_terminal_without_effects(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = Fixture(Path(raw))
            planned = fixture.plan(authorize_untrusted_source=True, linux=True)
            assert isinstance(planned, Ok), planned
            self.assertEqual(planned.value.request.platform, "linux")
            self.assertEqual(planned.value.legacy_plan.preflight_status, "unsupported")

            outcome = finalize_setup(
                planned.value,
                planned.value.review_digest,
                fixture.catalog,
                fixture.effective,
                fixture.adapter,
                replace(_runtime(), platform="linux"),
                consent=lambda _effect: True,
            )

            self.assertIsInstance(outcome, Ok)
            assert isinstance(outcome, Ok)
            self.assertIs(outcome.value.setup_status, SetupExecutionStatus.UNSUPPORTED)
            self.assertFalse((fixture.project / ".setup-config").exists())

    def test_finalize_persists_separate_setup_outcome_state_and_object_reference(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = Fixture(Path(raw))
            planned = fixture.plan(authorize_untrusted_source=True)
            assert isinstance(planned, Ok), planned

            outcome = finalize_setup(
                planned.value,
                planned.value.review_digest,
                fixture.catalog,
                fixture.effective,
                fixture.adapter,
                _runtime(),
                consent=lambda _effect: True,
            )

            self.assertIsInstance(outcome, Ok)
            assert isinstance(outcome, Ok)
            self.assertIs(outcome.value.payload_status, PayloadStatus.INSTALLED)
            self.assertIs(outcome.value.setup_status, SetupExecutionStatus.CONFIGURED)
            self.assertTrue(outcome.value.state_written)
            self.assertTrue((fixture.project / ".setup-config").exists())
            state_path = install_state_paths(
                "project",
                project_root=str(fixture.project),
                user_home=str(fixture.home),
                data_root=str(fixture.data),
            ).destination_path
            state = parse_install_state(Path(state_path).read_bytes(), path=state_path)
            assert isinstance(state, Ok), state
            self.assertEqual(
                state.value.installations[0].setup_state_ref,
                planned.value.setup_state_ref,
            )
            self.assertTrue(Path(planned.value.setup_state_path).is_file())
            references = read_references(ReferenceReadRequest(fixture.paths))
            assert isinstance(references, Ok), references
            self.assertIn(
                (
                    ReferenceKind.SETUP,
                    planned.value.setup_reference_owner,
                    fixture.candidate.digest,
                ),
                tuple((item.kind, item.owner, item.digest) for item in references.value.references),
            )

    def test_finalize_rejects_wrong_review_and_compensates_reference_persistence_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = Fixture(Path(raw))
            planned = fixture.plan(authorize_untrusted_source=True)
            assert isinstance(planned, Ok), planned

            wrong_review = finalize_setup(
                planned.value,
                sha256_bytes(b"wrong review"),
                fixture.catalog,
                fixture.effective,
                fixture.adapter,
                _runtime(),
                consent=lambda _effect: True,
            )
            self.assertIsInstance(wrong_review, Err)
            self.assertFalse((fixture.project / ".setup-config").exists())

            failure = Err(
                (
                    Diagnostic(
                        DiagnosticCode("synthetic-reference-failure"),
                        Severity.ERROR,
                        "reference write failed",
                    ),
                )
            )
            with patch(
                "agent_artifacts.setup_engine.io._replace_setup_reference",
                return_value=failure,
            ):
                outcome = finalize_setup(
                    planned.value,
                    planned.value.review_digest,
                    fixture.catalog,
                    fixture.effective,
                    fixture.adapter,
                    _runtime(),
                    consent=lambda _effect: True,
                )

            self.assertIsInstance(outcome, Ok)
            assert isinstance(outcome, Ok)
            self.assertIs(outcome.value.setup_status, SetupExecutionStatus.FAILED)
            self.assertFalse(outcome.value.state_written)
            self.assertFalse((fixture.project / ".setup-config").exists())
            self.assertFalse(Path(planned.value.setup_state_path).exists())

    def test_custom_entrypoint_executes_only_from_private_digest_verified_copy(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = Fixture(Path(raw), custom=True)
            planned = fixture.plan(
                authorize_untrusted_source=True,
                authorize_custom_entrypoint=True,
            )
            assert isinstance(planned, Ok), planned
            process = CustomProtocolProcess()
            with self.assertRaises(ValueError):
                replace(planned.value, custom_entrypoint_path=_path("setup/other.sh"))

            outcome = finalize_setup(
                planned.value,
                planned.value.review_digest,
                fixture.catalog,
                fixture.effective,
                fixture.adapter,
                _runtime(process),
                consent=lambda _effect: True,
            )

            self.assertIsInstance(outcome, Ok)
            assert isinstance(outcome, Ok)
            self.assertIs(outcome.value.setup_status, SetupExecutionStatus.CONFIGURED)
            custom_calls = [call for call in process.calls if call[0].endswith("install.sh")]
            self.assertEqual([call[1] for call in custom_calls], ["plan", "apply", "verify"])
            copied = Path(custom_calls[0][0])
            self.assertTrue(all(Path(call[0]) == copied for call in custom_calls))
            self.assertTrue(copied.is_relative_to(fixture.data / ".agent-artifacts/setup-runs"))
            self.assertFalse(copied.is_relative_to(Path(planned.value.object_root)))
            self.assertEqual(
                sha256_bytes(copied.read_bytes()), planned.value.custom_entrypoint_digest
            )

    def test_queue_stop_retry_and_rollback_preserve_per_item_terminal_outcomes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = Fixture(Path(raw), profiles=("claude", "tabnine"))
            first = fixture.plan("claude", authorize_untrusted_source=True)
            second = fixture.plan("tabnine", authorize_untrusted_source=True)
            assert isinstance(first, Ok) and isinstance(second, Ok)
            approvals = iter((False, True))

            stopped = execute_setup_queue(
                (first.value, second.value),
                (first.value.review_digest, second.value.review_digest),
                fixture.catalog,
                fixture.effective,
                fixture.adapter,
                _runtime(),
                consent=lambda _effect: next(approvals),
                stop_on_failure=True,
            )

            self.assertEqual(
                tuple(item.setup_status for item in stopped.items),
                (SetupExecutionStatus.CANCELLED, SetupExecutionStatus.SKIPPED),
            )
            self.assertEqual(stopped.payload_installed, 2)
            self.assertEqual(
                retryable_plans((first.value, second.value), stopped), (first.value, second.value)
            )

            retried_first = fixture.plan("claude", authorize_untrusted_source=True)
            assert isinstance(retried_first, Ok), retried_first
            retried = execute_setup_queue(
                (retried_first.value,),
                (retried_first.value.review_digest,),
                fixture.catalog,
                fixture.effective,
                fixture.adapter,
                _runtime(),
                consent=lambda _effect: True,
            )
            self.assertIs(retried.items[0].setup_status, SetupExecutionStatus.CONFIGURED)

            rolled = rollback_setup(
                retried_first.value,
                retried.items[0],
                fixture.adapter,
                _runtime(),
            )
            self.assertIsInstance(rolled, Ok)
            assert isinstance(rolled, Ok)
            self.assertIs(rolled.value.setup_status, SetupExecutionStatus.ROLLED_BACK)
            self.assertFalse((fixture.project / ".setup-config").exists())

            rejected_again = rollback_setup(
                retried_first.value,
                rolled.value,
                fixture.adapter,
                _runtime(),
            )
            self.assertIsInstance(rejected_again, Err)
            self.assertIn("review-bound", rejected_again.diagnostics[0].message)

    def test_rollback_rejects_tampered_receipts_and_changed_durable_state_before_mutation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = Fixture(Path(raw))
            planned = fixture.plan(authorize_untrusted_source=True)
            assert isinstance(planned, Ok), planned
            configured = finalize_setup(
                planned.value,
                planned.value.review_digest,
                fixture.catalog,
                fixture.effective,
                fixture.adapter,
                _runtime(),
                consent=lambda _effect: True,
            )
            assert isinstance(configured, Ok) and configured.value.record is not None
            receipt = dict(configured.value.record.receipt[0])
            receipt["path"] = str(fixture.project / "unreviewed-target")
            tampered_record = replace(configured.value.record, receipt=(receipt,))
            tampered_outcome = replace(configured.value, record=tampered_record)

            rejected_receipt = rollback_setup(
                planned.value,
                tampered_outcome,
                fixture.adapter,
                _runtime(),
            )

            self.assertIsInstance(rejected_receipt, Err)
            self.assertTrue((fixture.project / ".setup-config").exists())

            changed_record = replace(configured.value.record, detail="Changed after Review")
            Path(planned.value.setup_state_path).write_text(
                dump_setup_state(SetupState((changed_record,))) + "\n",
                encoding="utf-8",
            )
            rejected_state = rollback_setup(
                planned.value,
                configured.value,
                fixture.adapter,
                _runtime(),
            )
            self.assertIsInstance(rejected_state, Err)
            self.assertTrue((fixture.project / ".setup-config").exists())

    def test_queue_continues_after_failure_without_losing_an_earlier_success(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = Fixture(Path(raw), profiles=("claude", "tabnine"))
            first = fixture.plan("claude", authorize_untrusted_source=True)
            second = fixture.plan("tabnine", authorize_untrusted_source=True)
            assert isinstance(first, Ok) and isinstance(second, Ok)
            approvals = iter((True, False))

            outcome = execute_setup_queue(
                (first.value, second.value),
                (first.value.review_digest, second.value.review_digest),
                fixture.catalog,
                fixture.effective,
                fixture.adapter,
                _runtime(),
                consent=lambda _effect: next(approvals),
            )

            self.assertEqual(
                tuple(item.setup_status for item in outcome.items),
                (SetupExecutionStatus.CONFIGURED, SetupExecutionStatus.CANCELLED),
            )
            self.assertEqual(outcome.configured, 1)
            self.assertEqual(outcome.incomplete, 1)
            self.assertTrue(outcome.items[0].state_written)
            self.assertTrue(outcome.items[1].state_written)

    def test_queue_requires_one_review_per_plan_and_maps_review_errors_to_terminal_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = Fixture(Path(raw))
            planned = fixture.plan(authorize_untrusted_source=True)
            assert isinstance(planned, Ok), planned

            with self.assertRaisesRegex(ValueError, "reviewed digest"):
                execute_setup_queue(
                    (planned.value,),
                    (),
                    fixture.catalog,
                    fixture.effective,
                    fixture.adapter,
                    _runtime(),
                    consent=lambda _effect: True,
                )
            failed = execute_setup_queue(
                (planned.value,),
                (sha256_bytes(b"wrong review"),),
                fixture.catalog,
                fixture.effective,
                fixture.adapter,
                _runtime(),
                consent=lambda _effect: True,
            )
            self.assertIs(failed.items[0].setup_status, SetupExecutionStatus.FAILED)
            self.assertFalse(failed.items[0].state_written)

    def test_secret_shaped_failure_is_redacted_from_state_outcome_and_event(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = Fixture(Path(raw), secret_failure=True)
            planned = fixture.plan(authorize_untrusted_source=True)
            assert isinstance(planned, Ok), planned

            outcome = finalize_setup(
                planned.value,
                planned.value.review_digest,
                fixture.catalog,
                fixture.effective,
                fixture.adapter,
                _runtime(RecordingProcess(failure=True)),
                consent=lambda _effect: True,
            )

            self.assertIsInstance(outcome, Ok)
            assert isinstance(outcome, Ok)
            event = setup_outcome_event(outcome.value)
            state_bytes = Path(planned.value.setup_state_path).read_bytes()
            self.assertNotIn("synthetic-canary", repr(outcome.value))
            self.assertNotIn("synthetic-canary", repr(event))
            self.assertNotIn(b"synthetic-canary", state_bytes)
            self.assertNotIn("receipt", event)


if __name__ == "__main__":
    unittest.main()
