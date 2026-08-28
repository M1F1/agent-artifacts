"""Filtering a long catalog, in both frontends, without renumbering a single row.

The catalog a person meets is not the fixture's three artifacts; it is however many their company
publishes, and paging it to find a name they half remember is the thing this replaces. The one
rule everything here protects is that a filter hides rows and does nothing else: the numbers do
not move, and what was ticked stays ticked. A filtered list that renumbered itself would install
whatever happens to sit at the number the person read.
"""

from __future__ import annotations

import curses
import unittest

from agent_artifacts import tui
from tests.tui_wizard_curses_test import Screen

CHOICES = (
    tui._Choice(
        "artifact",
        "code-review",
        "skill",
        "[skill] code-review — Reviews a Python diff.",
        description="Reviews a Python diff.",
        qualified_key="acme/skill/code-review",
    ),
    tui._Choice(
        "artifact",
        "release-notes",
        "skill",
        "[skill] release-notes — Writes what a release changed.",
        description="Writes what a release changed.",
        qualified_key="acme/skill/release-notes",
    ),
    tui._Choice(
        "artifact",
        "house",
        "memory",
        "[memory] house — House conventions for reviewers.",
        description="House conventions for reviewers.",
        qualified_key="acme/memory/house",
    ),
    tui._Choice(
        "collection",
        "essentials",
        None,
        "[collection] essentials — The essential artifacts.",
        description="The essential artifacts.",
        qualified_key="acme/collection/essentials",
    ),
)


def _scripted(answers):
    values = iter(answers)

    def read(_prompt=""):
        try:
            return next(values)
        except StopIteration:
            raise EOFError from None

    return read


class TextSearchTest(unittest.TestCase):
    """`/TEXT` at the wizard's selection prompt."""

    def _run(self, answers):
        written: list[str] = []
        event = tui._prompt_wizard_indices(
            _scripted(answers), written.append, "Selection: ", CHOICES
        )
        return event, written

    def test_a_query_shows_only_the_rows_that_match(self):
        _event, written = self._run(["/release"])

        rows = [line for line in written if line.strip().startswith(("1.", "2.", "3.", "4."))]
        self.assertEqual(1, len(rows), written)
        self.assertIn("release-notes", rows[0])

    def test_a_shown_row_keeps_the_number_it_has_in_the_full_list(self):
        """The caller's indices address the basket and the plan, so they cannot be re-issued."""

        event, written = self._run(["/release", "2"])

        rows = [line for line in written if "release-notes" in line]
        self.assertTrue(rows[0].strip().startswith("2."), rows)
        self.assertEqual((1,), event.selected)

    def test_the_answer_says_how_much_of_the_list_matched(self):
        _event, written = self._run(["/review"])

        self.assertIn("2 of 4 match 'review'.", written)

    def test_a_bare_slash_lists_everything_again(self):
        _event, written = self._run(["/review", "/"])

        self.assertIn("4 entries.", written)
        self.assertEqual(1, len([line for line in written if "essentials" in line]))

    def test_a_query_that_matches_nothing_says_so_and_keeps_the_prompt(self):
        event, written = self._run(["/kubernetes", "3"])

        self.assertIn("Nothing matches 'kubernetes'. 4 entries searched.", written)
        self.assertEqual((2,), event.selected)

    def test_the_type_is_searchable_so_one_kind_can_be_listed_alone(self):
        _event, written = self._run(["/memory"])

        rows = [line for line in written if line.strip()[:2] in ("1.", "2.", "3.", "4.")]
        self.assertEqual(1, len(rows), written)
        self.assertIn("house", rows[0])

    def test_a_search_is_not_a_selection_and_never_ends_the_prompt(self):
        event, _written = self._run(["/review", "q"])

        self.assertEqual("quit", event.kind)


