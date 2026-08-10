# Optional security analyzers v1

AART can collect additional installation-risk evidence from independently installed command-line
tools without adding them to AART's Python environment. Optional analyzers are trusted processes,
not sandboxes, and their findings are evidence rather than a guarantee that an artifact is safe.
A missing or unusable provider produces an explicit `not-scanned` or `failed` attempt with unknown
coverage; it does not fail the surrounding AART operation.

## Process boundary

The process adapter resolves an already-installed executable and invokes a fixed argument vector
with `shell=False`. It passes JSON on standard input for protocol providers, captures standard
output/error under one hard combined byte cap, applies a timeout, and uses the immutable
content-addressed object root as
the working directory and scan path. Only `PATH`, locale fields, and `SYSTEMROOT` where present are
forwarded; `LC_ALL=C` is forced. Home paths, GitHub tokens, cloud credentials, and other ambient
environment values are not forwarded.

AART does not install a provider, import its Python package, run a package manager, or accept a
provider-selected command. Network use must be declared by the provider and approved by the
caller. This consent is orchestration policy, not network isolation: independently installed
analyzers remain trusted code with the operating-system access of the AART process.

Both input and output are bounded to 2 MiB for protocol providers. A descriptor must additionally
declare positive maximum input file and byte counts. The scan is not started when the exact object
exceeds those limits or its artifact type is unsupported. Timeout, failed start, non-zero exit,
oversized output, invalid UTF-8/JSON, identity drift, unsafe paths, and inconsistent coverage become
generic secret-free terminal attempts.

## `security-analyzer-v1` handshake

A protocol provider receives one canonical JSON document, including the trailing newline:

```json
{"action":"handshake","protocol":"security-analyzer-v1","schema_version":1}
```

It returns canonical JSON with exactly these fields:

```json
{
  "capabilities": ["python-static"],
  "file_extensions": [".py"],
  "max_input": {"bytes": 10485760, "files": 1000},
  "network": "none",
  "protocol": "security-analyzer-v1",
  "provider": {"id": "example-analyzer", "version": "2.1.0"},
  "rules_digest": "sha256:<64 lowercase hex characters>",
  "schema_version": 1,
  "supported_artifact_types": ["skill"]
}
```

`network` is `none` or `required`. Provider ID, version, rules digest, capabilities, artifact types,
file extensions, and limits are validated and retained as evidence. The returned provider ID must
equal the configured expected ID.

## Scan request and result

After a valid handshake AART sends a second canonical document to the same fixed command:

```json
{
  "action": "scan",
  "artifact_type": "skill",
  "input": {
    "file_count": 2,
    "object_digest": "sha256:<object digest>",
    "path": "/absolute/immutable/object/root",
    "total_bytes": 2048
  },
  "network_allowed": false,
  "protocol": "security-analyzer-v1",
  "schema_version": 1
}
```

The path refers to the exact verified CAS object. AART sends no setup values, credentials, source
tokens, or user secrets. The provider returns exact identity evidence from its handshake, status,
coverage, and normalized findings:

```json
{
  "action": "scan-result",
  "coverage": {"completed": 1, "expected": 1, "skipped": []},
  "findings": [
    {
      "fingerprint": "sha256:<normalized fingerprint>",
      "line": 7,
      "message": "Provider observed rule rule-101.",
      "path": "payload/main.py",
      "remediation": "Review the reported rule in the immutable artifact.",
      "rule_id": "rule-101",
      "severity": "high"
    }
  ],
  "protocol": "security-analyzer-v1",
  "provider": {
    "id": "example-analyzer",
    "rules_digest": "sha256:<same rules digest>",
    "version": "2.1.0"
  },
  "schema_version": 1,
  "status": "complete"
}
```

Finding paths must be safe relative paths present in the declared immutable input. A line requires
a path. The fingerprint is the canonical digest of provider ID, rule ID, path, and line. Duplicate
fingerprints, more than 256 findings, unknown fields, forged fingerprints, and provider/rules
identity changes reject the whole result. A protocol provider is responsible for supplying a safe,
bounded one-line message and remediation; built-in adapters go further and discard all raw tool
messages.

## Reviewed built-in command adapters

The built-in set is deterministic and contains no imports from the optional packages:

| Provider | Coverage | Input and important boundary |
|---|---|---|
| `ruff` | Python static rules | Uses isolated configuration, ignores `noqa`, emits JSON, and writes no cache |
| `bandit` | Python security static rules | Uses an empty fixed INI, ignores `nosec`, and fails on Bandit parse errors |
| `detect-secrets` | Credential-pattern heuristics | Disables network verification and never retains raw or hashed secret values |
| `pip-audit` | Known Python dependency advisories | Requires network consent, disables `pip`/resolution, and receives only sanitized pinned requirements on stdin |
| `shellcheck` | Shell static rules | Disables rc files and receives only declared `.sh`/`.bash` paths after `--` |

Each adapter first captures a bounded tool version, uses an adapter rules digest, invokes only its
reviewed fixed arguments, accepts documented finding exit codes, and converts native JSON into the
common evidence model. Raw descriptions, source excerpts, hashes, and messages from these tools are
not copied into AART output. `pip-audit` therefore accepts only UTF-8 direct dependencies pinned
with `==` (plus optional SHA-256 hashes), rejects includes, options, URLs, duplicate packages, and
unavailable content, sorts the accepted entries, and passes that sanitized document on standard
input. It does not resolve or install packages on behalf of an untrusted artifact. Unsupported or
changed native output fails closed as unknown coverage.

Callers discover the set through `discover_tool_adapters`, construct the exact input with
`analyzer_input_from_stored_object`, and invoke a selected adapter with `run_tool_adapter`. Generic
protocol providers use `AnalyzerCommand` and `run_protocol_analyzer`. Assessment aggregation,
attestation caching/freshness, suites, bundle statistics, policy gates, and CLI/TUI presentation are
owned by SEC03.
