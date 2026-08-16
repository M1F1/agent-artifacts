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
- **Next task:** the overnight queue is empty and the run is on the brief's fallback — re-checking
  this register's own `closed` rows against the evidence each one names, oldest first, repairing
  nothing. All thirteen rows that were `closed` on `main` have now been re-checked once. Twelve
  reproduce — `LAF-55` only in its offline half — and **`LAF-71` does not: it is `open` again** and
  Registry B's CI is still on `v2.5.0`. That is the first thing to look at after `LAF-90`. The same
  method has now been turned on this run's own fourteen closures: thirteen reproduce, and `RS-07`'s
  row names a pytest selector that collects nothing, which is `LAF-93`. A second pass then read four
  rows' claims against what their evidence proves: three hold, and the containment test's `--json`
  channel is `LAF-94`. The same pass over the four live-walk rows found `LAF-95`: a long failing
  Docker instruction reaches the operator as a mid-word fragment. `LAF-66` then held against a real
  wheel, and the walk found `LAF-96`: `receipt verify`'s two record-wide claims print headlines that
  contradict their own detail. `LAF-97` is the last of them: the register gate reads 60 listed files
  and `CHANGELOG.md` is not one, so its `2.6.0` section still calls `LAF-63` shipped open. The second pass is now complete: every
  `closed` row has been re-run once and re-read once, and the third pass has begun on the `open` ones
  — where `LAF-57`'s explanation turns out to go stale the moment `RS-12` merges. That pass is now
  finished too, and so are the `visible` and `deferred` rows: every row in the register has been
  re-checked once. `LAF-62` is `deferred` with nothing recording that decision — `LAF-99`. **The
  register itself omits three findings from one walk's table, all three the closed ones — `LAF-101`,
  and two are `major`.** The audit then moved to the live-acceptance documents: the append-only rule
  holds, the scenario map does not (`LAF-102`), and **the `2.6.0` receipt walk names no commit and no
  digest for the wheel it says was unpatched — `LAF-103`.** Reading the register against the stream
  then found this run's own gap: **the fifteen findings `LAF-76`..`LAF-90`, filed in the first half of
  the night, are described in this file and have no register row** — including `LAF-90`, which the run
  log calls the most serious thing found. They have rows now, and writing them found the gap's price:
  **two findings were filed twice tonight** — `LAF-84` again as `LAF-91`, `LAF-82` again as
  `LAF-100` — which is the re-discovery this register exists to stop. See
  *Overnight
  run 2026-08-15 → 16* below for what is done and on which branch. `LAF-61` and
  the human-gated passes — the curses front-end and the MCP credential run — wait for the maintainer
