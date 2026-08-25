from __future__ import annotations

import unittest

from agent_artifacts.domain.result import Ok
from agent_artifacts.protocol.hashing import sha256_bytes
from agent_artifacts.protocol.paths import parse_relative_path
from agent_artifacts.security.analyzers import (
    AnalyzerInput,
    AnalyzerProcessKind,
    AnalyzerProcessOutcome,
)
from agent_artifacts.security.model import AssessmentStatus, FindingSeverity
from agent_artifacts.security.tool_adapters import (
    BUILTIN_TOOL_ADAPTERS,
    BuiltInToolAdapter,
    DiscoveredToolAdapter,
    discover_tool_adapters,
    run_tool_adapter,
)
from tests.credential_fixtures import assignment_bytes


def _input(*paths: str) -> AnalyzerInput:
    files = []
    contents = []
    for raw in paths or ("payload/main.py",):
        path = parse_relative_path(raw)
        assert isinstance(path, Ok)
        content = b"demo==1.0\n" if raw.endswith("requirements.txt") else b"x" * 20
        files.append((path.value, len(content)))
        contents.append((path.value, content))
    return AnalyzerInput(
        sha256_bytes(b"tool-object"),
        "/immutable/objects/sha256/tool-object",
        "skill",
        tuple(files),
        tuple(contents),
    )


def _adapter(provider_id: str) -> DiscoveredToolAdapter:
    adapter = next(item for item in BUILTIN_TOOL_ADAPTERS if item.provider_id == provider_id)
    return DiscoveredToolAdapter(adapter, f"/opt/security-tools/{adapter.executable}")


def _run(provider_id: str, output: bytes, *, paths: tuple[str, ...] = ("payload/main.py",)):
    calls = []
    outcomes = [
        AnalyzerProcessOutcome(AnalyzerProcessKind.COMPLETED, 0, b"tool 1.2.3\n", b""),
        AnalyzerProcessOutcome(AnalyzerProcessKind.COMPLETED, 0, output, b""),
    ]

    def runner(request):  # type: ignore[no-untyped-def]
        calls.append(request)
        return outcomes.pop(0)

    return (
        run_tool_adapter(
            _adapter(provider_id),
            _input(*paths),
            runner=runner,
            allow_network=provider_id == "pip-audit",
        ),
        calls,
    )


