# Changelog

All notable AART changes are documented here. The project follows semantic versioning for the
executable; protocol, schema, artifact, importer, profile, and registry versions remain independent.

## 2.3.0 — 2026-08-14

Registry vendoring. `2.2.0` left four residues open; this release answers the one with no small fix
— a promoted native reference is not a `requires` target — by giving a registry a way to own foreign
content instead of referencing it. Minor and additive: two maintainer commands, two audit findings,
one flag, one unreferenced module removed. The v11 schema freeze carries protocol versions identical
to v10 and differs in two inputs, both of them protocol prose, neither a parsed field.

### Added

- `aart registry vendor`: copies a subtree of any Git repository into this registry as an owned
  package pinned to a resolved commit, with `provenance.json` recording the origin. The upstream
  needs no AART markers. A vendored artifact is an ordinary owned package — no new document format,
  no protocol revision, and a valid `requires` target because the registry owns it. The subtree is
  taken whole or not at all: a repository containing a symlink anywhere cannot be acquired, and a
  symlink inside the subtree is refused. A wrapper authored beside the copy is adopted, not
  overwritten.
- `aart registry revendor`: re-resolves the ref the copy was taken at and reports `up-to-date`,
  `changed`, or `unreachable`. **An upstream that cannot be read is never reported as up-to-date.**
  `--check` writes nothing and exits non-zero on drift. Applying a movement requires the version the
  maintainer states, because upstream declares no version this registry can trust.
- The security assessment runs over the exact bytes a vendoring would write — copied payload and
  authored wrapper alike — and its findings are rendered in the review before Finalize, with the
  attestation committed beside the package. Findings do not block the action; the review states that
  a successful vendor reports what was copied and is not a safety claim.
- Licence discovery: a licence file at the subtree root pre-fills the manifest's `license` where the
  text settles the SPDX identifier. The GNU family is recognised but `-only`/`-or-later` is never
  guessed. `--license` states one explicitly, wins over the discovered value, and survives
  re-vendoring instead of being erased when upstream moves.
- Two `aart registry audit` findings: a vendored artifact recording no licence, and — under the new
  `--check-upstream` — vendored artifacts behind their origin, with unreachable origins reported as
  unknown. Neither fails the audit. Without the flag the audit reaches no network, so it stays a
  pure function of the committed snapshot. A hand-edited `aart.vendor` record does fail it.
- `vendor` and `revendor` as canonical maintainer actions in the text front-end, producing the same
  request value as flag mode and rendering the same review, asserted by test over one fixture.
- `docs/tutorials/vendoring-v1.md`, a worked vendoring from a marker-less monorepo through the
  assessment to re-vendoring when upstream moves.

### Changed

- `registry vendor`, `revendor`, `promote-native`, and `refresh-native` each name their counterpart
  in `--help`: the choice between referencing a package and copying it is the decision that matters.
- `docs/protocol/registry-v1.md` tabulates the three delivery modes — authored here, referenced,
  vendored — against who the consumer reaches, who owns the version, who can change delivered bytes,
  whether upstream must speak AART, and whether the identity is a `requires` target, and states in
  the protocol that vendoring moves the trust boundary into the registry.
- `docs/protocol/native-source-v1.md` states what a vendored package is on disk, including the
  namespaced `aart.vendor` extension holding the ref and the authored file list, verified against
  `importer.options_digest`.

### Removed

- `agent_artifacts/io/net.py`, an unreferenced GitHub-API helper reading `GITHUB_TOKEN` and
  `GITHUB_API_URL`. AART holds no credentials of its own and reaches remotes by running system Git;
  nothing shipped imported the module. The `validate` gate now refuses any package file naming
  either variable. The fact itself, true since `2.0.0`, is recorded in
  `docs/release/compatibility-v10-addendum.md`.

## 2.2.0 — 2026-08-14

Live acceptance v2 ran forty scenarios against `2.1.0` and filed thirteen residues; this release
closes nine — every finding whose fix does not require a major — and decides the three open
questions. Minor and additive: one flag on existing commands, one computed reconciliation status,
one refusal that the maintainer gate already enforced. The v10 schema freeze carries protocol
versions identical to v9 and differs in two inputs, neither of them a parsed field.

### Added

- `--expect <review-digest>` on every review-first consumer command, and `--expect <from>:<to>` on
  `aart source resubscribe`. Finalize proceeds only when the recomputed review still matches what
  was read; otherwise it refuses and renders the new plan in both text and JSON, so an operator who
  cannot see the new plan cannot re-authorize it. `--yes` alone keeps its exact meaning.
- `identity-changed`: an installation whose subscription is intact but whose origin now declares a
  different `source_id` reconciles as that instead of `source-unavailable` forever.
  `aart marketplace update` rebinds the record in the project that owns the installation, and the
  review field is digest-bound, so consent for one identity cannot apply another.
- A consumer-side refusal for a snapshot whose `aart-registry.json` and `aart-source.json` declare
  different identities, naming both values and both files, on the direct and local paths as well as
  registry-git. `registry validate --strict --frozen` already refused it; no registry that passes
  its own maintainer gate is affected.
- `python scripts/release.py wheel-digest`, which stamps `HEAD` into a throwaway copy, builds, and
  prints the digest of the wheel this commit publishes. Publishing that line with the release
  artifacts is a checklist step from v10 onward.

### Changed