- **Last updated:** 2026-08-16
- **Next task:** the human-gated passes — the curses front-end and the MCP credential run — plus the
  four findings this stream left open (`LAF-61`, `LAF-69`, `LAF-73`, `LAF-75`). An unattended pass
  over the register is running against the queue in the
  [overnight run](#2026-08-15--16--overnight-residue-run) at the bottom of this file; everything it
  produces sits on local branches, unpushed, for review
- **Last updated:** 2026-08-15
- **Next task:** the overnight residue run continues with the validation cluster (`RS-08`, then
  `RS-01`). See *Overnight
- **Next task:** the overnight residue run continues with `RS-01`, then `LAF-47`/`RS-10` (design
  note first, committed alone). See *Overnight

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

## Overnight run 2026-08-15 → 16

The morning summary. Every branch below is cut from `main`, none is pushed, and none depends on
another; they can be reviewed and merged in any order.

**Merging them is not free, and an earlier version of this paragraph said something false about it.**
It said to expect conflicts in `PROGRESS.md` and the register and to *take both sides*. Simulated in
full on `2026-08-16` — all fourteen `fix/` branches merged into `main` in sequence with `git
merge-tree`, no branch touched (row 49):

- **13 of the 14 conflict.** Only the first merge is clean, whichever one goes first.
- **Taking both sides corrupts the register.** The finished file holds **eleven finding ids twice,
  one row `open` and one row `closed`** — `LAF-45`, `LAF-47`, `LAF-49`, `LAF-64`, `LAF-73`, `RS-01`,
  `RS-02`, `RS-07`, `RS-08`, `RS-09`, `RS-10`. Resolve the register **one row per id**: the branch
  that changed a row wins that row, and rows it did not touch keep the side that has evidence in
  them.
- **It is not two files.** `docs/testing/live-acceptance-scenarios.md` conflicts 8 times, and
  **code conflicts twice** — `agent_artifacts/registry_commands/planning.py`, where `RS-02`, `RS-09`
  and `RS-04` all rewrite the same refusals.
- `PROGRESS.md` conflicts in all 13, always as appends at the end plus the table: keep both, one
  table.
another; they can be reviewed and merged in any order. `PROGRESS.md` and the register are touched by
each of them, so expect conflicts in those two files and take both sides.

| # | Item | Branch | State |
|---|---|---|---|
| 1 | `RS-12` — setup steps ran without `HOME`, so docker could not read `config.json` | `fix/setup-docker-credentials-rs12` | done, walked live (v4) |
| 2 | `LAF-64` — the scope selector returned two types | `fix/curses-install-scope-laf64` | done, headless part walked; curses skin human-gated |
| 3 | `LAF-75` — `wheel-digest` printed the digest of a wheel it deleted | `fix/wheel-digest-emits-what-it-hashes-laf75` | done, walked live (v5) |
| 4 | `LAF-69` — the register gate ran in one direction only | `fix/docs-check-both-directions-laf69` | done, replayed against the real documents |
| 5 | `LAF-73` — an old record still says there is no undo | `fix/receipt-verify-stale-rollback-laf73` | done, walked live (v6) |
| 6 | `RS-11`/`RS-13`/`RS-14`/`RS-15` — the recipe format is closed | `docs/recipe-format-options` | options note written, nothing implemented; all four stay `open` |
| 7 | `RS-09` — a refused `registry` command said nothing about what to do next | `fix/registry-refusals-carry-remediation-rs09` | done in two commits on one branch: refusals, then the `validate`/`audit` report findings. `RS-09` closes |
| 8 | `RS-07` — `status` refused to read the project once the last source was removed | `fix/status-names-the-missing-source-rs07` | done, walked live (v7). `RS-07` closes |
| 9 | `LAF-45` — a completed `--check-upstream` printed nothing, so success looked like a dropped flag | `fix/audit-upstream-says-it-checked-laf45` | done, walked live (v8). `LAF-45` closes |
| 10 | `RS-08` — a broken `aart-registry.json` skipped the identity check instead of failing it | `fix/broken-registry-descriptor-fails-rs08` | done, walked live (v9). `RS-08` closes |
| 11 | `RS-01` — an `mcp` package written by hand was never checked, only a vendored one | `fix/owned-mcp-descriptor-is-checked-rs01` | done, walked live (v10). `RS-01` closes |
| 12 | `LAF-47`/`RS-10` — uninstall leaves the merge file behind, emptied | `fix/uninstall-removes-the-file-it-made` | two commits: the design note alone, then the fix. Walked live (v11). Both close; the case the design names stays open as `LAF-89` |
| 13 | `RS-04` — `vendor` refused without naming `revendor`, the command that would work | `fix/vendor-refusal-names-revendor-rs04` | done. `RS-04` closes. No live walk: a reworded refusal, which the brief excludes |
| 14 | `RS-02` — every registry request carried a compatibility window from an AART that no longer runs | `fix/registry-requests-stop-stamping-dead-bounds-rs02` | done, walked live (v12). `RS-02` closes. The same literals in the curses wizard are a new finding, `LAF-90` |
| 15 | `LAF-49` — Git runs without `https_proxy` and nothing said so | `fix/document-the-git-environment-laf49` | done. `LAF-49` closes as the documentation gap it always was; no behaviour changed. No live walk — the brief excludes a document |
| 16 | Re-check of the register's own oldest `closed` rows — `LAF-52`, `LAF-53`, `LAF-54`, `LAF-55` | `docs/recheck-closed-register-rows` | three re-checked against a real wheel and all three still reproduce; `LAF-55`'s live half is human-gated. One new finding, `LAF-91` |
| 17 | Re-check continued — `LAF-59`, `LAF-63`, `LAF-65`, `LAF-66`, `LAF-72` | `docs/recheck-closed-register-rows-2` | all five reproduce, `LAF-59` against a real failing Docker build. No new findings. Cut from `main` but carries row 16's `PROGRESS.md` and register, because the two are one record |
| 18 | Re-check continued — `LAF-68`, `LAF-70`, `LAF-71`, `LAF-74` | `docs/recheck-closed-register-rows-3` | **`LAF-71` does not reproduce and is back to `open`.** The other three do. New finding `LAF-92`. Carries row 17's record forward for the same reason |
| 19 | Re-check of this run's own fourteen closures, on their thirteen branches | `docs/recheck-tonights-closures` | thirteen reproduce. **`RS-07`'s row names a pytest selector that collects nothing** — the fix is sound, the record is not. New finding `LAF-93`. Carries row 18's record forward |
| 20 | Second pass: do the closed rows' *claims* reach further than their evidence? `LAF-63`, `LAF-72`, `LAF-55`, `LAF-65` | `docs/recheck-closed-row-claims` | three hold. The containment test's channel-4 walk asserts against a payload it writes itself — new finding `LAF-94`, a coverage claim, not an exposure. Carries row 19's record forward |
| 21 | Second pass continued, on the four rows closed by a live walk — `LAF-52`, `LAF-53`, `LAF-54`, `LAF-59` | `docs/recheck-live-walk-claims` | three hold. A long failing Docker instruction is reported as a mid-word fragment and the word *ERROR* is truncated away — new finding `LAF-95`, measured on two real builds. Carries row 20's record forward |
| 22 | `LAF-66`'s claim taken to the CLI on a real wheel — does `verify` look where the engine writes? | `docs/recheck-remaining-closed-claims` | **it does**, measured with a planted working copy. But the command that proved it prints two claims whose headlines say the reverse of their own detail — new finding `LAF-96`. Carries row 21's record forward |
| 23 | `LAF-74`'s claim: does the register gate hold the documents, or the listed ones? | `docs/recheck-doc-gate-reach` | the listed ones — 60 files. `CHANGELOG.md` is outside it and its `2.6.0` section still lists `LAF-63` as shipped open, which `2.6.0` fixed. New finding `LAF-97`. Carries row 22's record forward |
| 24 | The last two `closed` rows read for width — `LAF-68`, `LAF-70` | `docs/recheck-acceptance-runner-claim` | both hold; the acceptance runner really did reconcile eleven installations this morning. It installs the published wheel without checking its digest — new finding `LAF-98`. **Second pass complete.** Carries row 23's record forward |
| 25 | Third pass: are the `open` rows still true as written? `LAF-57`, `LAF-67`, `RS-05`, `RS-06` | `docs/recheck-open-rows` | all four still true; each row now carries the check. **`LAF-57`'s explanation goes stale when `RS-12` merges** — one of its four causes is the missing `HOME` that branch fixes. `RS-05`'s dead module ships in the wheel. Carries row 24's record forward |
| 26 | Third pass finished — `LAF-58`, `RS-11`, `RS-13`, `RS-14`, `RS-15` | `docs/recheck-open-rows-2` | all five still true; each row now carries the check. `LAF-58`'s remedy is one flag on a call the code already makes. **All three passes complete.** Carries row 25's record forward |
| 27 | The two dispositions no pass covered — `LAF-61` (`visible`) and `LAF-62` (`deferred`) | `docs/recheck-visible-deferred` | `LAF-61` warranted and now measured live. **`LAF-62` is `deferred` and nothing records the decision** — the commit that filed it says *left open*. New finding `LAF-99`; disposition left standing, the call is yours. Carries row 26's record forward |
| 28 | The register audited against its own rules | `docs/audit-register-shape` | **it carries eight findings from one walk's table and omits three, all three of them the closed ones** — `LAF-101`, and two are `major`. Its opening also overstates what `docs_check` enforces — `LAF-100`. Carries row 27's record forward |
| 29 | The scenario map and run documents audited against their own rules | `docs/audit-live-acceptance-docs` | append-only holds — the map's only later commit deletes nothing. But two run documents use no scenario id and a third invents a whole `LAB-*` namespace: `LAF-102`. Carries row 28's record forward |
| 30 | The five run headers read by hand against the pinning rule | `docs/audit-run-headers` | two of five keep all four fields; `-v2.md`'s digest is 13 of 64 characters; **`-receipt.md` names no commit, no size, no digest and no version** while claiming an unpatched wheel built from the committed tree — `LAF-103`. Carries row 29's record forward |
| 31 | The register read against the stream, in the direction `DOC008` does not check | `docs/audit-register-vs-stream` | every stream id has a row; the *Scope* count is stale and names two origins where there are three — `LAF-104`. And the measurement found this run's own gap: **`LAF-76`..`LAF-90` are in this file and in no register row.** Carries row 30's record forward |
| 32 | The fifteen missing rows written | `docs/register-the-missing-fifteen` | `LAF-76`..`LAF-90` are in the register, `open`, each naming the branch it was found on. Writing them found **two findings filed twice** — `LAF-84`≡`LAF-91` and `LAF-82`≡`LAF-100` — which is the cost of the gap, measured. Carries row 31's record forward |
| 33 | The five new rows that code can settle re-checked | `docs/recheck-the-fifteen` | `LAF-76`, `LAF-77`, `LAF-78`, `LAF-79`, `LAF-86` all hold. **`LAF-79` is one worse** — three functions carry the shape, not two — and `LAF-76`/`LAF-77` describe a gap that only opens when `RS-12` merges. No new findings. Carries row 32's record forward |
| 34 | The two rows that needed a build — `LAF-80`, `LAF-81` | `docs/recheck-the-build-rows` | both hold, measured in a detached worktree. **`wheel-digest` prints a different digest for a dirty tree at the same `HEAD`**, exit `0`, no warning. `make wheel` leaves `_commit.py` modified and the standing procedure does not say so. The documented verification reproduces `wheel-digest` exactly — a pass. Carries row 33's record forward |
| 35 | `LAF-90` walked end to end against a locally built wheel | `docs/recheck-laf90-live` | **reproduces.** `registry init` with the wizard's own defaults exits `0` and the command it then advises, `registry validate`, exits `1` with no remediation. The control passes: the flag defaults are `2.6.0`/`3.0.0` and validate. `LA-0-11`, `LA-0-12`, `LAS-62`. Carries row 34's record forward |
| 36 | `LAF-88` and `LAF-89` re-walked on a branch-built wheel | `docs/recheck-laf88-89` | both hold; `LA-U-31` and `LA-U-35` re-executed, not re-numbered. **`v11`'s recorded wheel digest reproduces byte for byte** — the first run header in this repository to be re-derived. `LAF-89`'s severity corrected to `low` to match the walk that filed it. Carries row 35's record forward |
| 37 | `LAF-85` read from the real data root, read-only | `docs/recheck-laf85-data-root` | **the `23:34` episode removed objects rather than writing any** — 43 of 68 shards touched, no object born after `20:12` — then rewrote the reference index at `23:36`. Setup state and config untouched. **Nothing there has changed since; it has not recurred all night.** Writer still unidentified. Carries row 36's record forward |
| 38 | Which code could have produced the `23:34` trace | `docs/laf85-which-code-sweeps` | **the sweep reading was too strong** — install-then-uninstall leaves the same trace, and it is corrected here. The collector it named, `collect_garbage`, **has no caller in the package at all**: `LAF-105`, and the store therefore only grows — 79 objects against 34 references on this machine. Carries row 37's record forward |
| 39 | Is `LAF-105` alone? The whole application layer measured | `docs/unreachable-application-surface` | **eight of twenty-eight public functions in `application/` have no caller outside their own module and the tests** — including the entire compiler orchestration. Two are honest supersession, six are unwired. `LAF-106`. Carries row 38's record forward |
| 40 | `io/` and `store/` measured the same way, by reachability | `docs/unreachable-io-store` | **`store/` is clean, `io/` has 11** — the analyzer process runner, four `fs.py` helpers, `RS-05`'s module and the compiler adapter: `LAF-107`. The method was rebuilt to count same-module callers first; all eight of `LAF-106` survive it. Carries row 39's record forward |
| 41 | The whole package measured at once, by a script written from scratch | `docs/unreachable-whole-package` | **103 of 482 public functions are unreachable, a fifth of the surface.** The biggest cluster is `security/`, 15 of 39: the policy evaluator and the analyzer protocol have no path from any command — `LAF-15` generalised. Five root modules have no importer at all and all five ship. `LAF-108`, `LAF-109`; `LAF-03` gets the row the register's own rule owes it; **`LAF-107`'s count is corrected to 8**. `application/` re-derives `LAF-106`'s exact eight. Carries row 40's record forward |
| 42 | The unreachable surface read against the commands the wheel actually ships | `docs/designs-vs-unreachable` | **AART lists analyzers it cannot run** — `security analyzers` and `suites` advertise providers, no flag selects one, and the whole execution half is unreachable: `LAF-110`. Two of `LAF-106`'s eight turn out to be **bypassed wrappers** — `registry format` works by skipping the application layer the file next door uses: `LAF-111`. Three are doors the SPEC designs and the CLI has not got, `store gc` implemented to §16 exactly. `LAF-15` gets the row the register owed it. Carries row 41's record forward |
| 43 | Every leaf of the parser invoked cold, on the real wheel | `docs/cold-command-surface` | **38 of 38 refuse or answer cleanly, zero tracebacks** — 20 argparse, 13 typed refusals, 5 honest empty answers. `RS-09` reproduces on `main` from the other side, its fix being unmerged. The `registry` group refuses in two renderings: `LAF-112`. **`SPEC-aart-1.0.md` §20 misdescribes the shipped surface in both directions** — it understates the implemented slice and names four legacy commands that do not exist: `LAF-113`. `LAF-105`'s *38 subcommands* confirmed by enumeration. Carries row 42's record forward |
| 44 | The `--json` contract walked cold, the same way | `docs/json-contract-cold` | **34 of 38 leaves accept `--json` and every one returns valid JSON** with `schema_version`, `operation` and typed codes — the machine channel is healthier than the prose. `RS-09` shows up structurally as `remediation: []`, and `LAF-112`'s two renderings carry distinct codes, so that one is a prose problem only. **The group written for machines has no machine channel**: all three `reporting` leaves and `upgrade` lack `--json`, and an invalid report is refused with one unqualified sentence — `LAF-115`. Three of the SPEC's sixteen stable codes are emitted nowhere — `LAF-114`. Carries row 43's record forward |
| 45 | What the commands write, watched at the disk | `docs/who-writes-when-cold` | All 38 leaves cold write **nothing**, in `HOME` or the working directory. Then the store watched across a review, an install and an uninstall: **the review that says it changes nothing leaves two objects behind, unreferenced**, and so does a refused install — `LAF-116`, high. That is the measured cause of `LAF-105`'s 79-objects-against-34-references. **`LAF-85`'s mechanism is reproduced and its first reading refuted**: shard mtimes move with no new birth on an ordinary install, and uninstall deletes no object. Carries row 44's record forward |
| 46 | How far `LAF-116` reaches, and what it costs | `docs/laf116-how-far` | **Two corrections to my own row, measured.** The deposit is content-addressed, so it grows once per distinct object and not per review; and **`marketplace status` — a query — deposits too**, earlier than the review does. `LAF-116` corrected `high` → `medium` with the reason in the row. New: **`source remove` leaves the removed source's content on disk**, 24 KB with no reference, no snapshot and no command that lists it — `LAF-117`. Carries row 45's record forward |
| 47 | The managed-block round trip, four ways | `docs/round-trip-residue` | **No new finding, and that is the result.** On `main` a `memory` artifact installs and uninstalls cleanly in all four states: the file AART made is removed, an unowned file is refused, a forced install restores the operator's bytes exactly, and a hand edit made after the install survives. Not `RS-10`'s case — that is the config merge. **`LAF-88` widened**: the empty harness directory is left by any artifact under `.claude/`, on `main`, not just by a hook on its branch. Carries row 46's record forward |
| 48 | The config merge round trip, three ways | `docs/mcp-merge-round-trip` | **`RS-10` reproduces on `main`, measured**: one `mcp` artifact installed and uninstalled leaves `.mcp.json` behind as `{"mcpServers":{}}`, exactly as written. **`LAF-89`'s order asymmetry is the branch's, not `main`'s** — on `main` both orders leave the same emptied file, so the fix takes nothing away. New: **the ownership gate depends on the effect** — `managed-block` refuses an unowned file until `--force`, `merge-json` merges into one first try without a word — `LAF-118`, low. The operator's own entries survive the round trip byte for byte. Carries row 47's record forward |
| 49 | The morning's merge instruction, simulated | `docs/merge-simulation` | **The instruction at the top of this section was false and is corrected above.** All fourteen `fix/` branches merged into `main` in sequence with `git merge-tree`: **13 of 14 conflict**, and *taking both sides* leaves **eleven ids in the register twice with contradictory dispositions** — `LAF-119`. The conflict reaches further than the two files named: the scenario map 8 times and `registry_commands/planning.py` twice. **The pass:** every one of the fifteen rows the fix branches closed carries a flipped disposition *and* an evidence column on its own branch — `15/15`, the per-iteration rule kept. Carries row 48's record forward |
| 50 | The two `deferred` rows no pass ever touched — `LAF-43`, `RS-03` | `docs/recheck-c5-deferred` | **both hold, measured live and in code.** A local repository is refused as an upstream in **two layers** — the config validator before the transport check — and `allow_local_transport` is **dead in the shipped package**: all three construction sites take the `False` default, only tests set it. A `source-local` tree with one symlink is refused whole, naming the path; the Git channel refuses the same shape without the word *symlink*, and `LAF-43` is why nobody can see that message. No new findings — cluster C5 is exactly the knot it says it is. Carries row 49's record forward |
| 51 | The scenario map read across every branch | `docs/scenario-id-collision` | **Row 50 gave two scenarios ids that were already taken, and this package found and corrected it.** The map's ids are allocated from whichever copy a branch holds: `main` has 113 rows, the document chain 138, and **40 ids live on a branch and nowhere else**. `fix/status-names-the-missing-source-rs07` wrote `LA-S-11`/`LA-S-12` at `04:12`; row 50 reused both at `14:28`. Renumbered here to `LA-S-17`/`LA-S-18`, past the `LA-S-16` another branch holds. No id changed meaning. New finding `LAF-120`, medium: nothing computes the next free id across branches and no gate reads this file. Carries row 50's record forward |
| 52 | The nine run headers written tonight, read against the pinning rule | `docs/audit-new-run-headers` | **Seven of nine pin the run to a branch name, not a commit** — only `v4` and `v5` name one — and `v6` and `v7` omit the wheel size as well: `LAF-121`. All nine carry a sha256, a version and a plain statement that the wheel is locally built. **Both size-less runs were re-derived and both digests reproduce byte for byte** — `543 422` bytes for `v6`, `542 418` for `v7`. The records are true today and only while their branches survive. Carries row 51's record forward |
| 53 | What the two fixes to do first actually cost | `docs/cost-the-first-two-fixes` | **Both are smaller than their severities suggest.** `LAF-90` is four literals in `tui.py` (`:2793`, `:2796`, `:2806`, `:2807`) and the values they should carry already exist on `main` as `_DEFAULT_MINIMUM_AART`/`_DEFAULT_MAXIMUM_AART` in `curation/model.py:26`, under a comment that describes this exact defect. `LAF-105` is **a missing verb, not a missing collector**: `collect_garbage`, `GcRequest`, `GcPlan` and both filesystem adapters all ship, the store design specifies plan-or-execute, and `SPEC-aart-1.0.md` already names global garbage collection — only `cli.py` never reaches it. That one command is also the removal path `LAF-116` and `LAF-117` lack. Costed in both rows. Carries row 52's record forward |

**New findings, recorded and not fixed:** `LAF-76`, `LAF-77`, `LAF-78`, `LAF-79` (from 1 and 2),
`LAF-80`, `LAF-81` (from 3), `LAF-82`, `LAF-83` (from 4), `LAF-84`, `LAF-85` (from 5), `LAF-86`
(from 8), `LAF-87` (from 9), `LAF-88` and `LAF-89` (from 12), `LAF-90` (from 14), `LAF-91`
(from 16), `LAF-92` (from 18), `LAF-93` (from 19), `LAF-94` (from 20), `LAF-95` (from 21), `LAF-96` (from 22), `LAF-97` (from 23), `LAF-98` (from 24), `LAF-99` (from 27), `LAF-100` and `LAF-101` (from 28), `LAF-102` (from 29), `LAF-103` (from 30), `LAF-104` (from 31), `LAF-105` (from 38), `LAF-106` (from 39), `LAF-107` (from 40), `LAF-108` and `LAF-109` (from 41), `LAF-110` and `LAF-111` (from 42), `LAF-112` and `LAF-113` (from 43), `LAF-114` and `LAF-115` (from 44), `LAF-116` (from 45), `LAF-117` (from 46), `LAF-118` (from 48), `LAF-119` (from 49), `LAF-120` (from 51), `LAF-121` (from 52). Every one now has a register row
saying where it came from — `LAF-76`..`LAF-90` only from iteration 32, which found them missing, and
33, which wrote them. Until then this sentence was here and was not true.
**`LAF-116` is the finding to read after `LAF-85`:** a plan-only review — the command that says it changes nothing — deposits objects in the durable store that no reference names and no command can remove. `marketplace status` does it too, and `source remove` leaves them behind (`LAF-117`).
**`LAF-90` is the highest-severity thing found in the implementation queue:** an operator who accepts the curses
wizard's own suggested defaults gets a registry that the AART which created it then refuses to read.
It is reproducible without a terminal and the register row carries both halves.
(from 8), `LAF-87` (from 9). Every one has a register row saying where it came from.
**`LAF-85` is the one to read first:** something wrote to
your real data root during this run, and the quality gates have been measured clear of it.

**Before you merge, read `LAF-87`.** The live-acceptance stressor ids continue across four separate
documents, and the scenarios file's own table stops at `LAS-30` as if `LAS-31` were free. It is not —
`LAS-31`..`LAS-56` are already taken by the v2, v3 and setup-build records. Branches 3, 5 and 8 each
took one of `LAS-31`, `LAS-32`, `LAS-33` for a new meaning tonight and need renumbering above the
highest id in use before they merge. Branches 9, 10 and 11 take `LAS-57`, `LAS-58` and `LAS-59` and
state the arithmetic in the scenarios file so the next run does not repeat it; branch 12 takes
`LAS-60` and branch 14 takes `LAS-61` on the same rule.
took one of `LAS-31`, `LAS-32`, `LAS-33` for a new meaning tonight and need renumbering to `LAS-58`+
before they merge. Branch 9 starts at `LAS-57` and states the arithmetic in the scenarios file so the
next run does not repeat it.
highest id in use before they merge. Branches 9 and 10 take `LAS-57` and `LAS-58` and state the
arithmetic in the scenarios file so the next run does not repeat it.

**Waiting for you.** The human-gated passes: the curses front-end (`LA-U-27a` and the wizard walk)
and the MCP credential run (`LA-M-10`, a private image with real credentials). `RS-11` is deliberately
untouched — it needs a live run against a second GHE host, which this run cannot make. Item 6 is the
note that says so in full: it measures all four refusals, recommends leaving them open for now, and
names the two observations that would change that.

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

### 2026-08-16 — overnight residue run, `LAF-73`
Branch `fix/receipt-verify-stale-rollback-laf73`, cut from `main`, not pushed. One work package.
- **The write path was fixed and the read path kept repeating the old records.** `RR-10E` corrected
  `rollback_command` for records written from `2.6.0` on. A record written before it still says *no
  command reverses a completed setup*, and the same executable that holds both facts said nothing.
  An operator reading an old receipt does by hand what one command does.
- **A claim in `verify`, which is the shape `RR-10F` set.** `receipt verify` now asks whether the
  recorded rollback line is a command this executable accepts. When it is not, the report says so
  and names the command that works today, composed from the record's own coordinates. The record is
  not touched: a persisted record is evidence of what a run reported, and rewriting it would destroy
  the thing receipts exist to be.
- **One source for the command string.** `rollback_command_for` composes it, `rollback_command`
  calls it, and `verify` calls it. Composing the sentence twice is precisely how `LAF-65` happened.
- **Walked live** — `docs/testing/PROGRESS-live-acceptance-v6.md`, which lives on the
  `fix/receipt-verify-stale-rollback-laf73` branch and is therefore not linked from here,
  scenarios `LA-M-12`..`LA-M-15`, stressor `LAS-32`. A real registry, a real install, a real setup
  writing a managed block into a sandbox home. With the record aged to the pre-`2.6.0` sentence, the
  `main` wheel reports `true=3, false=0` and says nothing; the branch reports `true=3, false=1`,
  names the undo command, exits `1`, and leaves the record file's sha256 unchanged. The command it
  names was then run: the block and the file are gone.
- **`LAF-73` closes; two findings recorded, not fixed.** `LAF-84`: a completed undo leaves the
  record reading `skipped`, a word that in this vocabulary means the setup never ran. `LAF-85`:
  something wrote to the real user data root at `23:34`–`23:36` during this unattended session while
  every live scenario ran under a sandbox `HOME`; `make integration`, `unit`, `validate` and
  `packaging-check` were each measured afterwards and touched nothing there, so the writer is
  unidentified and now tracked rather than shrugged at a second time.
### 2026-08-16 — overnight residue run, the recipe-format options note
Branch `docs/recipe-format-options`, cut from `main`, not pushed. One work package, no code.
- **Four findings, one decision.** `RS-11`, `RS-13`, `RS-14`, `RS-15` are what the triage brief says
  they are: the same postponed decision seen from four sides. The note treats them as one and is
  filed as `docs/design/OPTIONS-recipe-format-change.md`, on the `docs/recipe-format-options`
  branch and therefore not linked from here. Nothing
  is implemented, and all four rows stay `open` — `RS-11` was explicitly out of scope for this run.
- **The refusals are measured, not remembered.** Each of the four was produced by handing a real
  recipe to the shipped parser and to the canonical-tree check, and the note quotes the parser's own
  words with the file and line that says them.
- **Two claims were narrowed by the measurement.** `RS-13` blocks nothing: a `file.managed-block@1`
  step on `~/.zshrc` parses and plans today, so the missing module is a convenience. `RS-15` is
  about the package *root*: further files under `payload/` are already accepted for `skill`, `mcp`
  and `hook`, and `SETUP.md` was refused by that same allowlist until `LAF-27` added it — which is
  the fix shape, already walked once.
- **What the change would actually cost.** Not the code. `schema_version` and `protocol_version`
  must both be exactly `2`, and this project ships one revision of a protocol and refuses the rest.
  So changing what a recipe may say means every published recipe rises in step, and a registry
  rebuilt on the new revision stops being readable to consumers who have not upgraded — the
  `LAF-60`/`LAF-62` rollout, seen twice. That bill is the same for one change or four, which is the
  argument for doing them together or not at all.
- **The recommendation is to wait, and the note says what for.** Two observations, neither of which
  exists in any run: a second GHE host, which is what produces a per-operator value that is not a
  secret; and an operator who completed a setup wrongly because the recipe could not ask for a
  username, rather than merely reading a paragraph in `SETUP.md`. Without those, `RS-11` buys
  comfort rather than correctness, and low-and-open is a complete answer.
- **No new findings.**
### 2026-08-16 — overnight residue run, `RS-09` (first half)
Branch `fix/registry-refusals-carry-remediation-rs09`, cut from `main`, not pushed. One work
package, split: the refusals, with the report findings left for the next one.
- **The family that says the most after a success said nothing after a refusal.** `registry` emits
  follow-up commands when an action works. Its 37 refusals carried an empty `remediation` in both
  renderers, so the operator who most needed a next step was the one who got none.
- **The test reads the shipped modules, not a list.** `RegistryRefusalRemediationTest` walks the
  syntax of `registry_commands/planning.py` and `commands/registry.py` and fails on any `_error`
  built without a next step. A list of the refusals that carry one would be true the day it was
  written; this covers the refusal added next month. It failed on 37 sites before the fix.
- **Shared lines, not one sentence per site.** Fifteen constants cover thirty-seven refusals,
  because the operator's next step is the same wherever the same problem is stated — the lesson
  `SI-6` already paid for on the object store. The one exception interpolates the package it is
  about, so the command it names can be run as written.
- **The existing guard caught two mistakes while I wrote them.** `EveryVisibleCommandMentionTest`
  parses every `aart …` the package prints: it rejected `aart registry refresh`, which does not
  exist — the action is `refresh-native` — and every command ending in `--source .`, because a
  trailing period is stripped as punctuation and leaves the flag without a value. Both were mine,
  both were caught before they could reach an operator.
- **The parity test then found the second half of the defect.** `_emit_report` — how `validate` and
  `audit` state a refusal in text — printed the message and dropped the remediation, while the JSON
  envelope carried it. That is `LAF-52`'s shape one command family over, and it is fixed here.
- **`RS-09` stays `open`, on purpose.** The 34 findings `validate` and `audit` collect through
  `_diagnostic` still carry nothing. That is the next package, and the register row says so rather
  than claiming a closure the operator would not see.
- **No new findings.** No live acceptance: a reworded refusal is exactly what the run rules exclude,
  and every claim here is driven through the shipped CLI parser and the shipped renderers.
### 2026-08-16 — overnight residue run, `RS-09` (second half, `RS-09` closes)
Same branch as the first half, `fix/registry-refusals-carry-remediation-rs09`, because the two
halves are one finding and a reviewer who merges the branch should get all of it. Cut from `main`,
not pushed.
- **A report is where `validate` and `audit` state a problem.** The first half gave every `Err` a
  next step. These two commands do not refuse — they hand back a report, and its 33 findings named
  no next step at all. The dead end was the same one, in the commands a maintainer runs most.
- **The guard widened to `_diagnostic` and went red on 33 sites.** Same shape as before: it reads
  the syntax of the shipped module rather than a list, so the finding added next month is covered.
- **Warnings get a next step too, and some of them say *nothing to correct*.** A warning like
  *registry contains no external references* describes the limit of what the audit could check, not
  a defect. Saying which of the two it is, in the line itself, is the whole value: an operator
  otherwise cannot tell a gap in the registry from a gap in the audit.
- **The second CLI walk covers the report path.** `registry audit` on the `registry-v1` fixture
  prints three warnings and now three remediation lines, one per finding, and the test asserts the
  counts match rather than that *some* remediation appeared. Reproduction for the error path:
  `aart registry validate --strict` on a registry whose `aart.lock.json` is missing prints
  *compiled index requires a valid committed lock* with the lock-then-build sequence, and
  *compiled registry requires lock and index* with the rebuild.
- **`RS-09` closes.** Both renderers, both surfaces, guarded in the shipped modules.
- **No new findings.**
### 2026-08-16 — overnight residue run, `RS-07`
Branch `fix/status-names-the-missing-source-rs07`, cut from `main`, not pushed.
- **The refusal answered the wrong question.** `source remove` is the exit the product offers, and
  `DESIGN-source-subscription-lifecycle.md` §4 promises the project stays legible afterwards. Remove
  the *last* subscription and the next `marketplace status` refused with *this content operation
  requires at least one enabled source* — a statement about the configuration in answer to a
  question about the project, while the installed skill sat on disk two directories away.
- **`status` is not a content operation.** It reads the manifest and reports it; it fetches nothing.
  `uninstall` was exempted in `2.2.0` because the design names it, and `status` — the same kind of
  question — was left behind. The fix is one frozen set, `_PROJECT_LOCAL`, and `content_required`
  reading it, so the two commands that answer from the project answer without a source and every
  other lifecycle action keeps refusing.
- **The design now takes the decision it was recorded as not taking.** §4 states which commands stay
  answerable when the removed alias was the only one, and says plainly that `2.2.0` decided this for
  `uninstall` alone.
- **Walked live, and the two wheels disagree by exactly one line.** `LA-S-11`..`LA-S-13` in
  `docs/testing/PROGRESS-live-acceptance-v7.md`, on branch
  `fix/status-names-the-missing-source-rs07`: the `main` wheel
  refuses with exit `1`, the branch wheel reports `source-unavailable` with exit `0`, and the
  coordinate it prints is then handed to `uninstall` — with no source configured — which reviews,
  applies, and leaves the project empty. `install`, `update`, `list` and `setup` still refuse.
- **One new finding, `LAF-86`.** `uninstall` with no coordinate advises `marketplace list`. That
  command browses the *sources*, not the project, and refuses outright when none is configured — so
  the operator who just removed their last subscription is pointed at the one command that cannot
  help. Recorded, not fixed: naming the right command there is a different package.
### 2026-08-16 — overnight residue run, `LAF-45`
Branch `fix/audit-upstream-says-it-checked-laf45`, cut from `main`, not pushed.
- **The command that exists to report said nothing on success.** `registry audit --check-upstream`
  printed a line per vendored artifact when one was behind or unreachable, and nothing at all when
  every copy was current. An operator reading a CI log could not tell that from a command line the
  flag had been dropped out of — and on the `main` wheel the two outputs are byte-identical, which
  this run measured rather than assumed.
- **One line, at the end, only when asked.** The audit now closes with an `info` note: *checked 1
  vendored artifact against its upstream: 1 up-to-date, 0 changed, 0 unreachable*, or *no vendored
  artifacts to check against upstream* when the registry vendors none. Without the flag there is no
  note, so its absence still means something.
- **It is a note, not a finding.** New code `registry-audit-note` at severity `info`: it carries no
  remediation because nothing here asks anyone to act, and `passed` already ignores everything below
  `error`, so an audit that was passing keeps passing.
- **The dispositions come from `revendor`'s own vocabulary.** `_vendored_upstream_findings` now
  returns `up-to-date` / `changed` / `unreachable` alongside its diagnostics, so one answer about one
  copy does not get two names depending on which command asked.
- **A test that asserted the defect was corrected.** `test_an_unmoved_upstream_raises_no_drift_finding`
  asserted the word *upstream* appeared nowhere — which is silence-on-success written down as if it
  were the requirement. It now asserts what it means: no *finding*, and the note is separate.
- **Live: two passes and one honest blocked.** `LA-R-31`/`LA-R-32` in
  `docs/testing/PROGRESS-live-acceptance-v8.md`, on branch
  `fix/audit-upstream-says-it-checked-laf45`. `LA-R-33` — the
  [PROGRESS-live-acceptance-v8.md](docs/testing/PROGRESS-live-acceptance-v8.md). `LA-R-33` — the
  counts on a real vendored copy — is `blocked` by `LAF-43`: vendoring refuses a local repository,
  so no sandbox registry can hold a real vendored package, and this run may not publish to a remote.
  The three dispositions are covered hermetically through the real CLI instead, and the record says
  so rather than implying live coverage it does not have.
- **One new finding, `LAF-87`, and it affects tonight's other branches.** The live-acceptance
  stressor ids run to `LAS-56` across four documents while the scenarios file's table stops at
  `LAS-30`. Three branches from this run each re-used an id that already means something else.
  Recorded, not fixed; this branch starts at `LAS-57` and writes the arithmetic down where the next
  run will read it.
### 2026-08-16 — overnight residue run, `RS-08`
Branch `fix/broken-registry-descriptor-fails-rs08`, cut from `main`, not pushed.
- **The decision the `2.2.0` plan asked for, taken.** `SI-5` said the identity agreement is checked
  *whenever both documents are present*, and implemented it as *whenever both documents parse*. That
  left a third state nobody chose: a source shaped like a registry whose `aart-registry.json` is
  broken was admitted in silence. The plan recorded it as `RS-08` and said closing it needed a new
  refusal — its own decision, not a side effect. It is now in
  `DESIGN-subscription-identity-binding.md` §2.
- **A marker that is there must be readable.** A root entry named `aart-registry.json` must be a
  regular file that parses as a registry manifest. Absence is untouched: a source publishing only
  `aart-source.json` is an ordinary native source and stays one. What is refused is a snapshot that
  takes the marker's reserved name and does not honour it.
- **The refusal says what the parser could not read.** *aart-registry.json is present and does not
  parse, so the identity this source declares cannot be checked: missing required field
  'default_channel'* — the parser's own first line, because *that* it failed is the refusal and
  *why* is the only part a maintainer can act on. Two remediation lines: validate and republish, or
  remove the file if this source is not a registry.
- **Walked live, and the earlier wheel shows the cost.** `LA-S-14`..`LA-S-16` in
  `docs/testing/PROGRESS-live-acceptance-v9.md`, on branch
  `fix/broken-registry-descriptor-fails-rs08`. On `main` the same
  [PROGRESS-live-acceptance-v9.md](docs/testing/PROGRESS-live-acceptance-v9.md). On `main` the same
  source is added, an artifact installs from it, and the consumer's manifest records
  `declared_id: la-rs08-source` — an identity read from one document while the document that exists
  to corroborate it could not be read. Three broken shapes refuse on the branch (missing field, not
  JSON, a directory under that name); a source with no marker is unaffected.
- **The refusal withholds, it does not destroy.** A subscription made while healthy whose marker
  breaks later fails its `sync` and keeps its last-known-good snapshot: `source list` still healthy,
  `marketplace status` still `current`, the installed file still on disk.
- **No new findings.**
### 2026-08-16 — overnight residue run, `RS-01`
Branch `fix/owned-mcp-descriptor-is-checked-rs01`, cut from `main`, not pushed.
- **The narrowing was an accident, not a decision.** `VI-5` refuses a `payload/mcp.json` that
  declares no server, and `VI-4` refuses one that launches a file the consumer never receives. Both
  were computed inside the branch of the audit that reads a *vendored* package's `provenance.json`,
  so an `mcp` package authored in place — the ordinary way, and what `registry scaffold mcp` sets
  you up to do — reached neither. Nothing in the consequence depends on where the bytes came from:
  the install merges `descriptor["server"]` either way.
- **`registry audit` now runs the delivery check for every package it walks.** One call moved out of
  the vendored branch; the function takes the package base and its manifest instead of a vendoring
  record, and a `vendored` flag decides one word in the message.
- **It is `audit`, not `validate`, and that is the whole design decision.**
  `validate_registry_workspace` is not only the publisher's gate — the consumer runs it over a
  candidate source through `validate_registry_source_candidate`. A new hard failure there makes every
  registry already carrying such a descriptor unloadable on upgrade, on the subscriber's side too:
  the protocol break `VI-5` rejected, arrived at from the other direction. Recorded in
  `DESIGN-vendored-copy-integrity.md` §7 as an amendment that leaves the `2.4.0` paragraph standing.
- **An owned package is not called vendored.** Same fault, same remedy, but the message drops the
  word rather than sending a maintainer looking for an upstream that does not exist.
- **Walked live, three passes.** `LA-R-34`..`LA-R-36` in
  `docs/testing/PROGRESS-live-acceptance-v10.md`, on branch
  `fix/owned-mcp-descriptor-is-checked-rs01`. The registry — three `mcp`
  packages, nothing vendored — was created, scaffolded, locked, built and committed by a wheel built
  from `main`, so the finding cannot be an artefact of how the package was written. On `main`:
  `registry audit: passed`, exit `0`. On the branch: two errors naming `mcp/atlassian` and
  `mcp/jira`, exit `1`, and the third, healthy package named by neither.
- **The harm was measured rather than asserted.** `LA-R-36` installs the refused artifact from a
  consumer project on the *branch* wheel. `registry validate --strict --frozen` passes, the
  subscription succeeds, the install succeeds, and the project's `.mcp.json` ends up holding
  `"atlassian": {}` — a named server that starts no process. That empty object is why the audit error
  exists and why it is not a load-time refusal.
- **No new findings.** One thing worth a reader's eye is written into the v10 record rather than the
  register: `marketplace list` labels the empty-server artifact `[healthy]`, because that word means
  reconciliation health, not runnability. It is the `VI-5` decision working as chosen, and it is also
  why this check has to live on the maintainer's side.
### 2026-08-16 — overnight residue run, `LAF-47`/`RS-10` design note
Branch `fix/uninstall-removes-the-file-it-made`, cut from `main`, not pushed. **The note only.** The
brief asks for it committed on its own before any code, and that is what this commit is. Both
findings stay `open`.
- **Reproduced first, on a real wheel.** Install one `mcp` and one `hook` artifact into a clean git
  repository, uninstall both: `.agent-artifacts/` and `.claude/hooks/guard/` are reclaimed, and
  `.mcp.json` survives as `{"mcpServers":{}}` while `.claude/settings.json` survives as
  `{"hooks":{"PreToolUse":[]}}`. `git status --porcelain` reports two untracked paths on a repository
  that was clean. So `RS-10` is right that this is not an `mcp` quirk: `key` mode leaves an empty
  object and `list` mode an empty array.
- **The code for this exists and cannot fire.** `lifecycle/application.py:578` removes the
  destination when the effect created it and the result is empty — but it tests the **whole
  document**, and every merge target in every shipped profile writes under a `json_path`
  (`mcpServers`, `hooks.PreToolUse`, `mcp`, `hooks.BeforeTool`). After the last removal the document
  is `{"mcpServers": {}}`, which is not empty, so the branch is dead code for a merge at the
  document root that no profile asks for.
- **The evidence question is the real one, and it has a sharp answer.** `created_destination` is
  recorded per *effect*. Install two `mcp` artifacts separately and the first records `true`, the
  second `false` — correctly, the file was there. Uninstall in that order and the last effect out is
  the one that says `false`, while the record that said `true` was deleted with the first uninstall.
  The evidence for a file's origin can be destroyed before the file is last touched.
- **The rule the note settles on.** Remove only when the effect being reversed created the file, the
  merge was already proven reversible, and what remains is exactly the empty container chain on that
  effect's own `json_path` and nothing else. The third condition is what makes the first safe to act
  on: a file AART made is still a file an operator may have written into.
- **What it leaves, on purpose.** The reverse-order case above. Closing it needs a durable
  per-destination ownership fact in the install state, which is a state-schema change belonging to
  the version-boundary stream (`LAF-62`, cluster C4). The note says so, and the acceptance criteria
  require the register row to say so too rather than claim more than the fix delivers.
- **No new findings.** The design note is `docs/design/DESIGN-uninstall-file-reclamation.md`; both
  register rows point at it and stay `open`.
### 2026-08-16 — overnight residue run, `LAF-47`/`RS-10` implemented
Branch `fix/uninstall-removes-the-file-it-made`, second commit. The note is the commit before it.
- **The fix is one predicate.** The emptiness test now walks the effect's own `json_path` instead of
  testing the document root, so `{"mcpServers": {}}` after the last identity goes is recognised as an
  empty file rather than a document with one key in it. The removal branch that shipped in `2.2.0`
  and could never fire now fires.
- **Walking the chain, not descending to the leaf.** One extra key at any level means the file holds
  something this effect did not put there, and a file with anything in it is kept whoever wrote it.
  That is the condition that makes acting on `created_destination` safe.
- **Five scenarios, five passes.** `LA-U-31`..`LA-U-35` in
  `docs/testing/PROGRESS-live-acceptance-v11.md`, on branch
  `fix/uninstall-removes-the-file-it-made`. Same registry, authored and
  committed by a wheel built from `main`. After install and uninstall of the same two artifacts in
  the same clean repository, `main` leaves `?? .claude/` and `?? .mcp.json` and the branch leaves
  nothing.
- **The refusals were measured, not asserted.** A `.mcp.json` committed as `{"mcpServers":{}}`
  *before* any install survives install and uninstall byte-identical. A file AART created that an
  operator has since written into survives with their key intact and the container emptied.
- **A test that asserted the residue was corrected.**
  `test_key_merge_with_json_null_is_present_and_can_be_removed` ended by asserting the file was left
  as `{"mcpServers": {}}`. Its subject is that a `null` value is found and taken out; what it was
  pinning at the end was the defect. It now asserts the file is gone.
- **Two new findings, recorded and not fixed.** `LAF-88`: the emptied directory outlives the file —
  `.claude/settings.json` goes and `.claude/` stays, empty, invisible to `git status` because git
  does not track empty directories. `LAF-89`: whether the file is reclaimed depends on uninstall
  order, because `created_destination` is per effect and the record that carries `true` is deleted by
  the first uninstall. `LA-U-35` walks the asymmetry both ways — install order leaves the file,
  reverse order removes it. The design named this case before the walk found it, and the register row
  says so rather than letting `closed` imply more than the fix delivers.
### 2026-08-16 — overnight residue run, `RS-04`
Branch `fix/vendor-refusal-names-revendor-rs04`, cut from `main`, not pushed.
- **The refusal now says which command is not create-only.** Upstream moving is the ordinary reason
  to run `vendor` a second time, and `revendor` is what adopts movement. *artifact package already
  exists* was true and stopped there.
- **Which remediation depends on what is actually there.** A package carrying vendor provenance is
  sent to `aart registry revendor <kind> <name> --artifact-version <version>`, with the reason it
  needs that flag — `revendor` re-resolves the recorded ref and plans nothing without the version
  this registry will publish. A package authored in place is told it records no upstream, and offered
  the two things that do work: a name this registry does not use, or removing the package first.
- **Sending an authored package to `revendor` would have been a second wrong answer.** `revendor`
  re-resolves a recorded upstream; there is none, so it would refuse in its turn. The test asserts
  the word does not appear in that case.
- **No live walk.** The brief excludes a reworded refusal, and this is one: no behaviour changes, the
  same exit code, the same message, one remediation line added.
- **No new findings.**
### 2026-08-16 — overnight residue run, `RS-02`
Branch `fix/registry-requests-stop-stamping-dead-bounds-rs02`, cut from `main`, not pushed.
- **A window is now derived, never typed.** The command boundary substituted the literals `1.0.0`
  and `2.0.0` whenever a registry request arrived without a compatibility window — which is every
  action except `init`, because `--minimum-version` and `--maximum-version` exist on `init` alone.
  Both literals now come from the one place that derives them from the running executable, and the
  flag skin imports the same pair instead of computing its own ceiling. Three definitions of the
  same rule are how a fourth went stale.
- **The values were dead, and the run says so rather than assuming it.** `LA-R-40` scaffolds the
  same artifact under a `main` wheel and under the branch wheel and compares the trees: byte
  identical. A difference there would have meant something did read them and the register row was
  wrong.
- **The walk was worth its minutes for one reason.** The fix moves an import into `cli.py`, the
  entry point. An import that resolves under the test runner and not under an installed wheel is a
  failure every unit test passes through, so `LA-R-37` starts the real executable first. Five
  scenarios, five passes, `docs/testing/PROGRESS-live-acceptance-v12.md`.
- **What proves it:** `tests/registry_cli_test.py::RegistryCliTest::test_rs02_no_registry_action_declares_a_window_that_excludes_the_running_aart`
  asserts the invariant across `scaffold`, `vendor` and `promote-native` rather than pinning one
  literal, so an action added later inherits it. The second test holds the other side: an author who
  really supports a wider range still gets the range they asked for.
- **One new finding, recorded and not fixed. `LAF-90`, and it is the serious one.** The curses
  wizard offers the same two literals as its defaults for `registry init`. There they are not dead:
  an operator who presses return at both prompts authors a registry declaring `>=1.0.0,<2.0.0`, and
  `registry validate` on that registry answers *registry workspace is incompatible with this AART
  version*. The tool writes a registry it then refuses to read. Both halves were reproduced without
  a terminal — the wizard's question loop takes its reader as an argument — so only the screen
  itself is human-gated. `RS-02` fixed the flag path; the wizard is a separate package and was left
  alone.
### 2026-08-16 — overnight residue run, `LAF-49`
Branch `fix/document-the-git-environment-laf49`, cut from `main`, not pushed. The last item in the
brief's queue.
- **Nothing about the behaviour changed, and nothing should have.** AART runs system Git with an
  allowlisted environment — `HOME`, `PATH`, `SSH_AUTH_SOCK`, `XDG_CONFIG_HOME`, `SYSTEMROOT` — so
  `https_proxy` never reaches it. That is deliberate: a proxy URL is one of the ordinary places a
  credential hides, and `https://user:token@proxy.example:3128` is a supported form. `LAF-49` was
  never a request to pass it through. It was that nobody was told.
- **The cost is specific, so the page names it.** On a network whose only egress is a proxy, every
  command that touches a remote fails with Git's transport error and no mention of a proxy — and
  the operator exported the variable themselves, so it looks like it is in effect.
  `docs/configuration/git-environment-v1.md` states what is passed, what is dropped, why, and the
  route that works: `git config --global http.proxy`, which works precisely because `HOME` is
  passed. It covers the SSH case and the credentialed-proxy case too.
- **A document nobody links is barely better than no document.** The README's *Maintaining a
  registry* section now points at it with the symptom attached — clones at the prompt, fails under
  AART.
- **What proves it, and what keeps it true:** `tests/git_environment_docs_test.py` reads the three
  tables on the page and checks them against the code — the allowlist against
  `_ALLOWED_ENVIRONMENT`, every variable the page calls dropped against what `_safe_environment`
  actually returns, and the forced values against the values Git really sees. Prose can be right
  once and drift; this cannot drift without failing the suite.
- **No live walk.** The brief excludes a document, and the proxy scenario needs an egress-restricted
  network this run cannot build. The claims are driven against the real function instead.
- **No new findings.**
### 2026-08-16 — overnight residue run, re-checking closed rows (1)
Branch `docs/recheck-closed-register-rows`, cut from `main`, not pushed. The brief's fallback: take
`closed` rows oldest first, run the evidence the last column names, record the result, repair
nothing. Nothing in the code changed on this branch — the wheel built here has the same digest as
`main`, `fcdf95d94b8150c82570dccca154dda536ec3cac8e7c25b3e215dba124bcb174`, which is what makes the
observations below observations about the shipped tool.
The lab: a registry with one `mcp` artifact carrying a filesystem-only recipe
(`directory.create@1`), subscribed as a local source into a throwaway project, with a sandbox `HOME`.
Deliberately no Docker, no Keychain, no network — the three rows below are about what the operator is
*told*, and a recipe that needs nothing outside itself keeps the reading clean.
| Row | Evidence named | Result |
| `LAF-52` | `tests/setup_render_test.py`, and `marketplace setup` at a terminal prints the failure detail, the artifact key and the manual route | **reproduces.** 27 tests pass. `marketplace install --yes` on an unauthorized source prints `reason setup from local requires explicit source authorization`, the key `lab/mcp/labserver@1.0.0#claude/project`, and the manual route with `SETUP.md` and its absolute object-store path — and `Setup: planned=0, failures=1` comes *after* the content it used to replace |
| `LAF-54` | `marketplace setup` without `--yes` prints the effect list, the capabilities and the manual alternative before asking for approval | **reproduces.** Purpose, source, recipe path, recipe hash, plan hash, `capabilities filesystem`, required tools, the manual alternative with its status line, then the numbered effect with target, capability, recovery and details, ending `Reviewed only; re-run with --yes to apply this exact plan.` |
| `LAF-53` | `aart marketplace receipt undo <coordinate>` | **reproduces.** The command exists, reviews before acting (`reverses=1, keeps=0`, `Reviewed only…`), and on `--yes` the directory the run created is gone from the file system |
| `LAF-55` | `receipt verify` asks the Keychain whether the item holds a non-empty value; `tests/setup_verify_test.py` | **half checked.** The tests pass. The live half is `blocked`: it needs a keychain recipe and a real Keychain item, and the brief excludes credential entry. **What the human has to show:** store a secret through `marketplace setup` on a TTY, then empty it with `security add-generic-password -U -w ''`, then run `receipt verify` — the claim is that it reports the item as not holding a value rather than merely present |
- **No row was repaired, and no row moved.** All four rows stand as they are written.
- **One new finding, recorded and not fixed. `LAF-91`: a completed undo reports itself as
  `skipped`.** `marketplace receipt undo … --yes` removes what the run created, says `reverses=1,
  keeps=0`, and then prints `Undo outcome: skipped — Setup rollback completed`; `--json` puts
  `"status": "skipped"` beside `"ok": true`. The value is the artifact's post-undo *setup state*
  (`setup_runtime.py:1369`), and as a state it is right — the artifact is no longer set up. As the
  answer to *what did the undo do*, which is where the renderer puts it, it says the opposite of
  what happened. Found by running `LAF-53`'s evidence, which is the point of the exercise: the row
  is still true and the command still has a defect beside it.
### 2026-08-16 — overnight residue run, re-checking closed rows (2)
Branch `docs/recheck-closed-register-rows-2`, cut from `main`, not pushed. It carries the previous
branch's `PROGRESS.md` and register rather than `main`'s, because the two branches are one record of
one exercise; every other branch tonight is independent and this pair is not. Again no code changed:
the wheel is `fcdf95d9…`, the same digest as `main`.
| Row | Evidence named | Result |
| `LAF-59` | `RR-2B`; a build failing on its last instruction reports that instruction and its exit code | **reproduces**, against a real `docker build`. A recipe with one `docker.build@1` step, a Dockerfile with four verbose instructions and a failing fifth, run through `marketplace setup … --yes`. The reported detail keeps the head *and* the tail with the middle marked `… 1713 characters elided …`, and the tail is `6 | >>> RUN /bin/sh -c "echo about to fail; exit 3"` followed by `did not complete successfully: exit code: 3`. The original finding was that this end of the transcript was the part thrown away |
| `LAF-63` | one redactor in `agent_artifacts/redaction.py`, matching a credential name with any prefix, `tests/setup_render_test.py::test_laf63_a_prefixed_credential_name_is_redacted` | **reproduces.** The test passes and `def redact` still matches exactly one definition in the package |
| `LAF-65` | `rollback_command` names `receipt undo`, and `tests/setup_custom_test.py::WrittenCommandFieldTests` hands the written field to the shipped CLI parser | **reproduces**, and the test still does what the column says: both fields are handed to `_parse_failure`, the shipped parser, rather than compared against a string |
| `LAF-66` | the probe takes the run root the engine writes into, and `tests/setup_verify_test.py::test_laf66_…` drives the real writer and the real reader together | **reproduces.** The test calls `new_run_directory` and then `orphan_run_directories` — the real pair — and asserts the old search location finds nothing |
| `LAF-72` | there is one `redact_text` and `tests/token_containment_test.py` walks every string of the persisted record | **reproduces.** One definition, and the walk is still structural (`os.walk`, every string in the payload) rather than a list of field names |
- **No row was repaired and no row moved.** All five stand as written.
- **No new findings this iteration.**
- **Why `LAF-59` was worth the Docker run.** Its evidence is the one thing in this group that no
  test in the repository can hold: the transcript is produced by BuildKit, and what AART keeps of it
  is only observable by failing a real build. The re-check used a base image already on the machine,
  created no image tag — the build fails before one exists — and left nothing behind but ordinary
  build cache.
- **What is left in this sweep.** `LAF-68`, `LAF-70`, `LAF-71` and `LAF-74` are next by age. Their
  evidence is not in this repository: three name merged pull requests in the constellation's other
  repositories, and re-checking them means reading GitHub. That is a different kind of check from
  the ones above and is noted here rather than guessed at.
### 2026-08-16 — overnight residue run, re-checking closed rows (3)
Branch `docs/recheck-closed-register-rows-3`, cut from `main`, carrying the previous two branches'
record. This finishes the sweep: every row that was `closed` on `main` has now been re-checked once.
The evidence for these four is not in this repository — three name merged pull requests in the
constellation's other repositories — so this pass read GitHub. Read-only: `gh pr view`, `gh pr diff`,
and the contents API. Nothing was pushed, commented on, or opened.
| Row | Evidence named | Result |
| `LAF-68` | the acceptance runner is on `2.6.0` and reconciles eleven installations against the published wheel | **reproduces.** `consumer-acceptance.yml` on `main` installs `agent_artifacts-2.6.0-py3-none-any.whl` from the release, asserts `aart --version` equals `agent-artifacts 2.6.0`, and fails on drift against `EXPECTED_INSTALLATIONS: "11"` |
| `LAF-70` | the authoring machine runs `2.6.0`; Registry A's pin move is the remaining half | **reproduces**, both halves. `aart --version` on this machine is `agent-artifacts 2.6.0`, and Registry A's three workflows pin `v2.6.0` on `main` |
| `LAF-71` | every pin in the constellation is `2.6.0` and merged | **does not reproduce.** Registry B's three workflows pin `v2.5.0`. The row is `open` again |
| `LAF-74` | the release note was added to the checked list and `DOC009` then failed it | **reproduces.** A probe document under `docs/design/` claiming `LAF-63` is shipped open fails the gate with `DOC009 LAF-63 is listed as shipped open and is closed in the register`. The probe was removed |
- **`LAF-71` is the row the sweep was for.** It said every pin in the constellation had moved to
  `2.6.0` and named three merged pull requests. Two of them did what the row says. The third,
  Registry B's [#5](https://github.com/M1F1/agent-artifacts-registry-2/pull/5), is titled *Move the
  CI pin to 2.6.0*, was merged from a branch named `chore/move-pin-2.5.0`, and its diff moves all
  three workflows from `v2.0.0` to `v2.5.0`. No later pull request touches them and no `AART_REF`
  repository variable overrides the default, so Registry B's CI validates its registry with an AART
  one release behind the tool — which is the exact shape of `LAF-70`, the finding this pair came
  from. The row is `open` and nothing was repaired.
- **The new finding is not the pin. `LAF-92` is that a closure was recorded from a title.** The pin
  is a one-line change in another repository and someone will make it in a minute. What is worth
  keeping is how it got into this register as `closed`: three pull request numbers were collected,
  their titles read, and the diff of the third never opened. The register's own rule is that
  `closed` carries *the reproduction that establishes it*; a merge status is not that, and this is
  the first row in the sweep where the difference showed.
- **The triage brief is left standing.** `triage-brief-2.6.0.md` says the three workflows all pin
  `v2.6.0`. It is dated, it is what was believed on `2026-08-15`, and correcting it would destroy
  the evidence it exists to be. The correction lives in the register row and here.
### 2026-08-16 — overnight residue run, re-checking this run's own closures
Branch `docs/recheck-tonights-closures`, cut from `main`, carrying the previous branch's record. The
sweep of `main`'s `closed` rows finished in the entry above, so this pass turns the same method on
tonight's work: fourteen rows this run marked `closed` on thirteen branches. Each branch was checked
out and the evidence its own register row names was run there — not a re-run of the tests I wrote,
but a run of the string a reader would copy out of the register.
| Branch | Row | Result |
| `fix/setup-docker-credentials-rs12` | `RS-12` | 7 passed |
| `fix/curses-install-scope-laf64` | `LAF-64` | 4 passed |
| `fix/wheel-digest-emits-what-it-hashes-laf75` | `LAF-75` | 4 passed |
| `fix/docs-check-both-directions-laf69` | `LAF-69` | 12 passed |
| `fix/receipt-verify-stale-rollback-laf73` | `LAF-73` | 4 passed |
| `fix/registry-refusals-carry-remediation-rs09` | `RS-09` | 4 passed |
| `fix/status-names-the-missing-source-rs07` | `RS-07` | **no tests ran** |
| `fix/audit-upstream-says-it-checked-laf45` | `LAF-45` | 5 passed |
| `fix/broken-registry-descriptor-fails-rs08` | `RS-08` | 4 passed |
| `fix/owned-mcp-descriptor-is-checked-rs01` | `RS-01` | 4 passed |
| `fix/uninstall-removes-the-file-it-made` | `LAF-47`, `RS-10` | 5 passed |
| `fix/vendor-refusal-names-revendor-rs04` | `RS-04` | 1 passed |
| `fix/registry-requests-stop-stamping-dead-bounds-rs02` | `RS-02` | 1 passed, 3 subtests |
| `fix/document-the-git-environment-laf49` | `LAF-49` | 4 passed |
- **Thirteen of fourteen reproduce.** The fixes stand where the evidence runs.
- **`RS-07`'s evidence runs nothing, and says so quietly.** The row names
  `tests/identity_change_reconciliation_test.py::test_rs07_status_reports_the_project_when_the_only_subscription_is_removed`.
  That test is a method of `IdentityChangeReconciliationTest`, and a node id that skips the class
  matches nothing: pytest prints `no match in any of [<Module identity_change_reconciliation_test.py>]`,
  then `no tests ran`, and exits `4`. Name the class and the same test passes, so the fix is fine.
  What failed is the record — and it failed by printing a green-looking nothing rather than a red
  test, which is the part worth keeping. That is `LAF-93`, `open`, and nothing was repaired.
- **Three more rows name a glob.** `RS-08`, `LAF-45` and `LAF-73` each write `test_laf45_*`, which
  pytest also refuses as a node id; it needs `-k`. They ran here because I expanded them. A reader
  copying the row would not. Same finding, same row.
- **Nothing checks any of this.** `scripts/docs_check.py` verifies that links resolve and that every
  stream row reaches the register. It has never tried to run an evidence string, which is why a
  selector that collects nothing survived being written, reviewed and committed.
- **What is left.** Every `closed` row in the register — `main`'s and tonight's — has now been
  re-checked once. The next pass has to be a second look at rows whose evidence *ran*, asking
  whether what it proves is what the row claims, which is the shape `LAF-92` turned out to have.
### 2026-08-16 — overnight residue run, re-reading closed rows' claims
Branch `docs/recheck-closed-row-claims`, cut from `main`, carrying the previous branch's record.
Every `closed` row has now been re-checked once by running the evidence it names. This pass asks the
next question — the one `LAF-92` turned out to be — of four rows whose claims reach further than the
artifact they name: does the evidence establish the *whole* claim, or one instance of it? Nothing
was repaired and no code changed.
| Row | The claim that reaches further | Result |
| `LAF-63` | "one redactor in `agent_artifacts/redaction.py`, matching a credential name with any prefix" | **holds.** One `def redact_text` in the package. `setup.py`'s `_REDACTED_ASSIGNMENT` is a narrower post-step on top of it, not a second implementation |
| `LAF-72` | "`tests/token_containment_test.py` walks every string of the persisted record" | **holds as written** — channel 2 walks `dump_setup_state` output. The test's own docstring says channels 2 *and 4*, and channel 4 does not. That is `LAF-94` |
| `LAF-55` | "`receipt verify` asks the Keychain whether the item holds a non-empty value" | **holds.** The real `_keychain_value_present` is wired into `local_probes`, runs `security find-generic-password -w`, and returns `bool(stdout.strip())` — length only, value discarded. The live half stays human-gated |
| `LAF-65` | the written command fields are handed to the shipped parser "so it cannot go stale again" | **holds, and wider than I expected.** The two composers in `setup.py` are covered by `WrittenCommandFieldTests`, and `tui.py`'s two — including a `retry_command=` the class never reaches — are covered by the package-wide mention scan in `EveryVisibleCommandMentionTest` |
- **`LAF-94` is the one thing this pass found, and it is a claim, not a hole.** The containment
  test's channel 4 asserts against a `payload` dict the test writes itself, with `planned` and
  `planning_failures` empty. Its structural walk therefore visits 11 strings, all of them literals
  from the same file, and never calls `_setup_payload`. One real `planned` row carries 25, every one
  of them derived from a recipe, and a real run has one per queued artifact.
- **The containment itself is real, and I measured it rather than assuming.** A recipe whose
  `purpose` carried `COMPANY_GHE_TOKEN=<planted>` was planned and projected: `project_setup_review`
  returned `Configure access using [redacted]` and the planted value appears nowhere in the
  projection the `--json` payload is built from. So the `--json` channel is safe today by the
  projection, which is exactly the thing the test does not observe.
- **The design is left standing.** `DESIGN-token-containment.md` §4.3 says a new channel that
  forgets redaction fails the test without anybody extending a list. That is the same claim one
  level up and it is not literally true either — a new channel needs a new test. Per the brief the
  design keeps saying what it said; the correction lives in the register row and here.
- **What is left.** Three of the four claims survive a harder reading, which is the useful result:
  the rows are mostly written to the width of their evidence. The rows not yet read this way are the
  remaining `closed` ones — `LAF-52`, `LAF-53`, `LAF-54`, `LAF-59`, `LAF-66`, `LAF-68`, `LAF-70`,
  `LAF-74` — and the ones worth reading next are those whose evidence is a live walk, because a
  walk proves one path and the rows tend to state a property.
### 2026-08-16 — overnight residue run, re-reading the live-walk rows' claims
Branch `docs/recheck-live-walk-claims`, cut from `main`, carrying the previous branch's record. Same
question as the entry above, asked of the four rows closed by a live walk: a walk proves one path,
and these rows state a property. Two real Docker builds were run for this; both failed before a tag
existed, and `docker image ls` confirms nothing was left behind. No code changed.
| Row | The claim that reaches further | Result |
| `LAF-52` | "`marketplace setup` prints the failure detail, the artifact key and the manual route" | **holds.** `_failure_lines` renders key, reason and manual for every planning failure; `_planned_lines` renders the manual and all six effect fields; `_item_lines` renders every key the item payload carries. Nothing the JSON holds is dropped by the text |
| `LAF-53` | "`aart marketplace receipt undo <coordinate>`" | **holds in substance, thinly written.** The row names a command and no expected output. What it has to prove is that a successful setup is reversed, and that was measured in a real lab two iterations ago — `reverses=1, keeps=0` — not by this string |
| `LAF-54` | "prints the effect list, the capabilities and the manual alternative before asking for approval" | **holds, and consent is a flag, not a prompt.** `finalize_setup_queue(consent=lambda _effect: approved)` reads `--approve-setup-effects`. The review path prints the list; the design states that shape at `DESIGN-readable-receipt.md` §3.4 and it is what the row describes |
| `LAF-59` | "a build failing on its last instruction reports that instruction and its exit code" | **holds for a short instruction, degrades for a long one.** That is `LAF-95` |
- **`LAF-95`, measured on real BuildKit output rather than argued.** A build whose failing `RUN` is
  708 characters emits 5 907 characters; `failure_detail` keeps 512. `exit code: 4` and `did not
  complete successfully` survive, because they are last. What does not survive: `ERROR: failed to
  build: failed to solve: process`, the `>>>` marker naming the Dockerfile line, and the start of
  the instruction itself — the operator's detail begins mid-word at
  `gument-list-that-real-recipes-do-carry;`. The word *ERROR* does not appear anywhere in it.
- **The head is the sharper half of it.** 128 of the 512 characters go to
  `#0 building with "desktop-linux" instance using docker driver … #1 transferri`, cut mid-word, and
  it was byte-identical in both builds. `LAF-59` was raised *because* a consumer was shown
  `transferring dockerfile: 117B done` and never the failure. The fix keeps the tail and still
  spends a quarter of the budget on the same boilerplate.
- **The design is left standing.** `DESIGN-readable-receipt.md` §3.5 says both ends can carry
  meaning, so it keeps both. For `docker build` the head measurably does not, twice. The correction
  lives in the register row and here, per the brief.
- **A shorter failing instruction was checked first and reports well.** A chatty step producing
  10 647 characters still ends with the full `ERROR: … process "…" did not complete successfully:
  exit code: 3` — the instruction survives there because the ERROR line embeds the whole command,
  not because the `>>>` context block does; that block was elided in both runs.
- **What is left.** `LAF-66`, `LAF-68`, `LAF-70` and `LAF-74` are the `closed` rows not yet read
  this way. `LAF-53`'s row is worth widening when someone touches it: it names a command and not
  what the command has to print, which is the same weakness `LAF-93` found in a different form.
### 2026-08-16 — overnight residue run, `LAF-66`'s claim taken to the CLI
Branch `docs/recheck-remaining-closed-claims`, cut from `main`, carrying the previous branch's
record. `LAF-66` is the row where a passing test drove a fake and the probe looked nowhere real, so
its claim is the one that most deserves to be checked against a real executable rather than read.
The test proves the writer and the reader agree *given the same root*. Whether the CLI hands them
the same root is a separate claim, and it is the one `LAF-66` was.
**Run header.** Pre-release run against a **locally built** wheel, not a published asset.
| | |
|---|---|
| commit | `e3894fe` (`main`) |
| wheel | `agent_artifacts-2.6.0-py3-none-any.whl`, 542 151 bytes |
| wheel sha256 | `fcdf95d94b8150c82570dccca154dda536ec3cac8e7c25b3e215dba124bcb174` |
| `aart --version` | `agent-artifacts 2.6.0` |
| stressor | sandboxed `HOME`, `source-local` registry, filesystem-only recipe; no Docker, no Keychain, no network |
- **`LAF-66`'s claim holds end to end.** A real `marketplace setup` was applied, its `plan_hash`
  read back from `receipt show --json` (`b233f1dff6080db4…`), and a working copy planted at
  `<data_root>/.agent-artifacts/setup-runs/b233f1dff6080db4-plantedprobe`. `receipt verify` found it
  and printed the full path. The CLI resolves `run_root` from `runtime.paths.data_root` at
  `commands/marketplace.py:701` and the engine plans with `run_root=location.data_root` at
  `setup_engine/application.py:457` — the same root, and now measured to be the same root rather
  than traced to be.
- **`LAF-96` is what the walk found instead, and it is in the output of that very command.**
  `receipt verify` renders each claim as `f"{status}: {subject}"`. The two record-wide claims name
  the bad condition in the subject and are negative in the kind, so the headline inverts:
  `true: credential-shaped text in the persisted record` above `detail  no credential-shaped text in
  the record`, and `false: working copies left by plan b233f1dff6080db4` above `detail  1 working
  copy left by an interrupted run, not removed`. An operator who reads the headline and not the
  detail gets the opposite answer to the one the probe returned. Recorded, not fixed.
- **It is confined, which is why it survived.** Every step claim's subject is a bare noun — an image
  reference, a tag, a written path — so `true: aart/mcp/x:1.0.0` reads correctly. Only the two
  claims added later, whose subjects are sentences, compose wrongly.
- **`LAF-52` was watched holding in the same run.** A setup refused for want of source authorization
  printed the key, the reason, and the manual route with its resolved `SETUP.md` path, which is the
  rule `DESIGN-readable-receipt.md` §3.4 states.
- **Nothing touched the real data root.** Every command ran with `HOME` inside the lab; the data
  root exercised is under the lab's `home/Library/Application Support/agent-artifacts`.
- **What is left.** `LAF-68`, `LAF-70` and `LAF-74` are the `closed` rows still unread this way.
  `LAF-70`'s claim is already half-corrected by `LAF-71`/`LAF-92`; the other two need GitHub and a
  `DOC009` probe respectively, both of which this run has done once before.
### 2026-08-16 — overnight residue run, how far the register gate reaches
Branch `docs/recheck-doc-gate-reach`, cut from `main`, carrying the previous branch's record.
`LAF-74`'s row says a release note was added to the checked list and `DOC009` then failed it for a
stale claim. That reproduces, and it was checked with a probe two iterations ago. The claim that
reaches further is the one underneath it: that the gate holds the documents in agreement with the
register. It holds the documents somebody listed.
- **The list is four patterns and 60 files:** `docs/plan/*.md`, `docs/design/*.md`,
  `docs/release/compatibility-v14.md`, `docs/release/release-checklist-v14.md`. Everything else in
  the repository — `README.md`, `CHANGELOG.md`, `docs/testing/*`, `docs/configuration/*`, every
  other release document — is never read for a stale *shipped open* claim.
- **Measured rather than argued.** `DOC009`'s own three regexes were run over every markdown file
  outside the list. Three files would fail it:
| File | Would fail for | Verdict |
| `CHANGELOG.md:60` | `LAF-63` | **a current document with a stale claim, ungated** |
| `docs/release/release-checklist-v13.md:217` | `LAF-52`, `LAF-53`, `LAF-54`, `LAF-55`, `LAF-59` | dated record of `2.5.0`; correctly outside |
| `docs/testing/residue-stream-2026-08-15.md:36` | the same five | the heading says *From `2.5.0`*; correctly outside |
- **`LAF-97` is the first row.** `CHANGELOG.md`'s `## 2.6.0 — 2026-08-15` section lists `LAF-63`
  under *Known defects shipped open*. The register has `LAF-63` `closed` by `RR-10A`, and `RR-10`
  is work that shipped **in** `2.6.0` — the release the section describes. So the changelog tells a
  reader that the release they are installing ships a credential-redaction defect that the same
  release fixed. It is the identical stale claim `LAF-74` caught in `github-release-v2.6.0.md`,
  sitting in the document beside it, in a file the gate cannot see.
- **Nothing was edited.** The changelog section is a released version's record and the brief keeps
  dated documents standing; the fallback forbids repairing anything found this way in any case. The
  correction lives in the register row and here.
- **`LAF-74` stays `closed`.** Its evidence reproduces and its claim is about one file being added
  to the list, which is what happened. The reach of the list is a different finding, which is why it
  has a different id.
- **What is left.** `LAF-68` and `LAF-70` are the last two `closed` rows unread this way; both need
  GitHub and both were re-run against it two iterations ago, so what remains for them is only the
  width question. After that the second pass is complete and a third would be reading the `open`
  rows for the same defect.
### 2026-08-16 — overnight residue run, the last two closed rows read for width
Branch `docs/recheck-acceptance-runner-claim`, cut from `main`, carrying the previous branch's
record. `LAF-68` and `LAF-70` were the two `closed` rows not yet read this way. Read-only GitHub:
`gh run list`, `gh run view --log`, and the contents API. Nothing was pushed, commented on, or
opened. This completes the second pass over every `closed` row.
| Row | The claim that reaches further | Result |
| `LAF-68` | the acceptance runner *is on* `2.6.0` and *reconciles* eleven installations | **holds, and now as behaviour rather than as a file.** The scheduled run at `2026-08-16T05:49:33Z` on `main` succeeded in 13s: it downloaded `agent_artifacts-2.6.0-py3-none-any.whl` (542 kB) from the release, printed all eleven coordinates as `current`, and ended `11 installations current`. The job exits non-zero on a count other than `EXPECTED_INSTALLATIONS: 11` or on any status that is not `current` |
| `LAF-70` | the authoring machine runs `2.6.0`, installed after verifying its digest | **holds on this machine.** `/Users/mifi/.local/bin/aart` answers `agent-artifacts 2.6.0`. The Registry A half was re-checked two iterations ago; the Registry B half is `LAF-71`/`LAF-92` and stays `open` |
- **`LAF-98` is what reading `LAF-68` widely found.** The runner installs the published wheel by URL
  with `--no-deps` and never checks what it got. There is no `sha256`, no `shasum`, no digest step
  anywhere in `consumer-acceptance.yml`. `LAF-70`'s own row records that the *authoring machine*
  installed that same asset after verifying its digest against `wheel-digest` — so the careful
  procedure is the one a person did by hand, and the unattended job that runs every morning is the
  one that skips it. `release.py wheel-digest` exists to make the check possible and no CI in the
  constellation calls it. Recorded, not fixed.
- **The naming shape from `LAF-92` recurs, and here it is harmless.** The pull request that moved
  the runner to `2.6.0` is titled *Move the acceptance runner to AART 2.6.0* and was merged from a
  branch named `chore/aart-2.5.0` — the same title/branch disagreement that made `LAF-71`'s closure
  wrong in Registry B. This one's diff was read two iterations ago and does what the title says.
  Worth knowing that the pattern is in two repositories, not one.
- **The second pass is complete.** Every `closed` row has now been re-run once and then re-read once
  for whether its claim is wider than its evidence. Four rows were wider: `LAF-94`, `LAF-95`,
  `LAF-96`, `LAF-97`, plus `LAF-98` from this entry. A third pass would be the same two questions
  asked of the `open` rows — whether each is still true as written — and `LAF-86`, `LAF-89` and the
  four recipe-format rows are the ones whose wording has aged most since they were filed.
### 2026-08-16 — overnight residue run, the third pass begins: are the open rows still true?
Branch `docs/recheck-open-rows`, cut from `main`, carrying the previous branch's record. The second
pass finished with the last two `closed` rows. This starts the third: the same question asked of the
`open` ones — is each still true *as written*? Four rows were taken, chosen because nothing this run
has touched them and each had an empty evidence column: `LAF-57`, `LAF-67`, `RS-05`, `RS-06`. All
four stay `open`. Their rows now carry what the check found.
| Row | Says | Result |
| `LAF-57` | the two install routes agree on content and disagree on image identity | **true, and its explanation is about to go stale.** See below |
| `LAF-67` | no published artifact uses `docker.build@1`, so two acceptance criteria cannot be walked | **true, re-measured against the live registries.** Registry A publishes three setup recipes and all three use `docker.pull@1`; Registry B publishes none |
| `RS-05` | `io/cache.py` is unreferenced by shipping code | **true, and worse than it reads.** Nothing imports it, and it is in the published wheel |
| `RS-06` | `DESIGN-upstream.md` carries no superseded banner | **true.** No *superseded*, *obsolete* or *replaced by* anywhere in the file |
- **`LAF-57` is the one worth reading.** It gives four causes for the two routes producing different
  image ids: AART's working copy is mode `0600` where a shell redirect writes `0644`, each build
  stamps its own mtime, the hand build inherits the user's buildx defaults, and **AART's build runs
  without `HOME`**. That last one is fixed on `fix/setup-docker-credentials-rs12`, which this run
  produced: `_docker_env` now hands docker steps `HOME` and `DOCKER_CONFIG` so a private base image
  can authenticate. The moment that branch merges, a quarter of `LAF-57`'s explanation is false, and
  the attestation-manifest difference it produced — the hand build exporting one because it read the
  user's docker config, AART's not — may go with it. The other three causes are untouched, so the
  finding stands and its wording does not.
- **This is the register describing a world that one of tonight's own branches changes.** Worth
  saying plainly because nothing would have caught it: `LAF-57` is `open`, so no gate reads it, and
  the `RS-12` branch had no reason to look at a low-severity row about image digests.
- **`RS-05` ships.** `agent_artifacts/io/cache.py` is 94 lines, describes itself as *Immutable
  snapshot cache — shell (WP-7)*, is imported by nothing, and is present in
  `agent_artifacts-2.6.0-py3-none-any.whl`. The row says "unreferenced by shipping code", which is
  true; what it does not say is that it is itself shipped.
- **What is left.** The `open` rows still unread this way are `LAF-58` and the recipe-format cluster
  `RS-11`, `RS-13`, `RS-14`, `RS-15`, which the options note already treats as one change. Every
  other `open` row on `main` is a finding this run closed on a branch.
### 2026-08-16 — overnight residue run, the third pass finished
Branch `docs/recheck-open-rows-2`, cut from `main`, carrying the previous branch's record. The five
`open` rows nothing this run has touched: `LAF-58` and the recipe-format cluster `RS-11`, `RS-13`,
`RS-14`, `RS-15`. All five are still true as written, and every row now carries the check. That
completes the third pass — every row in the register has now been re-run, re-read for width, or
re-read for whether it is still true.
| Row | Says | Still true because |
| `LAF-58` | `preexisting` protects a tag's name, not its meaning; rollback restores neither | the receipt keeps only `returncode == 0`, never the id the tag pointed at |
| `RS-11` | `inputs` accepts only `type: "secret"` | `setup.py:584` raises *inputs[N].type must be 'secret'* |
| `RS-13` | no `shell.zshrc-managed-block@1` | the module table holds `shell.env-from-keychain@1` and `file.managed-block@1` and no third |
| `RS-14` | the format has no comment convention and every `_comment` was refused | `setup.py:389` allows a step exactly `{id, use, with}` |
| `RS-15` | a package cannot carry an auxiliary script at its root | `native_tree.py:451` fixes the root to six names |
- **`LAF-58`'s remedy is nearer than its row implies.** The row says closing it needs `RR-4A` at the
  capture site. The capture site already asks the question: `setup_runtime.py:451` runs
  `docker image inspect <tag>` *before* the build and throws away everything but the exit code, and
  `:463` runs `docker image inspect --format {{.Id}}` *after* it. Recording the earlier binding is
  one flag on a call the code already makes. Written down and not done — the fallback repairs
  nothing.
- **`RS-15` has a route the row does not mention.** The package root is fixed to six names, so an
  auxiliary script is refused there; it is accepted under `payload/` or `setup/`. That does not make
  the row false — it says *at its root* — but a reader deciding whether this matters should know the
  workaround exists.
- **`RS-14` is true because of a rule worth keeping.** A step must be exactly `{id, use, with}`.
  That strictness is what refuses `_comment`, and it is also what makes an unknown field a loud
  error rather than a silent no-op. The options note for the recipe-format cluster is the place that
  weighs the trade; nothing here changes it.
- **All three passes are done.** Every `closed` row: re-run once, re-read once for width. Every
  `open` row: re-read once for whether it is still true. Nine findings came out of it — `LAF-91`
  through `LAF-98`, plus `LAF-71` returning to `open`. The next iteration has no unread rows to
  take, so it should start on what the register does not cover at all: the `visible` and `deferred`
  rows, `LAF-61` and `LAF-62`, which are dispositions this run has never checked.
### 2026-08-16 — overnight residue run, the two dispositions nobody checks
Branch `docs/recheck-visible-deferred`, cut from `main`, carrying the previous branch's record. All
three passes covered `open` and `closed`. The register has two other dispositions and one row each:
`LAF-61` is `visible`, `LAF-62` is `deferred`. Neither has been checked this run. Both are checked
here against the register's own definitions.
| Row | Disposition means | Result |
| `LAF-61` | still true, and now observable — reported by a command rather than repaired | **warranted, and now measured.** Both halves |
| `LAF-62` | out of scope by an explicit decision recorded in a design, not by neglect | **the decision is not recorded anywhere.** That is `LAF-99` |
- **`LAF-61` holds on live evidence.** The working copy planted under the data root two iterations
  ago is still there, contents intact, after `receipt verify` reported it by full path. Named and
  not removed is exactly what `visible` claims, and it is now a measurement rather than a reading of
  the code.
- **`LAF-62`'s disposition has no support.** The commit that measured the finding —
  `6589778`, *The consumer is on a side of the index boundary too* — ends with *Recorded as `LAF-62`
  and left open*, and says the design question is deliberately unanswered because "a cleanup pass is
  the wrong place to answer it". The register was already carrying `deferred`, from `3ff834e`, the
  commit that created the table. The one design that names the finding,
  `DESIGN-readable-receipt.md` §5, says *it does not touch the index-version boundary … those need
  their own stream* — which records that design's scope, not a decision about the boundary.
- **I left it `deferred` and did not flip it.** `LAF-71` was flipped because its evidence factually
  did not reproduce. This is a judgement about whether a scope exclusion in another design counts as
  a recorded decision, and that judgement is the maintainer's. The row now says so and the
  disagreement is `LAF-99`.
- **Nothing could have caught it.** `DOC006`..`DOC009` check documents against the register. No rule
  checks the register against its own definitions — that a `closed` row carries a reproduction, that
  a `deferred` row names the design that deferred it. `LAF-93` found the same gap from the other
  side, where a `closed` row's reproduction could not be run.
- **`LAF-62` is also still true.** Registry A's committed index still carries three setup-bearing
  packages, so the condition that refuses a `≤2.4.0` consumer at `source add` has not gone away. The
  consumer project's nightly stopped failing on `2026-08-15` because the consumer moved to `2.6.0`,
  not because the boundary was addressed — the failed run at `05:46Z` and the green one the next
  morning are both in the acceptance repository's run list.
- **What is left.** Every row in the register has now been checked once, in whichever way its
  disposition allows. What has never been checked is the register's *shape*: whether each row obeys
  the rules the table's own header states. `LAF-93` and `LAF-99` are both instances of that, found
  by accident rather than by looking, and looking is the obvious next package.
### 2026-08-16 — overnight residue run, the register audited against its own rules
Branch `docs/audit-register-shape`, cut from `main`, carrying the previous branch's record. Every
row has been checked. This checks the table itself: does the register obey the rules its own header
states? Two do not, and both were invisible because every gate points outward — `DOC006`..`DOC009`
hold *documents* to the register and nothing holds the register to itself.
- **`LAF-101`: the register carries eight findings from one walk and omits three.**
  `PROGRESS-live-acceptance-setup-build.md` records `LAF-51`..`LAF-61` in a single findings table.
  The register has rows for `LAF-52`, `LAF-53`, `LAF-54`, `LAF-55`, `LAF-57`, `LAF-58`, `LAF-59`
  and `LAF-61`. It has no row for `LAF-51`, `LAF-56` or `LAF-60`. Those three are precisely the ones
  that were resolved: that document says *`LAF-51` is closed* and *`LAF-56` and `LAF-60` are
  documentation fixes that landed with `SBC-9`*. `LAF-56` and `LAF-60` are both `major` —
  the documented manual build could not be run as documented, and a `requires_aart` floor cannot
  protect an older consumer because the recipe is validated at source level.
- **The seeding took what was open and dropped what was closed.** The *Scope* rule cannot explain
  the split: all eleven ids come from the same pre-stream walk, so if three are outside the register
  then so are the other eight. What the omission does is leave three closures recorded as a sentence
  in a run log — which is cluster `C6`, the exact defect this register was written to end.
- **`LAF-100`: the register's opening paragraph overstates its own gate.** It says `docs_check`
  *fails when a document names a finding this file does not carry*. `DOC008` reads table rows in
  files matching `docs/testing/residue-stream-*.md` and nothing else. Measured: 28 finding ids are
  named across the 60 checked documents with no register row, and `make docs-check` passes on all of
  them. Most are pre-stream ids the *Scope* section legitimately places outside — the untrue part is
  the sentence, not the state.
- **The glob is why the walk documents are unreachable.** `_STREAM_GLOB` is
  `docs/testing/residue-stream-*.md`. Every `PROGRESS-live-acceptance-*.md` holds a findings table in
  the same shape and none of them matches, which is how three ids from one such table went
  unregistered without a diagnostic.
- **Nothing repaired.** Both are recorded `open` with where they were found. Adding the missing rows
  would be repairing the thing the fallback exists to measure, and two of them need a closure
  reproduction that only whoever landed `SBC-9` can write.
- **What is left.** The register's shape has one more untested rule: `DOC007` requires a
  reproduction for `closed` and `visible` and asks nothing of `deferred` — which is `LAF-99` from
  the previous package, now with a second instance behind it. Beyond that, the natural next package
  is the same audit applied to the live-acceptance documents: they are append-only by rule, and
  nothing enforces that either.
### 2026-08-16 — overnight residue run, the live-acceptance documents audited against their own rules
Branch `docs/audit-live-acceptance-docs`, cut from `main`, carrying the previous branch's record.
The register was audited against itself last package; this does the same for the scenario map and
the run documents. Read-only: git history and the documents themselves. No code changed.
- **The append-only rule holds, and that is worth recording as a pass.** The scenario map's whole
  history is two commits. The second, `eb82f5c`, appends `LAS-29` and `LAS-30` and deletes nothing —
  the diff has no removed lines at all. A rule that is only ever asserted is worth checking once;
  this one has been kept.
- **`LAF-102`: the map is not the register of scenarios it says it is.** It says *every scenario has
  a stable ID* and *a future run re-executes these IDs and compares against the recorded result*.
  Measured across the five run documents on `main`:
| Document | Scenario ids used | Declared in the map |
| `PROGRESS-live-acceptance.md` | 75 | all 75 |
| `PROGRESS-live-acceptance-v2.md` | none | — |
| `PROGRESS-live-acceptance-v3.md` | none | — |
| `PROGRESS-live-acceptance-receipt.md` | none — it walks a design's numbered criteria | — |
| `PROGRESS-live-acceptance-setup-build.md` | 25, all `LAB-*` | none; the map declares only `LA-0`, `LA-M`, `LA-R`, `LA-S`, `LA-U` |
- **The cause is in the title.** The file is *Live acceptance **v1** — scenario map*. It was written
  for one run, the discipline of appending to it was not carried forward, and each later walk grew
  its own record instead. Tonight's own walks append `LA-*` ids to it, so the practice is back — but
  the three documents that skipped it are still the record of what was walked.
- **This is `LAF-87` one level up.** That finding is about stressor ids continuing across four
  documents with no single place that knows the highest in use. This is the same shape for the
  scenarios themselves, and it is why a walk can report a pass against an id no future run can find.
- **What is left.** The run-header rule — tag or commit, wheel name and size, wheel sha256,
  `aart --version` — was checked only coarsely here and `-receipt.md` appears to carry no version
  line. Checking that properly means reading five headers by hand rather than counting matches, and
  it is the right size for the next package.
### 2026-08-16 — overnight residue run, the five run headers read against the pinning rule
Branch `docs/audit-run-headers`, cut from `main`, carrying the previous branch's record. The
previous package left this open with a guess; this reads all five headers by hand. Read-only, no
code changed. The rule is `DESIGN-live-acceptance-v1.md` §3 — the executable is *pinned to one commit
for the whole run* — plus the four fields the later runs converged on.
| Document | Tag or commit | Wheel name and size | Wheel sha256 | `aart --version` |
|---|---|---|---|---|
| `PROGRESS-live-acceptance.md` | commit | yes, 636 399 bytes | **absent** | yes |
| `PROGRESS-live-acceptance-v2.md` | tag and commit | yes, 473 423 bytes | **`a2edb0dc…4f47e`** | yes |
| `PROGRESS-live-acceptance-v3.md` | tag and commit | yes, 502 919 bytes | full 64 characters | yes |
| `PROGRESS-live-acceptance-setup-build.md` | commit | yes, 514 997 bytes | full 64 characters | yes |
| `PROGRESS-live-acceptance-receipt.md` | **none** | name only, **no size** | **none** | **none** |
- **`LAF-103`: the document that claims the most about its executable records the least.**
  `-receipt.md` opens *No patched executable … Everything below runs the wheel built from the
  committed tree* — a criterion the readable-receipt design raised to a requirement after `LAF-51`
  forced a patch in the previous run. Its header is titled `## Run root`, its executable row is the
  bare filename `agent_artifacts-2.6.0-py3-none-any.whl`, and `commit`, `sha256` and `aart --version`
  appear nowhere in it. `2.6.0` on `main` builds reproducibly — `fcdf95d9…`, 542 151 bytes, measured
  twice tonight — so the claim is almost certainly true. It is simply not checkable from the record,
  which is the only thing a run document exists to make possible.
- **`-v2.md`'s digest is present and useless.** `a2edb0dc…4f47e` is 13 of 64 characters. Elision is
  right in prose, where a digest is an identifier the reader recognises; in the row that pins the
  executable it is the whole value, and 13 characters match no file.
- **`-v1.md` predates the field, which is a different thing from dropping it.** It names a commit and
  a wheel built locally from it, so the executable is pinned by construction; the digest column only
  became meaningful once runs started downloading release assets, which is `-v2.md` onward.
- **Same cause as `LAF-102`.** The receipt walk was written as a check of one design's numbered
  acceptance criteria, cites `DESIGN-readable-receipt.md`, and never claims to be governed by
  `DESIGN-live-acceptance-v1.md` — so it inherited neither the scenario ids nor the run header. Two
  findings, one root: the fourth and fifth runs are live-acceptance runs by practice and not by
  document.
- **Nothing repaired**, per the brief: the headers are the record of runs that happened, and adding a
  digest to `-receipt.md` now would be writing down a number that was never observed.
- **What is left.** Every register row, the register's own shape, the scenario map, the append-only
  rule and now the run headers have each been checked once. The remaining unchecked claim of the same
  kind is the stream: `residue-stream-2026-08-15.md` says where each finding came from, `DOC008`
  checks its rows reach the register, and nothing checks the reverse — that a register row sourced
  from a stream is actually in one. That is the next package.
### 2026-08-16 — overnight residue run, the register read against the stream
Branch `docs/audit-register-vs-stream`, cut from `main`, carrying the previous branch's record.
`DOC008` checks that every stream row reaches the register; this reads the other direction. Nothing
changed but the register row and this file.
- **The direction `DOC008` enforces holds.** All 30 ids in the stream's tables have a row here. 54
  rows, 30 of them from the stream, 24 not.
- **`LAF-104`: the *Scope* paragraph is two sizes and one origin out of date.** It says the register
  was seeded from *the twenty-eight items* of the stream, and the stream carries 30. The stream's own
  *Twenty-eight deferred items* was written in `2e32975`, `LAF-63` was appended in `70a737a` and
  `LAF-64` in `3b04d5f`, and the register was created in `3ff834e` — one commit after both — copying
  a count that was already wrong. Nothing is misplaced by it: membership defines the boundary, not
  the number. The origins matter more. *Seeded from the stream, plus what implementing the response
  found* names two; of the 24 non-stream rows, 11 are the `2.6.0` work and **13 are from auditing the
  response rather than implementing it** — every `re-checking`, `re-reading` and `auditing` source
  filed tonight.
- **And the same measurement found this run's own gap.** Fifteen finding ids — `LAF-76` through
  `LAF-90` — appear in this file and in no row of the register. They were filed in the first half of
  the night, described in their iterations' entries, and listed together in the *New findings*
  paragraph above; the register never received them. `LAF-91` onward all have rows, so the
  discipline started midway. This is `LAF-101`'s shape — findings living in a run-log sentence
  instead of the table whose first line is *the single place that says what is open* — with the
  difference that this run wrote it, tonight, against a brief that says new problems go into the
  register as new rows.
- **Not fixed here, deliberately.** The brief says not to widen the package you are on, and fifteen
  rows written carelessly at the end of an iteration would be worse than fifteen rows written as
  their own. Each has an entry above to source them from.
- **What is left.** Write those fifteen rows, `open`, each with where it was found — that is the next
  package, and it is the one that makes the register true for the morning. `LAF-90` and `LAF-85` are
  the two the run log flags as worth reading first.
### 2026-08-16 — overnight residue run, the fifteen missing rows written
Branch `docs/register-the-missing-fifteen`, cut from `main`, carrying the previous branch's record.
The previous package found `LAF-76`..`LAF-90` living only in prose. This writes them into the
register, `open`, each naming the branch it was found on. Nothing was re-measured and nothing was
repaired: each row says what the iteration that filed it recorded, and where.
- **Where they were.** Eight of the fifteen — `LAF-76`..`LAF-83` — were named nowhere in this file
  except the *New findings* list. Their descriptions existed only in the commit messages of the
  branches that filed them (`87b7fbb`, `5f58aa6`, `6fcc14b`, `e598c58`, `e5af3f8`), which are
  unmerged, so on `main` those eight findings were an id and nothing else. The other seven had a
  sentence each in a run-log entry.
- **Two of the fifteen had already been filed a second time.** This is the cost of the gap, and it
  is measured rather than asserted:
| Filed as | From | Filed again as | From | One defect |
|---|---|---|---|---|
| `LAF-84` | iteration 5, the `LAF-73` walk | `LAF-91` | iteration 16, re-checking `LAF-53` | a completed undo reports itself `skipped` |
| `LAF-82` | iteration 4, implementing `LAF-69` | `LAF-100` | iteration 28, auditing the register | the register's claim that an unknown finding fails the gate is unimplemented |
- **Both pairs are left standing, both `open`, cross-linked.** The later row carries the fuller
  evidence in each case; which id retires is a maintainer's call, not a measurement, and the same
  reasoning that left `LAF-62`'s disposition alone applies here.
- **The run log's own claim was false and now says so.** The *New findings* paragraph ended *Every
  one has a register row saying where it came from*. That was true of `LAF-91` onward and untrue of
  the fifteen above it for the whole night. The sentence is corrected in place rather than deleted,
  because the point is that a summary line asserted a property nothing checked.
- **What is left.** Nothing in `docs_check` would have caught this: `DOC008` reads stream tables, and
  `PROGRESS.md` is not a checked document. A rule that fails when `PROGRESS.md` names a finding with
  no register row is the obvious answer and is a code change, so it belongs to a maintainer's
  package, not to a re-check iteration. The severities assigned tonight are first readings from the
  filing iteration's own words; `LAF-85` and `LAF-90` are the two that deserve a second opinion.
### 2026-08-16 — overnight residue run, the new rows re-checked against the code
Branch `docs/recheck-the-fifteen`, cut from `main`, carrying the previous branch's record. The
fifteen rows written last package were transcribed from other iterations' words, not measured. Five
of them are readable in the code on `main`; this reads them. All five hold, two are sharper than the
row said, and two are contingent in a way the row did not state.
| Row | Verdict on `main` |
|---|---|
| `LAF-76` | holds — `_custom_phase` takes `_minimal_env` at `setup_runtime.py:803`. **Contingent:** on `main` every adapter is equally narrow, so the gap opens only when `RS-12` merges |
| `LAF-77` | holds — `_probe_env` allows `HOME`, `_minimal_env` does not, under a docstring saying they are the same. Today's difference is `HOME`; `DOCKER_CONFIG` is the one `RS-12` adds |
| `LAF-78` | holds — `plan_artifact_scaffold` writes `artifact.json` and one payload file, and `ArtifactScaffoldOptions` has no setup field |
| `LAF-79` | holds, **one worse**: three functions carry the two-type shape on `main`, not two |
| `LAF-86` | holds — the remediation is shared by `install`, `uninstall` and `setup`, right for two of the three |
- **`LAF-79` was written from a branch, and read as if from `main`.** `_curses_singleselect`,
  `_curses_install_scope` and `_curses_install_mode` all take `wizard: bool = False` and all branch
  their return type on it. The row says two because the iteration that filed it was standing on the
  branch where the third is already fixed. Corrected in the row, with the counts for both states.
- **Two rows describe a gap that does not exist yet.** `LAF-76` and `LAF-77` are both differences
  between the docker adapters and everything else, and on `main` there is no difference to have —
  `_docker_env` does not exist here. They are real findings about the state after `RS-12` merges, and
  the rows now say so. This is `LAF-57`'s shape a second time: a finding whose truth depends on which
  branch you are standing on, filed without naming the branch.
- **No new findings.** Nothing was repaired; five rows gained the measurement they were written
  without.
- **What is left.** Ten of the fifteen are not readable from code alone: `LAF-80`, `LAF-81` need a
  build, `LAF-84`, `LAF-88`, `LAF-89`, `LAF-90` need a walk, `LAF-82`, `LAF-83`, `LAF-87` are
  document claims already measured under their duplicate ids, and `LAF-85` — the unidentified write
  to the real data root — is the one that cannot be re-checked at all without catching it happening
  again.
### 2026-08-16 — overnight residue run, the two rows that needed a build
Branch `docs/recheck-the-build-rows`, cut from `main`, carrying the previous branch's record.
`LAF-80` and `LAF-81` are claims about what building does, so they were built rather than read. A
detached worktree at `e3894fe`, removed afterwards; the repository itself was never dirtied.
- **`LAF-81` holds, and the command's own help is what it breaks.** On the clean worktree
  `wheel-digest` printed `sha256:8ed1226d…`. One comment line appended to
  `agent_artifacts/redaction.py`, `HEAD` unmoved at `e3894fe`, and the same command printed
  `sha256:19ca00a9…` — same wheel filename, exit `0`, no warning that anything was uncommitted.
  `packaging._copy_project` copies the working tree from disk and `_commit.py` is then written from
  `git rev-parse HEAD`, so the wheel carries the tag's stamp over the desk's bytes. `wheel-digest`'s
  help reads *print the digest of the wheel this commit publishes*.
- **`LAF-80` holds, with the document that omits it named.** `make wheel` leaves
  ` M agent_artifacts/_commit.py`: the committed value is `COMMIT = "unknown"`, the build writes the
  real sha and epoch. `wheel-reproducibility-v1.md` §*Verifying a published wheel* tells a verifier
  to `git checkout v<version>` and `make wheel` and never mentions that their checkout is dirty
  afterwards.
- **The two do not compound, and that is worth knowing.** `_commit.py` is the one file `make wheel`
  dirties, and `wheel-digest` overwrites it in its copy with identical content. So the dangerous
  sequence is not *build then hash* — it is any other uncommitted edit, including one made by a tool.
- **A pass, measured rather than assumed.** The documented verification — `make wheel` then
  `shasum -a 256 dist/…whl` — produced
  `8ed1226d5c2a8f3a5dd271903d95231abe2b82cca3521c5c208eac65171b72b5`, byte for byte what
  `wheel-digest` printed on the same clean tree. The two routes agree, which is the half of `LAF-75`
  that had not been checked since it was made `visible`.
- **No new findings, nothing repaired.**
- **What is left.** Of the fifteen, `LAF-84`, `LAF-88`, `LAF-89` and `LAF-90` need a walk against a
  built wheel rather than a build; `LAF-90` reproduces without a terminal by its own filing note and
  is the one worth walking first.
### 2026-08-16 — overnight residue run, `LAF-90` walked against a real wheel
Branch `docs/recheck-laf90-live`, cut from `main`, carrying the previous branch's record. The most
serious finding of the night was filed from a headless reproduction of the wizard's question loop.
This walks the whole path on a real executable instead.
**Run header.** Pre-release, **locally built** wheel — no release asset, no patched executable.
| Field | Value |
|---|---|
| AART commit | `e3894fe` (`main`, detached worktree, removed afterwards) |
| Wheel | `agent_artifacts-2.6.0-py3-none-any.whl` (542 151 bytes), built by `scripts/build_wheel.py` |
| Wheel sha256 | `fcdf95d94b8150c82570dccca154dda536ec3cac8e7c25b3e215dba124bcb174` |
| `aart --version` | `agent-artifacts 2.6.0` |
| Test venv | `$LAB90/venv` — `--no-deps`, only `agent-artifacts`, `pip`, `setuptools` |
| Sandbox `HOME` | `$LAB90/home`; the real `~` was neither read nor written |
| Scenarios | `LA-0-11`, `LA-0-12`, stressor `LAS-62` — appended to the map, nothing edited |
- **`LA-0-11` fails, which means `LAF-90` reproduces.** `registry init --minimum-version 1.0.0
  --maximum-version 2.0.0 --yes` — the two literals `tui.py:2793` and `:2796` offer at the `INIT`
  prompts — exits `0`, writes `requires_aart {min_inclusive: 1.0.0, max_exclusive: 2.0.0}`, and ends
  by advising four next commands. The first one it advises, `registry validate`, exits `1`:
  `registry-maintenance-invalid`, *registry workspace is incompatible with this AART version*, with
  `"remediation": []`. The tool writes a registry, tells the operator to validate it, and refuses.
- **`LA-0-12` passes, and it is what makes this a defect rather than a policy.** `registry init`
  with no version flags takes the **flag** defaults — `2.6.0` and `3.0.0`, printed in `init --help` —
  and `registry validate` on that registry exits `0`. Two default sets ship in one product; the one
  an operator reaches by pressing return is the stale one.
- **Severity confirmed as `high`, and the reachability is the reason.** Nothing here needs a rare
  state: a first-time maintainer accepting the tool's own suggestions gets a workspace the tool
  cannot read, and the refusal carries no remediation to get out of it.
- **The empty `remediation` is `RS-09`'s shape landing on a state the tool itself created.** `RS-09`
  is `open` on `main` and its fix is on its own branch; this walk is one more argument for it, not a
  new finding.
- **No new findings, nothing repaired.** The lab was removed and the repository was never dirtied.
- **What is left.** `LAF-88` and `LAF-89` — the emptied directory and the order-dependent
  reclamation — are the next walk, and they need an install and two uninstalls rather than a
  registry.
### 2026-08-16 — overnight residue run, `LAF-88` and `LAF-89` re-walked
Branch `docs/recheck-laf88-89`, cut from `main`, carrying the previous branch's record. Both
findings are about what `uninstall` leaves behind **after** the `LAF-47` fix, so neither is
measurable on `main` — the fix is unmerged. The walk therefore runs a wheel built from
`fix/uninstall-removes-the-file-it-made`, and says so.
| Field | Value |
|---|---|
| AART commit | `76a7f21` (`fix/uninstall-removes-the-file-it-made`, detached worktree, removed afterwards) |
| Wheel | `agent_artifacts-2.6.0-py3-none-any.whl` (542 648 bytes), **built from the branch** — no release carries this fix |
| Wheel sha256 | `73426b33ecce6d1e094d39f2689419afbfc90b5516d9c7942d5da14d5a146fd7` |
| `aart --version` | `agent-artifacts 2.6.0` |
| Sandbox `HOME` | `$LAB88/home`; the real `~` neither read nor written |
| Registry | `$LAB88/reg`, source id `lab`, a real git checkout, `hook/guard`, `mcp/atlassian`, `mcp/jira` scaffolded and built by the same wheel |
| Scenarios | `LA-U-31` and `LA-U-35` **re-executed**, not re-numbered |
- **The recorded run header reproduces byte for byte.** `PROGRESS-live-acceptance-v11.md` records
  542 648 bytes and `73426b33…` for this branch; building it again today produced exactly that. It
  is the first time a run header in this repository has been re-derived rather than trusted, and it
  is the other half of the `LAF-103` audit: the discipline is worth keeping because when the fields
  are there, they work.
- **`LAF-88` holds, with one detail the row did not have.** Install `hook/guard`, uninstall it:
  `git status --porcelain` prints nothing, and `ls -la .claude` shows a directory holding only `.`
  and `..`. `.claude/hooks/` and `settings.json` are both gone — the deeper directory *is*
  reclaimed. What survives is the one level the artifact did not itself fill.
- **`LAF-89` holds exactly as written.** Two `mcp` artifacts installed in separate commands.
  Uninstalled in install order, `.mcp.json` survives as `{"mcpServers":{}}` and `git status` reports
  `?? .mcp.json`. The same walk in a fresh repository, uninstalled in reverse order, removes the file
  and leaves the tree clean.
- **A severity was corrected, not invented.** This register carried `LAF-89` as `medium`; the walk
  that filed it records `low`. The row was transcribed from a run-log sentence rather than from the
  findings table, and now matches its source.
- **The scenario ids were re-executed, not re-numbered** — `LA-U-31` and `LA-U-35`, exactly what the
  scenario map says a later run should do. That rule works whenever the ids exist, which is the
  narrow half of `LAF-102` that is not broken.
- **One note for the next lab.** The object store under the sandbox `HOME` is written read-only, so
  a plain `rm -rf` on a lab directory fails with *Permission denied*; `chmod -R u+w` first. Expected
  for a content-addressed store, not a finding, and worth knowing before a cleanup looks like a leak.
- **No new findings, nothing repaired. The lab was removed and the repository was never dirtied.**
### 2026-08-16 — overnight residue run, `LAF-85` read from the disk it names
Branch `docs/recheck-laf85-data-root`, cut from `main`, carrying the previous branch's record.
`LAF-85` is the finding the run log flags as the one to read first: something wrote to the
operator's **real** data root at `23:34`–`23:36` while every scenario ran under a sandbox `HOME`.
It cannot be re-checked by catching it again, but the disk it happened on can be read.
**Read-only, and stated plainly:** `ls`, `find`, `stat` and one `json.load`. Nothing under
`~/Library/Application Support/agent-artifacts` was written, moved or removed by this package.
- **The episode removed content; it did not deposit any.** 43 of the 68 object shard directories
  carry mtime `2026-08-15 23:34`. A directory's mtime moves when an entry is created *or* removed —
  and **no object entry in the store has a birth time later than `20:12`**. Nothing was created at
  `23:34`, so what happened there was a removal.
- **One file changed, and it is the reference index.** `state/object-references.json`, born `23:36`,
  now carrying 34 references. AART writes atomically, so a rewrite produces a new birth time; that
  timestamp does not distinguish a first write from a later one, and it is not read as evidence of
  one.
- **A lock was taken and released.** `locks/` carries `23:36` and is empty. `state/setup/` is
  untouched since `2026-08-11 19:35`, so nothing wrote a setup record.
- **It has not recurred.** Zero entries anywhere under the root are newer than `2026-08-16 00:00` —
  across a night of continuous work, every command of it under a sandbox `HOME`. Whatever ran, ran
  once.
- **What this changes about the finding.** *Something wrote to your real data root* becomes: one
  episode, two minutes long, that swept objects out of 43 shards and rewrote the reference index,
  did not touch setup state or configuration, and has not happened again in the twelve hours since.
  The shape is a garbage collection or reference reconcile, not an install. **The writer is still
  unidentified**, which is the part of the row that stands unchanged.
- **No new findings, nothing repaired.**
- **What is left.** Of the fifteen, only `LAF-84` remains un-re-checked, and it is the duplicate of
  `LAF-91`, whose row already carries a live measurement. That closes the re-check of the fifteen.
### 2026-08-16 — overnight residue run, which code could have written at `23:34`
Branch `docs/laf85-which-code-sweeps`, cut from `main`, carrying the previous branch's record. The
previous package read the disk; this reads the code that could have produced what is on it.
Read-only, no code changed.
- **The previous entry's reading was too strong, and this corrects it.** It ended *the shape is a
  garbage collection or reference reconcile, not an install*. An install followed by an uninstall
  produces the identical trace: entries created and then removed move a shard's mtime and leave no
  surviving birth, and `write_references` is wired into `lifecycle/io.py`, `installation/io.py` and
  `setup_engine/io.py`, so an ordinary uninstall rewrites the index under exactly the lock that was
  taken. What stands is the measurement — 43 shards touched, nothing new survives, one file written,
  no setup record, no recurrence. What does not stand is calling it a sweep.
- **And the mechanism it named turns out to be the one nobody can run — `LAF-105`.**
  `application/store.py:110` implements `collect_garbage` properly: take the store lease, read the
  references, inventory the objects, delete every digest no reference names. **Nothing in the package
  calls it.** It is exported from `agent_artifacts.application`, `GcRequest` from
  `agent_artifacts.store`, and the only callers anywhere are two tests, both on temporary roots. None
  of the CLI's 38 subcommands reaches it.
- **So the durable store only grows.** On this machine's real data root, read-only: 79 object entries
  against 34 reference entries. Nothing an operator can type reclaims the difference.
- **That makes install-then-uninstall the likelier reading of `23:34`** — a walk that forgot its
  sandbox `HOME` and then cleaned up after itself — rather than a collector that has no door.
  Likelier, not established: the writer is still unidentified, and that half of `LAF-85` is
  unchanged.
- **`LAF-105` is not `RS-05`.** That row is about a module nothing imports. This one is finished,
  tested and correct code with no way in — the door is missing, not the room.
- **What is left.** The natural next question is whether anything else in `application/` is
  unreachable the same way. That is one grep against the CLI's dispatch table and the right size for
  a package.
### 2026-08-16 — overnight residue run, the rest of the application layer measured
Branch `docs/unreachable-application-surface`, cut from `main`, carrying the previous branch's
record. `LAF-105` found one unreachable entry point; this asks whether it is alone. Every public
function in `agent_artifacts/application/` was counted for callers outside its own module,
`application/__init__.py` and `tests/`. Read-only, no code changed.
**Twenty have a caller. Eight have none.**
| Function | Module | Reading |
| `collect_garbage` | `store.py` | `LAF-105` — the store cannot be reclaimed |
| `object_status` | `store.py` | the projection of verified / absent / corrupt, unwired |
| `compile_sources` | `compiler.py` | with it `CompilerPorts`, `CompilerSteps`, and every `CompilerRequest` — built nowhere outside the compiler package |
| `prepare_registry_format` | `registry_commands.py` | its `finalize_` counterpart *is* called |
| `prepare_native_promotion` | `registry_maintenance.py` | same shape — the finalize half is wired, the prepare half is not |
| `save_user_configuration` | `configuration.py` | the unchecked write beside a checked one that is used |
| `save_user_configuration_for_source_management` | `configuration.py` | superseded, and its replacement's docstring says so — *the CFG02 replacement for* |
| `recover_user_configuration` | `configuration.py` | the recovery path, unwired |
- **Two of the eight are honest supersession.** `save_user_configuration_checked` names what it
  replaced. Left standing is a defensible choice; it is the other six that are simply unwired.
- **`compile_sources` is the one to look at.** It is the functional compiler orchestration, and it
  is called from fifteen places in `tests/compiler_pipeline_test.py` and from nowhere else in the
  repository.
- **The cost is what green means.** All eight are covered by tests, so the suite reports these paths
  as working. It cannot report that nothing runs them. A coverage number counts lines executed by
  the suite, not lines an operator can reach, and eight entry points is where that difference stops
  being theoretical.
- **Recorded as `LAF-106`, `open`.** Nothing repaired: deleting or wiring any of these is a design
  decision, and two of them are deliberate.
- **What is left.** The same measurement one layer out — `agent_artifacts/io/` and
  `agent_artifacts/store/` — would say whether this is an `application/` habit or a package-wide
  one. `RS-05` is already one instance in `io/`.
### 2026-08-16 — overnight residue run, the same measurement one layer out
Branch `docs/unreachable-io-store`, cut from `main`, carrying the previous branch's record.
Read-only, no code changed.
- **The method needed fixing first, and it changed nothing.** The previous package counted callers
  *outside the defining module*, which marks a function dead when its only caller sits beside it —
  `io/config_cas.py`'s `write_configuration_checked` is exactly that, called by
  `checked_config_writer` two functions below. This package rebuilt the measurement as call-graph
  reachability: reached if a reachable function calls it, or any module refers to it outside an
  import. **All eight of `LAF-106`'s survive the stricter rule**, and the note in that row now says
  so.
- **`agent_artifacts/store/` is clean** — 5 of 5 reachable. Worth recording as a pass.
- **`agent_artifacts/io/` has 11, and they cluster**, which is `LAF-107`:
| Cluster | Functions | Reading |
| `io/security_analyzers.py` | `run_analyzer_process`, `write_input`, `read_stream`, `stop_process` | only `resolve_executable` is imported from this module, by `commands/security.py`. The process runner beside it is unwired — the mechanism half of `LAF-15`, which is that no command feeds `security scan` its input |
| `io/fs.py` | `copy_tree`, `read_json`, `remove_path`, `symlink_tree` | utilities with tests and no caller. **`symlink_tree` is not a missing feature** — `--install-mode symlink` is implemented in `installation/application.py` with its own handling, so this is a superseded helper |
| `io/cache.py` | `cache_dir`, `ensure_snapshot` | `RS-05`'s dead module, counted here for completeness |
| `io/object_store.py` | `materialize_compiler_object` | the adapter side of the compiler orchestration `LAF-106` records as unreachable — the same hole from the other end |
- **Severity `low`,** against `LAF-106`'s `medium`: helpers and adapters, not entry points a design
  promised. The one that carries weight is the analyzer cluster, because it is a second view of a
  finding that already exists.
- **Nothing repaired, nothing new beyond the row.**
- **What is left.** Three packages measured, one clean. `agent_artifacts/protocol/`,
  `security/` and `registry_commands/` are the remaining large ones, and the same script covers them
  — but the interesting question has been answered: the habit is real, it is concentrated in
  adapters and orchestration, and `store/` shows it is not universal.
### 2026-08-16 — overnight residue run, the whole package measured at once
Branch `docs/unreachable-whole-package`, cut from `main`, carrying the previous branch's record.
Read-only, no code changed. The script was rewritten from scratch rather than extended, so the
overlap with the last two packages is a replication rather than a repeat.
**The rule, stated so it can be argued with.** A public top-level function is *reached* when its
bare name is reachable from a seed. Seeds are every name a module refers to at module scope —
dispatch tables, class bodies, decorators, argument defaults — plus `main`, for the console script
`agent_artifacts.cli:main`. A reachable function makes every name in its body reachable. The rule is
name-based, so it over-approximates: any same-named function anywhere in the package rescues a dead
one. Every number below is therefore a floor.
**103 of 482 public top-level functions are unreachable.** A fifth of the surface.
| Package | Unreachable | Reading |
| `security/` | 15 of 39 | `evaluate_security_policy` has no caller and `summarize_bundle_security` is called only from inside it, so the policy chain is dead top to bottom, and the analyzer protocol goes with it. `commands/security.py` imports attestations, baseline, cache, projections — none of these |
| `domain/` + `fp.py` | 13 of 19, 10 of 11 | two functional cores, both dead: `LAF-109` |
| `compiler/` | 9 of 12 | the far side of `LAF-106`'s `compile_sources` |
| `application/` | 8 of 27 | **the identical eight names `LAF-106` lists**, from a script written independently |
| `io/` | 8 of 38 | `LAF-107`, corrected — see below |
| `commands/`, `configuration/`, `consumer/`, `installation/`, `reporting/`, `sources/`, `store/` | 0 | the wiring is real where operators reach it |
- **The security cluster is the one to read.** It is `LAF-15`'s mechanism generalised. Last
  iteration found the adapter unwired; this one finds the policy evaluator and the analyzer protocol
  unwired as well. The half of the security package that would *run* an analyzer and *judge* its
  output has no path from any command.
- **Five root modules have no importer anywhere in the package**: `compatibility.py`, `fp.py`,
  `hashing.py`, `policy.py`, `registry_publication.py`. All five ship — read out of the wheel built
  at this commit, `agent_artifacts-2.6.0-py3-none-any.whl`, 542 151 bytes, sha256 `fcdf95d9…`. Four
  have a test file and no caller. `hashing.py` has neither, and is a 22-line duplicate of
  `protocol/hashing.py`.
- **`registry_publication.py` is not a new observation.** `LAF-03` recorded it on `2026-08-13`: the
  module holding the SPDX allowlist enforces nothing, because nothing imports it. It is outside the
  register's stated scope, so the register's own rule applies — an older id gets a row the first
  time it is referred to again — and `LAF-03` now has one, `open`, re-measured today.
- **`LAF-107` is corrected: `io/` is 8, not 11.** `write_input`, `read_stream` and `stop_process`
  are nested helpers *inside* `run_analyzer_process`, and the previous script did not tell a nested
  `def` from a top-level one. The reading is unchanged — that module still has exactly one unwired
  public entry point — but the arithmetic was wrong and the row says so.
- **New findings: `LAF-108`** (medium, the whole-package measurement) and **`LAF-109`** (low, the
  duplicated cores). Nothing repaired.
- **What deletion would cost.** `LAF-106` found two of its eight were honest supersession, correctly
  left in place. So 103 is a list to read, not a list to delete, and no line of it should be removed
  on this measurement alone.
### 2026-08-16 — overnight residue run, the dead surface read against the shipped commands
Branch `docs/designs-vs-unreachable`, cut from `main`, carrying the previous branch's record. No code
changed. The measurement of the last three packages says a fifth of the package cannot be reached;
this one asks the question that follows — **what does the shipped CLI say about the parts that
cannot be reached?** Walked on the wheel built at this commit, `agent_artifacts-2.6.0-py3-none-any.whl`,
542 151 bytes, sha256 `fcdf95d9…`, installed with `--no-deps` into a throwaway venv, sandbox `HOME`.
- **AART lists analyzers it cannot run.** `aart security analyzers` prints `ruff: available` and
  four *not installed*. `aart security suites` describes three suites, two of which promise to add
  discovered providers. `security scan --help` has no flag that selects either. The whole execution
  half — `run_analyzer_process`, `run_tool_adapter`, `run_protocol_analyzer`, the handshake and scan
  encoders, `evaluate_security_policy` — is unreachable, while the discovery half is wired, which is
  exactly why the listing works. **`LAF-110`**, medium, `LA-R-42`, `LAS-63`. It is not `LAF-15`:
  that one is that no command emits the envelope `scan` reads; this one is that no command runs a
  provider even when the envelope is in hand.
- **Two of `LAF-106`'s eight are bypassed wrappers, not missing doors.** `aart registry format`
  works — walked live in a throwaway Git checkout, plan printed, `unchanged` for both files, exit
  `0`. It reaches `plan_registry_format` **directly** from `curation/runtime.py:856`, past the
  application wrapper. `promote-native` does the same at `:894`. The same file uses the application
  wrapper `prepare_registry_init` at `:417`. One runtime, two layers, three neighbouring commands:
  **`LAF-111`**, low, `LA-R-43`, `LAS-64`.
- **So the eight now read: three missing doors, two bypassed wrappers, three superseded writers.**
  The three missing ones are the interesting ones, and the design already describes them —
  `SPEC-aart-1.0.md` §20 lists `aart store status|verify|gc` and `aart compile` as design targets,
  and §16 specifies `store gc` as *dry-run by default, under a global lock*. `application/store.py`
  implements precisely that, `GcRequest.execute` defaulting to `False`. **The room is built to
  specification and the door was never cut.** That is a better description of `LAF-105` than *dead
  code*, and it argues against deletion as firmly as anything found tonight.
- **`LAF-15` gets its register row**, on the same rule that gave `LAF-03` one last iteration: my own
  two rows referred to it, so the register owed it a row. Re-measured on the shipped surface — the
  word *envelope* occurs twice in the CLI, in the help that consumes one and the error that rejects
  one, and no command writes one. Still true.
- **Four ids are still named in this register with no row: `LAF-28`, `LAF-51`, `LAF-56`, `LAF-60`.**
  `LAF-28` is quoted as an example of prose closure, not referred to as a finding. The other three
  are `LAF-101`'s own subject — the register omits exactly the three rows that were resolved — so
  writing them would be repairing `LAF-101` from inside a package that is not `LAF-101`'s. Left,
  deliberately, and recorded here so the morning knows it was a decision.
- **Nothing repaired.**
### 2026-08-16 — overnight residue run, every command run cold
Branch `docs/cold-command-surface`, cut from `main`, carrying the previous branch's record. No code
changed. Same wheel as the last package — `agent_artifacts-2.6.0-py3-none-any.whl`, 542 151 bytes,
sha256 `fcdf95d9…`, installed `--no-deps` into a throwaway venv. Every leaf of `build_parser()` run
with **no arguments**, in an empty directory, under a sandbox `HOME` (`LA-0-13`, `LAS-65`).
**The pass first, because it is the headline. 38 of 38 leaves refuse or answer cleanly. Zero
tracebacks.** The distribution:
| Exit | Count | What they are |
| `2` | 20 | argparse rejecting missing required arguments, before any product code runs |
| `1` | 13 | typed refusals: six `marketplace` (all with `remediation:`), seven `registry` (none with it) |
| `0` | 5 | `source list`, `source sync`, `source health`, `security analyzers`, `security suites` — queries that answer honestly with nothing configured |
- **`RS-09` reproduces on `main` from the other side.** Its fix is on a branch and not merged, so
  this walk sees the old shape: seven `registry` refusals with no remediation, beside six
  `marketplace` refusals that all carry one. Nothing new — a second, independent confirmation that
  the finding was stated correctly.
- **The `registry` group refuses in two renderings** — `validate`/`audit`/`test` with a
  `registry <verb>: failed` header and an indented error, `format`/`lock`/`build`/`diff` with a bare
  `error:` line that never names the command. **`LAF-112`**, low.
- **`SPEC-aart-1.0.md` §20 is wrong in both directions.** It calls the implemented slice
  `source add|list` and `marketplace list`, when 38 leaves under 6 groups ship; and it speaks of the
  *retained legacy `list/install/update/setup` compatibility commands*, none of which exists — each
  prints the top-level usage and refuses. **`LAF-113`**, medium. It is a checked current document,
  so this is not a dated record disagreeing with today; it is a specification describing a product
  that is not the one in the wheel.
- **Two counts other rows rest on are now exact.** `LAF-105` says *38 subcommands*: confirmed by
  enumeration. `LA-0-02` recorded *15 top-level / 49 leaves* at v1; today it is `6 / 38`, which is
  consolidation into groups rather than lost function — every v1 leaf found so far has an address
  under one of the six.
- **Nothing repaired.**
### 2026-08-16 — overnight residue run, the machine channel walked cold
Branch `docs/json-contract-cold`, cut from `main`, carrying the previous branch's record. No code
changed. Same wheel, same sandbox: every leaf that accepts `--json` run with it, in an empty
directory, under a sandbox `HOME` (`LA-0-14`, `LAS-66`). Yesterday's walk read what an operator
sees; this one reads what a script sees.
**The machine channel is in better shape than the prose. 34 of the 38 leaves accept `--json`, and
every one of them returns valid JSON on stdout** — `schema_version`, `ok`, `operation`, and typed
diagnostics carrying a code, a severity, a message and a remediation list. Two examples from the
walk, both refusals:
| Command | Code | Remediation |
| `marketplace list --json` | `no-source-configured` | *run `aart source add --help` …* |
| `registry format --json` | `registry-workspace-invalid` | `[]` |
- **`RS-09` is visible structurally.** The registry diagnostics carry `remediation: []` — the field
  is there and empty, which is exactly how the finding was written, seen now from the JSON side.
- **`LAF-112` is a prose problem only.** The two registry renderings carry *different* codes —
  `registry-command-invalid` for the workspace refusals, `registry-workspace-invalid` for the
  checkout ones — so a machine consumer can distinguish what a human cannot grep. That note is now
  in the row.
- **The group written for machines is the one with no machine channel.** `reporting
  validate-event`, `validate-issue` and `aggregate` have no `--json`, and neither does `upgrade`.
  `aart reporting validate-event <invalid file>` prints one line — `usage report is invalid` — and
  exits `1`. No code, no field, no pointer, no remediation. Its consumer is registry CI.
  **`LAF-115`**, medium.
- **Three of the SPEC's sixteen stable error codes are emitted nowhere.** `import-lossy`,
  `import-stale` and `lock-stale` exist only inside `INITIAL_ERROR_CODES`; `no-source-configured`
  has one emission site. That tuple has a single reference in the repository, in a test, so nothing
  requires an emitted code to belong to it — and 124 distinct codes are constructed. Where the SPEC
  offers `lock-stale`, the store emits `store-unavailable`. **`LAF-114`**, low.
- **Nothing repaired.**
### 2026-08-16 — overnight residue run, watching the disk while the commands run
Branch `docs/who-writes-when-cold`, cut from `main`, carrying the previous branch's record. No code
changed. Same wheel and venv; a fresh sandbox `HOME` per run, and for the second half a
`source-local` source built from the `RS-08` lab's two-artifact collection.
**Part one, the cold pass. All 38 leaves run with no arguments write nothing at all** — zero files
created under `HOME` and zero in the working directory, for every leaf, including the five that
exit `0`. A refused command does not create the data root.
**Part two is the one that matters.** Watching the object store across a review, an install and an
uninstall (`LA-U-36`, `LA-U-37`):
| Step | Objects | References | Shard mtimes | Birth times |
|---|---|---|---|---|
| after `source add` | 0 | absent | — | — |
| `install` **without** `--yes` | **6 files, 2 objects** | absent | `13:04:05` | `13:04:05` |
| `install --yes` | 6 | 1 | `13:04:26` | **still `13:04:05`** |
| `uninstall --yes` | **6** | **0** | `13:04:28` | still `13:04:05` |
- **The review that says it changes nothing writes to the durable store.** Its own help says
  *Without `--yes` the command prints the reviewed plan and exits without changing anything*. It
  exits `0` saying *Reviewed only*, and leaves two materialised objects behind with no reference
  index. A refused install — `--profile nosuch --yes` — leaves the same deposit, so materialisation
  happens before the profile is even validated. **`LAF-116`**, high, and it is the first `high` of
  the night that is not about the security surface.
- **`LAF-105`'s ratio now has a cause.** 79 objects against 34 references on the real root is what
  reviews and refused installs leave behind, and `collect_garbage` — the sweep that would remove
  them — has no command.
- **`LAF-85`'s mechanism is reproduced, and its first reading is refuted by measurement.** An
  install of already-present objects moved both shard directory mtimes *without giving any object a
  new birth*, and the uninstall moved them again, rewrote the reference index with a new birth time
  and zero references, and left `locks/` empty with a fresh mtime. That is the `23:34`–`23:36`
  signature item for item. A moved shard mtime with no new birth does **not** mean something was
  removed. The writer is still unnamed; the shape is no longer evidence of a sweep.
- **Nothing repaired.** `LAF-116` is a code change with a design question inside it — whether a
  review may fill the cache at all — and that is a decision, not a fix to make at 13:00 unattended.
### 2026-08-16 — overnight residue run, how far `LAF-116` reaches
Branch `docs/laf116-how-far`, cut from `main`, carrying the previous branch's record. No code
changed. Same wheel, fresh sandbox `HOME`, the same `source-local` collection.
**Two things in last iteration's row were wrong, and the measurement says so.**
| Command | Objects after |
|---|---|
| `source add` | 0 |
| `marketplace list` | 0 |
| **`marketplace status --profile claude`** | **2** |
| `source sync` | 2 |
| `install` without `--yes`, run three times | 2, 2, 2 |
| `install` without `--yes`, a different coordinate from the same collection | 2 |
- **The growth is not per invocation.** The store is content-addressed, so the same review three
  times leaves the same two objects. It grows once per distinct object ever resolved and never
  shrinks. The row said *grows by every review*; that is corrected.
- **The review is not the earliest depositing path.** `marketplace status` — a query — deposits the
  same two objects. `marketplace list` and `source sync` deposit nothing. The rule is: the first
  command that resolves an artifact to its content materialises it, whatever it is called.
- **Severity corrected `high` → `medium`** on that basis, and the reason is written into the row.
  The false sentence in the help text stands, the unremovability stands, the unbounded part does
  not.
- **`source remove` does not remove the content: `LAF-117`, medium.** `source remove --alias lab
  --yes` exits `0` saying *source removed; snapshot discarded*, and it is — `sources/` is empty,
  `config.json` lists none, `marketplace list` refuses with *no source configured*. The two objects
  and their six files remain, 24 KB, with no reference index, no snapshot naming them and no
  command that can list them: `object_status` is one of `LAF-106`'s unreachable eight. *Removed*
  means removed from the configuration, not from the disk, and nothing in the CLI shows the
  difference.
- **Nothing repaired.**
### 2026-08-16 — overnight residue run, the managed block round trip
Branch `docs/round-trip-residue`, cut from `main`, carrying the previous branch's record. No code
changed. Same wheel, fresh sandbox `HOME` per case, the `RS-08` lab's `memory/house` artifact, whose
install effect is `managed-block` (`LA-U-39`, `LAS-70`).
**This package found nothing new, and that is the result.** Four cases, all correct on `main`:
| Case | Install | Uninstall |
| No instruction file | writes `CLAUDE.md`, 147 bytes | **removes the file and `.agent-artifacts/` entirely** |
| An unowned `CLAUDE.md` present | **refuses**, `unowned or drifted content; use force`, nothing touched | — |
| The same, with `--force` | prepends a delimited block, 45 → 193 bytes | **restores the operator's 45 bytes exactly**, file kept |
| Forced, then the operator edits the file by hand | — | removes the block only; the original *and* the later hand-written section both survive |
- **That is the behaviour the `LAF-47`/`RS-10` design note argued for**, and for this artifact kind
  it is already true on `main`: remove the file AART made, never the file it did not.
- **It is not `RS-10`'s case.** That one is the config merge — `.mcp.json` and
  `.claude/settings.json` — which this fixture has no artifact for. Nothing here says anything about
  whether `RS-10` reproduces; a different path was measured and it passed.
- **`LAF-88` is wider than hooks and older than the branch it was found on.** Measured on a wheel
  built from `main`: install a *skill*, uninstall it, and `~/.claude/` (user scope) or `.claude/`
  (project scope) stays behind, empty, with the skill directory and payload gone. The row said
  `settings.json` and a hook; the truth is every artifact whose destination sits under the harness
  directory. Noted in the row, no new id — this register has already paid once for filing the same
  defect twice.
- **`.agent-artifacts/manifest.json` and `state.lock` are removed cleanly** when the last artifact
  in a project goes.
- **Nothing repaired, nothing new filed.**
### 2026-08-16 — overnight residue run, the config merge round trip
Branch `docs/mcp-merge-round-trip`, cut from `main`, carrying the previous branch's record. No code
changed. Same wheel built from `main`, fresh sandbox `HOME` and a fresh repository per case, two
`mcp` artifacts authored into the `RS-08` lab source — effect `merge-json`, destination `.mcp.json`
(`LA-U-40`, `LAS-71`). This is the case row 47 said it had not measured.
| Case | After install | After uninstall |
| One artifact, project scope | `.mcp.json` holds the `alpha` server; `.agent-artifacts/{manifest.json,state.lock}` | **`.mcp.json` stays as `{"mcpServers":{}}`**; everything else removed |
| Two artifacts, uninstalled in install order | both servers in one file | `{"mcpServers":{}}`, nothing else |
| Two artifacts, uninstalled in reverse order | both servers in one file | `{"mcpServers":{}}`, nothing else — **the same** |
| The operator wrote `.mcp.json` first | install **succeeds first try, exit `0`**; file holds `alpha` *and* `mine` | `{"mcpServers":{"mine":{"command":"my-server"}}}` — the operator's server intact |
- **`RS-10` reproduces on `main` exactly as the row states.** The emptied file is left behind. Its
  fix lives on `fix/uninstall-removes-the-file-it-made` and is unmerged, which is the expected shape
  for this run, not a regression.
- **`LAF-89` is narrower than it reads.** On `main` neither uninstall order reclaims the file, so
  the asymmetry that row describes is introduced *by the fix*: the branch removes the file in one
  order and leaves `main`'s behaviour in the other. The remainder of an improvement, not a defect in
  it. Written into the row.
- **New: the ownership gate is not the same for both effects — `LAF-118`, low.** The same command
  refuses a `memory` artifact when `CLAUDE.md` already exists and is not AART's (*unowned or drifted
  content; use force*), and installs an `mcp` artifact into an operator-written `.mcp.json` without
  asking. Both round trips are safe, and the difference is arguable — a merge owns a key, a managed
  block owns a file. What is not arguable is that no document says which effects gate and which do
  not, so an operator learns it by being warned once and not the next time.
