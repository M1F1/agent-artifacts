"""One script, two callers, and the exit code an agent loops on.

`prepare_release.py` is the local half of a release.  A person runs it bare and answers a
question; an agent passes the answer and reads a receipt.  Both take the same path through the
same steps, which is the only way the two stay honest about each other -- a JSON mode that runs
different code is a JSON mode that reports a run nobody had.
"""

from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import prepare_release  # noqa: E402

MARKERS = ("CHANGELOG.md:12: TODO(2.8.6): a bold sentence of claim",)


def _run(argv: list[str], *, markers: tuple[str, ...] = (), tty: bool = True) -> tuple[int, str]:
    stdout = io.StringIO()

    def shell(run, name, *_command):  # the real one runs a subprocess; the receipt is the point
        run.step(name, "done")

    def checklist(run, _registry):
        run.step("release checklist", "done")

    with mock.patch.object(prepare_release, "_shell", shell):
        with mock.patch.object(prepare_release, "_checklist", checklist):
            with mock.patch.object(
                prepare_release.release_docs, "open_markers", return_value=markers
            ):
                with mock.patch.object(sys.stdin, "isatty", return_value=tty):
                    with mock.patch("sys.stdout", stdout):
                        code = prepare_release.main(argv)
    return code, stdout.getvalue()


class AgentSurfaceTest(unittest.TestCase):
    def test_json_mode_prints_one_document_and_the_actions_left(self) -> None:
        code, out = _run(["prepare", "2.8.6", "--summary", "x", "--json"])

        self.assertEqual(code, prepare_release.EXIT_OK)
        receipt = json.loads(out)  # one document, not prose with a document in it
        self.assertEqual(receipt["status"], "prepared")
        self.assertEqual(receipt["version"], "2.8.6")
        self.assertEqual([step["status"] for step in receipt["steps"]], ["done"] * 5)
        self.assertIn("release checklist", [step["name"] for step in receipt["steps"]])
        # The three things left are the three a script must not do on its own.
        self.assertEqual(len(receipt["next_actions"]), 3)
        self.assertIn("cut release", receipt["next_actions"][2])

    def test_unwritten_documents_get_their_own_exit_code_and_the_lines(self) -> None:
        """`3`, not `2`: the answer is to write something, then run this again.

        A single failure code would make an agent treat an unwritten changelog the same as a
        failing gate -- one is a retry after work, the other is a stop.
        """

        code, out = _run(["prepare", "2.8.6", "--summary", "x", "--json"], markers=MARKERS)

        self.assertEqual(code, prepare_release.EXIT_DOCUMENTS_OPEN)
        receipt = json.loads(out)
        self.assertEqual(receipt["status"], "documents-open")
        self.assertEqual(receipt["placeholders"], list(MARKERS))

    def test_a_failed_step_stops_rather_than_retries(self) -> None:
        stdout = io.StringIO()
        with mock.patch.object(
            prepare_release, "_shell", side_effect=prepare_release.Stopped("gates failed")
        ):
            with mock.patch("sys.stdout", stdout):
                code = prepare_release.main(["prepare", "2.8.6", "--summary", "x", "--json"])

        self.assertEqual(code, prepare_release.EXIT_STOPPED)
        self.assertEqual(json.loads(stdout.getvalue())["status"], "stopped")


class HumanSurfaceTest(unittest.TestCase):
    def test_the_version_is_asked_for_when_it_is_not_given(self) -> None:
        with mock.patch("builtins.input", return_value="v2.8.6"):
            code, stdout_text = _run(["prepare"])

        self.assertEqual(code, prepare_release.EXIT_OK)
        stdout = io.StringIO(stdout_text)
        # A leading `v` is what a person types who has just looked at a tag.
        self.assertIn("2.8.6 is prepared", stdout.getvalue())

    def test_with_nobody_to_ask_it_refuses_rather_than_guesses(self) -> None:
        """A missing answer with nowhere to ask is a refusal, not a default.

        Guessing the version here would set six files to a number nobody chose, and the run after
        it would look like it worked.
        """

        code, out = _run(["prepare"], tty=False)

        self.assertEqual(code, prepare_release.EXIT_STOPPED)
        self.assertNotIn("is prepared", out)


if __name__ == "__main__":
    unittest.main()
