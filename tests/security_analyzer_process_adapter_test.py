from __future__ import annotations

import io
import subprocess
import time
import unittest
from unittest.mock import patch

from agent_artifacts.io.security_analyzers import resolve_executable, run_analyzer_process
from agent_artifacts.security.analyzers import (
    AnalyzerProcessKind,
    AnalyzerProcessRequest,
)


class _InputSink:
    def __init__(self) -> None:
        self.value = b""

    def write(self, value: bytes) -> int:
        self.value += value
        return len(value)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass


class _FakeProcess:
    def __init__(
        self,
        stdout: bytes = b"",
        stderr: bytes = b"",
        *,
        returncode: int = 0,
        times_out: bool = False,
    ) -> None:
        self.stdin = _InputSink()
        self.stdout = io.BytesIO(stdout)
        self.stderr = io.BytesIO(stderr)
        self.returncode = returncode
        self.times_out = times_out
        self.killed = False

    def wait(self, timeout: float | None = None) -> int:
        if self.times_out and not self.killed:
            raise subprocess.TimeoutExpired(("tool",), timeout)
        return self.returncode

    def kill(self) -> None:
        self.killed = True


class _DelayedStream:
    def read(self, _size: int) -> bytes:
        time.sleep(0.5)
        return b""

    def close(self) -> None:
        pass


class SecurityAnalyzerProcessAdapterTest(unittest.TestCase):
    def test_runner_uses_shell_false_minimal_environment_stdin_and_bounds(self) -> None:
        request = AnalyzerProcessRequest(
            ("/opt/analyzers/example", "--protocol"),
            "/immutable/object",
            b'{"action":"handshake"}',
            5,
            4,
        )
        process = _FakeProcess(b"012345", b"credential=secret")
        environment = {
            "PATH": "/custom/bin",
            "LANG": "pl_PL.UTF-8",
            "HOME": "/secret/home",
            "GITHUB_TOKEN": "secret",
            "AWS_SECRET_ACCESS_KEY": "secret",
        }

        with patch(
            "agent_artifacts.io.security_analyzers.subprocess.Popen", return_value=process
        ) as called:
            result = run_analyzer_process(request, environ=environment)

        self.assertEqual(result.kind, AnalyzerProcessKind.OUTPUT_LIMIT)
        self.assertTrue(process.killed)
        self.assertEqual(process.stdin.value, request.stdin)
        _args, kwargs = called.call_args
        self.assertFalse(kwargs["shell"])
        self.assertEqual(kwargs["cwd"], request.cwd)
        self.assertEqual(kwargs["stdin"], subprocess.PIPE)
        self.assertEqual(kwargs["stdout"], subprocess.PIPE)
        self.assertEqual(kwargs["stderr"], subprocess.PIPE)
        self.assertEqual(kwargs["env"]["LC_ALL"], "C")
        self.assertEqual(kwargs["env"]["PATH"], "/custom/bin")
        self.assertNotIn("HOME", kwargs["env"])
        self.assertNotIn("GITHUB_TOKEN", kwargs["env"])

    def test_timeout_missing_and_os_errors_have_secret_free_kinds(self) -> None:
        request = AnalyzerProcessRequest(("/opt/example",), "/object", b"{}", 1, 32)
        process = _FakeProcess(stderr=b"secret", times_out=True)
        with patch("agent_artifacts.io.security_analyzers.subprocess.Popen", return_value=process):
            timed_out = run_analyzer_process(request, environ={})
        self.assertEqual(timed_out.kind, AnalyzerProcessKind.TIMED_OUT)
        self.assertTrue(process.killed)

        failures = (
            (FileNotFoundError("secret path"), AnalyzerProcessKind.UNAVAILABLE),
            (OSError("token=secret"), AnalyzerProcessKind.FAILED_TO_START),
        )
        for error, expected in failures:
            with (
                self.subTest(expected=expected),
                patch("agent_artifacts.io.security_analyzers.subprocess.Popen", side_effect=error),
            ):
                outcome = run_analyzer_process(request, environ={})
                self.assertEqual(outcome.kind, expected)
                self.assertEqual(outcome.stdout, b"")
                self.assertEqual(outcome.stderr, b"")

    def test_successful_process_returns_only_bounded_streams(self) -> None:
        request = AnalyzerProcessRequest(("/opt/example",), "/object", b"request", 1, 32)
        process = _FakeProcess(b"response", b"warning", returncode=1)
        with patch("agent_artifacts.io.security_analyzers.subprocess.Popen", return_value=process):
            outcome = run_analyzer_process(request, environ={})
        self.assertEqual(outcome.kind, AnalyzerProcessKind.COMPLETED)
        self.assertEqual(outcome.returncode, 1)
        self.assertEqual(outcome.stdout, b"response")
        self.assertEqual(outcome.stderr, b"warning")

    def test_inherited_pipe_that_never_closes_cannot_hang_the_caller(self) -> None:
        request = AnalyzerProcessRequest(("/opt/example",), "/object", b"", 1, 32)
        process = _FakeProcess()
        process.stdout = _DelayedStream()  # type: ignore[assignment]
        started = time.monotonic()
        with patch("agent_artifacts.io.security_analyzers.subprocess.Popen", return_value=process):
            outcome = run_analyzer_process(request, environ={})
        self.assertLess(time.monotonic() - started, 0.4)
        self.assertEqual(outcome.kind, AnalyzerProcessKind.FAILED_TO_START)

    def test_request_rejects_shell_relative_executable_and_invalid_bounds(self) -> None:
        invalid = (
            lambda: AnalyzerProcessRequest(("sh", "-c", "bad"), "/object", b"{}", 1, 4),
            lambda: AnalyzerProcessRequest(("relative",), "/object", b"{}", 1, 4),
            lambda: AnalyzerProcessRequest(("/opt/../bin/tool",), "/object", b"{}", 1, 4),
            lambda: AnalyzerProcessRequest(("/opt/tool", "bad\narg"), "/object", b"{}", 1, 4),
            lambda: AnalyzerProcessRequest(("/opt/tool",), "relative", b"{}", 1, 4),
            lambda: AnalyzerProcessRequest(("/opt/tool",), "/", b"{}", 1, 4),
            lambda: AnalyzerProcessRequest(("/opt/tool",), "/object", b"{}", 0, 4),
            lambda: AnalyzerProcessRequest(("/opt/tool",), "/object", b"{}", 1, 0),
        )
        for constructor in invalid:
            with self.subTest(constructor=constructor), self.assertRaises(ValueError):
                constructor()

    def test_resolution_returns_only_absolute_executable_files(self) -> None:
        with patch("agent_artifacts.io.security_analyzers.shutil.which", return_value="relative"):
            self.assertIsNone(resolve_executable("example"))
        with patch("agent_artifacts.io.security_analyzers.shutil.which", return_value="/bin/sh"):
            self.assertIsNone(resolve_executable("example"))
        with patch(
            "agent_artifacts.io.security_analyzers.shutil.which", return_value="/opt/example"
        ):
            self.assertEqual(resolve_executable("example"), "/opt/example")


if __name__ == "__main__":
    unittest.main()
