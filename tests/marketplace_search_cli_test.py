"""`marketplace search` over a real synchronized source, because that is where it is used.

The matcher has its own tests; these prove the command around it — that the words reach it, that
the answer names artifacts a person can then install by the coordinate printed, and that the JSON
an agent reads says which words matched where.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import unittest
from unittest import mock

from agent_artifacts import cli
from tests.marketplace_lifecycle_e2e_test import _environment


def _run(env, *argv: str) -> tuple[int, str]:
    """The real CLI, with this environment's home and project, returning raw stdout.

    `marketplace search` takes no `--project`, exactly like its sibling `marketplace list`: both
    read configured sources and the current directory, and adding the flag to one of the two would
    make the pair inconsistent for no gain.
    """

    stdout = io.StringIO()
    with (
        mock.patch.dict(os.environ, env.xdg, clear=False),
        contextlib.redirect_stdout(stdout),
        mock.patch("os.getcwd", return_value=str(env.project)),
    ):
        code = cli.main(list(argv))
    return code, stdout.getvalue()


class SearchCommandTest(unittest.TestCase):
    def test_a_word_finds_the_artifact_whose_name_holds_it(self):
        with _environment() as env:
            code, out = _run(env, "marketplace", "search", "review")

        self.assertEqual(0, code, out)
        self.assertIn("reference/skill/code-review@1.0.0", out)
        self.assertIn("(name", out)

    def test_the_summary_line_says_how_much_of_the_catalog_answered(self):
        with _environment() as env:
            _code, out = _run(env, "marketplace", "search", "review")

        self.assertRegex(out.splitlines()[0], r"^\d+ of \d+ match 'review'\.$")

    def test_a_second_word_narrows_the_answer(self):
        with _environment() as env:
            _code, one = _run(env, "marketplace", "search", "review")
            _code, two = _run(env, "marketplace", "search", "review", "house")

        self.assertIn("code-review", one)
        self.assertNotIn("code-review", two)
        self.assertIn("Nothing matches 'review house'", two)

    def test_finding_nothing_is_not_a_failure_and_says_what_to_try(self):
        with _environment() as env:
            code, out = _run(env, "marketplace", "search", "kubernetes")

        self.assertEqual(0, code, out)
        self.assertIn("Nothing matches 'kubernetes'", out)
        self.assertIn("substring", out)

    def test_a_collection_is_searched_beside_the_artifacts(self):
        with _environment() as env:
            _code, out = _run(env, "marketplace", "search", "essentials")

        self.assertIn("reference/collection/essentials", out)
        self.assertIn("[collection]", out)

    def test_the_limit_keeps_the_best_row(self):
        with _environment() as env:
            _code, out = _run(env, "marketplace", "search", "review", "--limit", "1")

        printed = [line for line in out.splitlines() if line.startswith("  ")]
        self.assertEqual(1, len(printed), out)
        self.assertIn("code-review", printed[0])

    def test_a_limit_below_one_is_refused_rather_than_printing_nothing(self):
        with _environment() as env:
            code, out = _run(env, "marketplace", "search", "review", "--limit", "0", "--json")

        self.assertNotEqual(0, code)
        payload = json.loads(out)
        self.assertFalse(payload["ok"])
        self.assertEqual("marketplace.search", payload["operation"])

    def test_the_json_says_what_matched_and_where(self):
        with _environment() as env:
            code, out = _run(env, "marketplace", "search", "review", "--json")

        self.assertEqual(0, code, out)
        payload = json.loads(out)
        self.assertTrue(payload["ok"])
        self.assertEqual("marketplace.search", payload["operation"])
        self.assertEqual("review", payload["query"])
        best = payload["matches"][0]
        self.assertEqual("reference/skill/code-review@1.0.0", best["coordinate"])
        self.assertEqual("artifact", best["kind"])
        self.assertIn("name", best["matched"])
        self.assertGreater(best["score"], 0)
        self.assertGreaterEqual(payload["searched"], len(payload["matches"]))

    def test_the_coordinate_printed_is_the_one_install_takes(self):
        """A search whose answer cannot be pasted into the next command answers nothing."""

        with _environment() as env:
            _code, out = _run(env, "marketplace", "search", "review", "--json")
            coordinate = json.loads(out)["matches"][0]["coordinate"]
            code, payload = env.run(
                "marketplace", "install", coordinate, "--profile", "claude", "--yes"
            )

        self.assertEqual(0, code, payload)
        self.assertTrue(payload["finalized"])


if __name__ == "__main__":
    unittest.main()
