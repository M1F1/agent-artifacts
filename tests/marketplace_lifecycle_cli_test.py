"""Canonical non-interactive lifecycle commands (LIFE02).

These tests pin the agent-facing contract of ``aart marketplace install/update/uninstall/status/
setup``: JSON first, source-qualified coordinates, and an explicit Review/Finalize boundary that
replaces the TUI's interactive confirmation instead of removing it.
"""

from __future__ import annotations

import contextlib
import io
import json
import unittest
from dataclasses import dataclass, field
from unittest import mock

from agent_artifacts import cli
from agent_artifacts.configuration.model import SourceKind
from agent_artifacts.consumer.model import (
    ConsumerActionRequest,
    ConsumerOutcome,
    ConsumerReview,
    ConsumerReviewItem,
    ConsumerSetupQueue,
    ConsumerTerminalItem,
)
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import (
    ArtifactCoordinate,
    ArtifactIdentity,
    ObjectDigest,
    SourceAlias,
)
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.marketplace.catalog import build_marketplace
from agent_artifacts.protocol.hashing import sha256_bytes
from agent_artifacts.protocol.native_models import ArtifactSelector, CollectionManifest
from tests.marketplace_fixtures import (
    artifact,
    configured_source,
    effective_configuration,
    graph_with_collections,
    source_state,
)

COORDINATE = ArtifactCoordinate(
    SourceAlias("team"),
    ArtifactIdentity("skill", "code-review"),
    "1.0.0",
)


def _catalog():
    """A real compiled catalog: selector resolution must run against real data, not a stub."""

    team = configured_source("team", SourceKind.SOURCE_GIT)
    indexed = artifact("team-source", "code-review")
    compiled = graph_with_collections(
        team,
        "team-source",
        (indexed,),
        (
            CollectionManifest(
                1,
                "starter",
                "Install the reviewed starter set.",
                (ArtifactSelector(indexed.identity),),
            ),
        ),
    )
    built = build_marketplace(
        compiled,
        effective_configuration((team,)),
        (source_state(team, "team-source", display_order=0),),
    )
    assert isinstance(built, Ok), built
    return built.value


@dataclass(frozen=True, slots=True)
class _StubPlan:
    """Stand-in for a real domain plan; the CLI must never inspect its internals."""

    review_digest: ObjectDigest = ObjectDigest("sha256", "d" * 64)


def _review_item(action: str = "install") -> ConsumerReviewItem:
    return ConsumerReviewItem(
        f"{COORDINATE}#claude/project",
        COORDINATE,
        "claude",
        "project",
        action,  # type: ignore[arg-type]
        "abc1234",
        "company-reviewed",
        "sha256:manifest",
        "sha256:payload",
        "sha256:object",
        "assessed",
        "low",
        (),
        None,
        ObjectDigest("sha256", "d" * 64),
        _StubPlan(),  # type: ignore[arg-type]
    )


@dataclass(frozen=True, slots=True)
class _StubContext:
    catalog: object


@dataclass
class _StubService:
    """Records exactly which application-service calls a command performs."""

    context: _StubContext = field(default_factory=lambda: _StubContext(_catalog()))
    review: object = None
    outcome: object = None
    prepare_error: Err | None = None
    finalize_error: Err | None = None
    calls: list[str] = field(default_factory=list)
    finalize_digests: list[object] = field(default_factory=list)
    setup_authorizations: list[tuple[bool, bool]] = field(default_factory=list)
    prepared_requests: list[ConsumerActionRequest] = field(default_factory=list)
    queue: ConsumerSetupQueue | None = None

    def prepare(self, request):
        self.calls.append("prepare")
        self.prepared_requests.append(request)
        if self.prepare_error is not None:
            return self.prepare_error
        return Ok(self.review)

    def finalize(self, review, reviewed_digest):
        self.calls.append("finalize")
        self.finalize_digests.append(reviewed_digest)
        if self.finalize_error is not None:
            return self.finalize_error
        return Ok(self.outcome)

    def setup_queue(
        self,
        review,
        outcome,
        *,
        authorize_untrusted_source: bool = False,
        authorize_custom_entrypoint: bool = False,
    ):
        self.calls.append("setup_queue")
        self.setup_authorizations.append((authorize_untrusted_source, authorize_custom_entrypoint))
        return self.queue if self.queue is not None else ConsumerSetupQueue((), ())

    def finalize_setup_queue(self, queue, *, consent, stop_on_failure=False, runtime=None):
        self.calls.append("finalize_setup_queue")
        raise AssertionError("no test in this module reaches real setup execution")


