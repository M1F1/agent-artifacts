# AART 1.0 Execution Progress

- **Plan:** [PLAN.md](PLAN.md)
- **Issue:** [#27](https://github.com/M1F1/agent-artifacts/issues/27)
- **Target:** `1.0.0`
- **Current code version:** `0.1.48`
- **Execution status:** In progress
- **Next task:** `V01` after Q01 merges
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
| Q01 | Non-mutating quality gates and CI parity | P00 | complete | `codex/aart-1-0-q01-quality-gates` | pending merge | `make quality` passes; 812 unit, 21 integration, shell E2E, 82.32% coverage; Python 3.14 unit pass |
| V01 | Alpha versioning and release discipline | Q01 | pending | — | — | First implementation version `1.0.0a1` |
| D01 | DDD domain kernel and diagnostics | V01 | pending | — | — | Functional core foundation |
| P01 | Strict JSON/hash/SemVer/capabilities | D01 | pending | — | — | Protocol primitives |
| P02 | Canonical artifact/native source protocol | P01 | pending | — | — | `aart-source.json`, `artifact.json` |
| P03 | Registry entry/lock/index schemas | P02 | pending | — | — | Deterministic frozen registry inputs |
| C01 | Deterministic compiler pipeline | P03 | pending | — | — | Pure phases and diagnostics |
| C02 | Compatibility/effects/collection graph | C01 | pending | — | — | Deterministic expansion |
| CFG01 | Platform config and organization policy | P01,D01 | pending | — | — | Zero sources/default optional |
| SRC01 | Local/Git acquisition and snapshots | CFG01,C01 | pending | — | — | Atomic last-known-good |
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
Task: Q01 — Establish non-mutating quality gates and CI parity
Branch: codex/aart-1-0-q01-quality-gates
Worktree: /tmp/aart-q01.fJUZB2/worktree
Started: 2026-08-07
Bounded contexts: Developer tooling, verification, packaging, CI
Red test and expected failure: 8 expected failures proved missing canonical targets/scripts, a
  duplicated Python-3.11-only CI workflow, absent coverage tooling, and no hermetic packaging check
Focused tests: PASS — 8 Q01 contract tests on Python 3.11 and 3.14; 812-test Python 3.14 regression
Files owned: Makefile, pyproject.toml, .github/workflows/validate.yml, quality scripts/tests/docs,
  PROGRESS.md
Risks/migrations: developer-only coverage dependency; runtime dependencies must remain empty;
  quality and packaging checks must not mutate the source tree
PR: pending after push
CI: pending; matrix configured for Python 3.10 and 3.14
Merge: pending
```

## Quality-gate history

| Task | Focused tests | Format | Ruff | Mypy | Unit | Integration | E2E | Validate | Coverage | Packaging | Docs | CI |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| P00 | docs consistency pass | n/a | n/a | n/a | n/a | n/a | n/a | allowlist + issue pass | n/a | n/a | fences/links/diff pass | 2× validate pass |
| Q01 | 8 pass | 138 files pass | pass | 51 files pass | 812 pass | 21 pass | 11-step pass | pass | 82.32% (≥82%) | wheel build/import pass | links/fences/ledger pass | pending |

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
