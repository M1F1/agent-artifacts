# Registry protocol v1

An AART registry is a native source with optional curation documents. It may own canonical packages
under `artifacts/`, or reference native packages in other repositories through `entries/`. The
reference fixture at `tests/fixtures/protocol/registry-v1/` exercises both forms.

## Owned, referenced, vendored

Three ways content reaches a consumer through one registry. They differ in who the consumer must
reach, who owns the version, and who can change the bytes that are delivered:

| | Authored here | Referenced (`entries/`) | Vendored (`artifacts/` + `provenance.json`) |
|---|---|---|---|
| Where the payload lives | this registry | upstream repository | this registry |
| Who the consumer reaches | this registry | this registry **and** the upstream origin | this registry |
| Who owns the version | this registry | upstream | this registry |
| Who can change delivered bytes | this registry | upstream, at a new commit the maintainer pins | this registry |
| Upstream must be an AART package | — | yes | no |
| A `requires` target | yes | no | yes |

One worked vendoring, from an upstream with an arbitrary layout through to re-vendoring when it
moves, is in [the vendoring tutorial](../tutorials/vendoring-v1.md).

Vendoring is not a third document format. A vendored artifact is an ordinary owned package that
carries `provenance.json`, so every rule for owned content applies to it unchanged and an AART that
predates vendoring reads it without being taught anything.

**What vendoring moves is the trust boundary.** Copying a subtree into `artifacts/` makes this
registry the distributor of somebody else's work: its consumers install those bytes on this
registry's word, never having seen the origin, and upstream's later fixes — including security
fixes — do not reach them until a maintainer vendors the artifact again. AART records where the
bytes came from, assesses exactly the bytes that would be written, and reports what it found. It
does not certify them. A vendor or re-vendor that completes with no findings means the copy was
made and pinned, and nothing more; responsibility for the copied content stays with the maintainer
who published it. Licensing is part of that responsibility: the copy carries whatever obligations
the upstream licence imposes, `artifact.json`'s `license` records what this registry publishes it
under, and `aart registry audit` reports a vendored artifact that records none.

**The copy is verified against the record it carries.** `origin.input_digest` is the digest of the
taken subtree, and it is recomputable from the package alone: the payload files not listed in
`aart.vendor.authored` are exactly the copied ones. `aart registry validate --strict` and
`aart registry audit` recompute it, and `aart registry revendor` recomputes it before it reaches the
network. A vendored payload edited after vendoring therefore fails, offline, without upstream being
contacted — a package that claims an origin must still match it. This is a consistency check, not an
authentication: it proves the package agrees with its own record, not that the record is true.

**Assessed bytes and delivered bytes are not the same set for `mcp`.** The vendor assessment covers
the whole copied subtree, because this registry is redistributing it; installation applies the
effects the type declares, and for `mcp` that is the `server` object from `payload/mcp.json` and
nothing else. `mcp` is the only type where the two differ, and the review says so beside the
assessment rather than leaving a reader to infer that a finding in a copied script is a finding in
something no consumer of that artifact runs. The per-type delivery table is in
[the native source protocol](native-source-v1.md).

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
(`aart registry scaffold --help`), or vendor the upstream content into a package this registry owns
(`aart registry vendor --help`), which copies the subtree and records where it came from. A promoted
native reference is not a route to this: it is the `entries/` case below.

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