def _review(action: str = "install", *, items=None) -> ConsumerReview:
    request = ConsumerActionRequest(
        action,  # type: ignore[arg-type]
        (COORDINATE,) if action != "status" else (),
        ("claude",),
    )
    return ConsumerReview(
        request,
        (_review_item(action),) if items is None else items,
        sha256_bytes(b"unreviewed-consumer-action"),
    )


def _outcome(action: str = "install") -> ConsumerOutcome:
    return ConsumerOutcome(
        action,  # type: ignore[arg-type]
        (ConsumerTerminalItem(f"{COORDINATE}#claude/project", "changed", "installed"),),
    )


def _run(argv, service):
    stdout = io.StringIO()
    with (
        mock.patch(
            "agent_artifacts.commands.marketplace.load_local_consumer_service",
            return_value=Ok(service),
        ),
        contextlib.redirect_stdout(stdout),
    ):
        code = cli.main(argv)
    return code, stdout.getvalue()


def _payload(output: str):
    return json.loads(output)


class LifecycleParserTests(unittest.TestCase):
    def test_install_maps_coordinates_profiles_scope_and_mode(self) -> None:
        request = cli._to_request(
            cli.build_parser().parse_args(
                [
                    "marketplace",
                    "install",
                    "team/skill/code-review",
                    "--profile",
                    "claude",
                    "--scope",
                    "user",
                    "--mode",
                    "symlink",
                    "--json",
                    "--yes",
                ]
            )
        )

        self.assertEqual(request.command, "marketplace")
        self.assertEqual(request.marketplace_action, "install")
        self.assertEqual(request.names, ("team/skill/code-review",))
        self.assertEqual(request.profiles, ("claude",))
        self.assertEqual(request.scope, "user")
        self.assertEqual(request.install_mode, "symlink")
        self.assertTrue(request.json)
        self.assertTrue(request.yes)

    def test_health_maps_optional_selection_and_required_environment(self) -> None:
        request = cli._to_request(
            cli.build_parser().parse_args(
                [
                    "marketplace",
                    "health",
                    "team/collection/starter",
                    "--environment",
                    "runtime-environment.json",
                    "--json",
                ]
            )
        )

        self.assertEqual(request.marketplace_action, "health")
        self.assertEqual(request.names, ("team/collection/starter",))
        self.assertEqual(request.runtime_environment, "runtime-environment.json")
        self.assertEqual(request.profiles, ())

    def test_lifecycle_actions_do_not_accept_the_legacy_source_or_repo_flags(self) -> None:
        for action in ("install", "update", "uninstall", "status", "setup"):
            with self.subTest(action=action):
                parser = cli.build_parser()
                with self.assertRaises(SystemExit):
                    with contextlib.redirect_stderr(io.StringIO()):
                        parser.parse_args(
                            ["marketplace", action, "--source", "/tmp/legacy-checkout"]
                        )

    def test_offline_and_setup_authorization_flags_are_explicit(self) -> None:
        request = cli._to_request(
            cli.build_parser().parse_args(
                [
                    "marketplace",
                    "setup",
                    "team/skill/code-review",
                    "--profile",
                    "claude",
                    "--offline",
                    "--authorize-untrusted-source",
                    "--authorize-custom-entrypoint",
                    "--approve-setup-effects",
                    "--yes",
                ]
            )
        )

        self.assertTrue(request.offline)
        self.assertTrue(request.authorize_untrusted_source)
        self.assertTrue(request.authorize_custom_entrypoint)
        self.assertTrue(request.approve_setup_effects)

    def test_setup_authorizations_default_to_denied(self) -> None:
        request = cli._to_request(
            cli.build_parser().parse_args(
                ["marketplace", "install", "team/skill/code-review", "--profile", "claude"]
            )
        )

        self.assertFalse(request.offline)
        self.assertFalse(request.authorize_untrusted_source)
        self.assertFalse(request.authorize_custom_entrypoint)
        self.assertFalse(request.approve_setup_effects)
        self.assertFalse(request.yes)


