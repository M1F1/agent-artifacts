"""Host-independent safe relative path values for protocol documents and tree hashing."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from agent_artifacts.domain.diagnostics import Diagnostic, Severity, SourceLocation
from agent_artifacts.domain.result import Err, Ok, Result

from .codes import PATH_INVALID

_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:($|/)")


@dataclass(frozen=True, slots=True, order=True)
class SafeRelativePath:
    parts: tuple[str, ...]

    def __str__(self) -> str:
        return "/".join(self.parts)


def _invalid(raw: str, reason: str, location: SourceLocation | None) -> Err:
    return Err(
        (
            Diagnostic(
                PATH_INVALID,
                Severity.ERROR,
                f"invalid relative path {raw!r}: {reason}",
                location,
            ),
        )
    )


def parse_relative_path(
    raw: str,
    *,
    location: SourceLocation | None = None,
) -> Result[SafeRelativePath]:
    if not raw:
        return _invalid(raw, "path is empty", location)
    try:
        raw.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return _invalid(raw, "path contains an unpaired Unicode surrogate", location)
    if unicodedata.normalize("NFC", raw) != raw:
        return _invalid(raw, "path must use NFC Unicode normalization", location)
    if raw.startswith("/") or _WINDOWS_DRIVE_RE.match(raw):
        return _invalid(raw, "absolute paths are forbidden", location)
    if "\\" in raw:
        return _invalid(raw, "backslash is not a protocol separator", location)
    if any(ord(character) < 32 or ord(character) == 127 for character in raw):
        return _invalid(raw, "control characters are forbidden", location)
    parts = tuple(raw.split("/"))
    if any(part == "" for part in parts):
        return _invalid(raw, "empty path segments are forbidden", location)
    if any(part in {".", ".."} for part in parts):
        return _invalid(raw, "dot and parent segments are forbidden", location)
    return Ok(SafeRelativePath(parts))
