# Design: TUI legibility and selection ergonomics

Status: proposed; implementation has not started

## 1. Context

The wizard is functionally complete but reads poorly. Every screen spends its most valuable
space — the top of the terminal — on chrome, and the densest information (an artifact and its
security evidence) is compressed into a single punctuation-separated line that no longer fits a
terminal. Reviewing the running TUI produced eight concrete observations. Each one is traceable
to a specific renderer.

| # | Observation | Origin |
|---|---|---|
| 1 | The key legend is hard to scan; `·` separators read as noise | `render_header`, [wizard.py:405](../../agent_artifacts/wizard.py) |
| 2 | `Stage: Role` restates what the stepper above already shows | `render_header`, [wizard.py:391](../../agent_artifacts/wizard.py) |
| 3 | `(enter=confirm, q=quit)` in the title duplicates the legend | screen titles, [tui.py:4903](../../agent_artifacts/tui.py) |
| 4 | Sources shows both forms at once and they disagree | [wizard.py:398](../../agent_artifacts/wizard.py) + [tui.py:4215](../../agent_artifacts/tui.py) |
| 5 | Enter with nothing ticked silently ends the wizard | [tui.py:4549](../../agent_artifacts/tui.py) → [tui.py:1429](../../agent_artifacts/tui.py) |
| 6 | Only reached stages appear in the stepper | `stages_for`, [wizard.py:118](../../agent_artifacts/wizard.py) |
| 7 | An artifact row packs identity, trust, risk, coverage and harness state into one line | `render_marketplace_row`, [tui_marketplace.py:382](../../agent_artifacts/tui_marketplace.py) |
| 8 | `?` details wrap to the full terminal width, producing very long measures | `_draw_detail`, [tui.py:5642](../../agent_artifacts/tui.py) |

Observations 1, 4 and 7 share one root cause: `·` is used as a general-purpose separator to
flatten structured data into a string. Observations 2, 3 and 4 share another: the same fact is
rendered by two independent layers that do not know about each other.

The two hint forms in observation 4 are not merely redundant, they contradict each other. The
header advertises `Enter = continue` while the title advertises `enter=confirm`, and the header
advertises `Backspace = back` while the title omits back entirely.

Observation 5 is the only one that costs work rather than attention. A user who moves the cursor
onto `claude` and presses Enter — the single most natural gesture on a list — loses the session
and gets `No artifacts selected; no changes were made.`

## 2. Goals and non-goals

### Goals

- State every fact exactly once, in exactly one layer.
- Replace punctuation-flattened records with layout: indentation, aligned columns, and one fact
  per line.
- Keep key hints visible at all times, including while a long list is scrolled.
- Make Enter succeed on the gesture users actually perform.
- Show the whole path through the wizard from the first screen.
- Bound content to a readable measure rather than to the terminal width, in both directions: a
  line too long to track is as unread as a line truncated away.
- Keep list geometry stable under cursor movement, so the eye keeps its place.
- Preserve text/curses behavioral equivalence, which is an existing invariant of the wizard.
- Keep the renderers pure and separately testable; no new runtime dependency.

### Non-goals

- Colour, attributes, or any capability probing beyond what curses already does here.
- Mouse support, resizing behavior, or a new widget framework.
- Changing which stages exist, what they collect, or the order they run in.
- Changing catalog, trust, or security semantics. This design changes only how those facts are
  presented.
- Diagnostics and failure taxonomy, which belong to
  [DESIGN-typed-wizard-errors.md](DESIGN-typed-wizard-errors.md). See §9 for the boundary.

## 3. Decisions

### D1 — `·` is not a separator

`·` is removed everywhere it joins fields. Replacements are chosen per context:

- key hints are joined with `, ` — the form already used in screen titles and judged the more
  readable of the two in review;
- the stepper joins stages with `→`, which denotes sequence rather than mere adjacency;
- structured records are not joined at all. They become indented `label   value` lines.

`·` survives in exactly one role: the marker for a stage not yet reached (D3). It is a bullet
there, not a separator.

### D2 — Hints live in a pinned bottom status bar, and nowhere else

A single status bar occupies the last terminal row on every list screen. It is painted every
frame and is therefore unaffected by scroll offset. This mirrors `_curses_onboarding` and
`_draw_detail`, which already reserve `height - 1`; `_draw_list` currently does not, which is
why hints were pushed to the top in the first place.

The bar carries two segments:

