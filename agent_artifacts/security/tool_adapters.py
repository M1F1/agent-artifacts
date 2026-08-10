"""Reviewed pure normalizers for separately installed security command-line tools."""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass

from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import ObjectDigest
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.protocol.hashing import json_digest
from agent_artifacts.protocol.json import JsonArray, JsonObject, JsonValue, parse_json
from agent_artifacts.protocol.paths import SafeRelativePath, parse_relative_path

from .analyzers import (
    PROTOCOL,
    AnalyzerCommand,
    AnalyzerDescriptor,
    AnalyzerInput,
    AnalyzerProcessKind,
    AnalyzerProcessOutcome,
    AnalyzerProcessRequest,
    AnalyzerRunner,
    AnalyzerScanAttempt,
    ExecutableResolver,
)
from .model import (
    MAX_FINDINGS,
    AssessmentCoverage,
    AssessmentStatus,
    FindingSeverity,
    SecurityFinding,
    make_finding,
)

_ARTIFACT_TYPES = ("guideline", "hook", "mcp", "memory", "skill")
_VERSION_RE = re.compile(r"(?<![A-Za-z0-9])([0-9]+(?:\.[0-9]+){0,3}(?:[-+][A-Za-z0-9.-]+)?)")
_RULE_PART_RE = re.compile(r"[^a-z0-9]+")
_PINNED_REQUIREMENT_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]{0,127})=="
    r"(?P<version>[A-Za-z0-9][A-Za-z0-9._+!-]{0,127})"
    r"(?:[ \t]+--hash=sha256:[0-9a-fA-F]{64})*$"
)
_MAX_NATIVE_OUTPUT = 2 * 1024 * 1024
_TOOL_OUTPUT_INVALID = DiagnosticCode("security-tool-output-invalid")


def _error(message: str) -> Err:
    return Err((Diagnostic(_TOOL_OUTPUT_INVALID, Severity.ERROR, message),))


@dataclass(frozen=True, slots=True)
class BuiltInToolAdapter:
    provider_id: str
    executable: str
    capability: str
    file_extensions: tuple[str, ...]
    network_required: bool
    version_args: tuple[str, ...]
    scan_args: tuple[str, ...]
    accepted_scan_codes: tuple[int, ...]
    parser: str
    rules_revision: str = "adapter-v1"

    def __post_init__(self) -> None:
        commands_are_valid = True
        try:
            AnalyzerCommand(self.provider_id, self.executable, self.version_args)
            AnalyzerCommand(self.provider_id, self.executable, self.scan_args)
            AnalyzerDescriptor(
                self.provider_id,
                "0",
                PROTOCOL,
                (self.capability,),
                _ARTIFACT_TYPES,
                self.file_extensions,
                json_digest(JsonObject((("validation", True),))),
                self.network_required,
                100_000,
                10 * 1024 * 1024 * 1024,
            )
        except ValueError:
            commands_are_valid = False
        if (
            not commands_are_valid
            or not self.executable
            or not self.capability
            or self.parser not in {"ruff", "bandit", "detect-secrets", "pip-audit", "shellcheck"}
            or not self.version_args
            or not self.scan_args
            or not isinstance(self.accepted_scan_codes, tuple)
            or not self.accepted_scan_codes
            or any(
                not isinstance(item, int) or isinstance(item, bool) or not 0 <= item <= 255
                for item in self.accepted_scan_codes
            )
            or 0 not in self.accepted_scan_codes
            or len(set(self.accepted_scan_codes)) != len(self.accepted_scan_codes)
            or not isinstance(self.rules_revision, str)
            or not self.rules_revision
            or len(self.rules_revision) > 64
            or "\n" in self.rules_revision
            or "\r" in self.rules_revision
        ):
            raise ValueError("built-in tool adapter is invalid")

    @property
    def rules_digest(self) -> ObjectDigest:
        return json_digest(
            JsonObject(
                (
                    ("capability", self.capability),
                    ("accepted_scan_codes", JsonArray(self.accepted_scan_codes)),
                    ("executable", self.executable),
                    ("file_extensions", JsonArray(self.file_extensions)),
                    ("network_required", self.network_required),
                    ("parser", self.parser),
                    ("provider_id", self.provider_id),
                    ("revision", self.rules_revision),
                    ("scan_args", JsonArray(self.scan_args)),
                    ("version_args", JsonArray(self.version_args)),
                )
            )
        )


