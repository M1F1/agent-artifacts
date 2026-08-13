"""WP-0: the pure layout kernel shared by every TUI renderer.

Everything here is decidable without a terminal, so the curses layer is left with painting and
key handling only. See docs/design/DESIGN-tui-legibility.md.
"""

from __future__ import annotations

import pathlib
import unittest

from agent_artifacts import tui_layout as layout


class MeasureTests(unittest.TestCase):
    def test_prose_is_bounded_below_the_terminal_width(self):
        self.assertEqual(layout.measure(200), layout.READABLE_MEASURE)
        self.assertEqual(layout.measure(40), 40)

    def test_structured_content_uses_the_wider_bound(self):
        self.assertEqual(layout.measure(200, bound=layout.CONTENT_MEASURE), layout.CONTENT_MEASURE)

    def test_degenerate_widths_never_fall_below_one(self):
        self.assertEqual(layout.measure(0), 1)
        self.assertEqual(layout.measure(-5), 1)


class WrapTests(unittest.TestCase):
    def test_wide_terminals_do_not_produce_long_measures(self):
        text = "word " * 200

        lines = layout.wrap(text, width=200)

        self.assertTrue(lines)
        self.assertTrue(all(len(line) <= layout.READABLE_MEASURE for line in lines))

    def test_embedded_newlines_do_not_break_the_line_model(self):
        lines = layout.wrap("first\nsecond\rthird", width=80)

        self.assertEqual(lines, ("first second third",))

    def test_empty_text_still_yields_one_line(self):
        self.assertEqual(layout.wrap("", width=80), ("",))


class ColumnsTests(unittest.TestCase):
    ROWS = (
        ("mcp/github-docker", "registry", "unverified", "risk ?"),
        ("skill/code-review", "registry", "verified", "risk low"),
        ("guideline/python-style", "local", "verified", "risk low"),
    )

    def test_column_positions_are_identical_on_every_row(self):
        lines = layout.columns(self.ROWS, width=100)

        positions = {line.index("registry") for line in lines[:2]}
        self.assertEqual(len(positions), 1)

    def test_no_line_exceeds_the_requested_width(self):
        for width in (12, 24, 40, 80, 100, 200):
            for line in layout.columns(self.ROWS, width=width):
                self.assertLessEqual(len(line), width, f"width={width}")

    def test_structured_lines_stay_within_the_content_measure(self):
        rows = tuple(("identity", "x" * 300, "y" * 300) for _ in range(3))

        for line in layout.columns(rows, width=400):
            self.assertLessEqual(len(line), layout.CONTENT_MEASURE)

    def test_one_pathological_cell_does_not_push_later_columns_off_screen(self):
        rows = (
            ("short", "a" * 300, "keep"),
            ("other", "b", "keep"),
        )

        lines = layout.columns(rows, width=60)

        self.assertTrue(all("keep" in line for line in lines))

    def test_identity_survives_while_other_columns_can_still_give(self):
        rows = (("guideline/python-style", "registry", "verified"),)

        line = layout.columns(rows, width=40)[0]

        self.assertTrue(line.startswith("guideline/python-style"))

    def test_no_row_is_padded_with_trailing_whitespace(self):
        for line in layout.columns(self.ROWS, width=100):
            self.assertEqual(line, line.rstrip())

    def test_no_separator_punctuation_is_introduced(self):
        for line in layout.columns(self.ROWS, width=100):
            self.assertNotIn("·", line)


class FieldBlockTests(unittest.TestCase):
    FIELDS = (
        ("source", "registry (verified) at 3eff4bd"),
        ("risk", "low - scanned (4/4)"),
        ("harness", "claude:current"),
    )

    def test_values_align_in_one_column(self):
        lines = layout.field_block(self.FIELDS, indent=4, width=80)

        starts = {
            line.index(value.split()[0])
            for line, (_label, value) in zip(lines, self.FIELDS, strict=True)
        }
        self.assertEqual(len(starts), 1)

    def test_indent_is_applied_to_every_line(self):
        lines = layout.field_block(self.FIELDS, indent=6, width=80)

        self.assertTrue(all(line.startswith(" " * 6) for line in lines))

    def test_long_values_wrap_into_the_value_column_not_the_label_column(self):
        fields = (("source", "word " * 60),)

        lines = layout.field_block(fields, indent=4, width=60)

        self.assertGreater(len(lines), 1)
        continuation = lines[1]
        self.assertEqual(continuation.index(continuation.strip()[0]), lines[0].index("word"))

    def test_no_line_exceeds_the_requested_width(self):
        for width in (20, 40, 80, 200):
            for line in layout.field_block(self.FIELDS, indent=4, width=width):
                self.assertLessEqual(len(line), min(width, layout.CONTENT_MEASURE))

    def test_empty_fields_render_nothing(self):
        self.assertEqual(layout.field_block((), indent=4, width=80), ())


