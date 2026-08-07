"""Pure immutable collection transformations with explicit stable ordering."""

from __future__ import annotations

from typing import Callable, Iterable, TypeVar

T = TypeVar("T")


def sorted_values(values: Iterable[T], *, key: Callable[[T], str]) -> tuple[T, ...]:
    return tuple(sorted(values, key=key))


def upsert_sorted(values: Iterable[T], replacement: T, *, key: Callable[[T], str]) -> tuple[T, ...]:
    replacement_key = key(replacement)
    retained = (value for value in values if key(value) != replacement_key)
    return sorted_values((*retained, replacement), key=key)


def remove_sorted(values: Iterable[T], target: str, *, key: Callable[[T], str]) -> tuple[T, ...]:
    return sorted_values((value for value in values if key(value) != target), key=key)
