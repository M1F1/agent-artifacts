# AART 1.0 Implementation Plan

- **Status:** Execution in progress
- **Target:** `1.0.0`
- **Development train:** `1.0.0aN`
- **Tracking issue:** [#27](https://github.com/M1F1/agent-artifacts/issues/27)
- **Product requirements:** [docs/product/PRD-aart-1.0.md](docs/product/PRD-aart-1.0.md)
- **Technical specification:** [docs/design/SPEC-aart-1.0.md](docs/design/SPEC-aart-1.0.md)
- **Execution ledger:** [PROGRESS.md](PROGRESS.md)

## 1. Objective

Implement AART 1.0 as a zero-Python-runtime-dependency, federated compiler and package manager for
agent artifacts. AART must consume zero or more native local/Git sources and optional registries,
compile canonical artifact packages into supported harness layouts, maintain durable immutable
objects for Copy/Symlink installation, support controlled maintainer-time imports, expose optional
security assessment providers, and migrate existing 0.1.x catalogs/installations safely.

The implementation is complete only when every task in this plan is merged to `main`, every release
gate passes, the public reference-registry decision is resolved, and the stable version is
`1.0.0`. Nexus/PyPI publication is not required.

## 2. Scope and constraints

### In scope

- AART Source/Registry Protocol v1 and strict JSON schemas.
- Canonical artifact packages and deterministic compiler/index/lock output.
- Zero or more direct local/Git sources and optional registries/default registry.
- Organization policy, provenance, qualified identities, and trust derivation.
- Durable Git snapshots and content-addressed artifact objects outside the Python environment.
- Project/user Copy, managed Symlink, update/status/uninstall, setup, and migration.
- Maintainer scaffold/import/promote/validate/lock/build/audit/test workflows.
- Built-in zero-dependency installation-risk baseline and optional external analyzers.
- Source-aware persistent TUI and optional policy-approved usage reporting.
- Local editable/local-wheel delivery that is ready for later Nexus distribution.

### Out of scope

- Publishing the executable to Nexus/PyPI.
- Hosted non-Git registry/search services.
- Unreviewed importer plugins or consumer-time foreign conversion.
- Automatic maintainer commits/pushes from product code.
- Live symlinks to moving source channels.
- Cryptographic signing as a v1 requirement.
- Setup effect implementations beyond the approved macOS v1 boundary.

### Repository safety

- Preserve unrelated user files and dirty-worktree changes.
- Never stage, modify, delete, or format unrelated untracked files.
- Never force-push, bypass branch protection, or merge a red PR.
- Never publish a stable version/tag before task `REL01`.
- The approved public reference-registry target is exactly
  `https://github.com/M1F1/agent-artifacts-registry` with `PUBLIC` visibility. Do not create a
  different owner/name or change visibility without a new recorded decision.
- The legacy local `.git/hooks/pre-commit` mutates versions and wheels. P00, Q01, and V01 commits use
  `--no-verify` only after their explicit gates pass. V01 installs repository-owned, non-mutating
  hook guidance; after V01 merges and `core.hooksPath` points to `.githooks`, later task commits run
  normally and MUST NOT bypass that hook.

## 3. Delivery model

### One task, one branch, one PR, one merge

Every task ID below is an independently reviewable delivery unit:

1. Start from the latest `origin/main`.
2. Create `codex/aart-1-0-<task-id>-<slug>`.
3. Mark only that task `in_progress` in `PROGRESS.md`.
4. Execute Red -> Green -> Refactor.
5. Run task-specific and global gates.
6. Update the task row/evidence and mark it `complete` in the same branch.
7. Stage only task-owned files.
8. Commit intentionally. P00/Q01/V01 use `git commit --no-verify` because the legacy local hook
   mutates unrelated release files. After V01, use normal `git commit` with `.githooks` active.
9. Push the branch and create a ready PR linked to #27.
10. Wait for required CI checks and review/mergeability.
11. Squash-merge to `main` and delete the remote branch.
12. Verify the PR is merged and `origin/main` contains the task.
13. Remove only the explicitly created temporary worktree.
14. Continue immediately with the next unblocked task.

`P00` is the only exception: it lands the already-created planning documents from the current
worktree. It stages only the explicit documentation allowlist in that task. After `P00`, all code
tasks use isolated temporary Git worktrees created from `origin/main` so unrelated local files
cannot affect formatting, tests, or commits.

### Pull request contract

Each PR body contains:

- task ID and objective;
- issue link `#27`;
- DDD bounded context(s) touched;
- the first failing test(s) or characterization test(s);
- implementation summary and compatibility/migration notes;
- exact quality-gate commands and outcomes;
- security/privacy implications;
- explicit non-goals/follow-up tasks.

### Blockers

If a required gate, CI, branch protection, permission, or architectural precondition cannot be
resolved safely:

- do not merge;
- leave the branch/PR in a recoverable state;
- record the blocker and evidence in `PROGRESS.md`;
- do not skip to a dependent task;
- continue only with a task explicitly marked independent in the dependency graph;
- never weaken or delete a gate merely to make it green.

## 4. Architecture and DDD rules

### Bounded contexts

| Context | Owns | Does not own |
|---|---|---|
| Protocol | strict documents, versions, capabilities, canonical hashes | Git or filesystem IO |
| Artifact | canonical packages, type identity, compatibility, effects | source ranking/trust |
| Source | configured origins, snapshots, health, subscriptions | artifact installation |
| Registry | entries, collections, locks, indexes, maintainer curation | user harness files |
| Compiler | parse/resolve/normalize/validate/index diagnostics | durable mutation |
| Policy/Trust | allowed origins/capabilities, effective trust | self-declared source trust |
| Store | Git mirrors, snapshots, CAS, locks, GC | domain selection policy |
| Marketplace | source union, qualification, ambiguity, discovery | source mutation |
| Installation | plan/effects/state/update/uninstall | source conversion |
| Setup | reviewed capabilities, transactions, retry/rollback | payload resolution |
| Security Assessment | baseline, provider results, bundle aggregation, attestations | claims of safety |
| Reporting | redacted terminal session events and destination policy | installation success |
| Interface | CLI/TUI request mapping and rendering | domain decisions or raw IO rules |

### Dependency direction

New code follows this direction:

```text
interfaces -> application services -> domain
     |                |
     v                v
adapters ----------> ports
```

- Domain modules MUST NOT import adapters, CLI/TUI, subprocess, network, or platform paths.
- Application services orchestrate domain functions through injected ports.
- Ports are small typed protocols/callable contracts.
- Adapters own filesystem, Git, subprocess, clock, environment, Keychain, and GitHub effects.
- Interfaces map arguments/events into application requests and render typed outcomes.
- Existing flat modules are migrated incrementally; no big-bang package move is allowed.

### Aggregates and invariants

- `SourceSnapshot` is immutable after validation.
- `ArtifactObject` identity is its canonical digest.
- `CompiledMarketplace` is a deterministic value derived from source snapshots and policy inputs.
- `InstallationPlan` is immutable and carries every precondition needed for Finalize.
- `InstallationState` owns effect proof for one scope and is updated transactionally.
- `SetupTransaction` is separate from payload installation and records no secret values.
- `SecurityAssessment` is evidence for one object digest, provider/rules version, and time; it is not
  a certificate that an artifact is safe.

## 5. Functional-programming rules

Use a functional core with an imperative shell:

- Prefer frozen dataclasses, tuples, immutable mappings/projections, and explicit enums/literals.
- Pure functions receive all inputs and return values/results without hidden filesystem, network,
  environment, time, locale, or global-state access.
- Use explicit `Result`/typed diagnostics for expected domain failures; do not use exceptions as
  normal control flow.
- Accumulate independent validation errors deterministically rather than failing at the first one.
- Planners produce immutable actions; performers are the only mutation boundary.
- Parse -> validate -> normalize -> plan -> review -> apply remains observable in tests.
- Inject clock, random/ID generator, filesystem, Git runner, process runner, and environment reads.
- Sort every externally visible collection unless source order is itself part of the protocol.
- Never mutate an input domain object; return a replacement value.
- Keep functions small enough to test directly; isolate state machines as pure transitions.
- Serialization/deserialization is total over valid domain values and rejects unknown unsafe data.

## 6. TDD workflow

Every implementation task uses this loop:

1. **Characterize:** when changing 0.1.x behavior, first capture the intended legacy behavior.
2. **Red:** add the smallest failing unit/contract/integration test for the new requirement.
3. **Confirm red:** run the focused test and record the expected failure reason.
4. **Green:** add the minimum implementation that satisfies the test.
5. **Refactor:** improve names/boundaries without changing behavior; rerun focused tests.
6. **Negative cases:** add malformed, incompatible, partial-failure, and security boundary tests.
7. **Property matrix:** test ordering, idempotency, round trips, and deterministic output with
   multiple generated/sample inputs where relevant.
8. **Regression:** every discovered bug receives a failing regression test before its fix.
9. **Integration:** add port/adapter contract tests at IO boundaries.
10. **E2E:** add or update the smallest real workflow proving the vertical slice.

Tests use stdlib `unittest` unless an explicitly approved developer-only tool is added by `Q01`.
Runtime code remains stdlib-only. Tests MUST use temporary data/config/home directories and fake
network/process/Keychain adapters; they MUST NOT touch real user-global harness state.

## 7. Quality gates

### 7.1 Inner-loop gates

Run during Red/Green/Refactor:

- focused unit test module/method;
- Ruff check on changed Python files;
- mypy on the affected new bounded-context modules;
- deterministic fixture/golden comparison where applicable.

### 7.2 Pre-PR gates

After task `Q01`, the canonical command is:

```text
make quality
```

It MUST be non-mutating and aggregate:

```text
make format-check
make lint
make typecheck
make unit
make integration
make e2e
make validate
make coverage
make packaging-check
make docs-check
```

Before `Q01` lands, use the available equivalents appropriate to the task. `P00` is documentation
only and uses `git diff --check`, Markdown fence/link checks, and verification that #27 exists.

Formatting is a deliberate implementation step (`make format`) followed by review; the merge gate
is always the non-mutating `make format-check`.

### 7.3 Coverage policy

`Q01` records the current line/branch coverage baseline and introduces a non-decreasing fail-under
threshold. Never lower it. New domain/protocol/compiler/store/security modules target at least 90%
line coverage and must cover every declared error/terminal state. Global coverage is ratcheted
toward 90% without blocking early tasks on unrelated legacy gaps.

### 7.4 Type policy

- Existing mypy success is preserved.
- New bounded-context modules require complete public annotations.
- Enable stricter mypy options incrementally for new packages (`disallow_untyped_defs`,
  `warn_return_any`, `no_implicit_optional`, redundant/unused checks).
- Do not silence errors with broad `Any`, blanket ignores, or casts without a documented boundary.

### 7.5 CI policy

CI mirrors `make quality`, runs on minimum supported Python and the newest stable version supported
at implementation time, and keeps the local-wheel smoke build on Python 3.11+.

Task-specific CI may add:

- deterministic build comparison;
- frozen registry lock/index check;
- source/store concurrency/fault injection;
- migration fixtures;
- minimum/latest AART registry compatibility matrix;
- optional security analyzer adapter contract tests with fake executables.

No PR is merged until required CI is green. Flaky tests are fixed or quarantined with a tracked
root-cause task; they are never blindly rerun until green.

## 8. Task dependency graph

```text
P00 -> Q01 -> V01 -> D01 -> P01 -> P02 -> P03 -> C01 -> C02
                                  |                      |
                                  v                      v
                                CFG01 -> SRC01 -> CAS01 -> MKT01
                                                   |       |
                                                   v       v
                                                 IMP01 -> IMP02 -> REG01
                                                           |
                                                           v
                                                        STATE01
                                                           |
                                                           v
                                             INS01 -> INS02 -> LIFE01 -> SET01
                                                           |          |
                                                           v          v
                                                        SEC01 -> SEC02 -> SEC03
                                                                       |
                                            TUI01 -> TUI02 -> TUI03 <-+
                                               |                 |
                                               v                 v
                                             RPT01             SEP01
                                                                  |
                                                                  v
                                             MIG01 -> DIST01 -> E2E01 -> REL01
```

Tasks are executed in the listed plan order unless the dependency graph and `PROGRESS.md` prove an
alternative task is independent.

## 9. Execution tasks

### P00 — Land the AART 1.0 planning baseline

- **Depends on:** none.
- **Outcome:** merge the already prepared PRD, SPEC, README/TODO legacy notices, this `PLAN.md`, and
  `PROGRESS.md` without touching unrelated working-tree files.
- **TDD/docs-first:** validate Markdown fences/relative links, `git diff --check`, and consistency of
  version/registry/security terminology.
- **Allowlist:** `README.md`, `TODO.md`, `PLAN.md`, `PROGRESS.md`, `docs/product/PRD-aart-1.0.md`,
  `docs/design/SPEC-aart-1.0.md`, `docs/design/DESIGN.md`, `docs/plan/PLAN.md`.
- **Acceptance:** #27 is linked; registry is optional; direct sources, importers, immutable Symlink,
  alpha versioning, and security-assessment direction are represented; no implementation/version
  change is included.

### Q01 — Establish non-mutating quality gates and CI parity

- **Depends on:** P00.
- **Red tests:** demonstrate that the current CI omits Ruff/format/mypy/E2E/packaging/coverage and
  that quality commands can mutate or scan unrelated files.
- **Implement:** `make unit/integration/e2e/coverage/packaging-check/docs-check/quality`; developer
  dependencies for coverage and any required Markdown checker; CI matrix; hermetic temporary roots;
  documented tracked-file behavior.
- **Refactor:** reuse one script/config for local and CI gates rather than duplicating command logic.
- **Acceptance:** `make quality` is non-mutating, ignores unrelated untracked files in isolated task
  worktrees, exercises all gates, records baseline coverage in `PROGRESS.md`, and CI calls it.

### V01 — Introduce explicit alpha versioning and release discipline

- **Depends on:** Q01.
- **Red tests:** current bump script cannot parse prereleases and the legacy hook bumps every commit.
- **Implement:** PEP 440/SemVer-compatible `1.0.0aN` parsing; set the first implementation version to
  `1.0.0a1`; explicit version/bump/check commands; non-mutating repo-owned hook guidance; wheel name
  tests; prohibit stable tag before release gate.
- **Acceptance:** ordinary task commits never bump versions or rebuild tracked wheels; release bumps
  are explicit and tested; local wheel metadata matches package version.

### D01 — Create the DDD domain kernel and typed diagnostic contract

- **Depends on:** V01.
- **Red tests:** representative success/error/outcome values, deterministic sorting, immutable
  replacement, and serialization boundaries.
- **Implement:** domain identifiers, `Result`, diagnostic/error codes, source location, digest,
  terminal outcomes, pure collection helpers, and port conventions under incremental new modules.
- **Migration:** adapters translate legacy `model.py` values; do not move all legacy classes at once.
- **Acceptance:** new domain modules have no IO imports, are frozen/typed, and pass strict mypy.

### P01 — Strict JSON, canonical hashing, SemVer, and capability primitives

- **Depends on:** D01.
- **Red tests:** duplicate keys, unknown fields, invalid Unicode/path/int/float, SemVer prerelease
  ordering, compatible/incompatible bounds, canonical JSON/tree equality, executable-bit changes.
- **Implement:** strict JSON loader/writer, schema diagnostic primitives, canonical SHA-256 values,
  safe relative paths, SemVer/version bounds, and required/optional capability negotiation.
- **Acceptance:** equal logical inputs hash identically across order/host/locale; unsafe inputs fail
  with stable codes.

### P02 — Implement canonical artifact and native source protocol v1

- **Depends on:** P01.
- **Red tests:** all artifact types, source root discovery, descriptions, payload conventions,
  compatibility, install effects, setup references, prohibited source symlinks/special files.
- **Implement:** `aart-source.json`, `artifact.json`, provenance, collection primitives, source
  package loader, and adapters from current artifact shapes.
- **Acceptance:** no heuristic consumer crawl; one/multiple native packages compile identically from
  local and immutable Git trees; protocol fixtures are documented.

### P03 — Implement registry entry, lock, index, and collection schemas

- **Depends on:** P02.
- **Red tests:** registry-owned packages, native Git references, lock staleness, identity mismatch,
  self-reference avoidance, dangling/cyclic collections, deterministic index output.
- **Implement:** `aart-registry.json`, entry/lock/index documents, registry input digest, manifest/
  payload/object digests, review/provenance records, service advertisement.
- **Acceptance:** moving refs never reach consumers without committed resolved commit/digest; trust is
  absent from self-authored artifact data.

### C01 — Build the deterministic functional compiler pipeline

- **Depends on:** P03.
- **Red tests:** Acquire/Parse/Handshake/Resolve/Normalize/Validate/Index phase results, accumulated
  diagnostics, frozen consumer resolution, deterministic build replay, failure before publication.
- **Implement:** pure compiler inputs/outputs and application orchestration through source/object
  ports; no durable IO adapter yet.
- **Acceptance:** equal inputs produce byte-identical index/diagnostics; invalid inputs never yield a
  publishable snapshot.

### C02 — Compile compatibility, effects, collections, and source graphs

- **Depends on:** C01.
- **Red tests:** profile/platform/scope/mode compatibility, nested collection deduplication/cycles,
  external references, missing capabilities, removed artifacts, version-without-content rules.
- **Implement:** graph compiler and normalized marketplace records; preserve per-item reasons rather
  than filtering silently.
- **Acceptance:** broad selections can skip with reasons; explicit incompatible selections fail;
  deterministic collection expansion is reusable by bundles/security/install.

### CFG01 — Add platform config and organization policy

- **Depends on:** P01, D01.
- **Red tests:** macOS/Linux/test roots, empty config, zero sources, optional default registry,
  precedence, locked policy, denied CLI override, redaction, atomic writes, corrupt recovery.
- **Implement:** config/policy domain, ports, filesystem adapter, first-run application requests.
- **Acceptance:** AART works with no registry/source for non-content commands; policy always
  constrains flags/environment; tests never touch real home/config.

### SRC01 — Implement local/Git source acquisition and immutable snapshots

- **Depends on:** CFG01, C01.
- **Red tests:** local source, bare mirror init/fetch, private auth failure redaction, ref->commit,
  concurrent sync, timeout/offline, corrupt/incompatible candidate, last-known-good preservation.
- **Implement:** Git/process port and adapter (`shell=False`, no hooks), source locks, staged snapshot,
  atomic current pointer, health/doctor/status.
- **Acceptance:** remote source requires system Git but no Python runtime dependency; fetch failure
  never destroys current; credentials never enter output/state.

### CAS01 — Implement the immutable content-addressed artifact store

- **Depends on:** SRC01, P02.
- **Red tests:** digest verification, traversal/symlink/special-file rejection, concurrent identical
  publication, corrupt repair, read-only object, installed/setup references, safe GC/rollback.
- **Implement:** object port/adapter, stage/validate/atomic publish, reference index, verify/status/GC.
- **Acceptance:** published objects are immutable outside Python environments; GC dry-run is default
  and cannot remove referenced objects.

### MKT01 — Build the federated marketplace, qualification, and trust overlay

- **Depends on:** C02, CFG01, CAS01.
- **Red tests:** zero/one/multiple sources, duplicate type/name, default ranking without shadowing,
  qualified resolution, direct/local/registry/company trust derivation and invalidation.
- **Implement:** deterministic source union, search/list projections, ambiguity errors, policy trust
  overlay, source health/freshness presentation.
- **Acceptance:** source self-claims cannot produce reviewed trust; unqualified collisions fail with
  valid coordinates; JSON/human outputs include provenance and digest.

### IMP01 — Create the maintainer importer contract and legacy catalog importer

- **Depends on:** MKT01.
- **Red tests:** scan/plan/materialize/validate/diff/apply transitions; repeatability; lossy/ambiguous
  rejection; provenance; no execution; current 0.1.x catalog fixture conversion.
- **Implement:** built-in importer registry (no external plugins), provenance document, temp output,
  legacy `skills/guidelines/mcp/hooks/memory/bundles/upstreams.json` importer.
- **Acceptance:** equal pinned input/importer/options produce byte-identical canonical output;
  consumer paths cannot invoke an importer.

### IMP02 — Add native references, promotion, and locked upstream updates

- **Depends on:** IMP01, P03.
- **Red tests:** promote direct native source without copying, registry pin/ref lock, identity mismatch,
  changed upstream, rerun recorded importer, reviewable lock/index/provenance diff.
- **Implement:** registry entry add/promote/upstream check/update application services.
- **Acceptance:** native references avoid duplication; materialized foreign updates remain explicit
  maintainer diffs; no auto commit/push.

### REG01 — Deliver Maintainer registry commands and quality gate

- **Depends on:** IMP02.
- **Red tests:** init/scaffold/format/validate/lock/build/audit/test/diff/migrate dry-run/apply and
  writable-workspace enforcement.
- **Implement:** CLI/application services, deterministic templates, minimum/latest compatibility
  fixture, registry CI workflow/template, security/setup/provenance audits available so far.
- **Acceptance:** managed consumer snapshots are rejected as mutation targets; `--check` commands are
  non-mutating and CI-ready.

### STATE01 — Introduce installation manifest v2 and 0.1.x state migration

- **Depends on:** REG01.
- **Red tests:** v2 round trip/corruption, source alias+origin+commit, version/digests, profile/scope/
  mode/effect proof, backup, dry-run/apply/rollback, ambiguous legacy source, partial failure.
- **Implement:** new state domain/store and migration adapter; project state retained, user state moved
  to platform data root through explicit migration.
- **Acceptance:** no secrets/credential URLs/raw setup output; legacy state stays usable on failure;
  migration is idempotent and reversible.

### INS01 — Resolve/install canonical objects with Copy mode

- **Depends on:** STATE01, MKT01, CAS01.
- **Red tests:** qualified/unique resolution, cached/offline object, policy/compatibility, immutable
  plan preconditions, Copy file/tree/merge effects, drift/conflict/no-op/partial results.
- **Implement:** source-aware install application service and functional planner reusing legacy
  performers through adapters where safe.
- **Acceptance:** Finalize applies exactly the reviewed plan; Copy is default; installed state pins
  source and object evidence.

### INS02 — Implement durable managed Symlink and explicit retarget update

- **Depends on:** INS01.
- **Red tests:** pure file/tree links to CAS, mixed merge mode, environment deletion, source sync no
  retarget, explicit atomic update, broken/replaced/retargeted status, local mutable dev link.
- **Implement:** link planner/performer and object-reference lifecycle.
- **Acceptance:** managed links never target site-packages/venv/moving current; removing/recreating
  AART executable environment leaves links valid.

### LIFE01 — Migrate status, update, check, and uninstall lifecycle

- **Depends on:** INS02.
- **Red tests:** recorded subscription only, disabled/missing source, no same-name fallback, Copy/link/
  merge drift, upstream removal, prune, conflict/force, scope isolation, object reference release.
- **Implement:** source-aware lifecycle services and complete structured outcomes.
- **Acceptance:** fetch is distinct from update; every selection has a terminal result; uninstall
  removes only proven effects and preserves user content.

### SET01 — Bind reviewed setup to canonical objects, trust, and policy

- **Depends on:** LIFE01.
- **Red tests:** digest/recipe/plan binding, source trust downgrade, denied capability/custom entry,
  queue partial success/stop/retry/rollback, immutable run copy, secret redaction.
- **Implement:** setup request migration and policy overlay; retain macOS modules/keychain boundary.
- **Acceptance:** payload and setup outcomes remain separate; direct/unverified source setup is not
  implicitly authorized; no secret enters state/analytics.

### SEC01 — Add the zero-dependency installation-risk baseline

- **Depends on:** SET01, P02, P03.
- **Red tests:** `not-scanned/complete/partial/failed/stale`, digest binding, manifest/provenance/lock
  risks, declared capabilities/effects, Python AST, JSON/MCP, bounded shell heuristics, findings.
- **Implement:** pure baseline rules and normalized `SecurityAssessment`; use wording “installation
  risk”, never “safe”; no network or optional imports.
- **Acceptance:** baseline is deterministic, bounded, explainable, and cannot claim vulnerability
  coverage it does not have.

### SEC02 — Add out-of-process optional security analyzer providers

- **Depends on:** SEC01.
- **Red tests:** provider discovery, version/capability handshake, JSON protocol, timeout/crash/
  malformed output, minimal environment, network declaration, duplicate finding fingerprints.
- **Implement:** `security-analyzer-v1` subprocess contract and built-in command adapters for an
  initial reviewed set such as Ruff/Bandit, detect-secrets, pip-audit, and ShellCheck; optional MCP/
  IaC adapters remain capability-gated.
- **Acceptance:** providers install independently and are never auto-installed/imported into AART;
  absence yields partial/unknown coverage, not failure of core operation; runtime dependencies stay
  empty.

### SEC03 — Add security attestations, bundle aggregation, policy gates, and UI data

- **Depends on:** SEC02, C02, REG01.
- **Red tests:** assessment cache/attestation bound to object+provider+rules digest, staleness, trust,
  registry CI result, bundle deduplication, worst/range/mean/coverage, unknown/high policy gates.
- **Implement:** security index/attestation schema, bundle summary, policy decisions, CLI show/scan/
  analyzers/suites, normalized marketplace/TUI fields.
- **Acceptance:** bundle policy uses worst severity and unknown coverage rather than average; registry
  results do not become company-trusted without policy; users can install no optional analyzers.

### TUI01 — Add first-run source management and health stages

- **Depends on:** MKT01, REG01, SEC03.
- **Red tests:** recommended registry/direct source/no source, enable/disable/default, health/offline/
  incompatible states, organization restrictions, Backspace preservation in text/curses.
- **Implement:** source-management requests and pure wizard transitions/renderers.
- **Acceptance:** no registry is forced; company recommendation/review is clear; no mutation occurs
  before Finalize.

### TUI02 — Migrate consumer marketplace/cart/review/outcomes

- **Depends on:** TUI01, LIFE01.
- **Red tests:** qualified collisions, trust/security rows, filters, Copy/Symlink/scope/harness,
  basket invalidation, version/digest destinations, setup queue, no-op/partial/offline outcomes.
- **Implement:** source-aware User wizard using application requests rather than command stdout.
- **Acceptance:** every selected artifact has description/source/trust/security/install evidence;
  cursor/scroll/basket survive back navigation.

### TUI03 — Migrate Maintainer curation and security workflows

- **Depends on:** TUI02, REG01.
- **Red tests:** local checkout enforcement, scaffold/native promote/foreign import/upstream update,
  conversion warnings, lock/build/audit/security preview, diff, Finalize single apply.
- **Implement:** Maintainer wizard stages and outcome summaries.
- **Acceptance:** no auto commit/push; consumer managed stores remain read-only; exact follow-up
  commands are printed.

### RPT01 — Implement optional registry-owned usage reporting

- **Depends on:** TUI02, CFG01, SEC03.
- **Red tests:** absent destination means no prompt/queue/network; configured prompt/disabled/automatic
  modes; exact preview; redaction; partial results; GitHub Enterprise URL; failure isolation.
- **Implement:** versioned event schema, destination policy, browser-prefill/authenticated provider
  port, registry workflow/template for validation/aggregation/dashboard.
- **Acceptance:** never routes to artifact upstream implicitly; reporting cannot alter install exit
  status; issue input is treated as untrusted; no credentials/paths/logs.

### SEP01 — Extract and prove the public reference-registry boundary

- **Depends on:** TUI03, REG01, IMP01.
- **Red tests:** tool wheel contains no operational catalog; migrated current public artifacts pass
  registry build; CLI works with the registry/direct sources from outside tool checkout; the exact
  exported tree passes secret/credential, private-path, license, generated-file, and provenance
  checks.
- **Implement:** recheck that `M1F1/agent-artifacts-registry` is absent, then create that exact
  repository with `PUBLIC` visibility only after the reviewed export and all preflight gates pass.
  Seed it from a deterministic allowlisted export, enable registry CI before artifact publication,
  and provide a confidential-content-free company-registry bootstrap. Preserve provenance through
  source commit/digest links; transfer Git history only if the complete transferred history passes
  the same public-content audit.
- **Safety boundary:** never publish working-tree-only files, credentials, usage data, local config,
  private source URLs, or company artifacts. If the target already exists unexpectedly, ownership
  is no longer `M1F1`, visibility cannot be proven, or any scan is inconclusive, stop before remote
  creation/push and record evidence instead of selecting another repository automatically.
- **Acceptance:** `https://github.com/M1F1/agent-artifacts-registry` exists as a public repository;
  its first published tree is the reviewed export; tool and registry version independently; and
  registry CI passes minimum/latest compatible AART. The parameter decision is already authorized
  by D-008; no additional owner/name/visibility prompt is required when all preconditions hold.

### MIG01 — Complete legacy catalog/command/config migration and compatibility window

- **Depends on:** SEP01, STATE01.
- **Red tests:** full 0.1.x catalog and installed project/user fixtures, legacy `--source/--repo`,
  dry-run/apply/rollback, mixed old/new state, interrupted migration, actionable deprecations.
- **Implement:** migration orchestration and bounded compatibility adapters; remove package-catalog
  default assumptions only after migrations work.
- **Acceptance:** no silent reinterpretation; backups are deterministic/recoverable; rollback restores
  previous behavior/data.

### DIST01 — Prove local editable/local-wheel and future Nexus readiness

- **Depends on:** MIG01, SEP01.
- **Red tests:** install from editable checkout/local wheel in isolated tool dirs; invoke outside
  checkout; zero runtime Python deps; source sync; Copy/Symlink; delete/recreate environment;
  uninstall/reinstall; Python compatibility matrix.
- **Implement:** hermetic distribution smoke scripts, wheel resource rules, docs, explicit upgrade
  boundary; no Nexus publication.
- **Acceptance:** future index delivery requires no protocol/store/state redesign; wheel contains
  only code/schemas/profiles/importers/templates.

### E2E01 — Run the complete AART 1.0 system matrix and fault injection

- **Depends on:** DIST01, RPT01.
- **Red tests/fixtures:** direct-only; public+company+team; native reference; foreign import; collision;
  trust downgrade; offline; concurrent sync/install; corrupt lock/object; setup partial; security
  provider failure; reporting absent; migration/rollback.
- **Implement:** hermetic end-to-end runners and stable fixtures, with runtime budgets and cleanup.
- **Acceptance:** all workflows run without real home/keychain/credentials; outcomes and recovery
  commands match typed results; `make quality` remains deterministic.

### REL01 — Final release gates, documentation, and stable 1.0.0

- **Depends on:** every prior task.
- **Red checks:** release checklist detects incomplete progress, incompatible reference registry,
  stale schemas/indexes, version mismatch, dirty generated output, missing migration docs.
- **Implement:** final docs/tutorials/changelog, schema freeze, compatibility matrix, release command,
  explicit bump from latest alpha/RC to `1.0.0`.
- **Acceptance:** every `PROGRESS.md` task complete; local and CI gates green; reference registry green;
  no operational catalog in wheel; migration/rollback proven; no Nexus dependency; tag/release only
  after user-visible review and repository protections permit it.

## 10. Definition of done for every task

A task is complete only when:

- [ ] Dependencies are complete on `main`.
- [ ] `PROGRESS.md` names the task/branch and contains no other `in_progress` task.
- [ ] The first failing/characterization test is documented in the PR.
- [ ] Production implementation follows DDD dependency direction and functional-core rules.
- [ ] Positive, negative, error, idempotency, and deterministic cases are covered as applicable.
- [ ] Focused tests and `make quality` pass locally (or documented pre-Q01/docs equivalent).
- [ ] No unrelated file is staged or modified.
- [ ] Documentation/migration/security implications are updated.
- [ ] One intentional commit is pushed on a `codex/` task branch.
- [ ] PR links #27 and contains exact gate evidence.
- [ ] Required CI is green and PR is mergeable.
- [ ] PR is squash-merged to `main` without bypass/force.
- [ ] Remote task branch and explicit temporary worktree are cleaned safely.
- [ ] `origin/main` is verified to contain the merged task.

## 11. Final program exit criteria

The execution goal may finish only after:

1. every task from `P00` through `REL01` is complete and merged;
2. `make quality` passes from a clean `main` worktree;
3. AART version is stable `1.0.0` and all schema/protocol identifiers match the SPEC;
4. direct-source-only use works without registry/reporting/analyzers;
5. optional registry/company/security/reporting paths pass their matrices;
6. 0.1.x catalog/state migration and rollback pass;
7. local wheel/editable reinstall cannot break managed Symlinks;
8. no Nexus/PyPI publication was assumed or required;
9. issue #27 and final documentation summarize delivered behavior and any explicitly deferred work.
