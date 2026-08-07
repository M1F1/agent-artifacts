"""Small schema-validation primitives that accumulate typed diagnostics."""

from __future__ import annotations

import re
from typing import TypeVar

from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity, SourceLocation
from agent_artifacts.domain.result import Err, Ok, Result

from .codes import (
    SCHEMA_EXTENSION_KEY,
    SCHEMA_MISSING_FIELD,
    SCHEMA_TYPE,
    SCHEMA_UNKNOWN_FIELD,
)
from .json import JsonArray, JsonObject, JsonValue

_EXTENSION_RE = re.compile(r"^[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*)+$")
T = TypeVar("T")


def _diagnostic(
    code: DiagnosticCode,
    message: str,
    location: SourceLocation | None,
    *,
    field: str | None = None,
) -> Diagnostic:
    details = () if field is None else (("field", field),)
    return Diagnostic(code, Severity.ERROR, message, location, details=details)


def is_namespaced_extension(key: str) -> bool:
    return _EXTENSION_RE.fullmatch(key) is not None


def validate_object_fields(
    value: JsonObject,
    *,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
    allow_extensions: bool = False,
    location: SourceLocation | None = None,
) -> Result[JsonObject]:
    if required & optional:
        raise ValueError("required and optional fields must not overlap")
    present = frozenset(value.keys())
    diagnostics: list[Diagnostic] = []
    for field in sorted(required - present):
        diagnostics.append(
            _diagnostic(
                SCHEMA_MISSING_FIELD,
                f"missing required field {field!r}",
                location,
                field=field,
            )
        )
    allowed = required | optional
    for field in sorted(present - allowed):
        if allow_extensions and is_namespaced_extension(field):
            continue
        looks_like_extension = "." in field or any(
            not (character.isascii() and (character.isalnum() or character in "_-"))
            for character in field
        )
        code = (
            SCHEMA_EXTENSION_KEY
            if allow_extensions and looks_like_extension
            else SCHEMA_UNKNOWN_FIELD
        )
        message = (
            f"invalid namespaced extension field {field!r}"
            if code == SCHEMA_EXTENSION_KEY
            else f"unknown field {field!r}"
        )
        diagnostics.append(_diagnostic(code, message, location, field=field))
    return Err(tuple(diagnostics)) if diagnostics else Ok(value)


def _expect(
    value: JsonValue,
    expected: type[T],
    label: str,
    location: SourceLocation | None,
) -> Result[T]:
    if isinstance(value, expected):
        return Ok(value)
    return Err(
        (
            _diagnostic(
                SCHEMA_TYPE,
                f"expected {label}, got {type(value).__name__}",
                location,
            ),
        )
    )


def expect_object(
    value: JsonValue, *, location: SourceLocation | None = None
) -> Result[JsonObject]:
    return _expect(value, JsonObject, "object", location)


def expect_array(value: JsonValue, *, location: SourceLocation | None = None) -> Result[JsonArray]:
    return _expect(value, JsonArray, "array", location)


def expect_string(value: JsonValue, *, location: SourceLocation | None = None) -> Result[str]:
    return _expect(value, str, "string", location)


def expect_integer(value: JsonValue, *, location: SourceLocation | None = None) -> Result[int]:
    if isinstance(value, int) and not isinstance(value, bool):
        return Ok(value)
    return Err(
        (_diagnostic(SCHEMA_TYPE, f"expected integer, got {type(value).__name__}", location),)
    )
