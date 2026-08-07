# Registry protocol v1

An AART registry is a native source with optional curation documents. It may own canonical packages
under `artifacts/`, or reference native packages in other repositories through `entries/`. The
reference fixture at `tests/fixtures/protocol/registry-v1/` exercises both forms.

## Authored inputs

`aart-registry.json` declares protocol compatibility, required compiler capabilities, a default
channel, and optional service advertisements. A service advertisement is inert: for example, a
`github-issues` usage destination does not enable reporting without separate user or organization
policy. Authored registry, entry, artifact, and index documents cannot assign effective trust.

Each `entries/<type>/<name>.json` native reference records a credential-free Git URL, a reviewable
requested ref, the canonical package path ending in `<type>/<name>`, and a review record. A
registry-owned canonical package needs no duplicate entry document.

## Committed lock boundary

`aart.lock.json` resolves every native reference to a lowercase 40-hex commit plus manifest,
payload, and immutable-object digests. Consumer resolution compares the current deterministic
registry-input digest and every entry URL/ref/path/review field with the committed lock. It returns
only the pinned commit and digests; it never dereferences the moving requested ref.

The registry-input digest includes canonical JSON and raw non-JSON files from the root markers and
`entries/`, `artifacts/`, and `collections/`. It excludes generated `aart.lock.json` and
`aart.index.json`, explicit directory entries, and unrelated repository files. Local and immutable
Git snapshots therefore hash identically. Symlinks and special files inside registry inputs fail
closed.

## Compiled index

`aart.index.json` is a deterministic, payload-free consumer projection. Records contain qualified
source identity, one-line summaries, version and digests, compatibility, install effects, setup
and provenance summaries, review evidence, and derived collection membership. It never contains
payload bytes, credentials, raw importer logs, or a locally derived trust classification.

Both generation and parsing validate the complete collection graph. Duplicate or ambiguous
artifact identities, version exclusions, dangling artifact/collection references, cycles, and
membership claims that do not match the graph are rejected. Canonical JSON makes index bytes
independent of input ordering.
