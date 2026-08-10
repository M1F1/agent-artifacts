"""Pure values and orchestration for optional out-of-process security analyzers."""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import ObjectDigest
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.protocol.hashing import parse_sha256
from agent_artifacts.protocol.json import (
    JsonArray,
    JsonObject,
    JsonValue,
    canonical_json_bytes,
    parse_json,
)
from agent_artifacts.protocol.paths import SafeRelativePath, parse_relative_path

from .model import (
    MAX_FINDINGS,
    AssessmentCoverage,
    AssessmentStatus,
    FindingSeverity,
    ProviderAssessment,
    SecurityAssessment,
    SecurityFinding,
    risk_from_evidence,
)

PROTOCOL = "security-analyzer-v1"
ANALYZER_INVALID = DiagnosticCode("security-analyzer-invalid")
_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
_TYPE_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_EXECUTABLE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")
_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
_MAX_PROTOCOL_BYTES = 2 * 1024 * 1024
_MAX_INPUT_FILES = 100_000
_MAX_INPUT_BYTES = 10 * 1024 * 1024 * 1024
_FORBIDDEN_EXECUTABLES = frozenset(
    {"bash", "cmd", "dash", "fish", "powershell", "pwsh", "sh", "zsh"}
)
_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


def _one_line(value: str, maximum: int) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and len(value) <= maximum
        and "\n" not in value
        and "\r" not in value
        and "\x00" not in value
    )


def _valid_digest(value: object) -> bool:
    return (
        isinstance(value, ObjectDigest)
        and value.algorithm == "sha256"
        and _HEX_RE.fullmatch(value.value) is not None
    )


def _error(message: str) -> Err:
    return Err((Diagnostic(ANALYZER_INVALID, Severity.ERROR, message),))


def _fields(value: JsonValue, names: frozenset[str], label: str) -> Result[dict[str, JsonValue]]:
    if not isinstance(value, JsonObject):
        return _error(f"{label} must be an object")
    fields = dict(value.entries)
    if frozenset(fields) != names:
        return _error(f"{label} fields are invalid")
    return Ok(fields)


def _strict_document(data: bytes | str) -> Result[tuple[bytes, JsonValue]]:
    if not isinstance(data, (bytes, str)):
        return _error("analyzer document must be UTF-8 bytes or text")
    try:
        encoded = data.encode("utf-8") if isinstance(data, str) else data
    except UnicodeEncodeError:
        return _error("analyzer document is not UTF-8")
    if len(encoded) > _MAX_PROTOCOL_BYTES:
        return _error("analyzer document exceeds the output limit")
    parsed = parse_json(encoded, max_depth=16, max_string_length=4096)
    if isinstance(parsed, Err):
        return _error("analyzer document is not strict JSON")
    if canonical_json_bytes(parsed.value) != encoded:
        return _error("analyzer document is not canonical JSON")
    return Ok((encoded, parsed.value))


