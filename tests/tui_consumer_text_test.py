from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from agent_artifacts import tui
from agent_artifacts.compiler import CollectionCoordinate, MarketplaceCollection
from agent_artifacts.configuration.model import OrganizationPolicy, ReportingMode
from agent_artifacts.consumer import (
    ConsumerActionRequest,
    ConsumerApplicationService,
    ConsumerContext,
    LocalConsumerAdapter,
)
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.profiles.builtin import builtin
from agent_artifacts.protocol.capabilities import Capability
from agent_artifacts.reporting.application import ReportingApplicationService
from agent_artifacts.reporting.model import ReportingDestination
from agent_artifacts.reporting.projection import usage_report_from_consumer
from agent_artifacts.tui_sources import build_source_stage
from agent_artifacts.wizard import BasketItem, WizardSession
from tests.canonical_setup_application_test import Fixture as SetupFixture
from tests.canonical_symlink_test import _fixture
from tests.marketplace_fixtures import source_state

_INSTALL_STATE_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "install-state"


def _scripted(answers, prompts=None):
    values = iter(answers)

    def read(_prompt=""):
        if prompts is not None:
            prompts.append(_prompt)
        try:
            return next(values)
        except StopIteration:
            raise EOFError from None

    return read


def _tree_snapshot(root: Path) -> tuple[tuple[str, bytes], ...]:
    """Read-only test evidence that a failure path did not mutate an owned tree."""

    if not root.exists():
        return ()
    return tuple(
        (path.relative_to(root).as_posix(), path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    )


class TuiConsumerTextTest(unittest.TestCase):
    def test_err06_review_prepare_failure_is_a_record_and_back_returns_to_artifacts(self) -> None:
        session = WizardSession(
            current="artifacts",
            role="user",
            action="install",
            profiles=("claude",),
            scope="project",
        )
        service = mock.Mock()
        service.context.catalog.collections = ()
        service.prepare.return_value = Err(
            (
                Diagnostic(
                    DiagnosticCode("install-conflict"),
                    Severity.ERROR,
                    "the reviewed artifact plan is stale",
                    remediation=("return to Artifacts and choose current entries",),
                ),
            )
        )
        recovered = Ok(
            tui._UserWizardReadModel(
                (tui._Choice("artifact", "review", "skill", "review"),),
                {},
            )
        )
        writes: list[str] = []

        with (
            mock.patch.object(tui, "_load_user_wizard_read_model", return_value=recovered),
            mock.patch.object(tui, "ConsumerActionRequest", return_value=object()),
        ):
            code = tui._run_user_text_wizard(
                session,
                _scripted(["1", "b", "q", "y"]),
                writes.append,
                source_factory=mock.Mock(),
                source_dir=None,
                repo=None,
                project="/work/project",
                user_home=None,
                consumer_service=service,
            )

        self.assertEqual(code, 0)
        rendered = "\n".join(writes)
        self.assertIn("Review could not be reviewed", rendered)
        self.assertIn("error [install-conflict]", rendered)
        self.assertIn("Back = b", rendered)
        self.assertIn("Select artifact(s)/collection(s)", rendered)
        service.prepare.assert_called_once()

    def test_err06_finalize_failure_is_a_record_and_back_returns_to_artifacts(self) -> None:
        session = WizardSession(
            current="artifacts",
            role="user",
            action="install",
            profiles=("claude",),
            scope="project",
        )
        review = mock.Mock(review_digest=object())
        service = mock.Mock()
        service.context.catalog.collections = ()
        service.prepare.return_value = Ok(review)
        service.finalize.return_value = Err(
            (
                Diagnostic(
                    DiagnosticCode("install-conflict"),
                    Severity.ERROR,
                    "the reviewed artifact plan changed before finalization",
                    remediation=("return to Artifacts and review the current plan",),
                ),
            )
        )
        loaded = Ok(
            tui._UserWizardReadModel(
                (tui._Choice("artifact", "review", "skill", "review"),),
                {},
            )
        )
        writes: list[str] = []

        with (
            mock.patch.object(tui, "_load_user_wizard_read_model", return_value=loaded),
            mock.patch.object(tui, "ConsumerActionRequest", return_value=object()),
            mock.patch.object(tui, "render_consumer_review", return_value=()),
            mock.patch.object(tui, "can_finalize", return_value=True),
        ):
            code = tui._run_user_text_wizard(
                session,
                _scripted(["1", "y", "b", "q", "y"]),
                writes.append,
                source_factory=mock.Mock(),
                source_dir=None,
                repo=None,
                project="/work/project",
                user_home=None,
                consumer_service=service,
            )

        self.assertEqual(code, 0)
        rendered = "\n".join(writes)
        self.assertIn("Review could not be finalized", rendered)
        self.assertIn("error [install-conflict]", rendered)
        self.assertIn("Back = b", rendered)
        self.assertIn("Select artifact(s)/collection(s)", rendered)
        service.finalize.assert_called_once_with(review, review.review_digest)

    def test_err04_retry_reloads_only_artifacts_and_keeps_the_existing_basket(self) -> None:
        session = WizardSession(
            current="artifacts",
            action="install",
            profiles=("claude",),
            scope="project",
            basket=(BasketItem("artifact", "skill/review", "review"),),
        )
        failed = Err(
            (
                Diagnostic(
                    DiagnosticCode("install-state-legacy"),
                    Severity.ERROR,
                    "AART 0.1 installation state was detected.",
                ),
            )
        )
        recovered = Ok(
            tui._UserWizardReadModel(
                (tui._Choice("artifact", "review", "skill", "review"),),
                {},
            )
        )
        writes: list[str] = []

        with mock.patch.object(
            tui, "_load_user_wizard_read_model", side_effect=(failed, recovered)
        ) as load:
            code = tui._run_user_text_wizard(
                session,
                _scripted(["r", "q", "y"]),
                writes.append,
                source_factory=mock.Mock(),
                source_dir=None,
                repo=None,
                project="/work/project",
                user_home=None,
            )

        self.assertEqual(code, 0)
        self.assertEqual(load.call_count, 2)
        rendered = "\n".join(writes)
        self.assertIn("Retry = r", rendered)
        self.assertIn("Select artifact(s)/collection(s)", rendered)
        self.assertIn("Discard 1 selected basket item(s)?", rendered)

    def test_err03_canonical_loader_returns_the_original_domain_error_unchanged(self) -> None:
        diagnostic = Diagnostic(
            DiagnosticCode("install-state-legacy"),
            Severity.ERROR,
            "AART 0.1 installation state was detected.",
            details=(("detected_schema", "install-state-v0.1"),),
        )
        expected = Err((diagnostic,))
        service = mock.Mock()
        service.browse.return_value = expected
        session = WizardSession(
            current="artifacts",
            action="install",
            profiles=("claude",),
            scope="project",
        )

        loaded = tui._load_user_wizard_read_model(
            session,
            source_factory=mock.Mock(),
            source_dir=None,
            repo=None,
            project=None,
            user_home=None,
            consumer_service=service,
        )

        self.assertIs(loaded, expected)
        service.browse.assert_called_once()

    def test_err03_consumer_loader_reports_one_named_boundary_failure(self) -> None:
        """Without a canonical consumer service the wizard fails at one named boundary.

        The retired catalog source factory is never consulted as a fallback: a missing
        canonical service is an error to report, not a reason to read a legacy catalog.
        """

        source_factory = mock.Mock(return_value=tui.Err("legacy catalog could not open", code=7))
        session = WizardSession(
            current="artifacts",
            action="install",
            profiles=("claude",),
            scope="project",
        )

        loaded = tui._load_user_wizard_read_model(
            session,
            source_factory=source_factory,
            source_dir="/legacy/catalog",
            repo=None,
            project=None,
            user_home=None,
        )

        self.assertIsInstance(loaded, Err)
        assert isinstance(loaded, Err)
        self.assertEqual(
            loaded.diagnostics,
            (
                Diagnostic(
                    DiagnosticCode("canonical-consumer-unavailable"),
                    Severity.ERROR,
                    "the canonical consumer service is unavailable",
                    remediation=("configure and synchronize a canonical registry source",),
                ),
            ),
        )
        source_factory.assert_not_called()

    def test_err04_retired_project_state_renders_a_record_and_back_allows_user_scope_without_writes(
        self,
    ) -> None:
        """A project-only legacy state cannot block a user-scoped Artifacts view."""

        with tempfile.TemporaryDirectory() as raw:
            fixture = _fixture(Path(raw), "skill")
            project, _checkout, paths, location, _request, catalog, effective = fixture
            state_path = project / ".agent-artifacts" / "manifest.json"
            state_path.parent.mkdir()
            state_path.write_bytes(
                (_INSTALL_STATE_FIXTURES / "legacy-v01-manifest.json").read_bytes()
            )
            service = ConsumerApplicationService(
                ConsumerContext(catalog, effective, builtin(), location, paths),
                LocalConsumerAdapter(),
            )
            configured = effective.configuration.sources[0]
            stage = build_source_stage(
                effective.configuration,
                effective.policy,
                {
                    configured.alias: source_state(
                        configured, "direct-source", display_order=0
                    ).health
                },
                first_run=False,
            )
            assert isinstance(stage, Ok), stage
            before = (_tree_snapshot(project), _tree_snapshot(Path(paths.root)))
            writes: list[str] = []

            with mock.patch.object(tui.sys, "platform", "darwin"):
                code = tui._run_text(
                    _scripted(["", "1", "1", "1", "install", "1", "", "b", "b", "2", "", "q"]),
                    writes.append,
                    project=str(project),
                    source_stage_view=stage.value,
                    consumer_service=service,
                )

            self.assertEqual(code, 0)
            rendered = "\n".join(writes)
            compact = "".join(rendered.split())
            self.assertIn("Artifacts could not be loaded", rendered)
            self.assertIn("error [install-state-legacy]", rendered)
            self.assertIn(str(project), rendered)
            self.assertIn(str(state_path), compact)
            self.assertIn(
                "aartmarketplaceinstall<coordinate>--profile<name>",
                compact,
            )
            self.assertIn("Select artifact(s)/collection(s)", rendered)
            self.assertEqual((_tree_snapshot(project), _tree_snapshot(Path(paths.root))), before)

    def test_federated_collection_row_expands_to_members_before_review(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = _fixture(Path(raw), "skill")
            project, _checkout, paths, location, _request, catalog, effective = fixture
            member = catalog.items[0].coordinate
            catalog = replace(
                catalog,
                collections=(
                    MarketplaceCollection(
                        CollectionCoordinate(member.source, "starter"),
                        "Install the reviewed starter set.",
                        (member,),
                    ),
                ),
            )
            service = ConsumerApplicationService(
                ConsumerContext(catalog, effective, builtin(), location, paths),
                LocalConsumerAdapter(),
            )
            configured = effective.configuration.sources[0]
            state = source_state(configured, "direct-source", display_order=0)
            stage = build_source_stage(
                effective.configuration,
                effective.policy,
                {configured.alias: state.health},
                first_run=False,
            )
            assert isinstance(stage, Ok), stage
            writes = []

            with mock.patch.object(tui.sys, "platform", "darwin"):
                code = tui._run_text(
                    _scripted(["", "1", "1", "1", "install", "1", "", "2", "y"]),
                    writes.append,
                    project=str(project),
                    source_stage_view=stage.value,
                    consumer_service=service,
                )

            self.assertEqual(code, 0)
            rendered = "\n".join(writes)
            self.assertIn("direct/collection/starter", rendered)
            self.assertIn("Install outcome: succeeded", rendered)
            self.assertTrue((project / ".claude/skills/review/SKILL.md").exists())

    def test_canonical_setup_queue_has_separate_authorize_review_apply_feedback(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = SetupFixture(Path(raw))
            (fixture.project / ".agent-artifacts/manifest.json").unlink()
            service = ConsumerApplicationService(
                ConsumerContext(
                    fixture.catalog,
                    fixture.effective,
                    builtin(),
                    fixture.location,
                    fixture.paths,
                ),
                LocalConsumerAdapter(),
            )
            reviewed = service.prepare(
                ConsumerActionRequest(
                    "install",
                    (fixture.catalog.items[0].coordinate,),
                    ("claude",),
                )
            )
            assert isinstance(reviewed, Ok), reviewed
            payload = service.finalize(reviewed.value, reviewed.value.review_digest)
            assert isinstance(payload, Ok), payload
            writes = []

            with mock.patch.object(tui.sys, "platform", "darwin"):
                code = tui._run_canonical_setup_queue(
                    service,
                    reviewed.value,
                    payload.value,
                    # `s` is the answer that asks for the old behaviour: the full review, and a
                    # question per effect.  That is what this test is about, and it is now a
                    # keystroke rather than the only path through the screen (`#113`).
                    read=_scripted(["y", "s", "y"]),
                    write=writes.append,
                )

            self.assertEqual(code, 0)
            rendered = "\n".join(writes)
            self.assertIn("explicit permission", rendered)
            self.assertIn("Review setup queue", rendered)
            self.assertIn("Setup review:", rendered)
            self.assertNotIn(" -> ", rendered)
            # The item is bounded by its own rules, and the run is tallied once at the end.
            self.assertIn("setup 1/1 — START", rendered)
            self.assertIn("setup 1/1 — SUMMARY", rendered)
            self.assertIn("RUN SUMMARY", rendered)
            self.assertIn("selected    1", rendered)
            self.assertIn("configured  1", rendered)
            self.assertIn("incomplete  0", rendered)
            self.assertTrue((fixture.project / ".setup-config").exists())

    def test_canonical_decline_repeats_v2_manual_route_after_the_payload_is_installed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = SetupFixture(Path(raw), setup_version=2)
            (fixture.project / ".agent-artifacts/manifest.json").unlink()
            service = ConsumerApplicationService(
                ConsumerContext(
                    fixture.catalog,
                    fixture.effective,
                    builtin(),
                    fixture.location,
                    fixture.paths,
                ),
                LocalConsumerAdapter(),
            )
            reviewed = service.prepare(
                ConsumerActionRequest(
                    "install",
                    (fixture.catalog.items[0].coordinate,),
                    ("claude",),
                )
            )
            assert isinstance(reviewed, Ok), reviewed
            payload = service.finalize(reviewed.value, reviewed.value.review_digest)
            assert isinstance(payload, Ok), payload
            writes: list[str] = []

            code = tui._run_canonical_setup_queue(
                service,
                reviewed.value,
                payload.value,
                read=_scripted(["y", "n"]),
                write=writes.append,
            )

        self.assertEqual(code, 1)
        rendered = "\n".join(writes)
        self.assertIn(
            "Payload outcome: installed; installed payloads were not rolled back.", rendered
        )
        self.assertIn("Setup remains pending.", rendered)
        self.assertIn("Manual alternative", rendered)
        self.assertIn("SETUP.md", rendered)
        self.assertIn("No setup effect has run.", rendered)

    def test_canonical_planning_failure_keeps_a_verified_v2_manual_route(self) -> None:
        policy = OrganizationPolicy(1, allowed_setup_capabilities=(Capability("keychain"),))
        with tempfile.TemporaryDirectory() as raw:
            fixture = SetupFixture(Path(raw), policy=policy, setup_version=2)
            (fixture.project / ".agent-artifacts/manifest.json").unlink()
            service = ConsumerApplicationService(
                ConsumerContext(
                    fixture.catalog,
                    fixture.effective,
                    builtin(),
                    fixture.location,
                    fixture.paths,
                ),
                LocalConsumerAdapter(),
            )
            reviewed = service.prepare(
                ConsumerActionRequest(
                    "install",
                    (fixture.catalog.items[0].coordinate,),
                    ("claude",),
                )
            )
            assert isinstance(reviewed, Ok), reviewed
            payload = service.finalize(reviewed.value, reviewed.value.review_digest)
            assert isinstance(payload, Ok), payload
            writes: list[str] = []

            code = tui._run_canonical_setup_queue(
                service,
                reviewed.value,
                payload.value,
                read=_scripted([]),
                write=writes.append,
            )

        self.assertEqual(code, 1)
        rendered = "\n".join(writes)
        self.assertIn("Payload outcome: installed", rendered)
        self.assertIn("registry/skill/review@1.0.0@claude (project)", rendered)
        self.assertIn("SUMMARY", rendered)
        self.assertIn("Manual alternative", rendered)
        self.assertIn("SETUP.md", rendered)
        self.assertIn("No setup effect has run.", rendered)

    def test_canonical_setup_reporting_reuses_versioned_consumer_identity(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = SetupFixture(Path(raw))
            (fixture.project / ".agent-artifacts/manifest.json").unlink()
            service = ConsumerApplicationService(
                ConsumerContext(
                    fixture.catalog,
                    fixture.effective,
                    builtin(),
                    fixture.location,
                    fixture.paths,
                ),
                LocalConsumerAdapter(),
            )
            reviewed = service.prepare(
                ConsumerActionRequest(
                    "install",
                    (fixture.catalog.items[0].coordinate,),
                    ("claude",),
                )
            )
            assert isinstance(reviewed, Ok), reviewed
            payload = service.finalize(reviewed.value, reviewed.value.review_digest)
            assert isinstance(payload, Ok), payload

            with mock.patch.object(tui.sys, "platform", "darwin"):
                setup = tui._canonical_setup_run(
                    service,
                    reviewed.value,
                    payload.value,
                    read=_scripted(["y", "y", "y"]),
                    write=lambda _line: None,
                )

            self.assertEqual(setup.reporting[0].key, reviewed.value.items[0].key)
            report = usage_report_from_consumer(
                reviewed.value,
                payload.value,
                setup.reporting,
                aart_version="1.3.1",
                interface="tui",
            )
            self.assertEqual(report.results[0].setup_outcome, "configured")

    def test_reviewed_source_enablement_builds_consumer_context_before_finalize(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = _fixture(Path(raw), "skill")
            project, _checkout, paths, location, _request, catalog, effective = fixture
            service = ConsumerApplicationService(
                ConsumerContext(catalog, effective, builtin(), location, paths),
                LocalConsumerAdapter(),
            )
            configured = effective.configuration.sources[0]
            disabled = replace(configured, enabled=False)
            prospective_configuration = replace(
                effective.configuration,
                sources=(disabled,),
                default_registry=None,
            )
            state = source_state(configured, "direct-source", display_order=0)
            stage = build_source_stage(
                prospective_configuration,
                effective.policy,
                {disabled.alias: state.health},
                first_run=False,
            )
            assert isinstance(stage, Ok), stage
            order = []

            def factory(configuration):
                self.assertTrue(configuration.sources[0].enabled)
                order.append("factory")
                return Ok(service)

            def finalizer(request):
                self.assertTrue(request.after.sources[0].enabled)
                order.append("finalizer")
                return Ok(object())

            with mock.patch.object(tui.sys, "platform", "darwin"):
                code = tui._run_text(
                    _scripted(["", "1", "1", "1", "install", "1", "", "1", "y"]),
                    lambda _line: None,
                    project=str(project),
                    source_stage_view=stage.value,
                    source_finalizer=finalizer,
                    consumer_service_factory=factory,
                )

            self.assertEqual(code, 0)
            self.assertEqual(order, ["factory", "finalizer"])

    def test_federated_user_path_reviews_and_finalizes_without_command_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = _fixture(Path(raw), "skill")
            project, _checkout, paths, location, _request, catalog, effective = fixture
            context = ConsumerContext(catalog, effective, builtin(), location, paths)
            service = ConsumerApplicationService(context, LocalConsumerAdapter())
            configured = effective.configuration.sources[0]
            state = source_state(configured, "direct-source", display_order=0)
            stage = build_source_stage(
                effective.configuration,
                effective.policy,
                {configured.alias: state.health},
                first_run=False,
            )
            assert isinstance(stage, Ok), stage
            writes = []

            with (
                mock.patch.object(tui.sys, "platform", "darwin"),
                mock.patch.object(tui, "_dispatch_result") as legacy_dispatch,
            ):
                code = tui._run_text(
                    _scripted(["", "1", "1", "1", "install", "1", "", "1", "y"]),
                    writes.append,
                    project=str(project),
                    source_stage_view=stage.value,
                    consumer_service=service,
                )

            self.assertEqual(code, 0)
            legacy_dispatch.assert_not_called()
            rendered = "\n".join(writes)
            self.assertIn("direct/skill/review@1.0.0", rendered)
            self.assertIn("trust/security: direct-source; unknown (not-scanned)", rendered)
            self.assertIn("actual modes: copy", rendered)
            self.assertIn("Install outcome: succeeded", rendered)
            self.assertIn("changed=1", rendered)

    def test_reporting_provider_failure_after_finalize_preserves_success_exit(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = _fixture(Path(raw), "skill")
            project, _checkout, paths, location, _request, catalog, effective = fixture
            service = ConsumerApplicationService(
                ConsumerContext(catalog, effective, builtin(), location, paths),
                LocalConsumerAdapter(),
            )
            configured = effective.configuration.sources[0]
            state = source_state(configured, "direct-source", display_order=0)
            stage = build_source_stage(
                effective.configuration,
                effective.policy,
                {configured.alias: state.health},
                first_run=False,
            )
            assert isinstance(stage, Ok), stage
            failure = Err(
                (
                    Diagnostic(
                        DiagnosticCode("reporting-provider-failed"),
                        Severity.ERROR,
                        "provider unavailable",
                    ),
                )
            )
            reporting = ReportingApplicationService(
                ReportingDestination(ReportingMode.AUTOMATIC, "github.com", "org/usage"),
                lambda _plan: failure,
                lambda _plan: failure,
            )
            writes = []

            with mock.patch.object(tui.sys, "platform", "darwin"):
                code = tui._run_text(
                    _scripted(["", "1", "1", "1", "install", "1", "", "1", "y"]),
                    writes.append,
                    project=str(project),
                    source_stage_view=stage.value,
                    consumer_service=service,
                    reporting_service=reporting,
                )

            self.assertEqual(code, 0)
            self.assertTrue((project / ".claude/skills/review/SKILL.md").exists())
            rendered = "\n".join(writes)
            self.assertIn("Exact redacted usage report payload", rendered)
            self.assertIn("warning: usage report submission failed", rendered)

    def test_back_keeps_the_qualified_basket_and_finalizes_once(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = _fixture(Path(raw), "skill")
            project, _checkout, paths, location, _request, catalog, effective = fixture
            service = ConsumerApplicationService(
                ConsumerContext(catalog, effective, builtin(), location, paths),
                LocalConsumerAdapter(),
            )
            configured = effective.configuration.sources[0]
            state = source_state(configured, "direct-source", display_order=0)
            stage = build_source_stage(
                effective.configuration,
                effective.policy,
                {configured.alias: state.health},
                first_run=False,
            )
            assert isinstance(stage, Ok), stage
            writes = []

            with mock.patch.object(tui.sys, "platform", "darwin"):
                code = tui._run_text(
                    _scripted(
                        [
                            "",
                            "1",
                            "1",
                            "1",
                            "install",
                            "1",
                            "",
                            "1",
                            "back",
                            "",
                            "y",
                        ]
                    ),
                    writes.append,
                    project=str(project),
                    source_stage_view=stage.value,
                    consumer_service=service,
                )

            self.assertEqual(code, 0)
            rendered = "\n".join(writes)
            self.assertGreaterEqual(rendered.count("direct/skill/review@1.0.0"), 3)
            self.assertGreaterEqual(rendered.count("Basket: 1 selected"), 1)
            self.assertTrue((project / ".claude/skills/review/SKILL.md").exists())


class QuietSetupQueueTest(unittest.TestCase):
    """One question, then the steps run -- and the detail is there for whoever asks for it.

    The screen used to print every step of every plan, ask whether to finalize the queue, and
    then ask again about each step in turn.  That is a wall of text in front of a person who has
    already decided, and every `y` after the first asks a question whose answer was settled when
    they chose to install the artifact (`#113`).  No test asserted any of those strings, which is
    how they lasted; these do.
    """

    def _run(self, answers):
        """Install the fixture artifact, then run its setup queue against `answers`."""

        prompts: list[str] = []
        writes: list[str] = []
        with tempfile.TemporaryDirectory() as raw:
            fixture = SetupFixture(Path(raw))
            (fixture.project / ".agent-artifacts/manifest.json").unlink()
            service = ConsumerApplicationService(
                ConsumerContext(
                    fixture.catalog,
                    fixture.effective,
                    builtin(),
                    fixture.location,
                    fixture.paths,
                ),
                LocalConsumerAdapter(),
            )
            reviewed = service.prepare(
                ConsumerActionRequest(
                    "install",
                    (fixture.catalog.items[0].coordinate,),
                    ("claude",),
                )
            )
            assert isinstance(reviewed, Ok), reviewed
            payload = service.finalize(reviewed.value, reviewed.value.review_digest)
            assert isinstance(payload, Ok), payload

            with mock.patch.object(tui.sys, "platform", "darwin"):
                code = tui._run_canonical_setup_queue(
                    service,
                    reviewed.value,
                    payload.value,
                    read=_scripted(answers, prompts),
                    write=writes.append,
                )
            configured = (fixture.project / ".setup-config").exists()
        return code, "\n".join(writes), prompts, configured

    def test_pressing_enter_runs_the_queue_and_asks_nothing_else(self):
        # "y" authorizes the untrusted-source capability, which is a real question: the answer can
        # genuinely be no.  The empty line is the operator pressing Enter at the one question this
        # screen asks about the queue itself.
        code, rendered, prompts, configured = self._run(["y", ""])

        self.assertEqual(code, 0)
        self.assertTrue(configured)
        self.assertIn("Run setup? [Y/s/n]: ", prompts)
        self.assertIn("Setup: 1 step for 1 artifact.", rendered)
        self.assertIn("Enter runs them.", rendered)
        # The two prompts this change exists to remove.
        self.assertNotIn("Finalize this setup queue?", rendered + "".join(prompts))
        self.assertNotIn("Approve this exact effect?", rendered + "".join(prompts))
        # Reporting is not asking: the step still says what it is while it happens.
        self.assertIn("1. ", rendered)
        # And the detail nobody asked for stays unprinted.
        self.assertNotIn("Setup review:", rendered)

    def test_s_shows_every_step_and_asks_about_each_one(self):
        code, rendered, prompts, configured = self._run(["y", "s", "y"])

        self.assertEqual(code, 0)
        self.assertTrue(configured)
        self.assertIn("Review setup queue (runs sequentially after installed payloads):", rendered)
        self.assertIn("Setup review:", rendered)
        self.assertIn("Approve this exact effect? [y/N]: ", prompts)

    def test_n_stops_before_any_effect_runs(self):
        code, rendered, _prompts, configured = self._run(["y", "n"])

        self.assertEqual(code, 1)
        self.assertFalse(configured)
        self.assertIn("Setup remains pending.", rendered)
        self.assertIn("installed payloads were not rolled back", rendered)

    def test_an_answer_nobody_planned_for_stops_as_well(self):
        """A typo that runs every step is worse than a typo that runs none: the queue repeats."""

        code, _rendered, _prompts, configured = self._run(["y", "banana"])

        self.assertEqual(code, 1)
        self.assertFalse(configured)

    def test_no_terminal_at_all_never_runs_the_queue(self):
        """Ending the answers raises EOF, which is not an empty line and must not mean yes."""

        code, rendered, _prompts, configured = self._run(["y"])

        self.assertEqual(code, 1)
        self.assertFalse(configured)
        self.assertIn("Setup remains pending.", rendered)


if __name__ == "__main__":
    unittest.main()