- **Nothing repaired.**
### 2026-08-16 — overnight residue run, the morning's merge simulated
Branch `docs/merge-simulation`, cut from `main`, carrying the previous branch's record. No code
changed, and **no branch was touched**: every merge below was computed with `git merge-tree
--write-tree` and chained with `git commit-tree`, which writes objects and no references.
The register's `closed` rows are exhausted and its `visible`/`deferred` rows were re-checked in rows
27 and 44, so this package re-checks a claim of my own instead — the merge instruction at the top of
the overnight section, which is the sentence Michal acts on first.
**The pass, and it is the larger half.** Every fix branch keeps the per-iteration rule. For all
fifteen rows the run closed — `RS-01`, `RS-02`, `RS-04`, `RS-07`, `RS-08`, `RS-09`, `RS-10`,
`RS-12`, `LAF-45`, `LAF-47`, `LAF-49`, `LAF-64`, `LAF-69`, `LAF-73`, `LAF-75` — the row on that
branch reads `closed` *and* carries an evidence column of 273 to 735 characters, against 1 to 277 on
`main`. No branch flipped a disposition without writing what proves it.
**The failure is mine, in this file.** *Take both sides* is wrong for the register:
| Measured | Result |
|---|---|
| Fourteen fix branches merged into `main` in sequence | **13 conflict**; only the first is clean |
| The register after resolving every conflict by taking both sides | **11 ids appear twice**, one row `open` and one `closed` |
| Files that conflict | `PROGRESS.md` 13×, register 8×, scenario map 8×, `registry_commands/planning.py` **2×** |
- **Eight of the fourteen merge the register with no conflict at all, and four of those eight still
  duplicate a row** — `LAF-87`, `LAF-79`, `LAF-82`/`LAF-83`, `LAF-84`/`LAF-85`. A branch filed its
  own new finding as a row; `docs/register-the-missing-fifteen` later wrote the same id from
  `PROGRESS.md`; the two rows sit far apart, so Git merges them cleanly into a file that names the
  same finding twice. **Nothing warns you** — `docs_check.py` does not read the register, which is
  `LAF-100`'s subject, and duplicate ids are `LAF-101`'s, measured here from the merge direction.
