# AART 1.0 Execution Progress

- **Plan:** [PLAN.md](PLAN.md)
- **Issue:** [#27](https://github.com/M1F1/agent-artifacts/issues/27)
- **Target:** `1.0.0`
- **Current code version:** `1.0.0a1`
- **Execution status:** In progress
- **Next task:** `CAS01`
- **Last updated:** 2026-08-07

## Status rules

Allowed task states:

- `pending` — dependencies or execution have not started;
- `in_progress` — the only task currently being implemented;
- `blocked` — cannot proceed safely; blocker is recorded below;
- `complete` — local gates passed and the task's PR is merged to `main`.

At most one task may be `in_progress`. A row may be marked `complete` in its task branch immediately
before the final commit; it becomes authoritative only when that branch is merged to `main`.

The executor updates this file in every task PR with branch, PR, commit/merge, gate evidence, and a
short note. Do not mark work complete from memory or commentary alone.

## Baseline snapshot

| Gate | Planning-time result | Required action |
|---|---|---|
| Unit discovery | Pass | Preserve and split into explicit `unit` gate in Q01 |
| Ruff format check | Pass | Make required in CI through Q01 |
| Mypy | Pass for current package | Add strict ratchet for new contexts |
| Catalog/runtime validation | Pass | Replace monolithic-catalog assumption incrementally |
| Ruff lint | Clean tracked code is expected; current shared worktree contains unrelated untracked work | Use isolated task worktrees and never touch unrelated files |
| Bash E2E | Existing gate | Preserve and expand through vertical slices |
| Coverage | 82.32% branch-aware on Python 3.11 | Enforce non-decreasing `fail_under = 82`; new contexts target 90% |
| Wheel smoke | Existing hermetic unit coverage | Q01 creates explicit non-mutating gate; DIST01 expands it |

## Task ledger

| ID | Task | Depends on | Status | Branch | PR / merge | Gate evidence / notes |
|---|---|---|---|---|---|---|
| P00 | Land planning baseline | — | complete | `codex/aart-1-0-p00-planning-baseline` | [#28](https://github.com/M1F1/agent-artifacts/pull/28) / `d9bd997` | Docs gates and both CI runs passed; squash merge verified on `origin/main` |
| Q01 | Non-mutating quality gates and CI parity | P00 | complete | `codex/aart-1-0-q01-quality-gates` | [#29](https://github.com/M1F1/agent-artifacts/pull/29) / `3c34c16` | Four Python 3.10/3.14 CI jobs passed; squash merge and branch deletion verified |
| V01 | Alpha versioning and release discipline | Q01 | complete | `codex/aart-1-0-v01-alpha-versioning` | [#30](https://github.com/M1F1/agent-artifacts/pull/30) / `550e1d2` | Four Python 3.10/3.14 CI jobs passed after one recorded compatibility fix; squash merge verified |
| D01 | DDD domain kernel and diagnostics | V01 | complete | `codex/aart-1-0-d01-domain-kernel` | [#31](https://github.com/M1F1/agent-artifacts/pull/31) / `140c169` | Four Python 3.10/3.14 CI jobs passed; squash merge and branch deletion verified |
| P01 | Strict JSON/hash/SemVer/capabilities | D01 | complete | `codex/aart-1-0-p01-protocol-primitives` | [#32](https://github.com/M1F1/agent-artifacts/pull/32) / `9790312` | Four Python 3.10/3.14 CI jobs passed; squash merge and branch deletion verified |
| P02 | Canonical artifact/native source protocol | P01 | complete | `codex/aart-1-0-p02-native-protocol` | [#33](https://github.com/M1F1/agent-artifacts/pull/33) / `8b13c6f` | Four Python 3.10/3.14 CI jobs passed; squash merge and branch deletion verified |
| P03 | Registry entry/lock/index schemas | P02 | complete | `codex/aart-1-0-p03-registry-protocol` | [#34](https://github.com/M1F1/agent-artifacts/pull/34) / `b7d5cc5` | Four Python 3.10/3.14 CI jobs passed; squash merge and branch deletion verified |
| C01 | Deterministic compiler pipeline | P03 | complete | `codex/aart-1-0-c01-compiler-pipeline` | [#35](https://github.com/M1F1/agent-artifacts/pull/35) / `15dfe61` | Four Python 3.10/3.14 CI jobs passed after a recorded Ruff drift fix; squash merge verified |
| C02 | Compatibility/effects/collection graph | C01 | complete | `codex/aart-1-0-c02-graph-compiler` | [#36](https://github.com/M1F1/agent-artifacts/pull/36) / `261c5a5` | Four Python 3.10/3.14 CI jobs passed; squash merge and branch deletion verified |
| CFG01 | Platform config and organization policy | P01,D01 | complete | `codex/aart-1-0-cfg01-config-policy` | [#37](https://github.com/M1F1/agent-artifacts/pull/37) / `472340c` | Four Python 3.10/3.14 CI jobs passed; squash merge and branch deletion verified |
| SRC01 | Local/Git acquisition and snapshots | CFG01,C01 | in_progress | `codex/aart-1-0-src01-source-acquisition` | pending | Local quality passes: 1030 unit, 22 integration, E2E, 87.10% overall / 95.42% new-context coverage; Python 3.14 parity passes |
| CAS01 | Immutable content-addressed store | SRC01,P02 | pending | — | — | Safe verify/GC/reference model |
| MKT01 | Federated marketplace and trust | C02,CFG01,CAS01 | pending | — | — | No silent shadowing |
| IMP01 | Importer contract and legacy catalog importer | MKT01 | pending | — | — | Maintainer-only deterministic conversion |
| IMP02 | Native references/promotion/upstream locks | IMP01,P03 | pending | — | — | No payload duplication |
| REG01 | Maintainer registry commands/quality gate | IMP02 | pending | — | — | No automatic Git mutation |
| STATE01 | Manifest v2 and state migration | REG01 | pending | — | — | Backup/dry-run/rollback |
| INS01 | Canonical object install with Copy | STATE01,MKT01,CAS01 | pending | — | — | Immutable reviewed plan |
| INS02 | Durable managed Symlink | INS01 | pending | — | — | Explicit atomic retarget only |
| LIFE01 | Status/update/check/uninstall lifecycle | INS02 | pending | — | — | Recorded subscription only |
| SET01 | Setup trust/digest/policy integration | LIFE01 | pending | — | — | Separate payload/setup outcomes |
| SEC01 | Zero-dependency risk baseline | SET01,P02,P03 | pending | — | — | Evidence, never a “safe” claim |
| SEC02 | Optional out-of-process analyzers | SEC01 | pending | — | — | No auto-install/runtime deps |
| SEC03 | Attestations/bundle aggregation/policy | SEC02,C02,REG01 | pending | — | — | Worst/range/mean/coverage |
| TUI01 | First-run source management/health | MKT01,REG01,SEC03 | pending | — | — | Registry remains optional |
| TUI02 | Consumer marketplace/cart/review | TUI01,LIFE01 | pending | — | — | Source/trust/security visible |
| TUI03 | Maintainer curation/security UX | TUI02,REG01 | pending | — | — | Review/Finalize boundary |
| RPT01 | Optional registry-owned usage reporting | TUI02,CFG01,SEC03 | pending | — | — | Disabled without destination |
| SEP01 | Public reference-registry boundary | TUI03,REG01,IMP01 | pending | — | — | Approved target: public `M1F1/agent-artifacts-registry`; preflight required |
| MIG01 | Complete 0.1.x compatibility migration | SEP01,STATE01 | pending | — | — | No silent reinterpretation |
| DIST01 | Local wheel/editable Nexus readiness | MIG01,SEP01 | pending | — | — | No operational registry in wheel |
| E2E01 | Full system/fault-injection matrix | DIST01,RPT01 | pending | — | — | Hermetic end-to-end proof |
| REL01 | Stable release gates and `1.0.0` | all | pending | — | — | Never start before all prior rows complete |

## Current-task template

Copy and fill this section when a task becomes `in_progress`; clear it only after the PR is merged
or the task is recorded as blocked.

```text
Task: SRC01 — Local/Git source acquisition and immutable snapshots
Branch: codex/aart-1-0-src01-source-acquisition
Worktree: /tmp/aart-src01.umZOQT/worktree
Started: 2026-08-07
Bounded contexts: Pure source candidate/current/health values, sync fallback orchestration, bounded
  local/Git snapshot readers, fixed-argv Git process port, per-source locks, and atomic current store
Red test and expected failure: PASS — seven expected import errors because the managed
  source/acquisition/store APIs did not exist; review regressions then failed for TOCTOU, symlink,
  ownerless-lock, strict-pointer, hard-limit, and mirror-repair invariants before their fixes
Focused tests: PASS — 54 local/Git/process/store/lock/validation/status/E2E tests; new context has
  95.42% branch coverage; full quality has 1030 unit and 22 integration tests; Python 3.14 parity,
  Ruff, mypy over 97 source files, shell E2E, validation, wheel, and docs pass
Files owned: new sources/application/io modules, source tests/docs, TODO.md, PROGRESS.md
Risks/migrations: no CAS/marketplace/CLI/TUI wiring in SRC01; local test transports are explicit;
  candidates are inert bytes and publication remains unreachable before native-source validation
PR: pending after push
CI: pending
Merge: pending
```

## Quality-gate history

| Task | Focused tests | Format | Ruff | Mypy | Unit | Integration | E2E | Validate | Coverage | Packaging | Docs | CI |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| P00 | docs consistency pass | n/a | n/a | n/a | n/a | n/a | n/a | allowlist + issue pass | n/a | n/a | fences/links/diff pass | 2× validate pass |
| Q01 | 8 pass | 138 files pass | pass | 51 files pass | 812 pass | 21 pass | 11-step pass | pass | 82.32% (≥82%) | wheel build/import pass | links/fences/ledger pass | 4× Python 3.10/3.14 pass |
| V01 | 11 pass | 140 files pass | pass | 51 files pass | 823 pass | 21 pass | 11-step pass | version/tag pass | 82.32% (≥82%) | `1.0.0a1` wheel/metadata pass | pass | 4× Python 3.10/3.14 pass |
| D01 | 13 pass | 150 files pass | pass | 60 files pass | 836 pass | 21 pass | 11-step pass | pass | 82.65% overall; 98.14% new kernel | wheel/import pass | pass | 4× Python 3.10/3.14 pass |
| P01 | 16 pass | 162 files pass | pass | 68 files + strict protocol pass | 852 pass | 21 pass | 11-step pass | pass | 83.00% overall; 90.96% protocol | wheel/import pass | pass | 4× Python 3.10/3.14 pass |
| P02 | 26 pass | pass | pass | strict protocol pass | 878 pass | 21 pass | 11-step pass | pass | 83.77% overall; 91.09% new context | `1.0.0a1` wheel/import pass | pass | 4× Python 3.10/3.14 pass |
| P03 | 33 pass | pass | pass | strict protocol pass | 911 pass | 21 pass | 11-step pass | pass | 84.81% overall; 96.72% new context | `1.0.0a1` wheel/import pass | pass | 4× Python 3.10/3.14 pass |
| C01 | 18 pass | pass | pass | strict new contexts pass | 929 pass | 21 pass | 11-step pass | pass | 85.24% overall; 100% new context | `1.0.0a1` wheel/import pass | pass | 4× Python 3.10/3.14 pass |
| C02 | 11 pass | 188 files pass on Ruff 0.12.2 and 0.16.2 | pass | strict compiler/protocol pass | 940 pass | 21 pass | 11-step pass | pass | 85.70% overall; 98.52% graph | `1.0.0a1` wheel/import pass | pass | 4× Python 3.10/3.14 pass |
| CFG01 | 36 pass | 202 files pass on Ruff 0.12.2 and 0.16.2 | pass | 88 source files pass | 976 pass | 21 pass | 11-step pass | pass | 86.52% overall; 98.45% config context | `1.0.0a1` wheel/import pass | pass | 4× Python 3.10/3.14 pass |
| SRC01 | 54 pass | 223 files pass | pass | 97 source files pass | 1030 pass | 22 pass | 11-step pass | pass | 87.10% overall; 95.42% source context | `1.0.0a1` wheel/import pass | pass | pending |

Append one row per completed task. Record commands/versions or link the PR check summary when the
table would otherwise become unreadable. Failed attempts belong in the work log, not hidden.

## Decision log

| ID | Decision | Status | Rationale |
|---|---|---|---|
| D-001 | Registry/default registry is optional | accepted | AART remains federated and direct-source capable |
| D-002 | Canonical JSON protocol | accepted | Python 3.10 stdlib parsing and deterministic hashing |
| D-003 | Foreign conversion is maintainer-time only | accepted | Standard remains normative; consumer installs are reproducible |
| D-004 | Managed Symlink targets immutable CAS objects | accepted | Sync cannot silently change installed content |
| D-005 | Security means evidence/risk, not a “safe” certificate | accepted | Avoid false precision and false assurance |
| D-006 | External analyzers use subprocess JSON protocol | accepted | Optional dependencies stay outside the AART interpreter |
| D-007 | Task branches are squash-merged after green CI | accepted | One bounded change and traceable progress per PR |
| D-008 | Public reference registry remote is `M1F1/agent-artifacts-registry`, visibility `PUBLIC` | accepted | Same admin-owned account as the public tool repo; exact name was absent on 2026-08-07; SEP01 must recheck and pass the public-export audit before creation |
| D-009 | Versions change only through explicit commands; wheels are untracked release outputs | accepted | Ordinary commits and quality gates must be reproducible and non-mutating |
| D-010 | New 1.0 value contracts live in an IO-free `domain` package; legacy conversion lives in `adapters` | accepted | Enforces dependency direction while allowing incremental migration from `model.py` |
| D-011 | Protocol v1 uses immutable strict JSON values, lowercase namespaced extensions, signed-64-bit numeric SemVer identifiers, and framed lexical tree hashing | accepted | Makes parsing and identities bounded, host-independent, reviewable, and fail-closed without runtime dependencies |
| D-012 | Native-source compilation consumes an acquired immutable snapshot, discovers only the root marker and declared roots, and normalizes directory representation | accepted | Keeps local and pinned-Git compilation identical, prevents heuristic consumer crawling, allows unrelated repository content, and rejects links/special files only inside declared source content |
| D-013 | Registry consumers resolve native references only through a matching committed lock; service declarations stay inert and parsed indexes revalidate their graph | accepted | Prevents moving refs, self-authored trust/reporting activation, stale input use, and forged collection memberships from reaching installation |
| D-014 | Compiler Index creates an immutable candidate before Materialize, and pure phases receive no source locator/host path | accepted | Enforces plan-before-write, keeps host-specific acquisition data out of deterministic identity, and makes Publish unreachable until all candidate object/snapshot receipts match |
| D-015 | Marketplace identity is source-alias-qualified; collection expansion and compatibility decisions are pure shared graph results | accepted | Prevents silent cross-source shadowing and keeps browse, bundles, security, and install consumers on one deterministic expansion/reason contract |
| D-016 | Source snapshots are keyed by origin-independent content digest while pointers also bind the resolved local digest or Git commit | accepted | Converges identical local/Git bytes, permits safe concurrent publication, and preserves immutable revision provenance without path-derived identity |

## Blockers

None.

## Work log

### 2026-08-07 — Planning

- Created AART 1.0 PRD/SPEC and umbrella issue #27.
- Reframed registry as optional and sources as federated.
- Added controlled importer and security-assessment-provider direction.
- Created task graph, TDD/DDD/functional rules, quality gates, and delivery protocol.
- Resolved SEP01 owner/name/visibility as public `M1F1/agent-artifacts-registry`; deferred creation
  until the allowlisted export, content audit, and registry CI are ready.
- Did not start an implementation goal, commit, push, PR, merge, version bump, or release.

### 2026-08-07 — P00 started

- Created `codex/aart-1-0-p00-planning-baseline` from the exact current `origin/main` commit.
- Restricted ownership to the P00 documentation allowlist and preserved unrelated worktree files.
- The first docs run exposed an unmatched legacy fence in `docs/design/DESIGN.md`; removed the
  orphan closing fence and reran the complete validation successfully.
- Verified eight allowlisted files, 33 PLAN/PROGRESS tasks, 29 sequential SPEC sections, valid local
  links/fences, a clean diff, and open umbrella issue #27.

### 2026-08-07 — P00 merged; Q01 started

- Pushed commit `f698c4a`, opened ready PR #28, observed both `validate` jobs pass, and squash-merged
  without bypassing protection as `d9bd997`.
- Verified `origin/main` contains the P00 ledger and the remote P00 branch was deleted.
- Created the isolated Q01 worktree from exact merge `d9bd997`; unrelated root-worktree files are
  outside all Q01 tooling and Git status.

### 2026-08-07 — Q01 local gates complete

- Confirmed Red with eight contract failures for missing Make targets/scripts, CI parity, coverage,
  documentation, and non-mutating packaging behavior.
- Added one canonical functional quality runner used by all Make targets and CI; every subprocess
  receives temporary caches/data and the runner compares repository path/content/mode snapshots.
- Extracted catalog/import validation from duplicated Make/CI snippets, added Markdown and
  packaging checks, and preserved `dependencies = []` while adding developer-only tooling.
- Established branch-aware coverage at 82.32% with a non-decreasing 82% fail-under threshold.
- Verified `make quality`: Ruff format/lint, mypy, 812 unit/regression tests, 21 Python integration
  tests, the 11-step shell E2E, validation, coverage, wheel build/import, docs, and no source mutation.
- Verified all 812 tests on Python 3.14 and made one help assertion independent of version-specific
  `argparse` line wrapping; CI supplies the remaining Python 3.10 matrix evidence.

### 2026-08-07 — Q01 merged; V01 started

- Pushed commit `beb0167`, opened ready PR #29, observed all four Python 3.10/3.14 push/PR jobs pass,
  and squash-merged without protection bypass as `3c34c16`.
- Verified `origin/main`, remote branch deletion, and removed only the explicit Q01 temp worktree.
- Created the isolated V01 worktree from exact merge `3c34c16`.

### 2026-08-07 — V01 local gates complete

- Confirmed Red with nine expected failures/errors covering the legacy stable-only bump parser,
  implicit mutation, absent release guard, mutating hook contract, tracked wheel, and metadata policy.
- Introduced canonical `X.Y.Z[a|b|rc]N` version parsing, synchronized explicit set/alpha-bump
  commands, a fail-closed stable/tag gate tied to the complete task ledger, and version `1.0.0a1`.
- Retired the mutating bump entry point, added repository-owned non-mutating hook guidance, and
  changed wheels from committed inputs to ignored local/release outputs.
- Verified 11 focused tests; `make quality` with 823 tests, 21 integration tests, shell E2E,
  82.32% coverage, wheel metadata, docs, and no mutation; all 823 tests also pass on Python 3.14.6.
- The first push/PR CI runs exposed one Python 3.10-only test error: the new wheel-metadata test
  directly invoked the documented Python 3.11+ stdlib builder. Matched the existing packaging-test
  contract by skipping that builder-specific assertion below 3.11; Python 3.10 still runs its
  packaging gate, and Python 3.14 continues to prove the builder filename/metadata assertion.

### 2026-08-07 — V01 merged; D01 started

- Observed all four replacement Python 3.10/3.14 push/PR jobs pass and squash-merged PR #30 as
  `550e1d2`; verified the merged PR, exact `origin/main`, and remote branch deletion.
- Activated shared `core.hooksPath=.githooks`, ran the non-mutating hook successfully on merged
  `main`, and removed only the explicit V01 temporary worktree.
- Created the isolated D01 worktree from exact merge `550e1d2` and kept the unrelated root
  worktree files outside the task scope.

### 2026-08-07 — D01 local gates complete

- Confirmed Red with one failure and nine errors caused by the absent domain and adapter packages.
- Added frozen nominal source/artifact/digest identities, typed diagnostics and source locations,
  an accumulating `Result`, canonical terminal outcomes, immutable collection transforms, and
  runtime-checkable callable port conventions; none of the domain modules import IO/legacy layers.
- Added an explicit adapter that round-trips representative legacy `Ok`/`Err` values (including
  exit codes) and translates legacy artifacts without moving the existing model wholesale.
- Code review found a root-error/partial-cancellation session-classification bug; captured it as a
  failing regression before fixing the pure status fold.
- Verified 13 focused tests and 98.14% branch coverage for the new kernel/adapter; `make quality`
  passes with 836 tests, strict mypy over 60 files, 21 integration tests, shell E2E, 82.65% overall
  coverage, packaging, docs, validation, and no mutation; all 836 tests pass on Python 3.14.6.

### 2026-08-07 — D01 merged; P01 started

- Observed all four Python 3.10/3.14 push/PR jobs pass and squash-merged PR #31 as `140c169`;
  verified the merged PR, exact `origin/main`, remote branch deletion, and clean task worktree.
- Removed only the explicit D01 temporary worktree and created isolated P01 from exact `140c169`.

### 2026-08-07 — P01 local gates complete

- Confirmed Red with one failure and 15 errors because the protocol package and its strict value,
  validation, version, capability, and hashing contracts did not exist.
- Added frozen UTF-8 JSON/object values with duplicate-key, float, integer, Unicode, depth, and
  string bounds; schema helpers accumulate stable field diagnostics and permit only explicit
  lowercase namespaced extensions.
- Added NFC POSIX relative paths, SemVer 2.0 precedence and half-open bounds, deterministic
  required/optional capability negotiation, canonical SHA-256 values, and framed lexical tree
  hashing with executable-bit and directory identity plus a golden digest fixture.
- Boundary review captured fail-closed regressions for 5,000-digit JSON/SemVer numbers, oversized
  tree sizes, invalid entry kinds, and required/optional capability overlap before fixing them.
- Verified 16 focused tests and 90.96% branch coverage for the protocol context; `make quality`
  passes with 852 tests, strict mypy over 68 files, 21 integration tests, shell E2E, 83.00% overall
  coverage, packaging, docs, validation, and no mutation; all 852 tests pass on Python 3.14.6.

### 2026-08-07 — P01 merged; P02 started

- Observed all four Python 3.10/3.14 push/PR jobs pass and squash-merged PR #32 as `9790312`;
  verified the merged PR, exact `origin/main`, remote branch deletion, and clean task worktree.
- Removed only the explicit P01 temporary worktree and created isolated P02 from exact `9790312`.

### 2026-08-07 — P02 local gates complete

- Confirmed Red with 16 import errors because canonical native-source schemas, package loading,
  provenance/collections, and the legacy artifact adapter did not exist.
- Added strict immutable `aart-source.json`, `artifact.json`, provenance, and collection documents
  for skill, guideline, MCP, hook, and memory artifacts, including SemVer/capability handshakes,
  type-specific payload formats/effects, setup references, and canonical hash projections.
- Added a pure acquired-snapshot loader: local and immutable Git origins compile identically,
  discovery uses only the root marker and declared roots, directory representation is normalized,
  and symlinks/special files are rejected inside declared content without rejecting unrelated files.
- Added a deterministic legacy-artifact adapter plus an executable, documented native-source v1
  fixture; boundary review tightened URL credentials, collection versions, immutable constants,
  effects, malformed metadata, tree entries, and setup reference behavior.
- Verified 26 focused tests and 91.09% branch coverage for the new context; `make quality` passes
  with 878 tests, strict protocol mypy, 21 integration tests, shell E2E, 83.77% overall coverage,
  validation, `1.0.0a1` wheel/import, docs, and no mutation; all 878 tests pass on Python 3.14.6.

### 2026-08-07 — P02 merged; P03 started

- Observed all four Python 3.10/3.14 push/PR jobs pass and squash-merged PR #33 as `8b13c6f`;
  verified the merged PR, exact `origin/main`, remote branch deletion, and clean task worktree.
- Removed only the explicit P02 temporary worktree and created isolated P03 from exact `8b13c6f`.

### 2026-08-07 — P03 local gates complete

- Confirmed Red with three import errors covering 33 planned registry schema, lock, tree, graph,
  deterministic index, security-boundary, and executable-fixture tests.
- Added frozen strict documents for `aart-registry.json`, native Git entries, committed lock records,
  and payload-free indexes, with canonical projections, namespaced extension preservation, service
  advertisements, review/provenance summaries, pinned commits, and all required digests.
- Added host-independent registry-input hashing that canonicalizes JSON, binds payload/review input,
  excludes generated lock/index and unrelated files, rejects declared links/specials, and produces
  identical results for local and immutable-Git snapshots.
- Added consumer resolution that returns only approved committed-lock coordinates after input,
  URL/ref/path/review, identity, and self-reference checks; a moving requested ref is never used as
  the resolved source.
- Added deterministic index generation plus parser-side graph revalidation for duplicates,
  ambiguity, version bounds, dangling references, cycles, and derived nested membership; documented
  and executed a registry fixture containing both an owned package and an external native reference.
- Boundary review preserved Git path case during origin comparison, tightened ref validation, kept
  service advertisements inert, rejected trust/payload bytes, and prevented extension loss.
- Verified 33 focused tests and 96.72% branch coverage for the new context; `make quality` passes
  with 911 tests, strict protocol mypy, 21 integration tests, shell E2E, 84.81% overall coverage,
  validation, `1.0.0a1` wheel/import, docs, and no mutation; all 911 tests pass on Python 3.14.6.

### 2026-08-07 — P03 merged; C01 started

- Observed all four Python 3.10/3.14 push/PR jobs pass and squash-merged PR #34 as `b7d5cc5`;
  exact-head protection rejected one incorrect full SHA before the verified head was merged.
- Verified `origin/main`, remote branch deletion, removed only the explicit P03 worktree, and created
  isolated C01 from exact `b7d5cc5`.

### 2026-08-07 — C01 local gates complete

- Confirmed Red with three import/file errors because the compiler domain, application service,
  typed phase results, effect ports, and architecture boundary did not exist.
- Added frozen source/acquisition/context, phase output/report, resolved compilation, object plan,
  immutable candidate, publication request/receipt, and complete run values with digest-bound bytes,
  canonical ordering, and deterministic diagnostics.
- Added generic pure Parse/Handshake/Resolve/Normalize/Validate/Index steps plus injected Acquire,
  Materialize, and Publish callable ports; no durable IO imports or adapters were introduced.
- Consumer requests require locked revisions/snapshot digests and a frozen Resolve result. Acquire
  and Materialize accumulate independent failures, while every failed phase deterministically skips
  all later phases and makes publication unreachable.
- Boundary review removed locators/host paths from the pure compiler context, retained warnings when
  a phase also errors, validated every port receipt, and refined the SPEC so Index creates the
  complete candidate before any object write.
- Verified deterministic replay across source order and different host locators, all phase failure
  cuts, partial immutable-object failures, invalid candidates, mismatched receipts, and programmer
  invariants with 18 focused tests and 100% branch coverage.
- `make quality` passes with 929 tests, strict mypy, 21 integration tests, shell E2E, 85.24% overall
  coverage, validation, `1.0.0a1` wheel/import, docs, and no mutation; all 929 tests pass on Python
  3.14.6.

### 2026-08-07 — C01 CI formatter drift fixed

- Diagnosed all four PR #35 failures as the same format-only difference between local Ruff 0.12.2
  and the CI-resolved Ruff 0.16.2; no compiler behavior or test result had failed.
- Applied the current canonical formatting and re-ran the complete local quality and Python 3.14
  gates before updating the PR.

### 2026-08-07 — C01 merged; C02 started

- Observed all four replacement Python 3.10/3.14 jobs pass and squash-merged PR #35 as `15dfe61`;
  verified the merged PR, exact `origin/main`, remote branch deletion, and clean task worktree.
- Removed only the explicit C01 temporary worktree and created isolated C02 from exact `15dfe61`.
- Scoped C02 to an IO-free qualified marketplace graph, compatibility/effect decisions, reusable
  collection expansion, explicit-vs-broad selection behavior, and previous-snapshot lifecycle rules.

### 2026-08-07 — C02 Red/Green and boundary review

- Confirmed Red with two expected import errors because no marketplace graph API existed.
- Added qualified source/artifact/collection values, canonical payload-free graph bytes, a typed C01
  phase output bridge, deterministic nested expansion, and accumulated compatibility/setup reasons.
- Added broad-versus-explicit selection semantics: broad requests retain per-item skip reasons;
  explicit missing, removed, version-mismatched, or incompatible requests fail without filtering.
- Added previous-snapshot comparison for removal tombstones, version regression, same-precedence
  digest changes, and reviewable version-without-projected-content warnings.
- Boundary review made same-version checks bind full manifest/payload/object digests (including
  setup/README bytes), rejected mismatched/duplicate source graph values, and stopped conflicting
  requested versions from being silently deduplicated.
- Verified 11 focused tests and 98.52% branch coverage for the graph context. `make quality` passes
  with 940 tests, strict mypy over 81 files, 21 integration tests, shell E2E, 85.70% overall
  coverage, validation, `1.0.0a1` wheel/import, docs, and no tracked mutation; all 940 tests pass on
  Python 3.14.6 and Ruff 0.16.2 also accepts the complete format/lint surface.

### 2026-08-07 — C02 merged; CFG01 started

- Observed all four Python 3.10/3.14 jobs pass and squash-merged PR #36 as `261c5a5`; verified the
  merged PR, exact `origin/main`, remote branch deletion, and clean task worktree.
- Removed only the explicit C02 temporary worktree and created isolated CFG01 from exact `261c5a5`.
- Scoped CFG01 so platform paths are injected/pure, policy is evaluated before write/network ports,
  zero-source local operation is valid, and corrupt recovery never exposes or discards input bytes.

### 2026-08-07 — CFG01 Red/Green/Refactor

- Confirmed Red with five expected import errors for the absent configuration domain, application
  ports, and filesystem adapter.
- Added pure macOS/Linux/XDG path resolution, strict canonical config/policy schema v1, immutable
  precedence and policy decisions, first-run/no-source/recovery application requests, and a private
  atomic `fsync`/replace filesystem adapter.
- Expanded malformed/type/security/precondition coverage to 36 focused tests; the six new runtime
  modules reach 98.45% combined branch coverage, with model/application at 100%. Tests use only
  injected fake paths and `TemporaryDirectory` roots.
- Passed the canonical local quality matrix with 976 unit-discovery tests, 21 integration tests,
  shell E2E, strict mypy over 88 source files, 86.52% global branch coverage, validation,
  `1.0.0a1` wheel/import checks, documentation checks, and no tracked mutation.

### 2026-08-07 — CFG01 merged; SRC01 started

- Observed all four Python 3.10/3.14 jobs pass and squash-merged PR #37 as `472340c`; verified the
  exact PR head, merged state, `origin/main`, remote branch deletion, and clean CFG01 worktree.
- Removed only the explicit CFG01 temporary worktree and created isolated SRC01 from exact
  `472340c`; unrelated files in the root worktree remain untouched.
- Scoped SRC01 around inert bounded snapshots, system-Git fixed argv, per-source serialization,
  validation-before-publication, atomic current pointers, and explicit last-known-good outcomes.

### 2026-08-07 — SRC01 Red/Green and security review

- Confirmed initial Red with seven expected import errors for the absent source model, local/Git
  acquisition, application sync, process, atomic store, and lock APIs.
- Added origin-derived source instances, hard-bounded inert snapshots, native compatibility
  validation, health/status projection, explicit offline/fetch last-known-good outcomes, and strict
  canonical current pointers that bind local revisions or immutable Git commits.
- Added fixed-argv `shell=False` system Git with sanitized environment/redacted diagnostics, bare
  mirror init/repair/fetch, branch/tag-to-commit resolution, safe tree/archive comparison, and a
  real system-Git integration test without Python runtime dependencies.
- Added private staged snapshot publication, byte/digest verification before atomic `current.json`
  replacement, convergent concurrent writers, per-source owner leases with interrupted/stale
  recovery, and an end-to-end local sync through all production ports.
- Repository code review captured Red regressions before fixes for file-to-symlink TOCTOU,
  symlinked managed snapshot/mirror paths, ownerless locks, partial mirror remote configuration,
  unbounded caller limits, cross-instance publication, and malformed durable identities.
- Verified 54 focused tests and 95.42% branch coverage for the complete new context. The canonical
  non-mutating quality matrix passes with 1030 unit tests, 22 integration tests, shell E2E, strict
  mypy over 97 source files, Ruff, 87.10% global coverage, validation, `1.0.0a1` wheel/import, and
  documentation; all 1030 tests also pass on Python 3.14.6.
