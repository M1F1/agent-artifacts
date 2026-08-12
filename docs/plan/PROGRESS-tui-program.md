# Progress record: TUI program

Resume file. Written so that this document plus the repository is enough to continue without any
conversation history.

## Goal

Make the `aart` TUI legible and predictable, and make its failures honest. Three tracks, in this
agreed order:

1. **ERR05a — constrain the curses fallback.** Done.
2. **TUI legibility program.** Current.
3. **Typed wizard errors, ERR01 onward.** After legibility, so diagnostics render as records
   through the `tui_layout` kernel instead of being flattened into strings. Its follow-up wave,
   ERR09, applies the same record contract to setup reviews, manual fallback and effect outcomes.

The order is deliberate. Legibility builds the rendering kernel that typed errors need, and its D5
removes the most frequently hit false failure (`No artifacts selected`), shrinking what the
diagnostics work has to cover. ERR05a jumped the queue because the blanket handlers were
discarding live sessions and would have swallowed exceptions during the legibility refactor.

## Documents

| Track | Design | Plan |
|---|---|---|
| Legibility | [DESIGN-tui-legibility.md](../design/DESIGN-tui-legibility.md) | [PLAN-tui-legibility.md](PLAN-tui-legibility.md) |
| Typed errors | [DESIGN-typed-wizard-errors.md](../design/DESIGN-typed-wizard-errors.md) | [PLAN-typed-wizard-errors.md](PLAN-typed-wizard-errors.md) |
| Track-3 setup follow-up | [DESIGN-setup-review-transparency.md](../design/DESIGN-setup-review-transparency.md) | [PLAN-setup-review-transparency.md](PLAN-setup-review-transparency.md) |

An issue summary for the legibility track was drafted but **not** filed on GitHub; it awaits
authorization.