BUILTIN_TOOL_ADAPTERS = (
    BuiltInToolAdapter(
        "ruff",
        "ruff",
        "python-static",
        (".py",),
        False,
        ("--version",),
        ("check", "--isolated", "--ignore-noqa", "--output-format=json", "--no-cache", "."),
        (0, 1),
        "ruff",
    ),
    BuiltInToolAdapter(
        "bandit",
        "bandit",
        "python-static",
        (".py",),
        False,
        ("--version",),
        ("--ini", "/dev/null", "--ignore-nosec", "-r", ".", "-f", "json", "-q"),
        (0, 1),
        "bandit",
    ),
    BuiltInToolAdapter(
        "detect-secrets",
        "detect-secrets",
        "secret-detection",
        (),
        False,
        ("--version",),
        ("scan", "--all-files", "--no-verify"),
        (0,),
        "detect-secrets",
    ),
    BuiltInToolAdapter(
        "pip-audit",
        "pip-audit",
        "dependency-advisories",
        (".txt",),
        True,
        ("--version",),
        ("--format=json", "--progress-spinner=off", "--disable-pip", "--no-deps"),
        (0, 1),
        "pip-audit",
        "adapter-v1-pinned-requirements",
    ),
    BuiltInToolAdapter(
        "shellcheck",
        "shellcheck",
        "shell-static",
        (".bash", ".sh"),
        False,
        ("--version",),
        ("--format=json1", "--norc"),
        (0, 1),
        "shellcheck",
    ),
)


@dataclass(frozen=True, slots=True)
class DiscoveredToolAdapter:
    adapter: BuiltInToolAdapter
    executable_path: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.adapter, BuiltInToolAdapter) or (
            self.executable_path is not None
            and (
                not isinstance(self.executable_path, str)
                or not posixpath.isabs(self.executable_path)
                or posixpath.normpath(self.executable_path) != self.executable_path
                or self.executable_path == "/"
                or len(self.executable_path) > 1024
                or posixpath.basename(self.executable_path) != self.adapter.executable
            )
        ):
            raise ValueError("discovered tool adapter is invalid")

    @property
    def available(self) -> bool:
        return self.executable_path is not None


def discover_tool_adapters(
    *,
    resolver: ExecutableResolver,
) -> tuple[DiscoveredToolAdapter, ...]:
    """Resolve only pre-existing executables in reviewed deterministic order."""

    discovered: list[DiscoveredToolAdapter] = []
    for adapter in BUILTIN_TOOL_ADAPTERS:
        try:
            item = DiscoveredToolAdapter(adapter, resolver(adapter.executable))
        except ValueError:
            item = DiscoveredToolAdapter(adapter, None)
        discovered.append(item)
    return tuple(discovered)


def _attempt(
    adapter: BuiltInToolAdapter,
    object_digest: ObjectDigest,
    status: AssessmentStatus,
    detail: str,
    descriptor: AnalyzerDescriptor | None = None,
) -> AnalyzerScanAttempt:
    return AnalyzerScanAttempt(
        adapter.provider_id,
        object_digest,
        status,
        AssessmentCoverage(0, 1, (detail,)),
        detail,
        descriptor,
    )


def _relevant_files(
    adapter: BuiltInToolAdapter,
    analyzer_input: AnalyzerInput,
) -> tuple[SafeRelativePath, ...]:
    if adapter.parser == "pip-audit":
        return tuple(
            path
            for path, _size in analyzer_input.files
            if posixpath.basename(str(path)).casefold()
            in {"requirements.txt", "requirements-dev.txt"}
        )
    if not adapter.file_extensions:
        return tuple(path for path, _size in analyzer_input.files)
    return tuple(
        path
        for path, _size in analyzer_input.files
        if any(str(path).casefold().endswith(suffix) for suffix in adapter.file_extensions)
    )


def _version(data: bytes) -> str | None:
    if len(data) > 4096:
        return None
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return None
    match = _VERSION_RE.search(text)
    if match is None or len(match.group(1)) > 64:
        return None
    return match.group(1)


