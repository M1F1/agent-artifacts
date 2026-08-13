# AART 2.1.0 compatibility matrix

AART `2.1.0` is a minor release over `2.0.0`. It adds two public commands and loosens nothing.
Every `2.0.0` configuration, source store, object store, installation record, registry, and
artifact is read and written exactly as before.

| Boundary | Supported in 2.1.0 | Change from 2.0.0 | Gate |
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
| CLI surface | **two commands added** | `source remove`, `source resubscribe` | CLI and e2e tests |

## Why this is minor

Two subcommands are added under an existing family and nothing is removed, renamed, or narrowed.
This is the criterion `compatibility-v7.md` stated and `compatibility-v8.md` failed on purpose; here
it holds. A `2.0.0` user upgrading to `2.1.0` loses no command, no flag, and no output shape.

The schema freeze differs from v8 in **no input**. `schema-freeze-v9.json` and
`schema-freeze-v8.json` carry identical `schema_inputs` digests and identical `protocol_versions`;
only `release_version` differs. That is the machine-checked statement that this release moves no
protocol boundary.

## Added

### `aart source remove`

Ends one subscription. It owns both places a subscription lives — the configuration entry and the
managed snapshot under the data root — and clears `default_registry` when it named the removed
alias. Review-first: without `--yes` nothing is written.

The managed snapshot is discarded before the configuration is written. A removal interrupted between
the two steps therefore leaves a subscription whose snapshot is absent, which `aart source sync`
repairs, rather than an unsubscribed origin whose store still binds an identity nothing can reach.

Installed artifacts and project files are never touched. An artifact installed from a removed source
keeps its files and its durable manifest and reconciles as `source-unavailable`; re-adding the alias
restores reconciliation.

### `aart source resubscribe`

Adopts a changed declared `source_id` at an unchanged origin and ref, keeping alias, kind, location,
ref, and the default-registry flag. Review-first, and the review renders both identities, both
revisions, and both snapshot digests.

Adoption authorizes a **transition**, not a destination. Finalize re-reads the origin and applies the
exact transition that was reviewed or refuses; an upstream that moves again between review and
finalize is never absorbed silently. Resubscribing an identity that did not change is refused, naming
`aart source sync`.

The operation writes no configuration at all, which is why the five preserved fields are preserved by
construction rather than by being rewritten.

## Changed

The identity-change refusal in `source sync` now names `aart source resubscribe --alias <alias>`
instead of advising the operator to "review the configured origin before replacing this source" —
there was no replace. The alias-already-configured and origin-already-configured refusals now name
`sync`, `resubscribe`, and `remove`.

This is diagnostic text, not a contract change. No refusal was loosened: `sync` still refuses a
changed identity, and adoption is never implicit.

## What did not change

No protocol revision, no schema, no store layout, no on-disk format, no consent semantics. Without
`--yes` every action still stops after Review and changes nothing. `--json` remains a rendering that
changes no effect. A `2.0.0` executable reads everything `2.1.0` writes and the reverse, because
`2.1.0` writes nothing new: `source remove` deletes existing structures and `source resubscribe`
publishes a snapshot in the shape `source sync` already published.

## Downgrade

A `2.1.0` data root is fully readable by `2.0.0`. The only asymmetry is operational, not structural:
a `2.0.0` executable cannot perform the two new operations, so an identity change at an unchanged
origin is again a dead end on that version. Nothing needs to be undone to downgrade.

## `requires_aart` windows

No window needs re-authoring. A registry or artifact declaring `min_inclusive: "2.0.0"`,
`max_exclusive: "3.0.0"` admits this release unchanged. A registry may declare a `2.1.0` floor if it
relies on the new commands in its own documentation, but nothing in the protocol requires it.