class CursesSearchTest(unittest.TestCase):
    """`/` on the curses list: type to narrow, enter to keep, escape to clear."""

    def _labels(self):
        return tuple(choice.label for choice in CHOICES)

    def _rows(self, screen: Screen) -> list[str]:
        return [
            value for _row, _column, value in screen.lines if value.strip().startswith(("> ", "["))
        ]

    def _painted(self, screen: Screen) -> str:
        """Every frame, not the last one: a filter is judged by what it showed while typing."""

        return "\n".join(value for _row, _column, value in screen.history)

    def test_typing_after_slash_narrows_the_list(self):
        # / r e l  then enter to keep the filter, then enter to confirm the cursor row.
        keys = (ord("/"), ord("r"), ord("e"), ord("l"), 10, 10)
        screen = Screen(keys, height=20, width=90)

        result = tui._curses_multiselect(
            curses,
            screen,
            "Artifacts",
            self._labels(),
            documents=tui._choice_documents(CHOICES),
        )

        self.assertEqual((1,), result)

    def test_the_row_confirmed_is_the_row_the_filter_showed(self):
        """The cursor is an index into the caller's list, so a filter must move it, not renumber."""

        keys = (ord("/"), ord("h"), ord("o"), ord("u"), ord("s"), ord("e"), 10, 10)
        screen = Screen(keys, height=20, width=90)

        result = tui._curses_multiselect(
            curses, screen, "Artifacts", self._labels(), documents=tui._choice_documents(CHOICES)
        )

        self.assertEqual((2,), result)

    def test_escape_clears_the_filter_instead_of_quitting(self):
        """Outside a filter Escape leaves the screen; inside one it only drops the filter."""

        keys = (ord("/"), ord("h"), 27, 10)
        screen = Screen(keys, height=20, width=90)

        result = tui._curses_multiselect(
            curses, screen, "Artifacts", self._labels(), documents=tui._choice_documents(CHOICES)
        )

        self.assertIsNotNone(result)
        last_frame = [value for _row, _column, value in screen.lines]
        self.assertEqual(4, len([line for line in last_frame if "[ ]" in line]), last_frame)

    def test_typing_moves_the_cursor_onto_the_best_match(self):
        """One more letter and Enter takes the row the filter was narrowing towards."""

        keys = (ord("/"), ord("h"), 10, 10)
        screen = Screen(keys, height=20, width=90)

        result = tui._curses_multiselect(
            curses, screen, "Artifacts", self._labels(), documents=tui._choice_documents(CHOICES)
        )

        self.assertEqual((2,), result)

    def test_dropping_the_filter_leaves_the_cursor_where_it_was(self):
        """Clearing a filter is not a reason to lose the row someone is looking at."""

        keys = (ord("/"), ord("h"), 27, 10)
        screen = Screen(keys, height=20, width=90)

        result = tui._curses_multiselect(
            curses, screen, "Artifacts", self._labels(), documents=tui._choice_documents(CHOICES)
        )

        self.assertEqual((2,), result)

    def test_a_letter_typed_into_the_filter_is_not_a_command(self):
        """`q` would quit and `b` would go back outside the filter; inside it they are letters."""

        keys = (ord("/"), ord("q"), ord("b"), 27, 10)
        screen = Screen(keys, height=20, width=90)

        result = tui._curses_multiselect(
            curses,
            screen,
            "Artifacts",
            self._labels(),
            wizard=True,
            documents=tui._choice_documents(CHOICES),
        )

        self.assertEqual("confirm", result.kind)

    def test_backspace_widens_the_filter_again(self):
        keys = (ord("/"), ord("h"), ord("o"), ord("u"), 8, 8, 8, 10, 10)
        screen = Screen(keys, height=20, width=90)

        tui._curses_multiselect(
            curses, screen, "Artifacts", self._labels(), documents=tui._choice_documents(CHOICES)
        )

        self.assertIn("4 entries.", self._painted(screen))

    def test_the_filter_says_what_is_typed_and_how_much_answered(self):
        keys = (ord("/"), ord("r"), ord("e"), 27, 10)
        screen = Screen(keys, height=20, width=90)

        tui._curses_multiselect(
            curses, screen, "Artifacts", self._labels(), documents=tui._choice_documents(CHOICES)
        )

        painted = self._painted(screen)
        self.assertIn("/re", painted)
        self.assertIn("match 're'", painted)

    def test_a_filter_hides_rows_and_never_unticks_them(self):
        # Tick row 1 (code-review), filter down to `house`, tick that too, then confirm.
        keys = (ord(" "), ord("/"), *map(ord, "conventions"), 10, ord(" "), 10)
        screen = Screen(keys, height=20, width=90)

        result = tui._curses_multiselect(
            curses, screen, "Artifacts", self._labels(), documents=tui._choice_documents(CHOICES)
        )

        self.assertEqual((0, 2), result)

    def test_a_filter_that_matches_nothing_refuses_rather_than_confirming_a_hidden_row(self):
        keys = (ord("/"), ord("z"), ord("z"), 10, 10, 27)
        screen = Screen(keys, height=20, width=90)

        result = tui._curses_multiselect(
            curses, screen, "Artifacts", self._labels(), documents=tui._choice_documents(CHOICES)
        )

        self.assertIsNone(result)
        self.assertIn("Nothing matches 'zz'", self._painted(screen))

    def test_the_status_bar_advertises_the_key(self):
        screen = Screen((10,), height=16, width=90)

        tui._curses_multiselect(curses, screen, "Artifacts", ("one", "two"))

        bar = [value for row, _column, value in screen.lines if row == screen.height - 1][0]
        self.assertIn("/=search", bar)

    def test_without_documents_the_printed_label_is_what_is_searched(self):
        """Every list gets the filter; only the artifact list can rank it by name."""

        keys = (ord("/"), ord("t"), ord("w"), ord("o"), 10, 10)
        screen = Screen(keys, height=20, width=90)

        result = tui._curses_multiselect(curses, screen, "Rows", ("one", "two", "three"))

        self.assertEqual((1,), result)


if __name__ == "__main__":
    unittest.main()