- The plan review digest no longer moves on an unchanged workspace: `source_age_seconds` and source
  health left the digested value. Freshness is rendered instead — a `Source freshness:` line in text
  and a `source_freshness` field beside `review` in JSON, never inside it.
- Resolution failures name the layer that failed. An alias never configured, one configured but
  never synchronized, and a cold cache read under `--offline` each carry their own diagnostic and
  remediation; `artifact-not-found` survives for the case where it is true.
- `aart marketplace uninstall` plans from the durable manifest rather than resolving through the
  source, so an artifact whose subscription is gone can still be removed. **This is the one refusal
  loosened in this release**: `no-source-configured` no longer gates uninstall, because uninstall is
  not a content operation. Collections remain the exception.
- Uninstall reclaims what it emptied — the profile directories the removed record created, and the
  manifest and its lock with the last record in a scope. A directory holding anything the install
  did not put there is never removed, and a harness root such as `.claude` is never reclaimed.
  Uninstalling everything no longer leaves `.agent-artifacts/` behind.
- The `requires` refusal states its rule: the dependency must be published by this registry, with an
  identity the registry does not publish distinguished from one it references from another origin.
  The rule is unchanged and is now written down in `docs/protocol/registry-v1.md`.
- Per-source diagnostics render their remediation in text mode, not only under `--json`. A busy
  source lock reports the holder's age, pid, host, liveness, and the stale window; every
  `store-unavailable` failure carries remediation instead of a bare errno.
- `aart setup retry` and `aart setup rollback` are gone from rendered text. The retry names
  `aart marketplace setup`, which is the canonical verb; the rollback field names the artifact,
  profile, and scope to undo from the recorded receipt and states that no command does it.

### Packaging

- `agent_artifacts-2.2.0-py3-none-any.whl` is byte-reproducible: member dates come from the
  committer date stamped into the source, and member order, compression, permissions, and
  create-system are pinned rather than taken from the build platform. `SOURCE_DATE_EPOCH` is
  deliberately not read.

### Testing

- Every user-visible `aart …` mention in the shipped package — display reasons and TUI hints
  included, not only `Diagnostic.remediation` — is parsed by the real `cli.build_parser()`. Commands
  removed in `2.0.0` are legible to that guard because it reads the removals out of the
  compatibility tables, which makes the addendum part of the gate.
- Text and JSON carry the same remediation for every command family that renders both.
- Clean checkout → install → uninstall everything → `git status --porcelain` is empty, against a
  real git repository; a pre-existing profile directory holding foreign content survives.
- Two builds of one commit at different wall-clock times produce byte-identical wheels.

### Compatibility

No protocol revision, schema, store layout, or on-disk format changed, and no `requires_aart` window
needs re-authoring: `>= 2.0.0, < 3.0.0` admits this release. A `2.2.0` data root is fully readable by
`2.1.0` and `2.0.0`. See [compatibility-v10.md](docs/release/compatibility-v10.md).

## 2.1.0 — 2026-08-13

The source subscription lifecycle closes. `2.0.0` could subscribe to a source and refresh it, but
could not end a subscription or follow a source through a declared identity change. Minor, and
strictly additive: two commands are added, nothing is removed, renamed, or narrowed, and the v9
schema freeze is byte-identical to v8 in every declared input.

### Added

- `aart source remove` ends one subscription and owns both places it lives: the configuration entry
  and the managed snapshot, plus the `default_registry` pointer when it named that alias. The
  snapshot is discarded before the configuration is written, so an interrupted removal leaves a
  subscription `aart source sync` repairs rather than an unsubscribed origin whose store still binds
  an unreachable identity. Installed files and durable manifests are never touched.
- `aart source resubscribe` adopts a changed declared `source_id` at an unchanged origin and ref,
  keeping alias, kind, location, ref, and the default-registry flag — by writing no configuration at
  all. The review renders both identities, both revisions, and both snapshot digests, and finalize
  applies that exact transition or refuses, so an upstream that moves again between review and
  finalize is never absorbed silently. Resubscribing an unchanged identity is refused, naming
  `aart source sync`.
- Both commands reach the curses Sources stage on `r` and `i`, dispatching the same application
  request values as the flag-mode paths.

### Changed

- The `source sync` identity refusal names `aart source resubscribe --alias <alias>` instead of
  advising a "replace" that did not exist; the alias-already-configured and origin-already-configured
  refusals name `sync`, `resubscribe`, and `remove`. Diagnostic text only — no refusal was loosened,
  and adoption is never implicit.

### Testing

- The 2026-08-13 live-acceptance reproduction (`LAF-28`) is a test: recovery uses shipped commands
  only, with no hand-edited configuration and no directory deleted from the data root.
- Every source operation runs against a project holding an installed payload and a durable manifest,
  with the project tree compared byte for byte including `st_mtime_ns`; a managed symlink still
  resolves after its source is removed, and a durable manifest outlives its subscription and
  reconciles as `source-unavailable`.
- Every `aart …` command named in a source-area remediation is parsed by the real
  `cli.build_parser()`, so remediation text cannot drift from the shipped surface.

### Compatibility

No protocol revision, schema, store layout, or on-disk format changed, and no `requires_aart` window
needs re-authoring: `>= 2.0.0, < 3.0.0` admits this release. A `2.1.0` data root is fully readable by
`2.0.0`. See [compatibility-v9.md](docs/release/compatibility-v9.md).

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