def _descriptor(adapter: BuiltInToolAdapter, version: str) -> AnalyzerDescriptor:
    return AnalyzerDescriptor(
        adapter.provider_id,
        version,
        PROTOCOL,
        (adapter.capability,),
        _ARTIFACT_TYPES,
        adapter.file_extensions,
        adapter.rules_digest,
        adapter.network_required,
        100_000,
        10 * 1024 * 1024 * 1024,
    )


def _scan_argv(
    discovered: DiscoveredToolAdapter,
    relevant: tuple[SafeRelativePath, ...],
) -> tuple[str, ...]:
    assert discovered.executable_path is not None
    adapter = discovered.adapter
    if adapter.parser == "shellcheck":
        return (
            discovered.executable_path,
            *adapter.scan_args,
            "--",
            *(str(path) for path in relevant),
        )
    if adapter.parser == "pip-audit":
        return (discovered.executable_path, *adapter.scan_args, "--requirement", "-")
    return (discovered.executable_path, *adapter.scan_args)


def _dynamic_file_limit(adapter: BuiltInToolAdapter) -> int | None:
    if adapter.parser == "shellcheck":
        return 65 - 1 - len(adapter.scan_args) - 1
    return None


def _requirements_stdin(
    relevant: tuple[SafeRelativePath, ...],
    analyzer_input: AnalyzerInput,
) -> Result[bytes]:
    requirements: dict[str, str] = {}
    for path in relevant:
        content = analyzer_input.content(path)
        if content is None or len(content) > 1024 * 1024:
            return _error("requirements content is unavailable or too large")
        try:
            text = content.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return _error("requirements content is not UTF-8")
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            match = _PINNED_REQUIREMENT_RE.fullmatch(line)
            if match is None:
                return _error("requirements contain an unpinned or unsupported entry")
            name = re.sub(r"[-_.]+", "-", match.group("name").casefold())
            if name in requirements:
                return _error("requirements contain a duplicate package")
            requirements[name] = line
    if not requirements:
        return _error("requirements contain no pinned dependencies")
    result = ("\n".join(requirements[name] for name in sorted(requirements)) + "\n").encode()
    if len(result) > _MAX_NATIVE_OUTPUT:
        return _error("normalized requirements exceed the input limit")
    return Ok(result)


def _process_failure(
    adapter: BuiltInToolAdapter,
    object_digest: ObjectDigest,
    outcome: AnalyzerProcessOutcome,
    descriptor: AnalyzerDescriptor | None,
    *,
    accepted_codes: tuple[int, ...] = (0,),
) -> AnalyzerScanAttempt | None:
    if outcome.kind is not AnalyzerProcessKind.COMPLETED:
        return _attempt(
            adapter,
            object_digest,
            AssessmentStatus.FAILED,
            "Optional analyzer process failed.",
            descriptor,
        )
    if outcome.returncode not in accepted_codes:
        return _attempt(
            adapter,
            object_digest,
            AssessmentStatus.FAILED,
            "Optional analyzer exited unsuccessfully.",
            descriptor,
        )
    return None


def _json(data: bytes) -> Result[JsonValue]:
    if len(data) > _MAX_NATIVE_OUTPUT:
        return _error("tool output exceeds the adapter limit")
    parsed = parse_json(data, max_depth=32, max_string_length=4096)
    if isinstance(parsed, Err):
        return _error("tool output is not strict JSON")
    return parsed


def _object(value: JsonValue, label: str) -> Result[dict[str, JsonValue]]:
    if not isinstance(value, JsonObject):
        return _error(f"{label} must be an object")
    return Ok(dict(value.entries))


def _array(value: JsonValue, label: str) -> Result[tuple[JsonValue, ...]]:
    if not isinstance(value, JsonArray) or len(value.items) > MAX_FINDINGS:
        return _error(f"{label} must be a bounded array")
    return Ok(value.items)


def _relative_path(raw: JsonValue, analyzer_input: AnalyzerInput) -> Result[SafeRelativePath]:
    if not isinstance(raw, str) or not raw or "\\" in raw or "\x00" in raw:
        return _error("tool finding path is invalid")
    candidate = raw
    if posixpath.isabs(candidate):
        prefix = analyzer_input.root + "/"
        if not candidate.startswith(prefix):
            return _error("tool finding path escapes the immutable input")
        candidate = candidate[len(prefix) :]
    while candidate.startswith("./"):
        candidate = candidate[2:]
    parsed = parse_relative_path(candidate)
    if isinstance(parsed, Err):
        return _error("tool finding path is unsafe")
    if parsed.value not in {item[0] for item in analyzer_input.files}:
        return _error("tool finding path is outside the declared input files")
    return parsed


