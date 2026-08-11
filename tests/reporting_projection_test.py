from __future__ import annotations

import unittest
from dataclasses import replace
from typing import cast

from agent_artifacts.consumer.model import (
    ConsumerActionRequest,
    ConsumerOutcome,
    ConsumerPlan,
    ConsumerReview,
    ConsumerReviewEffect,
    ConsumerReviewItem,
    ConsumerTerminalItem,
)
from agent_artifacts.domain.identifiers import ArtifactCoordinate, ArtifactIdentity, SourceAlias
from agent_artifacts.protocol.hashing import sha256_bytes
from agent_artifacts.protocol.semver import SemVer
from agent_artifacts.reporting.model import usage_report_bytes
from agent_artifacts.reporting.projection import (
    SetupReportState,
    usage_report_from_consumer,
    usage_reports_by_registry_from_consumer,
)


def _coordinate() -> ArtifactCoordinate:
    return ArtifactCoordinate(
        SourceAlias("company"),
        ArtifactIdentity("mcp", "atlassian"),
        SemVer(1, 0, 0),
    )


def _review() -> ConsumerReview:
    coordinate = _coordinate()
    request = ConsumerActionRequest(
        "install", (coordinate,), ("tabnine",), "user", "symlink", "darwin"
    )
    digest = sha256_bytes(b"x")
    plan = cast(ConsumerPlan, object())
    item = ConsumerReviewItem(
        f"{coordinate}#tabnine/user",
        coordinate,
        "tabnine",
        "user",
        "install",
        "a" * 40,
        "company-reviewed",
        str(digest),
        str(digest),
        str(digest),
        "complete",
        "low",
        (ConsumerReviewEffect("copy-tree", "/Users/alice/private", "symlink"),),
        None,
        digest,
        plan,
    )
    return ConsumerReview(request, (item,), sha256_bytes(b"unreviewed-consumer-action"))


class ReportingProjectionTest(unittest.TestCase):
    def test_projection_uses_allowlisted_facts_and_ignores_terminal_detail_and_destinations(
        self,
    ) -> None:
        review = _review()
        terminal = ConsumerOutcome(
            "install",
            (
                ConsumerTerminalItem(
                    review.items[0].key,
                    "failed",
                    "TOKEN=secret at /Users/alice/private",
                    "pending",
                ),
            ),
        )
        setup = SetupReportState(
            review.items[0].key,
            "verification-failed",
            sha256_bytes(b"recipe"),
            "verification",
            "setup-verification-failed",
        )

        event = usage_report_from_consumer(
            review,
            terminal,
            (setup,),
            aart_version="1.0.0a1",
            interface="tui",
        )

        self.assertEqual(event.results[0].actual_modes, ("symlink",))
        self.assertEqual(event.results[0].setup_outcome, "verification-failed")
        self.assertEqual(event.results[0].installer_digest, sha256_bytes(b"recipe"))
        rendered = repr(event)
        self.assertNotIn("secret", rendered)
        self.assertNotIn("/Users/alice", rendered)
        self.assertNotIn("company", rendered)

    def test_projection_rejects_missing_or_extra_terminal_identity(self) -> None:
        review = _review()
        for items in (
            (),
            (ConsumerTerminalItem("different#tabnine/user", "changed"),),
        ):
            with self.subTest(items=items):
                with self.assertRaises(ValueError):
                    usage_report_from_consumer(
                        review,
                        ConsumerOutcome("install", items),
                        (),
                        aart_version="1.0.0a1",
                        interface="tui",
                    )

    def test_projection_partitions_results_by_registry_without_serializing_aliases(self) -> None:
        first = _review()
        second_coordinate = ArtifactCoordinate(
            SourceAlias("public"),
            ArtifactIdentity("skill", "search"),
            SemVer(1, 0, 0),
        )
        second_item = replace(
            first.items[0],
            key=f"{second_coordinate}#tabnine/user",
            coordinate=second_coordinate,
        )
        request = replace(
            first.request,
            coordinates=tuple(sorted((*first.request.coordinates, second_coordinate), key=str)),
        )
        review = ConsumerReview(
            request,
            (first.items[0], second_item),
            sha256_bytes(b"unreviewed-consumer-action"),
        )
        outcome = ConsumerOutcome(
            "install",
            tuple(ConsumerTerminalItem(item.key, "changed") for item in review.items),
        )

        routed = usage_reports_by_registry_from_consumer(
            review,
            outcome,
            (),
            aart_version="1.0.0a1",
            interface="tui",
        )

        self.assertEqual(
            tuple(item.source_alias.value for item in routed),
            ("company", "public"),
        )
        payloads = tuple(usage_report_bytes(item.report).decode("utf-8") for item in routed)
        self.assertIn('"artifact_name":"atlassian"', payloads[0])
        self.assertNotIn('"artifact_name":"search"', payloads[0])
        self.assertIn('"artifact_name":"search"', payloads[1])
        self.assertNotIn("company", payloads[0])
        self.assertNotIn("public", payloads[1])

    def test_projection_uses_bounded_failure_categories_for_terminal_states(self) -> None:
        review = _review()
        key = review.items[0].key
        cases = (
            ("cancelled", "setup-installer", "user-cancelled"),
            ("queue-declined", "queue", "user-cancelled"),
            ("unsupported", "setup-installer", "unsupported"),
            ("prerequisite-missing", "setup-installer", "dependency"),
            ("conflicted", "setup-installer", "conflict"),
        )
        for status, phase, expected in cases:
            with self.subTest(status=status):
                event = usage_report_from_consumer(
                    review,
                    ConsumerOutcome(
                        "install",
                        (ConsumerTerminalItem(key, "changed", setup_status="pending"),),
                    ),
                    (
                        SetupReportState(
                            key,
                            status,
                            failure_phase=phase,
                            failure_code=f"setup-{status}",
                        ),
                    ),
                    aart_version="1.0.0a1",
                    interface="tui",
                )
                assert event.results[0].failure is not None
                self.assertEqual(event.results[0].failure.category, expected)

    def test_unknown_setup_phase_is_rejected(self) -> None:
        review = _review()
        key = review.items[0].key
        with self.assertRaises(ValueError):
            SetupReportState(
                key,
                "failed",
                failure_phase="unknown",
                failure_code="setup-failed",
            )


if __name__ == "__main__":
    unittest.main()