- **`LAF-119`, medium**, is the finding: resolving this run's branches the way this file told you to
  produces a register that answers *is it fixed?* with both answers for eleven findings.
- The paragraph is corrected in place with the per-row rule that does work. It is a current
  document and its purpose is to be right in the morning; the dated documents are untouched.
- **Nothing repaired** — no branch, no code, no resolution committed. The simulation left objects in
  `.git` and no reference.
### 2026-08-16 — overnight residue run, the two rows nothing had ever checked
Branch `docs/recheck-c5-deferred`, cut from `main`, carrying the previous branch's record. No code
changed. Live half against the same locally built `2.6.0` wheel in the throwaway venv, sandbox
`HOME`, a real `git init` repository and a hand-built source tree (`LA-S-17`, `LA-S-18`, `LAS-72`,
`LAS-73`).
Every register row now carries a check except two: `LAF-43` and `RS-03`, the cluster-C5 pair, whose
evidence column was a pointer to a design rather than a reproduction. Row 27 covered the other two
non-`open` dispositions. These are the last.
| Attempt | Result |
|---|---|
| `source add --kind source-git --location file:///…/repo` | exit `1`, *source URL must be a safe credential-free Git location* |
| the same with a plain absolute path | exit `1`, same message |
| `--kind registry-git` with `file://` | exit `1`, same message |
| `source add --kind source-local` on a tree with one symlink | exit `1`, *local source symlinks are forbidden: artifacts/skill/demo/payload/alias.md* |
- **`LAF-43` holds, and it is stricter than the row says.** The refusal lands in
  `configuration/schema.py:201` — the config validator — *before* the transport check at
  `sources/git.py:198` runs. And the switch that would allow it is dead: `allow_local_transport`
  defaults `False`, all three `GitSnapshotRequest` construction sites in the package leave the
  default, and `curation/runtime.py:241` passes `False` by hand. Only two test modules ever set it
  `True`. Rehearsing a vendoring locally would take two changes, not one.
