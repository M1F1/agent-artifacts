# AART 2.3.0 compatibility matrix

AART `2.3.0` is a minor release over `2.2.0`. It adds two registry-maintainer commands, two audit
findings, and one flag on `registry audit`; it removes one internal module that shipped code never
imported. No command, flag, or output shape is removed. Every `2.0.0`, `2.1.0`, and `2.2.0`
configuration, source store, object store, installation record, registry, and artifact is read and
written exactly as before.

| Boundary | Supported in 2.3.0 | Change from 2.2.0 | Gate |
|---|---|---|---|
| Python | 3.10+ | none | package and system matrix |
| Runtime dependencies | none | none | wheel metadata and `pip --no-deps` smoke |
| Native Source / Registry Protocol | v1 with `requires` | none | schema freeze and registry gates |
| Canonical package tree | `SETUP.md` allowed at the package root | none | native tree and registry gates |
| Provenance document | v1 | **one namespaced extension written**, `aart.vendor` | provenance and vendoring tests |
| Configuration schema | v1 | none | configuration tests |
| Source store layout | v2 | none | source store tests |
| Installation state | v2 | none | lifecycle tests |
| Setup recipe | v2 only | none | setup parser and canonical setup tests |
| Reporting | v1 | none | reporting tests |
| Security assessment | v1 | none | security tests |
| CLI surface | **two commands and one flag added** | `registry vendor`, `registry revendor`, `registry audit --check-upstream` | CLI and e2e tests |
| Maintainer text front-end | **two actions added** | `vendor`, `revendor` | TUI parity tests |
| Registry audit findings | **two added** | vendored artifact with no license; vendored artifact behind upstream | audit tests |
| Published wheel | byte-reproducible from the tag | digest published with the release | packaging tests |

## Why this is minor

Vendoring adds no document format. A vendored artifact is an ordinary owned package under
`artifacts/` that carries a `provenance.json` — the document AART has read since `2.0.0` — so every
loader, index, lock, and installer handles it with the code that already existed. **An AART that
predates this release reads a vendored artifact without being taught anything.**

The two facts re-vendoring needs and a provenance document does not otherwise carry — the ref the
copy was taken at, and which files the maintainer authored rather than copied — are written as the
namespaced extension `aart.vendor`. Namespaced extensions are a protocol-v1 feature, preserved
unchanged by readers that do not understand them, so this moves no protocol boundary. The record is
verified against `importer.options_digest`, which already covers URL, ref, and path: an edited
record is refused rather than trusted.

The schema freeze differs from v10 in **two inputs and no protocol version**.
`schema-freeze-v11.json` and `schema-freeze-v10.json` carry identical `protocol_versions`;
`docs/protocol/registry-v1.md` and `docs/protocol/native-source-v1.md` differ. Neither is a parsed
field: both documents gained sections stating what vendoring is and what it costs. That is the
machine-checked statement that this release moves no protocol boundary.

## Added

### `aart registry vendor`

Copies a subtree of any Git repository into this registry as an owned package pinned to a resolved
commit, with `provenance.json` recording the origin. The upstream needs no AART markers, and this
registry then owns the copy: it declares the version, and upstream fixes reach consumers only when
it is vendored again.

This is what answers the `2.2.0` residue that a promoted native reference is not a `requires`
target. A vendored artifact is registry-owned, so it is.

A repository containing a symlink anywhere cannot be acquired, and a symlink inside the taken
subtree is refused. The subtree is taken whole or not at all.

### `aart registry revendor`

Re-resolves the ref the artifact was vendored at and compares the subtree with the copy this
registry ships. It reports one of three dispositions — `up-to-date`, `changed`, `unreachable` — and
**an upstream that cannot be read is never reported as up-to-date**. `--check` writes nothing and
exits non-zero on `changed`, which is the shape a scheduled job needs. Applying a change requires
the version the maintainer states for it: upstream declares no version AART can trust, and a default
would answer the one question the command exists to ask.

### The assessment is part of the vendor review

Both commands assess exactly the bytes that would be written — the copied payload and the wrapper
the maintainer authored beside it — and render the findings in the review before Finalize, with the
attestation committed beside the package. A vendor that completes with no findings means the copy
was made and pinned; it is not a safety claim, and the review says so.

### Two audit findings and `--check-upstream`

`aart registry audit` reports a vendored artifact that records no license, and — under the new
`--check-upstream` flag — vendored artifacts that are behind their origin. Without the flag the
audit stays a pure function of the committed snapshot, so it works offline and in CI with no remote.
Neither finding fails the audit: being behind upstream is a fact about the world, not a defect in
the registry. A hand-edited `aart.vendor` record does fail it.

### Licence discovery

Vendoring reads a licence file at the root of the taken subtree and pre-fills the manifest's
`license` when the text settles the SPDX identifier. It never guesses between GNU `-only` and
`-or-later`, and reports what it found — or that it found nothing — in the review. `--license`
states one explicitly; a stated licence wins over a discovered one, and is carried through
re-vendoring rather than being erased when upstream moves.

### `vendor` and `revendor` in the text front-end

Both are canonical maintainer actions in the wizard, producing the same request value as flag mode
and rendering the same review. The parity is asserted by a test over one fixture, not assumed.

## Changed

`aart registry vendor --help` and the three neighbouring verbs each name their counterpart, so
choosing between referencing a package and copying it is a decision the help text supports.

The registry protocol document now tabulates all three delivery modes — authored here, referenced
through `entries/`, vendored into `artifacts/` — against who the consumer must reach, who owns the
version, who can change delivered bytes, whether upstream must speak AART, and whether the identity
is a `requires` target.

## Removed

`agent_artifacts/io/net.py`, an unreferenced GitHub-API helper reading `GITHUB_TOKEN` and
`GITHUB_API_URL`. It was importable but imported by nothing shipped, and it advertised a credential
AART does not hold: AART reaches remotes by running system Git, and has done so since `2.0.0`.
Nothing in the public CLI, protocol, or store surface referenced it. The `validate` gate now refuses
any package file naming either variable, so the promise cannot come back by accident.

## What did not change

No protocol revision, no schema, no store layout, no on-disk format, no consent semantics. Without
`--yes` every action still stops after Review and changes nothing, and AART still never commits or
pushes a maintainer checkout. How AART reaches a remote is unchanged and is recorded in
[`compatibility-v10-addendum.md`](compatibility-v10-addendum.md).

## Downgrade

A `2.3.0` data root is fully readable by `2.2.0`, `2.1.0`, and `2.0.0`. A registry containing
vendored artifacts is readable by all of them: the packages are ordinary owned packages, and the
`aart.vendor` extension is preserved unchanged by readers that do not understand it. The asymmetry
is operational, not structural — an older executable cannot re-vendor, and its `registry audit` does
not report the two new findings.

## `requires_aart` windows

No window needs re-authoring. A registry or artifact declaring `min_inclusive: "2.0.0"`,
`max_exclusive: "3.0.0"` admits this release unchanged. A registry that vendors artifacts does not
need to raise its floor: the packages it publishes are readable by every AART in that window.

## Published wheel

`agent_artifacts-2.3.0-py3-none-any.whl` is byte-reproducible: rebuilding the tagged commit anywhere
produces the same sha256, not merely the same member contents. The expected digest is published with
the release artifacts rather than committed, because it is a property of the tagged commit and
cannot live inside it. See [wheel-reproducibility-v1.md](wheel-reproducibility-v1.md).
