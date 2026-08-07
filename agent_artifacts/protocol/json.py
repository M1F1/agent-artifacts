"""Strict immutable JSON parsing and canonical UTF-8 serialization."""

from __future__ import annotations

import json as stdlib_json
from dataclasses import dataclass
from typing import Union

from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity, SourceLocation
from agent_artifacts.domain.result import Err, Ok, Result

from .codes import (
    JSON_DEPTH,
    JSON_DUPLICATE_KEY,
    JSON_FLOAT,
    JSON_INTEGER_RANGE,
    JSON_INVALID,
    JSON_STRING_LENGTH,
    JSON_UNICODE,
)

MIN_PROTOCOL_INTEGER = -(2**63)
MAX_PROTOCOL_INTEGER = 2**63 - 1


@dataclass(frozen=True, slots=True)
class JsonObject:
    entries: tuple[tuple[str, "JsonValue"], ...]

    def __post_init__(self) -> None:
        keys = tuple(key for key, _value in self.entries)
        if len(set(keys)) != len(keys):
            raise ValueError("JsonObject entries must have unique keys")
        object.__setattr__(self, "entries", tuple(sorted(self.entries, key=lambda item: item[0])))

    def get(self, key: str, default: JsonValue | None = None) -> JsonValue | None:
        for candidate, value in self.entries:
            if candidate == key:
                return value
        return default

    def keys(self) -> tuple[str, ...]:
        return tuple(key for key, _value in self.entries)


@dataclass(frozen=True, slots=True)
class JsonArray:
    items: tuple["JsonValue", ...]


JsonScalar = Union[None, bool, int, str]
JsonValue = Union[JsonScalar, JsonObject, JsonArray]


class _ParseProblem(ValueError):
    def __init__(self, code: DiagnosticCode, message: str):
        super().__init__(message)
        self.code = code


def _problem(code: DiagnosticCode, message: str, location: SourceLocation | None) -> Err:
    return Err((Diagnostic(code, Severity.ERROR, message, location),))


def _parse_integer(raw: str) -> int:
    digits = raw[1:] if raw.startswith("-") else raw
    if len(digits) > 19:
        raise _ParseProblem(JSON_INTEGER_RANGE, "JSON integer is outside signed 64-bit range")
    value = int(raw)
    if not MIN_PROTOCOL_INTEGER <= value <= MAX_PROTOCOL_INTEGER:
        raise _ParseProblem(JSON_INTEGER_RANGE, "JSON integer is outside signed 64-bit range")
    return value


def _reject_float(raw: str) -> float:
    raise _ParseProblem(JSON_FLOAT, f"floating-point JSON number is forbidden: {raw}")


def _reject_constant(raw: str) -> object:
    raise _ParseProblem(JSON_INVALID, f"non-standard JSON constant is forbidden: {raw}")


def _object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _ParseProblem(JSON_DUPLICATE_KEY, f"duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def _validated_text(value: str, max_string_length: int) -> str:
    if len(value) > max_string_length:
        raise _ParseProblem(
            JSON_STRING_LENGTH,
            f"JSON string exceeds {max_string_length} code points",
        )
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise _ParseProblem(JSON_UNICODE, "JSON contains an unpaired Unicode surrogate") from error
    return value


def _freeze(value: object, *, depth: int, max_depth: int, max_string_length: int) -> JsonValue:
    if depth > max_depth:
        raise _ParseProblem(JSON_DEPTH, f"JSON nesting exceeds maximum depth {max_depth}")
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        if not MIN_PROTOCOL_INTEGER <= value <= MAX_PROTOCOL_INTEGER:
            raise _ParseProblem(JSON_INTEGER_RANGE, "JSON integer is outside signed 64-bit range")
        return value
    if isinstance(value, str):
        return _validated_text(value, max_string_length)
    if isinstance(value, list):
        return JsonArray(
            tuple(
                _freeze(
                    item,
                    depth=depth + 1,
                    max_depth=max_depth,
                    max_string_length=max_string_length,
                )
                for item in value
            )
        )
    if isinstance(value, dict):
        entries: list[tuple[str, JsonValue]] = []
        for key, item in value.items():
            valid_key = _validated_text(key, max_string_length)
            entries.append(
                (
                    valid_key,
                    _freeze(
                        item,
                        depth=depth + 1,
                        max_depth=max_depth,
                        max_string_length=max_string_length,
                    ),
                )
            )
        return JsonObject(tuple(entries))
    raise _ParseProblem(JSON_INVALID, f"unsupported parsed JSON value: {type(value).__name__}")


def parse_json(
    data: bytes | str,
    *,
    location: SourceLocation | None = None,
    max_depth: int = 64,
    max_string_length: int = 1_000_000,
) -> Result[JsonValue]:
    """Parse one strict JSON value without allowing unsafe Python JSON extensions."""

    if max_depth < 0 or max_string_length < 0:
        raise ValueError("JSON bounds must be non-negative")
    try:
        text = data.decode("utf-8", errors="strict") if isinstance(data, bytes) else data
    except UnicodeDecodeError:
        return _problem(JSON_UNICODE, "JSON input is not valid UTF-8", location)

    try:
        parsed = stdlib_json.loads(
            text,
            object_pairs_hook=_object_pairs,
            parse_int=_parse_integer,
            parse_float=_reject_float,
            parse_constant=_reject_constant,
        )
        return Ok(
            _freeze(
                parsed,
                depth=0,
                max_depth=max_depth,
                max_string_length=max_string_length,
            )
        )
    except _ParseProblem as error:
        return _problem(error.code, str(error), location)
    except stdlib_json.JSONDecodeError as error:
        diagnostic_location = SourceLocation(
            source=None if location is None else location.source,
            path=None if location is None else location.path,
            pointer=None if location is None else location.pointer,
            line=error.lineno,
            column=error.colno,
        )
        return _problem(JSON_INVALID, f"invalid JSON: {error.msg}", diagnostic_location)
    except RecursionError:
        return _problem(JSON_DEPTH, f"JSON nesting exceeds maximum depth {max_depth}", location)


def _to_python(value: JsonValue) -> object:
    if isinstance(value, JsonObject):
        return {key: _to_python(item) for key, item in value.entries}
    if isinstance(value, JsonArray):
        return [_to_python(item) for item in value.items]
    return value


def canonical_json_bytes(value: JsonValue) -> bytes:
    text = stdlib_json.dumps(
        _to_python(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return (text + "\n").encode("utf-8")