def _rule_id(raw: JsonValue, *, prefix: str = "rule") -> Result[str]:
    if not isinstance(raw, (str, int)) or isinstance(raw, bool):
        return _error("tool rule identifier is invalid")
    normalized = _RULE_PART_RE.sub("-", str(raw).casefold()).strip("-")[:96]
    if not normalized:
        return _error("tool rule identifier is empty")
    if not normalized[0].isalpha():
        normalized = f"{prefix}-{normalized}"
    return Ok(normalized)


def _line(raw: JsonValue) -> Result[int | None]:
    if raw is None:
        return Ok(None)
    if not isinstance(raw, int) or isinstance(raw, bool) or not 1 <= raw <= 10_000_000:
        return _error("tool finding line is invalid")
    return Ok(raw)


def _finding(
    descriptor: AnalyzerDescriptor,
    rule_id: str,
    severity: FindingSeverity,
    path: SafeRelativePath | None,
    line: int | None,
) -> SecurityFinding:
    return make_finding(
        rule_id,
        severity,
        f"{descriptor.id} reported rule {rule_id}.",
        "Review the reported rule in the exact immutable artifact before installation.",
        provider_id=descriptor.id,
        path=path,
        line=line,
    )


def _ruff(
    value: JsonValue,
    descriptor: AnalyzerDescriptor,
    analyzer_input: AnalyzerInput,
) -> Result[tuple[SecurityFinding, ...]]:
    items = _array(value, "Ruff output")
    if isinstance(items, Err):
        return items
    findings: list[SecurityFinding] = []
    for value_item in items.value:
        item = _object(value_item, "Ruff finding")
        if isinstance(item, Err):
            return item
        location = _object(item.value.get("location"), "Ruff location")
        rule = _rule_id(item.value.get("code"))
        path = _relative_path(item.value.get("filename"), analyzer_input)
        if isinstance(location, Err) or isinstance(rule, Err) or isinstance(path, Err):
            return _error("Ruff finding is invalid")
        line = _line(location.value.get("row"))
        if isinstance(line, Err):
            return line
        findings.append(
            _finding(descriptor, rule.value, FindingSeverity.MEDIUM, path.value, line.value)
        )
    return Ok(tuple(findings))


def _bandit(
    value: JsonValue,
    descriptor: AnalyzerDescriptor,
    analyzer_input: AnalyzerInput,
) -> Result[tuple[SecurityFinding, ...]]:
    root = _object(value, "Bandit output")
    if isinstance(root, Err):
        return root
    errors = _array(root.value.get("errors"), "Bandit errors")
    if isinstance(errors, Err) or errors.value:
        return _error("Bandit reported incomplete analysis")
    items = _array(root.value.get("results"), "Bandit results")
    if isinstance(items, Err):
        return items
    severity_map = {
        "LOW": FindingSeverity.LOW,
        "MEDIUM": FindingSeverity.MEDIUM,
        "HIGH": FindingSeverity.HIGH,
    }
    findings: list[SecurityFinding] = []
    for value_item in items.value:
        item = _object(value_item, "Bandit finding")
        if isinstance(item, Err):
            return item
        rule = _rule_id(item.value.get("test_id"))
        path = _relative_path(item.value.get("filename"), analyzer_input)
        line = _line(item.value.get("line_number"))
        severity = item.value.get("issue_severity")
        if (
            isinstance(rule, Err)
            or isinstance(path, Err)
            or isinstance(line, Err)
            or severity not in severity_map
        ):
            return _error("Bandit finding is invalid")
        findings.append(
            _finding(descriptor, rule.value, severity_map[severity], path.value, line.value)
        )
    return Ok(tuple(findings))