@dataclass(frozen=True, slots=True)
class AnalyzerDescriptor:
    id: str
    version: str
    protocol: str
    capabilities: tuple[str, ...]
    artifact_types: tuple[str, ...]
    file_extensions: tuple[str, ...]
    rules_digest: ObjectDigest
    network_required: bool
    max_input_files: int
    max_input_bytes: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.capabilities, tuple)
            or not all(isinstance(item, str) for item in self.capabilities)
            or not isinstance(self.artifact_types, tuple)
            or not all(isinstance(item, str) for item in self.artifact_types)
            or not isinstance(self.file_extensions, tuple)
            or not all(isinstance(item, str) for item in self.file_extensions)
        ):
            raise ValueError("analyzer descriptor is invalid")
        capabilities = tuple(sorted(set(self.capabilities)))
        artifact_types = tuple(sorted(set(self.artifact_types)))
        file_extensions = tuple(sorted(set(self.file_extensions)))
        if (
            not isinstance(self.id, str)
            or _ID_RE.fullmatch(self.id) is None
            or not isinstance(self.version, str)
            or _VERSION_RE.fullmatch(self.version) is None
            or self.protocol != PROTOCOL
            or not capabilities
            or len(capabilities) != len(self.capabilities)
            or len(capabilities) > 64
            or any(_ID_RE.fullmatch(item) is None for item in capabilities)
            or not artifact_types
            or len(artifact_types) != len(self.artifact_types)
            or len(artifact_types) > 64
            or any(_TYPE_RE.fullmatch(item) is None for item in artifact_types)
            or len(file_extensions) > 256
            or len(file_extensions) != len(self.file_extensions)
            or any(
                not _one_line(item, 32) or not item.startswith(".") or "/" in item or "\\" in item
                for item in file_extensions
            )
            or not _valid_digest(self.rules_digest)
            or not isinstance(self.network_required, bool)
            or not isinstance(self.max_input_files, int)
            or isinstance(self.max_input_files, bool)
            or not 1 <= self.max_input_files <= _MAX_INPUT_FILES
            or not isinstance(self.max_input_bytes, int)
            or isinstance(self.max_input_bytes, bool)
            or not 1 <= self.max_input_bytes <= _MAX_INPUT_BYTES
        ):
            raise ValueError("analyzer descriptor is invalid")
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(self, "artifact_types", artifact_types)
        object.__setattr__(self, "file_extensions", file_extensions)


@dataclass(frozen=True, slots=True)
class AnalyzerInput:
    object_digest: ObjectDigest
    root: str
    artifact_type: str
    files: tuple[tuple[SafeRelativePath, int], ...]
    contents: tuple[tuple[SafeRelativePath, bytes], ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.files, tuple)
            or any(not isinstance(item, tuple) or len(item) != 2 for item in self.files)
            or not isinstance(self.contents, tuple)
            or any(not isinstance(item, tuple) or len(item) != 2 for item in self.contents)
            or any(
                not isinstance(path, SafeRelativePath)
                or not isinstance(size, int)
                or isinstance(size, bool)
                or size < 0
                for path, size in self.files
            )
            or any(
                not isinstance(path, SafeRelativePath) or not isinstance(content, bytes)
                for path, content in self.contents
            )
        ):
            raise ValueError("analyzer input is invalid")
        files = tuple(sorted(self.files, key=lambda item: str(item[0])))
        contents = tuple(sorted(self.contents, key=lambda item: str(item[0])))
        paths = tuple(path for path, _size in files)
        content_paths = tuple(path for path, _content in contents)
        sizes = dict(files)
        if (
            not _valid_digest(self.object_digest)
            or not isinstance(self.root, str)
            or not posixpath.isabs(self.root)
            or posixpath.normpath(self.root) != self.root
            or self.root == "/"
            or not isinstance(self.artifact_type, str)
            or _TYPE_RE.fullmatch(self.artifact_type) is None
            or not files
            or len(files) > _MAX_INPUT_FILES
            or len(set(paths)) != len(paths)
            or len(set(content_paths)) != len(content_paths)
            or any(path not in sizes or len(content) != sizes[path] for path, content in contents)
            or sum(size for _path, size in files) > _MAX_INPUT_BYTES
        ):
            raise ValueError("analyzer input is invalid")
        object.__setattr__(self, "files", files)
        object.__setattr__(self, "contents", contents)

    @property
    def file_count(self) -> int:
        return len(self.files)

    @property
    def total_bytes(self) -> int:
        return sum(size for _path, size in self.files)

    def content(self, path: SafeRelativePath) -> bytes | None:
        for candidate, content in self.contents:
            if candidate == path:
                return content
        return None


