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
| Legibility WP-0 … WP-4 | not started | — |
| Typed errors ERR01 … ERR04, ERR05b, ERR06, ERR07 | not started | — |

Baseline at the time of writing: 1746 unit + 52 integration tests, all ten gates of
`python scripts/quality.py` green. `main` is ahead of `origin/main` and has not been pushed.

## Next task

**WP-0 from [PLAN-tui-legibility.md](PLAN-tui-legibility.md)** — the layout kernel. Owns
`agent_artifacts/tui_layout.py` and `tests/tui_layout_test.py`, both new. Pure, stdlib only, no
imports from `tui`, `wizard`, or `tui_marketplace`.

Public surface to implement:

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

Plus the frozen vocabulary: stage markers `✓ ▸ ·`, box markers `[x] [ ] [!]`, the `→` stepper
join, the `…` projection token, and the hint table `space=toggle, enter=confirm, b=back,
?=details, a=add, q=quit` in that degrade order.

After WP-0: Wave A is WP-1 (`wizard.py`) and WP-2 (`tui_marketplace.py`) in parallel; then WP-3
(`tui.py`) inline on `main`; then WP-4 (docs + gate).

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