class ReviewFinalizeBoundaryTests(unittest.TestCase):
    def test_collection_install_expands_before_the_application_service_review(self) -> None:
        service = _StubService(review=_review(), outcome=_outcome())

        code, output = _run(
            [
                "marketplace",
                "install",
                "team/collection/starter",
                "--profile",
                "claude",
                "--json",
            ],
            service,
        )

        self.assertEqual(code, 0, output)
        self.assertEqual(service.prepared_requests[0].coordinates, (COORDINATE,))

    def test_install_without_yes_stops_after_review_and_mutates_nothing(self) -> None:
        service = _StubService(review=_review(), outcome=_outcome())

        code, output = _run(
            ["marketplace", "install", "team/skill/code-review", "--profile", "claude", "--json"],
            service,
        )

        self.assertEqual(code, 0)
        self.assertEqual(service.calls, ["prepare"])
        payload = _payload(output)
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["finalized"])
        self.assertEqual(payload["operation"], "marketplace.install")
        self.assertIn("review_digest", payload)

    def test_install_with_yes_finalizes_the_exact_reviewed_digest(self) -> None:
        review = _review()
        service = _StubService(review=review, outcome=_outcome())

        code, output = _run(
            [
                "marketplace",
                "install",
                "team/skill/code-review",
                "--profile",
                "claude",
                "--json",
                "--yes",
            ],
            service,
        )

        self.assertEqual(code, 0)
        self.assertEqual(service.calls, ["prepare", "finalize"])
        self.assertEqual(service.finalize_digests, [review.review_digest])
        payload = _payload(output)
        self.assertTrue(payload["finalized"])
        self.assertEqual(payload["session_status"], "succeeded")

    def test_review_only_output_names_the_flag_that_would_apply_it(self) -> None:
        service = _StubService(review=_review(), outcome=_outcome())

        _, output = _run(
            ["marketplace", "install", "team/skill/code-review", "--profile", "claude"],
            service,
        )

        self.assertIn("--yes", output)
        self.assertEqual(service.calls, ["prepare"])

    def test_a_prepare_failure_never_reaches_finalize(self) -> None:
        service = _StubService(
            prepare_error=Err(
                (
                    Diagnostic(
                        DiagnosticCode("artifact-ambiguous"),
                        Severity.ERROR,
                        "artifact skill/code-review is ambiguous; valid coordinates: "
                        "company/skill/code-review, team/skill/code-review",
                    ),
                )
            )
        )

        code, output = _run(
            [
                "marketplace",
                "install",
                "team/skill/code-review",
                "--profile",
                "claude",
                "--json",
                "--yes",
            ],
            service,
        )

        self.assertEqual(code, 1)
        self.assertEqual(service.calls, ["prepare"])
        payload = _payload(output)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["diagnostics"][0]["code"], "artifact-ambiguous")

    def test_a_failed_finalize_reports_a_non_zero_exit(self) -> None:
        service = _StubService(
            review=_review(),
            finalize_error=Err(
                (
                    Diagnostic(
                        DiagnosticCode("consumer-review-mismatch"),
                        Severity.ERROR,
                        "consumer Finalize digest does not match the reviewed basket",
                    ),
                )
            ),
        )

        code, output = _run(
            [
                "marketplace",
                "install",
                "team/skill/code-review",
                "--profile",
                "claude",
                "--json",
                "--yes",
            ],
            service,
        )

        self.assertEqual(code, 1)
        self.assertFalse(_payload(output)["ok"])

    def test_a_failed_outcome_item_exits_non_zero_even_when_finalize_succeeds(self) -> None:
        outcome = ConsumerOutcome(
            "install",
            (ConsumerTerminalItem(f"{COORDINATE}#claude/project", "failed", "payload missing"),),
        )
        service = _StubService(review=_review(), outcome=outcome)

        code, output = _run(
            [
                "marketplace",
                "install",
                "team/skill/code-review",
                "--profile",
                "claude",
                "--json",
                "--yes",
            ],
            service,
        )

        self.assertEqual(code, 1)
        payload = _payload(output)
        self.assertTrue(payload["finalized"])
        self.assertEqual(payload["session_status"], "failed")