@dataclass(frozen=True, slots=True)
class AnalyzerCommand:
    provider_id: str
    executable: str
    fixed_args: tuple[str, ...] = ()
    timeout_seconds: float = 30.0
    max_output_bytes: int = _MAX_PROTOCOL_BYTES

    def __post_init__(self) -> None:
        if (
            not isinstance(self.provider_id, str)
            or _ID_RE.fullmatch(self.provider_id) is None
            or not isinstance(self.executable, str)
            or _EXECUTABLE_RE.fullmatch(self.executable) is None
            or self.executable.casefold() in _FORBIDDEN_EXECUTABLES
            or not isinstance(self.fixed_args, tuple)
            or len(self.fixed_args) > 64
            or any(not _one_line(item, 1024) for item in self.fixed_args)
            or not isinstance(self.timeout_seconds, (int, float))
            or isinstance(self.timeout_seconds, bool)
            or not 0 < self.timeout_seconds <= 3600
            or not isinstance(self.max_output_bytes, int)
            or isinstance(self.max_output_bytes, bool)
            or not 1 <= self.max_output_bytes <= _MAX_PROTOCOL_BYTES
        ):
            raise ValueError("analyzer command is invalid")


class AnalyzerProcessKind(str, Enum):
    COMPLETED = "completed"
    UNAVAILABLE = "unavailable"
    TIMED_OUT = "timed-out"
    OUTPUT_LIMIT = "output-limit"
    FAILED_TO_START = "failed-to-start"


@dataclass(frozen=True, slots=True)
class AnalyzerProcessRequest:
    argv: tuple[str, ...]
    cwd: str
    stdin: bytes
    timeout_seconds: float
    max_output_bytes: int

    def __post_init__(self) -> None:
        executable = (
            self.argv[0]
            if isinstance(self.argv, tuple) and self.argv and isinstance(self.argv[0], str)
            else ""
        )
        if (
            not self.argv
            or not posixpath.isabs(executable)
            or posixpath.normpath(executable) != executable
            or executable == "/"
            or posixpath.basename(executable).casefold() in _FORBIDDEN_EXECUTABLES
            or len(self.argv) > 65
            or any(not _one_line(item, 1024) for item in self.argv)
            or not isinstance(self.cwd, str)
            or not posixpath.isabs(self.cwd)
            or posixpath.normpath(self.cwd) != self.cwd
            or self.cwd == "/"
            or not isinstance(self.stdin, bytes)
            or len(self.stdin) > _MAX_PROTOCOL_BYTES
            or not isinstance(self.timeout_seconds, (int, float))
            or isinstance(self.timeout_seconds, bool)
            or not 0 < self.timeout_seconds <= 3600
            or not isinstance(self.max_output_bytes, int)
            or isinstance(self.max_output_bytes, bool)
            or not 1 <= self.max_output_bytes <= _MAX_PROTOCOL_BYTES
        ):
            raise ValueError("analyzer process request is invalid")


@dataclass(frozen=True, slots=True)
class AnalyzerProcessOutcome:
    kind: AnalyzerProcessKind
    returncode: int | None = None
    stdout: bytes = b""
    stderr: bytes = b""

    def __post_init__(self) -> None:
        if (
            not isinstance(self.kind, AnalyzerProcessKind)
            or (self.kind is AnalyzerProcessKind.COMPLETED)
            != (isinstance(self.returncode, int) and not isinstance(self.returncode, bool))
            or not isinstance(self.stdout, bytes)
            or not isinstance(self.stderr, bytes)
            or (self.kind is not AnalyzerProcessKind.COMPLETED and (self.stdout or self.stderr))
        ):
            raise ValueError("analyzer process outcome is invalid")


@dataclass(frozen=True, slots=True)
class AnalyzerScanAttempt:
    provider_id: str
    object_digest: ObjectDigest
    status: AssessmentStatus
    coverage: AssessmentCoverage
    detail: str
    descriptor: AnalyzerDescriptor | None = None
    findings: tuple[SecurityFinding, ...] = ()

    def __post_init__(self) -> None:
        findings = tuple(sorted(self.findings, key=lambda item: item.sort_key))
        if (
            not isinstance(self.provider_id, str)
            or _ID_RE.fullmatch(self.provider_id) is None
            or not _valid_digest(self.object_digest)
            or not isinstance(self.status, AssessmentStatus)
            or not isinstance(self.coverage, AssessmentCoverage)
            or not _one_line(self.detail, 512)
            or (self.descriptor is not None and self.descriptor.id != self.provider_id)
            or any(item.provider_id != self.provider_id for item in findings)
            or len({item.fingerprint for item in findings}) != len(findings)
            or (self.descriptor is None and findings)
            or (self.status is AssessmentStatus.COMPLETE and not self.coverage.complete)
            or (
                self.status in {AssessmentStatus.PARTIAL, AssessmentStatus.FAILED}
                and self.coverage.complete
            )
            or (
                self.status is AssessmentStatus.NOT_SCANNED
                and (self.coverage.completed or findings)
            )
            or self.status is AssessmentStatus.STALE
        ):
            raise ValueError("analyzer scan attempt is invalid")
        object.__setattr__(self, "findings", findings)


