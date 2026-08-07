"""A typed Result algebra whose expected failures carry structured diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Generic, Iterable, TypeVar, Union

from .diagnostics import Diagnostic, sort_diagnostics

T_co = TypeVar("T_co", covariant=True)
T = TypeVar("T")
U = TypeVar("U")


@dataclass(frozen=True, slots=True)
class Ok(Generic[T_co]):
    value: T_co


@dataclass(frozen=True, slots=True)
class Err:
    diagnostics: tuple[Diagnostic, ...]

    def __post_init__(self) -> None:
        if not self.diagnostics:
            raise ValueError("Err requires at least one diagnostic")
        object.__setattr__(self, "diagnostics", sort_diagnostics(self.diagnostics))


Result = Union[Ok[T_co], Err]


def is_ok(result: Result[object]) -> bool:
    return isinstance(result, Ok)


def is_err(result: Result[object]) -> bool:
    return isinstance(result, Err)


def map_ok(result: Result[T], function: Callable[[T], U]) -> Result[U]:
    return Ok(function(result.value)) if isinstance(result, Ok) else result


def bind(result: Result[T], function: Callable[[T], Result[U]]) -> Result[U]:
    return function(result.value) if isinstance(result, Ok) else result


def map_err(result: Result[T], function: Callable[[Diagnostic], Diagnostic]) -> Result[T]:
    if isinstance(result, Ok):
        return result
    return Err(tuple(function(diagnostic) for diagnostic in result.diagnostics))


def collect(results: Iterable[Result[T]]) -> Result[tuple[T, ...]]:
    values: list[T] = []
    diagnostics: list[Diagnostic] = []
    for result in results:
        if isinstance(result, Ok):
            values.append(result.value)
        else:
            diagnostics.extend(result.diagnostics)
    return Err(tuple(diagnostics)) if diagnostics else Ok(tuple(values))


def err(*diagnostics: Diagnostic) -> Err:
    return Err(diagnostics)