def _detect_secrets(
    value: JsonValue,
    descriptor: AnalyzerDescriptor,
    analyzer_input: AnalyzerInput,
) -> Result[tuple[SecurityFinding, ...]]:
    root = _object(value, "detect-secrets output")
    if isinstance(root, Err):
        return root
    results = _object(root.value.get("results"), "detect-secrets results")
    if isinstance(results, Err) or len(results.value) > MAX_FINDINGS:
        return _error("detect-secrets results are invalid")
    findings: list[SecurityFinding] = []
    for raw_path, raw_items in sorted(results.value.items()):
        path = _relative_path(raw_path, analyzer_input)
        items = _array(raw_items, "detect-secrets file results")
        if isinstance(path, Err) or isinstance(items, Err):
            return _error("detect-secrets file result is invalid")
        for raw_item in items.value:
            item = _object(raw_item, "detect-secrets finding")
            if isinstance(item, Err):
                return item
            line = _line(item.value.get("line_number"))
            if isinstance(line, Err):
                return line
            finding_type = _rule_id(item.value.get("type"), prefix="pattern")
            if isinstance(finding_type, Err):
                return finding_type
            findings.append(
                _finding(
                    descriptor,
                    f"credential-pattern-{finding_type.value}",
                    FindingSeverity.HIGH,
                    path.value,
                    line.value,
                )
            )
            if len(findings) > MAX_FINDINGS:
                return _error("detect-secrets output exceeds the finding limit")
    return Ok(tuple(findings))


def _pip_audit(
    value: JsonValue,
    descriptor: AnalyzerDescriptor,
    analyzer_input: AnalyzerInput,
) -> Result[tuple[SecurityFinding, ...]]:
    dependencies = _array(value, "pip-audit dependencies")
    if isinstance(dependencies, Err):
        return dependencies
    findings: list[SecurityFinding] = []
    for raw_dependency in dependencies.value:
        dependency = _object(raw_dependency, "pip-audit dependency")
        if isinstance(dependency, Err):
            return dependency
        vulns = _array(dependency.value.get("vulns"), "pip-audit vulnerabilities")
        if isinstance(vulns, Err):
            return vulns
        for raw_vuln in vulns.value:
            vuln = _object(raw_vuln, "pip-audit vulnerability")
            if isinstance(vuln, Err):
                return vuln
            rule = _rule_id(vuln.value.get("id"), prefix="advisory")
            if isinstance(rule, Err):
                return rule
            findings.append(_finding(descriptor, rule.value, FindingSeverity.MEDIUM, None, None))
            if len(findings) > MAX_FINDINGS:
                return _error("pip-audit output exceeds the finding limit")
    return Ok(tuple(findings))


def _shellcheck(
    value: JsonValue,
    descriptor: AnalyzerDescriptor,
    analyzer_input: AnalyzerInput,
) -> Result[tuple[SecurityFinding, ...]]:
    raw_items: JsonValue = value
    if isinstance(value, JsonObject):
        raw_items = value.get("comments")
    items = _array(raw_items, "ShellCheck output")
    if isinstance(items, Err):
        return items
    severity_map = {
        "style": FindingSeverity.LOW,
        "info": FindingSeverity.LOW,
        "warning": FindingSeverity.MEDIUM,
        "error": FindingSeverity.HIGH,
    }
    findings: list[SecurityFinding] = []
    for raw_item in items.value:
        item = _object(raw_item, "ShellCheck finding")
        if isinstance(item, Err):
            return item
        raw_code = item.value.get("code")
        rule = _rule_id(f"sc{raw_code}" if isinstance(raw_code, int) else raw_code)
        path = _relative_path(item.value.get("file"), analyzer_input)
        line = _line(item.value.get("line"))
        level = item.value.get("level")
        if (
            isinstance(rule, Err)
            or isinstance(path, Err)
            or isinstance(line, Err)
            or level not in severity_map
        ):
            return _error("ShellCheck finding is invalid")
        findings.append(
            _finding(descriptor, rule.value, severity_map[level], path.value, line.value)
        )
    return Ok(tuple(findings))


def _parse_findings(
    adapter: BuiltInToolAdapter,
    data: bytes,
    descriptor: AnalyzerDescriptor,
    analyzer_input: AnalyzerInput,
) -> Result[tuple[SecurityFinding, ...]]:
    parsed = _json(data)
    if isinstance(parsed, Err):
        return parsed
    parsers = {
        "ruff": _ruff,
        "bandit": _bandit,
        "detect-secrets": _detect_secrets,
        "pip-audit": _pip_audit,
        "shellcheck": _shellcheck,
    }
    findings = parsers[adapter.parser](parsed.value, descriptor, analyzer_input)
    if isinstance(findings, Err):
        return findings
    if len({item.fingerprint for item in findings.value}) != len(findings.value):
        return _error("tool output contains duplicate finding fingerprints")
    return findings


