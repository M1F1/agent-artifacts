from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from agent_artifacts.consumer import (
    ConsumerActionRequest,
    ConsumerContext,
    ConsumerOutcome,
    ConsumerReviewEffect,
    ConsumerSetupFailure,
    ConsumerTerminalItem,
    prepare_consumer_action,
)
from agent_artifacts.domain.result import Ok
from agent_artifacts.lifecycle import LocalLifecycleAdapter
from agent_artifacts.profiles.builtin import builtin
from agent_artifacts.protocol.hashing import sha256_bytes
from tests.canonical_symlink_test import _fixture


class ConsumerModelTest(unittest.TestCase):
    def test_requests_contexts_effects_and_terminal_values_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            ConsumerActionRequest("install", (), ("claude",))
        with self.assertRaises(ValueError):
            ConsumerReviewEffect("", "/target", "copy")
        with self.assertRaises(ValueError):
            ConsumerTerminalItem("artifact", "invented")
        with self.assertRaises(ValueError):
            ConsumerSetupFailure("", "missing key")
        duplicate = ConsumerTerminalItem("same", "current")
        with self.assertRaises(ValueError):
            ConsumerOutcome("status", (duplicate, duplicate))

        with tempfile.TemporaryDirectory() as raw:
            project, _checkout, paths, location, _request, catalog, effective = _fixture(
                Path(raw), "skill"
            )
            del project
            with self.assertRaises(ValueError):
                ConsumerContext(
                    catalog,
                    effective,
                    {"wrong": builtin()["claude"]},
                    location,
                    paths,
                )

    def test_review_digest_is_computed_once_and_rejects_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            _project, _checkout, paths, location, _request, catalog, effective = _fixture(
                Path(raw), "skill"
            )
            context = ConsumerContext(catalog, effective, builtin(), location, paths)
            review = prepare_consumer_action(
                ConsumerActionRequest(
                    "install",
                    (catalog.items[0].coordinate,),
                    ("claude",),
                ),
                context,
                LocalLifecycleAdapter(),
            )
            assert isinstance(review, Ok), review

            with self.assertRaises(ValueError):
                replace(review.value, review_digest=sha256_bytes(b"substituted"))


if __name__ == "__main__":
    unittest.main()