```
space=toggle, enter=confirm, b=back, ?=details, a=add, q=quit    2 selected   5-12 of 48
```

Left segment is the hint list, right segment is the counters. Under width pressure the bar
degrades in a fixed order: drop the row range, then the selection count, then progressively drop
hints from the right (`a`, `?`, `b`), never dropping `enter` or `q`.

Consequences: `render_header` stops emitting a hint line, and every screen title loses its
parenthetical. Titles become plain nouns — `Sources`, `Select profile(s)`, `Action`.

The `?=details` hint appears for the first time. It is implemented today
([tui.py:5332](../../agent_artifacts/tui.py)) but advertised nowhere, so it is effectively
undiscoverable.

### D3 — The stepper shows the whole path, with three markers

Markers become `✓` confirmed, `▸` current, `·` not yet reached, dropping the `[x]`/`[●]`
brackets.

```
✓ How it works  →  ▸ Role  →  · Sources  →  · Harness  →  · Action
```

`stages_for` returns only stages whose existence is already determined, because the path forks on
role and again on action. A new pure function `projected_stages_for` extends it with the default
continuation so the user sees where they are heading. When the tail is a projection rather than a
certainty, the stepper ends with a `…` token. Choosing Maintainer, or an action with a different
shape, recomputes the projection on the next frame.

The projection is honest about being one: it never marks a projected stage as confirmed, and the
trailing `…` is the visible signal that the tail can still change.

### D4 — `Stage:` is deleted

`▸` in the stepper carries the same fact. One exception is retained: when the stepper is too wide
for the terminal and must be truncated, the current stage can fall out of view. In that case, and
only then, the header emits a single `▸ Role` line so the current position is never unavailable.

This interacts with the header-overflow priority list in `_draw_list`
([tui.py:5400](../../agent_artifacts/tui.py)), which currently keeps lines by matching `"[●]" in
line` and `line.startswith("Stage:")`. Both predicates die with the strings they match; the
priorities must be rewritten against the new markers or, preferably, against a typed header
structure rather than string sniffing.

### D5 — Enter confirms, and defaults to the row under the cursor

On a multi-select screen:

- if anything is ticked, Enter confirms that set — Enter never unticks;
- if nothing is ticked and the cursor row is selectable, Enter confirms exactly that row;
- if nothing is ticked and the cursor row is disabled, Enter does not advance. The screen stays
  and shows the row's existing incompatibility reason, which is already carried on the choice
  ([tui.py:2066](../../agent_artifacts/tui.py)) and currently only visible under `?`.

The gesture is idempotent in the sense that matters: ticking `claude` and pressing Enter, and
pressing Enter with the cursor on `claude`, reach the same state.

`empty_selection` remains reachable only when the list has no selectable row at all. That is a
genuine dead end and belongs to the diagnostics design, not here.

Space keeps its current meaning and remains the only way to build a multi-item selection or to
untick.

### D6 — The list stays one line per item; a pinned pane carries the detail

Structured evidence moves out of the row and into a **detail pane pinned below the list**, above
the status bar. The pane always describes the cursor item.

```
  [ ] mcp/github-docker        registry  unverified  risk ?
> [ ] skill/code-review        registry  verified    risk low
  [ ] guideline/python-style   local     verified    risk low

------------------------------------------------
  skill/code-review
  Review a diff for correctness and cleanups.
    source    registry (verified) at 3eff4bd
    risk      low - scanned (4/4)
    harness   claude:current
    status    compatible
```

The list row keeps identity, then the two or three fields that drive a choice, in aligned
columns. Everything else is the pane's job, and the complete record stays behind `?`.

An earlier revision of this design expanded the cursor row in place. That is rejected on two
grounds. It is worse to read: every cursor movement reflows every row below it, so the list has
no stable geometry and the eye loses its place on each keystroke. It is also far more invasive,
because it breaks the invariant `_draw_list` is built on and that a test names explicitly —
`test_draw_list_keeps_each_row_to_one_visual_line` ([tui_test.py:839](../../tests/tui_test.py)) —
forcing cursor, scroll and checked state to be re-indexed from screen rows to item indices.

The pane avoids both problems because it lives outside the list viewport. Item index and row
index stay the same number, so cursor movement and scroll clamping
([tui.py:5441](../../agent_artifacts/tui.py)) are untouched. The only change to the list is its
budget:

```
visible_rows = height - list_start - pane_height - 1
```

which is the reservation trick D2 already applies for the status bar, applied a second time. The
pane has a fixed height computed once per frame, so the list geometry is stable while the cursor
moves.

