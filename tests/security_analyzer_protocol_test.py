from __future__ import annotations

import unittest

from agent_artifacts.domain.identifiers import ObjectDigest
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.protocol.hashing import json_digest, sha256_bytes
from agent_artifacts.protocol.json import JsonObject
from agent_artifacts.protocol.native_tree import SnapshotEntry, SnapshotEntryKind
from agent_artifacts.protocol.paths import parse_relative_path
from agent_artifacts.security.analyzers import (
    AnalyzerCommand,
    AnalyzerDescriptor,
    AnalyzerInput,
    AnalyzerProcessKind,
    AnalyzerProcessOutcome,
    AnalyzerScanAttempt,
    handshake_request_bytes,
    parse_handshake,
    parse_scan_result,
    run_protocol_analyzer,
    scan_request_bytes,
    to_security_assessment,
)
from agent_artifacts.security.application import analyzer_input_from_stored_object
from agent_artifacts.security.model import AssessmentStatus, FindingSeverity
from agent_artifacts.store.model import StoredObject, make_object_candidate

RULES = sha256_bytes(b"rules-v1")
OBJECT = sha256_bytes(b"object-v1")


def _descriptor(**changes: object) -> AnalyzerDescriptor:
    values: dict[str, object] = {
        "id": "example-analyzer",
        "version": "2.1.0",
        "protocol": "security-analyzer-v1",
        "capabilities": ("python-static",),
        "artifact_types": ("skill",),
        "file_extensions": (".py",),
        "rules_digest": RULES,
        "network_required": False,
        "max_input_files": 10,
        "max_input_bytes": 4096,
    }
    values.update(changes)
    return AnalyzerDescriptor(**values)  # type: ignore[arg-type]


def _input(**changes: object) -> AnalyzerInput:
    path = parse_relative_path("payload/main.py")
    assert isinstance(path, Ok)
    values: dict[str, object] = {
        "object_digest": OBJECT,
        "root": "/immutable/objects/sha256/object",
        "artifact_type": "skill",
        "files": ((path.value, 12),),
    }
    values.update(changes)
    return AnalyzerInput(**values)  # type: ignore[arg-type]


def _handshake_json(**changes: str) -> bytes:
    provider_id = changes.get("provider_id", "example-analyzer")
    protocol = changes.get("protocol", "security-analyzer-v1")
    rules = changes.get("rules_digest", str(RULES))
    return (
        "{"
        '"capabilities":["python-static"],'
        '"file_extensions":[".py"],'
        '"max_input":{"bytes":4096,"files":10},'
        '"network":"none",'
        f'"protocol":"{protocol}",'
        f'"provider":{{"id":"{provider_id}","version":"2.1.0"}},'
        f'"rules_digest":"{rules}",'
        '"schema_version":1,'
        '"supported_artifact_types":["skill"]'
        "}\n"
    ).encode()


def _scan_json(*, duplicate: bool = False, provider_id: str = "example-analyzer") -> bytes:
    path = parse_relative_path("payload/main.py")
    assert isinstance(path, Ok)
    from agent_artifacts.security.model import make_finding

    finding = make_finding(
        "rule-101",
        FindingSeverity.HIGH,
        "Provider observed rule rule-101.",
        "Review the reported rule in the immutable artifact.",
        provider_id=provider_id,
        path=path.value,
        line=4,
    )
    item = (
        "{"
        f'"fingerprint":"{finding.fingerprint}",'
        '"line":4,'
        '"message":"Provider observed rule rule-101.",'
        '"path":"payload/main.py",'
        '"remediation":"Review the reported rule in the immutable artifact.",'
        '"rule_id":"rule-101",'
        '"severity":"high"'
        "}"
    )
    findings = f"{item},{item}" if duplicate else item
    return (
        "{"
        '"action":"scan-result",'
        '"coverage":{"completed":1,"expected":1,"skipped":[]},'
        f'"findings":[{findings}],'
        '"protocol":"security-analyzer-v1",'
        f'"provider":{{"id":"{provider_id}","rules_digest":"{RULES}",'
        '"version":"2.1.0"},'
        '"schema_version":1,'
        '"status":"complete"'
        "}\n"
    ).encode()


