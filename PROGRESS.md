# AART 1.0 Execution Progress

- **Plan:** [PLAN.md](PLAN.md)
- **1.0 issue (historical):** [#27](https://github.com/M1F1/agent-artifacts/issues/27)
- **Post-1.0 issue:** [#61](https://github.com/M1F1/agent-artifacts/issues/61)
- **Target:** `1.0.0`
- **Current code version:** `2.6.0`
- **Execution status:** `2.6.0` gives the persisted setup receipt a reader — `marketplace receipt
  show`, `verify`, `undo` — over state `2.2.0` already wrote, and stops two rendering paths printing
  counts over payloads that held the answer. Still the released `2.0.0` contract, and the first
  release in three with **no registry obligation in either direction**: nothing here publishes into an
  index. The v14 freeze carries protocol versions identical to v13 and differs in one input,
  `agent_artifacts/setup.py`, where the difference is a single rename. **Released** as tag `v2.6.0`
  and a GitHub release carrying the wheel, after a second live acceptance pass and the token
  containment work (`RR-10`) that pass made necessary
- **Next task:** the overnight residue run continues with `LAF-69` and `LAF-73`; `LAF-75` closed on
  `fix/wheel-digest-emits-what-it-hashes-laf75`. The human-gated passes — the curses front-end and
  the MCP credential run — and `LAF-61` still wait for the maintainer
- **Last updated:** 2026-08-16

## Readable receipt (`2.6.0`, released)

- **Design:** [docs/design/DESIGN-readable-receipt.md](docs/design/DESIGN-readable-receipt.md)
- **Plan:** [docs/plan/PLAN-readable-receipt.md](docs/plan/PLAN-readable-receipt.md)
- **Stream:** [docs/testing/residue-stream-2026-08-15.md](docs/testing/residue-stream-2026-08-15.md)
- **Register:** [docs/testing/residue-register.md](docs/testing/residue-register.md)
- **Branch:** `feat/receipt-as-residue`, merged as [#90](https://github.com/M1F1/agent-artifacts/pull/90); tagged `v2.6.0`
- **Root cause:** AART writes a complete account of every setup run and offers no way to look at it.
  Every part of an undo exists, is tested, and runs — exactly once, on the failure path inside a run.
  `cli.py` contained no occurrence of `receipt` and none of `rollback`.
- **Released `2026-08-15`.** Tag `v2.6.0`, wheel digest
  `sha256:ccdbff2a6f111d4d8dc478c2a4415785628cfb41e4ee7d6b0b41702f2ef6ba91`. The full fail-closed
  `release.py check` passed against a clean `origin/main` registry clone. **Published as a GitHub
  release** with the wheel attached; not on any package index. The published asset was downloaded and
  its digest checked against `wheel-digest` — which is how `LAF-75` was caught, one `curl` before it
  would have shipped a digest line that did not describe its own attachment.
- **Registry step: a pin move, and nothing else.** `2.6.0` adds no index field, capability or module,
  so a registry built on `2.5.0` validates on `2.6.0` and the reverse. Registry B's PR is green
  against the real tag; the consumer repository's is green against the published wheel, reconciling
  eleven installations. **Both merged**, along with Registry A's own pin, on the maintainer's
  instruction; every repository in the constellation now gates at `2.6.0`.
- **Method note:** nearly every design premise this stream checked against the code proved partly
  false, and each refutation is recorded where it was found rather than edited away. Three of the six
  findings the design set out to close turned out not to be the absence it named; `LAF-58`'s premise —
  that the receipt records the tag's prior image id — is false; `DESIGN §5`'s claim that `LAF-47` and
  `RS-10` become visible to `verify` is false. A design edited until it agrees with the code stops
  being evidence of what was believed when it was written.

| ID | Work package | Status | Evidence / next action |
|---|---|---|---|
| RR-1 | The persisted record can be read from outside a run | done | Lookup by coordinate, profile and scope with no lock; three distinct refusals, each with remediation. The middle one says *no setup run has been recorded* and not *it declares no setup* — measuring it live refuted the first draft |
| RR-2 | `marketplace receipt show` | done | Structural parity test: every value the `--json` payload carries appears in the text, so a field added to the receipt and forgotten in the renderer fails without anyone remembering to extend the test |
| RR-2A | The text renderer stops summarising what `--json` carries | done | Counts may accompany content, never replace it; empty cases say they checked. Found `LAF-63` while writing the tests, recorded rather than fixed mid-package |
| RR-2B | A transcript keeps the end that explains it | done | One helper at all three capture sites; redaction still precedes truncation and the helper cannot reorder them |
| RR-3 | `marketplace receipt verify` | done | Pure planning, imperative probes at the edge, three statuses. `LAF-55` closed; `LAF-61` made visible and left alone, proved by hashing `.zshrc` before and after |
| RR-4 | `marketplace receipt undo` | done | Review-first proved by hashing both `.zshrc` and the record file across a run without `--yes`. `plan_undo` is held to `_rollback_receipt` by a test that runs the real rollback against a fake runtime, module by module |
| RR-5 | The same three actions in both front-ends | done | One seam, `tui.receipt_outcome`; an AST guard fails if either skin names a receipt renderer or the rollback outside it. Found `LAF-64` |
| RR-6 | The documents become a test gate | done | Command reference with the renderer's real output, and `compatibility-v14`. Six findings move out of shipped-open and **five** close — the plan said six; `LAF-61` is `visible`, and the document says so rather than rounding up |
| RR-7 | The open-residue register, derived rather than maintained | done | Thirty rows, four `docs-check` rules each with a test that makes it fail. Released documents are outside it on purpose: a dated record does not have to agree with the present |
| RR-8 | The `2.6.0` release commit | done | Version `2.6.0`, contract v14: [compatibility](docs/release/compatibility-v14.md), [checklist](docs/release/release-checklist-v14.md), [notes](docs/release/github-release-v2.6.0.md). The freeze claim is verified rather than asserted — identical `protocol_versions`, one differing input |
| RR-9 | Live acceptance: two registries and the consumer repository | done | Walked with no patched executable. Nine of nine scenarios attempted; three failed or were unreachable and became `LAF-65`..`LAF-69`. The run is what turned a finished release into a second pass |
| RR-10 | Token containment: the three release blockers | done | [design](docs/design/DESIGN-token-containment.md), [plan](docs/plan/PLAN-token-containment.md). One redactor at the exits (`LAF-63`, `LAF-72`), the orphan probe reads where runs are (`LAF-66`), the rollback field names a command that exists (`LAF-65`). Re-walked live; scenario 6 passes both halves |
| RR-2C | Credential redaction misses namespaced names | done | Superseded by `RR-10A`. The estimate was one pattern; measuring first found **two** redactors with the weaker one on the write-to-disk path, which is the defect that mattered (`LAF-72`) |
| RR-4A | The capture site records what a tag pointed at | todo | Read `{{.Id}}` at the pre-build inspect and record `previous_image_id`; the undo then restores a `preexisting` tag's binding |

## Setup build context (`2.5.0`, released)

- **Design:** [docs/design/DESIGN-setup-build-context.md](docs/design/DESIGN-setup-build-context.md)
- **Plan:** [docs/plan/PLAN-setup-build-context.md](docs/plan/PLAN-setup-build-context.md)
- **Branch:** `feat/setup-build-context`
- **Acceptance case:** one real artifact, `mcp/company-atlassian` — two vendored files, an authored
  `Dockerfile`, a corporate CA that exists only on the consumer's machine, and an image built
  locally and never published. Verified against `2.4.0`: the package is expressible **except** for
  the two steps this work adds, and its maintainer's workaround is a shell script run by hand from a
  clone of the registry.
- **Root cause:** a recipe can name where to write and cannot name what to read. The package sits in
  neither of the setup model's two address spaces, and even the custom entrypoint is executed from a
  temporary copy with no path to the package in its environment.

| ID | Work package | Status | Evidence / next action |
|---|---|---|---|
| SBC-1 | A recipe can name the package, and AART hands it a copy | done | Package-relative source paths plus build-context materialization into the per-run directory; the object store stays read-only, held by a digest test rather than by review |
| SBC-2 | `docker.build@1` | done | Tag derived as `aart/<type>/<name>:<version>`; receipt records context digest, tag, local image id; rollback removes only a tag this run created |
| SBC-3 | `trust-store.export-certificates@1` and the `trust-store` capability | done | Reads public certificates only, writes into the materialized context only, refused without one; a distinct capability so the review does not inflate it to credential-store access |
| SBC-4 | A Dockerfile is assessed | done | `_text_like` currently skips a file named `Dockerfile` entirely — AART would execute bytes the baseline never read |
| SBC-5 | The review says what a build does | done | Neither module may fall through to the generic effect line; the manual alternative still renders before consent |
| SBC-6 | The worked artifact, and the documentation that makes it copyable | done | Module reference, worked section, the three limits from design §9, and a test that every module in `_MODULES` is documented |
| SBC-7 | Live acceptance: both routes, on a real machine | done | Both routes walked and diffed on a real daemon and a real keychain: [`PROGRESS-live-acceptance-setup-build.md`](docs/testing/PROGRESS-live-acceptance-setup-build.md). Ten findings (`LAF-51`..`LAF-60`) in five clusters; `LAF-51` makes the guided route unreachable as shipped and had to be worked around to observe anything else. Contents agree between routes; image identity does not |
| SBC-9 | The guided route actually runs | done | One table decides what a recipe needs; the index publishes it and the consumer recomputes it, so the gate compares like with like. `LAF-51` closed and the acceptance scenarios re-walked unpatched; `LAF-56` and `LAF-60` fixed in the reference |
| SBC-8 | The `2.5.0` release commit | done | Version `2.5.0`, contract v13: [compatibility](docs/release/compatibility-v13.md), [checklist](docs/release/release-checklist-v13.md), [notes](docs/release/github-release-v2.5.0.md), and a freeze that differs from v12 in one input and no protocol version. The matrix carries the two upgrade obligations — rebuild the index, do not publish a new-module artifact ahead of consumer upgrades — and the eight findings shipping open. Published as [v2.5.0](https://github.com/M1F1/agent-artifacts/releases/tag/v2.5.0) from `b0b0253`, wheel `sha256:a9a04ad4…`, reproducible across two builds |
| SBC-10 | The reference registry moves with the release | done | `release-check` failed three registry gates on the tag: a not-yet-rebuilt index disagrees with what `2.5.0` recomputes. Rebuilt on `2.5.0` and the CI pin moved with it ([registry#7](https://github.com/M1F1/agent-artifacts-registry/pull/7)); measured in both directions — the rebuilt index fails the same gate under `2.4.0` and `2.0.0`. The upgrade note now says which side a registry is on ([#87](https://github.com/M1F1/agent-artifacts/pull/87)). **The claim recorded here that consumers are untouched either way is false and was corrected on 2026-08-15**: a `2.0.0` or `2.4.0` consumer cannot add the rebuilt registry (`LAF-62`) |

## Live acceptance run

Live (non-hermetic) acceptance testing against real GitHub registries and a real consumer repo is
tracked in its own ledger so it does not mix with this release record:
[docs/testing/PROGRESS-live-acceptance.md](docs/testing/PROGRESS-live-acceptance.md)
(design · plan · scenario map alongside it in `docs/testing/`). The second run, against released
`2.1.0`, is [docs/testing/PROGRESS-live-acceptance-v2.md](docs/testing/PROGRESS-live-acceptance-v2.md);
its composed response is
[DESIGN-subscription-identity-binding.md](docs/design/DESIGN-subscription-identity-binding.md) and
[PLAN-subscription-identity-binding.md](docs/plan/PLAN-subscription-identity-binding.md).

The third run, against released `2.3.0` and its vendoring surface, is
[docs/testing/PROGRESS-live-acceptance-v3.md](docs/testing/PROGRESS-live-acceptance-v3.md). Its
composed response is
[DESIGN-vendored-copy-integrity.md](docs/design/DESIGN-vendored-copy-integrity.md) and
[PLAN-vendored-copy-integrity.md](docs/plan/PLAN-vendored-copy-integrity.md), released as `2.4.0`:
`LAF-41` (the shipped payload was verified against nothing), `LAF-42` (`up-to-date` was read from
the record, not the bytes, and printed two commits it did not reconcile), and `LAF-46` (a vendored
`mcp` payload never reaches the consumer, undocumented and taught wrongly). Residues left open there
are listed at the end of the plan and in
[docs/release/release-checklist-v12.md](docs/release/release-checklist-v12.md).

## Post-v1.0.0 catalog-boundary follow-up

- **Plan:** [docs/plan/PLAN-post-v1-catalog-boundary.md](docs/plan/PLAN-post-v1-catalog-boundary.md)
- **Issue:** [#61](https://github.com/M1F1/agent-artifacts/issues/61)
- **Branches:** all original executable follow-ups and AART PRs #69 and #71 are merged; REG02 and
  REG03 are merged separately to `M1F1/agent-artifacts-registry`.
- **Status:** the original program is complete. AART `v1.1.1` supplies the missing per-artifact
  compatibility boundary, registry PR #1 publishes the rewritten skills and generated registry
  evidence. Upstream Residuality PR #1, AART PR #69, and registry PR #2 are merged. The `1.2.0`
  release added one-coordinate collection lifecycle selection and advisory runtime health. The
  `1.3.0` release makes prompt reporting the new-client default and partitions reports by source
  registry without changing any registry or artifact compatibility floor.
- **Last updated:** 2026-08-11
- **Next checkpoint:** publish AART `v1.3.0`, update registry quality CI to the released executable,
  then merge registry analytics PR #3 while keeping analytics generation pinned to `v1.2.0`.

| ID | Task | Status | Evidence / next action |
|---|---|---|---|
| CB01 | Remove embedded catalog, implicit checkout fallback, and finish source onboarding/read-only browse | complete | CB01.A removes production payload roots/exporter and rejects legacy/canonical embedded catalog paths, including dangling root symlinks. CB01.B adds strict source parsing/sync plus first-run TUI and agent `source add/list`; configuration now rejects a same-origin/different-ref Git pair across equivalent HTTPS/SSH/SCP spellings until SRC02, resolves safe `refs/heads/*` branch inputs, and an empty required-policy curses Sources screen supports Add/Back/Quit. CB01.C adds `marketplace list --json` with digest verification and no object publication. Final `make quality` passes. Locally committed/pushed as `9bdb24d`; tracked by issue #61, in review as PR #62 with green CI on Python 3.10 and 3.14. |
| LIFE02 | Canonical non-interactive lifecycle (`marketplace install/update/uninstall/status/setup`) | complete | JSON-first lifecycle over the existing canonical application services. Coordinates are `<source>/<kind>/<name>[@<version>]`; an unqualified `<kind>/<name>` resolves only when unique, otherwise a deterministic ambiguity diagnostic names every valid coordinate. Without `--yes` every action stops after Review and changes nothing; `--yes` finalizes the digest of the review computed in the same process. Setup authorizations are never implied (`--authorize-untrusted-source`, `--authorize-custom-entrypoint`, `--approve-setup-effects`). Legacy `--source`/`--repo` are rejected on these subcommands. Real temporary-home/project E2E covers Copy, managed Symlink into the object store, user scope, update no-op, status, uninstall, offline, and JSON diagnostics. Full `make quality` passes. Setup *execution* E2E is deliberately not added — see the residual note below. |
| SRC02 | Ref-aware source-store migration plus sync/health/doctor commands | complete | Source identity is now `(kind, location, ref)`, so two refs of one Git origin own separate mirrors, snapshots, and pointers instead of sharing one. The uniqueness invariant moved from origin to (origin, ref) in all four places that enforced it: configuration model, schema parser, addition planner, and `SourceAdditionRequest`. `<data_root>/sources/store.json` records layout v2 and is written only after every rebind succeeds. Migration planning is pure and refuses to guess: a legacy+ref-aware pair is a conflict, and one legacy directory claimable by two configured refs is an explicit ambiguity naming both aliases. Applying uses atomic renames, never renames onto an existing directory, is idempotent, and resumes from a partially applied state. Adds `aart source sync`, `health`, and `doctor [--apply]`, none of which may change source identity, configuration, or policy. Design: `docs/design/DESIGN-src02-ref-aware-sources.md`. Full `make quality` passes. |
| CFG02 | Atomic source-management configuration writes | complete | Adds a configuration-scoped lock plus an expected-digest compare-and-swap writer (`agent_artifacts/io/config_cas.py`). `LoadedConfiguration` now carries `observed_digest`, and both reviewed source-management finalizers — CLI `source add` and the TUI source selection/addition — name that exact state; the compare runs under the lock immediately before the atomic replace, closing the window a pre-write re-read alone cannot. A losing writer gets a deterministic `config-write-conflict` retry diagnostic and never overwrites. The writer is an injected port (`ConfigurationPorts.write_checked`), so the application layer states the contract and io implements it. A crashed lock holder is reclaimed only when both old and provably gone; a live holder is never stolen from. Tests cover the isolated writer (11), the wired CLI path including a writer injected mid-sync (4), lock release on both success and refusal, and idempotent retry. Full `make quality` passes. |
| REG02 | Registry-owned agent skills | complete | AART PR [#67](https://github.com/M1F1/agent-artifacts/pull/67) released `v1.1.1` with optional, manual per-artifact `requires_aart`; missing bounds remain unrestricted, incompatible artifacts remain visible, and installation is blocked with a reason. Registry PR [#1](https://github.com/M1F1/agent-artifacts-registry/pull/1) rewrites `agent-artifacts` and `author-aart-installer` as registry-owned `2.0.0` skills, removes their stale legacy provenance, adds the requested `>=1.1.0` artifact bounds to all three skills, regenerates lock/index, and pins CI to released AART `v1.1.1` with format/validate/lock/build/audit/minimum/latest gates. Both PR and post-merge CI passed. No executable version was raised for this documentation update. |
| REG03 | Residuality framework collection in the main registry | complete | Upstream PR [M1F1/residues-architecture-framework#1](https://github.com/M1F1/residues-architecture-framework/pull/1), AART PR [#69](https://github.com/M1F1/agent-artifacts/pull/69), and registry PR [M1F1/agent-artifacts-registry#2](https://github.com/M1F1/agent-artifacts-registry/pull/2) are merged. The registry contains fourteen MIT `1.0.0` artifacts, exact provenance, generated lock/index, the collection, Python `>=3.11.0` advisory metadata on thirteen skills, and green Copy/Symlink tests. No Residuality artifact gained incidental `requires_aart`, so the registry remains installable by `v1.1.1`; those users can install visible members individually. |
| REL02 | Next executable release contract | complete | Version `1.1.0`, not the originally guessed `1.0.1`: LIFE02 and SRC02 add eleven public CLI commands, which is a SemVer MINOR change. Adds a versioned release contract (`RELEASE_CONTRACT_VERSION = 2`) with `schema-freeze-v2.json`, `release-checklist-v2.md`, `compatibility-v2.md`, and `github-release-v1.1.0.md`. REL01's `1.0.0` evidence is untouched and never regenerated; the v2 freeze differs from v1 in exactly one input, `agent_artifacts/configuration/schema.py`, from SRC02's relaxed origin-and-ref rule. `compatibility-v2.md` records the one-directional configuration compatibility: every `1.0.0` config still loads, but a `1.1.0` multi-ref config is rejected by `1.0.0`, which is why REG02 must raise `requires_aart` to `>=1.1.0`. |

### 2026-08-11 — CB01 work log

- Reframed the tool repository as executable-only; operational content is retained in canonical
  registries and legacy compatibility fixtures/importers remain tested.
- Removed the first-run `bundled-legacy` source fallback so neither CLI nor TUI treats its own
  checkout as a marketplace.
- Added agent-facing source bootstrap and safe discovery contracts without silently rerouting
  legacy lifecycle commands.
- Added a source-management-only policy path: individual required sources may be synchronized and
  persisted one at a time, while all content operations still fail closed until every required
  alias is enabled. Host/direct/reporting/default constraints remain enforced.
- Added native and registry read-only browse tests proving catalog discovery does not materialize
  CAS objects while registry-owned package digests remain verified.
- Reconciled the released history: PR #60 merged as `92aa3ea`, and immutable `v1.0.0` resolves to
  that commit. The original 1.0 plan/ledger now records this as historical evidence rather than an
  active release action.
- Hardened the code-only boundary after review: it rejects the six legacy roots, canonical
  source/registry roots and markers, and dangling root symlinks. The version tool now keeps the
  runtime protocol contract synchronized with package and project version values.
- Corrected the post-release README and historical Symlink design so humans are directed to the
  TUI, agents to JSON source/discovery commands, and legacy lifecycle examples retain explicit
  source context.
- Added final P1 regressions from review: configuration parsing/model construction now reject a
  second ref for one Git origin, and a no-row curses Sources screen under a required-source policy
  still offers Add/Back/Quit. A post-add curses failure now hands the refreshed Sources view to the
  text fallback. The remaining configuration write race is deliberately tracked as `CFG02`, not
  hidden by the pre-write revalidation.
- Normalized the Git-origin invariant across HTTPS/SSH/SCP transport spellings, host case, and
  optional `.git`; a safe full branch ref (`refs/heads/*`) now resolves through the fetched remote
  tracking ref. Both fixes have focused real-Git/configuration/TUI regressions.
- Final local `make quality` passed after all review corrections: Ruff format/lint, mypy on 193
  source files, all unit tests, integration/E2E, validation, coverage, packaging, and docs.
- Committed and pushed the locally complete CB01 implementation as `9bdb24d`
  (`codex/remove-legacy-root-catalog`). No issue/PR, merge, tag, or release was created.
- Opened post-1.0 tracking issue #61 for the catalog-boundary program (CB01, LIFE02, SRC02, CFG02,
  REG02, REL02). Released issue #27 stays closed and historical.
- Re-ran the complete quality matrix on the final branch state rather than trusting the earlier
  green run: `format-check, lint, typecheck, unit, integration, e2e, validate, coverage,
  packaging-check, docs-check` all pass, total branch coverage 85.12%, `version check OK: 1.0.0`.
- Opened the CB01 review PR against `main` as #62; all four CI jobs (Python 3.10 and 3.14, push and
  pull_request) passed and the PR reports `mergeStateStatus=CLEAN`. Merge, tag, and release remain
  unauthorized and deliberately not performed.

### 2026-08-11 — LIFE02 work log

- Branched `codex/aart-life02-marketplace-lifecycle` from the CB01 branch rather than `main`: the
  task extends the `marketplace` command surface CB01 introduces, so it is a stacked review PR.
- TDD, red first. `parse_artifact_selectors` was written against failing tests; one of them caught a
  real ordering defect before it could ship — a selector dataclass with `order=True` raised
  `TypeError` when a qualified and an unqualified selector shared an identity, because `None` is not
  comparable to a `SourceAlias`. Ordering now uses the rendered selector, which is total.
- Resolution reuses the catalog's existing `resolve_artifact`, so the ambiguity contract is the one
  the marketplace already enforces rather than a second, drifting implementation. Resolved
  coordinates are version-pinned by the catalog; the tests assert the pinned form.
- The Review/Finalize boundary is the load-bearing safety property: without `--yes` a command
  prepares the plan, prints it, and returns without calling `finalize`. With `--yes` it finalizes
  the digest of the review computed in the same process, so a plan cannot drift between the two.
- Setup authorizations are separate opt-in flags and each defaults to denying. Consent for setup
  effects is a decision derived from `--approve-setup-effects`, never a prompt and never implied.
- `--scope user` combined with `--project` is rejected by an existing CLI guard; the E2E harness
  honours that guard instead of working around it.
- Residual gap, stated rather than hidden: E2E covers setup *planning*, review, and the empty-queue
  path, but not real setup *execution*. Executing a recipe through the CLI would run real
  subprocesses, and the only way to make it hermetic would be to add a test-only runtime injection
  seam to production code. Setup execution stays covered by the existing setup-engine tests
  (`tests/setup_e2e_test.py`), and `--approve-setup-effects` is covered at the unit level.
- Full local `make quality` passed: Ruff format/lint, mypy, unit, integration, E2E, validation,
  coverage, packaging, and docs.

## Status rules

Allowed task states:

- `pending` — dependencies or execution have not started;
- `in_progress` — the only task currently being implemented;
- `blocked` — cannot proceed safely; blocker is recorded below;
- `complete` — local gates passed; the task record becomes authoritative only after its PR is merged
  to `main`.

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
| SRC01 | Local/Git acquisition and snapshots | CFG01,C01 | complete | `codex/aart-1-0-src01-source-acquisition` | [#38](https://github.com/M1F1/agent-artifacts/pull/38) / `88d764a` | Four Python 3.10/3.14 CI jobs passed; squash merge and branch deletion verified |
| CAS01 | Immutable content-addressed store | SRC01,P02 | complete | `codex/aart-1-0-cas01-content-store` | [#39](https://github.com/M1F1/agent-artifacts/pull/39) / `15304ae` | Four Python 3.10/3.14 CI jobs passed; squash merge and branch deletion verified |
| MKT01 | Federated marketplace and trust | C02,CFG01,CAS01 | complete | `codex/aart-1-0-mkt01-federated-marketplace` | [#40](https://github.com/M1F1/agent-artifacts/pull/40) / `85a5a5f` | Two four-job Python 3.10/3.14 CI matrices passed; squash merge and branch deletion verified |
| IMP01 | Importer contract and legacy catalog importer | MKT01 | complete | `codex/aart-1-0-imp01-legacy-importer` | [#41](https://github.com/M1F1/agent-artifacts/pull/41) / `e3157d3` | Two four-job Python 3.10/3.14 CI matrices passed; squash merge and branch deletion verified |
| IMP02 | Native references/promotion/upstream locks | IMP01,P03 | complete | `codex/aart-1-0-imp02-native-promotion` | [#42](https://github.com/M1F1/agent-artifacts/pull/42) / `ab8ae2b` | Two four-job Python 3.10/3.14 CI matrices passed; squash merge and branch deletion verified |
| REG01 | Maintainer registry commands/quality gate | IMP02 | complete | `codex/aart-1-0-reg01-registry-commands` | [#43](https://github.com/M1F1/agent-artifacts/pull/43) / `7351861` | Two four-job Python 3.10/3.14 CI matrices passed; squash merge and branch deletion verified |
| STATE01 | Manifest v2 and state migration | REG01 | complete | `codex/aart-1-0-state01-state-migration` | [#44](https://github.com/M1F1/agent-artifacts/pull/44) / `3affea4` | Two four-job Python 3.10/3.14 CI matrices passed; squash merge and branch deletion verified |
| INS01 | Canonical object install with Copy | STATE01,MKT01,CAS01 | complete | `codex/aart-1-0-ins01-canonical-copy` | [#45](https://github.com/M1F1/agent-artifacts/pull/45) / `314e5e0` | Two four-job Python 3.10/3.14 CI matrices passed; squash merge and branch deletion verified |
| INS02 | Durable managed Symlink | INS01 | complete | `codex/aart-1-0-ins02-managed-symlink` | [#46](https://github.com/M1F1/agent-artifacts/pull/46) / `0940566` | Two four-job Python 3.10/3.14 CI matrices passed; squash merge verified |
| LIFE01 | Status/update/check/uninstall lifecycle | INS02 | complete | `codex/aart-1-0-life01-lifecycle` | [#47](https://github.com/M1F1/agent-artifacts/pull/47) / `e23c726` | Two four-job Python 3.10/3.14 CI matrices passed; squash merge verified |
| SET01 | Setup trust/digest/policy integration | LIFE01 | complete | `codex/aart-1-0-set01-setup` | [#48](https://github.com/M1F1/agent-artifacts/pull/48) / `7a4b045` | Two four-job Python 3.10/3.14 CI matrices passed; squash merge and branch deletion verified |
| SEC01 | Zero-dependency risk baseline | SET01,P02,P03 | complete | `codex/aart-1-0-sec01-risk-baseline` | [#49](https://github.com/M1F1/agent-artifacts/pull/49) / `655ac46` | Two four-job Python 3.10/3.14 CI matrices passed; squash merge and branch deletion verified |
| SEC02 | Optional out-of-process analyzers | SEC01 | complete | `codex/aart-1-0-sec02-analyzers` | [#50](https://github.com/M1F1/agent-artifacts/pull/50) / `524ff38` | Two four-job Python 3.10/3.14 CI matrices passed; squash merge and branch deletion verified |
| SEC03 | Attestations/bundle aggregation/policy | SEC02,C02,REG01 | complete | `codex/aart-1-0-sec03-attestations-policy` | [#51](https://github.com/M1F1/agent-artifacts/pull/51) / `feecf26` | Two four-job Python 3.10/3.14 CI matrices passed; squash merge and branch deletion verified |
| TUI01 | First-run source management/health | MKT01,REG01,SEC03 | complete | `codex/aart-1-0-tui01-source-health` | [#52](https://github.com/M1F1/agent-artifacts/pull/52) / `62cadb5` | Two final four-job Python 3.10/3.14 CI matrices passed after recorded format/test-isolation fixes; squash merge and branch deletion verified |
| TUI02 | Consumer marketplace/cart/review | TUI01,LIFE01 | complete | `codex/aart-1-0-tui02-consumer-marketplace` | [#53](https://github.com/M1F1/agent-artifacts/pull/53) / `d37feb8` | Two replacement four-job Python 3.10/3.14 CI matrices passed after the recorded platform-fixture fix; squash merge and branch deletion verified |
| TUI03 | Maintainer curation/security UX | TUI02,REG01 | complete | `codex/aart-1-0-tui03-maintainer-curation` | [#54](https://github.com/M1F1/agent-artifacts/pull/54) / `7089147` | Two four-job Python 3.10/3.14 matrices passed; squash merge and branch deletion verified |
| RPT01 | Optional registry-owned usage reporting | TUI02,CFG01,SEC03 | complete | `codex/aart-1-0-rpt01-usage-reporting` | [#55](https://github.com/M1F1/agent-artifacts/pull/55) / `716051e` | Final four-job Python 3.10/3.14 matrix passed; protected squash merge and exact `origin/main` verified |
| SEP01 | Public reference-registry boundary | TUI03,REG01,IMP01 | complete | `codex/aart-1-0-sep01-reference-registry` | [#56](https://github.com/M1F1/agent-artifacts/pull/56) / `0e63768` | Final four-job Python 3.10/3.14 matrix passed; protected squash merge and exact `origin/main` verified |
| MIG01 | Complete 0.1.x compatibility migration | SEP01,STATE01 | complete | `codex/aart-1-0-mig01-compatibility-migration` | [#57](https://github.com/M1F1/agent-artifacts/pull/57) / `e70ec62` | Final four-job Python 3.10/3.14 matrix passed; protected squash merge and exact `origin/main` verified |
| DIST01 | Local wheel/editable Nexus readiness | MIG01,SEP01 | complete | `codex/aart-1-0-dist01-distribution` | [#58](https://github.com/M1F1/agent-artifacts/pull/58) / `b05fd42` | Final four-job Python 3.10/3.14 matrix passed; protected squash merge and exact `origin/main` verified |
| E2E01 | Full system/fault-injection matrix | DIST01,RPT01 | complete | `codex/aart-1-0-e2e01-system-matrix` | [#59](https://github.com/M1F1/agent-artifacts/pull/59) / `5ae7310` | Final four-job Python 3.10/3.14 matrix passed; protected squash merge and exact `origin/main` verified |
| REL01 | Stable release gates and `1.0.0` | all | complete | `codex/aart-1-0-rel01-stable-release` | [#60](https://github.com/M1F1/agent-artifacts/pull/60) / `92aa3ea` (`v1.0.0`) | Stable `1.0.0` released after the protected PR merge. Docs/schema freeze, 24 focused tests, local gates, and Python 3.10/3.14 CI passed; immutable tag resolves to the merged commit. |

## Current-task template

Copy and fill this section when a task becomes `in_progress`; clear it only after the PR is merged
or the task is recorded as blocked.

```text
Task: CB01 — post-v1.0.0 catalog boundary and source onboarding (locally complete)
Branch: codex/remove-legacy-root-catalog
Worktree: /private/tmp/aart-catalog-cleanup.V7N3iV/worktree
Started: 2026-08-11
Bounded contexts: executable-only repository boundary, explicit source onboarding, TUI first-run
  behavior, agent JSON discovery, configuration policy, documentation, and regression gates
Red tests and expected failures: embedded legacy/canonical roots and dangling symlinks are rejected;
  first run no longer invents a bundled catalog; partial required-source configuration is usable
  only for source management, never marketplace content; duplicate Git origins across refs and an
  empty required-policy curses Sources screen are rejected/navigable respectively
Focused tests: repository boundary, configuration/policy, source CLI/runtime/validation, TUI source
  stage, consumer read-only marketplace, version synchronization, release fixtures
Files owned: tool code/tests, executable-boundary docs, post-v1 plan/TODO/PROGRESS; no registry
  payloads or `v1.0.0` release evidence
Risks/migrations: source sync must precede config write; source refs remain origin-keyed until SRC02;
  configuration writes need CAS/locking in CFG02; content remains fail-closed until required
  sources are complete; browse must not materialize CAS
Commit: `9bdb24d` pushed to `origin/codex/remove-legacy-root-catalog`
PR: not opened; a new post-1.0 issue must be linked before review PR creation
CI: local `make quality` passed after final corrections (Ruff format/lint, mypy on 193 source
  files, all unit tests, integration/E2E, validation, coverage, packaging, and docs)
Merge: none — commit/push only; do not tag/release
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
| SRC01 | 54 pass | 223 files pass | pass | 97 source files pass | 1030 pass | 22 pass | 11-step pass | pass | 87.10% overall; 95.42% source context | `1.0.0a1` wheel/import pass | pass | 4× Python 3.10/3.14 pass |
| CAS01 | 37 pass | 239 files pass | pass | 104 source files pass | 1067 pass | 23 pass | 11-step pass | pass | 87.34% overall; 91.01% store context | `1.0.0a1` wheel/import pass | pass | 4× Python 3.10/3.14 pass |
| MKT01 | 47 pass | 250 files pass | pass | 107 source files pass | 1088 pass | 24 pass | 11-step pass | pass | 87.55% overall; 97.56% marketplace/config contexts | `1.0.0a1` wheel/import pass | pass | 2× 4-job Python 3.10/3.14 pass |
| IMP01 | 42 pass | 267 files pass | pass | 113 source files pass | 1130 pass | 28 pass | 11-step pass | pass | 87.78% overall; 90.61% importer/application/IO contexts | `1.0.0a1` wheel/import pass | pass | local Python 3.14.6 all 1130 pass; 2× 4-job Python 3.10/3.14 pass |
| IMP02 | 31 pass + 2 subtests | 281 files pass | pass | 118 source files pass | 1161 pass | 28 pass | 11-step pass | pass | 87.72% overall; 85.68% focused context | `1.0.0a1` wheel/import pass | pass | local Python 3.14.6 all 1161 pass; first 4-job Python 3.10/3.14 CI matrix passed |
| REG01 | 126 pass + 206 subtests | 298 files pass | pass | 127 source files pass | 1197 pass | 28 pass | 11-step pass | pass | 86.92% overall (≥82%) | `1.0.0a1` wheel/import pass | pass | local Python 3.14 all 1197 pass; first 4-job Python 3.10/3.14 matrix passed |
| STATE01 | 28 pass + 8 subtests | 309 files pass | pass | 135 source files pass | 1225 pass | 28 pass | 11-step pass | pass | 86.59% overall (≥82%) | `1.0.0a1` wheel/import pass | pass | local Python 3.14 all 1225 pass; first 4-job Python 3.10/3.14 matrix passed |
| INS01 | 27 pass | 315 files pass | pass | 139 source files pass | 1243 pass | 28 pass | 11-step pass | pass | 86.12% overall (≥82%) | `1.0.0a1` wheel/import pass | pass | local Python 3.14.6 all 1243 pass; first 4-job Python 3.10/3.14 matrix passed |
| INS02 | 55 pass | 316 files pass | pass | 139 source files pass | 1252 pass | 28 pass | 11-step pass | pass | 86.12% overall (≥82%) | `1.0.0a1` wheel/import pass | pass | local Python 3.14.6 all 1252 pass; first 4-job Python 3.10/3.14 matrix passed |
| LIFE01 | 53 pass | 322 files pass | pass | 143 source files pass | 1285 pass | 28 pass | 11-step pass | pass | 85.86% overall (≥82%) | `1.0.0a1` wheel/import pass | pass | local Python 3.14.6 all 1285 pass; 2× 4-job Python 3.10/3.14 pass |
| SET01 | 62 pass | 327 files pass | pass | 147 source files pass | 1303 pass | 28 pass | 11-step pass | pass | 85.91% overall; 90.94% new setup context | `1.0.0a1` wheel/import pass | pass | local Python 3.14.6 all 1303 pass; first 4-job Python 3.10/3.14 matrix passed |
| SEC01 | 46 pass | 332 files pass | pass | 151 source files pass | 1331 pass | 28 pass | 11-step pass | stdlib-only runtime pass | 86.15% overall; 93.87% security context | `1.0.0a1` wheel/import pass | pass | local Python 3.14.6 all 1331 pass; first 4-job Python 3.10/3.14 matrix passed |
| SEC02 | 43 pass | 339 files pass | pass | 155 source files pass | 1374 pass | 28 pass | 11-step pass | stdlib-only runtime pass | 86.45% overall; 94.91% analyzer contexts | `1.0.0a1` wheel/import pass | pass | local Python 3.14.6 all 1374 pass; first 4-job Python 3.10/3.14 matrix passed |
| SEC03 | 159 pass | 353 files pass | pass | 164 source files pass | 1400 pass | 28 pass | 11-step pass | stdlib-only runtime pass | 86.29% overall (≥82%) | `1.0.0a1` wheel/import pass | pass | local Python 3.14.6 all 1400 pass; first 4-job Python 3.10/3.14 matrix passed |
| TUI01 | 45 pass; 138 TUI pass | 356 files pass on Ruff 0.12.2 and 0.16.2 | pass | 166 source files pass | 1423 pass | 28 pass | 11-step pass | stdlib-only runtime pass | 86.26% overall; 96.45% source values, 100% finalizer | `1.0.0a1` wheel/import pass | pass | local Python 3.14.6 all 1423 pass; first 4-job Python 3.10/3.14 matrix passed |
| TUI02 | 36 focused; 167 TUI/consumer pass | 367 files pass | pass | 172 source files pass | 1452 pass | 28 pass | 11-step pass | stdlib-only runtime pass | 86.26% overall; 87.98% focused consumer contexts | `1.0.0a1` wheel/import pass | pass | local pass; 2× replacement 4-job Python 3.10/3.14 matrices passed |
| TUI03 | 57 focused | 375 files pass | pass | 175 source files pass | 1472 pass | 29 pass | 11-step pass | stdlib-only runtime pass | 86.06% overall; 91.19% focused curation contexts | `1.0.0a1` wheel/import pass | pass | local Python 3.11.0 complete quality wrapper and first 4-job Python 3.10/3.14 matrix pass; final ledger matrix pending |
| RPT01 | 32 reporting; 56 cross-context regressions | 395 files pass | pass | 185 source files pass | 1506 pass | 29 pass | 11-step pass | stdlib-only runtime/version pass | 85.74% overall (≥82%) | `1.0.0a1` wheel/import pass | pass | replacement 4-job Python 3.10/3.14 matrix passed after one format-only CI correction; final ledger matrix pending |
| SEP01 | 32 publication/export | 399 files pass | pass | 186 source files pass | 1519 pass | 31 pass | 11-step pass | strict registry + stdlib/version pass | 85.83% overall; 92.81% publication boundary | `1.0.0a1` wheel/import/no-registry-roots pass | pass | registry minimum/latest jobs and replacement 4-job Python 3.10/3.14 tool matrix pass after recorded test-fixture corrections; final ledger matrix pending |
| MIG01 | 84 pass + 46 subtests | 404 files pass | pass | 188 source files pass | 1545 pass | 35 pass | 11-step pass | strict catalog/runtime + version pass | 85.58% overall (≥82%) | `1.0.0a1` wheel/import pass | pass | final 4-job Python 3.10/3.14 matrix passed; exact protected merge verified |
| DIST01 | 86 pass | 406 files pass | pass | 188 source files pass | 1546 pass | 36 pass | 11-step pass | strict catalog/runtime + version pass | 85.54% overall (≥82%) | allowlisted `1.0.0a1` wheel/RECORD/import plus editable-wheel lifecycle pass | pass | final 4-job Python 3.10/3.14 matrix passed; exact protected merge verified |
| E2E01 | 8 focused + 13 scenarios/18 acceptance tests | 410 files pass | pass | 188 source files pass | 1553 pass | 39 pass | 11-step pass | strict catalog/runtime + version pass | 85.56% overall (≥82%) | allowlisted `1.0.0a1` wheel/RECORD/import pass | pass | final 4-job Python 3.10/3.14 matrix passed; exact protected merge verified |
| REL01 | 24 release/version/workflow/export tests | 414 files pass | pass | 188 source files pass | 1566 pass | 40 pass | 11-step pass | stable version/schema/system matrix pass | 85.62% overall (≥82%) | `1.0.0` wheel/RECORD/import pass | pass | PR #60 merged as `92aa3ea`; tag/release `v1.0.0` verified |

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
| D-017 | Effective marketplace trust is a local policy overlay bound to source, snapshot, object, review, provenance, and policy evidence | accepted | Prevents source self-claims, aliases, and default ranking from granting reviewed trust and makes evidence changes invalidate the decision |
| D-018 | Native registry references retain upstream source identity and promotion is a reviewed three-file projection | accepted | Preserves marketplace qualification, avoids payload duplication, and confines mutations to entry/lock/index without commit or push |
| D-019 | Setup authority is a reviewed digest-bound plan over exact object, recipe, trust, policy, platform, and destination evidence | accepted | Prevents source drift or trust changes from gaining execution authority; custom code runs only from a verified private copy and setup remains independently reportable/rollbackable |
| D-020 | Installation-risk evidence binds the exact object and a canonical baseline rules descriptor; incomplete coverage remains unknown unless observed high/critical facts dominate | accepted | Keeps stdlib-only evidence deterministic and explainable without turning a completed heuristic scan into a certification or hiding serious observations behind skipped coverage |
| D-021 | Optional analyzers are trusted bounded processes with object-bound evidence; built-ins disable ambient config and normalize secret-free native output | accepted | Preserves a zero-dependency runtime and explicit unknown coverage without claiming OS sandboxing or letting tools choose commands, install packages, or rebind results to another object |
| D-022 | Security attestations bind object/provider/rules/options/policy; registry evidence trust is local-policy-derived and bundle gates preserve worst/unknown facts | accepted | Prevents stale or self-trusting evidence, makes optional provider absence explicit, and keeps favorable averages from hiding critical/high/unknown installation risk |

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

### 2026-08-07 — SRC01 PR quality passed

- Pushed implementation commit `b5aed23` and opened ready PR #38.
- All four push/pull_request quality jobs passed on Python 3.10 and 3.14 without a CI-only fix.
- Recorded the verified evidence and marked the task complete in its branch; the status becomes
  authoritative only after the protected squash merge to `main`.

### 2026-08-07 — SRC01 merged; CAS01 started

- Observed all four replacement Python 3.10/3.14 jobs pass and squash-merged PR #38 as `88d764a`;
  verified the merged PR, exact `origin/main`, and remote branch deletion.
- Removed only the explicit SRC01 temporary worktree and created isolated CAS01 from exact
  `88d764a`; unrelated root-worktree files remain untouched.
- Scoped CAS01 to digest verification, safe atomic convergence/repair, immutable modes, explicit
  references, non-following verification, and plan-before-execute garbage collection.

### 2026-08-07 — CAS01 Red/Green and security review

- Confirmed initial Red with six expected import errors for the absent immutable object model,
  application orchestration, filesystem store, reference persistence, and store-lock APIs.
- Added a strict canonical object envelope, SHA-256-bound immutable candidates, normalized tree and
  size/count/depth limits, compiler-plan materialization, and fixed managed path identities.
- Added private stage/flush/freeze/atomic publication, concurrent identical convergence, verified
  read-back, safe corruption repair, explicit missing/verified/degraded status, and read-only object
  trees that preserve executable bits.
- Added canonical `0600` reference persistence for installed, setup, source-current, retained,
  rollback, and transaction roots; owner/kind replacement and dry-run-first GC share one global
  lease, and execute mode can delete only the exact unreferenced plan.
- Repository code review captured Red regressions before fixes for forged candidate values,
  symlinked state and intermediate managed paths, directory-to-symlink scan races, unbounded entry
  counts, status/digest mismatch, duplicate GC receipts, and physical-delete rollback. Complete
  tombstones are verified, restored, and re-frozen when removal fails.
- Verified 37 focused tests and 91.01% branch coverage for the complete new store context; full
  `make quality` passes with 1067 unit tests, 23 integration tests, shell E2E, strict mypy over 104
  source files, Ruff, 87.34% global branch coverage, validation, `1.0.0a1` wheel/import, and docs.
  All 1067 tests also pass on Python 3.14.6; exact PR/CI evidence follows below.

### 2026-08-07 — CAS01 PR quality passed

- Pushed implementation commit `cf845a1` and opened ready PR #39.
- All four push/pull_request quality jobs passed on Python 3.10 and 3.14 without a CI-only fix.
- Recorded the verified evidence and marked the task complete in its branch; the status becomes
  authoritative only after the protected squash merge to `main`.

### 2026-08-07 — CAS01 merged; MKT01 started

- Observed all four replacement Python 3.10/3.14 jobs pass and squash-merged PR #39 as `15304ae`;
  verified the merged PR, exact `origin/main`, store files, and remote branch deletion.
- Removed only the explicit clean CAS01 temporary worktree and created isolated MKT01 from exact
  `15304ae`; unrelated root-worktree files remain untouched.
- Scoped MKT01 around the existing qualified C02 graph: deterministic ranking without shadowing,
  exact resolution, source health/freshness, local policy-derived trust, provenance/digest output,
  and trust-evidence invalidation.

### 2026-08-07 — MKT01 Red/Green and boundary review

- Confirmed Red with four expected import errors for the absent marketplace package and exact
  company-reviewed source policy identity; the pure dependency-boundary test already passed.
- Added a bounded deterministic union over enabled runtime source states and the qualified C02
  graph, default-registry presentation ranking without shadowing, explicit unique/qualified
  resolution, removed-history projections, and preservation of qualified collections.
- Added locally derived `local`, `direct-source`, `registry-reviewed`, `company-reviewed`, and
  `unverified` decisions. Company review requires the exact declared source ID, normalized Git
  host/repository policy identity, and an approved registry entry; aliases, defaults, and direct
  source review metadata cannot elevate trust.
- Bound trust evidence to artifact digests, normalized provenance, source identity/origin/revision/
  snapshot, entry review, and the complete canonical policy. JSON and human projections include
  qualified provenance/digest/health/trust evidence and defensively redact common secrets.
- Repository code review tightened strict SemVer/slug/query values, runtime health/current
  consistency, source/item/collection binding, duplicate collection rejection, hard catalog
  bounds, ambiguity details, and credential-bearing provenance/summary output.
- Verified 47 focused tests and 97.56% branch coverage across the marketplace/configuration
  contexts. The canonical non-mutating quality matrix passes with 1088 unit tests, 24 integration
  tests, the 11-step shell E2E, strict mypy over 107 source files, Ruff over 250 files, 87.55%
  global branch coverage, validation, `1.0.0a1` wheel/import, and documentation. All 1088 tests
  also pass on Python 3.14.6; exact PR/CI evidence follows below.

### 2026-08-07 — MKT01 implementation PR quality passed

- Pushed implementation commit `54c139a` and opened ready PR #40.
- All four push/pull_request quality jobs passed on Python 3.10 and 3.14 without a CI-only fix.
- Recorded the verified evidence and marked the task complete in its branch; the status becomes
  authoritative only after the protected squash merge to `main`.

### 2026-08-07 — MKT01 merged; IMP01 started

- Observed all four replacement Python 3.10/3.14 jobs pass and squash-merged PR #40 as `85a5a5f`;
  verified the merged PR, exact `origin/main`, and remote branch deletion.
- Removed only the explicit clean MKT01 temporary worktree and created isolated IMP01 from exact
  `85a5a5f`; unrelated files in the root worktree remain untouched.
- Scoped IMP01 to a built-in, maintainer-only importer registry and a plan-before-apply workflow
  that converts the complete 0.1.x catalog layout into validated canonical native packages with
  digest-bound provenance and no content execution.

### 2026-08-07 — IMP01 Red

- Added a complete legacy-catalog fixture covering skills, guidelines, MCP plus declarative setup,
  hooks with inert executable-looking payload, memory, bundles/pins, and pinned upstream tracking.
- Confirmed Red with five expected import errors because the new importer package and canonical
  provenance/collection writers do not exist; both dependency-boundary tests already pass.
- Fixed the contract around explicit immutable Git input, strict built-in importer/version/options,
  deterministic canonical materialization and validation, exact provenance, loss/ambiguity/stale
  rejection, and digest-bound diff/apply planning.

### 2026-08-07 — IMP01 Green and review

- Implemented the closed `legacy-catalog-v1` registry and frozen scan/plan/materialize/validate/
  diff/apply values over immutable Git snapshots, with exact option/input/output/review digests.
- Converted skills, guidelines, MCP, hooks, memory, bundles/pins, declarative setup content, and
  tracked/untracked origins into deterministic native source packages and provenance without
  executing repository content or retaining timestamps, credentials, or checkout-local paths.
- Added a reviewed filesystem output port with bounded descriptor-relative reads, symlink/special
  file rejection, private sibling staging, destination preconditions, verified replacement,
  rollback, no-op feedback, retained-backup warnings, and post-publication durability warnings.
- Applied the repository `code-review` skill. It found two substantive adapter defects: forged
  prefix-compatible stage receipts and a false failure after successful publication when parent
  `fsync` failed. Bound stages to their issuing live adapter and made post-publication durability
  failure an explicit success warning; regression and fault-injection tests cover both fixes.
- Focused Red/Green/regression suite: 42 tests pass with 90.61% branch coverage across the new
  importer/application/filesystem contexts; Ruff and mypy pass across the complete changed scope.
- Canonical `make quality` passes: 267 formatted/linted files, 113 typed source files, 1130 unit
  tests, 28 integration tests, 11-step shell E2E, validation/version checks, 87.78% global branch
  coverage, deterministic `1.0.0a1` wheel packaging, and documentation checks.
- Re-ran all 1130 unit/regression tests successfully on local Python 3.14.6. The two pre-existing
  HTTP 401 cleanup `ResourceWarning` messages remain non-failing and are unrelated to IMP01.

### 2026-08-07 — IMP01 implementation CI

- Committed the reviewed implementation as `4e25b46`, pushed the isolated task branch, and opened
  ready PR #41 targeting `main`.
- All four push/pull_request quality jobs passed on Python 3.10 and 3.14 without a CI-only code fix.
- Corrected a malformed PR description caused by local shell backtick interpretation; the accidental
  action only reran local quality commands and did not mutate tracked files or remote code.
- Recorded the verified implementation evidence in this ledger. A final four-job matrix reruns on
  this documentation-only commit before the protected squash merge.

### 2026-08-07 — IMP01 merged; IMP02 started

- Observed all four final ledger jobs pass and squash-merged ready PR #41 as `e3157d3`; verified the
  merged PR, exact `origin/main`, and remote branch deletion.
- Removed only the clean IMP01 temporary worktree and created the isolated IMP02 worktree from
  exact `e3157d3`; unrelated root-worktree files remain untouched.
- Scoped IMP02 to pure, review-digest-bound registry entry/promotion/upstream plans over existing
  protocol-v1 lock/index primitives, with native references that write no payload bytes and
  materialized foreign refreshes that rerun only the recorded built-in importer/options.

### 2026-08-07 — IMP02 Red

- Added tests for deterministic entry-only add, native promotion without payload duplication,
  exact lock/ref/commit/digest projection, identity mismatch, unchanged/changed upstream checks,
  recorded importer/options enforcement, and reviewed application finalization.
- Confirmed Red with five expected missing-module import errors; both pure-planner and consumer
  dependency-boundary tests already pass.

### 2026-08-07 — IMP02 Green, review, and local gates

- Added pure entry, native promotion, locked-upstream check, and recorded-importer rerun planners;
  every registry change is digest-bound and limited to entry/lock/index, while apply remains behind
  an injected port with no Git publication operation.
- Native references retain the acquired upstream `source_id` and payload bytes stay in the source;
  registry-owned packages and collections are revalidated and preserved in the compiled index.
- Applied the repository `code-review` skill. Regression-first review fixed forged review digests,
  stale no-op finalization, inconsistent lock/index preservation, hard-coded artifact roots, lost
  owned packages, source-ID changes, runtime value validation, and pending/re-review transitions.
- Verified 31 focused tests plus 2 subtests and the broader registry/importer suite; strict mypy and
  dependency-boundary tests forbid IO, Git/process, dynamic-plugin, and consumer-path imports.
- `make quality` passes with 1,161 unit tests, 28 integration tests, the 11-step shell E2E, Ruff over
  281 files, mypy over 118 source files, 87.72% global branch coverage, `1.0.0a1` wheel/import,
  validation, docs, and the non-mutation check. All 1,161 tests also pass on Python 3.14.6.

### 2026-08-07 — IMP02 implementation CI

- Committed the reviewed implementation as `05a758c`, pushed the isolated task branch, and opened
  ready PR #42 targeting `main` with the complete Red/Green/gate/security evidence.
- All four push/pull_request quality jobs passed on Python 3.10 and 3.14 without a CI-only fix; the
  PR is mergeable with a clean merge state.
- Recorded the evidence in this ledger. A final four-job matrix reruns on this documentation-only
  commit before the protected squash merge.

### 2026-08-07 — IMP02 merged; REG01 started

- Observed all four final ledger jobs pass and squash-merged ready PR #42 as `ab8ae2b`; verified the
  merged PR, exact `origin/main`, and remote branch deletion.
- Removed only the clean IMP02 temporary worktree and created the isolated REG01 worktree from
  exact `ab8ae2b`; unrelated root-worktree files remain untouched.
- Scoped REG01 to deterministic registry init/scaffold/format/validate/lock/build/audit/test/diff/
  migrate commands, a review-before-apply local workspace adapter, compatibility/CI templates, and
  explicit rejection of managed or non-writable mutation targets without any Git commit/push.

### 2026-08-07 — REG01 Red

- Added contract tests for deterministic init and CI templates, valid artifact scaffolding,
  canonical format checks, lock/build projections, validation/audit/minimum-latest compatibility,
  legacy migration, filesystem preconditions, all ten CLI actions, and dependency boundaries.
- Confirmed Red with four expected missing-module collection errors and three CLI failures because
  the registry command context, workspace adapter, Request mapping, parser actions, and dispatch do
  not exist. Both no-IO functional-core and no-commit/push boundary tests already pass.

### 2026-08-10 — REG01 Green, code review, and local gates

- Implemented pure plans and application services for `registry init`, `scaffold`, `format`,
  `validate`, `lock`, `build`, `audit`, `test`, `diff`, and reviewed legacy `migrate`, including
  deterministic protocol/CI templates and minimum/latest compatibility fixtures.
- Added a bounded local-workspace adapter that requires a real writable Git checkout, rejects
  managed consumer snapshots, symlinks, special files, stale reviews, and concurrent writers, and
  atomically rolls back partial mutations without invoking Git commit or push.
- Code review added regression coverage for exact receipt/review digests, no-op races, lock-held
  writers, rollback cleanup, custom-root and workflow overwrite refusal, byte-stable payloads,
  pending-ref network boundaries, provenance/lock agreement, forged indexes, migration identity,
  and credential-free local AART installation in the generated registry workflow.
- Passed the complete local quality gate: Ruff format on 298 files, Ruff lint, mypy on 127 source
  files, 1197 unit tests, 28 integration tests, 11-step E2E, validation/version checks, 86.92%
  branch coverage, wheel build/import, docs checks, and a second 1197-test run on Python 3.14.

### 2026-08-10 — REG01 implementation CI

- Published implementation commit `ba33903` and opened ready PR #43 referencing the 1.0 umbrella
  issue without closing it.
- All four push/pull-request quality jobs passed on Python 3.10 and 3.14 without a CI-only fix; the
  PR is mergeable with a clean merge state.
- Recorded the evidence in this ledger. A final four-job matrix reruns on this documentation-only
  commit before the protected squash merge.

### 2026-08-10 — REG01 merged; STATE01 started

- Observed all four final ledger jobs pass and squash-merged ready PR #43 as `7351861`; verified the
  merged PR, exact `origin/main`, and remote branch deletion.
- Removed only the clean REG01 temporary worktree and created the isolated STATE01 worktree from
  exact `7351861`; unrelated root-worktree files remain untouched.
- Scoped STATE01 to strict schema-v2 installation evidence, explicit legacy source resolution,
  project/user path policy, and reviewed atomic migration with backup and rollback.

### 2026-08-10 — STATE01 Red

- Added contracts for canonical v2 round-trip and corruption, credential-free source evidence,
  version/digest/profile/scope/mode/effect proof, deterministic project/user migration planning,
  missing/ambiguous legacy sources, proof mismatch, backup, stale review, idempotent apply, exact
  rollback, and partial failure preservation.
- Confirmed Red with three expected collection errors because the install-state domain/schema,
  migration application service, and local state-store adapter do not exist.

### 2026-08-10 — STATE01 Green, code review, and local gates

- Implemented canonical manifest v2 with qualified source/subscription/commit evidence, artifact
  SemVer and manifest/payload/object digests, profile/scope/requested mode, per-effect actual-mode
  and ownership proof, and non-secret setup-state references.
- Added pure project/user path policy and explicit legacy candidate resolution; project state stays
  in place while user state moves from the home-root legacy path into the platform data root.
- Added reviewed prepare/apply/rollback services and a bounded no-follow filesystem adapter with
  digest-bound plans, private full-digest backups, journals, exclusive locking, atomic writes,
  idempotence, stale detection, and compensation for post-replace/post-unlink/apply/rollback faults.
- The `code-review` skill added regression coverage for Git subscription safety, forged reviewed
  plans, legacy symlink reinterpretation, merge identity binding, duplicate/unknown legacy JSON,
  global effect ownership, symlink state files, and compensation after partial mutations. No open
  review findings remain.
- The first full quality attempt stopped at one Ruff import-order finding in the narrow application
  export. Fixed it mechanically, then reran the entire gate rather than only the failed step.
- Passed Ruff format on 309 files, Ruff lint, mypy on 135 source files, 1225 unit tests, 28
  integration tests, 11-step E2E, validation/version checks, 86.59% branch coverage, wheel
  build/import, docs checks, and a second 1225-test run on Python 3.14.

### 2026-08-10 — STATE01 implementation CI

- Published implementation commit `ba52a15` and opened ready PR #44 referencing the 1.0 umbrella
  issue without closing it.
- All four push/pull-request quality jobs passed on Python 3.10 and 3.14 without a CI-only fix; the
  PR is mergeable with a clean merge state.
- Recorded the evidence in this ledger. A final four-job matrix reruns on this documentation-only
  commit before the protected squash merge.

### 2026-08-10 — STATE01 merged; INS01 started

- Observed both four-job Python 3.10/3.14 CI matrices pass and squash-merged PR #44 as `3affea4`;
  verified exact `origin/main`, merged PR state, remote branch deletion, and preserved the unrelated
  root-worktree files.
- Created isolated INS01 from exact merge `3affea4` and confirmed Red with two import errors for the
  intentionally absent canonical installation context. The contract covers qualified resolution,
  offline CAS use, trust/policy/compatibility, immutable review binding, Copy file/tree/merge
  projection, no-op/drift/stale review, manifest-v2 evidence, and partial-failure rollback.

### 2026-08-10 — INS01 Green, code review, and local gates

- Added an IO-free canonical installation model and application service for qualified resolution,
  organization-policy and shared compatibility checks, verified/offline CAS reads, exact
  destination/state snapshots, immutable Review digests, and source-aware Copy finalization.
- Projected skill trees, guideline files, MCP key merges, hook tree/list merges, and memory files or
  managed blocks through established pure planners. JSON merges preserve foreign configuration,
  reject path/identity collisions unless force was reviewed, and distinguish multiple managed
  identities sharing one configuration path.
- Added a bounded no-follow local adapter with scope locking, transaction and durable installed CAS
  references, atomic state-last writes, structured no-op/conflict/failure results, and compensation
  for effect, state, and reference-update faults.
- Applied the repository `code-review` skill. Review added manifest/payload/provenance revalidation,
  marketplace/policy revalidation at Finalize, bounded tree inspection, nonblocking locks, unsafe
  symlink rejection, rollback of the failing operation, transaction references, stable ownership
  history, local-source evidence, normalized credential-free provenance, and merge-identity tests.
  No open review findings remain.
- Focused tests pass: 27 tests covering resolution, offline/cache, trust/compatibility, all Copy
  effects, drift/force/no-op, stale Review, manifest-v2/reference evidence, JSON ownership, and
  partial-failure rollback.
- `make quality` passes with Ruff format on 315 files, Ruff lint, mypy on 139 source files, 1243 unit
  tests, 28 integration tests, the 11-step shell E2E, validation/version checks, 86.12% branch
  coverage, `1.0.0a1` wheel/import, docs, and repository non-mutation. An initial auxiliary Python
  3.14 command used a stale pyenv path and failed before running tests; the detected
  `/opt/homebrew/bin/python3.14` then passed all 1243 tests on Python 3.14.6.

### 2026-08-10 — INS01 implementation CI

- Published reviewed implementation commit `b29cc23` and opened ready PR #45 referencing the 1.0
  umbrella issue without closing it.
- All four push/pull-request quality jobs passed on Python 3.10 and 3.14 without a CI-only fix; the
  PR is mergeable with a clean merge state.
- Recorded the evidence in this ledger. A final four-job matrix reruns on this documentation-only
  commit before the protected squash merge.

### 2026-08-10 — INS01 merged; INS02 started

- Observed all four final ledger jobs pass and squash-merged ready PR #45 as `314e5e0`; verified
  exact `origin/main`, merged PR state, remote branch deletion, and preserved the unrelated root
  worktree files.
- Removed only the clean INS01 temporary worktree and created isolated INS02 from exact merge
  `314e5e0`.
- Scoped INS02 to immutable CAS-backed file/tree symlinks, mixed copied merge effects, explicit
  atomic retarget, broken/replaced/retargeted classification, object-reference replacement, and an
  opt-in verified mutable-local developer link for local sources.

### 2026-08-10 — INS02 Red

- Added seven end-to-end application contracts for immutable CAS tree/file links, copied fallback
  and mixed hook effects, environment deletion, source-sync stability, explicit retarget plus
  reference replacement, link-state classification, mutable-local edits, and retarget rollback.
- Confirmed Red with the expected import failure because the canonical installation context had no
  LinkOperation, LinkStatus, or classifier and rejected all Symlink requests.

### 2026-08-10 — INS02 Green, code review, and local gates

- Implemented exact immutable-CAS file/tree link plans while keeping merge/configuration effects in
  Copy mode; managed targets never point at a checkout, virtual environment, executable package,
  or moving source pointer. Source refresh alone leaves installed links unchanged, and an explicit
  reviewed update atomically retargets the link and replaces its durable installed object reference.
- Added target and destination preconditions, atomic sibling-link replacement, state-last commit,
  transaction references, exact rollback, and status classification for current, mutable-local,
  broken, retargeted, and replaced links. The opt-in mutable-local mode is limited to a real path
  inside the selected local source and rejects intermediate symlink escapes.
- Applied the repository `code-review` skill. Review closed findings for lexical boundary escapes,
  forged in-object targets, invalid operation topology, unsafe control characters, missing link
  postconditions, retained-object timing, and silent adoption of a foreign retargeted link. No open
  review findings remain.
- Focused coverage passes 55 tests, including nine Symlink lifecycle contracts and canonical
  install/state regressions. `make quality` passes Ruff format on 316 files, Ruff lint, mypy on 139
  source files, 1252 unit tests, 28 integration tests, the 11-step shell E2E, validation/version
  checks, 86.12% branch coverage, `1.0.0a1` wheel/import, docs, and repository non-mutation. All
  1252 tests also pass on Python 3.14.6; two pre-existing HTTP cleanup ResourceWarnings are nonfatal.

### 2026-08-10 — INS02 implementation CI

- Published reviewed implementation commit `55720ce` and opened ready PR #46 referencing the 1.0
  umbrella issue without closing it.
- All four push/pull-request quality jobs passed on Python 3.10 and 3.14 without a CI-only fix; the
  PR is mergeable with a clean merge state.
- Recorded the evidence in this ledger. A final four-job matrix reruns on this documentation-only
  commit before the protected squash merge.

### 2026-08-10 — INS02 merged; LIFE01 started

- Observed all four final ledger jobs pass and squash-merged ready PR #46 as `0940566`; verified
  exact `origin/main`, merged PR state, remote branch deletion, and preserved the unrelated root
  worktree files.
- Removed only the clean INS02 temporary worktree and created isolated LIFE01 from exact merge
  `0940566`.
- Scoped LIFE01 to offline manifest-v2 status, current-snapshot checks without implicit fetch,
  updates through exact recorded source subscriptions, explicit upstream-removal pruning, safe
  effect-owned uninstall, per-selection terminal outcomes, scope isolation, and reference release.

### 2026-08-10 — LIFE01 Red

- Added end-to-end contracts for Copy/link/merge status, fetch-free exact-subscription checks,
  explicit reviewed updates, upstream-removal retention/prune, force policy, JSON preservation,
  rollback, scope selection, per-record terminal outcomes, and installed-reference release.
- Extended the state contract test with digest-bound merge identity evidence required to inspect and
  reverse one managed JSON identity without touching foreign entries.
- Confirmed Red with the expected missing `agent_artifacts.lifecycle` import and rejected
  `identity_evidence` constructor argument; no implementation path was reachable.

### 2026-08-10 — LIFE01 Green, code review, and local gates

- Added an IO-free lifecycle model/application boundary for exact scope/coordinate/profile
  selection, per-effect local status, fetch-free marketplace checks, recorded-subscription-only
  updates, explicit upstream-removal prune, reviewed uninstall, and structured terminal outcomes.
- Reused canonical Install for updates so Copy conflicts, managed-link retargets, object evidence,
  state-last writes, and installed references retain one transaction model. New state records bind
  JSON merge identities and memory composition mode; older memory records fall back to `prepend`.
- Added a no-follow local uninstall adapter that removes only state-proven effects, preserves
  foreign JSON and memory content, isolates project/user state, releases only the exact installed
  reference owner, reads back every mutation, and compensates plus verifies effect/state/reference
  rollback on failure.
- Applied the repository `code-review` skill. Review closed findings for JSON `null` versus absence,
  list-identity and container-type drift, source URL/profile mismatch, scoped operation forgery,
  reversed markers, durable mutation postconditions, reference-release verification, rollback
  verification, and retained memory mode. No open review findings remain.
- Focused coverage passes 53 tests. `make quality` passes Ruff format on 322 files, Ruff lint, mypy
  on 143 source files, 1285 unit tests, 28 integration tests, the 11-step shell E2E,
  validation/version checks, 85.86% branch coverage, `1.0.0a1` wheel/import, docs, and repository
  non-mutation.
- All 1285 tests, integration, and E2E also pass on Python 3.14.6. Local direct-script validation on
  Python 3.14 requires `PYTHONPATH=.` when the worktree is not installed; with the same import
  context as CI it passes validation, packaging, and docs. Two pre-existing HTTP cleanup
  ResourceWarnings remain nonfatal.

### 2026-08-10 — LIFE01 implementation CI

- Published reviewed implementation commit `258895b` and opened ready PR #47 referencing the 1.0
  umbrella issue without closing it.
- All four push/pull-request quality jobs passed on Python 3.10 and 3.14 without a CI-only fix; the
  PR is mergeable with a clean merge state.
- Recorded the evidence in this ledger. A final four-job matrix reruns on this documentation-only
  commit before the protected squash merge.

### 2026-08-10 — LIFE01 merged; SET01 started

- Observed all four final ledger jobs pass and squash-merged ready PR #47 as `e23c726`; verified
  exact `origin/main`, merged PR state, remote branch deletion, and preserved the unrelated root
  worktree files.
- Removed only the clean LIFE01 temporary worktree and created isolated SET01 from exact merge
  `e23c726`.
- Scoped SET01 to canonical-object recipe and plan binding, effective trust and organization-policy
  enforcement, immutable run copies, sequential stop/retry/rollback outcomes, separate payload and
  setup results, durable non-secret setup evidence, and the existing macOS/Keychain boundary.

### 2026-08-10 — SET01 Red, Green, review, and local gates

- Confirmed Red first through the missing canonical setup module and a regression demonstrating
  that custom setup still executed its mutable source path instead of an immutable reviewed copy.
- Added an IO-free canonical setup model/application boundary. Review and finalization now bind the
  exact installed object, marketplace identity, recipe, platform, destination, effective trust,
  organization policy, capabilities, and explicit authority for untrusted/custom execution.
- Added transactional setup-state and CAS-reference persistence, sequential stop/retry/rollback
  outcomes, independent payload/setup statuses, allowlisted reporting, and execution of custom
  setup only from a digest-verified private `0700` run copy. No credential value is persisted or
  emitted by the canonical boundary.
- Applied the repository `code-review` skill and closed findings for managed-root containment,
  durable rollback evidence, exact receipt validation, current-state/reference verification, and
  review-bound platform selection. No open review findings remain.
- Focused setup coverage passes 62 tests with 90.94% line coverage in the new setup context.
  `make quality` passes Ruff format on 327 files, Ruff lint, mypy on 147 source files, 1303 unit
  tests, 28 integration tests, the 11-step shell E2E, validation/version checks, 85.91% overall
  branch coverage, `1.0.0a1` wheel/import, docs, and repository non-mutation.
- The full 1303-test suite, integration tests, validation, packaging, docs, and shell E2E also pass
  on Python 3.14.6. Pre-existing nonfatal HTTP cleanup ResourceWarnings remain unchanged.

### 2026-08-10 — SET01 implementation CI

- Published reviewed implementation commit `378004c` and opened ready PR #48 referencing the 1.0
  umbrella issue without closing it.
- All four push/pull-request quality jobs passed on Python 3.10 and 3.14 without a CI-only fix; the
  PR is mergeable with a clean merge state.
- Recorded the evidence in this ledger. A final four-job matrix reruns on this documentation-only
  commit before the protected squash merge.

### 2026-08-10 — SET01 merged; SEC01 started

- Observed all four final ledger jobs pass and squash-merged ready PR #48 as `7a4b045`; verified
  exact `origin/main`, merged PR state, remote branch deletion, and preserved the unrelated root
  worktree files.
- Removed only the clean SET01 temporary worktree and created isolated SEC01 from exact merge
  `7a4b045`.
- Scoped SEC01 to deterministic, bounded, stdlib-only installation-risk evidence bound to the exact
  object and rules digests, including metadata/lock/provenance, declared effects/capabilities,
  credential, Python AST, MCP/JSON, shell, transport, and pinning observations.

### 2026-08-10 — SEC01 Red, Green, review, and local gates

- Confirmed Red first with the expected missing `agent_artifacts.security` import before any
  assessment state, digest binding, rule, or canonical evidence path was reachable.
- Added frozen assessment/provider/coverage/finding values and strict canonical JSON. Fingerprints,
  status, maximum severity, installation risk, finding counts, provider state, object digest, and
  rules digest are mutually validated; object/rules changes produce explicit stale evidence.
- Added a pure stdlib baseline over exact object/index/manifest/payload/provenance/lock agreement,
  review state, effects, setup capabilities/custom code, conservative credential patterns, Python
  AST, strict JSON/MCP, bounded shell patterns, plaintext transport, and unpinned references.
- Findings contain only generic observed facts and remediation; matched credential values and raw
  importer warnings are never emitted. Text, AST, shell, assessment input, provider, and finding
  limits turn missing coverage into partial/unknown evidence instead of unbounded work.
- Applied the repository `code-review` skill. Review closed findings for forged fingerprint/risk/
  status fields, oversized assessment arrays/input, pre-normalization finding growth, and rules
  digest coverage of engine limits/revision. No open review findings remain.
- Focused coverage passes 46 tests with 93.87% branch coverage across the new security context.
  `make quality` passes Ruff format on 332 files, Ruff lint, mypy on 151 source files, 1331 unit
  tests, 28 integration tests, the 11-step shell E2E, validation/runtime-dependency checks, 86.15%
  overall branch coverage, `1.0.0a1` wheel/import, docs, and repository non-mutation.
- The full 1331-test suite, integration tests, validation, packaging, docs, and shell E2E also pass
  on Python 3.14.6. Two pre-existing nonfatal HTTP cleanup ResourceWarnings remain unchanged.

### 2026-08-10 — SEC01 implementation CI

- Published reviewed implementation commit `01761f7` and opened ready PR #49 referencing the 1.0
  umbrella issue without closing it.
- All four push/pull-request quality jobs passed on Python 3.10 and 3.14 without a CI-only fix; the
  PR is mergeable with a clean merge state.
- Recorded the evidence in this ledger. A final four-job matrix reruns on this documentation-only
  commit before the protected squash merge.

### 2026-08-10 — SEC01 merged; SEC02 started

- Observed all four final ledger jobs pass and squash-merged ready PR #49 as `655ac46`; verified
  exact `origin/main`, merged PR state, remote branch deletion, and preserved the unrelated root
  worktree files.
- Removed only the clean SEC01 temporary worktree and created isolated SEC02 from exact merge
  `655ac46`.
- Scoped SEC02 to explicit discovery, versioned JSON handshake/scan, fixed argv with minimal
  environment, timeout/crash/malformed-output handling, network declaration/consent, duplicate
  fingerprint rejection, and reviewed output adapters for independently installed analyzers.

### 2026-08-10 — SEC02 local gates complete

- Confirmed Red because the analyzer protocol, process boundary, application mapping, and reviewed
  tool adapters did not exist; implemented a canonical `security-analyzer-v1` handshake/scan
  contract whose attempts and assessments bind the exact immutable CAS object and rules digest.
- Added fixed-argv subprocess execution with a minimal credential-free environment, one combined
  hard output cap, timeout handling, executable identity checks, no shell, and generic secret-free
  failure outcomes. Optional packages remain separately installed trusted code, never runtime
  dependencies or claimed sandboxes.
- Added deterministic discovery and native-output adapters for Ruff, Bandit, detect-secrets,
  pip-audit, and ShellCheck. Ambient config and network verification are disabled where supported;
  pip-audit alone requires network consent and receives only canonical pinned direct requirements
  over stdin, never artifact-selected options, includes, URLs, paths, or package resolution.
- Code review captured regressions for unbounded combined subprocess output, inherited open pipes,
  unsafe resolver identity, dynamic argv overflow, policy-incomplete rules digests, false pip
  locations, untrusted requirements input, and object-evidence rebinding before the fixes landed.
- Verified 43 focused tests and 94.91% branch coverage for the analyzer contexts. `make quality`
  passes Ruff format on 339 files, Ruff lint, mypy on 155 source files, 1374 unit tests, 28
  integration tests, the 11-step shell E2E, stdlib-only validation, 86.45% overall branch coverage,
  `1.0.0a1` wheel/import, docs, and repository non-mutation.
- Python 3.14.6 passes all 1374 tests, integration, shell E2E, validation, packaging, and docs. Its
  first full-wrapper attempt stopped at the absent optional Ruff package, so no global dependency
  was installed; the static developer gates remain proven by the canonical environment and CI.

### 2026-08-10 — SEC02 implementation CI

- Published reviewed implementation commit `7519147` and opened ready PR #50 referencing the 1.0
  umbrella issue without closing it.
- All four push/pull-request quality jobs passed on Python 3.10 and 3.14 without a CI-only fix; the
  PR is mergeable with a clean merge state.
- Recorded the evidence in this ledger. A final four-job matrix reruns on this documentation-only
  commit before the protected squash merge.

### 2026-08-10 — SEC02 merged; SEC03 started

- Observed all four final ledger jobs pass and squash-merged ready PR #50 as `524ff38`; verified
  exact `origin/main`, merged PR state, remote branch deletion, and preserved the unrelated root
  worktree files.
- Removed only the clean SEC02 temporary worktree and created isolated SEC03 from exact merge
  `524ff38`.
- Scoped SEC03 to exact cache/attestation identity and freshness, policy-derived registry evidence
  trust, deduplicated bundle statistics, worst/unknown installation gates, security CLI commands,
  and normalized marketplace/TUI-facing fields.

### 2026-08-10 — SEC03 Red, Green, review, and local gates

- Confirmed Red independently for absent cache/attestation/index schemas, deterministic bundle and
  policy values, normalized projections/suites, CLI security wiring, and registry-CI evidence
  verification before implementing each vertical slice.
- Added strict canonical attestations keyed by object, provider/version, rules, normalized options,
  and effective policy digests; any identity change produces stale evidence. Local cache writes are
  private, symlink-rejecting, atomic, collision-safe, and idempotent.
- Added registry security indexes whose exact document bytes, cache keys, source identity, and
  registry-input digest are verified. `registry audit` requires evidence for every compiled object,
  rejects unknown objects/tampering/critical risk, and keeps high/unknown results visible for review;
  registry evidence becomes reviewed only through an exact local trust context.
- Added deduplicated bundle worst/range/known-mean/severity/status/coverage/provider/trust summaries
  and recomputed installation policy decisions. Unknown/stale members are excluded from the mean but
  remain explicit gates; favorable means cannot override critical/high/unknown facts.
- Added normalized assessment, artifact, bundle, and policy projections plus baseline/recommended/
  extended analyzer suites. `aart security scan/show/verify/analyzers/suites` never installs optional
  providers and consistently says installation risk or assessment rather than exposing `safe`.
- Applied the repository `code-review` skill and closed findings for invalid provider-version
  crashes and missing tampered-registry evidence coverage. No open review findings remain.
- Verified 159 focused tests. `make quality` passes Ruff format on 353 files, Ruff lint, mypy on 164
  source files, 1400 unit tests, 28 integration tests, the 11-step shell E2E, stdlib-only validation,
  86.29% overall branch coverage, `1.0.0a1` wheel/import, docs, and repository non-mutation.
- Python 3.14.6 also passes all 1400 tests, validation, version, packaging, and docs gates. Two
  pre-existing nonfatal HTTP cleanup ResourceWarnings remain unchanged.

### 2026-08-10 — SEC03 implementation CI

- Published reviewed implementation commit `e3eae01` and opened ready PR #51 referencing the 1.0
  umbrella issue without closing it.
- All four push/pull-request quality jobs passed on Python 3.10 and 3.14 without a CI-only fix; the
  PR is mergeable with a clean implementation diff.
- Recorded the evidence in this ledger. A final four-job matrix reruns on this documentation-only
  commit before the protected squash merge.

### 2026-08-10 — SEC03 merged; TUI01 started

- Observed all four final ledger jobs pass and squash-merged ready PR #51 as `feecf26`; verified
  exact `origin/main`, merged PR state, remote branch deletion, and preserved the unrelated root
  worktree files.
- Removed only the clean SEC03 temporary worktree and created isolated TUI01 from exact merge
  `feecf26`.
- Scoped TUI01 to a source-management stage shared by User and Maintainer, durable health/policy
  facts, immutable deferred requests, Backspace state, and one Finalize write boundary. Registry
  use remains optional, while TUI02 retains ownership of federated artifact consumption.

### 2026-08-10 — TUI01 Red, Green, review, and local gates

- Confirmed Red through the missing source-stage values/module and missing User/Maintainer wizard
  transition before implementing the recommended/direct/no-source, enable/disable/default,
  health, policy, and text/curses Backspace contracts.
- Added pure frozen source rows, selections, operations, and deferred requests. They distinguish
  registry/direct/local origin; current/stale/offline/invalid/incompatible/missing/disabled health;
  required/recommended/default state; and exact locally policy-derived company review without
  exposing Git credentials or trusting aliases/source claims.
- Added Sources after Role in both frontends. Navigation retains selections and cursor/scroll;
  explicit legacy catalog arguments never modify global configuration; first-run fallback remains
  visible only for a genuinely absent user configuration; no registry is forced; configuration is
  written only after the final reviewed action and artifact dispatch is blocked on save failure.
- Kept the TUI01-to-TUI02 migration boundary explicit: the existing consumer bridge accepts one
  local source or one `github.com` direct source on `main`; registry, multi-source, other-host, and
  other-ref consumption fail visibly until TUI02 supplies the federated marketplace view.
- Applied the repository `code-review` skill. Review found that a policy reporting overlay could be
  accidentally persisted while toggling a source. The application load result now exposes the raw
  user configuration separately from its effective policy projection; planning validates policy
  but stores and writes only exact user values. A regression proves reporting locks are not copied
  into the user document. No open review findings remain.
- Verified 45 focused source/wizard tests and 138 discovered TUI tests. New-context branch coverage
  is 96.45% for source-stage values and 100% for the finalizer. `make quality` passes Ruff format on
  356 files, Ruff lint, mypy on 166 source files, 1423 unit tests, 28 integration tests, the 11-step
  shell E2E, stdlib-only validation, 86.26% overall branch coverage, `1.0.0a1` wheel/import, docs,
  and repository non-mutation.
- The first Python 3.14.6 full-wrapper attempt stopped before tests because that interpreter lacks
  the optional Ruff package; no global dependency was installed. Its targeted run then passed all
  1423 tests and 28 integration tests but direct-script validation initially lacked an editable
  package import. With the repository supplied explicitly through `PYTHONPATH`, validation,
  version, packaging, and docs passed. The isolated CI matrix supplies the full developer-tool
  proof on Python 3.10 and 3.14.

### 2026-08-10 — TUI01 initial CI format fix

- Published implementation commit `041e551` plus local-gate ledger commit `37c4b16`, and opened
  ready PR #52 referencing the 1.0 umbrella issue without closing it.
- Both Python 3.10/3.14 push jobs and both pull-request jobs stopped at the same format check before
  tests: CI resolved Ruff 0.16.2 while the canonical local environment uses Ruff 0.12.2, and the
  newer formatter parenthesizes two multiline test lambdas differently.
- Applied only the mechanical formatter delta reported by CI. The focused 23-test source-stage
  module passes, and all 356 files now pass format/lint under both Ruff 0.12.2 and exact 0.16.2 in a
  temporary isolated environment.
- The next matrix passed format, lint, and type checking, then exposed three runtime-context test
  failures caused by ambient GitHub-runner `XDG_*` values. The tests wrote beneath their temporary
  home defaults while the production resolver correctly honored XDG, so they observed an empty
  first-run configuration. The fixture now pins config/data/cache XDG roots to the same temporary
  home layout, preserving real path semantics and preventing host-environment leakage. A new
  replacement four-job matrix reruns on this hermetic test fix.

### 2026-08-10 — TUI01 implementation CI

- All four replacement push/pull-request quality jobs passed on Python 3.10 and 3.14 after the
  formatter and ambient-XDG test-isolation fixes; no product behavior changed in either CI fix.
- PR #52 is ready and mergeable with the complete implementation diff. This ledger commit records
  the remote evidence, and a final four-job matrix reruns before the protected squash merge.

### 2026-08-10 — TUI01 merged; TUI02 started

- Observed all four final ledger jobs pass and squash-merged ready PR #52 as `62cadb5`; verified
  exact `origin/main`, merged PR state, remote branch deletion, and preservation of the unrelated
  root-worktree files.
- Removed only the clean TUI01 temporary worktree and created isolated TUI02 from exact merge
  `62cadb5`.
- Scoped TUI02 to replacing the transitional one-source consumer bridge with the configured
  federated marketplace union, qualified collision handling, trust/security/effect evidence,
  persistent basket/review state, canonical install/lifecycle application requests, and complete
  terminal outcomes for both text and curses frontends.

### 2026-08-10 — TUI02 marketplace projection Red/Green slice

- Recorded the expected missing-module Red failure before adding the consumer projection.
- Added an IO-free qualified artifact row model joining marketplace source/trust evidence,
  per-harness compatibility, normalized security evidence, lifecycle state, deterministic filters,
  actual-mode preview, and qualified basket reconciliation.
- Passed the first five focused projection tests; canonical multi-item plans, setup queue,
  structured terminal outcomes, and text/curses integration remain intentionally uncommitted.

### 2026-08-10 — TUI02 canonical consumer application and frontends

- Added a frozen consumer request/review/outcome model and application facade over the canonical
  install, lifecycle, setup, marketplace, security, state, and CAS contexts. Multi-item Review is
  sequentially projected, binds exact qualified versions/digests/destinations/modes, and Finalize
  reuses typed domain plans rather than parsing command output.
- Replaced the User text/curses transitional bridge with the configured source union. Both
  frontends preserve qualified cart, cursor, scroll, and earlier wizard values across Back;
  finalize only after the source-selection write succeeds and after curses teardown.
- Added explicit no-op/succeeded/partial/failed outcomes with per-target counts and details, plus a
  separately authorized and reviewed sequential setup queue whose failures retain exact retry
  commands without rolling back successful payload installation.
- Runtime composition supports persisted or reviewed prospective source configuration, publishes
  native and registry-owned packages to the immutable store, rebinds registry coordinates without
  losing upstream provenance, and accepts optional security evidence only after exact registry,
  input-digest, document, attestation, and local-trust verification.

### 2026-08-10 — TUI02 review and local quality gates

- Applied the repository `code-review` skill. Review found that external artifacts were visible
  from `aart.index.json` but an empty CAS had no consumer acquisition path. The runtime now resolves
  only the selected external reference through its matching committed `aart.lock.json`, fetches the
  immutable locked commit under a managed source lock, validates the native package against lock
  and index, and atomically publishes the verified object. Browse remains fetch-free, cache hits do
  not fetch, offline cache misses are explicit, and registries containing references only are valid.
- Added fail-closed coverage for stale/missing lock/index evidence, mismatched registry identity,
  acquisition failure, offline cache miss, exact pinned Git request, cache reuse, and reference-only
  registries. No open review findings remain.
- Passed 36 focused consumer/marketplace/frontend tests and 167 discovered TUI/consumer tests.
  The final exact-tree `make quality` run passed Ruff format on 367 files, Ruff lint, mypy on 172
  source files, 1452 unit tests, 28 integration tests, the 11-step shell E2E, stdlib-only validation,
  86.26% overall branch coverage (87.98% across the focused consumer contexts), `1.0.0a1`
  wheel/import, docs, and repository non-mutation.

### 2026-08-10 — TUI02 initial CI platform-fixture fix

- Published implementation commit `703af53` and opened ready PR #53 referencing the 1.0 umbrella
  issue without closing it.
- All four push/pull-request Python 3.10/3.14 jobs passed format, lint, and type checking, then
  reported the same five User-flow test failures. The product correctly selected Linux on the
  GitHub runner while the synthetic canonical artifacts and macOS setup fixture declared only
  Darwin compatibility, so the wizard correctly disabled them before Review.
- Made those Darwin-specific frontend tests pin their intended simulated platform explicitly rather
  than inherit the host OS. The 12 affected text/curses tests pass both normally and when the outer
  test process is forced to report Linux; product platform detection remains unchanged.

### 2026-08-10 — TUI02 implementation CI

- All four replacement push/pull-request quality jobs passed on Python 3.10 and 3.14 after the
  platform-fixture fix; no product behavior changed in the CI correction.
- PR #53 is ready and mergeable with the reviewed implementation diff. This ledger commit records
  the remote evidence, and a final four-job matrix reruns before the protected squash merge.

### 2026-08-10 — TUI02 merged; TUI03 started

- Observed all four final ledger jobs pass and squash-merged ready PR #53 as `d37feb8`; verified
  exact `origin/main`, merged PR state, remote branch deletion, and preservation of the unrelated
  root-worktree files.
- Removed only the clean TUI02 temporary worktree and created isolated TUI03 from exact merge
  `d37feb8`.
- Scoped TUI03 to a canonical Maintainer application and wizard for local-checkout scaffold,
  promotion/import, upstream, lock/build/audit/security previews and structured outcomes. Finalize
  is the only apply boundary; the flow never commits, pushes, or mutates consumer managed stores.

### 2026-08-10 — TUI03 canonical curation Red/Green slices

- Recorded the expected missing `agent_artifacts.curation` package Red before production edits.
- Added immutable curation request/review/check/change/outcome values and deterministic renderers.
  The local runtime prepares exact registry workspace or registry-input plans, verifies an explicit
  writable Git checkout before every mutation preview, and finalizes only the displayed digest.
- Added canonical init/scaffold, approved native promotion, one-reference upstream refresh,
  controlled `legacy-catalog-v1` conversion with warnings, lock/build, validate, audit/security
  evidence, and read-only diff. Exact follow-up commands never commit or push, and a boundary test
  prevents consumer store/state writers from entering the runtime.
- Routed canonical/empty Git workspaces through the new text and curses Maintainer action path while
  preserving legacy catalogs unchanged. Back keeps entered values and reuses an unchanged prepared
  plan; detailed curses work starts after teardown; structured outcomes distinguish applied,
  no-op, read-only observed drift, and failed quality checks.
- The code-review skill identified four edge contracts before publication. Tightened native
  mutation Finalize against the complete displayed workspace snapshot (including unrelated managed
  workflow changes), rejected registry-entry identity/path mismatches, made recovery commands
  action-aware, and ensured canonical Maintainer-to-User transitions load the canonical consumer
  runtime in both text and curses paths. A final audit also preserved that exact loaded service
  across curses teardown and Finalize. Regression tests cover each case.
- Final local evidence: 57 focused tests pass with 91.19% curation model/runtime coverage; the full
  quality wrapper passes Ruff format/lint over 375 files, mypy over 175 source modules, 1472 unit
  tests, 29 integration tests, 11-step E2E, stdlib-only validation, 86.06% overall coverage,
  `1.0.0a1` packaging, and docs validation.
- Published ready and mergeable PR #54 from commit `98a0c93`; all four initial push/PR quality jobs
  passed on Python 3.10 and 3.14. This ledger update records that remote evidence and triggers the
  final matrix before the protected squash merge.

### 2026-08-10 — TUI03 merged; RPT01 started

- Observed all four final ledger jobs pass and squash-merged ready PR #54 as `7089147`; verified
  exact `origin/main`, merged PR state, remote branch deletion, and preservation of the unrelated
  root-worktree files.
- Removed only the clean TUI03 temporary worktree and created isolated RPT01 from exact merge
  `7089147`.
- Reconciled PLAN/PRD/SPEC with superseded issue #24: registry advertisements remain inert; an
  effective destination must be explicitly configured/policy-owned, report events omit source
  repositories/aliases, paths, logs, credentials, and user/machine identifiers, and GitHub issue
  bodies remain untrusted ingestion input.
- Added the first reporting model/schema/application contracts and recorded the expected missing
  `agent_artifacts.reporting` package Red before production edits.

### 2026-08-10 — RPT01 Red/Green, security review, and local gates

- Added a versioned, allowlisted usage-session event and strict untrusted issue-body parser. Events
  contain only artifact/profile/scope/mode/outcome categories, bounded setup installer digests, and
  coarse failure facts; paths, source aliases/repositories, logs, credentials, and user/machine
  identifiers cannot enter the model.
- Resolved reporting only from the explicit effective registry and its inert `usage_reporting`
  service advertisement. Disabled mode returns before source reads, prompts, queues, or network;
  provider or configuration failures are warnings and cannot alter consumer/setup exit status.
- Added separate consent-and-preview browser submission and opt-in authenticated `gh` submission.
  The browser prefill carries raw JSON for the Issue Form's `render: json` field, automatic mode
  never constructs a bounded browser URL, provider exceptions are redacted, and `gh` uses fixed
  argv, `shell=False`, stdin issue bodies, and host-specific authentication checks.
- Added registry-owned inert Issue Form plus validation and scheduled dashboard workflows, and
  offline CLI commands to validate events/issues and aggregate a bounded `body,createdAt` export
  into escaped static HTML and canonical JSON. Registry initialization does not activate a
  reporting destination; a maintainer must explicitly author a compatible service.
- The repository `code-review` pass captured and fixed browser field double-fencing, automatic-mode
  URL coupling, provider exception escape, unbounded slugs/codes/payloads, impossible timestamps,
  incomplete setup failure categories, a defensive setup-plan lookup, and premature form labeling
  that could have made an unvalidated issue look validated. Regression tests cover each externally
  observable contract; no open review findings remain.
- Final local evidence: 32 reporting-context tests and 71 cross-context reporting/TUI/CLI/registry
  tests pass. Noninteractive `make quality` passes Ruff format/lint over 395 files, mypy over 185
  source modules, 1506 unit tests, 29 integration tests, the 11-step shell E2E, stdlib-only runtime
  and version validation, 85.74% overall branch coverage, `1.0.0a1` wheel packaging, and docs.
  An intentionally PTY-bound trial shortened responsive TUI descriptions at 80 columns and failed
  two pre-existing full-width text assertions; the canonical non-PTY gate and all product tests pass.
- Initial PR #55 push/PR jobs reached only the format gate: CI Ruff 0.16.2 required parentheses
  around one multi-line test lambda that local Ruff 0.12.2 accepted. Applied the exact current-Ruff
  formatting with no product behavior change; replacement gate evidence follows after push.

### 2026-08-10 — RPT01 implementation CI passed

- Published implementation commit `d55d6cc`, opened ready and mergeable PR #55, and applied the
  format-only compatibility commit `10efd27` after diagnosing the initial Ruff 0.16.2 result from
  GitHub Actions logs.
- All four replacement push/pull-request quality jobs passed on Python 3.10 and 3.14. This ledger
  update records the remote evidence and triggers the final matrix before the protected squash
  merge; RPT01's complete status becomes authoritative only on `main`.

### 2026-08-10 — RPT01 merged; SEP01 started

- Observed all four final ledger jobs pass and squash-merged ready PR #55 as `716051e`; verified
  exact `origin/main`, merged PR state, remote branch deletion, and preservation of the unrelated
  root-worktree files.
- Created isolated SEP01 from exact merge `716051e`, reconfirmed authenticated GitHub owner `M1F1`,
  and confirmed that `M1F1/agent-artifacts-registry` does not exist before any remote mutation.
- A throwaway migration probe compiled all ten public legacy artifacts and both collections with
  canonical source-commit/input-digest provenance. Lock, build, strict frozen validation, registry
  compatibility tests, and audit ran successfully; audit correctly exposed absent per-artifact
  license declarations, so publication remains fail-closed while the Red/Green export contract is
  implemented.

### 2026-08-10 — SEP01 deterministic export and public audit Green slice

- Added an optional, digest-bound `--license` migration input and proved that `MIT` is emitted into
  every migrated artifact manifest without changing the legacy import default.
- Added a pure exact-tree public policy/audit plus a non-following bounded reader. The boundary
  fixes target/source identity, source commit/path/digest provenance, artifact/collection/license
  allowlists, repository metadata, and the exact CI bytes; it rejects credential signatures,
  private paths/endpoints, non-text content, unsafe/unexpected/generated paths, links, and special
  files.
- Added a source-only exporter that verifies the approved Git origin, resolves one exact commit,
  initializes fresh history, migrates/formats/locks/builds, runs strict frozen/audit/minimum/latest
  checks, and emits the audited tree digest without creating, committing, or pushing a remote.
- Recorded the expected missing-module/script Red, then passed 32 focused importer, registry,
  publication, packaging, and export tests. Two independent exports from exact commit `716051e`
  are byte-identical with ten artifacts and two collections; an isolated wheel contains no
  operational catalog and validates/tests/lists the registry from outside the tool checkout.
- The repository `code-review` pass tightened source-origin verification, bound the approved target
  into immutable metadata, made registry roots/CI bytes exact, and added before/open/after file
  identity checks to the publication reader. A spoofed checkout origin now fails before creating
  the destination. Focused branch coverage for the new publication boundary is 92.81%.

### 2026-08-10 — SEP01 local gates and public reference registry passed

- Final non-mutating local quality passes Ruff format/lint over 399 files, mypy over 186 source
  modules, 1519 unit tests, 31 Python integration tests, the 11-step shell E2E, stdlib/version
  validation, 85.83% overall branch coverage, `1.0.0a1` wheel packaging, and documentation checks.
- Generated the sole publishable candidate from committed source `716051e`: 51 files, ten
  artifacts, two collections, audit digest
  `sha256:bb35e1e55df8ef97bf7fff20957ab5e05aee4ee9d78a3721e4eb0327155bcf44`, and
  Git tree `2cdc3b5`. Created fresh history only; no tool-repository history or working-tree-only
  file crossed the boundary.
- Immediately before creation, reconfirmed authenticated owner `M1F1` and received HTTP 404 for
  the exact target. Created `https://github.com/M1F1/agent-artifacts-registry` with `PUBLIC`
  visibility and pushed sole root commit `004acd0`; GitHub reports owner `M1F1`, default branch
  `main`, the exact local commit/tree SHAs, and one-commit history.
- Registry Actions run `31415376543` passed both `minimum` and `latest` jobs. Each independently
  passed format-check, strict frozen validation, lock/build checks, audit, and its compatibility
  test against the tool's public `main`. Node-runtime deprecation annotations on upstream Actions
  are informational and did not alter either successful job result.

### 2026-08-10 — SEP01 tool CI compatibility correction

- Published implementation commit `ab7bbda` and opened ready PR #56. The initial push/PR matrices
  failed only in the new reference-export E2E fixture: Python 3.10 cannot directly run the
  repository's Python 3.11+ stdlib wheel builder, and GitHub's detached synthetic PR-merge commit
  was not reachable through a source ref when the exporter fetched the exact commit.
- Kept product and publication behavior unchanged. The E2E fixture now exposes checkout `HEAD`
  under an explicit local Git ref before exact-commit export and reuses the established
  cross-version packaging helper, which selects the stdlib builder on Python 3.11+ and the
  dependency-free `pip wheel --no-build-isolation` path on Python 3.10.
- The corrected focused E2E test passes. A fresh non-PTY `make quality` passes Ruff format/lint
  over 399 files, mypy over 186 source modules, 1519 unit tests, 31 integration tests, the
  11-step shell E2E, validation, 85.83% overall branch coverage (92.81% publication boundary),
  packaging, and docs. A diagnostic PTY run alone demonstrated the existing terminal-width
  truncation behavior in two TUI snapshot assertions; official local and CI gates run without PTY.
- The first replacement matrix then exposed GitHub Actions' shallow-checkout boundary: fetching
  detached `HEAD` into a fresh fixture warned that shallow roots could not be updated and left no
  `FETCH_HEAD`. The fixture now uses `--update-shallow` and a direct
  `HEAD:refs/heads/export` refspec. This exact operation succeeds against a local detached
  `--depth=1` clone, and both corrected reference-export E2E tests pass locally.

### 2026-08-10 — SEP01 implementation CI passed

- Published shallow-source correction `62c5ffe`; all four replacement push/pull-request quality
  jobs passed on Python 3.10 and 3.14 in Actions runs `31416477266` and `31416480846`.
- Together with public registry run `31415376543`, remote evidence now proves both the independent
  minimum/latest registry contract and the tool's supported Python matrix. This ledger update
  records that evidence and triggers the final tool matrix before protected squash merge; SEP01's
  complete status becomes authoritative only on `main`.

### 2026-08-10 — SEP01 merged; MIG01 started

- Observed all four final ledger jobs pass and squash-merged ready PR #56 as `0e63768`; verified
  exact `origin/main`, merged PR state, remote branch deletion, public registry visibility/default
  branch, and preservation of unrelated root-worktree files.
- Removed only the clean SEP01 temporary worktree/branch and created isolated MIG01 from exact merge
  `0e63768`. Existing STATE01 already supplies pure strict legacy planning plus an atomic local
  backup/apply/rollback adapter; MIG01 will expose the complete public workflow and bounded legacy
  command/config compatibility without reintroducing an embedded default catalog.

### 2026-08-10 — MIG01 compatibility migration and local gates complete

- Added first-class `aart migrate state --from 0.1` dry-run/apply/rollback orchestration. Migration
  resolves every legacy identity to exactly one enabled current source, supports explicit repeatable
  `--source-map TYPE/NAME@PROFILE=ALIAS`, inspects only validated destinations, and never labels
  retained legacy bytes as the current marketplace object.
- Added committed project/user 0.1 fixtures covering skill, guideline, MCP, hook, and memory effects,
  early manifests without install metadata, raw-file and legacy `repr(value)` hash verification,
  key/list merge conversion, local/Git/package-era source resolution, Copy and Symlink transitions,
  lifecycle status/update/uninstall, and exact rollback.
- Made migration recovery durable across processes and interruption points: deterministic collision
  suffixes, private backup before journal/destination writes, bounded no-follow receipt discovery,
  resume after journal or destination writes, mixed-state refusal during review, compensation, and
  rollback that does not load marketplace configuration. A colliding stale journal cannot hide the
  later valid suffixed receipt.
- The `code-review` pass found and fixed loose parsing before effect inspection, invalid legacy
  identity misclassification, dry-run acceptance of unrelated user v2 state, rollback coupling to
  current sources, ignored extra link metadata, and collision/receipt disagreement. Focused
  regressions capture every correction; legacy memory mode remains explicit `null` because 0.1 did
  not persist it, with in-place marker updates and the documented missing-block compatibility mode.
- Removed the package-embedded operational catalog default. Legacy `--source`/`--repo` command paths
  now require an explicit input and emit a compatibility warning; canonical marketplace behavior is
  not silently routed through the old adapter.
- Final local evidence: 84 focused tests plus 46 subtests pass. `make quality` passes Ruff format over
  404 files, Ruff lint, mypy over 188 source modules, 1545 unit tests, 35 Python integration tests,
  the 11-step shell E2E, strict validation/version checks, 85.58% overall branch coverage,
  `1.0.0a1` packaging, and documentation checks.

### 2026-08-10 — MIG01 implementation CI passed

- Published implementation commit `223a457` and opened ready PR #57. All four initial push and
  pull-request quality jobs passed on Python 3.10 and 3.14 in Actions runs `31420263209` and
  `31420310320`.
- This ledger update records the remote evidence and triggers the final matrix before protected
  squash merge; MIG01's complete status becomes authoritative only on `main`.

### 2026-08-10 — MIG01 merged; DIST01 started

- Observed all four final ledger jobs pass and squash-merged ready PR #57 as `e70ec62`; verified
  exact `origin/main`, merged PR state, remote branch deletion, and preservation of the unrelated
  root-worktree files.
- Removed only the clean MIG01 temporary worktree/branch and created isolated DIST01 from exact
  merge `e70ec62`. Distribution work remains local and hermetic: no Nexus/PyPI publication or real
  user home, index, credentials, registry, or network is in scope.

### 2026-08-10 — DIST01 implementation and local gates complete

- Replaced implicit remote self-update with an explicit typed local upgrade plan. Exactly one real
  wheel or checkout is required; fixed pip argv always contains `--no-index --no-deps`, editable
  mode disables build isolation, dry-run invokes no runner, and virtualenv `sys.executable` is kept
  intact rather than resolving through its symlink to a base interpreter.
- Added an independent wheel allowlist and packaging audit for normalized regular members, exact
  distribution identity, complete SHA-256/size-bound `RECORD`, zero unconditional runtime
  dependencies, and exclusion of operational artifact/registry content and symlinked package data.
- Added a hermetic editable-to-wheel lifecycle runner. From outside the checkout it syncs a native
  source, installs Copy and immutable-object Symlink targets, removes the editable environment,
  resumes status/uninstall/reinstall from the local wheel, removes that environment, and proves the
  managed link survives both removals without an index or real user paths.
- The lifecycle exposed and fixed a domain mismatch: source synchronization emits
  `local:<snapshot-sha256>`, while installation state accepted only legacy `local`. Both remain
  readable, and new synced installations retain snapshot-bound evidence.
- The `code-review` pass removed inherited `PYTHONPATH`/`PYTHONHOME` contamination from phase
  processes and added missing wheel `RECORD`, unsafe-member, and package-directory-symlink checks.
- The first push Python 3.14 job exposed that modern `venv` no longer bundles `setuptools`; the
  index-free editable smoke therefore could not import its declared build backend. Added
  `setuptools` explicitly to the development-only extra so CI supplies the build prerequisite to
  the isolated tool directory without adding a runtime dependency or enabling an index in smoke.
- Final local evidence: 86 focused tests pass. `make quality` passes Ruff format over 406 files,
  Ruff lint, mypy over 188 source modules, 1546 unit tests, 36 Python integration tests, the
  11-step shell E2E, strict validation/version checks, 85.54% overall branch coverage, hardened
  `1.0.0a1` packaging, and documentation checks.

### 2026-08-10 — DIST01 implementation CI passed

- Published implementation commit `0e2256f` and opened ready PR #58. The first push Python 3.14
  job in run `31422591436` reproduced the missing editable build-backend prerequisite; Python 3.10
  passed, and no runtime/package test failed before that boundary.
- Published focused correction `f8b7f9c`. All four replacement push and pull-request quality jobs
  passed on Python 3.10 and 3.14 in Actions runs `31422957299` and `31422960142`. This ledger update
  records that evidence and triggers the final matrix before protected squash merge.

### 2026-08-10 — DIST01 merged; E2E01 started

- Observed all four final Python 3.10/3.14 jobs pass in Actions runs `31423170240` and
  `31423177973`, then squash-merged ready PR #58 as `b05fd42`; verified the merged PR, exact
  `origin/main`, remote branch deletion, and preservation of unrelated root-worktree files.
- Removed only the clean DIST01 temporary worktree and created isolated E2E01 from exact merge
  `b05fd42`. Scoped the task to one auditable, hermetic runner over all thirteen named system and
  fault-injection scenarios, with isolated processes, bounded runtime, deterministic evidence,
  actionable recovery commands, and cleanup independent of the real home or credentials.

### 2026-08-10 — E2E01 Red

- Added the complete ordered scenario contract plus characterization coverage for a simultaneous
  public/company/team marketplace and concurrent reviewed installation convergence.
- Confirmed Red: the focused suite produced five expected `FileNotFoundError` failures because the
  system-matrix runner did not exist. The marketplace characterization also caught an invalid test
  assumption about the source projection field; the existing domain behavior itself remained
  unchanged, and the concurrent installation characterization already passed without lost state.

### 2026-08-10 — E2E01 Green, code review, and local gates

- Added a functional manifest and imperative runner for all thirteen required scenarios, covering
  eighteen exact acceptance tests. Every scenario gets a separate process, temporary HOME/TMP/XDG
  tree, credential-free minimal environment, loopback-refused HTTP configuration, Git prompt/global
  config isolation, a fixed timeout, deterministic typed receipt, and exact recovery command.
- Added real public/company/team federation and concurrent install convergence characterizations.
  The latter proves exactly one reviewed plan applies while its racing peer terminates safely, with
  one canonical state record and no partial or lost payload.
- Applied the repository `code-review` skill. The review simplified canonical scenario selection,
  retained path/time/output-free receipts, confirmed timeout/nonzero/runner failure redaction and
  cleanup, and clarified the external-network boundary in the operator documentation.
- Focused tests pass (8 top-level tests, including the complete 13-scenario/18-acceptance-test run),
  and `make system-matrix` reports 13/13 passed. `make quality` passes Ruff format over 410 files,
  Ruff lint, mypy over 188 source modules, 1553 unit tests, 39 Python integration tests, the 11-step
  shell E2E, validation/version checks, 85.56% branch coverage, hardened `1.0.0a1` packaging, and
  documentation checks.

### 2026-08-10 — E2E01 implementation CI passed

- Published implementation commit `f094eaf` and opened ready PR #59. All four initial push and
  pull-request quality jobs passed on Python 3.10 and 3.14 in Actions runs `31424301741` and
  `31424338373` without a CI-only correction.
- This ledger-only update records exact remote evidence and triggers the final protected-merge
  matrix; E2E01 becomes authoritative on `main` only after that matrix remains green.

### 2026-08-10 — E2E01 merged; REL01 started

- Observed all four final Python 3.10/3.14 jobs pass in Actions runs `31424577401` and
  `31424582462`, then squash-merged ready PR #59 as `5ae7310`; verified the merged PR, exact
  `origin/main`, remote branch deletion, and preservation of unrelated root-worktree files.
- Removed only the clean E2E01 worktree and created isolated REL01 from exact merge `5ae7310`.
  The public reference registry remains `PUBLIC` at the approved URL; its latest head `004acd0`
  has green registry CI run `31415376543`, and current AART main passes format/strict frozen
  validate/lock/build/audit/minimum+latest checks against a clean clone without modifying it.

### 2026-08-10 — REL01 Red

- Added release contracts for exact prerelease-to-stable finalization, complete progress, version
  agreement, required migration/release documents, schema-freeze freshness, clean generated state,
  approved registry origin, distinct registry compatibility/lock/index failures, redacted receipts,
  tag-workflow parity, and a fresh exported-registry end-to-end release check.
- Confirmed Red with five expected missing `scripts/release.py` failures, one absent version
  finalization API error, one absent tag-workflow gate failure, and the expected assertion that the
  repository was still `1.0.0a1` rather than stable `1.0.0`.

### 2026-08-10 — REL01 review hardening

- Independent review found that an unapproved or mutable registry could be reported as compatible,
  and that tag workflow provenance did not prove the source was already merged into `main`.
  New Red contracts now require a clean registry whose `HEAD` equals fetched `origin/HEAD`, suppress
  all downstream registry claims on provenance failure, record the accepted registry commit, check
  source/registry cleanliness before and after gates, and require the release source/tag commit to
  be an ancestor of fetched `origin/main`.
- The tag workflow now fetches `main` explicitly and checks tag ancestry before the release command.
  Focused release/version/workflow/export suite: 23 pass. Full local quality passed: 414 formatted
  files, Ruff, 188-source mypy, 1565 unit, 40 integration, 11-step E2E, strict validation,
  85.62% coverage, `1.0.0` wheel/import, and docs. PR CI evidence follows after the hardened
  changes are included in the release branch.
- The complete release receipt also passed against the clean approved public reference registry at
  `004acd06e51d63905ce12313e0c514c1a05913bd` with every source/registry/schema/system/package
  control green. This pre-merge evidence intentionally disables only the `origin/main` ancestry and
  source-clean checks; the CLI/tag workflow enforces both after the reviewed branch is merged.

### 2026-08-10 — REL01 final review correction

- Final review identified that a stale local `origin/HEAD` could still look pinned. The checker now
  compares the local revision with the live `git ls-remote --symref origin HEAD` advertisement before
  and after registry gates; a stale remote ref blocks all downstream registry claims. A focused Red
  test proves the failure path. The `v1.0.0` workflow trigger is deliberately exact because the
  release command/docs are a fixed 1.0.0 contract; later stable versions require a new contract.
- The hardened focused suite now has 24 passing tests. The final full local quality rerun passed:
  414 formatted files, Ruff, 188-source mypy, 1566 unit, 40 integration, 11-step E2E, strict
  validation, 85.62% coverage, `1.0.0` wheel/RECORD/import, and docs.
- Reran the real pre-merge receipt after remote-freshness hardening: the clean reference checkout,
  its fetched `origin/HEAD`, and the live advertised default head all resolve to
  `004acd06e51d63905ce12313e0c514c1a05913bd`; all eleven receipt controls pass.

### 2026-08-10 — REL01 initial CI passed

- Published `f2791ea` and opened ready PR [#60](https://github.com/M1F1/agent-artifacts/pull/60).
  All four initial push/pull-request quality jobs passed on Python 3.10 and 3.14 in Actions runs
  `31431386048` and `31431428569`; the Node.js runtime deprecation annotations are informational.
- This ledger-only update records the remote evidence and triggers the final protected-merge
  matrix. The release becomes authoritative only after that matrix is green and the reviewed PR is
  squash-merged into `main`.

### 2026-08-13 — canonical remediation WP-1..WP-6; 2.0.0 release contract

- Retired the legacy plan/merge/execute engine (`planners.py`, `merge.py`, `executor.py`) and their
  tests. Nothing imported them after the legacy CLI/TUI branch went; only their own tests kept them
  alive. The two pure helpers whose edges they were the last cover of — `_render_template` and
  `_descend` — gained direct tests against the canonical implementations.
- **Version decision: 2.0.0, not 1.5.0.** The remediation removes nine top-level commands, which is
  exactly the criterion `compatibility-v7.md` cited when it argued `1.4.0` was minor. A minor would
  have told a `1.4.0` user the upgrade was safe and then taken half their CLI. The v7 note warned
  that an executable major invalidates every artifact declaring the conventional `max_exclusive:
  "2.0.0"`; that disruption is accepted here rather than deferred, and both registries re-author
  their windows as part of the same change.
- Restored two pieces of released evidence the branch had damaged. `schema-freeze-v7.json` had been
  rewritten in place while still naming `"release_version":"1.4.0"`, silently replacing a shipped
  release's frozen contract; it is back to its `v1.4.0` bytes and `2.0.0` has its own v8 freeze.
  `migration-v1.md`, which the release check requires and which the `migrate` removal deleted, is
  restored and marked historical.
- **`1.4.0` shipped an unsatisfiable migration**, and this is the finding that connects the rest.
  It required a package-root `SETUP.md` for setup v2 while its own package validation refused any
  file at that path, so following its documented migration produced a registry `1.4.0` itself
  rejected with `unexpected canonical package path: SETUP.md`. Verified directly against the
  released tag. `2.0.0` allows the file, so publication and consumption agree on one rule — which
  also means no released `1.x` can validate either migrated registry.
- Two version literals went stale the moment the major landed, both the same defect this branch had
  already fixed once for the version flags: `registry init` floored its window at the running
  release but kept a literal `2.0.0` ceiling, so on `2.0.0` floor met ceiling and every init was
  refused; and the test suite hardcoded `1.0.0` as the executable version with "needs a newer AART"
  spelled `2.0.0`. Both now derive from the running release.
- WP-6, `M1F1/agent-artifacts-registry-2`: window raised to `>= 2.0.0, < 3.0.0`, CI repinned from
  `v1.3.1` to `v2.0.0`, and the `mcp/github-docker` manual route replaced by the full end-to-end
  guide written during live acceptance, which had been sitting uncommitted in a working tree since
  the run. Format, strict frozen validate, lock, build, audit, and both compatibility points pass.
- WP-6, `M1F1/agent-artifacts-registry`: same window and CI move. `skill/author-aart-installer` was
  still teaching the retired setup revision — its authoring schema and template pinned `const: 1`,
  its reference documented protocol v1, and its workflow never said where `SETUP.md` goes — so an
  author following it produced a recipe AART has refused since `1.4.0`. All four migrated to v2.
  Stale `--latest-version 1.1.1` pins dropped rather than renumbered. All gates pass.
- Cleared the acceptance run's probe residue from the `agent-artifacts-registry-2` main checkout: a
  consumer installation (`.agent-artifacts/manifest.json`, `.mcp.json`, `.tabnine/`) performed into
  the registry checkout itself, plus the uncommitted index/lock drift.
- Local gates: `make quality` green — format, lint, mypy, 1136 unit tests, integration, validate,
  83.00% branch coverage (threshold 82), `2.0.0` packaging, docs. `make release-check` fails only on
  the expected publication-ordering controls: the registry checkouts are on unpublished branches and
  the release source is not yet merged into `origin/main`. Nothing is pushed.

### 2026-08-13 — 2.0.0 released; both registries published; consumer project created

- **`v2.0.0` is released.** Tag `eb82f5c`, GitHub release *AART 2.0.0* with the reviewed
  `docs/release/github-release-v2.0.0.md` notes and `agent_artifacts-2.0.0-py3-none-any.whl`
  (461 668 bytes) attached by the release workflow.
- The release gate is circular by design and was resolved in the recorded order. The `release` job
  clones `M1F1/agent-artifacts-registry` and runs the full checklist against it, so the tagged run
  failed on `registry-validate/build/audit/compatibility` while main still carried `1.x` content.
  Tag first, publish Registry A, re-run the gate: green, then publish the release itself.
- **Both WP-6 branches had to be redone.** `origin/main` of each registry had been force-replaced
  during the live acceptance run (`4386ac0` Registry A, `7e347a6` Registry B), so the branches
  described in the previous entry targeted artifacts main no longer has. Both PRs were closed with
  that explanation and the work redone against the current content. What the previous entry says
  about `skill/author-aart-installer` and the `github-docker` end-to-end manual is a record of that
  superseded branch, not of what is published.
- **Registry A** ([#5](https://github.com/M1F1/agent-artifacts-registry/pull/5), `319fe35`): the
  three Docker MCP recipes migrated to setup v2 with `SETUP.md` at the package root, window raised
  to `>= 2.0.0, < 3.0.0`, CI repinned from `main` to `v2.0.0`. Two content defects surfaced on the
  way. `hook/la-guard` shipped `payload/hook.json` as literally `{}` — published, installable, and
  inert; the `2.0.0` compiler refuses it before publication, and it now carries a real PreToolUse
  guard. The `github-enterprise-docker` manual told the reader to add `agent-artifacts-registry-2`
  as the source for an artifact that lives in `agent-artifacts-registry`.
- **Registry B** ([#4](https://github.com/M1F1/agent-artifacts-registry-2/pull/4), `b7b7d6f`):
  closes WP-5 on the registry side. The nine `residual-0*` stages and three `residual-run-*` drivers
  declare `requires: skill/using-residues >= 1.0.0, < 2.0.0`; until now the kernel dependency lived
  in prose and in a sibling path lookup that failed at first use. `requires` is an unknown field to
  every released `1.x` parser, so the window is `>= 2.0.0, < 3.0.0` and all three workflows pin
  `v2.0.0`.
- **Consumer project created:**
  [`M1F1/agent-artifacts-live-acceptance-project`](https://github.com/M1F1/agent-artifacts-live-acceptance-project).
  Eleven installations from both registries covering all five artifact kinds, written by the
  released wheel at project scope for `claude` in copy mode and committed exactly as AART wrote
  them. Ten were requested — `skill/using-residues` is the eleventh, pulled in by the declared
  dependency, which is design §6 acceptance criterion 6 proven on published content rather than on a
  fixture. CI installs the released wheel, configures both sources from scratch, and fails on any
  installation that is not `current` or any file the run changed.
- Not yet done: WP-7's full agent-driven acceptance matrix, and the human-gated curses, real-home,
  and MCP credential passes.

### 2026-08-13 — source subscription lifecycle; 2.1.0 release contract

- **`aart source remove` and `aart source resubscribe`**
  ([#78](https://github.com/M1F1/agent-artifacts/pull/78), `ca6c1bb`) close the dead end live
  acceptance recorded as `LAF-28`: a registry that changed its declared `source_id` at an unchanged
  origin and ref could not be left, refreshed, re-added, or adopted. Design and plan in
  `docs/design/DESIGN-source-subscription-lifecycle.md` and
  `docs/plan/PLAN-source-subscription-lifecycle.md`; SL-1..SL-7 all landed.
- The second trap was the one that mattered: editing `config.json` alone was never enough, because
  the identity check reads the managed snapshot store, which is keyed by origin rather than by
  alias. `remove` therefore owns both, and discards the store *before* writing the configuration, so
  an interrupted removal leaves a subscription `sync` repairs rather than an unsubscribed origin
  whose store still binds an unreachable identity.
- Adoption authorizes a **transition**, not a destination. `SourceIdentityTransition` carries both
  identities, both revisions, and both digests; finalize re-reads the origin and applies that exact
  move or refuses. Resubscribing writes no configuration at all, which is why alias, kind, location,
  ref, and the default-registry flag survive by construction.
- Nothing was loosened. `sync` still refuses a changed identity; what changed is that the refusal
  now names a command that exists. `tests/source_remediation_test.py` feeds every ``aart …`` string
  found in real production refusals to `cli.build_parser()`, with a negative control, so the text
  cannot drift back.
- **Version decision: 2.1.0, not 2.0.1.** Two public subcommands are added, which is a SemVer minor
  by the same criterion `compatibility-v7.md` stated and `2.0.0` deliberately failed. Contract v9:
  `schema-freeze-v9.json` is byte-identical to v8 in every declared input and in every protocol
  version — only `release_version` differs, which is the machine-checked statement that no boundary
  moved.
- **No registry precondition.** Unlike `2.0.0`, nothing needs re-authoring first: a registry on
  `>= 2.0.0, < 3.0.0` passes `registry test --compatibility all --latest-version 2.1.0` unchanged,
  so executable and registries can be released in either order.

### 2026-08-13 — live acceptance v2 against released 2.1.0

- **`v2.1.0` is released.** Tag `3aff63d`, GitHub release *AART 2.1.0*, wheel attached by the release
  workflow. `make release-check` passed from merged `main` against a clean `origin/HEAD` checkout of
  Registry A — including `registry-compatibility`, which is the machine-checked form of "no registry
  precondition".
- **Second live acceptance run executed** against the released wheel (downloaded release asset, not a
  local build): [docs/testing/PROGRESS-live-acceptance-v2.md](docs/testing/PROGRESS-live-acceptance-v2.md).
  Ten new stressors (`LAS-31`..`LAS-40`), 26 scenarios, 13 findings, agent scope complete.
- **Three of v1's four consumer majors are fixed**, verified by re-applying the original stressors:
  the bare-`update` crash (`LAF-20`), `status` never reporting an available update (`LAF-25`), and
  `update --prune` removing nothing (`LAF-26`). `LAF-17` teardown litter persists. `LAF-16` is now
  root-caused: `_plan_review_value` includes `source_age_seconds`, so the consent digest is a clock.
- **The criticality finding is `LAF-33`**, and it lands on the feature this release shipped: after
  `source resubscribe` adopts a new identity, every artifact installed under the old one reports
  `source-unavailable` permanently, because the installation record pins `declared_id` and nothing
  rebinds it. The resubscription review promises the opposite.
- **Four attractors** organise the set: a missing subscription reported as a missing artifact;
  identity pinned in four places of which two are maintained; remediation that exists in the envelope
  but not on the operator's path; and review-first binding a process rather than a decision.
- **Composed response written**, four changes for eleven residues:
  [DESIGN-subscription-identity-binding.md](docs/design/DESIGN-subscription-identity-binding.md) and
  [PLAN-subscription-identity-binding.md](docs/plan/PLAN-subscription-identity-binding.md) (SI-1..SI-7,
  shaped as a `2.2.0` minor). Three `question` findings are deliberately left to a maintainer
  decision rather than folded into the plan.
- Positive results kept in the record: the removal ordering invariant survives a deleted store,
  `2.0.0` ↔ `2.1.0` data roots interoperate in both directions with no migration, concurrent source
  operations are safe, and both new Sources actions drive correctly through the text front-end.
- Still human-gated, unchanged: the curses passes and the MCP credential pass.

### 2026-08-14 — subscription identity binding; 2.2.0 release contract

- **`SI-1`..`SI-9` all landed**, closing nine of live acceptance v2's thirteen residues. Design and
  plan in `docs/design/DESIGN-subscription-identity-binding.md` and
  `docs/plan/PLAN-subscription-identity-binding.md`; each package's section records what the plan
  did not anticipate, which is where the interesting part of this release is written down.
- **The criticality finding `LAF-33` is closed by splitting one value in two.** An installation
  record conflated the subscription it resolves through with the identity that subscription's origin
  declared. Split apart, an intact subscription declaring a different identity is `identity-changed`,
  and `marketplace update` rebinds the record in the project that owns it — never from the source
  command, which cannot know which projects exist.
- **Review-first now binds a decision rather than a process.** `--expect` was only possible once the
  review digest stopped being a clock (`LAF-16`/`LAF-35`), which is why `SI-1` ran first.
- **The remediation guard grew past `Diagnostic`.** Every user-visible `aart …` mention in the
  package is parsed by the real CLI parser, and the compatibility tables' removal records are what
  make a removed command legible to it — so a release document is part of a test gate.
- **Two residues were closed by deleting litter rather than adding code:** teardown reclaims what it
  emptied (`LAF-17`, failed by hand in both live acceptance runs), and the wheel reproduces from the
  tagged commit rather than the build clock (`LAF-30`).
- **Four residues are deliberately open**, each recorded against the package that will own it:
  `marketplace status` under a removed sole subscription, a malformed `aart-registry.json` skipping
  the identity comparison, no CLI surface reversing a completed setup, and a promoted artifact not
  being a `requires` target — which `2.3.0` answers with `registry vendor`.
- **Contract v10.** `schema-freeze-v10.json` carries protocol versions identical to v9 and differs in
  two inputs, neither a parsed field: the text of a rendered command, and a protocol document
  section stating a rule the compiler already enforced. No registry precondition.
- Still human-gated, unchanged: the curses passes, the MCP credential pass, and the publication
  itself.

### 2026-08-14 — registry vendoring; 2.3.0 release contract

- **`VN-1`..`VN-9` all landed.** Design and plan in `docs/design/DESIGN-registry-vendoring.md` and
  `docs/plan/PLAN-registry-vendoring.md`; each package's section records what the plan did not
  anticipate, which is again where the interesting part of the release is written down.
- **The residue is closed by making content owned, not by loosening a rule.** `requires` still
  resolves only against packages the registry owns; `registry vendor` gives a maintainer a way to
  own foreign content, so the dependency rule needed no change at all.
- **No protocol revision, and that is the design claim.** A vendored artifact is an ordinary owned
  package carrying `provenance.json`; the two facts re-vendoring needs ride in the namespaced
  `aart.vendor` extension, verified against `importer.options_digest`. `schema-freeze-v11.json`
  carries protocol versions identical to v10 and differs in exactly two inputs, both protocol prose.
- **A successful vendor is a report, not a certificate.** The assessment covers the exact bytes that
  would be written — the maintainer's authored wrapper as much as the copied payload — findings do
  not block the action, and the review says in words that the registry is now the distributor.
- **`unreachable` is not `up-to-date`.** The one reading design §6 forbids is an upstream that could
  not be read counting as agreement; `revendor --check` exits non-zero for it, and
  `registry audit --check-upstream` reports it as unknown rather than as drift.
- **One module was deleted for what it promised rather than what it did.** `io/net.py` read
  `GITHUB_TOKEN`; AART holds no credentials and runs system Git. The `validate` gate now refuses the
  names, so the promise cannot return by accident.
- **Three residues are open and owned by nobody**, recorded in the plan: `io/cache.py` is now
  unreferenced by shipping code, `docs/design/DESIGN-upstream.md` carries no superseded banner, and
  `commands/registry.py` stamps dead `1.0.0`/`2.0.0` AART bounds on every non-`init` request.
- Still human-gated, unchanged: the curses passes and the MCP credential pass.

### 2026-08-15 — post-release verification of Registry B and the consumer project

- **The upgrade obligation is narrower than the release wrote it, and its cost is wider.** Registry B
  (`la-registry-b`) owns no setup-bearing package, so the vocabulary boundary never reaches its
  index: `registry build` under `2.5.0` reports `unchanged: aart.index.json`, and the committed index
  passes `validate --strict --frozen` under `2.0.0` *and* `2.5.0`. "Valid on one side or the other,
  never both" holds for an index that carries a recipe, not for every index. Only the CI pin moved
  ([registry-2#5](https://github.com/M1F1/agent-artifacts-registry-2/pull/5)); all seven gates of its
  quality workflow pass under `2.5.0` against the unchanged index.
- **`LAF-62`: a `≤2.4.0` consumer cannot add a rebuilt registry.** Severity: major; owned by nobody.
  `source add --kind registry-git` against rebuilt Registry A exits 1 with `compiled index disagrees
  with owned package` for `mcp/github-docker`, `mcp/github-enterprise-docker`, and
  `mcp/postgres-docker`, under both `2.0.0` and `2.4.0` (the latter run from a worktree at `v2.4.0`).
  It fails before any artifact is named, so nothing downstream is reachable. Reproduction: any clean
  home, `aart source add --alias registry-a --kind registry-git --location
  https://github.com/M1F1/agent-artifacts-registry.git --ref main`.
- **What that falsifies.** `SBC-10` and the rebuild commit both recorded that consumers are untouched
  either way, and named the `2.4.0` consumer specifically as adding the registry "exactly as before".
  The reasoning was that a consumer recompiles the index from the source snapshot and never reads the
  committed one; publishing that snapshot evidently validates the committed index first. The design
  claim may still be right about *installing* — it is wrong about *subscribing*, which is the step
  that comes first.
- **It was already failing in production, unobserved for a day.** The consumer project's nightly
  acceptance run failed at 2026-08-15 05:46 UTC with exactly those three lines; the last green run was
  2026-08-14 06:49 UTC, before the rebuild merged at 21:26. Between those two timestamps the
  reconciliation this workflow exists to perform had silently stopped happening. A registry-side
  release step and a consumer-side pin are one obligation, and only half of it was written down.
- **The installation state itself never moved.** Every step of the consumer workflow replayed locally
  under `2.5.0` against an isolated home: both sources `healthy`, `marketplace status` `ok` with 11
  of 11 `current`, `git diff --exit-code` clean. The runner's pin moved to `2.5.0`
  ([project#1](https://github.com/M1F1/agent-artifacts-live-acceptance-project/pull/1)); nothing was
  reinstalled, because nothing needed to be.
- **Open, and deliberately not fixed here:** `LAF-62` itself. Whether `source add` should validate a
  committed index at all is a design question — the snapshot it publishes is recompiled either way —
  and answering it inside a cleanup pass would be the wrong place to decide it.

### 2026-08-15 — an upstream repository, and vendoring two subtrees out of it

The constellation had a gap the acceptance runs kept papering over: every artifact in both
registries was authored inside the registry that publishes it. `aart registry vendor` existed,
was tested, and was documented against a fictional upstream. Nothing had ever been vendored from a
repository that did not know AART existed — which is precisely the case a company registry faces.

- **The upstream is deliberately ordinary.**
  [`agent-artifacts-upstream`](https://github.com/M1F1/agent-artifacts-upstream) at `v1.0.0`:
  `README.md`, `LICENSE`, and two subtrees under `packages/`. No `aart-source.json`, no
  `artifact.json`, no build, no release process beyond `git tag`. It is what the tutorial describes
  and what a GitHub Enterprise repository looks like from the outside.
- **Two subtrees, chosen for the two licence routes.** `packages/release-evidence` carries its own
  `LICENSE` and `vendor-license` **discovered** `MIT` by reading it; `packages/branch-conventions`
  carries none, and the identifier had to be **stated** with `--license MIT`. Both routes are now
  exercised by something other than a test fixture.
- **Both are pinned to a commit, not a ref.** `3706c2a5a679f17a3c3d4979b840fa86bc2a13e5` is what
  `v1.0.0` meant at the moment of vendoring; `provenance.json` keeps the ref beside it so `revendor`
  knows which moving name to re-resolve. The four `vendor-*` checks passed and the three standing
  warnings were read rather than skipped: a successful vendor reports what was copied and claims
  nothing about whether copying it was wise.
- **The copy was checked by consuming it, not by trusting the review.** A scratch project added the
  registry as a `source-local` source and installed both:
  `.claude/skills/release-evidence/{SKILL.md,LICENSE,references/verification-checklist.md}` and
  `.claude/guidelines/branch-conventions.md`. A skill delivers its tree; a guideline delivers one
  managed file. `lock`, `build`, `audit` and `validate --strict --frozen` are green with the two new
  packages in the index ([registry#9](https://github.com/M1F1/agent-artifacts-registry/pull/9)).
- **`LAF-71` closes here.** Registry A's three workflows still gated at `v2.5.0` — the half of the
  finding that had no PR while Registry B and the consumer had both moved
  ([registry#10](https://github.com/M1F1/agent-artifacts-registry/pull/10)). No index rebuild:
  `2.6.0` changes the setup engine and the redactor, not the registry contract.
- **No new findings.** Nine commands ran across two repositories and everything refused what it
  should and accepted what it should. That is worth recording precisely because the previous two live
  passes each produced five, and a run that finds nothing is only evidence when the run was real.

### 2026-08-16 — overnight residue run, `LAF-75`

Branch `fix/wheel-digest-emits-what-it-hashes-laf75`, cut from `main`, not pushed. One work package.

- **The defect is one of evidence.** `python scripts/release.py wheel-digest` built the publishable
  wheel in a temporary directory, printed its digest, and deleted it. The publisher then had to
  produce the attachment some other way, and the obvious way — `python scripts/build_wheel.py` —
  builds a **different file under the same name**, because a build from the checkout carries no
  commit stamp. `2.6.0` came within one `curl` of publishing a digest line that did not describe its
  own attachment.
- **The fix hands over the artifact.** `wheel-digest` now writes the wheel into `dist/`, or into
  `--output <dir>`, and reads the digest back **from the written file**, so the first printed line
  describes the file named on the second. A copy that arrived short cannot be described by the
  digest of the file it was copied from.
- **Walked live, both sides, one machine** — [`PROGRESS-live-acceptance-v5.md`](docs/testing/PROGRESS-live-acceptance-v5.md),
  scenarios `LA-0-07`..`LA-0-10`, stressor `LAS-31`. On `main` the command printed `8ed1226d…` and
  left no `dist/`; the wheel a publisher then builds hashed `fcdf95d9…`. On the branch the printed
  `e552d473…` is the digest of the file in `dist/`, and that file installs into a clean venv,
  reports `agent-artifacts 2.6.0` and carries `COMMIT = 1c659a3…` where the other carries
  `unknown`. A stale unstamped wheel already sitting in `dist/` is replaced by the hashed one.
- **`LAF-75` closes.** `tests/release_test.py::WheelDigestArtifactTest` holds the property: the
  printed digest is the digest of the file left behind, the command names the path, the emitted
  wheel carries this commit, and the default destination is `dist/`.
- **Two findings recorded, not fixed.** `LAF-80`: `make wheel` rewrites the tracked
  `agent_artifacts/_commit.py` and no document says to restore it, so the verification route
  `wheel-reproducibility-v1.md` recommends leaves a dirty checkout. `LAF-81`: `wheel-digest` builds
  from the working tree while stamping `HEAD`, so on a dirty checkout it emits a wheel claiming a
  commit it does not contain — true before this change, and now durable as a file.
- **`release-checklist-v14.md` is left alone.** It is `2.6.0`'s dated evidence and its workaround
  paragraph was true when it shipped. The standing procedure lives in `wheel-reproducibility-v1.md`,
  which is where the new two-line output and the "attach the file it names" rule are recorded; the
  next checklist inherits from there.
