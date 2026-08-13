# Changelog

All notable AART changes are documented here. The project follows semantic versioning for the
executable; protocol, schema, artifact, importer, profile, and registry versions remain independent.

## 2.0.0 — 2026-08-13

The canonical remediation: one product, one interface, one compiler before every boundary.

Major for the executable, and deliberately so. Nine top-level commands were removed, which is
exactly the criterion `1.4.0` cited when it argued for a minor. Every registry and artifact
declaring the conventional `requires_aart` ceiling of `2.0.0` must raise its window to
`>= 2.0.0, < 3.0.0` before this release will read it. See Compatibility below.

### Removed

- The legacy catalog product: `list`, `install`, `status`, `check`, `update`, `uninstall`, `setup`,
  `migrate`, and `upstream` at the top level, `registry migrate`, the legacy catalog readers and
  writers, the legacy plan/merge/execute engine, the legacy install confirmation in the TUI, and
  the legacy `--source`/`--repo` inputs. The canonical `aart marketplace` family replaces the
  lifecycle verbs; `migrate` and `upstream` have no replacement.
- The 0.1 state conversion path. A recognized 0.1 state file is now refused at the boundary with
  one typed diagnostic naming remove-and-reinstall. `docs/release/migration-v1.md` is retained as
  released `1.0.0` evidence and marked historical.

### Added

- `SETUP.md` is a valid canonical package-root file, which is what makes the setup v2 migration
  documented in `1.4.0` actually performable — see Compatibility.
- Artifact dependencies: a manifest may declare `requires`, the transitive closure is resolved
  before review, and an unsatisfied dependency fails without mutation.
- `--memory-mode` on the canonical install verb. The modes were implemented and recorded in state,
  but the only flag that set them lived on a removed command.

### Changed

- Status, check, update, prune, uninstall, review, and outcome rendering are projections of one
  snapshot-bound reconciliation plan, so finalization is never reported independently of durable
  state. A bare `update` reconciles every installation in the requested scope.
- The published index carries the setup capabilities the recipe declares, so a host missing a
  required capability is refused before a credential is requested.
- `registry test --latest-version` and `registry init --minimum-version` default to the running
  release instead of a literal `1.0.0`.

### Fixed

- A forced memory replace preserves the displaced content as a managed sidecar and restores it on
  uninstall; a missing sidecar is a typed conflict rather than a silent delete.
- The semantic digest of an artifact declaring dependencies hashed its last requirement instead of
  itself.
- An empty Git checkout is no longer classified as a registry, so a consumer is not routed into
  maintainer curation.

### Compatibility

`1.4.0` required a package-root `SETUP.md` for setup v2 while its own package validation refused
any such file, so its documented migration produced a registry `1.4.0` itself rejected. `2.0.0`
resolves the contradiction; a registry that migrated its recipes requires `2.0.0` or later.

## 1.4.0 — 2026-08-12

Typed wizard errors, a transparent setup review, and a manual route out of every installer.

Minor for the executable: no command, subcommand, or flag was removed or renamed, and every
artifact declaring the conventional `requires_aart` ceiling of `2.0.0` keeps working. The one
breaking change belongs to the independently versioned setup-recipe protocol, which now supports a
single revision — a registry publishing a `1`/`1` recipe must be rebuilt before its setup-capable
artifacts install again. See Compatibility below.

### Changed

- Every wizard stage now reports failure through one typed diagnostic algebra instead of ad-hoc
  strings, and three previously indistinguishable outcomes are now separate and separately
  actionable:
  - **Recognized AART 0.1 installation state** (`install-state-legacy`) states the exact state
    path, the detected and required schema, and previews migration for the project and user scope
    independently. It is a report, not an action.
  - **Unreadable installation state** (`install-state-invalid`) keeps the parser's own precise
    location — file, line, column — and never suggests migration, because migration cannot repair
    a file that is not valid state.
  - **A defect in AART** (`tui-stage-internal`) names the stage, the operation, and the exception
    type only. No message, traceback, subprocess output, or setup input is displayed, and the
    wizard is not restarted after one.