class SecurityAnalyzerProtocolTest(unittest.TestCase):
    def test_handshake_request_is_exact_canonical_json(self) -> None:
        self.assertEqual(
            handshake_request_bytes(),
            b'{"action":"handshake","protocol":"security-analyzer-v1","schema_version":1}\n',
        )

    def test_handshake_parses_capabilities_limits_and_network_declaration(self) -> None:
        parsed = parse_handshake(_handshake_json(), expected_provider_id="example-analyzer")
        self.assertEqual(parsed, Ok(_descriptor()))

        network = _handshake_json().replace(b'"network":"none"', b'"network":"required"')
        parsed_network = parse_handshake(network, expected_provider_id="example-analyzer")
        self.assertIsInstance(parsed_network, Ok)
        assert isinstance(parsed_network, Ok)
        self.assertTrue(parsed_network.value.network_required)

    def test_handshake_rejects_wrong_provider_protocol_digest_and_unknown_fields(self) -> None:
        invalid = (
            _handshake_json(provider_id="other"),
            _handshake_json(protocol="security-analyzer-v2"),
            _handshake_json(rules_digest="sha256:bad"),
            _handshake_json().replace(b'"schema_version":1', b'"extra":true,"schema_version":1'),
            b"not-json",
            b"x" * (2 * 1024 * 1024 + 1),
        )
        for data in invalid:
            with self.subTest(data=data[:40]):
                self.assertIsInstance(
                    parse_handshake(data, expected_provider_id="example-analyzer"), Err
                )

    def test_handshake_rejects_invalid_document_and_nested_value_shapes(self) -> None:
        invalid = (
            [],
            "\ud800",
            b"[]\n",
            _handshake_json().replace(
                b'"provider":{"id":"example-analyzer","version":"2.1.0"}',
                b'"provider":[]',
            ),
            _handshake_json().replace(b'"max_input":{"bytes":4096,"files":10}', b'"max_input":[]'),
            _handshake_json().replace(b'["python-static"]', b'"python-static"'),
            _handshake_json().replace(b'[".py"]', b"[1]"),
            _handshake_json().replace(b'["skill"]', b"[]"),
            _handshake_json().replace(b'["python-static"]', b'["python-static","python-static"]'),
            _handshake_json().replace(b'"version":"2.1.0"', b'"version":true'),
            _handshake_json().replace(b'"network":"none"', b'"network":"sometimes"'),
            _handshake_json().replace(b'"files":10', b'"files":true'),
            _handshake_json().replace(b'"bytes":4096', b'"bytes":0'),
        )
        for data in invalid:
            with self.subTest(data=str(data)[:50]):
                self.assertIsInstance(
                    parse_handshake(data, expected_provider_id="example-analyzer"),  # type: ignore[arg-type]
                    Err,
                )

    def test_descriptor_and_input_reject_unsafe_or_unbounded_values(self) -> None:
        invalid_descriptors = (
            lambda: _descriptor(id="Bad ID"),
            lambda: _descriptor(version="bad version"),
            lambda: _descriptor(protocol="security-analyzer-v2"),
            lambda: _descriptor(capabilities=("bad capability",)),
            lambda: _descriptor(capabilities=()),
            lambda: _descriptor(artifact_types=("Bad",)),
            lambda: _descriptor(artifact_types=()),
            lambda: _descriptor(file_extensions=("../py",)),
            lambda: _descriptor(rules_digest=ObjectDigest("sha256", "z" * 64)),
            lambda: _descriptor(network_required="yes"),
            lambda: _descriptor(max_input_files=0),
            lambda: _descriptor(max_input_bytes=True),
            lambda: _descriptor(file_extensions=("py",)),
            lambda: _descriptor(capabilities=("python-static", "python-static")),
            lambda: _descriptor(artifact_types=("skill", "skill")),
            lambda: _descriptor(file_extensions=(".py", ".py")),
        )
        for constructor in invalid_descriptors:
            with self.subTest(constructor=constructor), self.assertRaises(ValueError):
                constructor()
        with self.assertRaises(ValueError):
            _input(root="relative")
        with self.assertRaises(ValueError):
            _input(root="/")
        with self.assertRaises(ValueError):
            _input(artifact_type="Bad Type")
        with self.assertRaises(ValueError):
            _input(object_digest=ObjectDigest("sha256", "z" * 64))
        with self.assertRaises(ValueError):
            _input(files=())
        with self.assertRaises(ValueError):
            _input(files=(_input().files[0], _input().files[0]))
        with self.assertRaises(ValueError):
            _input(files=((parse_relative_path("payload/main.py").value, -1),))  # type: ignore[union-attr]
        with self.assertRaises(ValueError):
            _input(files=(([], 1),))
        with self.assertRaises(ValueError):
            _input(contents=(([], b"x"),))
        other = parse_relative_path("payload/other.py")
        assert isinstance(other, Ok)
        with self.assertRaises(ValueError):
            _input(contents=((other.value, b"x"),))
        with self.assertRaises(ValueError):
            _input(contents=((_input().files[0][0], b"wrong size"),))
        with self.assertRaises(ValueError):
            _input(contents=((_input().files[0][0], b"x" * 12),) * 2)

    def test_command_and_process_outcome_values_reject_inconsistent_states(self) -> None:
        invalid_commands = (
            lambda: AnalyzerCommand("Bad", "tool"),
            lambda: AnalyzerCommand("example", "sh"),
            lambda: AnalyzerCommand("example", "path/tool"),
            lambda: AnalyzerCommand("example", "tool", ("bad\narg",)),
            lambda: AnalyzerCommand("example", "tool", timeout_seconds=0),
            lambda: AnalyzerCommand("example", "tool", max_output_bytes=0),
        )
        for constructor in invalid_commands:
            with self.subTest(constructor=constructor), self.assertRaises(ValueError):
                constructor()
        invalid_outcomes = (
            lambda: AnalyzerProcessOutcome(AnalyzerProcessKind.COMPLETED),
            lambda: AnalyzerProcessOutcome(AnalyzerProcessKind.TIMED_OUT, 1),
            lambda: AnalyzerProcessOutcome(AnalyzerProcessKind.TIMED_OUT, stdout=b"raw"),
            lambda: AnalyzerProcessOutcome("failed"),  # type: ignore[arg-type]
        )
        for constructor in invalid_outcomes:
            with self.subTest(constructor=constructor), self.assertRaises(ValueError):
                constructor()

    def test_scan_request_binds_exact_object_path_counts_and_network_consent(self) -> None:
        self.assertEqual(
            scan_request_bytes(_descriptor(), _input(), network_allowed=False),
            (
                b'{"action":"scan","artifact_type":"skill","input":{"file_count":1,'
                b'"object_digest":"'
                + str(OBJECT).encode()
                + b'","path":"/immutable/objects/sha256/object","total_bytes":12},'
                b'"network_allowed":false,"protocol":"security-analyzer-v1","schema_version":1}\n'
            ),
        )
        with self.assertRaises(ValueError):
            scan_request_bytes(_descriptor(), _input(), network_allowed=1)  # type: ignore[arg-type]

    def test_scan_result_normalizes_finding_and_builds_security_assessment(self) -> None:
        attempt = parse_scan_result(_scan_json(), _descriptor(), _input())
        self.assertIsInstance(attempt, Ok)
        assert isinstance(attempt, Ok)
        self.assertEqual(attempt.value.status, AssessmentStatus.COMPLETE)
        self.assertEqual(attempt.value.object_digest, OBJECT)
        self.assertEqual(attempt.value.findings[0].severity, FindingSeverity.HIGH)

        assessment = to_security_assessment(OBJECT, attempt.value)
        self.assertIsInstance(assessment, Ok)
        assert isinstance(assessment, Ok)
        self.assertEqual(assessment.value.installation_risk.value, "high")
        self.assertEqual(assessment.value.providers[0].id, "example-analyzer")
        self.assertIsInstance(
            to_security_assessment(sha256_bytes(b"different-object"), attempt.value), Err
        )

    def test_scan_result_rejects_provider_mismatch_unsafe_path_and_duplicate_fingerprints(
        self,
    ) -> None:
        invalid = (
            _scan_json(provider_id="other"),
            _scan_json().replace(b'"path":"payload/main.py"', b'"path":"../secret"'),
            _scan_json().replace(b'"path":"payload/main.py"', b'"path":"payload/missing.py"'),
            _scan_json(duplicate=True),
            _scan_json().replace(b'"status":"complete"', b'"status":"partial"'),
        )
        for data in invalid:
            with self.subTest(data=data[:80]):
                self.assertIsInstance(parse_scan_result(data, _descriptor(), _input()), Err)

    def test_scan_result_rejects_malformed_nested_evidence_and_inconsistent_coverage(self) -> None:
        invalid = (
            b"[]\n",
            _scan_json().replace(
                b'"provider":{"id":"example-analyzer","rules_digest":',
                b'"provider":{"extra":true,"id":"example-analyzer","rules_digest":',
            ),
            _scan_json().replace(
                b'"coverage":{"completed":1,"expected":1,"skipped":[]}',
                b'"coverage":[]',
            ),
            _scan_json().replace(b'"findings":[', b'"findings":true,"ignored":['),
            _scan_json().replace(b'"schema_version":1', b'"schema_version":2'),
            _scan_json().replace(b'"action":"scan-result"', b'"action":"other"'),
            _scan_json().replace(b'"status":"complete"', b'"status":"stale"'),
            _scan_json().replace(b'"completed":1', b'"completed":true'),
            _scan_json().replace(b'"expected":1', b'"expected":0'),
            _scan_json().replace(b'"skipped":[]', b'"skipped":[1]'),
            _scan_json().replace(b'"fingerprint":"sha256:', b'"fingerprint":"bad:'),
            _scan_json().replace(b'"line":4', b'"line":true'),
            _scan_json().replace(b'"path":"payload/main.py"', b'"path":1'),
            _scan_json().replace(b'"rule_id":"rule-101"', b'"rule_id":1'),
            _scan_json().replace(b'"severity":"high"', b'"severity":"extreme"'),
        )
        for data in invalid:
            with self.subTest(data=data[:70]):
                self.assertIsInstance(parse_scan_result(data, _descriptor(), _input()), Err)

    def test_absent_provider_is_not_scanned_without_core_failure(self) -> None:
        command = AnalyzerCommand("example-analyzer", "example-analyzer", ("--protocol",))

        result = run_protocol_analyzer(
            command,
            _input(),
            resolver=lambda _name: None,
            runner=lambda _request: self.fail("missing executable must not run"),
        )

        self.assertEqual(result.status, AssessmentStatus.NOT_SCANNED)
        self.assertIsNone(result.descriptor)
        self.assertEqual(result.coverage.completed, 0)
        self.assertIn("not installed", result.detail)

    def test_successful_run_performs_handshake_then_scan_with_fixed_resolved_argv(self) -> None:
        requests = []
        outputs = [_handshake_json(), _scan_json()]

        def runner(request):  # type: ignore[no-untyped-def]
            requests.append(request)
            return AnalyzerProcessOutcome(AnalyzerProcessKind.COMPLETED, 0, outputs.pop(0), b"")

        result = run_protocol_analyzer(
            AnalyzerCommand("example-analyzer", "example-analyzer", ("--protocol",)),
            _input(),
            resolver=lambda _name: "/opt/tools/example-analyzer",
            runner=runner,
        )

        self.assertEqual(result.status, AssessmentStatus.COMPLETE)
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0].argv, ("/opt/tools/example-analyzer", "--protocol"))
        self.assertEqual(requests[0].stdin, handshake_request_bytes())
        self.assertEqual(requests[1].cwd, _input().root)
        self.assertNotIn(b"secret", requests[1].stdin)

    def test_timeout_crash_and_malformed_output_become_failed_attempts(self) -> None:
        outcomes = (
            AnalyzerProcessOutcome(AnalyzerProcessKind.TIMED_OUT),
            AnalyzerProcessOutcome(AnalyzerProcessKind.COMPLETED, 9, b"", b"token=secret"),
            AnalyzerProcessOutcome(AnalyzerProcessKind.COMPLETED, 0, b"not-json", b""),
            AnalyzerProcessOutcome(AnalyzerProcessKind.OUTPUT_LIMIT),
        )
        for outcome in outcomes:
            with self.subTest(kind=outcome.kind):
                result = run_protocol_analyzer(
                    AnalyzerCommand("example-analyzer", "example-analyzer"),
                    _input(),
                    resolver=lambda _name: "/opt/example-analyzer",
                    runner=lambda _request, outcome=outcome: outcome,
                )
                self.assertEqual(result.status, AssessmentStatus.FAILED)
                self.assertNotIn("secret", result.detail)

    def test_scan_process_failures_and_bad_resolved_path_are_terminal_safe_outcomes(self) -> None:
        unsafe = run_protocol_analyzer(
            AnalyzerCommand("example-analyzer", "example-analyzer"),
            _input(),
            resolver=lambda _name: "relative",
            runner=lambda _request: self.fail("unsafe executable must not run"),
        )
        self.assertEqual(unsafe.status, AssessmentStatus.FAILED)

        mismatched = run_protocol_analyzer(
            AnalyzerCommand("example-analyzer", "example-analyzer"),
            _input(),
            resolver=lambda _name: "/opt/other-analyzer",
            runner=lambda _request: self.fail("mismatched executable must not run"),
        )
        self.assertEqual(mismatched.status, AssessmentStatus.FAILED)

        for scan_outcome in (
            AnalyzerProcessOutcome(AnalyzerProcessKind.TIMED_OUT),
            AnalyzerProcessOutcome(AnalyzerProcessKind.COMPLETED, 2, b"", b"raw secret"),
            AnalyzerProcessOutcome(AnalyzerProcessKind.COMPLETED, 0, b"bad", b""),
        ):
            outcomes = [
                AnalyzerProcessOutcome(AnalyzerProcessKind.COMPLETED, 0, _handshake_json(), b""),
                scan_outcome,
            ]
            with self.subTest(scan_outcome=scan_outcome):
                result = run_protocol_analyzer(
                    AnalyzerCommand("example-analyzer", "example-analyzer"),
                    _input(),
                    resolver=lambda _name: "/opt/example-analyzer",
                    runner=lambda _request, outcomes=outcomes: outcomes.pop(0),
                )
                self.assertEqual(result.status, AssessmentStatus.FAILED)

        with self.assertRaises(ValueError):
            run_protocol_analyzer(
                AnalyzerCommand("example-analyzer", "example-analyzer"),
                _input(),
                resolver=lambda _name: None,
                runner=lambda _request: self.fail(),
                allow_network=1,  # type: ignore[arg-type]
            )

    def test_network_and_declared_input_limits_prevent_scan(self) -> None:
        second_path = parse_relative_path("payload/other.py")
        assert isinstance(second_path, Ok)
        first_path = _input().files[0][0]
        cases = (
            (_handshake_json().replace(b'"network":"none"', b'"network":"required"'), _input()),
            (
                _handshake_json().replace(b'"files":10', b'"files":1'),
                _input(files=((first_path, 6), (second_path.value, 6))),
            ),
            (_handshake_json().replace(b'"bytes":4096', b'"bytes":1'), _input()),
            (_handshake_json().replace(b'["skill"]', b'["mcp"]'), _input()),
        )
        for handshake, analyzer_input in cases:
            calls = 0

            def runner(_request, handshake=handshake):  # type: ignore[no-untyped-def]
                nonlocal calls
                calls += 1
                return AnalyzerProcessOutcome(AnalyzerProcessKind.COMPLETED, 0, handshake, b"")

            with self.subTest(handshake=handshake):
                result = run_protocol_analyzer(
                    AnalyzerCommand("example-analyzer", "example-analyzer"),
                    analyzer_input,
                    resolver=lambda _name: "/opt/example-analyzer",
                    runner=runner,
                )
                self.assertEqual(result.status, AssessmentStatus.NOT_SCANNED)
                self.assertEqual(calls, 1)

    def test_attempt_values_are_bounded_and_do_not_accept_forged_provider_findings(self) -> None:
        coverage = parse_scan_result(_scan_json(), _descriptor(), _input())
        assert isinstance(coverage, Ok)
        with self.assertRaises(ValueError):
            AnalyzerScanAttempt(
                "other",
                OBJECT,
                AssessmentStatus.COMPLETE,
                coverage.value.coverage,
                "complete",
                _descriptor(),
                coverage.value.findings,
            )

    def test_descriptor_rules_digest_is_not_a_self_authored_constant(self) -> None:
        descriptor = _descriptor()
        self.assertNotEqual(
            descriptor.rules_digest,
            json_digest(JsonObject((("provider", descriptor.id),))),
        )

        missing = run_protocol_analyzer(
            AnalyzerCommand("example-analyzer", "example-analyzer"),
            _input(),
            resolver=lambda _name: None,
            runner=lambda _request: self.fail(),
        )
        self.assertIsInstance(to_security_assessment(OBJECT, missing), Err)

    def test_verified_stored_object_maps_to_exact_immutable_analyzer_input(self) -> None:
        payload = parse_relative_path("payload/main.py")
        directory = parse_relative_path("payload")
        assert isinstance(payload, Ok)
        assert isinstance(directory, Ok)
        candidate = make_object_candidate(
            (
                SnapshotEntry(directory.value, SnapshotEntryKind.DIRECTORY),
                SnapshotEntry(payload.value, SnapshotEntryKind.FILE, b"print('ok')\n"),
            )
        )
        assert isinstance(candidate, Ok)
        stored = StoredObject(candidate.value, "/managed/objects/sha256/example")

        result = analyzer_input_from_stored_object(stored, artifact_type="skill")

        self.assertEqual(result.object_digest, candidate.value.digest)
        self.assertEqual(result.root, stored.root)
        self.assertEqual(result.files, ((payload.value, 12),))
        self.assertEqual(result.content(payload.value), b"print('ok')\n")
        self.assertIsNone(result.content(directory.value))


if __name__ == "__main__":
    unittest.main()