def run_tool_adapter(
    discovered: DiscoveredToolAdapter,
    analyzer_input: AnalyzerInput,
    *,
    runner: AnalyzerRunner,
    allow_network: bool = False,
) -> AnalyzerScanAttempt:
    """Run one reviewed adapter while keeping the external package outside AART."""

    if not isinstance(allow_network, bool):
        raise ValueError("network consent must be explicit")
    adapter = discovered.adapter
    if discovered.executable_path is None:
        return _attempt(
            adapter,
            analyzer_input.object_digest,
            AssessmentStatus.NOT_SCANNED,
            "Optional analyzer is not installed.",
        )
    if adapter.network_required and not allow_network:
        return _attempt(
            adapter,
            analyzer_input.object_digest,
            AssessmentStatus.NOT_SCANNED,
            "Optional analyzer requires network access that was not approved.",
        )
    relevant = _relevant_files(adapter, analyzer_input)
    if not relevant:
        return _attempt(
            adapter,
            analyzer_input.object_digest,
            AssessmentStatus.NOT_SCANNED,
            "Artifact has no relevant files for this analyzer.",
        )
    dynamic_limit = _dynamic_file_limit(adapter)
    if dynamic_limit is not None and (
        len(relevant) > dynamic_limit or any(len(str(path)) > 1024 for path in relevant)
    ):
        return _attempt(
            adapter,
            analyzer_input.object_digest,
            AssessmentStatus.NOT_SCANNED,
            "Artifact exceeds the analyzer adapter input limits.",
        )
    scan_stdin = b""
    if adapter.parser == "pip-audit":
        requirements = _requirements_stdin(relevant, analyzer_input)
        if isinstance(requirements, Err):
            return _attempt(
                adapter,
                analyzer_input.object_digest,
                AssessmentStatus.NOT_SCANNED,
                "Artifact requirements are not safe pinned direct dependencies.",
            )
        scan_stdin = requirements.value
    version_request = AnalyzerProcessRequest(
        (discovered.executable_path, *adapter.version_args),
        analyzer_input.root,
        b"",
        10,
        4096,
    )
    version_outcome = runner(version_request)
    failure = _process_failure(adapter, analyzer_input.object_digest, version_outcome, None)
    if failure is not None:
        return failure
    version = _version(version_outcome.stdout + b"\n" + version_outcome.stderr)
    if version is None:
        return _attempt(
            adapter,
            analyzer_input.object_digest,
            AssessmentStatus.FAILED,
            "Optional analyzer version output was malformed.",
        )
    descriptor = _descriptor(adapter, version)
    scan_request = AnalyzerProcessRequest(
        _scan_argv(discovered, relevant),
        analyzer_input.root,
        scan_stdin,
        120,
        _MAX_NATIVE_OUTPUT,
    )
    scan_outcome = runner(scan_request)
    failure = _process_failure(
        adapter,
        analyzer_input.object_digest,
        scan_outcome,
        descriptor,
        accepted_codes=adapter.accepted_scan_codes,
    )
    if failure is not None:
        return failure
    findings = _parse_findings(adapter, scan_outcome.stdout, descriptor, analyzer_input)
    if isinstance(findings, Err):
        return _attempt(
            adapter,
            analyzer_input.object_digest,
            AssessmentStatus.FAILED,
            "Optional analyzer output was malformed or incompatible.",
            descriptor,
        )
    return AnalyzerScanAttempt(
        adapter.provider_id,
        analyzer_input.object_digest,
        AssessmentStatus.COMPLETE,
        AssessmentCoverage(1, 1),
        "Optional analyzer completed with normalized evidence.",
        descriptor,
        findings.value,
    )


__all__ = [
    "BUILTIN_TOOL_ADAPTERS",
    "BuiltInToolAdapter",
    "DiscoveredToolAdapter",
    "discover_tool_adapters",
    "run_tool_adapter",
]