Where the terminal is too short to afford both — under roughly 16 rows — the pane is dropped
before the list is, and `?` remains the route to everything.

Identity is rendered first and never truncated; the summary and trailing columns absorb all
truncation. Today the key can be pushed off-screen by a long summary, which is the worst possible
field to lose.

### D7 — Content is bounded to a readable measure, not to the terminal

Every renderer currently sizes itself to `_width(stdscr) - 1`. On a wide terminal that produces
the long lines seen in review, and width is its own legibility failure: past roughly 100
characters the eye stops reliably finding the start of the next line, so long rows go unread
even though every character is on screen.

Two bounds apply:

- `READABLE_MEASURE = 80` for wrapped prose — summaries, reasons, the `?` view.
- `CONTENT_MEASURE = 100` for structured lines — list rows, the detail pane, aligned columns.

On a terminal wider than the bound the remaining columns stay empty. That is the point: the
content column keeps a fixed, learnable geometry, and column positions do not drift with the
window size.

Two elements are exempt and keep the full width, because both are single lines whose value is
proportional to what fits: the stepper and the status bar. Digest lines are exempt for a
different reason, given in D8.

### D8 — The detail view is a record, not a paragraph

The `?` view currently renders one sentence built by string concatenation
([tui.py:2049](../../agent_artifacts/tui.py)), mixing prose and three sha256 digests. It becomes
the same `label   value` block used by D6, with the summary as wrapped prose above it and each
digest on its own line. Digest lines are exempt from the measure — a wrapped hash is unreadable
and uncopyable — and are ellipsized only if the terminal is narrower than the digest.

## 4. Rendering contract

The work is split so that everything decidable without a terminal is pure and unit-testable, and
curses is left with painting and key handling.

A new module `agent_artifacts/tui_layout.py` owns generic layout:

```python
READABLE_MEASURE = 80
CONTENT_MEASURE = 100

def measure(width: int, *, bound: int = READABLE_MEASURE) -> int: ...
def wrap(text: str, *, width: int) -> tuple[str, ...]: ...
def columns(cells: tuple[tuple[str, ...], ...], *, width: int) -> tuple[str, ...]: ...
def field_block(fields: tuple[tuple[str, str], ...], *, indent: int, width: int) -> tuple[str, ...]: ...
def status_bar(hints: tuple[tuple[str, str], ...], *, counters: tuple[str, ...], width: int) -> str: ...
def pane_budget(*, height: int, requested: int) -> int: ...
```

`columns` computes one shared column layout for the whole list, so column positions are identical
on every row. `pane_budget` returns the rows the detail pane may occupy, or `0` when the terminal
is too short to afford one (D6).

`agent_artifacts/tui_marketplace.py` gains artifact-specific projections beside the existing
`render_marketplace_row`:

```python
def artifact_cells(row: MarketplaceArtifactRow) -> tuple[str, ...]: ...
def render_artifact_pane(row: MarketplaceArtifactRow, *, width: int) -> tuple[str, ...]: ...
def render_artifact_detail(row: MarketplaceArtifactRow) -> tuple[str, ...]: ...
```

`artifact_cells` returns the row's cells unpadded; the list widget passes the whole set through
`columns` so alignment is computed across all rows at once rather than per row.

`render_marketplace_row` is retained during the change and removed once no caller remains; it has
direct test coverage ([tui_marketplace_test.py:120](../../tests/tui_marketplace_test.py)) that
must move to the replacements rather than simply being deleted.

`agent_artifacts/wizard.py` keeps ownership of stage semantics: `projected_stages_for` is added,
`render_stepper` re-markered, `render_header` reduced to stepper, optional current-stage
fallback, basket and notices.

## 5. Text frontend parity

Text mode has no cursor, so D5's "row under the cursor" has no analogue. Equivalence is preserved
at the level of outcome rather than gesture: confirming an empty selection in text mode re-prompts
with an explicit hint instead of ending the wizard. The silent exit disappears from both
frontends, which is the property that matters.

Text mode already carries its hints in the prompt itself (`Selection (b=back, q=quit): `), which
is the text-mode equivalent of a pinned bottom bar — it is the last thing printed before input.
Those prompts stay; `render_header` stops adding a second copy for text mode too.

## 6. Invariants that change

Two currently-asserted properties are deliberately broken and their tests must be rewritten, not
deleted:

1. `render_header` emits a hint line;
2. `render_header` emits `Stage: <label>`.