AnalyzerRunner = Callable[[AnalyzerProcessRequest], AnalyzerProcessOutcome]
ExecutableResolver = Callable[[str], str | None]


def handshake_request_bytes() -> bytes:
    return canonical_json_bytes(
        JsonObject((("action", "handshake"), ("protocol", PROTOCOL), ("schema_version", 1)))
    )


def _string_array(value: JsonValue, label: str, maximum: int) -> Result[tuple[str, ...]]:
    if (
        not isinstance(value, JsonArray)
        or len(value.items) > maximum
        or any(not isinstance(item, str) for item in value.items)
    ):
        return _error(f"{label} must be a bounded string array")
    return Ok(tuple(value.items))  # type: ignore[arg-type]


def parse_handshake(data: bytes | str, *, expected_provider_id: str) -> Result[AnalyzerDescriptor]:
    document = _strict_document(data)
    if isinstance(document, Err):
        return document
    root = _fields(
        document.value[1],
        frozenset(
            {
                "capabilities",
                "file_extensions",
                "max_input",
                "network",
                "protocol",
                "provider",
                "rules_digest",
                "schema_version",
                "supported_artifact_types",
            }
        ),
        "analyzer handshake",
    )
    if isinstance(root, Err):
        return root
    raw = root.value
    provider = _fields(raw["provider"], frozenset({"id", "version"}), "provider")
    limits = _fields(raw["max_input"], frozenset({"bytes", "files"}), "max_input")
    capabilities = _string_array(raw["capabilities"], "capabilities", 64)
    artifact_types = _string_array(raw["supported_artifact_types"], "artifact types", 64)
    extensions = _string_array(raw["file_extensions"], "file extensions", 256)
    if any(
        isinstance(item, Err)
        for item in (provider, limits, capabilities, artifact_types, extensions)
    ):
        return _error("analyzer handshake contains invalid nested values")
    assert isinstance(provider, Ok)
    assert isinstance(limits, Ok)
    assert isinstance(capabilities, Ok)
    assert isinstance(artifact_types, Ok)
    assert isinstance(extensions, Ok)
    provider_id = provider.value["id"]
    version = provider.value["version"]
    rules = raw["rules_digest"]
    network = raw["network"]
    if (
        raw["schema_version"] != 1
        or raw["protocol"] != PROTOCOL
        or provider_id != expected_provider_id
        or not isinstance(provider_id, str)
        or not isinstance(version, str)
        or not isinstance(rules, str)
        or network not in {"none", "required"}
        or not isinstance(limits.value["files"], int)
        or isinstance(limits.value["files"], bool)
        or not isinstance(limits.value["bytes"], int)
        or isinstance(limits.value["bytes"], bool)
    ):
        return _error("analyzer handshake identity or field types are invalid")
    digest = parse_sha256(rules)
    if isinstance(digest, Err):
        return _error("analyzer handshake rules digest is invalid")
    try:
        return Ok(
            AnalyzerDescriptor(
                provider_id,
                version,
                PROTOCOL,
                capabilities.value,
                artifact_types.value,
                extensions.value,
                digest.value,
                network == "required",
                limits.value["files"],
                limits.value["bytes"],
            )
        )
    except ValueError:
        return _error("analyzer handshake values are invalid")


