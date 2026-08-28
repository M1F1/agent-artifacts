"""Find an artifact by typing part of it, in whichever frontend the person is already in.

A catalog of a dozen artifacts is a list.  A catalog of two hundred is not: the name someone half
remembers is somewhere in it, and paging a numbered list to find it is the worst way to look
something up.  Every other tool that lists installable things solves this the same way -- you type,
the list shrinks -- so this module is the one place that decides what "matches" and what "first"
mean, and the CLI, the text wizard, and the curses list all ask it rather than each inventing an
answer.

Three properties are load-bearing, and each is a test below:

* **Every word must match.**  ``review python`` finds what matches *both*, not what matches either.
  Adding a word narrows, which is what a person typing a second word is trying to do; a search
  where a second word widens the result is a search nobody can steer.
* **The order is a stated table, not a feeling.**  The six constants below are the whole
  ranking.  A name that *is* the word beats a name that starts with it, which beats a summary
  that mentions it.
  Ties keep catalog order, so two runs over one catalog print one order.
* **It matches text, not artifacts.**  Nothing here knows what a coordinate or a trust class is.
  Callers turn their own rows into ``Document``s, so the same matcher serves a marketplace item, a
  wizard row, and a collection, and none of them can drift from the others.

The whole thing is substring matching over folded text.  No index, no stemming, no fuzzy distance,
and above all no dependency: AART's runtime is the standard library and stays that way.  A person
looking for `code-review` types `review`, and substring matching is exactly what answers that.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

# What a match in each place is worth.  Summed over the words typed; the largest wins the row.
NAME_EXACT = 100
NAME_PREFIX = 50
NAME_SUBSTRING = 30
COORDINATE = 20
SUMMARY = 10
OTHER = 5


@dataclass(frozen=True, slots=True)
class Document:
    """One searchable row, as text.

    ``name`` is the bare artifact or collection name -- the part a person actually types.
    ``coordinate`` is its qualified form.  ``extra`` carries anything else worth finding on, each
    entry ``(label, text)``; the label is what the answer names when it says where the word was
    found, so it should read as a word ("authors", "members"), not as a field path.
    """

    name: str
    coordinate: str = ""
    summary: str = ""
    extra: tuple[tuple[str, str], ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class Hit:
    """One matching document: where it sits in the caller's own sequence, and why it matched."""

    index: int
    score: int
    matched: tuple[str, ...]


def terms(query: str) -> tuple[str, ...]:
    """The words to look for: folded, de-duplicated, in the order they were typed."""

    return tuple(dict.fromkeys(word for word in query.casefold().split() if word))


def _fold(text: str) -> str:
    return " ".join(text.split()).casefold()


def match(document: Document, term: str) -> tuple[int, tuple[str, ...]]:
    """What one word is worth against one document, and every place it was found.

    The score is the best single place, not the sum of them: a word that appears in both the name
    and the summary of one artifact says no more about that artifact than a word in its name.  The
    places are all reported, because that is what the answer shows a person to explain the order.
    """

    found: list[tuple[int, str]] = []
    name = _fold(document.name)
    if name == term:
        found.append((NAME_EXACT, "name"))
    elif name.startswith(term):
        found.append((NAME_PREFIX, "name"))
    elif term in name:
        found.append((NAME_SUBSTRING, "name"))
    if term in _fold(document.coordinate):
        found.append((COORDINATE, "coordinate"))
    if term in _fold(document.summary):
        found.append((SUMMARY, "summary"))
    for label, text in document.extra:
        if term in _fold(text):
            found.append((OTHER, label))
    if not found:
        return 0, ()
    best = max(score for score, _ in found)
    return best, tuple(dict.fromkeys(label for _, label in found))


def score(document: Document, wanted: Sequence[str]) -> tuple[int, tuple[str, ...]]:
    """The document's total against every word, or ``0`` when one of them is missing."""

    total = 0
    places: list[str] = []
    for term in wanted:
        value, labels = match(document, term)
        if value == 0:
            return 0, ()
        total += value
        places.extend(labels)
    return total, tuple(dict.fromkeys(places))


def search(
    documents: Sequence[Document], query: str, *, limit: int | None = None
) -> tuple[Hit, ...]:
    """The matching documents, best first, each pointing back at its place in ``documents``.

    An empty query matches everything, in catalog order, scoring nothing.  That is what "clear the
    filter" asks for, and having it here means no caller has to special-case the blank line.
    """

    if limit is not None and limit < 1:
        raise ValueError("a search limit is a count of rows, so it is at least 1")
    wanted = terms(query)
    if not wanted:
        hits = tuple(Hit(index, 0, ()) for index in range(len(documents)))
        return hits if limit is None else hits[:limit]

    found = []
    for index, document in enumerate(documents):
        total, places = score(document, wanted)
        if total:
            found.append(Hit(index, total, places))
    found.sort(key=lambda hit: (-hit.score, hit.index))
    ranked = tuple(found)
    return ranked if limit is None else ranked[:limit]


def summary_line(query: str, matches: int, total: int) -> str:
    """The one line that says what was searched and how much of the catalog answered.

    "Entries", not "artifacts": a collection is searched beside the artifacts and can be the thing
    found, and a count that calls it an artifact would be one off from what the list shows.
    """

    entries = f"{total} entr{'y' if total == 1 else 'ies'}"
    if not terms(query):
        return f"{entries}."
    quoted = " ".join(query.split())
    if matches == 0:
        return f"Nothing matches {quoted!r}. {entries} searched."
    return f"{matches} of {total} match {quoted!r}."


__all__ = [
    "COORDINATE",
    "Document",
    "Hit",
    "NAME_EXACT",
    "NAME_PREFIX",
    "NAME_SUBSTRING",
    "OTHER",
    "SUMMARY",
    "match",
    "score",
    "search",
    "summary_line",
    "terms",
]
