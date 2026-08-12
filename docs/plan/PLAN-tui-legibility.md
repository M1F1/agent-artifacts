# Plan: TUI legibility and selection ergonomics

Implements [DESIGN-tui-legibility.md](../design/DESIGN-tui-legibility.md). Decision references
below (D1–D8) point at that document's §3.

Status: implemented. Every package below has landed on `main`; the running record of which
commit carried which step is [PROGRESS-tui-program.md](PROGRESS-tui-program.md).

Baseline before starting: `main`, 1740 unit tests + 52 integration green via
`python scripts/quality.py`. Baseline after WP-4: 1828 unit + 52 integration, all ten gates
green.

## Shape of the work

One shared kernel is built first, because every other package depends on it. Two pure renderers
then proceed in parallel against that frozen kernel. The curses and text wiring lands last and
inline, because it is the only package that touches `agent_artifacts/tui.py` and it is where the
whole suite has to come back to green.

```
WP-0 kernel (inline)
      |
      +-- WP-1 wizard.py       \  parallel
      +-- WP-2 tui_marketplace  /
      |
WP-3 tui.py wiring (inline on main)
      |
WP-4 docs + final gate (inline)
```

File ownership is disjoint per package. No two packages in the same wave write the same file.

Every package is tests-first: write the failing assertions for the new contract, then make them
pass, then delete or rewrite the assertions the design supersedes. Rewriting a superseded test to
assert the new contract is required; deleting it without a replacement is not acceptable, since
three of them guard invariants we are deliberately changing (design §6).

## WP-0 — Contract freeze and layout kernel

Runs inline on `main`. Everything downstream imports this, so it lands before any agent is
dispatched.

**Owns:** `agent_artifacts/tui_layout.py` (new), `tests/tui_layout_test.py` (new).

Unlike a signatures-only freeze, this package implements the kernel outright. It is small, it is
pure, and leaving it stubbed would block both Wave A packages from having green tests.

Deliverables:

- `READABLE_MEASURE = 80`, `CONTENT_MEASURE = 100`, and `measure(width, *, bound)` returning
  `min(max(width, 1), bound)` (D7).
- `wrap(text, *, width)` — the bounded prose wrapper (D7).
- `columns(cells, *, width)` — one shared column layout for a whole list, so positions are
  identical on every row; each column is capped and truncates within itself rather than pushing
  later columns off screen (D6).
- `field_block(fields, *, indent, width)` — aligned `label   value` lines; the label column is
  the longest label plus padding; values that overflow wrap into the value column (D6, D8).
- `status_bar(hints, *, counters, width)` — hints joined with `, `, counters right-aligned,
  degrading in the fixed order of D2: row range, then selection count, then hints from the right,
  never dropping `enter` or `q`.
- `pane_budget(*, height, requested)` — rows the detail pane may take, or `0` when the terminal is
  too short. Encodes the give-up order: pane before header extras, never the list below three
  rows, never the bar (D6).
- Frozen vocabulary: stage markers `✓ ▸ ·`, the box markers `[x] [ ] [!]` (D10), the `→` stepper
  join, the `…` projection token, and the canonical hint table (`space=toggle`, `enter=confirm`,
  `b=back`, `?=details`, `a=add`, `q=quit`) in that degrade order (D2, D9).

Acceptance: `tui_layout` has no imports from `tui`, `wizard`, or `tui_marketplace`; no non-stdlib
import; every function is total for widths 1..200 and heights 1..60; `columns` never emits a line
longer than its `width`; `pane_budget` never starves the list below three rows.

## Wave A — pure renderers, parallel

Both packages import `tui_layout` and nothing from each other.

### WP-1 — Stepper and header

**Owns:** `agent_artifacts/wizard.py`, `tests/wizard_render_test.py`.
**Must not touch:** `tui.py`, `tui_marketplace.py`, `tui_layout.py`.

- Add `projected_stages_for(session)` beside `stages_for`, returning the full expected path plus
  a projection flag for the tail (D3). `stages_for` keeps its current semantics and callers;
  nothing outside rendering may switch to the projection.
- `render_stepper` emits `✓ ▸ ·` with `→` joins, and appends `…` when the tail is projected.
- `render_header` drops the hint line (D2) and drops `Stage:` (D4), keeping basket and notices.
  It emits a `▸ <label>` line only when the stepper had to be truncated and the current stage is
  no longer visible.
- Trim `onboarding_lines` to what the status bar cannot say — what aart does, what the two roles
  mean, where artifacts come from. It names no keys (D11).

Acceptance: rendering a session at every stage of both role paths produces no `·` separator, no
`Stage:` prefix, and no hint text; a narrow width still yields the current stage exactly once.

### WP-2 — Artifact projections

**Owns:** `agent_artifacts/tui_marketplace.py`, `tests/tui_marketplace_test.py`.
**Must not touch:** `tui.py`, `wizard.py`, `tui_layout.py`.

- `artifact_cells(row)` — the row's cells unpadded, identity first; the widget aligns them through
  `columns` so one layout serves every row (D6).
- `render_artifact_pane(row, *, width)` — the pinned pane body: identity, wrapped summary, then
  `source`, `risk`, `harness`, `status` via `field_block`.