def scan_request_bytes(
    descriptor: AnalyzerDescriptor,
    analyzer_input: AnalyzerInput,
    *,
    network_allowed: bool,
) -> bytes:
    if not isinstance(network_allowed, bool):
        raise ValueError("network consent must be explicit")
    return canonical_json_bytes(
        JsonObject(
            (
                ("action", "scan"),
                ("artifact_type", analyzer_input.artifact_type),
                (
                    "input",
                    JsonObject(
                        (
                            ("file_count", analyzer_input.file_count),
                            ("object_digest", str(analyzer_input.object_digest)),
                            ("path", analyzer_input.root),
                            ("total_bytes", analyzer_input.total_bytes),
                        )
                    ),
                ),
                ("network_allowed", network_allowed and descriptor.network_required),
                ("protocol", PROTOCOL),
                ("schema_version", 1),
            )
        )
    )


def _coverage(value: JsonValue) -> Result[AssessmentCoverage]:
    fields = _fields(value, frozenset({"completed", "expected", "skipped"}), "coverage")
    if isinstance(fields, Err):
        return fields
    completed = fields.value["completed"]
    expected = fields.value["expected"]
    skipped = _string_array(fields.value["skipped"], "coverage skips", 512)
    if (
        not isinstance(completed, int)
        or isinstance(completed, bool)
        or not isinstance(expected, int)
        or isinstance(expected, bool)
        or isinstance(skipped, Err)
    ):
        return _error("analyzer coverage values are invalid")
    try:
        return Ok(AssessmentCoverage(completed, expected, skipped.value))
    except ValueError:
        return _error("analyzer coverage values are invalid")


def _finding(
    value: JsonValue,
    provider_id: str,
    analyzer_input: AnalyzerInput,
) -> Result[SecurityFinding]:
    fields = _fields(
        value,
        frozenset({"fingerprint", "line", "message", "path", "remediation", "rule_id", "severity"}),
        "analyzer finding",
    )
    if isinstance(fields, Err):
        return fields
    raw = fields.value
    string_names = ("fingerprint", "message", "remediation", "rule_id", "severity")
    if any(not isinstance(raw[name], str) for name in string_names):
        return _error("analyzer finding string values are invalid")
    path: SafeRelativePath | None = None
    if raw["path"] is not None:
        if not isinstance(raw["path"], str):
            return _error("analyzer finding path is invalid")
        parsed_path = parse_relative_path(raw["path"])
        if isinstance(parsed_path, Err):
            return _error("analyzer finding path is unsafe")
        if parsed_path.value not in {item[0] for item in analyzer_input.files}:
            return _error("analyzer finding path is outside the declared input files")
        path = parsed_path.value
    line = raw["line"]
    if line is not None and (not isinstance(line, int) or isinstance(line, bool)):
        return _error("analyzer finding line is invalid")
    digest = parse_sha256(raw["fingerprint"])  # type: ignore[arg-type]
    if isinstance(digest, Err):
        return _error("analyzer finding fingerprint is invalid")
    try:
        return Ok(
            SecurityFinding(
                provider_id,
                raw["rule_id"],  # type: ignore[arg-type]
                FindingSeverity(raw["severity"]),
                raw["message"],  # type: ignore[arg-type]
                raw["remediation"],  # type: ignore[arg-type]
                digest.value,
                path,
                line,
            )
        )
    except ValueError:
        return _error("analyzer finding values are invalid")