- **`RS-03` holds.** One symlink anywhere aborts the whole acquisition; no flag relaxes it. The two
  channels refuse it differently — the local reader names the path and the word *symlink*, the Git
  reader accepts only file modes `100644`/`100755` and calls everything else *an unsafe entry*.
  Because `LAF-43` blocks the Git channel locally, the vaguer of the two messages is the one no
  operator can reach.
- **No new findings.** C5's claim — *the tool's own refusals block rehearsing the tool* — is exactly
  what the measurement shows, from both ends.
- **Nothing repaired.**
### 2026-08-16 — overnight residue run, the scenario map read across every branch
Branch `docs/scenario-id-collision`, cut from `main`, carrying the previous branch's record. No code
changed. Nothing was walked: this is a reading of `docs/testing/live-acceptance-scenarios.md` on all
fifty branches at once, prompted by a simpler question — *do tonight's scenario ids appear in any run
document?* On the chain they appear in none, because `PROGRESS-live-acceptance-v4`..`v12` live on the
fix branches. That answer was a distraction. The real one was next to it.
**Row 50 gave two scenarios ids that were already taken.**
| | |
|---|---|
| `fix/status-names-the-missing-source-rs07`, `04:12` | `LA-S-11` *the project is still readable after the last subscription goes*, `LA-S-12` *fetching still refuses without a source* |
| `docs/recheck-c5-deferred`, `14:28` | `LA-S-11` *a local repository offered as an upstream*, `LA-S-12` *a source tree containing a symlink* |
The cause is mechanical and it will happen again: every branch is cut from `main`, so the next free
id is read from a copy of the map that does not contain the other branches' ids. `main` holds 113
rows, this chain 138, and **40 ids exist on one branch and nowhere else** — `LA-0-07`..`LA-0-10`,
`LA-R-31`..`LA-R-41`, `LA-S-13`..`LA-S-16`, `LA-U-31`..`LA-U-35`, `LA-M-08`..`LA-M-15`,
`LAS-31`..`LAS-33`, `LAS-57`..`LAS-61`.
- **Corrected here, not hidden.** The newer pair is renumbered to `LA-S-17` and `LA-S-18`, past the
  `LA-S-16` that `fix/broken-registry-descriptor-fails-rs08` holds. The `04:12` rows keep their ids.
  No id changed meaning, which is what the append-only rule protects; the register rows for `LAF-43`
  and `RS-03` and row 50's entry now cite the new pair.
