"""Pure, bounded, standard-library installation-risk baseline."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

from agent_artifacts.domain.identifiers import ObjectDigest
from agent_artifacts.domain.result import Err
from agent_artifacts.protocol.hashing import file_entry, json_digest, tree_digest
from agent_artifacts.protocol.json import JsonArray, JsonObject, JsonValue, parse_json
from agent_artifacts.protocol.native_models import PAYLOAD_FORMAT_BY_TYPE
from agent_artifacts.protocol.native_schema import (
    artifact_manifest_to_json,
    parse_artifact_manifest,
    parse_provenance,
    provenance_to_json,
)
from agent_artifacts.protocol.native_tree import SnapshotEntry, SnapshotEntryKind
from agent_artifacts.protocol.paths import SafeRelativePath, parse_relative_path
from agent_artifacts.protocol.registry_models import IndexArtifact, LockedArtifact
from agent_artifacts.store.model import ObjectCandidate

from .model import (
    MAX_FINDINGS,
    AssessmentCoverage,
    AssessmentStatus,
    FindingSeverity,
    InstallationRisk,
    ProviderAssessment,
    SecurityAssessment,
    SecurityFinding,
    make_finding,
    mark_assessment_stale_value,
    risk_from_evidence,
)

_PROVIDER_ID = "aart-baseline"
_PROVIDER_VERSION = "1"
_RULESET_REVISION = "baseline-v1.0"
_MAX_SCANNED_FILE_BYTES = 1024 * 1024
_MAX_AST_NODES = 50_000
_MAX_SHELL_LINES = 20_000
_RAW_FINDING_LIMIT = MAX_FINDINGS + 1
_EXPECTED_CATEGORIES = (
    "metadata",
    "provenance-lock",
    "declared-effects",
    "credentials",
    "python-ast",
    "json-mcp",
    "shell",
    "transport-pinning",
)


@dataclass(frozen=True, slots=True)
class _Rule:
    id: str
    severity: FindingSeverity
    message: str
    remediation: str


_RULES = (
    _Rule(
        "object-digest-mismatch",
        FindingSeverity.CRITICAL,
        "Canonical object bytes do not match the indexed object digest.",
        "Reacquire and verify the exact indexed object before installation.",
    ),
    _Rule(
        "manifest-missing",
        FindingSeverity.CRITICAL,
        "The canonical object has no regular artifact manifest.",
        "Rebuild the object from a valid native artifact package.",
    ),
    _Rule(
        "manifest-invalid",
        FindingSeverity.CRITICAL,
        "The artifact manifest cannot be validated as protocol v1.",
        "Correct the manifest and rebuild the immutable object.",
    ),
    _Rule(
        "manifest-digest-mismatch",
        FindingSeverity.CRITICAL,
        "The artifact manifest does not match the indexed manifest digest.",
        "Regenerate the index and lock from the exact artifact manifest.",
    ),
    _Rule(
        "manifest-index-mismatch",
        FindingSeverity.CRITICAL,
        "Manifest identity, compatibility, effects, or setup metadata differs from the index.",
        "Recompile the source and review the resulting index change.",
    ),
    _Rule(
        "payload-digest-mismatch",
        FindingSeverity.CRITICAL,
        "Payload bytes do not match the indexed payload digest.",
        "Reacquire or rebuild the exact immutable artifact object.",
    ),
    _Rule(
        "provenance-missing",
        FindingSeverity.HIGH,
        "Indexed origin provenance is absent from the object.",
        "Rebuild the object with matching canonical provenance evidence.",
    ),
    _Rule(
        "provenance-unexpected",
        FindingSeverity.MEDIUM,
        "The object contains provenance that is absent from the index.",
        "Recompile the source so index and object provenance agree.",
    ),
    _Rule(
        "provenance-invalid",
        FindingSeverity.HIGH,
        "Object provenance cannot be validated as protocol v1.",
        "Correct provenance metadata and rebuild the object.",
    ),
    _Rule(
        "provenance-index-mismatch",
        FindingSeverity.HIGH,
        "Object provenance differs from indexed origin evidence.",
        "Resolve the origin to one immutable commit and rebuild the index.",
    ),
    _Rule(
        "review-missing",
        FindingSeverity.MEDIUM,
        "No registry review decision is attached to this artifact.",
        "Review the exact object and record the decision in a controlled registry when appropriate.",
    ),
    _Rule(
        "review-pending",
        FindingSeverity.MEDIUM,
        "Registry review is still pending for this artifact.",
        "Complete review of the exact object before broad distribution.",
    ),
    _Rule(
        "review-rejected",
        FindingSeverity.HIGH,
        "Registry review rejected this artifact.",
        "Do not install until the rejection is resolved and a new object is reviewed.",
    ),
    _Rule(
        "lock-missing",
        FindingSeverity.HIGH,
        "Reviewed external provenance has no matching committed lock evidence.",
        "Generate and commit a lock that binds origin, commit, manifest, payload, and object digests.",
    ),
    _Rule(
        "lock-evidence-mismatch",
        FindingSeverity.CRITICAL,
        "Committed lock evidence differs from the indexed object or provenance.",
        "Regenerate the lock from the reviewed immutable source and investigate unexpected drift.",
    ),
    _Rule(
        "source-moving-ref",
        FindingSeverity.LOW,
        "The authored source selector is moving, while this object is pinned by a resolved commit.",
        "Review lock updates before accepting newly resolved content.",
    ),
    _Rule(
        "importer-warning",
        FindingSeverity.LOW,
        "The importer recorded one or more conversion warnings.",
        "Inspect importer warnings in the trusted maintainer workflow and correct lossy conversion.",
    ),
    _Rule(
        "install-effect-copy-tree",
        FindingSeverity.LOW,
        "Installation copies a directory tree into a harness destination.",
        "Review the exact destination and object file list before finalization.",
    ),
    _Rule(
        "install-effect-write-file",
        FindingSeverity.LOW,
        "Installation writes a managed file into a harness destination.",
        "Review the exact destination and replacement behavior before finalization.",
    ),
    _Rule(
        "install-effect-merge-json",
        FindingSeverity.MEDIUM,
        "Installation merges values into harness JSON configuration.",
        "Review the JSON target, identity, and managed rollback evidence.",
    ),
    _Rule(
        "install-effect-managed-block",
        FindingSeverity.MEDIUM,
        "Installation edits a managed block inside a user-controlled file.",
        "Review the marker, target, and preserved foreign content.",
    ),
    _Rule(
        "setup-capability-keychain",
        FindingSeverity.HIGH,
        "Setup requests credential-store access.",
        "Review credential identity and consent without exposing credential values.",
    ),
    _Rule(
        "setup-capability-filesystem",
        FindingSeverity.MEDIUM,
        "Setup requests filesystem mutation authority.",
        "Review every managed path and rollback effect.",
    ),
    _Rule(
        "setup-capability-managed-file",
        FindingSeverity.MEDIUM,
        "Setup requests managed-file mutation authority.",
        "Review every managed path and rollback effect.",
    ),
    _Rule(
        "setup-capability-docker",
        FindingSeverity.HIGH,
        "Setup requests container runtime execution.",
        "Require digest-pinned images and review runtime effects.",
    ),
    _Rule(
        "setup-capability-docker-pull",
        FindingSeverity.HIGH,
        "Setup requests a container image pull.",
        "Require an immutable image digest and approved network access.",
    ),
    _Rule(
        "setup-capability-network",
        FindingSeverity.HIGH,
        "Setup requests network access.",
        "Review exact endpoints and pin all remotely executed content.",
    ),
    _Rule(
        "setup-capability-process",
        FindingSeverity.MEDIUM,
        "Setup requests local process execution.",
        "Review fixed argv, executable identity, environment, and timeout.",
    ),
    _Rule(
        "setup-capability-custom-code",
        FindingSeverity.CRITICAL,
        "Setup requests execution of custom artifact code.",
        "Require explicit trust, policy approval, digest binding, and immutable run-copy review.",
    ),
    _Rule(
        "setup-capability-verify-command",
        FindingSeverity.MEDIUM,
        "Setup requests a verification command.",
        "Review the fixed executable argv, working directory, and timeout.",
    ),
    _Rule(
        "setup-capability-unknown",
        FindingSeverity.HIGH,
        "Setup declares a capability unknown to the baseline rules.",
        "Review and explicitly allow the capability only after understanding its effects.",
    ),
    _Rule(
        "setup-capabilities-undeclared",
        FindingSeverity.HIGH,
        "Setup exists without indexed capability evidence.",
        "Compile and review the complete setup capability set.",
    ),
    _Rule(
        "setup-capability-mismatch",
        FindingSeverity.HIGH,
        "Setup recipe capabilities differ from indexed capability evidence.",
        "Recompile the object and review the exact declared capability set.",
    ),
    _Rule(
        "setup-recipe-missing",
        FindingSeverity.HIGH,
        "Indexed setup recipe bytes are missing from the object.",
        "Rebuild the object with the exact declared setup recipe.",
    ),
    _Rule(
        "setup-recipe-invalid",
        FindingSeverity.HIGH,
        "Setup recipe is not strict JSON with a reviewable top-level object.",
        "Correct and validate the declarative setup recipe.",
    ),
    _Rule(
        "custom-setup-entrypoint",
        FindingSeverity.CRITICAL,
        "Setup declares a custom code entrypoint.",
        "Review its exact digest and require explicit custom-code authorization.",
    ),
    _Rule(
        "file-scan-limit",
        FindingSeverity.UNKNOWN,
        "A text-like file exceeds the bounded baseline scan limit.",
        "Inspect the file separately or use an independently installed analyzer with declared limits.",
    ),
    _Rule(
        "text-decode-failed",
        FindingSeverity.UNKNOWN,
        "A text-like file is not valid UTF-8 and was not fully inspected.",
        "Convert it to reviewable UTF-8 or inspect it with an appropriate external analyzer.",
    ),
    _Rule(
        "embedded-credential",
        FindingSeverity.CRITICAL,
        "A credential-like literal is embedded in artifact content.",
        "Remove the value, rotate it if real, and use runtime credential indirection.",
    ),
    _Rule(
        "python-parse-failed",
        FindingSeverity.UNKNOWN,
        "Python source could not be parsed by the running standard-library AST parser.",
        "Correct the syntax or inspect it with a compatible external analyzer.",
    ),
    _Rule(
        "python-node-limit",
        FindingSeverity.UNKNOWN,
        "Python AST exceeds the bounded baseline node limit.",
        "Split or inspect the source with an independently installed analyzer.",
    ),
    _Rule(
        "python-dynamic-execution",
        FindingSeverity.HIGH,
        "Python invokes dynamic code compilation or execution.",
        "Replace dynamic execution with explicit reviewed operations.",
    ),
    _Rule(
        "python-subprocess-shell",
        FindingSeverity.CRITICAL,
        "Python starts a subprocess with shell interpretation enabled.",
        "Use fixed argv with shell interpretation disabled.",
    ),
    _Rule(
        "python-os-system",
        FindingSeverity.HIGH,
        "Python invokes a command through os.system.",
        "Use a fixed argv subprocess call with shell interpretation disabled.",
    ),
    _Rule(
        "python-unsafe-deserialization",
        FindingSeverity.HIGH,
        "Python invokes a code-capable deserialization API.",
        "Use a data-only format and validate the parsed schema.",
    ),
    _Rule(
        "json-parse-failed",
        FindingSeverity.UNKNOWN,
        "A JSON file is not valid strict bounded JSON.",
        "Correct duplicate keys, encoding, structure, or size before installation.",
    ),
    _Rule(
        "mcp-shell-dispatch",
        FindingSeverity.HIGH,
        "MCP configuration dispatches through a command shell.",
        "Use a direct executable and fixed argument array.",
    ),
    _Rule(
        "shell-pipe-to-interpreter",
        FindingSeverity.CRITICAL,
        "Shell content pipes downloaded bytes directly to an interpreter.",
        "Download, verify a pinned digest, inspect, and execute as separate steps.",
    ),
    _Rule(
        "shell-privilege-escalation",
        FindingSeverity.HIGH,
        "Shell content requests privilege escalation.",
        "Remove privilege escalation or isolate it in an explicitly reviewed administrator procedure.",
    ),
    _Rule(
        "shell-destructive-broad-path",
        FindingSeverity.CRITICAL,
        "Shell content performs recursive deletion against a broad path.",
        "Restrict deletion to an exact validated managed path with recoverable behavior.",
    ),
    _Rule(
        "shell-dynamic-evaluation",
        FindingSeverity.HIGH,
        "Shell content dynamically evaluates constructed text.",
        "Replace eval with fixed commands and quoted arguments.",
    ),
    _Rule(
        "unpinned-package-install",
        FindingSeverity.MEDIUM,
        "Shell content installs a package without an exact version or digest constraint.",
        "Pin the package version and verify it through the approved package source.",
    ),
    _Rule(
        "insecure-transport",
        FindingSeverity.HIGH,
        "Artifact content references plaintext HTTP transport.",
        "Use authenticated HTTPS or another approved encrypted transport.",
    ),
    _Rule(
        "unpinned-container-image",
        FindingSeverity.HIGH,
        "Setup references a container image without an immutable SHA-256 digest.",
        "Pin the exact image digest and review registry provenance.",
    ),
    _Rule(
        "findings-truncated",
        FindingSeverity.UNKNOWN,
        "Additional baseline findings were omitted at the bounded result limit.",
        "Inspect the artifact with narrower inputs or additional independent analyzers.",
    ),
)
_RULE_BY_ID = {item.id: item for item in _RULES}
BASELINE_RULES_DIGEST = json_digest(
    JsonObject(
        (
            ("ast_node_limit", _MAX_AST_NODES),
            ("finding_limit", MAX_FINDINGS),
            ("revision", _RULESET_REVISION),
            (
                "rules",
                JsonArray(
                    tuple(
                        JsonObject(
                            (
                                ("id", item.id),
                                ("message", item.message),
                                ("remediation", item.remediation),
                                ("severity", item.severity.value),
                            )
                        )
                        for item in _RULES
                    )
                ),
            ),
            ("shell_line_limit", _MAX_SHELL_LINES),
            ("text_file_byte_limit", _MAX_SCANNED_FILE_BYTES),
        )
    )
)


@dataclass(frozen=True, slots=True)
class BaselineScanRequest:
    object_candidate: ObjectCandidate
    artifact: IndexArtifact
    lock: LockedArtifact | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.object_candidate, ObjectCandidate)
            or not isinstance(self.artifact, IndexArtifact)
            or (self.lock is not None and not isinstance(self.lock, LockedArtifact))
        ):
            raise ValueError("baseline scan request is invalid")


def _finding(
    rule_id: str,
    *,
    path: SafeRelativePath | None = None,
    line: int | None = None,
) -> SecurityFinding:
    rule = _RULE_BY_ID[rule_id]
    return make_finding(
        rule.id,
        rule.severity,
        rule.message,
        rule.remediation,
        path=path,
        line=line,
    )


def _payload_digest(entries: tuple[SnapshotEntry, ...]):
    values = []
    for entry in entries:
        raw = str(entry.path)
        if entry.kind is not SnapshotEntryKind.FILE or not raw.startswith("payload/"):
            continue
        parsed = parse_relative_path(raw.removeprefix("payload/"))
        if isinstance(parsed, Err):
            return parsed
        values.append(file_entry(parsed.value, entry.content, executable=entry.executable))
    return tree_digest(values)


def _setup_matches(manifest, indexed: IndexArtifact) -> bool:
    if manifest.setup is None or indexed.setup is None:
        return manifest.setup is None and indexed.setup is None
    return (
        manifest.setup.recipe == indexed.setup.recipe
        and manifest.setup.platforms == indexed.setup.platforms
    )


def _metadata_findings(
    request: BaselineScanRequest,
    files: dict[str, SnapshotEntry],
) -> tuple[tuple[SecurityFinding, ...], object | None, bool]:
    findings: list[SecurityFinding] = []
    failed = False
    if request.object_candidate.digest != request.artifact.object_digest:
        findings.append(_finding("object-digest-mismatch"))
        failed = True
    entry = files.get("artifact.json")
    if entry is None or entry.kind is not SnapshotEntryKind.FILE:
        findings.append(_finding("manifest-missing"))
        return tuple(findings), None, True
    parsed = parse_artifact_manifest(entry.content, path="artifact.json")
    if isinstance(parsed, Err):
        findings.append(_finding("manifest-invalid", path=entry.path))
        return tuple(findings), None, True
    manifest = parsed.value
    if json_digest(artifact_manifest_to_json(manifest)) != request.artifact.manifest_digest:
        findings.append(_finding("manifest-digest-mismatch", path=entry.path))
        failed = True
    expected_format = PAYLOAD_FORMAT_BY_TYPE.get(
        manifest.identity.kind  # type: ignore[arg-type]
    )
    if (
        manifest.identity != request.artifact.identity
        or manifest.version != request.artifact.version
        or manifest.summary != request.artifact.summary
        or manifest.payload.root.parts != ("payload",)
        or manifest.payload.format != expected_format
        or manifest.compatibility != request.artifact.compatibility
        or manifest.install != request.artifact.install
        or not _setup_matches(manifest, request.artifact)
    ):
        findings.append(_finding("manifest-index-mismatch", path=entry.path))
        failed = True
    payload = _payload_digest(request.object_candidate.entries)
    if isinstance(payload, Err) or payload.value != request.artifact.payload_digest:
        findings.append(_finding("payload-digest-mismatch"))
        failed = True
    return tuple(findings), manifest, failed


def _lock_matches(lock: LockedArtifact, artifact: IndexArtifact, provenance_digest) -> bool:
    provenance = artifact.provenance
    return (
        provenance is not None
        and lock.origin_url == provenance.origin_url
        and lock.resolved_commit == provenance.resolved_commit
        and lock.path == provenance.path
        and lock.manifest_digest == artifact.manifest_digest
        and lock.payload_digest == artifact.payload_digest
        and lock.object_digest == artifact.object_digest
        and lock.artifact_version == artifact.version
        and lock.review == artifact.review
        and lock.provenance_digest == provenance_digest
    )


def _provenance_findings(
    request: BaselineScanRequest,
    files: dict[str, SnapshotEntry],
) -> tuple[tuple[SecurityFinding, ...], bool, bool]:
    findings: list[SecurityFinding] = []
    incomplete = False
    failed = False
    entry = files.get("provenance.json")
    provenance = None
    provenance_digest = None
    if entry is not None:
        if entry.kind is not SnapshotEntryKind.FILE:
            findings.append(_finding("provenance-invalid", path=entry.path))
            failed = True
        else:
            parsed = parse_provenance(entry.content, path="provenance.json")
            if isinstance(parsed, Err):
                findings.append(_finding("provenance-invalid", path=entry.path))
                failed = True
            else:
                provenance = parsed.value
                provenance_digest = json_digest(provenance_to_json(provenance))
    indexed = request.artifact.provenance
    if indexed is not None and provenance is None:
        findings.append(_finding("provenance-missing"))
        failed = True
    elif indexed is None and provenance is not None:
        findings.append(_finding("provenance-unexpected", path=entry.path if entry else None))
    elif indexed is not None and provenance is not None:
        if (
            indexed.origin_url != provenance.origin.url
            or indexed.resolved_commit != provenance.origin.resolved_commit
            or indexed.path != provenance.origin.path
        ):
            findings.append(
                _finding("provenance-index-mismatch", path=entry.path if entry else None)
            )
            failed = True
        if provenance.warnings:
            findings.append(_finding("importer-warning", path=entry.path if entry else None))
    review = request.artifact.review
    if review is None:
        findings.append(_finding("review-missing"))
    elif review.status == "pending":
        findings.append(_finding("review-pending"))
    elif review.status == "rejected":
        findings.append(_finding("review-rejected"))
    lock_required = review is not None and indexed is not None
    if lock_required and request.lock is None:
        findings.append(_finding("lock-missing"))
        incomplete = True
    elif request.lock is not None:
        if not _lock_matches(request.lock, request.artifact, provenance_digest):
            findings.append(_finding("lock-evidence-mismatch"))
            failed = True
        elif re.fullmatch(r"[0-9a-f]{40}", request.lock.requested_ref) is None:
            findings.append(_finding("source-moving-ref"))
    return tuple(findings), incomplete, failed


_CAPABILITY_RULE = {
    "keychain": "setup-capability-keychain",
    "filesystem": "setup-capability-filesystem",
    "managed-file": "setup-capability-managed-file",
    "docker": "setup-capability-docker",
    "docker-pull": "setup-capability-docker-pull",
    "network": "setup-capability-network",
    "process": "setup-capability-process",
    "custom-code": "setup-capability-custom-code",
    "verify-command": "setup-capability-verify-command",
}


def _declared_findings(
    artifact: IndexArtifact,
    files: dict[str, SnapshotEntry],
) -> tuple[tuple[SecurityFinding, ...], bool]:
    findings = [_finding(f"install-effect-{effect}") for effect in artifact.install.effects]
    incomplete = False
    setup = artifact.setup
    if setup is None:
        return tuple(findings), incomplete
    if not setup.capabilities:
        findings.append(_finding("setup-capabilities-undeclared"))
        incomplete = True
    for capability in setup.capabilities:
        findings.append(
            _finding(_CAPABILITY_RULE.get(capability.value, "setup-capability-unknown"))
        )
    recipe = files.get(str(setup.recipe))
    if recipe is None or recipe.kind is not SnapshotEntryKind.FILE:
        findings.append(_finding("setup-recipe-missing", path=setup.recipe))
        return tuple(findings), True
    parsed = parse_json(recipe.content)
    if isinstance(parsed, Err) or not isinstance(parsed.value, JsonObject):
        findings.append(_finding("setup-recipe-invalid", path=recipe.path))
        return tuple(findings), True
    fields = dict(parsed.value.entries)
    raw_capabilities = fields.get("capabilities")
    if isinstance(raw_capabilities, JsonArray) and all(
        isinstance(item, str) for item in raw_capabilities.items
    ):
        recipe_capabilities = tuple(
            sorted(set(item for item in raw_capabilities.items if isinstance(item, str)))
        )
        indexed_capabilities = tuple(sorted(item.value for item in setup.capabilities))
        if recipe_capabilities != indexed_capabilities:
            findings.append(_finding("setup-capability-mismatch", path=recipe.path))
            incomplete = True
    else:
        findings.append(_finding("setup-capability-mismatch", path=recipe.path))
        incomplete = True
    if isinstance(fields.get("custom_entrypoint"), str):
        findings.append(_finding("custom-setup-entrypoint", path=recipe.path))
    return tuple(findings), incomplete


_TEXT_SUFFIXES = (
    ".cfg",
    ".env",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".py",
    ".sh",
    ".toml",
    ".ts",
    ".txt",
    ".yaml",
    ".yml",
    ".zsh",
)
_SECRET_PREFIX = re.compile(
    r"(?:AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{16,})"
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)[\"']?(token|password|passwd|secret|api[_-]?key)[\"']?\s*[:=]\s*[\"']?([^\s,;\"']{8,})"
)


def _text(entry: SnapshotEntry) -> tuple[str | None, str | None]:
    if len(entry.content) > _MAX_SCANNED_FILE_BYTES:
        return None, "file-scan-limit"
    try:
        return entry.content.decode("utf-8"), None
    except UnicodeDecodeError:
        return None, "text-decode-failed"


def _text_like(entry: SnapshotEntry) -> bool:
    raw = str(entry.path).lower()
    return raw.endswith(_TEXT_SUFFIXES) or entry.executable or entry.content.startswith(b"#!")


def _placeholder(value: str) -> bool:
    lowered = value.lower()
    return (
        value.startswith(("$", "<", "{{"))
        or "${" in value
        or "{{" in value
        or any(
            word in lowered for word in ("example", "placeholder", "redacted", "changeme", "your_")
        )
    )


def _credential_findings(
    entries: tuple[SnapshotEntry, ...],
) -> tuple[tuple[SecurityFinding, ...], tuple[str, ...]]:
    findings: list[SecurityFinding] = []
    skipped: list[str] = []
    for entry in entries:
        if entry.kind is not SnapshotEntryKind.FILE or not _text_like(entry):
            continue
        content, reason = _text(entry)
        if reason is not None:
            findings.append(_finding(reason, path=entry.path))
            skipped.append(f"credentials:{entry.path}:{reason}")
            continue
        assert content is not None
        detected = bool(_SECRET_PREFIX.search(content) or "-----BEGIN PRIVATE KEY-----" in content)
        if not detected:
            detected = any(
                not _placeholder(match.group(2)) for match in _SECRET_ASSIGNMENT.finditer(content)
            )
        if detected:
            findings.append(_finding("embedded-credential", path=entry.path))
    return tuple(findings), tuple(skipped)


def _call_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _python_findings(
    entries: tuple[SnapshotEntry, ...],
) -> tuple[tuple[SecurityFinding, ...], tuple[str, ...]]:
    findings: list[SecurityFinding] = []
    skipped: list[str] = []
    for entry in entries:
        if entry.kind is not SnapshotEntryKind.FILE or not str(entry.path).lower().endswith(".py"):
            continue
        content, reason = _text(entry)
        if reason is not None:
            findings.append(_finding(reason, path=entry.path))
            skipped.append(f"python-ast:{entry.path}:{reason}")
            continue
        assert content is not None
        try:
            tree = ast.parse(content, filename=str(entry.path))
        except (SyntaxError, ValueError):
            findings.append(_finding("python-parse-failed", path=entry.path))
            skipped.append(f"python-ast:{entry.path}:parse")
            continue
        nodes = tuple(ast.walk(tree))
        if len(nodes) > _MAX_AST_NODES:
            findings.append(_finding("python-node-limit", path=entry.path))
            skipped.append(f"python-ast:{entry.path}:nodes")
            continue
        for node in nodes:
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node.func)
            line = getattr(node, "lineno", None)
            if name in {
                "eval",
                "exec",
                "compile",
                "builtins.eval",
                "builtins.exec",
                "builtins.compile",
            }:
                findings.append(_finding("python-dynamic-execution", path=entry.path, line=line))
            if name == "os.system":
                findings.append(_finding("python-os-system", path=entry.path, line=line))
            if name in {"pickle.load", "pickle.loads", "marshal.load", "marshal.loads"}:
                findings.append(
                    _finding("python-unsafe-deserialization", path=entry.path, line=line)
                )
            if name.startswith("subprocess.") and any(
                keyword.arg == "shell"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
                for keyword in node.keywords
            ):
                findings.append(_finding("python-subprocess-shell", path=entry.path, line=line))
            if len(findings) >= _RAW_FINDING_LIMIT:
                skipped.append("python-ast:findings")
                return tuple(findings), tuple(skipped)
    return tuple(findings), tuple(skipped)


def _walk_json(value: JsonValue):
    if isinstance(value, JsonObject):
        for key, item in value.entries:
            yield key, item
            yield from _walk_json(item)
    elif isinstance(value, JsonArray):
        for item in value.items:
            yield from _walk_json(item)


def _shell_line_findings(
    line_text: str,
    *,
    path: SafeRelativePath,
    line: int | None,
) -> tuple[SecurityFinding, ...]:
    findings: list[SecurityFinding] = []
    if re.search(
        r"(?i)\b(?:curl|wget)\b[^|\n]{0,2048}\|\s*(?:/usr/bin/env\s+)?(?:sh|bash|zsh)\b", line_text
    ):
        findings.append(_finding("shell-pipe-to-interpreter", path=path, line=line))
    if re.search(r"(?i)(?:^|[;&|]\s*|\s)sudo(?:\s|$)", line_text):
        findings.append(_finding("shell-privilege-escalation", path=path, line=line))
    if re.search(
        r"(?i)\brm\s+(?:-[A-Za-z]*r[A-Za-z]*f|-rf|-fr)\s+(?:/|~|\$HOME|\$\{HOME\})(?:\s|$)",
        line_text,
    ):
        findings.append(_finding("shell-destructive-broad-path", path=path, line=line))
    if re.search(r"(?:^|[;&|]\s*|\s)eval(?:\s|$)", line_text):
        findings.append(_finding("shell-dynamic-evaluation", path=path, line=line))
    if re.search(r"\b(?:pip|pip3|python\s+-m\s+pip)\s+install\s+", line_text) and not re.search(
        r"(?:==|@sha256:|--require-hashes)", line_text
    ):
        findings.append(_finding("unpinned-package-install", path=path, line=line))
    return tuple(findings)


def _json_findings(
    entries: tuple[SnapshotEntry, ...],
) -> tuple[tuple[SecurityFinding, ...], tuple[str, ...]]:
    findings: list[SecurityFinding] = []
    skipped: list[str] = []
    sensitive = re.compile(r"(?i)(?:token|password|passwd|secret|api[_-]?key)")
    for entry in entries:
        if entry.kind is not SnapshotEntryKind.FILE or not str(entry.path).lower().endswith(
            ".json"
        ):
            continue
        content, reason = _text(entry)
        if reason is not None:
            findings.append(_finding(reason, path=entry.path))
            skipped.append(f"json-mcp:{entry.path}:{reason}")
            continue
        assert content is not None
        parsed = parse_json(content)
        if isinstance(parsed, Err):
            findings.append(_finding("json-parse-failed", path=entry.path))
            skipped.append(f"json-mcp:{entry.path}:parse")
            continue
        for key, value in _walk_json(parsed.value):
            if (
                sensitive.search(key)
                and isinstance(value, str)
                and len(value) >= 8
                and not _placeholder(value)
            ):
                findings.append(_finding("embedded-credential", path=entry.path))
            if key == "image" and isinstance(value, str) and "@sha256:" not in value:
                findings.append(_finding("unpinned-container-image", path=entry.path))
            if len(findings) >= _RAW_FINDING_LIMIT:
                skipped.append("json-mcp:findings")
                return tuple(findings), tuple(skipped)
        if str(entry.path) != "payload/mcp.json":
            continue
        for _key, value in _walk_json(parsed.value):
            if not isinstance(value, JsonObject):
                continue
            fields = dict(value.entries)
            command = fields.get("command")
            args = fields.get("args")
            if not isinstance(command, str) or not isinstance(args, JsonArray):
                continue
            string_args = tuple(item for item in args.items if isinstance(item, str))
            shell = command.rsplit("/", 1)[-1] in {"sh", "bash", "zsh"}
            if shell and "-c" in string_args:
                findings.append(_finding("mcp-shell-dispatch", path=entry.path))
                for argument in string_args:
                    findings.extend(_shell_line_findings(argument, path=entry.path, line=None))
                    if len(findings) >= _RAW_FINDING_LIMIT:
                        skipped.append("json-mcp:findings")
                        return tuple(findings), tuple(skipped)
    return tuple(findings), tuple(skipped)


def _shell_findings(
    entries: tuple[SnapshotEntry, ...],
) -> tuple[tuple[SecurityFinding, ...], tuple[str, ...]]:
    findings: list[SecurityFinding] = []
    skipped: list[str] = []
    for entry in entries:
        raw = str(entry.path).lower()
        is_shell = raw.endswith((".sh", ".bash", ".zsh")) or entry.content.startswith(
            (b"#!/bin/sh", b"#!/bin/bash", b"#!/usr/bin/env bash", b"#!/usr/bin/env zsh")
        )
        if entry.kind is not SnapshotEntryKind.FILE or not is_shell:
            continue
        content, reason = _text(entry)
        if reason is not None:
            findings.append(_finding(reason, path=entry.path))
            skipped.append(f"shell:{entry.path}:{reason}")
            continue
        assert content is not None
        lines = content.splitlines()
        if len(lines) > _MAX_SHELL_LINES:
            findings.append(_finding("file-scan-limit", path=entry.path))
            skipped.append(f"shell:{entry.path}:lines")
            lines = lines[:_MAX_SHELL_LINES]
        for number, line_text in enumerate(lines, start=1):
            findings.extend(_shell_line_findings(line_text, path=entry.path, line=number))
            if len(findings) >= _RAW_FINDING_LIMIT:
                skipped.append("shell:findings")
                return tuple(findings), tuple(skipped)
    return tuple(findings), tuple(skipped)


def _transport_findings(
    entries: tuple[SnapshotEntry, ...],
) -> tuple[tuple[SecurityFinding, ...], tuple[str, ...]]:
    findings: list[SecurityFinding] = []
    skipped: list[str] = []
    for entry in entries:
        if entry.kind is not SnapshotEntryKind.FILE or not _text_like(entry):
            continue
        content, reason = _text(entry)
        if reason is not None:
            findings.append(_finding(reason, path=entry.path))
            skipped.append(f"transport-pinning:{entry.path}:{reason}")
            continue
        assert content is not None
        for number, line_text in enumerate(content.splitlines(), start=1):
            if "http://" in line_text.lower():
                findings.append(_finding("insecure-transport", path=entry.path, line=number))
                if len(findings) >= _RAW_FINDING_LIMIT:
                    skipped.append("transport-pinning:findings")
                    return tuple(findings), tuple(skipped)
    return tuple(findings), tuple(skipped)


def _deduplicate_and_bound(
    findings: tuple[SecurityFinding, ...],
) -> tuple[tuple[SecurityFinding, ...], bool]:
    by_fingerprint = {str(item.fingerprint): item for item in findings}
    ordered = tuple(sorted(by_fingerprint.values(), key=lambda item: item.sort_key))
    if len(ordered) <= MAX_FINDINGS:
        return ordered, False
    truncated = _finding("findings-truncated")
    retained = tuple(
        sorted((*ordered[: MAX_FINDINGS - 1], truncated), key=lambda item: item.sort_key)
    )
    return retained, True


def _assessment(
    object_digest: ObjectDigest,
    findings: tuple[SecurityFinding, ...],
    skipped: tuple[str, ...],
    *,
    failed: bool,
) -> SecurityAssessment:
    bounded, truncated = _deduplicate_and_bound(findings)
    skipped_values = tuple(sorted(set((*skipped, *(("findings:truncated",) if truncated else ())))))
    incomplete_categories = {
        item.split(":", 1)[0]
        for item in skipped_values
        if item.split(":", 1)[0] in _EXPECTED_CATEGORIES
    }
    coverage = AssessmentCoverage(
        len(_EXPECTED_CATEGORIES) - len(incomplete_categories),
        len(_EXPECTED_CATEGORIES),
        skipped_values,
    )
    status = (
        AssessmentStatus.FAILED
        if failed
        else AssessmentStatus.COMPLETE
        if coverage.complete
        else AssessmentStatus.PARTIAL
    )
    maximum = max(
        (item.severity for item in bounded),
        key=lambda item: item.rank,
        default=FindingSeverity.UNKNOWN,
    )
    detail = {
        AssessmentStatus.COMPLETE: "Baseline rules completed for every declared coverage category.",
        AssessmentStatus.PARTIAL: "Baseline rules skipped one or more bounded coverage categories.",
        AssessmentStatus.FAILED: "Baseline evidence failed an object, manifest, provenance, or lock integrity check.",
    }[status]
    provider = ProviderAssessment(
        _PROVIDER_ID,
        _PROVIDER_VERSION,
        BASELINE_RULES_DIGEST,
        status,
        coverage,
        detail,
    )
    return SecurityAssessment(
        1,
        object_digest,
        status,
        risk_from_evidence(status, maximum),
        maximum,
        coverage,
        bounded,
        (provider,),
    )


def assess_installation_risk(request: BaselineScanRequest) -> SecurityAssessment:
    """Assess one immutable object without IO, network, processes, or optional imports."""

    entries = request.object_candidate.entries
    files = {str(entry.path): entry for entry in entries if entry.kind is SnapshotEntryKind.FILE}
    findings: list[SecurityFinding] = []
    skipped: list[str] = []
    failed = False

    metadata, _manifest, metadata_failed = _metadata_findings(request, files)
    findings.extend(metadata)
    failed |= metadata_failed
    if metadata_failed:
        skipped.append("metadata:integrity")

    provenance, provenance_incomplete, provenance_failed = _provenance_findings(request, files)
    findings.extend(provenance)
    failed |= provenance_failed
    if provenance_incomplete or provenance_failed:
        skipped.append("provenance-lock:evidence")

    declared, declared_incomplete = _declared_findings(request.artifact, files)
    findings.extend(declared)
    if declared_incomplete:
        skipped.append("declared-effects:capabilities")

    for scanner in (
        _credential_findings,
        _python_findings,
        _json_findings,
        _shell_findings,
        _transport_findings,
    ):
        scanner_findings, scanner_skipped = scanner(entries)
        findings.extend(scanner_findings)
        skipped.extend(scanner_skipped)

    return _assessment(
        request.object_candidate.digest,
        tuple(findings),
        tuple(skipped),
        failed=failed,
    )


def not_scanned_assessment(object_digest: ObjectDigest, reason: str) -> SecurityAssessment:
    coverage = AssessmentCoverage(0, len(_EXPECTED_CATEGORIES), ("baseline:not-requested",))
    provider = ProviderAssessment(
        _PROVIDER_ID,
        _PROVIDER_VERSION,
        BASELINE_RULES_DIGEST,
        AssessmentStatus.NOT_SCANNED,
        coverage,
        reason,
    )
    return SecurityAssessment(
        1,
        object_digest,
        AssessmentStatus.NOT_SCANNED,
        InstallationRisk.UNKNOWN,
        FindingSeverity.UNKNOWN,
        coverage,
        (),
        (provider,),
    )


def mark_assessment_stale(
    assessment: SecurityAssessment,
    *,
    current_object_digest: ObjectDigest,
    current_rules_digest: ObjectDigest,
) -> SecurityAssessment:
    baseline = next((item for item in assessment.providers if item.id == _PROVIDER_ID), None)
    if (
        assessment.object_digest == current_object_digest
        and baseline is not None
        and baseline.rules_digest == current_rules_digest
    ):
        return assessment
    return mark_assessment_stale_value(assessment)