One existing invariant is deliberately **kept**: one list item renders as exactly one visual line
(`test_draw_list_keeps_each_row_to_one_visual_line`). D6 was chosen partly so this stays true, and
it is now load-bearing rather than incidental — the pane exists precisely so the list never
reflows.

Three properties are newly asserted: the status bar is present on the final row of every list
frame regardless of scroll offset; no rendered line contains `·` as a field separator; and no
structured line exceeds `CONTENT_MEASURE` however wide the terminal is.

## 7. Secondary decisions

These did not come from the review session; they surfaced while reading the renderers. All three
have been decided.

### D9 — Both frontends accept `b`, and the bar says `b=back`

Curses accepts Backspace today, text accepts `b`/`back`, and the two legends have always
advertised different keys. With hints centralized in one bar the inconsistency becomes
conspicuous: the bar cannot honestly document two frontends at once.

Curses gains `b` as a back key; Backspace keeps working as an unadvertised alias, since it is the
reflex in a full-screen interface and breaking it would be gratuitous. Text is unchanged. The bar
documents `b=back` — one key, true in both frontends, and three characters cheaper in a line that
degrades under width pressure.

### D10 — Disabled rows are marked `[!]`

`[-]` and `[ ]` are hard to tell apart at a glance, so an unavailable artifact reads as merely
unticked. The marker becomes `[!]`.

The box column is retained rather than dropped, which keeps every row's identity starting at the
same screen column — the alignment D6 depends on. The reason stays in the pinned pane, which is
where the cursor row's evidence already lives, so no reason text competes with the columns.

### D11 — Onboarding drops its key list

`onboarding_lines` ([wizard.py:340](../../agent_artifacts/wizard.py)) enumerates controls that D2
now keeps permanently on screen. The screen keeps only what the bar cannot express: what aart
does, what User and Maintainer mean, and where artifacts come from.

### Noted, not a decision

`Selected: N` moves from a header line into the status bar counters by D2, reclaiming a header
row. Recorded here because it is a visible relocation rather than a deletion.

## 8. Risks

- Vertical budget contention. Header, list, pane and bar now compete for rows, and three of them
  are reservations. The failure mode is a list squeezed to one or two rows on a short terminal.
  Mitigation: a single pure `pane_budget` decides, with the fixed give-up order — pane first,
  then header extras, never the list below three rows and never the bar.
- Roughly a dozen tests across six files assert on the strings being removed. They must be
  rewritten to assert on the new contract, and a bulk find-and-replace would silently weaken
  them.
- Column layout is computed across all rows, so one pathological value can widen a column for
  everyone. `columns` caps any single column and truncates within it rather than letting it push
  later columns off screen.

## 9. Boundary with typed wizard errors

[DESIGN-typed-wizard-errors.md](DESIGN-typed-wizard-errors.md) owns what a failure *is*: its
code, stage, context and remediation. This design owns where text lands on screen and which
keystroke does what.

They meet in exactly one place. `No artifacts selected; no changes were made.` is today both a
presentation problem and a diagnostics problem. D5 removes the case where it fires spuriously;
what remains — a list with no selectable row — is a real dead end and its message, code and
remediation belong to the diagnostics design. This design must not invent a competing failure
channel for it.

## 10. Acceptance

- No screen shows the same key hint twice, and no rendered line uses `·` as a separator.
- The status bar is visible on the last row of every list screen at any scroll offset.
- The stepper shows the full projected path from the first screen, with `✓ ▸ ·` and a trailing
  `…` while the tail is a projection.
- Enter on a fresh profile list with the cursor on `claude` proceeds with `claude` selected.
- Enter with the cursor on an incompatible artifact keeps the screen open and shows the reason.
- Every artifact row occupies exactly one line with aligned columns, and moving the cursor changes
  no row's position or content.
- The pinned pane shows the cursor artifact's summary, source, trust, risk, coverage, harness and
  compatibility as indented aligned fields, and is dropped before the list on short terminals.
- No structured line exceeds 100 columns and no prose line exceeds 80, on a terminal of any width.
- `?` wraps prose at 80 columns, renders fields as a record, and puts each digest on its own line.
- Text and curses reach the same outcomes; neither ends the session on an empty confirm.
- `b` goes back in both frontends and the bar advertises it; Backspace still works in curses.
- Disabled rows show `[!]` and keep the box column aligned with every other row.
- The onboarding screen names no keys.
- `python scripts/quality.py` is green.
