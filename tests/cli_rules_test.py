"""Unit tests for the semantic flag-combination validator (agent_artifacts.cli_rules).

Pure-function tests: each case builds a :class:`Request` directly and asserts whether
``validate_flags`` returns ``None`` (accepted) or an ``Err(code=2)`` with the expected message.
The end-to-end wiring (cli.main -> stderr -> exit code) is covered in cli_test.py and
upstream_cli_test.py.
"""

import unittest

from agent_artifacts.cli_rules import validate_flags
from agent_artifacts.commands._common import USAGE
from agent_artifacts.model import Err, Request


def _req(command, **kw) -> Request:
    return Request(command=command, **kw)


class Class1SilentPrecedence(unittest.TestCase):
    """Two accepted flags that feed one decision, where the core silently drops one."""

    def test_repo_and_source_mutually_exclusive(self):
        err = validate_flags(_req("install", repo="o/r", source_dir="/src"))
        self.assertIsInstance(err, Err)
        self.assertEqual(err.code, USAGE)
        self.assertIn("--repo and --source are mutually exclusive", err.reason)

    def test_source_and_version_mutually_exclusive(self):
        err = validate_flags(_req("install", source_dir="/src", version="v1.2"))
        self.assertIsInstance(err, Err)
        self.assertIn("--source and --version are mutually exclusive", err.reason)

    def test_all_with_names_rejected(self):
        err = validate_flags(_req("install", all=True, names=("code-review",)))
        self.assertIsInstance(err, Err)
        self.assertIn("--all cannot be combined", err.reason)

    def test_all_with_bundles_rejected(self):
        err = validate_flags(_req("install", all=True, bundles=("base",)))
        self.assertIsInstance(err, Err)
        self.assertIn("--all cannot be combined", err.reason)

    def test_all_alone_is_fine(self):
        self.assertIsNone(validate_flags(_req("install", all=True, profiles=("claude",))))

    def test_all_with_type_is_fine(self):
        # --type filters the "all" set rather than competing with it.
        self.assertIsNone(validate_flags(_req("install", all=True, type_filter="skill")))

    def test_repo_alone_is_fine(self):
        self.assertIsNone(validate_flags(_req("install", repo="o/r")))

    def test_source_alone_is_fine(self):
        self.assertIsNone(validate_flags(_req("install", source_dir="/src")))

    def test_repo_with_version_is_fine(self):
        # A remote repo legitimately resolves an explicit ref.
        self.assertIsNone(validate_flags(_req("install", repo="o/r", version="v2")))


class AcceptedGlobals(unittest.TestCase):
    """Globals each command *does* consume stay valid (the happy paths)."""

    def test_status_accepts_repo_and_project(self):
        self.assertIsNone(validate_flags(_req("status", repo="o/r", project="./app")))

    def test_check_accepts_repo_project_version(self):
        self.assertIsNone(
            validate_flags(_req("check", repo="o/r", project="./app", version="main"))
        )

    def test_upgrade_accepts_repo_and_version(self):
        self.assertIsNone(validate_flags(_req("upgrade", repo="o/r", version="main")))

    def test_list_accepts_repo_source_version(self):
        # ... but not both repo and source at once; here only source + version-less.
        self.assertIsNone(validate_flags(_req("list", source_dir="/src")))
        self.assertIsNone(validate_flags(_req("list", repo="o/r", version="main")))

    def test_uninstall_accepts_project(self):
        self.assertIsNone(validate_flags(_req("uninstall", project="./app", all=True)))

    def test_upstream_accepts_source(self):
        self.assertIsNone(
            validate_flags(_req("upstream", upstream_action="check", source_dir="/catalog"))
        )

    def test_install_accepts_all_three_axes(self):
        self.assertIsNone(
            validate_flags(_req("install", repo="o/r", project="./app", profiles=("claude",)))
        )


if __name__ == "__main__":
    unittest.main()