class SecurityToolAdaptersTest(unittest.TestCase):
    def test_initial_reviewed_set_is_explicit_and_has_no_python_dependencies(self) -> None:
        self.assertEqual(
            tuple(item.provider_id for item in BUILTIN_TOOL_ADAPTERS),
            ("ruff", "bandit", "detect-secrets", "pip-audit", "shellcheck"),
        )
        self.assertEqual(
            tuple(item.capability for item in BUILTIN_TOOL_ADAPTERS),
            (
                "python-static",
                "python-static",
                "secret-detection",
                "dependency-advisories",
                "shell-static",
            ),
        )

    def test_discovery_reports_installed_and_missing_without_installing(self) -> None:
        looked_up = []

        def resolver(name: str) -> str | None:
            looked_up.append(name)
            return f"/opt/{name}" if name in {"ruff", "shellcheck"} else None

        discovered = discover_tool_adapters(resolver=resolver)

        self.assertEqual(looked_up, [item.executable for item in BUILTIN_TOOL_ADAPTERS])
        self.assertEqual(
            tuple(item.available for item in discovered),
            (True, False, False, False, True),
        )

    def test_adapter_and_discovery_values_reject_unsafe_commands_and_paths(self) -> None:
        valid = BUILTIN_TOOL_ADAPTERS[0]
        invalid_adapters = (
            lambda: BuiltInToolAdapter(
                "Bad", "ruff", "python-static", (".py",), False, ("--version",), (), (0,), "ruff"
            ),
            lambda: BuiltInToolAdapter(
                "ruff", "sh", "python-static", (".py",), False, ("--version",), (), (0,), "ruff"
            ),
            lambda: BuiltInToolAdapter(
                "ruff", "ruff", "", (".py",), False, ("--version",), (), (0,), "ruff"
            ),
            lambda: BuiltInToolAdapter(
                "ruff",
                "ruff",
                "bad capability",
                (".py",),
                False,
                ("--version",),
                (),
                (0,),
                "ruff",
            ),
            lambda: BuiltInToolAdapter(
                "ruff", "ruff", "python-static", ("py",), False, ("--version",), (), (0,), "ruff"
            ),
            lambda: BuiltInToolAdapter(
                "ruff",
                "ruff",
                "python-static",
                (".py",),
                "yes",
                ("--version",),
                (),
                (0,),
                "ruff",
            ),
            lambda: BuiltInToolAdapter(
                "ruff", "ruff", "python-static", (".py",), False, (), (), (0,), "ruff"
            ),
            lambda: BuiltInToolAdapter(
                "ruff",
                "ruff",
                "python-static",
                (".py",),
                False,
                ("--version",),
                ("check",),
                [0],  # type: ignore[arg-type]
                "ruff",
            ),
            lambda: BuiltInToolAdapter(
                "ruff", "ruff", "python-static", (".py",), False, ("--version",), (), (1,), "ruff"
            ),
            lambda: BuiltInToolAdapter(
                "ruff", "ruff", "python-static", (".py",), False, ("--version",), (), (0,), "other"
            ),
        )
        for constructor in invalid_adapters:
            with self.subTest(constructor=constructor), self.assertRaises(ValueError):
                constructor()
        for path in ("relative", "/"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                DiscoveredToolAdapter(valid, path)
        with self.assertRaises(ValueError):
            DiscoveredToolAdapter(valid, "/bin/sh")

        unsafe_discovery = discover_tool_adapters(resolver=lambda _name: "/bin/sh")
        self.assertTrue(all(not item.available for item in unsafe_discovery))

    def test_rules_digest_binds_adapter_policy_not_only_parser_arguments(self) -> None:
        base = BUILTIN_TOOL_ADAPTERS[0]
        changed = BuiltInToolAdapter(
            base.provider_id,
            base.executable,
            base.capability,
            base.file_extensions,
            base.network_required,
            base.version_args,
            base.scan_args,
            (0, 1, 2),
            base.parser,
            base.rules_revision,
        )
        self.assertNotEqual(base.rules_digest, changed.rules_digest)

    def test_missing_adapter_is_not_scanned_and_does_not_call_runner(self) -> None:
        adapter = BUILTIN_TOOL_ADAPTERS[0]
        result = run_tool_adapter(
            DiscoveredToolAdapter(adapter, None),
            _input(),
            runner=lambda _request: self.fail("missing tool must not run"),
        )
        self.assertEqual(result.status, AssessmentStatus.NOT_SCANNED)
        self.assertIn("not installed", result.detail)

    def test_ruff_adapter_uses_fixed_json_argv_and_safe_normalized_finding(self) -> None:
        output = (
            b'[{"code":"S602","filename":"payload/main.py",'
            b'"location":{"column":1,"row":7},"message":"'
            + assignment_bytes("token", "must-not-echo")
            + b'"}]'
        )
        result, calls = _run("ruff", output)

        self.assertEqual(result.status, AssessmentStatus.COMPLETE)
        self.assertEqual(result.descriptor.version, "1.2.3")  # type: ignore[union-attr]
        self.assertEqual(result.findings[0].rule_id, "s602")
        self.assertEqual(result.findings[0].severity, FindingSeverity.MEDIUM)
        self.assertNotIn("must-not-echo", result.findings[0].message)
        self.assertEqual(
            calls[1].argv,
            (
                "/opt/security-tools/ruff",
                "check",
                "--isolated",
                "--ignore-noqa",
                "--output-format=json",
                "--no-cache",
                ".",
            ),
        )
        self.assertEqual(calls[1].stdin, b"")

    def test_bandit_adapter_maps_severity_without_copying_raw_message(self) -> None:
        output = (
            b'{"errors":[],"results":[{"filename":"payload/main.py",'
            b'"issue_severity":"HIGH","issue_text":"'
            + assignment_bytes("credential", "secret")
            + b'",'
            b'"line_number":2,"test_id":"B602"}]}'
        )
        result, calls = _run("bandit", output)
        self.assertEqual(result.status, AssessmentStatus.COMPLETE)
        self.assertEqual(result.findings[0].rule_id, "b602")
        self.assertEqual(result.findings[0].severity, FindingSeverity.HIGH)
        self.assertNotIn("secret", result.findings[0].message)
        self.assertEqual(
            calls[1].argv,
            (
                "/opt/security-tools/bandit",
                "--ini",
                "/dev/null",
                "--ignore-nosec",
                "-r",
                ".",
                "-f",
                "json",
                "-q",
            ),
        )

    def test_detect_secrets_adapter_never_echoes_secret_or_hash(self) -> None:
        output = (
            b'{"results":{"payload/main.py":[{"hashed_secret":"abc123",'
            b'"is_verified":false,"line_number":3,"type":"AWS Access Key"}]},'
            b'"version":"1.2.3"}'
        )
        result, _calls = _run("detect-secrets", output)
        self.assertEqual(result.status, AssessmentStatus.COMPLETE)
        self.assertEqual(result.findings[0].rule_id, "credential-pattern-aws-access-key")
        self.assertEqual(result.findings[0].severity, FindingSeverity.HIGH)
        self.assertNotIn("abc123", result.findings[0].message)
        self.assertNotIn("AWS", result.findings[0].message)

    def test_detect_secrets_keeps_distinct_detector_rules_at_the_same_location(self) -> None:
        output = (
            b'{"results":{"payload/main.py":['
            b'{"line_number":3,"type":"AWS Access Key"},'
            b'{"line_number":3,"type":"Secret Keyword"}]}}'
        )
        result, _calls = _run("detect-secrets", output)
        self.assertEqual(result.status, AssessmentStatus.COMPLETE)
        self.assertEqual(
            tuple(item.rule_id for item in result.findings),
            ("credential-pattern-aws-access-key", "credential-pattern-secret-keyword"),
        )

    def test_pip_audit_requires_explicit_network_and_maps_advisories(self) -> None:
        discovered = _adapter("pip-audit")
        blocked = run_tool_adapter(
            discovered,
            _input("payload/requirements.txt"),
            runner=lambda _request: self.fail("network-blocked tool must not run"),
        )
        self.assertEqual(blocked.status, AssessmentStatus.NOT_SCANNED)
        self.assertIn("network", blocked.detail)

        output = (
            b'[{"name":"demo","version":"1",'
            b'"vulns":[{"aliases":["CVE-2025-0001"],"description":"'
            + assignment_bytes("token", "secret")
            + b'",'
            b'"fix_versions":["2"],"id":"PYSEC-2025-1"}]}]'
        )
        calls = []
        outcomes = [
            AnalyzerProcessOutcome(AnalyzerProcessKind.COMPLETED, 0, b"pip-audit 2.7.3\n", b""),
            AnalyzerProcessOutcome(AnalyzerProcessKind.COMPLETED, 1, output, b""),
        ]
        result = run_tool_adapter(
            discovered,
            _input("payload/requirements.txt"),
            runner=lambda request: (calls.append(request), outcomes.pop(0))[1],
            allow_network=True,
        )
        self.assertEqual(result.status, AssessmentStatus.COMPLETE)
        self.assertEqual(result.findings[0].rule_id, "pysec-2025-1")
        self.assertEqual(result.findings[0].severity, FindingSeverity.MEDIUM)
        self.assertIsNone(result.findings[0].path)
        self.assertNotIn("secret", result.findings[0].message)
        self.assertEqual(
            calls[1].argv,
            (
                "/opt/security-tools/pip-audit",
                "--format=json",
                "--progress-spinner=off",
                "--disable-pip",
                "--no-deps",
                "--requirement",
                "-",
            ),
        )
        self.assertEqual(calls[1].stdin, b"demo==1.0\n")

    def test_pip_audit_rejects_unpinned_options_urls_and_includes_before_process_start(
        self,
    ) -> None:
        path = parse_relative_path("payload/requirements.txt")
        assert isinstance(path, Ok)
        unsafe = (b"demo>=1\n", b"-r /etc/passwd\n", b"demo @ https://example.test/x.whl\n")
        for content in unsafe:
            analyzer_input = AnalyzerInput(
                _input().object_digest,
                _input().root,
                "skill",
                ((path.value, len(content)),),
                ((path.value, content),),
            )
            with self.subTest(content=content):
                result = run_tool_adapter(
                    _adapter("pip-audit"),
                    analyzer_input,
                    runner=lambda _request: self.fail("unsafe requirements must not run"),
                    allow_network=True,
                )
                self.assertEqual(result.status, AssessmentStatus.NOT_SCANNED)
                self.assertIn("requirements", result.detail)

    def test_pip_audit_canonicalizes_multiple_hashed_inputs_and_requires_content(self) -> None:
        development = parse_relative_path("payload/requirements-dev.txt")
        production = parse_relative_path("payload/requirements.txt")
        assert isinstance(development, Ok)
        assert isinstance(production, Ok)
        digest = b"a" * 64
        first = b"Zoo_Pkg==2.0 --hash=sha256:" + digest + b"\n"
        second = b"alpha.pkg==1.0\n"
        analyzer_input = AnalyzerInput(
            _input().object_digest,
            _input().root,
            "skill",
            ((development.value, len(first)), (production.value, len(second))),
            ((development.value, first), (production.value, second)),
        )
        calls = []
        outcomes = [
            AnalyzerProcessOutcome(AnalyzerProcessKind.COMPLETED, 0, b"pip-audit 2.7.3\n", b""),
            AnalyzerProcessOutcome(AnalyzerProcessKind.COMPLETED, 0, b"[]", b""),
        ]

        result = run_tool_adapter(
            _adapter("pip-audit"),
            analyzer_input,
            runner=lambda request: (calls.append(request), outcomes.pop(0))[1],
            allow_network=True,
        )

        self.assertEqual(result.status, AssessmentStatus.COMPLETE)
        self.assertEqual(calls[1].stdin, second + first)
        missing_content = AnalyzerInput(
            _input().object_digest,
            _input().root,
            "skill",
            ((production.value, len(second)),),
        )
        missing = run_tool_adapter(
            _adapter("pip-audit"),
            missing_content,
            runner=lambda _request: self.fail("missing content must not run"),
            allow_network=True,
        )
        self.assertEqual(missing.status, AssessmentStatus.NOT_SCANNED)

    def test_shellcheck_scans_only_declared_shell_files_and_maps_level(self) -> None:
        output = (
            b'[{"code":2086,"column":1,"endColumn":2,"endLine":4,'
            b'"file":"payload/install.sh","fix":null,"level":"warning",'
            b'"line":4,"message":"raw shell text"}]'
        )
        result, calls = _run(
            "shellcheck", output, paths=("payload/install.sh", "payload/readme.md")
        )
        self.assertEqual(result.status, AssessmentStatus.COMPLETE)
        self.assertEqual(result.findings[0].rule_id, "sc2086")
        self.assertEqual(result.findings[0].severity, FindingSeverity.MEDIUM)
        self.assertEqual(
            calls[1].argv,
            (
                "/opt/security-tools/shellcheck",
                "--format=json1",
                "--norc",
                "--",
                "payload/install.sh",
            ),
        )

    def test_shellcheck_json1_object_and_absolute_input_path_are_supported(self) -> None:
        root = "/immutable/objects/sha256/tool-object"
        output = (
            b'{"comments":[{"code":100,"file":"'
            + root.encode()
            + b'/payload/install.sh","level":"error","line":1}]}'
        )
        result, _calls = _run("shellcheck", output, paths=("payload/install.sh",))
        self.assertEqual(result.status, AssessmentStatus.COMPLETE)
        self.assertEqual(result.findings[0].severity, FindingSeverity.HIGH)
        self.assertEqual(str(result.findings[0].path), "payload/install.sh")

    def test_no_relevant_files_is_not_scanned(self) -> None:
        result = run_tool_adapter(
            _adapter("shellcheck"),
            _input("payload/readme.md"),
            runner=lambda _request: self.fail("empty plan must not run"),
        )
        self.assertEqual(result.status, AssessmentStatus.NOT_SCANNED)
        self.assertIn("relevant files", result.detail)

    def test_dynamic_argv_limit_is_a_not_scanned_outcome_and_network_consent_is_boolean(
        self,
    ) -> None:
        paths = tuple(f"payload/script-{index}.sh" for index in range(64))
        result = run_tool_adapter(
            _adapter("shellcheck"),
            _input(*paths),
            runner=lambda _request: self.fail("oversized argv plan must not run"),
        )
        self.assertEqual(result.status, AssessmentStatus.NOT_SCANNED)
        self.assertIn("input limits", result.detail)

        too_long = "payload/" + "x" * 1014 + ".sh"
        long_path_result = run_tool_adapter(
            _adapter("shellcheck"),
            _input(too_long),
            runner=lambda _request: self.fail("oversized argv value must not run"),
        )
        self.assertEqual(long_path_result.status, AssessmentStatus.NOT_SCANNED)
        self.assertIn("input limits", long_path_result.detail)

        with self.assertRaises(ValueError):
            run_tool_adapter(
                _adapter("pip-audit"),
                _input("payload/requirements.txt"),
                runner=lambda _request: self.fail(),
                allow_network=1,  # type: ignore[arg-type]
            )

    def test_malformed_crashed_and_duplicate_native_outputs_fail_closed(self) -> None:
        duplicate = (
            b'[{"code":"S602","filename":"payload/main.py","location":{"row":7}},'
            b'{"code":"S602","filename":"payload/main.py","location":{"row":7}}]'
        )
        for output in (b"not-json", duplicate):
            with self.subTest(output=output[:30]):
                result, _calls = _run("ruff", output)
                self.assertEqual(result.status, AssessmentStatus.FAILED)

        outcomes = [
            AnalyzerProcessOutcome(AnalyzerProcessKind.COMPLETED, 0, b"ruff 1.2.3\n", b""),
            AnalyzerProcessOutcome(AnalyzerProcessKind.TIMED_OUT),
        ]
        result = run_tool_adapter(
            _adapter("ruff"),
            _input(),
            runner=lambda _request: outcomes.pop(0),
        )
        self.assertEqual(result.status, AssessmentStatus.FAILED)

    def test_version_and_exit_failures_are_bounded_and_do_not_expose_output(self) -> None:
        version_failures = (
            AnalyzerProcessOutcome(AnalyzerProcessKind.TIMED_OUT),
            AnalyzerProcessOutcome(AnalyzerProcessKind.COMPLETED, 2, b"ruff 1.0\n", b"secret"),
            AnalyzerProcessOutcome(AnalyzerProcessKind.COMPLETED, 0, b"no version", b"secret"),
            AnalyzerProcessOutcome(AnalyzerProcessKind.COMPLETED, 0, b"\xff", b""),
            AnalyzerProcessOutcome(AnalyzerProcessKind.COMPLETED, 0, b"1" * 100, b""),
            AnalyzerProcessOutcome(AnalyzerProcessKind.COMPLETED, 0, b"1" * 5000, b""),
        )
        for outcome in version_failures:
            with self.subTest(outcome=outcome):
                result = run_tool_adapter(
                    _adapter("ruff"),
                    _input(),
                    runner=lambda _request, outcome=outcome: outcome,
                )
                self.assertEqual(result.status, AssessmentStatus.FAILED)
                self.assertNotIn("secret", result.detail)

        outcomes = [
            AnalyzerProcessOutcome(AnalyzerProcessKind.COMPLETED, 0, b"ruff 1.2.3\n", b""),
            AnalyzerProcessOutcome(
                AnalyzerProcessKind.COMPLETED, 8, b"[]", assignment_bytes("token", "secret")
            ),
        ]
        failed = run_tool_adapter(
            _adapter("ruff"), _input(), runner=lambda _request: outcomes.pop(0)
        )
        self.assertEqual(failed.status, AssessmentStatus.FAILED)
        self.assertNotIn("secret", failed.detail)

    def test_each_native_parser_rejects_malformed_or_incomplete_evidence(self) -> None:
        malformed = {
            "ruff": (
                b"{}",
                b"[1]",
                b'[{"code":"S1","filename":"/outside.py","location":{"row":1}}]',
                b'[{"code":true,"filename":"payload/main.py","location":{"row":1}}]',
                b'[{"code":"S1","filename":"payload/main.py","location":{"row":0}}]',
            ),
            "bandit": (
                b"[]",
                b'{"errors":["parse failed"],"results":[]}',
                b'{"errors":[],"results":[1]}',
                b'{"errors":[],"results":[{"filename":"payload/main.py",'
                b'"issue_severity":"UNDEFINED","line_number":1,"test_id":"B1"}]}',
            ),
            "detect-secrets": (
                b"[]",
                b'{"results":[]}',
                b'{"results":{"../outside":[{"line_number":1,"type":"Key"}]}}',
                b'{"results":{"payload/main.py":[1]}}',
                b'{"results":{"payload/main.py":[{"line_number":0,"type":"Key"}]}}',
                b'{"results":{"payload/main.py":[{"line_number":1,"type":true}]}}',
            ),
            "pip-audit": (
                b"{}",
                b"[1]",
                b'[{"name":"demo","vulns":true}]',
                b'[{"name":"demo","vulns":[1]}]',
                b'[{"name":"demo","vulns":[{"id":true}]}]',
            ),
            "shellcheck": (
                b"{}",
                b"[1]",
                b'[{"code":1,"file":"../outside","level":"warning","line":1}]',
                b'[{"code":1,"file":"payload/install.sh","level":"bad","line":1}]',
                b'[{"code":1,"file":"payload/install.sh","level":"warning","line":0}]',
            ),
        }
        paths = {
            "pip-audit": ("payload/requirements.txt",),
            "shellcheck": ("payload/install.sh",),
        }
        for provider_id, outputs in malformed.items():
            for output in outputs:
                with self.subTest(provider_id=provider_id, output=output[:30]):
                    result, _calls = _run(
                        provider_id,
                        output,
                        paths=paths.get(provider_id, ("payload/main.py",)),
                    )
                    self.assertEqual(result.status, AssessmentStatus.FAILED)


if __name__ == "__main__":
    unittest.main()
