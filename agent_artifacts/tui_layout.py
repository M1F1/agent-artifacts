"""Pure layout kernel for the text and curses TUI (WP-0 of DESIGN-tui-legibility).

Everything decidable without a terminal lives here: how wide content may be, how a record turns
into aligned lines, how the status bar degrades, and how many rows the detail pane may claim. The
curses layer is left with painting and key handling.

Two rules from the design are enforced structurally rather than by convention:

- ``·`` is never a separator. Hints join with ``, ``, records become columns and field blocks.
- content is bounded to a readable measure rather than to the terminal width, because a line too
  long to track is as unread as a line truncated away.
"""

from __future__ import annotations

import textwrap
from typing import Mapping, Sequence, Tuple

# --------------------------------------------------------------------------- #
# Frozen vocabulary.                                                            #
# --------------------------------------------------------------------------- #

READABLE_MEASURE = 80
"""Bound for wrapped prose: summaries, reasons, the detail view."""

CONTENT_MEASURE = 100
"""Bound for structured lines: list rows, the detail pane, aligned columns."""

STAGE_CONFIRMED = "✓"
STAGE_CURRENT = "▸"
STAGE_PENDING = "·"
STAGE_JOIN = "→"
STAGE_PROJECTION = "…"

BOX_CHECKED = "[x]"
BOX_EMPTY = "[ ]"
BOX_DISABLED = "[!]"

HINT_ORDER: Tuple[Tuple[str, str], ...] = (
    ("space", "toggle"),
    ("enter", "confirm"),
    ("b", "back"),
    ("?", "details"),
    ("a", "add"),
    ("s", "sync"),
    ("i", "resubscribe"),
    ("r", "remove"),
    ("q", "quit"),
)
"""The canonical hint table. Rendering drops from the right, so later entries are cheaper."""

PROTECTED_HINTS = frozenset({"enter", "q"})
"""Hints that survive any width: without them a screen has no documented exit."""

MIN_LIST_ROWS = 3
"""The list never shrinks below this; the pane gives way first."""

CHROME_ROWS = 4
"""Rows a list screen spends on stepper, title, counters, and the status bar."""

PANE_MIN_HEIGHT = 16
"""Below this the detail pane is dropped entirely and ``?`` remains the route to everything."""

_COLUMN_GAP = 2
_LABEL_GAP = 2
_COUNTER_GAP = 3


def _ellipsize(text: str, width: int) -> str:
    """One visual line no wider than *width*, marking truncation with ``…``."""

    if width <= 0:
        return ""
    flat = text.replace("\r", " ").replace("\n", " ")
    if len(flat) <= width:
        return flat
    if width == 1:
        return STAGE_PROJECTION
    return flat[: width - 1] + STAGE_PROJECTION


def measure(width: int, *, bound: int = READABLE_MEASURE) -> int:
    """Bound *width* to a readable measure, never returning less than one column."""

    return min(max(width, 1), max(bound, 1))


def wrap(text: str, *, width: int) -> Tuple[str, ...]:
    """Wrap prose at the readable measure, collapsing embedded line breaks."""

    limit = measure(width)
    flat = text.replace("\r", " ").replace("\n", " ")
    wrapped = textwrap.wrap(
        flat,
        width=limit,
        break_long_words=True,
        break_on_hyphens=False,
    )
    return tuple(wrapped) or ("",)


def _column_widths(rows: Sequence[Sequence[str]], *, budget: int) -> Tuple[int, ...]:
    """Fit natural column widths into *budget*, shrinking the widest later column first.

    The first column is identity and is shrunk only once every other column is down to one
    character, so a long summary can never push a key off screen.
    """

    count = max((len(row) for row in rows), default=0)
    if not count:
        return ()
    widths = [
        max((len(row[index]) for row in rows if index < len(row)), default=0)
        for index in range(count)
    ]
    gaps = _COLUMN_GAP * (count - 1)
    while sum(widths) + gaps > budget:
        shrinkable = [index for index in range(1, count) if widths[index] > 1]
        if not shrinkable:
            shrinkable = [index for index in range(count) if widths[index] > 1]
        if not shrinkable:
            break
        widest = max(shrinkable, key=lambda index: (widths[index], index))
        widths[widest] -= 1
    return tuple(widths)


