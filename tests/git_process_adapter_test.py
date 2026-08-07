from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.io.git import GitProcessRequest, run_git_process


class GitProcessAdapterTest(unittest.TestCase):
    def test_runner_uses_fixed_argv_shell_false_sanitized_environment_and_bounds_output(
        self,
    ) -> None:
        completed = subprocess.CompletedProcess(
            ["git", "version"],
            0,
            stdout=b"0123456789",
            stderr=b"warning",
        )
        request = GitProcessRequest(("git", "version"), "/work", 10, max_output_bytes=4)
        environment = {
            "PATH": "/bin",
            "HOME": "/fake/home",
            "SSH_AUTH_SOCK": "/fake/agent",
            "GITHUB_TOKEN": "must-not-leak",
            "GIT_ASKPASS": "/evil/helper",
            "LC_ALL": "unsafe",
        }

        with patch("agent_artifacts.io.git.subprocess.run", return_value=completed) as called:
            result = run_git_process(request, environ=environment)

        self.assertIsInstance(result, Ok)
        assert isinstance(result, Ok)
        self.assertEqual(result.value.stdout, b"0123")
        self.assertEqual(result.value.stderr, b"warn")
        args, kwargs = called.call_args
        self.assertEqual(args[0], ("git", "version"))
        self.assertFalse(kwargs["shell"])
        self.assertEqual(kwargs["cwd"], "/work")
        self.assertEqual(kwargs["timeout"], 10)
        self.assertEqual(kwargs["env"]["LC_ALL"], "C")
        self.assertNotIn("GITHUB_TOKEN", kwargs["env"])
        self.assertNotIn("GIT_ASKPASS", kwargs["env"])

    def test_auth_errors_timeouts_and_missing_git_are_typed_and_redacted(self) -> None:
        secret_url = "https://user:secret@example.test/repo.git"
        request = GitProcessRequest(("git", "fetch", secret_url), "/work", 1)
        failed = subprocess.CompletedProcess(
            list(request.argv),
            128,
            stdout=b"",
            stderr=f"Authentication failed for {secret_url} token=top-secret".encode(),
        )
        with patch("agent_artifacts.io.git.subprocess.run", return_value=failed):
            auth = run_git_process(request, environ={"PATH": "/bin"})
        self.assertIsInstance(auth, Err)
        assert isinstance(auth, Err)
        self.assertEqual(auth.diagnostics[0].code.value, "source-auth-failed")
        self.assertNotIn("secret", auth.diagnostics[0].message)

        timeout = subprocess.TimeoutExpired(list(request.argv), 1, output=b"token=late")
        with patch("agent_artifacts.io.git.subprocess.run", side_effect=timeout):
            timed_out = run_git_process(request, environ={"PATH": "/bin"})
        self.assertIsInstance(timed_out, Err)
        assert isinstance(timed_out, Err)
        self.assertEqual(timed_out.diagnostics[0].code.value, "source-unavailable")
        self.assertNotIn("late", timed_out.diagnostics[0].message)

        with patch("agent_artifacts.io.git.subprocess.run", side_effect=FileNotFoundError("git")):
            missing = run_git_process(request, environ={})
        self.assertIsInstance(missing, Err)
        assert isinstance(missing, Err)
        self.assertIn("install Git", missing.diagnostics[0].remediation)

        unavailable = subprocess.CompletedProcess(
            list(request.argv), 1, stdout=b"ordinary failure", stderr=None
        )
        with patch("agent_artifacts.io.git.subprocess.run", return_value=unavailable):
            failed = run_git_process(request, environ={})
        self.assertIsInstance(failed, Err)
        assert isinstance(failed, Err)
        self.assertEqual(failed.diagnostics[0].code.value, "source-unavailable")

        with patch("agent_artifacts.io.git.subprocess.run", side_effect=OSError("cannot exec")):
            os_error = run_git_process(request, environ={})
        self.assertIsInstance(os_error, Err)

    def test_request_rejects_shell_strings_relative_cwd_and_invalid_bounds(self) -> None:
        invalid = (
            lambda: GitProcessRequest("git status", "/work", 1),  # type: ignore[arg-type]
            lambda: GitProcessRequest(("sh", "-c", "git status"), "/work", 1),
            lambda: GitProcessRequest(("git", "status"), "relative", 1),
            lambda: GitProcessRequest(("git", "status"), "/work", 0),
            lambda: GitProcessRequest(("git", "status"), "/work", 1, max_output_bytes=0),
            lambda: GitProcessRequest(("git", "sh"), "/work", 1),
            lambda: GitProcessRequest(("git", "bad\narg"), "/work", 1),
        )
        for constructor in invalid:
            with self.subTest(constructor=constructor), self.assertRaises(ValueError):
                constructor()


if __name__ == "__main__":
    unittest.main()
