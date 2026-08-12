from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from agent_artifacts import tui
from agent_artifacts.compiler import CollectionCoordinate, MarketplaceCollection
from agent_artifacts.configuration.model import ReportingMode
from agent_artifacts.consumer import (
    ConsumerActionRequest,
    ConsumerApplicationService,
    ConsumerContext,
    LocalConsumerAdapter,
)
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.profiles.builtin import builtin
from agent_artifacts.reporting.application import ReportingApplicationService
from agent_artifacts.reporting.model import ReportingDestination
from agent_artifacts.reporting.projection import usage_report_from_consumer
from agent_artifacts.tui_sources import build_source_stage
from tests.canonical_setup_application_test import Fixture as SetupFixture
from tests.canonical_symlink_test import _fixture
from tests.marketplace_fixtures import source_state

_INSTALL_STATE_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "install-state"


def _scripted(answers):
    values = iter(answers)

    def read(_prompt=""):
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
    def test_err02_legacy_project_state_reaches_artifacts_as_one_flattened_error_without_writes(
        self,
    ) -> None:
        """ERR03 will preserve this diagnostic instead of flattening it at the text boundary."""

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
                    _scripted(["", "1", "1", "1", "install", "1", ""]),
                    writes.append,
                    project=str(project),
                    source_stage_view=stage.value,
                    consumer_service=service,
                )

            self.assertEqual(code, 2)
            self.assertIn(
                "error: AART 0.1 installation state was detected.",
                "\n".join(writes),
            )
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
                    read=_scripted(["y", "y", "y"]),
                    write=writes.append,
                )

            self.assertEqual(code, 0)
            rendered = "\n".join(writes)
            self.assertIn("explicit permission", rendered)
            self.assertIn("Review setup queue", rendered)
            self.assertIn("Setup outcome: configured=1, incomplete=0", rendered)
            self.assertTrue((fixture.project / ".setup-config").exists())

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


if __name__ == "__main__":
    unittest.main()
