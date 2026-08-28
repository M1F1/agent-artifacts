"""The version is read out of the changelog, so the changelog's shape is load-bearing.

Every rule here exists because getting it wrong produces a wrong version number rather than an
untidy file, and a published version number cannot be taken back.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_test_{name}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


changelog = _load("changelog")

WELL_FORMED = """# Changelog

A preamble that is not a section.

## Unreleased

### Added

- A thing that is now possible.

## 2.0.0 — 2026-08-21

### Removed

- A thing that is not possible any more.

## 1.9.0 — 2026-08-01

### Fixed

- A thing that was wrong.
"""


class ParseTest(unittest.TestCase):
    def test_every_section_is_found_with_its_kinds(self):
        sections = changelog.parse(WELL_FORMED)

        self.assertEqual([None, "2.0.0", "1.9.0"], [section.version for section in sections])
        self.assertEqual(("Added",), sections[0].kinds)
        self.assertFalse(sections[0].released)
        self.assertTrue(sections[1].released)
        self.assertEqual("2026-08-21", sections[1].date)

    def test_a_body_is_everything_under_the_heading(self):
        first = changelog.parse(WELL_FORMED)[0]

        self.assertIn("### Added", first.body)
        self.assertIn("A thing that is now possible.", first.body)
        self.assertNotIn("## 2.0.0", first.body)

    def test_a_heading_in_no_known_shape_is_refused_by_name(self):
        with self.assertRaises(changelog.ChangelogError) as raised:
            changelog.parse("# Changelog\n\n## 2.0.0 (August)\n\nprose\n")

        self.assertIn("## 2.0.0 (August)", str(raised.exception))
        self.assertIn("X.Y.Z", str(raised.exception))


class CheckTest(unittest.TestCase):
    def test_a_well_formed_file_has_nothing_to_say(self):
        self.assertEqual((), changelog.check(WELL_FORMED))

    def test_the_repositorys_own_changelog_passes(self):
        """`docs-check` runs this, but a direct failure names the file rather than the gate."""

        text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

        self.assertEqual((), changelog.check(text))

    def test_versions_must_read_newest_first(self):
        swapped = WELL_FORMED.replace("## 2.0.0 — 2026-08-21", "## 1.0.0 — 2026-08-21")

        (problem,) = changelog.check(swapped)

        self.assertIn("1.9.0 is not below 1.0.0", problem)

    def test_one_version_cannot_appear_twice(self):
        twice = WELL_FORMED.replace("## 1.9.0 — 2026-08-01", "## 2.0.0 — 2026-08-01")

        problems = changelog.check(twice)

        self.assertTrue(any("appears twice" in problem for problem in problems), problems)

    def test_a_date_that_is_not_a_date_is_caught(self):
        wrong = WELL_FORMED.replace("2026-08-21", "2026-13-45")

        problems = changelog.check(wrong)

        self.assertTrue(any("is not a date" in problem for problem in problems), problems)

    def test_an_empty_section_is_caught(self):
        empty = "# Changelog\n\n## 2.0.0 — 2026-08-21\n\n## 1.9.0 — 2026-08-01\n\n- A thing.\n"

        problems = changelog.check(empty)

        self.assertTrue(any("is empty" in problem for problem in problems), problems)

    def test_unreleased_belongs_above_what_has_shipped(self):
        below = """# Changelog

## 2.0.0 — 2026-08-21

### Fixed

- A thing.

## Unreleased

### Added

- Another thing.
"""

        problems = changelog.check(below)

        self.assertTrue(
            any("is not the first section" in problem for problem in problems), problems
        )


class ImpliedPartTest(unittest.TestCase):
    def test_the_largest_part_any_heading_asks_for_wins(self):
        self.assertEqual("major", changelog.implied_part(("Fixed", "Removed", "Added")))
        self.assertEqual("minor", changelog.implied_part(("Fixed", "Added")))
        self.assertEqual("patch", changelog.implied_part(("Fixed", "Documentation")))

    def test_the_heading_is_read_however_it_is_capitalised(self):
        self.assertEqual("major", changelog.implied_part(("breaking",)))

    def test_prose_headings_are_kept_and_ignored(self):
        """`Compatibility` and `Known defects shipped open` say nothing about the number."""

        self.assertEqual(
            "patch",
            changelog.implied_part(("Compatibility", "Known defects shipped open", "Fixed")),
        )

    def test_a_section_that_decides_nothing_refuses_rather_than_guesses(self):
        with self.assertRaises(changelog.ChangelogError) as raised:
            changelog.implied_part(("Compatibility",))

        self.assertIn("cannot be decided", str(raised.exception))
        # And it says what would work.
        self.assertIn("added", str(raised.exception))


class NextVersionTest(unittest.TestCase):
    def test_above_one_the_part_is_the_part(self):
        self.assertEqual(("major", "3.0.0"), changelog.next_version(WELL_FORMED_REMOVED, "2.8.5"))

    def test_below_one_every_part_moves_the_one_below_it(self):
        """`0.y.z` promises nothing, so a removal there is not the event `1.0.0` announces."""

        self.assertEqual(("minor", "0.1.0"), changelog.next_version(WELL_FORMED_REMOVED, "0.0.1"))
        self.assertEqual(("patch", "0.0.2"), changelog.next_version(WELL_FORMED, "0.0.1"))

    def test_the_mapping_below_one_is_stated_once(self):
        self.assertEqual("minor", changelog.part_before_one("major"))
        self.assertEqual("patch", changelog.part_before_one("minor"))
        self.assertEqual("patch", changelog.part_before_one("patch"))


WELL_FORMED_REMOVED = WELL_FORMED.replace(
    "### Added\n\n- A thing that is now possible.", "### Removed\n\n- A thing that is gone."
)


class ReleaseTest(unittest.TestCase):
    def test_cutting_stamps_the_heading_and_keeps_every_word(self):
        cut = changelog.release(WELL_FORMED, "2.1.0", "2026-08-28")

        self.assertIn("## 2.1.0 — 2026-08-28", cut)
        self.assertNotIn("## Unreleased", cut)
        self.assertIn("A thing that is now possible.", cut)
        # And what was already released is untouched.
        self.assertIn("## 2.0.0 — 2026-08-21", cut)

    def test_no_empty_unreleased_is_left_behind(self):
        """An empty section fails the check, so leaving one would break the next run."""

        cut = changelog.release(WELL_FORMED, "2.1.0", "2026-08-28")

        self.assertEqual((), changelog.check(cut))

    def test_cutting_a_file_with_nothing_waiting_says_so(self):
        released_only = (
            WELL_FORMED.split("## Unreleased")[0]
            + WELL_FORMED.split("- A thing that is now possible.\n")[1]
        )

        with self.assertRaises(changelog.ChangelogError) as raised:
            changelog.release(released_only, "0.1.0", "2026-08-28")

        self.assertIn("nothing to release", str(raised.exception))


class SectionBodyTest(unittest.TestCase):
    def test_the_entries_are_handed_to_the_release_scaffold(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "CHANGELOG.md").write_text(WELL_FORMED, encoding="utf-8")

            body = changelog.section_body(root)

        self.assertIn("A thing that is now possible.", body)

    def test_nothing_waiting_is_not_an_error_here(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "CHANGELOG.md").write_text("# Changelog\n\n", encoding="utf-8")

            self.assertIsNone(changelog.section_body(root))


if __name__ == "__main__":
    unittest.main()
