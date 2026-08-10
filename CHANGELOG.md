# Changelog

All notable AART changes are documented here. The project follows semantic versioning for the
executable; protocol, schema, artifact, importer, profile, and registry versions remain independent.

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