def parse_scan_result(
    data: bytes | str,
    descriptor: AnalyzerDescriptor,
    analyzer_input: AnalyzerInput,
) -> Result[AnalyzerScanAttempt]:
    document = _strict_document(data)
    if isinstance(document, Err):
        return document
    root = _fields(
        document.value[1],
        frozenset(
            {"action", "coverage", "findings", "protocol", "provider", "schema_version", "status"}
        ),
        "analyzer scan result",
    )
    if isinstance(root, Err):
        return root
    raw = root.value
    provider = _fields(raw["provider"], frozenset({"id", "rules_digest", "version"}), "provider")
    coverage = _coverage(raw["coverage"])
    findings_value = raw["findings"]
    if (
        isinstance(provider, Err)
        or isinstance(coverage, Err)
        or not isinstance(findings_value, JsonArray)
        or len(findings_value.items) > MAX_FINDINGS
        or raw["schema_version"] != 1
        or raw["protocol"] != PROTOCOL
        or raw["action"] != "scan-result"
        or raw["status"] not in {"not-scanned", "complete", "partial", "failed"}
    ):
        return _error("analyzer scan result fields are invalid")
    assert isinstance(provider, Ok)
    assert isinstance(coverage, Ok)
    expected_provider = {
        "id": descriptor.id,
        "rules_digest": str(descriptor.rules_digest),
        "version": descriptor.version,
    }
    if provider.value != expected_provider:
        return _error("analyzer scan result does not match the handshake")
    findings: list[SecurityFinding] = []
    for value in findings_value.items:
        finding = _finding(value, descriptor.id, analyzer_input)
        if isinstance(finding, Err):
            return finding
        findings.append(finding.value)
    if len({item.fingerprint for item in findings}) != len(findings):
        return _error("analyzer scan result contains duplicate finding fingerprints")
    try:
        return Ok(
            AnalyzerScanAttempt(
                descriptor.id,
                analyzer_input.object_digest,
                AssessmentStatus(raw["status"]),
                coverage.value,
                "Analyzer scan completed with normalized evidence.",
                descriptor,
                tuple(findings),
            )
        )
    except ValueError:
        return _error("analyzer scan result status and coverage are inconsistent")


def _attempt(
    provider_id: str,
    object_digest: ObjectDigest,
    status: AssessmentStatus,
    detail: str,
    descriptor: AnalyzerDescriptor | None = None,
) -> AnalyzerScanAttempt:
    return AnalyzerScanAttempt(
        provider_id,
        object_digest,
        status,
        AssessmentCoverage(0, 1, (detail,)),
        detail,
        descriptor,
    )


def _run_failure(
    provider_id: str,
    object_digest: ObjectDigest,
    outcome: AnalyzerProcessOutcome,
    descriptor: AnalyzerDescriptor | None = None,
) -> AnalyzerScanAttempt | None:
    if outcome.kind is not AnalyzerProcessKind.COMPLETED:
        labels = {
            AnalyzerProcessKind.UNAVAILABLE: "Analyzer executable became unavailable.",
            AnalyzerProcessKind.TIMED_OUT: "Analyzer process timed out.",
            AnalyzerProcessKind.OUTPUT_LIMIT: "Analyzer output exceeded the configured limit.",
            AnalyzerProcessKind.FAILED_TO_START: "Analyzer process could not be started.",
        }
        return _attempt(
            provider_id,
            object_digest,
            AssessmentStatus.FAILED,
            labels[outcome.kind],
            descriptor,
        )
    if outcome.returncode != 0:
        return _attempt(
            provider_id,
            object_digest,
            AssessmentStatus.FAILED,
            "Analyzer process exited unsuccessfully.",
            descriptor,
        )
    return None


