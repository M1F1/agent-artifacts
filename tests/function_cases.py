"""Make module-level ``test_*`` functions visible to ``unittest discover``.

`AD-41`. Five test modules were written as bare functions rather than as `TestCase` methods.
`unittest`'s loader collects `TestCase` subclasses and nothing else, so those fifty tests were
imported by nobody and run by nothing: the file existed, the assertions were correct, and the
gate that reports "unit OK" never executed a line of them. A test that cannot fail is not a
test, and the surfaces they cover — the `--json` payload renderer, the receipt, verification —
are exactly the ones a release note points at.

The functions are left as they are. The loader is what was missing, so the loader is what this
adds: one generated `TestCase` per module, carrying each function as a method under its own
name, so a failure still reports which function failed.
"""

from __future__ import annotations

import inspect
import unittest
from typing import Any, Mapping, Type


def function_test_case(namespace: Mapping[str, Any], *, name: str) -> Type[unittest.TestCase]:
    """Return a `TestCase` whose methods are *namespace*'s zero-argument `test_*` functions."""

    methods: dict[str, Any] = {"__module__": str(namespace.get("__name__", name))}
    for key, value in namespace.items():
        if not key.startswith("test_") or not inspect.isfunction(value):
            continue
        if inspect.signature(value).parameters:
            # A function that wants arguments wants a fixture this loader does not have; it is
            # left uncollected rather than called with something invented.
            continue
        methods[key] = lambda self, function=value: function()
    return type(name, (unittest.TestCase,), methods)
