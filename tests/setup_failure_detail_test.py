"""RR-2B: a failure transcript keeps the end that explains it.

`LAF-59`: BuildKit prints progress first and the failing instruction last, so head truncation
shows a consumer the transfer line and never the exit code.
"""

from __future__ import annotations

from agent_artifacts.setup_runtime import failure_detail
from tests.function_cases import function_test_case

BUILDKIT_HEAD = "#1 [internal] load build definition\n#1 transferring dockerfile: 117B done\n"
BUILDKIT_TAIL = (
    'ERROR: process "/bin/sh -c set -eu && exit 3" did not complete successfully: exit code: 3\n'
)


def _transcript(filler: int) -> str:
    return (
        BUILDKIT_HEAD + ("#4 resolve docker.io/library/python:3.12-slim\n" * filler) + BUILDKIT_TAIL
    )


def test_a_short_transcript_is_untouched() -> None:
    text = BUILDKIT_HEAD + BUILDKIT_TAIL

    assert failure_detail(text) == text


def test_the_failing_instruction_survives_a_long_transcript() -> None:
    detail = failure_detail(_transcript(40))

    assert "exit code: 3" in detail
    assert "did not complete successfully" in detail


def test_the_head_survives_too_and_the_middle_says_it_was_elided() -> None:
    detail = failure_detail(_transcript(40))

    assert detail.startswith("#1 [internal] load build definition")
    assert "characters elided" in detail


def test_the_result_never_exceeds_the_limit() -> None:
    for filler in (1, 5, 40, 400):
        detail = failure_detail(_transcript(filler))
        assert len(detail) <= 512, filler


def test_a_secret_is_redacted_before_truncation_not_after() -> None:
    # Truncating first could cut the assignment in half and leave a tail the pattern no longer
    # matches, which is why failure_detail owns both steps.
    text = "TOKEN=supersecretvalue\n" + ("filler line\n" * 60) + "TOKEN=anothersecret\n"

    detail = failure_detail(text)

    assert "supersecretvalue" not in detail
    assert "anothersecret" not in detail


def test_a_tiny_limit_still_keeps_the_end() -> None:
    detail = failure_detail(_transcript(40), limit=40)

    assert "exit code: 3" in detail
    assert len(detail) <= 40


# Collected by `unittest discover`, which sees `TestCase` subclasses and nothing
# else; without this the functions above are imported and never run (`AD-41`).
SetupFailureDetailTests = function_test_case(globals(), name="SetupFailureDetailTests")