def run_protocol_analyzer(
    command: AnalyzerCommand,
    analyzer_input: AnalyzerInput,
    *,
    resolver: ExecutableResolver,
    runner: AnalyzerRunner,
    allow_network: bool = False,
) -> AnalyzerScanAttempt:
    """Discover, handshake, constrain, and run one protocol provider without raising expected failures."""

    if not isinstance(allow_network, bool):
        raise ValueError("network consent must be explicit")
    executable = resolver(command.executable)
    if executable is None:
        return _attempt(
            command.provider_id,
            analyzer_input.object_digest,
            AssessmentStatus.NOT_SCANNED,
            "Optional analyzer is not installed.",
        )
    try:
        if posixpath.basename(executable) != command.executable:
            raise ValueError("resolved executable identity changed")
        argv = (executable, *command.fixed_args)
        handshake_request = AnalyzerProcessRequest(
            argv,
            analyzer_input.root,
            handshake_request_bytes(),
            command.timeout_seconds,
            command.max_output_bytes,
        )
    except ValueError:
        return _attempt(
            command.provider_id,
            analyzer_input.object_digest,
            AssessmentStatus.FAILED,
            "Resolved analyzer executable is unsafe.",
        )
    handshake_outcome = runner(handshake_request)
    failure = _run_failure(command.provider_id, analyzer_input.object_digest, handshake_outcome)
    if failure is not None:
        return failure
    descriptor_result = parse_handshake(
        handshake_outcome.stdout,
        expected_provider_id=command.provider_id,
    )
    if isinstance(descriptor_result, Err):
        return _attempt(
            command.provider_id,
            analyzer_input.object_digest,
            AssessmentStatus.FAILED,
            "Analyzer handshake was malformed or incompatible.",
        )
    descriptor = descriptor_result.value
    if descriptor.network_required and not allow_network:
        return _attempt(
            command.provider_id,
            analyzer_input.object_digest,
            AssessmentStatus.NOT_SCANNED,
            "Analyzer requires network access that was not approved.",
            descriptor,
        )
    if analyzer_input.artifact_type not in descriptor.artifact_types:
        return _attempt(
            command.provider_id,
            analyzer_input.object_digest,
            AssessmentStatus.NOT_SCANNED,
            "Analyzer does not support this artifact type.",
            descriptor,
        )
    if (
        analyzer_input.file_count > descriptor.max_input_files
        or analyzer_input.total_bytes > descriptor.max_input_bytes
    ):
        return _attempt(
            command.provider_id,
            analyzer_input.object_digest,
            AssessmentStatus.NOT_SCANNED,
            "Artifact exceeds the analyzer declared input limits.",
            descriptor,
        )
    request = AnalyzerProcessRequest(
        argv,
        analyzer_input.root,
        scan_request_bytes(descriptor, analyzer_input, network_allowed=allow_network),
        command.timeout_seconds,
        command.max_output_bytes,
    )
    outcome = runner(request)
    failure = _run_failure(
        command.provider_id,
        analyzer_input.object_digest,
        outcome,
        descriptor,
    )
    if failure is not None:
        return failure
    parsed = parse_scan_result(outcome.stdout, descriptor, analyzer_input)
    if isinstance(parsed, Err):
        return _attempt(
            command.provider_id,
            analyzer_input.object_digest,
            AssessmentStatus.FAILED,
            "Analyzer scan output was malformed or incompatible.",
            descriptor,
        )
    return parsed.value


def to_security_assessment(
    object_digest: ObjectDigest,
    attempt: AnalyzerScanAttempt,
) -> Result[SecurityAssessment]:
    if attempt.descriptor is None or object_digest != attempt.object_digest:
        return _error("analyzer attempt has no matching object and handshake evidence")
    provider = ProviderAssessment(
        attempt.provider_id,
        attempt.descriptor.version,
        attempt.descriptor.rules_digest,
        attempt.status,
        attempt.coverage,
        attempt.detail,
    )
    maximum = max(
        (finding.severity for finding in attempt.findings),
        key=lambda item: item.rank,
        default=FindingSeverity.UNKNOWN,
    )
    try:
        return Ok(
            SecurityAssessment(
                1,
                object_digest,
                attempt.status,
                risk_from_evidence(attempt.status, maximum),
                maximum,
                attempt.coverage,
                attempt.findings,
                (provider,),
            )
        )
    except ValueError:
        return _error("analyzer attempt cannot form normalized security evidence")


__all__ = [
    "ANALYZER_INVALID",
    "PROTOCOL",
    "AnalyzerCommand",
    "AnalyzerDescriptor",
    "AnalyzerInput",
    "AnalyzerProcessKind",
    "AnalyzerProcessOutcome",
    "AnalyzerProcessRequest",
    "AnalyzerScanAttempt",
    "handshake_request_bytes",
    "parse_handshake",
    "parse_scan_result",
    "run_protocol_analyzer",
    "scan_request_bytes",
    "to_security_assessment",
]