Track 3 is now tracked publicly: [#74 — Typed stage failures and actionable TUI
diagnostics](https://github.com/M1F1/agent-artifacts/issues/74) owns ERR01–ERR08, while
[#75 — Transparent setup review and manual `SETUP.md`
fallback](https://github.com/M1F1/agent-artifacts/issues/75) owns ERR09 after its explicit
ERR04/ERR06 dependencies.

## Status

| Item | State | Evidence |
|---|---|---|
| Legibility design + plan | committed | `3ce271b` |
| ERR05a fallback boundary | committed | `6ce2e25`, 6 new tests in `tests/tui_fallback_boundary_test.py` |
| Legibility WP-0 layout kernel | committed | 31 new tests in `tests/tui_layout_test.py` |
| Legibility WP-1 stepper and header | committed | 15 tests in `tests/wizard_render_test.py`; 11 rewritten across 6 files |
| Legibility WP-2 artifact projections | committed | 10 tests in `tests/tui_marketplace_test.py`; 4 moved off `render_marketplace_row` |
| Legibility WP-3 steps 1, 2, 6 | committed | 6 tests in `tests/tui_wizard_curses_test.py::StatusBarTests` |
| Legibility WP-3 step 3 | committed | 6 tests in `tests/tui_wizard_curses_test.py::ScreenChromeTests` |
| Legibility WP-3 step 4 | committed | 4 tests in `tests/tui_wizard_curses_test.py::DetailPaneTests` |
| Legibility WP-3 steps 5 and 7 | committed | 5 tests in `EnterSemanticsTests`, 3 across text tests |
| Legibility WP-3 steps 8, 9, 10 | committed | 4 tests in `DetailRecordAndWidthTests`, 2 more across text tests |
| Legibility WP-4 docs and gate | committed | statuses flipped, README screen block rewritten |
| Typed errors ERR01 | completed | parser fixtures and 4 characterization tests across `tests/install_state_schema_test.py`, `tests/tui_consumer_text_test.py`, and `tests/tui_source_stage_test.py`; all 10 quality gates green (1832 unit tests) |
| Typed errors ERR02 | completed | `install-state-legacy` recognizes only the exact `repo`/`installed` v0.1 envelope; every other parser failure is `install-state-invalid` with its original safe location/message; all 10 quality gates green (1833 unit tests) |
| Typed errors ERR03 | completed | canonical Artifacts loader returns `DomainResult`; immutable `WizardStageFailure` preserves diagnostics and read-only recovery context; legacy command errors cross one named adapter |
| Typed errors ERR04 | completed | `c87935e`; one pure, width-bounded record renderer for text and curses; in-place Retry/Back/Quit preserves session and basket; all 10 quality gates green (1845 tests) |
| Typed errors ERR05b | completed | `13b3b99`; `InternalFailureContext` tracks safe stage/operation outside `WizardSession`; `AART_DEBUG=1` writes traceback only to local stderr; capability probe falls back only for import/TTY failures; all 10 quality gates green (1851 tests) |
| Typed errors ERR06 | completed | `181d555`; Sources local feedback + blocking records, Review/Finalize records across consumer and curation paths, terminal records after curses teardown; all 10 quality gates green (1861 tests) |
| Typed errors ERR08 | completed | `b331060`; default Maintainer curates `cwd`, skips consumer Sources in text/curses, preserves explicit legacy route and pure Back/stepper behavior; all 10 quality gates green (1866 tests) |
| Typed errors ERR09-A | completed | `819b885`; versioned `1/1` → `2/2` setup contract derives package-root `SETUP.md`, validates safe v2 documents/custom headers and retains v1 behavior; all 10 quality gates green (1870 tests) |
| Typed errors ERR09-B | completed | `0cfee2a`; one typed, width-bounded setup review has safe effect records and only local/commit-pinned manual routes; v1 remains explicitly unavailable; all 10 quality gates green (1876 tests) |
| Pre-existing typecheck repair | committed | `c92cf52`; **not a regression of this track** — the legacy-importer bundle-kind tuple failed `mypy` unchanged on the prior HEAD. Typed module constant plus one bundle-membership regression test; all 10 quality gates green (1889 tests, 85.25% branch coverage) |
| Typed errors ERR09-C | completed | `74c22e9`; both adapters render one bounded setup outcome with the `SETUP.md` route, a denied plan keeps its verified route through `CanonicalSetupAttempt`, and a blocking retained run crosses one named bridge into `WizardStageFailure`; all 10 quality gates green (1892 tests, 85.27% branch coverage) |
| Typed errors ERR09-D | completed | `e7b9853`; authoring material, README manual-route section, representative static/custom/local-source fixtures, and the single-revision setup contract (see below); all 10 quality gates green (1898 tests, 85.28% branch coverage) |
| Typed errors ERR07 | pending | — |

Baseline before ERR01: 1828 unit + 52 integration tests, all ten gates of
`python scripts/quality.py` green. The current branch was pushed through `4653775` before this
package began.

**The legibility track is complete.** Every package of
[PLAN-tui-legibility.md](PLAN-tui-legibility.md) has landed.

### Deviation from the plan's file ownership

The plan assigns `tui.py` and the six string-asserting test files to WP-3, because ownership
exists to stop *parallel agents* colliding. Running sequentially there is no collision, and the
binding constraint is instead that every commit leaves the suite green. WP-1 therefore also:

- rewrote 11 assertions across `tui_wizard_text_test.py`, `tui_wizard_curses_test.py`,
  `tui_roles_test.py`, `tui_source_stage_test.py`, `tui_wizard_e2e_test.py` and
  `tui_wizard_maintainer_test.py`, from `Stage: X` to the stepper's `▸ X`;
- replaced the header-overflow priorities in `_draw_list` (`tui.py`), which matched `[●]` and
  `Stage:` and so matched nothing after the re-markering. A narrow-terminal test caught this as a
  real regression, not a hypothetical one. WP-3 step 2 is consequently already done.

## Next task

**ERR07 of [PLAN-typed-wizard-errors.md](PLAN-typed-wizard-errors.md)** — track documentation and
handoff. It closes the typed-error track: no code contract is left open by ERR09.

ERR09-A/B/C/D provide the manual-document boundary, the pure bounded review, the wired outcomes in
both adapters, and the authoring material. Payload and setup outcomes must remain distinct in
anything ERR07 writes.

Read that plan for the package order. ERR05 is complete (`6ce2e25`, `13b3b99`): expected
stage errors have ERR04's record renderer; internal errors have safe stage context, an opt-in
local debug traceback, and a narrowed terminal-capability probe.

### ERR04 delivery notes

- `render_wizard_stage_failure` is the shared functional-core projection. It bounds normal lines,
  renders stage, operation, safe context, locations, remediation and only declared recovery
  actions. Its allowlist excludes secret-shaped details and the adapter-only compatibility exit
  status.
- Both frontends implement the same `retry` event. It repeats only the read-model load; `back`
  uses normal immutable-session navigation; `quit` preserves the existing basket-discard
  confirmation. Curses uses a scrollable record with a recovery-only bottom bar, not a stale
  artifact pane.
- The one legacy-command bridge keeps its historical nonzero exit status only after the user quits
  its record. That transport detail is neither rendered nor allowed to weaken Retry/Back for the
  canonical typed path.
- Independent review found and fixed the initial curses quit/basket asymmetry. Focused TUI tests,
  `git diff --check`, and all ten `python scripts/quality.py` gates pass. No manifest,
  configuration, source store, project tree, setup state or analytics write is on this path.

### ERR05b delivery notes

- `InternalFailureContext` is an imperative-shell value containing only stage and operation. It
  never enters `WizardSession`, reporting or analytics. It marks Artifacts load, Review, Finalize,
  Setup and Reporting boundaries before their effects, so redacted internal records name the last
  safe context.
- The default record has the stable code, context and exception type only. `AART_DEBUG=1` is the
  deliberate developer opt-in and writes a traceback to local stderr; it never changes normal
  stdout, reports or outcomes.
- The capability probe returns text fallback only for missing `curses` or TTY `OSError`; an
  unexpected probe exception produces the same redacted nonzero internal record. Focused tests
  cover both kinds of failure, debug isolation, stage updates and no second wizard.
- Independent review found no critical issue. `git diff --check` and all ten
  `python scripts/quality.py` gates pass (1851 tests). The remaining risk is intentional: debug
  stderr is for a local developer and may contain exception data, which is why it is opt-in and
  never forwarded.

### ERR06 delivery notes

- The audit classifies Sources choice validation as list-local feedback: curses reuses the fixed
  lower list slot, preserves its geometry and displays the typed code plus a bounded explanation;
  text gives the same compact code-bearing feedback before the next source prompt. Source-add,
  sync and refresh failures remain local to the setup flow; their code-bearing notices are bounded
  to `CONTENT_MEASURE` in curses.
- Boundaries crossed after the Sources selection (consumer loading and the narrow legacy source
  argument adapter) are blocking `Sources` records with conservative Back/Quit recovery. The old
  adapter exit code is not rendered and cannot reduce that recovery contract.
- Consumer and curation review preparation, source finalization and canonical consumer/curation
  finalization preserve `DomainErr` into a `Review` record in text. Curses uses the same record
  while the session is live; after its required teardown, an expected finalization error is a
  terminal record with the known nonzero outcome instead of a raw flattened line or a second
  wizard.
- Profile/scope/mode compatibility has no separate `DomainErr` adapter: its pure projections keep
  the user on their current input screen, while Artifacts retains ERR04's typed loader path.
  Setup and reporting stay post-outcome warning-only; ERR09 owns their dedicated bounded effect
  record and `SETUP.md` route. No diagnostic enters reporting or analytics.
- Independent review found no critical issue. Targeted placement/recovery/no-write tests, a
  startup-record regression and all ten `python scripts/quality.py` gates pass (1861 tests).

Useful facts carried over from the legibility work:

- `tui_layout` gives you `wrap`, `field_block`, `columns`, `status_bar`, `measure`,
  `READABLE_MEASURE` (80, prose) and `CONTENT_MEASURE` (100, structured).
- `tui_marketplace.render_artifact_detail` is the worked example of a record: sectioned headings,
  aligned `label   value` blocks, and digest lines deliberately exempt from the measure.
- `_draw_detail(curses, stdscr, label, record=…)` renders any such record scrollably, and
  `_choice_detail` is the projector both frontends share — text mode writes the same lines.
- Two guard tests in `ScreenChromeTests` parse `tui.py` and fail if any string literal names a key
  outside a text prompt or uses ` · ` as a separator. New diagnostics must satisfy both.
- **The live reproducer for ERR02 is still in the working tree** — see the section at the end.
- **ERR01 characterized the second reproducer too.** Before ERR08, a canonical registry checkout
  routed Maintainer through the consumer-only Sources question and dead-ended on its registry.
  ERR06 made the retained explicit legacy bridge a recoverable typed record; **ERR08** now makes
  the default Maintainer route curate the current directory without visiting Sources. A dedicated
  checkout-picker screen was considered and deliberately left out of scope.

### ERR08 delivery notes

- `WizardSession.maintainer_checkout` is a pure route fact. `use_current_checkout` drops Sources
  from the Maintainer stage graph, so the stepper never lists an unreachable stage and Back from
  Maintainer action returns directly to Role. Changing role clears the fact.
- Text and curses set that fact only for Maintainer with neither `--source` nor `--repo`; they use
  the absolute current working directory as the curation root. User continues to visit Sources,
  while any explicit legacy source/repo route keeps Sources and its ERR06 recoverable bridge.
- The default Maintainer User-workflows entry reuses the configured source policy without adding a
  consumer Sources prompt. No source selection, source finalizer, configuration write or catalog
  mutation occurs while reaching the Maintainer action list.
- The registry-only reproducer, both frontend gates, stage/Back invariants and explicit-path
  regression coverage pass. Independent review found no critical issue; all ten quality gates
  passed with 1866 tests.

### ERR09-C delivery notes

- Both adapters now render `render_setup_outcome` for every post-payload result: the retained
  post-install runner and `aart setup` records, and the canonical planning failure, decline and
  execution paths. The payload statement always comes first, and the outcome record carries the
  `SETUP.md` route whenever the status is not complete. The flattened `module: summary -> target`
  effect sentence is gone from both consent paths; each effect is approved by its reviewed index,
  identity and recovery.
- A denied plan keeps the route it already proved. `prepare_setup` splits at the seam where the
  recipe — and with it a v2 `SETUP.md` — is validated but trust and policy have not yet applied.
  `prepare_setup_attempt` returns a `CanonicalSetupAttempt` whose invariant is that a planned
  attempt always carries a manual route, so a failure before that seam claims none rather than
  inventing one. `prepare_setup` keeps its signature; no existing caller changed.
- The manual status distinguishes an unstarted setup (`declined`, `planning-failed`,
  `unsupported` → "No setup effect has run.") from a partial one. `skipped` is deliberately not
  unstarted: `rollback_record` also reports it after a *completed* rollback, where effects did run.
- **Audit of plan item 4.** The fixed bottom pane is already list-local only: no setup code runs
  inside the curses wizard, so a setup record cannot reach it. That is now pinned behaviorally —
  the setup stage is observed to execute after `curses.wrapper` returned, not merely after the
  last screen. The one real gap was the retained runner, which printed `error: <reason>` for a
  blocking failure. It now crosses one named 0.1 bridge into `WizardStageFailure`, reusing ERR04's
  record and ERR06's terminal-recovery rule, and preserves its legacy exit status. No second
  setup-only error system was introduced.
- **Known imprecision, carried as a follow-up.** The retained `run_queue` returns a bare `Err` and
  discards the records it already completed, so a mid-queue receipt/state persistence failure
  cannot name which items finished. The blocking record therefore offers each queued route as
  possibly-incomplete work rather than claiming that no effect ran. Making that runner return its
  completed records alongside the failure is worth doing when the retained path is next touched.
- Independent review found no critical issue. All ten `python scripts/quality.py` gates pass
  (1892 unit + 52 integration tests, 85.27% branch coverage).

### ERR09-D delivery notes

- **Scope change, decided by the maintainer mid-package.** The plan's "state v1 compatibility
  precisely" item is void: AART now supports exactly one setup-recipe revision. Both version
  fields must be `2`, and the superseded `1`/`1` pair is rejected at parse time with the migration
  named in the error. The prompt invariant "keep v1 compatibility" was explicitly overridden — the
  general rule for this repository is that only the newest revision of a protocol or standard is
  maintained.
- **What that removed, rather than added.** `manual_path` is no longer optional, so every
  validated installer carries exactly one route; `SetupManualReference` lost its `legacy` flag and
  the "manual documentation unavailable" render branch, and both JSON payloads lost the `legacy`
  key; `source.py` and the setup engine validate `SETUP.md` unconditionally instead of behind a
  version test. There is no compatibility branch left in validation, review, or the runtime.
- The one genuinely defensive case that the `legacy` flag was overloading — a route escaping the
  source root — is now its own total behavior: the route is named package-relative, never as a
  path outside the root. `setup_review_test` pins it with a hand-crafted `manual_path`, because a
  derived route cannot reach that state today and the guard exists for future producers.
- Authoring material is `docs/design/DESIGN-setup-installers.md` §3.1 (document first, then the
  recipe, then a script only for what no module expresses, with the header template) and
  §17.1 of the SPEC for the normative rules. The README gained a "Declining Automation" section:
  a worked `Manual alternative` block, the distinction between "No setup effect has run." and
  "Automated setup is incomplete", and the explicit statements that declining never rolls back the
  payload and that following the route is never consent.
- Representative packages live in `tests/fixtures/setup-routes/`: `mcp/atlassian` (static recipe,
  Keychain + shell) and `skills/onboarding` (non-MCP, custom entrypoint with a complementary
  `restart.notice@1` module step). `tests/setup_manual_routes_test.py` proves they load as valid
  sources without executing anything, that the pinned and unpinned routes resolve as specified,
  and that neither document carries a credential shape.
- **Not migrated, deliberately.** Setup state recorded by an earlier run stays readable exactly as
  written; the receipt reader still accepts its stored version fields. Rejecting old *inputs* is
  not the same as rewriting existing *state*, and nothing is migrated in place.
- Independent review found no critical issue. All ten `python scripts/quality.py` gates pass
  (1898 unit + 52 integration tests, 85.28% branch coverage).

## Working agreements

- TDD. Write the failing assertions for the new contract first.
- DDD with a functional core and imperative shell; pure rendering, effects at the edge.
- Zero non-stdlib dependencies, `unittest` not pytest. Flag any new dependency as a decision.
- Run `python scripts/quality.py` — all ten gates — before calling a package done. The `coverage`
  gate needs the dev extras in the active venv (`pip install -e ".[dev]"`); a missing `coverage`
  module fails the gate without any code being wrong. The runtime stays zero-dependency.
- Rewrite superseded assertions against the new contract. Never delete one without a replacement.
- Preserve unrelated changes. The untracked `.agent-artifacts/`, `.tabnine/` and `TABNINE.md` in
  the working tree are not ours to touch.
- If a task has no design document and plan, write them first and hold for review before coding.
- Commit when the work is a coherent unit. **Do not push, merge, tag, release, or file issues
  without explicit authorization.**
- Parallel worktree agents branch from the session's initial HEAD, not live `main`. Paste every
  contract they need into their prompt and treat any baseline they report as stale.

## Decisions already made

All are recorded in the design documents with rationale; this is the index.

- Legibility D1–D8: retire `·` as a separator; hints in one pinned bottom bar; full projected
  stepper with `✓ ▸ ·`; delete `Stage:`; Enter confirms and defaults to the cursor row; detail in a
  pinned pane rather than an expanding row; content bounded to 80 (prose) and 100 (structured);
  `?` renders a record, digests unwrapped.
- Legibility D9–D11: `b` goes back in both frontends and the bar says so, Backspace stays as an
  unadvertised alias; disabled rows use `[!]`; onboarding names no keys.
- Rejected: expanding the cursor row in place. It reflows the list on every keystroke and would
  force cursor, scroll and checked state to be re-indexed from screen rows.

## Live reproducer for track 3

`.agent-artifacts/manifest.json` in this working tree currently has top-level `installed` and
`repo` keys — genuine 0.1 state. ERR02 can be driven against it without building a fixture. Do not
delete or migrate it without asking; it is the reproducer.
