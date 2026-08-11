# Changelog

All notable AART changes are documented here. The project follows semantic versioning for the
executable; protocol, schema, artifact, importer, profile, and registry versions remain independent.

## 1.2.0 — 2026-08-11

Minor release adding collection selection to the canonical marketplace lifecycle and advisory
runtime health over repository-supplied environment inventories.

### Added

- Canonical marketplace lifecycle commands accept `<source>/collection/<name>` and expand it to
  the exact versioned member coordinates compiled by the selected source before Review.
- The human TUI exposes compatible collections as bundle rows and explains why an incompatible
  collection cannot be selected.
- Artifacts may publish optional `com.m1f1.runtime-requirements` namespaced metadata with generic
  capability IDs and SemVer bounds.
- `aart marketplace health [COORDINATE ...] --environment PATH --json` compares those declarations
  with one explicit runtime inventory owned by the consuming repository.

### Compatibility

- The native Source/Registry Protocol remains v1. Runtime requirements use its existing opaque,
  namespaced artifact-extension boundary rather than a new compiled-index field.
- AART does not probe or install runtimes. Health is advisory, a valid report exits zero regardless
  of requirement status, and the JSON contract states `installation_blocking: false`.
- Missing environment evidence reports `unknown`; an out-of-range observed version reports
  `unsatisfied`. Neither result affects Install, Update, or Setup.
- Existing AART `1.1.1` clients ignore the advisory extension, keep artifacts visible/installable,
  and can install collection members individually.
- Registry and per-artifact `requires_aart` floors do not rise merely because this executable adds
  the shortcut and health command. A publisher changes a bound only if its payload actually invokes
  a new AART capability.

## 1.1.1 — 2026-08-11

Patch release implementing the per-artifact AART compatibility boundary documented for `1.1.0`.
The field is opt-in and manually maintained; ordinary executable changes do not raise artifact
minimums.

### Fixed

- Native artifact manifests and compiled registry index records now accept an optional
  `requires_aart` half-open version range.
- Compatibility checks reject only a selected artifact outside that range; an unrestricted
  artifact behaves exactly as before.
- Registry compilation propagates the bound deterministically, marketplace JSON exposes it when
  present, and install/security verification detects a manifest/index mismatch.

### Compatibility

- Existing artifacts omit `requires_aart` and gain no new restriction.
- A producer adds or raises the field only when that artifact actually depends on executable
  behavior unavailable in an older AART version; a patch release alone is never a reason.
- `1.1.0` did not parse this documented field. Therefore a source that begins authoring it must
  advertise `1.1.1` as its source-level parser floor, even when an individual artifact's functional
  minimum is `1.1.0`.

## 1.1.0 — 2026-08-11

Canonical non-interactive agent surface over configured sources, and a ref-aware managed source
store. No protocol, artifact, registry, or installation-state schema changed.

### Added

- `aart marketplace install/update/uninstall/status/setup`: JSON-first lifecycle over configured
  sources, with source-qualified `<source>/<kind>/<name>[@<version>]` coordinates and a deterministic
  ambiguity diagnostic instead of a guessed source.
- An explicit Review/Finalize boundary for non-interactive use: without `--yes` a command changes
  nothing, and `--yes` finalizes the digest of the review computed in the same process.
- Explicit setup authorization flags (`--authorize-untrusted-source`,
  `--authorize-custom-entrypoint`, `--approve-setup-effects`); omitting one denies rather than
  prompts.
- `aart source sync/health/doctor` for refreshing, diagnosing, and migrating configured sources
  without re-adding an existing alias.
- Ref-aware source storage keyed by `(kind, location, ref)`, so one Git origin can be tracked at
  several refs with separate mirrors, snapshots, and pointers.
- A versioned source-store layout (`<data_root>/sources/store.json`) with pure migration planning,
  atomic application, crash-resume, and explicit conflict/ambiguity refusal.

### Changed

- The repository ships no operational catalog: `skills/`, `guidelines/`, `mcp/`, `hooks/`,
  `memory/`, and `bundles/` were removed, the first-run `bundled-legacy` fallback is gone, and a
  validation gate keeps them from returning. Legacy external-checkout import is unchanged.
- Configuration uniqueness moved from Git origin to origin *and* ref. A `1.1.0` configuration using
  multi-ref sources is **not readable by `1.0.0`**; every `1.0.0` configuration still loads here.
- Reviewed source-management configuration writes are guarded by a configuration lock and an
  expected-digest compare-and-swap; a concurrent writer is refused with `config-write-conflict`
  rather than silently overwritten.
- The legacy `--source`/`--repo` warning names `aart marketplace` alongside the TUI.

### Upgrade note

The first run against a `1.0.0` source store reports configured sources as `missing` until
`aart source doctor --apply` or `aart source sync` runs; `aart source health` reports
`pending_store_migration`. Migration is never implicit.

## 1.0.0 — 2026-08-10

First stable release of AART as a standalone, zero-runtime-dependency compiler and package manager
for agent artifacts.

### Added

- Federated local/Git sources and optional public, company, team, or private registries.
- Strict native source, canonical artifact, registry entry/lock/index, configuration, reporting,
  security evidence, setup, and installation-state protocols.
- Deterministic marketplace compilation with qualified coordinates, compatibility, collections,
  provenance, locally derived trust, and collision-safe resolution.
- Durable source snapshots and a content-addressed object store with offline last-known-good,
  repair, locking, references, and garbage collection.
- Reviewed Copy and immutable managed Symlink installation for project and user scopes, including
  status, check, update, uninstall, retry, rollback, and explicit typed outcomes.
- Source-aware User and Maintainer TUI workflows with persistent basket/back navigation, health,
  descriptions, security evidence, setup queues, and preview-before-finalize curation.
- Built-in deterministic legacy-catalog import, native promotion, registry maintenance, 0.1.x
  state migration, exact backup, and later-process rollback.
- Zero-dependency risk baseline, optional isolated analyzers, attestations, bundle aggregation, and
  optional policy-approved usage reporting.
- Hermetic local editable/wheel lifecycle smoke and thirteen-scenario system/fault matrix.

### Changed

- The operational marketplace is no longer packaged with the executable. The public reference
  catalog is maintained independently at `M1F1/agent-artifacts-registry`.
- A registry and default registry are optional; direct-source-only use is a first-class path.
- Legacy `--source`/`--repo` catalog use is an explicit compatibility path instead of an implicit
  package-local default.

### Compatibility

- Python 3.10 through 3.14 are release-gated; the installed runtime uses only the standard library.
- Native Source/Registry Protocol v1 is stable; canonical installation state is schema v2.
- Delivery is from a local checkout or local wheel. Nexus/PyPI publication remains future work and
  is not required by any runtime, registry, state, Copy, or Symlink contract.

See the [compatibility matrix](docs/release/compatibility-v1.md),
[migration guide](docs/release/migration-v1.md), and
[release evidence](docs/release/release-checklist-v1.md).
