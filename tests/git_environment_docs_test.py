"""`LAF-49`: the Git subprocess environment is documented, and the document is fed from the code.

AART runs system Git with an allowlisted environment, so `https_proxy` never reaches it. That is
deliberate — a proxy URL is one of the places a credential hides — and on a network whose only
egress is a proxy it means every clone fails with a transport error that says nothing about the
proxy having been dropped. The workaround exists and nothing named it.

A page can be written once and drift. So the list it publishes is compared against
`_ALLOWED_ENVIRONMENT` itself, and every variable it claims is dropped is put through the real
`_safe_environment` to confirm it is.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from agent_artifacts.io.git import _ALLOWED_ENVIRONMENT, _safe_environment

_ROOT = Path(__file__).resolve().parent.parent
_REFERENCE = _ROOT / "docs/configuration/git-environment-v1.md"
_ROW = re.compile(r"^\| `([A-Za-z][A-Za-z0-9_]*)` \|", re.MULTILINE)


def _section(title: str) -> str:
    """The body under one `##` heading, so each table is read where it is published."""

    text = _REFERENCE.read_text()
    body = text.split(f"\n## {title}\n", 1)[1]
    return body.split("\n## ", 1)[0]


def _variables(title: str) -> set[str]:
    return set(_ROW.findall(_section(title)))


class GitEnvironmentReferenceTest(unittest.TestCase):
    def test_the_document_publishes_the_allowlist_the_code_applies(self) -> None:
        self.assertEqual(_variables("What Git receives"), set(_ALLOWED_ENVIRONMENT))

    def test_every_variable_the_document_calls_dropped_is_dropped(self) -> None:
        named = _variables("What Git does not receive")
        self.assertIn("https_proxy", named)

        environment = {name: "http://user:pw@proxy.example:3128" for name in named}
        environment["HOME"] = "/home/operator"
        passed = _safe_environment(environment)

        for name in named:
            with self.subTest(name=name):
                self.assertNotIn(name, passed)

    def test_the_workaround_the_document_offers_rests_on_a_variable_that_survives(self) -> None:
        # The page tells the operator to put the proxy in `~/.gitconfig`.  That works only because
        # `HOME` is passed, which is what makes the advice more than a guess.
        self.assertIn("http.proxy", _section("What Git does not receive"))
        self.assertIn("HOME", _safe_environment({"HOME": "/home/operator", "https_proxy": "x"}))

    def test_the_values_aart_forces_are_published_as_forced_not_inherited(self) -> None:
        passed = _safe_environment({"GIT_TERMINAL_PROMPT": "1", "LC_ALL": "fr_FR.UTF-8"})

        self.assertEqual(_variables("What AART sets"), {"GIT_TERMINAL_PROMPT", "LC_ALL"})
        self.assertEqual(passed["GIT_TERMINAL_PROMPT"], "0")
        self.assertEqual(passed["LC_ALL"], "C")


if __name__ == "__main__":
    unittest.main()