- A stage-blocking failure opens the scrollable record with Retry/Back/Quit; a problem local to a
  row of a still-usable list stays in the fixed pane below that list. The status bar advertises
  keys and is never the only place an error appears.
- Setup review projects each effect as a bounded record with its identity, target, capability and
  recovery, replacing the terminal-width-dependent `module: summary -> target` line.
- Every setup review and every incomplete setup outcome names the package's `SETUP.md` route, with
  a commit-pinned HTTPS URL or a contained local path. Declining automation is a supported way to
  finish; it never rolls back an installed payload, and following the manual route is never
  recorded as consent.

### Fixed

- The packaging gate now proves a built wheel reproduces the checkout's typed diagnostics, rather
  than only proving the package imports.

### Compatibility

- **Breaking — setup recipes support exactly one revision.** `schema_version` and
  `protocol_version` must both be `2`, which is what makes the package-root `SETUP.md` mandatory. A
  recipe declaring the superseded `1`/`1` pair is refused when the catalog is read, and the error
  names the migration: raise both fields to `2` and add the document. A registry that still
  publishes a `1`/`1` recipe will have those artifacts rejected at discovery until it is rebuilt.
  Artifacts without a setup recipe are unaffected.
- **No installation state is migrated, rewritten, or deleted automatically.** Recognized 0.1 state
  is reported with the explicit `aart migrate state --from 0.1 … --dry-run` preview that a person
  chooses to run; `--apply` and `--rollback` remain separate explicit steps. State written by an
  earlier version stays readable exactly as written, and an already-recorded setup receipt keeps
  its stored version fields — rejecting an old *input* is not rewriting existing *state*.
- The CLI surface is backward compatible: no command, subcommand, or flag was removed or renamed,
  and `--yes`, `--approve-setup-effects`, trust authorization, and per-effect consent behave
  exactly as before.
- Installation state stays at v2, the native source/registry protocol at v1, and reporting at v1.
  No per-artifact `requires_aart` floor is raised by this release.

## 1.3.1 — 2026-08-11

Patch release fixing the read-only JSON Review for declarative marketplace setup.

### Fixed

- `aart marketplace setup ... --json` without `--yes` now projects setup-capable reviewed items as
  pending and prepares their exact canonical setup plans from already-installed immutable records.
- Review remains non-mutating and never grants source, custom-code, or effect authorization. Missing
  installation evidence remains a planning failure rather than an inferred or executable plan.
- Artifacts without a setup recipe remain `not-required`, and the existing Finalize path is
  unchanged.

### Compatibility

- No protocol, schema, configuration, installation-state, registry, reporting, or setup-recipe
  version changes.
- Registry and per-artifact `requires_aart` floors do not rise. Existing artifacts remain visible
  and installable; `1.3.1` is needed only by agents that require a complete non-mutating setup
  Review before deciding whether to finalize it.

## 1.3.0 — 2026-08-11

Minor release making consent-based usage reporting the default for new configurations and routing
reports to the registry that advertised each installed artifact.

### Changed

- New user configurations default to consent-based `prompt` reporting. Without an explicit central
  destination, results are partitioned by the registry through which each artifact was selected.
- Each advertising registry receives only its own artifact results. Source aliases stay local,
  identical endpoints are deduplicated, direct sources are omitted, and every proposed Issue keeps
  both default-No confirmations.
- Explicit `disabled` remains silent, while `automatic` still requires one explicit destination and
  can never be enabled by a registry advertisement.

### Compatibility

- Reporting protocol v1 and its serialized payload are unchanged. Registry aliases are routing-only
  client state and are never sent to a reporting destination.
- Existing explicit `disabled`, `prompt`, and `automatic` configurations retain their meaning. A
  missing reporting section now resolves to `prompt` without requiring a central destination.
- AART `1.2.0` rejects the new prompt-without-destination configuration form, so downgrading a
  configuration written by `1.3.0` requires adding a destination or explicitly disabling reporting.
- Registry and per-artifact `requires_aart` floors are not raised by this client-side behavior.

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
`migration guide`, and
[release evidence](docs/release/release-checklist-v1.md).
