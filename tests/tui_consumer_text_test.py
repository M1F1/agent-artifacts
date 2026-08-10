from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from agent_artifacts import tui
from agent_artifacts.consumer import (
    ConsumerActionRequest,
    ConsumerApplicationService,
    ConsumerContext,
    LocalConsumerAdapter,
)
from agent_artifacts.domain.result import Ok
from agent_artifacts.profiles.builtin import builtin
from agent_artifacts.tui_sources import build_source_stage
from tests.canonical_setup_application_test import Fixture as SetupFixture
from tests.canonical_symlink_test import _fixture
from tests.marketplace_fixtures import source_state


def _scripted(answers):
    values = iter(answers)

    def read(_prompt=""):
        try:
            return next(values)
        except StopIteration:
            raise EOFError from None

    return read


class TuiConsumerTextTest(unittest.TestCase):
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

            with mock.patch.object(tui, "_dispatch_result") as legacy_dispatch:
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

            code = tui._run_text(
                _scripted(["", "1", "1", "1", "install", "1", "", "1", "back", "", "y"]),
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