class LifecycleRequestMappingTests(unittest.TestCase):
    def test_scope_mode_offline_force_and_prune_reach_the_action_request(self) -> None:
        service = _StubService(review=_review("update"), outcome=_outcome("update"))

        _run(
            [
                "marketplace",
                "update",
                "team/skill/code-review",
                "--profile",
                "claude",
                "--scope",
                "user",
                "--mode",
                "symlink",
                "--offline",
                "--force",
                "--prune",
                "--json",
            ],
            service,
        )

        prepared = service.prepared_requests[0]
        self.assertEqual(prepared.action, "update")
        self.assertEqual(prepared.scope, "user")
        self.assertEqual(prepared.mode, "symlink")
        self.assertTrue(prepared.offline)
        self.assertTrue(prepared.force)
        self.assertTrue(prepared.prune)

    def test_status_needs_no_coordinates(self) -> None:
        service = _StubService(review=_review("status"), outcome=_outcome("status"))

        code, output = _run(["marketplace", "status", "--profile", "claude", "--json"], service)

        self.assertEqual(code, 0)
        self.assertEqual(service.prepared_requests[0].coordinates, ())
        self.assertEqual(_payload(output)["operation"], "marketplace.status")

    def test_install_requires_at_least_one_coordinate(self) -> None:
        service = _StubService(review=_review(), outcome=_outcome())

        code, output = _run(["marketplace", "install", "--profile", "claude", "--json"], service)

        self.assertEqual(code, 1)
        self.assertEqual(service.calls, [])
        self.assertEqual(_payload(output)["diagnostics"][0]["code"], "consumer-invalid")

    def test_install_requires_at_least_one_profile(self) -> None:
        service = _StubService(review=_review(), outcome=_outcome())

        code, output = _run(["marketplace", "install", "team/skill/code-review", "--json"], service)

        self.assertEqual(code, 1)
        self.assertEqual(service.calls, [])
        self.assertEqual(_payload(output)["diagnostics"][0]["code"], "consumer-invalid")

    def test_an_unparseable_coordinate_fails_before_any_service_call(self) -> None:
        service = _StubService(review=_review(), outcome=_outcome())

        code, output = _run(
            ["marketplace", "install", "not-a-coordinate", "--profile", "claude", "--json"],
            service,
        )

        self.assertEqual(code, 1)
        self.assertEqual(service.calls, [])
        self.assertIn("<source>/<kind>/<name>", _payload(output)["diagnostics"][0]["message"])


class SetupAuthorizationTests(unittest.TestCase):
    def test_setup_never_authorizes_untrusted_capabilities_implicitly(self) -> None:
        service = _StubService(review=_review(), outcome=_outcome())

        _run(
            [
                "marketplace",
                "setup",
                "team/skill/code-review",
                "--profile",
                "claude",
                "--json",
                "--yes",
            ],
            service,
        )

        self.assertEqual(service.setup_authorizations, [(False, False)])

    def test_setup_passes_only_the_authorizations_that_were_requested(self) -> None:
        service = _StubService(review=_review(), outcome=_outcome())

        _run(
            [
                "marketplace",
                "setup",
                "team/skill/code-review",
                "--profile",
                "claude",
                "--authorize-untrusted-source",
                "--json",
                "--yes",
            ],
            service,
        )

        self.assertEqual(service.setup_authorizations, [(True, False)])

    def test_setup_without_yes_reviews_the_queue_without_executing_it(self) -> None:
        service = _StubService(review=_review(), outcome=_outcome())

        code, output = _run(
            ["marketplace", "setup", "team/skill/code-review", "--profile", "claude", "--json"],
            service,
        )

        self.assertEqual(code, 0)
        self.assertNotIn("finalize_setup_queue", service.calls)
        self.assertFalse(_payload(output)["finalized"])


class ConfigurationGateTests(unittest.TestCase):
    def test_a_content_operation_fails_closed_without_a_configured_source(self) -> None:
        denial = Err(
            (
                Diagnostic(
                    DiagnosticCode("no-source-configured"),
                    Severity.ERROR,
                    "this content operation requires at least one enabled source",
                    remediation=("run `aart source add --help` to configure one",),
                ),
            )
        )
        stdout = io.StringIO()
        with (
            mock.patch(
                "agent_artifacts.commands.marketplace.load_local_consumer_service",
                return_value=denial,
            ),
            contextlib.redirect_stdout(stdout),
        ):
            code = cli.main(
                [
                    "marketplace",
                    "install",
                    "team/skill/code-review",
                    "--profile",
                    "claude",
                    "--json",
                    "--yes",
                ]
            )

        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["diagnostics"][0]["code"], "no-source-configured")


if __name__ == "__main__":  # pragma: no cover - unittest entry point
    unittest.main()
