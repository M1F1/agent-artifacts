# Installation-risk attestations and policy v1

An AART security attestation is canonical, digest-bound assessment evidence for one immutable
artifact object and one provider execution identity. It reduces uncertainty; it is not a claim
that an artifact is safe. AART itself remains dependency-free, and no `aart security` command
installs an optional analyzer.

## Cache identity and local storage

`AssessmentCacheKey` includes all inputs that can change the meaning of evidence:

- object digest;
- provider ID and provider version;
- rules digest;
- normalized analyzer-options digest;
- effective installation-policy digest.

Changing any field makes an older attestation `stale`. The local cache addresses the canonical
attestation by the complete cache-key digest under
`attestations/sha256/<prefix>/<remainder>.json`. Writes create private real directories and files,
reject symlink traversal and conflicting evidence, publish atomically without overwriting, and are
idempotent for identical evidence.

## Registry evidence and derived trust

A registry may commit:

```text
security/index.json
security/attestations/<attestation-sha256>.json
```

The canonical index binds each document path and byte digest to its full cache key. Every
registry-CI attestation also names the registry source ID, exact registry-inputs digest, and
resolved revision. `aart registry audit` verifies those bindings against `aart.index.json`, requires
evidence coverage for every compiled object, rejects evidence for unknown objects, rejects critical
installation risk, and reports high or unknown risk for explicit review.

The document cannot make itself trusted. `unverified`, `registry-reviewed`, or `company-reviewed`
trust is derived only when local policy matches the exact publisher source ID and registry-inputs
digest. Local results are classified separately as local evidence. Cryptographic signatures are
not part of v1; adding them requires a separately versioned protocol and does not weaken these
digest and local-policy checks.

## Bundle summary and installation policy

Bundle aggregation first deduplicates exact artifact coordinates and rejects conflicting evidence
for one coordinate. It exposes artifact count, worst installation risk, min/max range, mean of
known risk as secondary context, finding and status counts, aggregate coverage, provider set,
weakest attestation trust, and the exact worst, unknown, and stale coordinates.

Unknown and stale members never enter the mean and never disappear. Policy recomputes the summary
from per-artifact evidence and bases `allow`, `warn`, `confirm`, or `block` on worst risk,
unknown/stale/failed coverage, scope, provider suite, and locally derived trust. A favorable mean
cannot override a high, critical, or unknown member. Default policy warns for unavailable optional
evidence rather than making optional analyzers runtime dependencies.

## CLI

```console
# Run the zero-dependency baseline over an exact object selected from a compiled index.
aart security scan object.json --index aart.index.json --artifact skill/review \
  --lock aart.lock.json --cache /path/to/aart-security-cache

# Inspect canonical assessment or attestation evidence.
aart security show /path/to/attestation.json --json

# Verify canonical form and compare the full expected cache identity.
aart security verify /path/to/attestation.json \
  --object-digest sha256:<current-object-digest> --json

# Discover reviewed adapters already present on this machine; nothing is installed.
aart security analyzers
aart security suites
```

`scan` reads bounded real files, verifies the canonical object/index/optional lock, runs the pure
baseline, and optionally publishes a local attestation cache entry. `show` exposes provider
version, rules digest, coverage, risk, findings remediation, and status through the normalized
projection. `verify` returns non-zero for stale evidence. Publisher trust flags must supply source
ID, registry-inputs digest, and local trust together.

JSON and human output use “installation risk” and “assessment”; they deliberately expose no
boolean `safe` field.