- **`LAF-120`, medium.** Nothing computes the next free id across branches, and no gate reads this
  file: `docs_check.py` covers `docs/plan`, `docs/design`, two released documents and the stream, and
  the map is in none of them. A repeated id makes a walk unciteable, which is the one thing a stable
  id is for.
- **The other four ranges this run appended are clean** — `LA-0-13`/`14`, `LA-R-42`/`43`,
  `LA-U-36`..`40`, `LAS-63`..`73` all sit above every branch's highest. `LA-S-*` was the one phase
  where a fix branch had gone further than the chain could see.
- **Nothing else repaired.**
### 2026-08-16 — overnight residue run, the nine new run headers
Branch `docs/audit-new-run-headers`, cut from `main`, carrying the previous branch's record. No code
changed and no run document was edited — `v4`..`v12` are run records on their own branches and stay
as written. Row 30 read the five run headers that existed this morning; these nine did not exist
then.
| Field the rule asks for | How many of the nine carry it |
|---|---|
| A tag or commit under test | **2** — `v4` (`87b7fbb`), `v5` (`1c659a3`) |
| Wheel name | 9 |
| Wheel size | 7 — `v6` and `v7` omit it |
| Wheel sha256 | 9 |
| `aart --version` | 9 |
| Said plainly to be a locally built, unreleased wheel | 8 — `v5` says it by describing the two wheels it builds rather than in a sentence |
- **`LAF-121`, medium.** Seven headers write *AART commit under test* as a branch name. A branch is
  not a pin: it moves, and it can be deleted after a merge, at which point the run cannot be
  re-derived from its own record. `LAF-103` is the same defect one degree worse — a header with no
  commit, size, digest or version at all.
