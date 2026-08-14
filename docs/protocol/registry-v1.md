# Registry protocol v1

An AART registry is a native source with optional curation documents. It may own canonical packages
under `artifacts/`, or reference native packages in other repositories through `entries/`. The
reference fixture at `tests/fixtures/protocol/registry-v1/` exercises both forms.

## Authored inputs

`aart-registry.json` declares protocol compatibility, required compiler capabilities, a default
channel, and optional service advertisements. A `github-issues` usage advertisement makes that
registry eligible for the default prompt-only, per-registry reporting flow; it can never enable
automatic submission. Users and organization policy can disable prompts or select one explicit
central destination. Authored registry, entry, artifact, and index documents cannot assign
effective trust.

Each `entries/<type>/<name>.json` native reference records a credential-free Git URL, a reviewable
requested ref, the canonical package path ending in `<type>/<name>`, and a review record. A
registry-owned canonical package needs no duplicate entry document.

## Dependency scope

An artifact's `requires` resolves **inside one registry, against the artifacts that registry owns**.
This is deliberate, not a gap. A dependency on an artifact in another registry breaks whenever a
maintainer who does not own it changes their own registry, and neither the lock nor the index of the
depending registry can pin what it does not contain. Consumption federates across every configured
source; publication does not.

To depend on foreign content, put it in this registry: author the artifact here
(`aart registry scaffold --help`), or copy the upstream content into a package this registry owns and
record where it came from.

An `entries/` native reference is not a `requires` target. It offers a foreign package to consumers
of this registry — they resolve and install it from its own repository at the pinned commit — but the
declared dependency graph is validated over registry-owned packages, so a `requires` naming a
referenced identity is refused. The refusal says which of the two cases it is: an identity this
registry does not publish at all, or one it references from another origin rather than owning.

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
source identity, one-line summaries, version and digests, compatibility, optional per-artifact
`requires_aart` bounds, install effects, setup and provenance summaries, review evidence, and
derived collection membership. It never contains payload bytes, credentials, raw importer logs,
or a locally derived trust classification. The compiled bound must match the canonical manifest;
it is not a registry-wide minimum and is never inferred from the current executable version.

Both generation and parsing validate the complete collection graph. Duplicate or ambiguous
artifact identities, version exclusions, dangling artifact/collection references, cycles, and
membership claims that do not match the graph are rejected. Canonical JSON makes index bytes
independent of input ordering.

Maintainer-side entry, promotion, locked-update, review-digest, and apply-port rules are documented
in [`registry maintenance planning v1`](../registry/maintenance-planning-v1.md).
