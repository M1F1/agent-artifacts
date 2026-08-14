# AART 2.2.0 compatibility matrix

AART `2.2.0` is a minor release over `2.1.0`. It adds one flag to existing commands, one
reconciliation status, and one refusal; it removes no command, no flag, and no output shape. Every
`2.0.0` and `2.1.0` configuration, source store, object store, installation record, registry, and
artifact is read and written exactly as before.

| Boundary | Supported in 2.2.0 | Change from 2.1.0 | Gate |
|---|---|---|---|
| Python | 3.10+ | none | package and system matrix |
| Runtime dependencies | none | none | wheel metadata and `pip --no-deps` smoke |
| Native Source / Registry Protocol | v1 with `requires` | none | schema freeze and registry gates |
| Canonical package tree | `SETUP.md` allowed at the package root | none | native tree and registry gates |
| Configuration schema | v1 | none | configuration tests |
| Source store layout | v2 | none | source store tests |
| Installation state | v2 | none | lifecycle tests |
| Setup recipe | v2 only | none | setup parser and canonical setup tests |
| Reporting | v1 | none | reporting tests |
| Security assessment | v1 | none | security tests |
| CLI surface | **one flag added** | `--expect` on review-first commands | CLI and e2e tests |
| Reconciliation status | **one status added** | `identity-changed` | update and status tests |
| Consumer acquisition | **one refusal added** | registry/source identity disagreement | source validation tests |
| Uninstall teardown | reclaims what it emptied | manifest, lock, and emptied profile directories | lifecycle and teardown tests |
| Published wheel | byte-reproducible from the tag | digest published with the release | packaging tests |

## Why this is minor

`--expect` is additive on every command that already reviewed; `--yes` alone keeps its exact
meaning. `identity-changed` is a computed reconciliation status, never a stored field. No command is
removed, renamed, or narrowed — the criterion `compatibility-v7.md` stated and `compatibility-v8.md`
deliberately failed.

The schema freeze differs from v9 in **two inputs and no protocol version**.
`schema-freeze-v10.json` and `schema-freeze-v9.json` carry identical `protocol_versions`;
`agent_artifacts/setup.py` and `docs/protocol/registry-v1.md` differ. Neither difference is a parsed
field: `setup.py`'s change is the text of the retry and rollback commands rendered to an operator,
and the protocol document gains a section stating a dependency rule the compiler already enforced.
That is the machine-checked statement that this release moves no protocol boundary.

## Added

### `--expect` on review-first commands

Every consumer lifecycle command that renders a review accepts `--expect <review-digest>`, and
`aart source resubscribe` accepts `--expect <from>:<to>`. Finalize proceeds only when the recomputed
review still matches what was read; otherwise it refuses and renders the new review, so an operator
who cannot see the new plan cannot re-authorize it.

`--yes` without `--expect` is unchanged: finalize what this process just computed.

This is usable only because the review digest stopped moving. `source_age_seconds` and source health
left the digested value, so two reviews of one unchanged workspace agree; freshness is still
rendered, as a `Source freshness:` line in text and a `source_freshness` field beside `review` in
JSON — never inside it, since `review` is the exact value the digest covers.

### `identity-changed`

An installation whose subscription is intact but whose origin now declares a different `source_id`
reconciles as `identity-changed` instead of reporting `source-unavailable` forever.
`aart marketplace update` acts on it in the project that owns the installation: the review states
both identities, and finalize rebinds the record. The review field is digest-bound, so consent read
for a rebinding to one identity cannot apply a rebinding to another.

### A refusal at consumer acquisition

A snapshot carrying both `aart-registry.json` and `aart-source.json` whose declared identities
disagree is refused when it is acquired, naming both values and both files. This was already refused
by `registry validate --strict --frozen`; the consumer accepted it. **No registry that passes the
maintainer gate is affected** — the check is the publisher's own rule applied consistently, not a new
rule.

## Changed

Resolution failures name the layer that failed. An alias that was never configured, one configured
but never synchronized, and a cold cache read under `--offline` used to report `artifact-not-found`
with empty remediation, about the one part of the request that was never wrong. Each now carries its
own diagnostic and remediation; `artifact-not-found` survives for the case where it is true.

`aart marketplace uninstall` plans from the durable manifest rather than resolving through the
source. **This is the one refusal loosened in this release, and only here**: `no-source-configured`
no longer gates uninstall, because uninstall is not a content operation — it reads what the project
already has. Collections remain the exception, since the manifest never records a registry-side
grouping.

Uninstall reclaims what it emptied: the profile directories the removed record created, and — with
the last record in a scope — `.agent-artifacts/manifest.json` and its lock. A directory holding
anything the install did not put there is never removed, and a harness root such as `.claude` is
never reclaimed at all. **Anything that expected an emptied `.agent-artifacts/` to remain after
uninstalling everything will find it gone**; that litter was `LAF-17`, reported in both live
acceptance runs as the operator's own uncommitted change.

The `requires` refusal states its rule. `skill/x requires missing skill/y` read as "not published
yet"; it now says the dependency must be published by this registry, distinguishes an identity the
registry does not publish from one it references from another origin, and carries remediation. The
rule itself is unchanged and is now written down in [the registry protocol](../protocol/registry-v1.md).

Remediation reaches text mode. Per-source diagnostics rendered their remediation only under
`--json`; text and JSON now carry the same lines for every family that has both.

## What did not change

How AART reaches a remote did not change here, and has not changed since `2.0.0`: it runs system
Git and holds no credentials of its own. That rule is stated in
[`compatibility-v10-addendum.md`](compatibility-v10-addendum.md), added during `2.3.0`.

No protocol revision, no schema, no store layout, no on-disk format, no consent semantics. Without
`--yes` every action still stops after Review and changes nothing. `--json` remains a rendering that
changes no effect. `2.2.0` writes nothing new: the added status is computed at reconciliation time
and never stored.

## Downgrade

A `2.2.0` data root is fully readable by `2.1.0` and by `2.0.0`. The asymmetries are operational,
not structural: an older executable cannot pass `--expect`, does not compute `identity-changed`, and
leaves the teardown litter behind again. Nothing needs to be undone to downgrade.

## `requires_aart` windows

No window needs re-authoring. A registry or artifact declaring `min_inclusive: "2.0.0"`,
`max_exclusive: "3.0.0"` admits this release unchanged.

## Published wheel

`agent_artifacts-2.2.0-py3-none-any.whl` is byte-reproducible: rebuilding the tagged commit anywhere
produces the same sha256, not merely the same member contents. The expected digest is published with
the release artifacts rather than committed, because it is a property of the tagged commit and
cannot live inside it. See [wheel-reproducibility-v1.md](wheel-reproducibility-v1.md).
