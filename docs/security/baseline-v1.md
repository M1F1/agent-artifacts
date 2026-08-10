# Installation-risk baseline v1

The `aart-baseline` provider produces deterministic, explainable evidence for one immutable
canonical artifact object. It is implemented with the Python standard library, performs no IO,
network access, process execution, or optional imports, and does not certify an artifact or claim
general vulnerability coverage.

## Evidence contract

`SecurityAssessment` binds all results to the scanned `object_digest`. Its baseline provider entry
also binds provider ID/version and `rules_digest`; changing the current object or rules marks cached
evidence `stale`. Valid statuses are:

- `not-scanned` — the caller did not request a scan;
- `complete` — every baseline category completed within its declared bounds;
- `partial` — one or more categories were skipped or could not be parsed;
- `failed` — object, manifest, payload, provenance, or lock integrity evidence failed;
- `stale` — the object or rules identity changed after assessment.

Installation risk and finding severity use `unknown`, `low`, `medium`, `high`, and `critical`.
Unknown or incomplete coverage remains explicit. A high or critical observed finding is not hidden
by incomplete coverage; otherwise non-complete evidence reports unknown installation risk.

Every finding contains a stable provider/rule/location fingerprint, bounded one-line observed-fact
message, severity, relative path/line when known, and concrete remediation. Credential-like values
are never copied into a finding, fingerprint, provider detail, or serialized assessment.

Canonical JSON includes summary finding counts, total coverage, provider evidence, and normalized
findings. `assessment_bytes` and `parse_assessment` enforce one canonical representation suitable
for later digest-bound caches and attestations.

## Baseline coverage

The fixed v1 categories are:

1. object, artifact manifest, payload digest, and compiled index agreement;
2. provenance, review, and committed external-reference lock agreement;
3. declared install effects, setup capabilities, recipe declarations, and custom entrypoints;
4. conservative embedded-credential patterns without emitting matched values;
5. Python standard-library AST observations such as dynamic execution, `shell=True`,
   `os.system`, and code-capable deserialization;
6. strict JSON and MCP observations such as literal credentials, shell dispatch, and unpinned
   container images;
7. bounded shell observations including pipe-to-interpreter, privilege escalation, recursive broad
   deletion, dynamic evaluation, and unpinned Python package installation;
8. plaintext HTTP and related transport/pinning observations in text-like content.

Review, effects, and capabilities are reported even when no content heuristic matches. A completed
scan therefore means the documented rules ran within bounds, not that nothing else can happen at
runtime.

## Bounds and deterministic behavior

The object store already bounds canonical objects to 10,000 files, 10 MiB per file, and 100 MiB
total. The baseline applies tighter analysis limits:

- 1 MiB per text-like file;
- 50,000 Python AST nodes per file;
- 20,000 shell lines per file;
- 256 normalized findings per assessment.

Crossing a limit emits a generic rule finding, records the skipped category/path, and yields partial
coverage. Result ordering and fingerprints do not depend on input iteration order, locale, wall
clock, host paths, or environment variables. Finding truncation is explicit.

## Pure API

Callers pass already validated values; the provider never locates or fetches content itself:

```python
from agent_artifacts.security import BaselineScanRequest, assess_installation_risk

assessment = assess_installation_risk(
    BaselineScanRequest(object_candidate, index_artifact, matching_lock_or_none)
)
```

A reviewed external artifact with provenance requires a matching `LockedArtifact`. Native/direct
objects can still be assessed without a registry; absence or state of review remains visible as
evidence. Optional analyzer execution is specified in
[`analyzers-v1.md`](analyzers-v1.md). CLI scan/show, cache attestations, bundle aggregation, and
policy enforcement belong to SEC03 and do not change this pure baseline contract.