class StatusBarTests(unittest.TestCase):
    HINTS = layout.HINT_ORDER

    def test_hints_are_comma_separated_and_never_dot_separated(self):
        bar = layout.status_bar(self.HINTS, counters=(), width=120)

        self.assertIn("space=toggle, enter=confirm", bar)
        self.assertNotIn("·", bar)

    def test_counters_are_right_aligned_when_there_is_room(self):
        bar = layout.status_bar(self.HINTS, counters=("2 selected", "5-12 of 48"), width=120)

        self.assertTrue(bar.startswith("space=toggle"))
        self.assertTrue(bar.rstrip().endswith("5-12 of 48"))
        self.assertLessEqual(len(bar), 120)

    def test_the_row_range_is_the_first_thing_dropped(self):
        counters = ("2 selected", "5-12 of 48")
        # One column narrower than the narrowest bar that fits both counters, derived rather than
        # hard-coded so the property survives any change to the hint table.
        narrowest = min(
            width
            for width in range(1, 201)
            if counters[1] in layout.status_bar(self.HINTS, counters=counters, width=width)
        )

        bar = layout.status_bar(self.HINTS, counters=counters, width=narrowest - 1)

        self.assertNotIn("5-12 of 48", bar)
        self.assertIn("2 selected", bar)

    def test_hints_degrade_from_the_right_before_enter_and_quit(self):
        bar = layout.status_bar(self.HINTS, counters=(), width=40)

        self.assertNotIn("a=add", bar)
        self.assertIn("enter=confirm", bar)
        self.assertIn("q=quit", bar)

    def test_enter_and_quit_survive_the_narrowest_useful_bar(self):
        bar = layout.status_bar(self.HINTS, counters=(), width=24)

        self.assertIn("enter", bar)
        self.assertIn("q", bar)

    def test_the_bar_uses_the_full_terminal_width_not_the_content_measure(self):
        bar = layout.status_bar(self.HINTS, counters=("40 selected", "1-60 of 900"), width=200)

        self.assertGreater(len(bar), layout.CONTENT_MEASURE)
        self.assertLessEqual(len(bar), 200)

    def test_no_bar_ever_exceeds_its_width(self):
        for width in range(1, 201):
            bar = layout.status_bar(self.HINTS, counters=("2 selected",), width=width)
            self.assertLessEqual(len(bar), width, f"width={width}")


class PaneBudgetTests(unittest.TestCase):
    def test_short_terminals_drop_the_pane_before_the_list(self):
        self.assertEqual(layout.pane_budget(height=10, requested=6), 0)

    def test_the_pane_never_starves_the_list_below_three_rows(self):
        for height in range(1, 61):
            budget = layout.pane_budget(height=height, requested=40)
            remaining = height - layout.CHROME_ROWS - budget
            if budget:
                self.assertGreaterEqual(remaining, layout.MIN_LIST_ROWS, f"height={height}")

    def test_a_modest_request_is_granted_whole_on_a_normal_terminal(self):
        self.assertEqual(layout.pane_budget(height=24, requested=6), 6)

    def test_nothing_is_reserved_when_nothing_is_requested(self):
        self.assertEqual(layout.pane_budget(height=40, requested=0), 0)


class KernelContractTests(unittest.TestCase):
    def test_the_kernel_depends_on_no_other_tui_module(self):
        source = pathlib.Path(layout.__file__).read_text(encoding="utf-8")

        for forbidden in ("agent_artifacts.tui ", "from .tui", "tui_marketplace", "wizard"):
            self.assertNotIn(forbidden, source)

    def test_every_function_is_total_across_plausible_terminals(self):
        rows = (("identity", "value"), ("other", "value"))
        fields = (("label", "value"),)
        for width in range(1, 201):
            layout.wrap("some prose to lay out", width=width)
            layout.columns(rows, width=width)
            layout.field_block(fields, indent=4, width=width)
            layout.status_bar(layout.HINT_ORDER, counters=("2 selected",), width=width)
        for height in range(1, 61):
            layout.pane_budget(height=height, requested=6)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
