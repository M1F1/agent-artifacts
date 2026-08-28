"""What "matches" and "first" mean, stated once, because three frontends now depend on them.

Ranking is the kind of thing that is right until somebody reorders two branches, and then it is
quietly wrong forever: the artifact a person was looking for is on the second screen and they
conclude the catalog does not have it. Each test here is one sentence of the contract.
"""

from __future__ import annotations

import unittest

from agent_artifacts.marketplace.search import (
    Document,
    Hit,
    match,
    score,
    search,
    summary_line,
    terms,
)

CATALOG = (
    Document(
        "code-review",
        "acme/skill/code-review",
        "Reviews a Python diff against the team's rules.",
        (("authors", "Ada Lovelace"), ("license", "MIT")),
    ),
    Document(
        "python-format",
        "acme/skill/python-format",
        "Formats Python sources.",
        (("authors", "Grace Hopper"),),
    ),
    Document(
        "review",
        "other/command/review",
        "Opens a review checklist.",
    ),
    Document(
        "release-notes",
        "acme/skill/release-notes",
        "Writes the notes a release needs.",
    ),
)


class TermsTest(unittest.TestCase):
    def test_the_words_are_folded_and_kept_in_the_order_typed(self):
        self.assertEqual(("review", "python"), terms("  Review   PYTHON "))

    def test_a_word_typed_twice_is_one_word(self):
        self.assertEqual(("review",), terms("review review"))

    def test_nothing_typed_is_no_words(self):
        self.assertEqual((), terms("   "))


class MatchTest(unittest.TestCase):
    def test_a_name_that_is_the_word_beats_a_name_that_starts_with_it(self):
        exact, _ = match(Document("review"), "review")
        prefix, _ = match(Document("review-notes"), "review")

        self.assertGreater(exact, prefix)

    def test_a_name_that_starts_with_the_word_beats_a_name_that_merely_holds_it(self):
        prefix, _ = match(Document("review-notes"), "review")
        inside, _ = match(Document("code-review"), "review")

        self.assertGreater(prefix, inside)

    def test_a_name_beats_a_coordinate_beats_a_summary_beats_anything_else(self):
        name, _ = match(Document("thing"), "thing")
        coordinate, _ = match(Document("other", "acme/skill/thing"), "thing")
        summary, _ = match(Document("other", "", "a thing"), "thing")
        other, _ = match(Document("other", "", "", (("authors", "thing"),)), "thing")

        self.assertGreater(name, coordinate)
        self.assertGreater(coordinate, summary)
        self.assertGreater(summary, other)

    def test_every_place_the_word_was_found_is_reported(self):
        _, places = match(CATALOG[0], "review")

        self.assertEqual(("name", "coordinate", "summary"), places)

    def test_one_word_in_two_places_is_worth_the_better_place_only(self):
        """Twice in one artifact says no more about it than once, so it does not score twice."""

        both, _ = match(Document("thing", "acme/skill/thing"), "thing")
        name_only, _ = match(Document("thing"), "thing")

        self.assertEqual(name_only, both)

    def test_a_word_that_is_nowhere_scores_nothing_and_names_nowhere(self):
        self.assertEqual((0, ()), match(CATALOG[0], "kubernetes"))

    def test_case_and_spacing_in_the_document_do_not_hide_a_match(self):
        found, _ = match(Document("X", "", "Reviews   a\n  PYTHON diff"), "python diff")

        self.assertTrue(found)


class ScoreTest(unittest.TestCase):
    def test_a_word_that_is_missing_makes_the_whole_document_miss(self):
        self.assertEqual((0, ()), score(CATALOG[3], ("release", "python")))

    def test_the_words_that_do_match_are_added_up(self):
        first, _ = match(CATALOG[0], "review")
        second, _ = match(CATALOG[0], "python")
        total, _ = score(CATALOG[0], ("review", "python"))

        self.assertEqual(first + second, total)


class SearchTest(unittest.TestCase):
    def test_a_second_word_narrows_rather_than_widens(self):
        one = search(CATALOG, "review")
        two = search(CATALOG, "review python")

        self.assertEqual((2, 0), tuple(hit.index for hit in one))
        self.assertEqual((0,), tuple(hit.index for hit in two))

    def test_the_exact_name_comes_first(self):
        (best, *_rest) = search(CATALOG, "review")

        self.assertEqual(2, best.index)
        self.assertEqual("review", CATALOG[best.index].name)

    def test_a_hit_points_back_at_the_callers_own_row(self):
        """The frontends renumber nothing, so an index that drifts selects the wrong artifact."""

        (hit,) = search(CATALOG, "grace")

        self.assertIsInstance(hit, Hit)
        self.assertEqual(CATALOG[hit.index].name, "python-format")
        self.assertEqual(("authors",), hit.matched)

    def test_rows_that_tie_keep_catalog_order(self):
        tied = (Document("a", "", "shared word"), Document("b", "", "shared word"))

        self.assertEqual((0, 1), tuple(hit.index for hit in search(tied, "shared")))

    def test_nothing_typed_matches_everything_in_catalog_order(self):
        hits = search(CATALOG, "   ")

        self.assertEqual(tuple(range(len(CATALOG))), tuple(hit.index for hit in hits))
        self.assertEqual((0,) * len(CATALOG), tuple(hit.score for hit in hits))

    def test_a_limit_takes_the_best_rows_not_the_first_ones(self):
        hits = search(CATALOG, "review", limit=1)

        self.assertEqual((2,), tuple(hit.index for hit in hits))

    def test_a_limit_below_one_is_refused_rather_than_returning_nothing(self):
        with self.assertRaises(ValueError):
            search(CATALOG, "review", limit=0)

    def test_an_empty_catalog_is_not_an_error(self):
        self.assertEqual((), search((), "review"))


class SummaryLineTest(unittest.TestCase):
    def test_it_says_how_much_of_the_catalog_answered(self):
        self.assertEqual("2 of 4 match 'review'.", summary_line("review", 2, 4))

    def test_nothing_found_says_what_was_searched(self):
        line = summary_line("kubernetes", 0, 4)

        self.assertIn("kubernetes", line)
        self.assertIn("4 entries searched", line)

    def test_no_query_counts_rather_than_quotes(self):
        self.assertEqual("4 entries.", summary_line("", 4, 4))
        self.assertEqual("1 entry.", summary_line("", 1, 1))


if __name__ == "__main__":
    unittest.main()
