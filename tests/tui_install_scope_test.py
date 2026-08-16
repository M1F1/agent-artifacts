"""`LAF-64`: the scope selector answers with one type, and which one is decided by its name.

The helper used to take `wizard=True` and answer with a `WizardInput` carrying an *index*, or,
without the flag, with the `InstallScope` itself. Both shapes are legitimate; the trap is that the
function knows which mode it is in and its return type does not say so. A second caller written the
obvious way — `if isinstance(result, WizardInput): return` — compiles, typechecks, and treats every
successful selection as a cancel. That is what the first draft of the receipt flow did, and only a
test caught it.

Two names, two return types, and no flag that can move a caller between them by accident.
"""

from __future__ import annotations

import curses
import inspect
import unittest

from agent_artifacts import tui
from agent_artifacts.wizard import WizardInput

_ENTER = 10
_QUIT = ord("q")
_BACK = ord("b")
_DOWN = curses.KEY_DOWN


class Screen:
    """The smallest screen the list widget will draw on; keys are read in order."""

    def __init__(self, keys=(), *, height=14, width=54):
        self.keys = iter(keys)
        self.height = height
        self.width = width
        self.lines = []

    def clear(self):
        self.lines.clear()

    def addstr(self, row, column, value):
        self.lines.append((row, column, value))

    def refresh(self):
        pass

    def getmaxyx(self):
        return self.height, self.width

    def getch(self):
        return next(self.keys)


class TheWizardEntryPointTests(unittest.TestCase):
    def test_laf64_every_outcome_is_a_wizard_input(self):
        """Confirm, back and quit. A caller may branch on `kind` and never on the type."""

        for name, keys, kind in (
            ("confirm", (_ENTER,), "confirm"),
            ("back", (_BACK,), "back"),
            ("quit", (_QUIT,), "quit"),
        ):
            with self.subTest(name):
                event = tui._curses_install_scope_event(curses, Screen(keys))

                self.assertIsInstance(event, WizardInput)
                self.assertEqual(event.kind, kind)

    def test_laf64_a_confirmed_selection_indexes_the_choice_list(self):
        event = tui._curses_install_scope_event(curses, Screen((_DOWN, _ENTER)))

        self.assertEqual(event.kind, "confirm")
        self.assertEqual(event.selected, (1,))
        self.assertEqual(tui.INSTALL_SCOPE_CHOICES[event.selected[0]].scope, "user")


class TheFlagCannotComeBackTests(unittest.TestCase):
    def test_laf64_the_selector_takes_no_mode_flag(self):
        """The defect was a boolean deciding a return type. Nothing may reintroduce one here."""

        parameters = inspect.signature(tui._curses_install_scope_event).parameters

        self.assertNotIn("wizard", parameters)

    def test_laf64_the_scope_only_shape_is_gone_rather_than_kept_unused(self):
        """Two shapes with one reader is the same trap with a spare exit."""

        self.assertFalse(hasattr(tui, "_curses_install_scope"))


if __name__ == "__main__":
    unittest.main()