def columns(rows: Sequence[Sequence[str]], *, width: int) -> Tuple[str, ...]:
    """Lay every row out on one shared column grid, so positions never drift between rows."""

    if not rows:
        return ()
    budget = measure(width, bound=CONTENT_MEASURE)
    widths = _column_widths(rows, budget=budget)
    if not widths:
        return tuple("" for _row in rows)
    lines = []
    for row in rows:
        cells = []
        for index, cell_width in enumerate(widths):
            cell = row[index] if index < len(row) else ""
            cells.append(_ellipsize(cell, cell_width).ljust(cell_width))
        lines.append(_ellipsize((" " * _COLUMN_GAP).join(cells).rstrip(), budget))
    return tuple(lines)


def field_block(fields: Sequence[Tuple[str, str]], *, indent: int, width: int) -> Tuple[str, ...]:
    """Render ``label   value`` lines on one label column, wrapping values under the value column."""

    if not fields:
        return ()
    budget = measure(width, bound=CONTENT_MEASURE)
    pad = " " * max(indent, 0)
    label_width = max(len(label) for label, _value in fields)
    value_column = len(pad) + label_width + _LABEL_GAP
    available = max(budget - value_column, 1)
    lines = []
    for label, value in fields:
        wrapped = wrap(value, width=available) if value else ("",)
        head = f"{pad}{label.ljust(label_width)}{' ' * _LABEL_GAP}{wrapped[0]}"
        lines.append(_ellipsize(head.rstrip(), budget))
        for continuation in wrapped[1:]:
            lines.append(_ellipsize(f"{' ' * value_column}{continuation}".rstrip(), budget))
    return tuple(lines)


def _hint_text(hints: Sequence[Tuple[str, str]]) -> str:
    return ", ".join(f"{key}={action}" for key, action in hints)


def status_bar(
    hints: Sequence[Tuple[str, str]],
    *,
    counters: Sequence[str] = (),
    width: int,
) -> str:
    """Compose the pinned bar: hints on the left, counters right-aligned.

    The bar is exempt from ``CONTENT_MEASURE`` — it is a single line whose value is proportional
    to what fits. Under pressure it sheds counters from the right, then unprotected hints from the
    right, and only then truncates.
    """

    if width <= 0:
        return ""
    remaining = list(hints)
    shown_counters = list(counters)
    while True:
        left = _hint_text(remaining)
        right = (" " * _COUNTER_GAP).join(shown_counters)
        if not right:
            if len(left) <= width:
                return left
        else:
            if len(left) + _COUNTER_GAP + len(right) <= width:
                filler = width - len(left) - len(right)
                return f"{left}{' ' * filler}{right}"
            shown_counters.pop()
            continue
        droppable = [
            index for index, (key, _action) in enumerate(remaining) if key not in PROTECTED_HINTS
        ]
        if not droppable:
            return _ellipsize(left, width)
        remaining.pop(droppable[-1])


def pane_budget(*, height: int, requested: int) -> int:
    """Rows the detail pane may occupy, or zero when the terminal cannot afford one.

    The give-up order is fixed: the pane yields before the list, the list never falls below
    :data:`MIN_LIST_ROWS`, and the status bar is never sacrificed.
    """

    if requested <= 0 or height < PANE_MIN_HEIGHT:
        return 0
    spare = height - CHROME_ROWS - MIN_LIST_ROWS
    if spare <= 0:
        return 0
    return min(requested, spare)


STAGE_MARKERS: Mapping[str, str] = {
    "confirmed": STAGE_CONFIRMED,
    "current": STAGE_CURRENT,
    "pending": STAGE_PENDING,
}

BOX_MARKERS: Mapping[str, str] = {
    "checked": BOX_CHECKED,
    "empty": BOX_EMPTY,
    "disabled": BOX_DISABLED,
}

__all__ = [
    "BOX_CHECKED",
    "BOX_DISABLED",
    "BOX_EMPTY",
    "BOX_MARKERS",
    "CHROME_ROWS",
    "CONTENT_MEASURE",
    "HINT_ORDER",
    "MIN_LIST_ROWS",
    "PANE_MIN_HEIGHT",
    "PROTECTED_HINTS",
    "READABLE_MEASURE",
    "STAGE_CONFIRMED",
    "STAGE_CURRENT",
    "STAGE_JOIN",
    "STAGE_MARKERS",
    "STAGE_PENDING",
    "STAGE_PROJECTION",
    "columns",
    "field_block",
    "measure",
    "pane_budget",
    "status_bar",
    "wrap",
]