- `render_artifact_detail(row)` — the full record for `?`: wrapped summary, all evidence fields,
  each digest on its own line and exempt from the measure (D8).
- Keep `render_marketplace_row` exported and working until WP-3 removes its last caller. Its three
  existing assertions move to the replacements in the same commit that adds them, so coverage is
  never merely dropped.

Acceptance: a row whose summary is 400 characters still shows its full key at width 40; no output
line contains `·`; digest lines are never wrapped mid-hash.

## WP-3 — Curses and text wiring

Runs **inline on `main`**, not in a worktree. It is the integration point, it touches the widest
surface, and it must leave the entire suite green — the conditions under which a stale worktree
baseline causes the most damage.

**Owns:** `agent_artifacts/tui.py` and every test file that asserts on the old strings:
`tests/tui_test.py`, `tests/tui_wizard_curses_test.py`, `tests/tui_wizard_text_test.py`,
`tests/tui_wizard_e2e_test.py`, `tests/tui_install_mode_test.py`, `tests/tui_roles_test.py`,
`tests/tui_source_stage_test.py`, `tests/tui_wizard_maintainer_test.py`.

Ordered steps, each independently testable:

1. **Pin the status bar.** `_draw_list` reserves `height - 1` for the body and paints
   `status_bar(...)` on the last row every frame, following the existing pattern in
   `_curses_onboarding` and `_draw_detail`. Assert visibility at scroll offset 0 and at maximum
   scroll.
2. **Rewrite header overflow priorities.** The predicates matching `"[●]" in line` and
   `line.startswith("Stage:")` die with those strings; replace string sniffing with the marker
   vocabulary from WP-0 (D4).
3. **Strip parentheticals from titles.** All screen titles in `tui.py` become plain nouns; the
   hints they carried are already in the bar.
4. **Reserve the detail pane and align the rows.** `_draw_list` subtracts `pane_budget(...)` from
   its viewport and paints `render_artifact_pane(...)` for the cursor item between list and bar;
   rows go through `columns(...)`. Cursor and scroll arithmetic
   ([tui.py:5441](../../agent_artifacts/tui.py)) is **not** touched — one item stays one row, and
   `test_draw_list_keeps_each_row_to_one_visual_line` must still pass unmodified. Add the
   stability assertion: moving the cursor changes no row's text or position.
5. **Enter semantics.** In `_curses_multiselect`: Enter with a non-empty tick set confirms it;
   with an empty set and a selectable cursor row, confirms that row; with an empty set and a
   disabled cursor row, stays and surfaces the row's reason (D5). `empty_selection` survives only
   for a list with no selectable row.
6. **Back key and disabled marker.** Curses accepts `b` alongside Backspace (D9); the disabled box
   becomes `[!]` and keeps its column (D10). Both are small and independently assertable.
7. **Text parity.** Confirming an empty selection re-prompts with a hint instead of ending the
   session; `render_header` no longer duplicates the prompt's hints in text mode (design §5).
8. **Detail view.** `_draw_detail` wraps at `measure(available)` and renders
   `render_artifact_detail(row)` (D7, D8).
9. **Drop `render_marketplace_row`** once `_canonical_choice` uses the new projections, and remove
   it from `__all__`.
10. **Bound the width.** Apply `CONTENT_MEASURE` to rows, pane and columns, and `READABLE_MEASURE`
   to prose. Assert at simulated widths 40, 80, 120 and 200 that no structured line exceeds 100
   and no prose line exceeds 80 (D7).

Acceptance: every acceptance bullet in design §10; `python scripts/quality.py` green.

## WP-4 — Docs and gate

Runs inline. **Owns:** `docs/design/DESIGN-tui-legibility.md`, `docs/plan/PLAN-tui-legibility.md`,
any README or help text that reproduces a changed screen.

- Flip both documents' status from proposed to implemented.
- Re-run `python scripts/quality.py` on `main` after all merges. Per the worktree gotcha, this
  gate runs inline on `main` and never as a worktree agent, and any built wheel is rebuilt here
  so it does not embed a stale tree.

## Sequential fallback

Single agent, no worktrees: WP-0 → WP-1 → WP-2 → WP-3 → WP-4, unchanged in content. Wave A's two
packages are independent but not order-dependent, so a single agent loses parallelism and nothing
else.

## Agent prompt kit

Wave A agents branch from the session's initial HEAD, not from live `main`. Each prompt must
therefore carry, inline and in full:

- the complete `tui_layout.py` public surface from WP-0, pasted as text rather than referenced by
  commit;
- the package's owned-file list and its must-not-touch list;
- the relevant design decisions verbatim;
- an explicit instruction to treat any test baseline it observes as stale.

Merge Wave A by taking the disjoint files onto current `main` and re-running the full suite there.

## Risk register

| Risk | Mitigation |
|---|---|
| Header, pane and bar reservations starve the list on short terminals | Single pure `pane_budget` owns the give-up order; explicit tests at heights 6, 10, 16 and 24 |
| Bulk find-and-replace silently weakens ~12 assertions across 6 files | WP-3 owns all six files; each superseded assertion is rewritten against the new contract, not deleted |
| One pathological cell widens a column for every row | `columns` caps each column and truncates within it |
| `render_marketplace_row` removed while a caller remains | Removal is the last step of WP-3, after `_canonical_choice` is migrated |
