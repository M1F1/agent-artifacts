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
| Typed errors ERR06, ERR07, ERR08, ERR09 | not started | — |

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

**ERR06 of [PLAN-typed-wizard-errors.md](PLAN-typed-wizard-errors.md)** — audit each remaining
stage and operation boundary; preserve canonical `DomainErr` or explicitly name a narrow legacy
adapter. Classify rather than blanket-wrap exceptions, then add targeted regression tests for each
boundary and its mutation/secret-safety contract.

**ERR09 is the planned follow-up wave, not the next task.** It must wait for ERR04's shared
failure renderer and ERR06's audit of setup boundaries. Its separate setup-review design preserves
the current v1 protocol while making `SETUP.md`, bounded effect records and a manual route the
standard for new setup-capable artifacts.

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
- **ERR01 characterized the second reproducer too.** From a canonical registry checkout, role
  Maintainer plus an enabled registry source prints one flattened line in text mode, returns to
  Sources, and permits a clean quit without writes. The curses adapter records the same flattened
  error as a terminal selection failure and exits 2. Neither frontend names a stage or offers the
  role the right input. **ERR08** makes Maintainer default to curating the current directory and
  skip Sources; a dedicated checkout-picker screen was considered and deliberately left out of
  scope.

## Working agreements

- TDD. Write the failing assertions for the new contract first.
- DDD with a functional core and imperative shell; pure rendering, effects at the edge.
- Zero non-stdlib dependencies, `unittest` not pytest. Flag any new dependency as a decision.
- Run `python scripts/quality.py` — all ten gates — before calling a package done.
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