- **The two thinnest records were re-derived, and both hold.** A wheel built in a detached worktree
  from `eedc4a0` is **543 422 bytes, `3674e1c9…`**; from `ac12a6a`, **542 418 bytes, `941fae3d…`**.
  Both digests are exactly what `v6` and `v7` recorded. That is the second and third run header in
  this repository to be re-derived from scratch, after `v11` in row 36.
- **What that pair of facts means together:** the records are accurate, and their accuracy is
  currently provable only because nothing has been merged or pruned yet. The fix is a commit sha in
  the header, which costs one `git rev-parse` at write time.
- **Nothing repaired**, and the worktrees used for the rebuild were removed.
### 2026-08-16 — overnight residue run, costing the two fixes to do first
Branch `docs/cost-the-first-two-fixes`, cut from `main`, carrying the previous branch's record. No
code changed. Reading only, and deliberately narrow: I recommended two fixes to start with, and a
recommendation is worth more when the cost is measured rather than guessed.
**`LAF-90` — four literals, and their replacements already exist.**
| Where | What |
|---|---|
| `tui.py:2793`, `:2796` | the prompt defaults, *Minimum AART version [1.0.0]* and *Maximum AART version (exclusive) [2.0.0]* |
| `tui.py:2806`, `:2807` | the same two again, as the fallback when an operator presses return |
| `curation/model.py:26`, `:27` | `_DEFAULT_MINIMUM_AART = str(EXECUTABLE_VERSION)` and the next major — **on `main`, today** |
Above those two constants sits a comment that describes this defect in advance: literals go stale
every release and eventually make the pair unsatisfiable. The package already knows the rule; the
wizard is the one place that did not get it. Exporting the constants and using them is the fix.
**`LAF-105` — the collector is not missing, only its verb.** Present on `main`:
`collect_garbage` (`application/store.py:110`); `GcRequest` with `execute: bool = False`, which is
the dry-run-by-default the SPEC asks for; `GcPlan`; and both adapters the ports need,
`inventory_objects` (`io/object_store.py:469`) and `delete_object` (`:510`).
`docs/store/content-addressed-store-v1.md` specifies plan-or-execute through injected ports under
the global lease, and `SPEC-aart-1.0.md` lists *global garbage collection* among the operations that
protocol covers. What is absent is any path from `cli.py`.
- **That makes the sequencing clear.** One command surface closes `LAF-105`, and it is also the only
  thing `LAF-116` and `LAF-117` need — today an operator can see unreferenced objects accumulate and
  has no way to remove them, because the code that removes them cannot be called.
- Both costings are written into their register rows, so the morning reader gets them next to the
  finding rather than in a run-log entry.
- **Nothing repaired.**
| `RS-12` | `fix/setup-docker-credentials-rs12` | done — code, unit evidence, and a live walk against two executables one commit apart ([v4](docs/testing/PROGRESS-live-acceptance-v4.md)) |
