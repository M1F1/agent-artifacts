"""The order of a release, and what happens when a step is not ready.

The value of `cut_release.py` is not that it types faster.  It is that a release either passes
every precondition or produces nothing at all: no tag, no release, nothing half-published to undo
by hand.  So these tests are mostly about refusals, and about one thing more than the refusal
itself -- that a refusal reaches the operator naming the fix, not just the failure.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import cut_release  # noqa: E402

TAG = "v2.9.0"


def _result(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=(), returncode=returncode, stdout=stdout, stderr="")


class _Git:
    """Answers git by first argument, and records everything it was asked."""

    def __init__(self, **answers: subprocess.CompletedProcess[str]) -> None:
        self.answers = answers
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        self.calls.append(arguments)
        return self.answers.get(arguments[0], _result())


def _clean_repository(**overrides: subprocess.CompletedProcess[str]) -> _Git:
    """A checkout with nothing to complain about, before any override."""

    answers = {
        "status": _result(""),  # clean worktree
        "ls-remote": _result(""),  # the tag does not exist yet
        "merge-base": _result(returncode=0),  # HEAD is in main
        "rev-parse": _result("abc1234"),
    }
    answers.update(overrides)
    return _Git(**answers)


class PreconditionsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.notes = mock.MagicMock(spec=Path)
        self.notes.exists.return_value = True
        self.notes.read_text.return_value = "Real notes.\n"
        # `check-tag` is a subprocess; the versions agreeing is not what these tests are about.
        patched = mock.patch.object(cut_release, "_run")
        self.run = patched.start()
        self.addCleanup(patched.stop)

    def _refusal(self, git: _Git) -> str:
        with mock.patch.object(cut_release, "_git", git):
            with self.assertRaises(cut_release.Refused) as raised:
                cut_release.preconditions("2.9.0", TAG, self.notes, "origin")
        return str(raised.exception)

    def test_a_dirty_worktree_is_refused_before_anything_else_runs(self) -> None:
        """A release built from uncommitted work is a release nobody can reproduce."""

        git = _clean_repository(status=_result(" M scripts/release.py\n"))
        said = self._refusal(git)
        self.assertIn("uncommitted changes", said)
        # And it stopped there: the version check is a subprocess, and it never ran.
        self.run.assert_not_called()

    def test_missing_notes_are_refused_with_the_reason_they_matter(self) -> None:
        self.notes.read_text.return_value = "   \n"
        said = self._refusal(_clean_repository())
        self.assertIn("release notes", said)
        # Not merely "missing file": the point is that notes written afterwards are unread.
        self.assertIn("nobody read", said)

    def test_a_tag_that_already_exists_is_refused_with_the_way_out(self) -> None:
        """`v2.8.5 already exists` was a real dead end in the Enterprise walk.

        The refusal carries the command that clears it, because the safe case (a tag pushed but
        never released) and the unsafe one (a published version) look identical from here and only
        the operator can tell them apart.
        """

        git = _clean_repository()
        git.answers["ls-remote"] = _result("abc\trefs/tags/v2.9.0\n")
        said = self._refusal(git)
        self.assertIn("already exists", said)
        self.assertIn(f"git push origin :refs/tags/{TAG}", said)

    def test_a_commit_outside_main_is_refused(self) -> None:
        git = _clean_repository()
        git.answers["merge-base"] = _result(returncode=1)
        said = self._refusal(git)
        self.assertIn("not in origin/main", said)
        self.assertIn("no one reviewed", said)

    def test_a_ready_repository_passes_and_writes_nothing(self) -> None:
        git = _clean_repository()
        with mock.patch.object(cut_release, "_git", git):
            cut_release.preconditions("2.9.0", TAG, self.notes, "origin")
        written = [call[0] for call in git.calls]
        for verb in ("tag", "push", "commit"):
            self.assertNotIn(verb, written)


class ExitCodeTest(unittest.TestCase):
    def test_a_refusal_exits_non_zero_and_says_so_on_stderr(self) -> None:
        with mock.patch.object(cut_release, "preconditions", side_effect=cut_release.Refused("no")):
            self.assertEqual(cut_release.main(["cut", "2.9.0", "--without-registry"]), 2)


if __name__ == "__main__":
    unittest.main()
