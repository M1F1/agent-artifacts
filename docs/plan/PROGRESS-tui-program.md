# Progress record: TUI program

Resume file. Written so that this document plus the repository is enough to continue without any
conversation history.

## Goal

Make the `aart` TUI legible and predictable, and make its failures honest. Three tracks, in this
agreed order:

1. **ERR05a — constrain the curses fallback.** Done.
2. **TUI legibility program.** Current.
3. **Typed wizard errors, ERR01 onward.** After legibility, so diagnostics render as records
   through the `tui_layout` kernel instead of being flattened into strings.

The order is deliberate. Legibility builds the rendering kernel that typed errors need, and its D5
removes the most frequently hit false failure (`No artifacts selected`), shrinking what the
diagnostics work has to cover. ERR05a jumped the queue because the blanket handlers were
discarding live sessions and would have swallowed exceptions during the legibility refactor.

## Documents

| Track | Design | Plan |
|---|---|---|
| Legibility | [DESIGN-tui-legibility.md](../design/DESIGN-tui-legibility.md) | [PLAN-tui-legibility.md](PLAN-tui-legibility.md) |
| Typed errors | [DESIGN-typed-wizard-errors.md](../design/DESIGN-typed-wizard-errors.md) | [PLAN-typed-wizard-errors.md](PLAN-typed-wizard-errors.md) |

An issue summary for the legibility track was drafted but **not** filed on GitHub; it awaits
authorization.

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
| Legibility WP-3 steps 8, 9, 10 | not started | — |
| Legibility WP-4 | not started | — |
| Typed errors ERR01 … ERR04, ERR05b, ERR06, ERR07 | not started | — |

Baseline at the time of writing: 1797 unit + 52 integration tests, all ten gates of
`python scripts/quality.py` green. `main` is ahead of `origin/main` and has not been pushed.

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

**WP-3 of [PLAN-tui-legibility.md](PLAN-tui-legibility.md), step 8 onward** — curses and text
wiring. Runs inline on `main`, owns `agent_artifacts/tui.py` and the eight test files that assert
on old screen strings.

Done so far: **step 2** (landed with WP-1), **steps 1 and 6** (the pinned bar, `b`, `[!]`),
**step 3** (titles are nouns, every footer is a `status_bar`, no `·` separator survives in
`tui.py`), **step 4** (the pane and the column grid) and **steps 5 and 7** (Enter semantics in
both frontends). Steps 1 and 6 landed together on purpose — the bar advertises `b=back`, and
shipping that sentence before the key worked would have made the bar lie.

Remaining: **8** (`_draw_detail` through `render_artifact_detail`), **9** (drop
`render_marketplace_row` once `_canonical_choice` no longer calls it), **10** (bound the width and
assert it at 40/80/120/200). Two guard tests fail loudly if a regression reintroduces old chrome:
`ScreenChromeTests` parses `tui.py` and rejects any string literal that names a key outside a text
prompt, or uses ` · ` as a separator.

What steps 1, 3, 4, 5 and 7 established, for the steps that build on them:

- `_draw_list` reserves `height - 1` for the body and paints `status_bar` on the last row every
  frame. Step 4's pane comes out of `body_height`, not out of the bar.
- `_list_hints(toggle=, back=, details=, add=)` filters `HINT_ORDER` to the keys a screen accepts;
  `_list_counters(...)` returns `("N selected", "first-last of total")` in shed order.
- The `Selected: N` header line is gone — it is the bar's counter now — so `list_start` is
  `row + 2` on every list, checkbox or not.
- Every screen with a pinned last row now paints `status_bar`: onboarding (`enter=start`), review
  and confirm (`enter=finalize`), the discard prompt (`y=discard, n=return`), the curses text
  input (`backspace=back when empty`), and `_draw_detail` (`q=return`). Step 8 may restate the
  detail bar but does not have to invent one.
- `b` also goes back from review, confirmation, the source-addition review and the mode screen.
- `onboarding_lines` lost "Press Enter to start." (D11): the bar says it in curses and the prompt
  says it in text. That edit is in `wizard.py`, WP-1's file — same sequential-ownership deviation
  as before, recorded above.
- `_draw_list` takes `cells=` (a shared column grid, laid out across every row at once) and
  `pane_for=(index, width) -> lines`. Both are optional; only the artifacts screen passes them,
  because that is the screen observation 7 was about. `_Choice` carries `cells` and `row` so the
  screen can hand them over, and `_choice_pane` covers collections, which have no security record.
- `_fitting_cells` drops whole trailing columns when they no longer fit, rather than letting
  `columns` shrink them to `regist…`. This is the caller-side half of the WP-2 decision below.
- The pane sits directly under the last list row, or just above the bar when the list is long.
  Both positions depend only on frame constants, so nothing moves while the cursor does.
- `render_artifact_pane` abbreviates the revision to seven characters (`aaaaaaa…`). At 62 columns
  the full hash wrapped over three lines and pushed the `status` field — the one carrying the
  refusal reason — off the bottom of the pane. `render_artifact_detail` still prints it whole.
- Enter with nothing ticked takes the cursor row; on a disabled row it refuses, paints the reason
  on the blank separator row `_draw_list` already reserves, and stays. `empty_selection` now only
  happens when no row in the list is selectable at all. `_curses_multiselect` takes `reasons=`
  beside `disabled=`; both list screens that can disable a row pass it.
- Text mode has no cursor, so parity is at the level of outcome: a blank answer with an empty
  basket writes `_NOTHING_SELECTED` and asks again, in both `_prompt_wizard_indices` and the
  legacy `_prompt_indices`. `q` remains the way out of both.

Everything else WP-3 needs is pure and tested:

```python
from agent_artifacts.tui_layout import (
    BOX_CHECKED, BOX_DISABLED, BOX_EMPTY, CHROME_ROWS, CONTENT_MEASURE, HINT_ORDER,
    MIN_LIST_ROWS, PANE_MIN_HEIGHT, PROTECTED_HINTS, READABLE_MEASURE,
    STAGE_CONFIRMED, STAGE_CURRENT, STAGE_JOIN, STAGE_PENDING, STAGE_PROJECTION,
    columns, field_block, measure, pane_budget, status_bar, wrap,
)
from agent_artifacts.tui_marketplace import (
    artifact_cells, render_artifact_detail, render_artifact_pane,
)
```

`_canonical_choice` ([tui.py:2064](../../agent_artifacts/tui.py)) is the last caller of
`render_marketplace_row`; migrating it is step 9 and the function is deleted from `__all__` in the
same commit.

Then WP-4 (flip both document statuses, final gate).

### Settled in WP-2: the narrow-column question WP-0 carried forward

`columns` shrinks every non-identity column toward one character rather than dropping it, so a
four-cell row at width 44 degraded to `identity  ava…  ris…  reg…`. A stump costs the same space
as the word and carries nothing, so **the caller drops whole columns instead**, and the kernel is
left alone.

`artifact_cells` therefore returns its cells in decreasing importance — key, state, risk, trust —
and WP-3 passes a prefix of them chosen by width. Verified degradation:

```
width 100:  company/skill/review@1.0.0  available  risk low      registry-reviewed
width  60:  company/skill/review@1.0.0  available  risk low
width  44:  company/skill/review@1.0.0  available
```

This is the only WP-2 decision not already written in the design; it needs no revision there
because D6 fixes the row's content, not its arity.

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
