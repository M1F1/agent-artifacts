"""Small functional toolkit (WP-0): Result combinators + composition helpers.

Pure, stdlib-only. The rest of the codebase chains `Result` values through these instead
of raising for domain errors (DESIGN.md §14). Re-exports `Ok`/`Err` so callers can do
``from agent_artifacts.fp import Ok, Err, bind``.
"""

from __future__ import annotations

from functools import reduce
from typing import Callable, Iterable, Tuple

from .model import Err, Ok, Result

__all__ = [
    "Ok",
    "Err",
    "is_ok",
    "is_err",
    "map_ok",
    "map_err",
    "bind",
    "unwrap_or",
    "sequence",
    "partition",
    "collect",
    "compose",
    "pipe",
]


def is_ok(r: Result) -> bool:
    return isinstance(r, Ok)


def is_err(r: Result) -> bool:
    return isinstance(r, Err)


def map_ok(r: Result, f: Callable) -> Result:
    """Apply `f` to the value inside an `Ok`; pass `Err` through unchanged."""
    return Ok(f(r.value)) if isinstance(r, Ok) else r


def map_err(r: Result, f: Callable[[str], str]) -> Result:
    """Transform an `Err`'s reason; pass `Ok` through unchanged."""
    return Err(f(r.reason), r.code) if isinstance(r, Err) else r


def bind(r: Result, f: Callable[..., Result]) -> Result:
    """Monadic bind: run `f` on the `Ok` value (it returns a `Result`); short-circuit `Err`."""
    return f(r.value) if isinstance(r, Ok) else r


def unwrap_or(r: Result, default):
    return r.value if isinstance(r, Ok) else default


def sequence(results: Iterable[Result]) -> Result:
    """``Iterable[Result[T]] -> Result[tuple[T, ...]]``, short-circuiting on the first `Err`."""
    out = []
    for r in results:
        if isinstance(r, Err):
            return r
        out.append(r.value)
    return Ok(tuple(out))


def partition(results: Iterable[Result]) -> Tuple[tuple, tuple]:
    """Split into ``(ok_values, err_results)`` — neither short-circuits."""
    materialised = tuple(results)
    oks = tuple(r.value for r in materialised if isinstance(r, Ok))
    errs = tuple(r for r in materialised if isinstance(r, Err))
    return oks, errs


def collect(results: Iterable[Result]) -> Result:
    """Like `sequence`, but **accumulates** every error (used for validation, PLAN.md §5/WP-5)."""
    oks, errs = partition(results)
    if errs:
        # Preserve the error code when all accumulated errors agree, so a lone CONFLICT (4)
        # surfaces as 4 rather than the generic 1; fall back to 1 only when codes are mixed.
        codes = {e.code for e in errs}
        code = codes.pop() if len(codes) == 1 else 1
        return Err("; ".join(e.reason for e in errs), code=code)
    return Ok(oks)


def compose(*fns: Callable) -> Callable:
    """Left-to-right composition: ``compose(f, g)(x) == g(f(x))``."""
    return reduce(lambda f, g: lambda x: g(f(x)), fns, lambda x: x)


def pipe(value, *fns: Callable):
    """Thread `value` through `fns` left-to-right."""
    return reduce(lambda acc, f: f(acc), fns, value)
