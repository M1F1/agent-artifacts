# Source origin freshness and sync policy

Source freshness is an evidence comparison, not a clock classification. AART compares the exact
validated candidate currently available at the configured origin with the durable current pointer:
declared source identity, resolved revision, and snapshot digest must all match.

## States

- `healthy` / `current` means the comparison ran and all three values matched.
- `not-synchronized` means the comparison ran and at least one value differed. The durable pointer
  is not moved by this check.
- `could-not-check` means origin acquisition could not complete. A last-known-good pointer remains
  available when one exists, but the interface does not call it current.
- `missing` means there is no durable pointer to compare.
- `degraded` and `invalid` remain local validation failures, distinct from origin availability.

Publication age remains observable evidence. It does not decide whether origin and snapshot match;
an old byte-identical snapshot is current, while a recently published snapshot can already be
`not-synchronized`.

## Effective sync mode

Every ordinary source-bearing entry point consumes the effective `sync.mode`:

- `auto` acquires, validates, and atomically publishes the origin candidate before projecting the
  source. Failure retains a complete last-known-good snapshot and reports `could-not-check`.
- `manual` acquires and validates a candidate under the source lease, compares it, and never
  publishes. A changed origin is therefore visible as `not-synchronized` until an explicit
  `aart source sync`.

The source stage applies this policy when bare `aart` starts. `source list`, `source health`, and
marketplace command composition use the same runtime operation. Offline operations never perform
the origin comparison and continue to use their explicit last-known-good contract.

Freshness checking shares the synchronization lease because Git acquisition updates the managed
mirror and temporary workspace even though it does not move `current.json`. Candidate validation
is mandatory before comparison, and a validator returning evidence other than the candidate it was
given is a local invalid-state result.

## Acceptance

Tests cover a young mismatched source, an old byte-identical source, an unavailable origin, manual
comparison without publication, automatic publication, and a second explicit synchronization that
returns `unchanged`.
