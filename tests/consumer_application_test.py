from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from agent_artifacts.consumer import (
    ConsumerActionRequest,
    ConsumerContext,
    finalize_consumer_action,
    prepare_consumer_action,
    prepare_consumer_setup_queue,
    render_consumer_outcome,
    render_consumer_review,
)
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.lifecycle import LocalLifecycleAdapter
from agent_artifacts.marketplace.model import MarketplaceCatalog, MarketplaceItem
from agent_artifacts.profiles.builtin import builtin
from agent_artifacts.security.aggregation import ArtifactSecurityEvidence
from agent_artifacts.security.attestations import AttestationTrust
from agent_artifacts.security.baseline import not_scanned_assessment
from tests.canonical_setup_application_test import Fixture as SetupFixture
from tests.canonical_symlink_test import _fixture


def _context(fixture) -> ConsumerContext:
    _project, _checkout, paths, location, _request, catalog, effective = fixture
    return ConsumerContext(catalog, effective, builtin(), location, paths)


class ConsumerApplicationTest(unittest.TestCase):
    def test_invalid_profile_or_missing_lifecycle_selection_fails_before_review(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            context = _context(_fixture(Path(raw), "skill"))
            coordinate = context.catalog.items[0].coordinate
            adapter = LocalLifecycleAdapter()

            missing_profile = prepare_consumer_action(
                ConsumerActionRequest("install", (coordinate,), ("missing",)),
                context,
                adapter,
            )
            missing_installation = prepare_consumer_action(
                ConsumerActionRequest("update", (coordinate,), ("claude",)),
                context,
                adapter,
            )
            incompatible_platform = prepare_consumer_action(
                ConsumerActionRequest(
                    "install",
                    (coordinate,),
                    ("claude",),
                    platform="linux",
                ),
                context,
                adapter,
            )

            self.assertIsInstance(missing_profile, Err)
            self.assertIn("profiles are unavailable", missing_profile.diagnostics[0].message)
            self.assertIsInstance(missing_installation, Err)
            self.assertIn(
                "installations were not found", missing_installation.diagnostics[0].message
            )
            self.assertIsInstance(incompatible_platform, Err)
            self.assertIn("platform", incompatible_platform.diagnostics[0].message)

    def test_merge_effect_keeps_copy_as_the_actual_mode_under_symlink_request(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            context = _context(_fixture(Path(raw), "mcp"))
            reviewed = prepare_consumer_action(
                ConsumerActionRequest(
                    "install",
                    (context.catalog.items[0].coordinate,),
                    ("claude",),
                    mode="symlink",
                ),
                context,
                LocalLifecycleAdapter(),
            )

            assert isinstance(reviewed, Ok), reviewed
            self.assertEqual(reviewed.value.items[0].effects[0].kind, "merge-json")
            self.assertEqual(reviewed.value.items[0].effects[0].actual_mode, "copy")

    def test_install_review_binds_qualified_version_digests_destinations_and_actual_mode(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = _fixture(Path(raw), "skill")
            context = _context(fixture)
            coordinate = context.catalog.items[0].coordinate
            context = replace(
                context,
                security=(
                    ArtifactSecurityEvidence(
                        coordinate,
                        not_scanned_assessment(
                            context.catalog.items[0].artifact.artifact.object_digest,
                            "No analyzer was requested for this test object.",
                        ),
                        AttestationTrust.LOCAL,
                        5,
                    ),
                ),
            )

            reviewed = prepare_consumer_action(
                ConsumerActionRequest(
                    "install",
                    (coordinate,),
                    ("claude",),
                    mode="symlink",
                ),
                context,
                LocalLifecycleAdapter(),
            )

            self.assertIsInstance(reviewed, Ok)
            assert isinstance(reviewed, Ok)
            item = reviewed.value.items[0]
            self.assertEqual(item.coordinate, coordinate)
            self.assertEqual(item.trust, "direct-source")
            self.assertEqual(item.security_status, "not-scanned")
            self.assertEqual(item.installation_risk, "unknown")
            self.assertEqual(item.effects[0].actual_mode, "symlink")
            self.assertTrue(item.effects[0].destination.endswith("/.claude/skills/review"))
            self.assertEqual(
                item.object_digest, str(context.catalog.items[0].artifact.artifact.object_digest)
            )
            rendered = "\n".join(render_consumer_review(reviewed.value))
            self.assertIn(str(coordinate), rendered)
            self.assertIn("actual modes: symlink", rendered)

    def test_finalize_reports_changed_then_explicit_no_op_and_rejects_wrong_review(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            context = _context(_fixture(Path(raw), "skill"))
            request = ConsumerActionRequest(
                "install",
                (context.catalog.items[0].coordinate,),
                ("claude",),
                mode="copy",
            )
            adapter = LocalLifecycleAdapter()
            reviewed = prepare_consumer_action(request, context, adapter)
            assert isinstance(reviewed, Ok), reviewed

            rejected = finalize_consumer_action(
                reviewed.value,
                context.catalog.items[0].artifact.artifact.object_digest,
                context,
                adapter,
            )
            applied = finalize_consumer_action(
                reviewed.value,
                reviewed.value.review_digest,
                context,
                adapter,
            )
            assert isinstance(applied, Ok), applied
            reviewed_again = prepare_consumer_action(request, context, adapter)
            assert isinstance(reviewed_again, Ok), reviewed_again
            current = finalize_consumer_action(
                reviewed_again.value,
                reviewed_again.value.review_digest,
                context,
                adapter,
            )

            self.assertIsInstance(rejected, Err)
            self.assertEqual(applied.value.session_status, "succeeded")
            self.assertEqual(applied.value.counts, (("changed", 1),))
            self.assertIsInstance(current, Ok)
            assert isinstance(current, Ok)
            self.assertEqual(current.value.session_status, "no-op")
            self.assertEqual(current.value.counts, (("current", 1),))
            self.assertIn("Install outcome: no-op", render_consumer_outcome(current.value)[0])

    def test_finalize_converts_one_application_error_into_a_typed_failed_item(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            context = _context(_fixture(Path(raw), "skill"))
            adapter = LocalLifecycleAdapter()
            reviewed = prepare_consumer_action(
                ConsumerActionRequest(
                    "install",
                    (context.catalog.items[0].coordinate,),
                    ("claude",),
                ),
                context,
                adapter,
            )
            assert isinstance(reviewed, Ok), reviewed
            failure = Err(
                (
                    Diagnostic(
                        DiagnosticCode("synthetic-failure"),
                        Severity.ERROR,
                        "synthetic apply failure",
                    ),
                )
            )

            with mock.patch(
                "agent_artifacts.consumer.application.finalize_install",
                return_value=failure,
            ):
                outcome = finalize_consumer_action(
                    reviewed.value,
                    reviewed.value.review_digest,
                    context,
                    adapter,
                )

            assert isinstance(outcome, Ok), outcome
            self.assertEqual(outcome.value.session_status, "failed")
            self.assertEqual(outcome.value.counts, (("failed", 1),))
            self.assertIn("synthetic apply failure", outcome.value.items[0].detail)

    def test_sequential_basket_plans_compose_state_and_report_partial_finalize(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            skill_fixture = _fixture(root, "skill")
            guideline_fixture = _fixture(root, "guideline")
            context = _context(skill_fixture)
            skill_item = skill_fixture[5].items[0]
            guideline_item = guideline_fixture[5].items[0]
            rebound = MarketplaceItem(
                guideline_item.artifact,
                skill_item.source,
                guideline_item.trust,
            )
            context = ConsumerContext(
                MarketplaceCatalog(
                    context.catalog.sources,
                    (skill_item, rebound),
                ),
                context.effective,
                context.profiles,
                context.location,
                context.store_paths,
            )
            adapter = LocalLifecycleAdapter()
            reviewed = prepare_consumer_action(
                ConsumerActionRequest(
                    "install",
                    tuple(item.coordinate for item in context.catalog.items),
                    ("claude",),
                    mode="copy",
                ),
                context,
                adapter,
            )
            assert isinstance(reviewed, Ok), reviewed
            self.assertEqual(len(reviewed.value.items), 2)
            conflicted_destination = Path(reviewed.value.items[1].effects[0].destination)
            conflicted_destination.parent.mkdir(parents=True, exist_ok=True)
            conflicted_destination.write_text("changed after Review\n")

            outcome = finalize_consumer_action(
                reviewed.value,
                reviewed.value.review_digest,
                context,
                adapter,
            )

            assert isinstance(outcome, Ok), outcome
            self.assertEqual(outcome.value.selected, 2)
            self.assertEqual(outcome.value.session_status, "partial")
            self.assertEqual(dict(outcome.value.counts), {"changed": 1, "conflict": 1})

    def test_offline_cached_install_and_lifecycle_actions_have_typed_feedback(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            context = _context(_fixture(Path(raw), "skill"))
            coordinate = context.catalog.items[0].coordinate
            adapter = LocalLifecycleAdapter()
            install = prepare_consumer_action(
                ConsumerActionRequest(
                    "install",
                    (coordinate,),
                    ("claude",),
                    offline=True,
                ),
                context,
                adapter,
            )
            assert isinstance(install, Ok), install
            installed = finalize_consumer_action(
                install.value,
                install.value.review_digest,
                context,
                adapter,
            )
            assert isinstance(installed, Ok), installed

            status = prepare_consumer_action(
                ConsumerActionRequest("status", (), ("claude",)),
                context,
                adapter,
            )
            check = prepare_consumer_action(
                ConsumerActionRequest("check", (), ("claude",)),
                context,
                adapter,
            )
            update = prepare_consumer_action(
                ConsumerActionRequest("update", (coordinate,), ("claude",)),
                context,
                adapter,
            )
            uninstall = prepare_consumer_action(
                ConsumerActionRequest("uninstall", (coordinate,), ("claude",)),
                context,
                adapter,
            )

            self.assertTrue(installed.value.offline_last_known_good)
            self.assertIn(
                "offline last-known-good", "\n".join(render_consumer_outcome(installed.value))
            )
            assert isinstance(status, Ok), status
            self.assertEqual(status.value.items[0].plan.status.value, "current")
            status_outcome = finalize_consumer_action(
                status.value,
                status.value.review_digest,
                context,
                adapter,
            )
            check_outcome = finalize_consumer_action(
                check.value,
                check.value.review_digest,
                context,
                adapter,
            )
            assert isinstance(status_outcome, Ok), status_outcome
            assert isinstance(check_outcome, Ok), check_outcome
            self.assertEqual(status_outcome.value.counts, (("current", 1),))
            self.assertEqual(check_outcome.value.counts, (("current", 1),))
            assert isinstance(update, Ok), update
            updated = finalize_consumer_action(
                update.value,
                update.value.review_digest,
                context,
                adapter,
            )
            assert isinstance(updated, Ok), updated
            self.assertEqual(updated.value.counts, (("current", 1),))
            assert isinstance(uninstall, Ok), uninstall
            removed = finalize_consumer_action(
                uninstall.value,
                uninstall.value.review_digest,
                context,
                adapter,
            )
            assert isinstance(removed, Ok), removed
            self.assertEqual(removed.value.counts, (("removed", 1),))

    def test_setup_queue_starts_after_payload_and_preserves_policy_failure_or_exact_plan(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = SetupFixture(Path(raw))
            (fixture.project / ".agent-artifacts/manifest.json").unlink()
            context = ConsumerContext(
                fixture.catalog,
                fixture.effective,
                builtin(),
                fixture.location,
                fixture.paths,
            )
            coordinate = context.catalog.items[0].coordinate
            reviewed = prepare_consumer_action(
                ConsumerActionRequest("install", (coordinate,), ("claude",)),
                context,
                fixture.adapter,  # type: ignore[arg-type]
            )
            assert isinstance(reviewed, Ok), reviewed
            self.assertIsNotNone(reviewed.value.items[0].setup)
            self.assertIn("setup queue", "\n".join(render_consumer_review(reviewed.value)))
            payload = finalize_consumer_action(
                reviewed.value,
                reviewed.value.review_digest,
                context,
                fixture.adapter,  # type: ignore[arg-type]
            )
            assert isinstance(payload, Ok), payload
            self.assertEqual(payload.value.items[0].setup_status, "pending")

            denied = prepare_consumer_setup_queue(
                reviewed.value,
                payload.value,
                context,
                fixture.adapter,
            )
            authorized = prepare_consumer_setup_queue(
                reviewed.value,
                payload.value,
                context,
                fixture.adapter,
                authorize_untrusted_source=True,
            )

            self.assertEqual(len(denied.plans), 0)
            self.assertEqual(len(denied.failures), 1)
            self.assertIn("authorization", denied.failures[0].detail)
            self.assertEqual(len(authorized.plans), 1)
            self.assertEqual(authorized.failures, ())
            self.assertEqual(
                authorized.plans[0].object_digest,
                context.catalog.items[0].artifact.artifact.object_digest,
            )


if __name__ == "__main__":
    unittest.main()
