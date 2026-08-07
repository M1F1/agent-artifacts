"""Dependency-free SemVer 2.0 precedence and half-open compatibility bounds."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import total_ordering
from typing import Union

from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity, SourceLocation
from agent_artifacts.domain.result import Err, Ok, Result

from .codes import SEMVER_INVALID, VERSION_BOUNDS_INVALID

PrereleaseIdentifier = Union[int, str]
_NUMBER = r"(?:0|[1-9][0-9]*)"
_IDENTIFIER = r"[0-9A-Za-z-]+"
_SEMVER_RE = re.compile(
    rf"^(?P<major>{_NUMBER})\.(?P<minor>{_NUMBER})\.(?P<patch>{_NUMBER})"
    rf"(?:-(?P<prerelease>{_IDENTIFIER}(?:\.{_IDENTIFIER})*))?"
    rf"(?:\+(?P<build>{_IDENTIFIER}(?:\.{_IDENTIFIER})*))?$"
)
_MAX_SEMVER_NUMBER = 2**63 - 1


def _bounded_number(raw: str) -> int | None:
    if len(raw) > 19:
        return None
    value = int(raw)
    return value if value <= _MAX_SEMVER_NUMBER else None


@total_ordering
@dataclass(frozen=True, slots=True, eq=False)
class SemVer:
    major: int
    minor: int
    patch: int
    prerelease: tuple[PrereleaseIdentifier, ...] = ()
    build: tuple[str, ...] = ()

    def __str__(self) -> str:
        prerelease = "" if not self.prerelease else "-" + ".".join(map(str, self.prerelease))
        build = "" if not self.build else "+" + ".".join(self.build)
        return f"{self.major}.{self.minor}.{self.patch}{prerelease}{build}"

    def _core(self) -> tuple[int, int, int]:
        return (self.major, self.minor, self.patch)

    def same_precedence(self, other: SemVer) -> bool:
        return self._core() == other._core() and self.prerelease == other.prerelease

    def __eq__(self, other: object) -> bool:
        return isinstance(other, SemVer) and self.same_precedence(other)

    def __hash__(self) -> int:
        return hash((self._core(), self.prerelease))

    def __lt__(self, other: SemVer) -> bool:
        if not isinstance(other, SemVer):
            return NotImplemented
        if self._core() != other._core():
            return self._core() < other._core()
        return _prerelease_less(self.prerelease, other.prerelease)


def _prerelease_less(
    left: tuple[PrereleaseIdentifier, ...],
    right: tuple[PrereleaseIdentifier, ...],
) -> bool:
    if not left:
        return False
    if not right:
        return True
    common_length = min(len(left), len(right))
    for index in range(common_length):
        left_item = left[index]
        right_item = right[index]
        if left_item == right_item:
            continue
        if isinstance(left_item, int):
            return not isinstance(right_item, int) or left_item < right_item
        if isinstance(right_item, int):
            return False
        return left_item < right_item
    return len(left) < len(right)


@dataclass(frozen=True, slots=True)
class VersionBounds:
    min_inclusive: SemVer | None = None
    max_exclusive: SemVer | None = None

    def allows(self, version: SemVer) -> bool:
        if self.min_inclusive is not None and version < self.min_inclusive:
            return False
        return self.max_exclusive is None or version < self.max_exclusive


def _error(code: DiagnosticCode, message: str, location: SourceLocation | None) -> Err:
    return Err((Diagnostic(code, Severity.ERROR, message, location),))


def parse_semver(raw: str, *, location: SourceLocation | None = None) -> Result[SemVer]:
    match = _SEMVER_RE.fullmatch(raw)
    if match is None:
        return _error(SEMVER_INVALID, f"invalid SemVer: {raw!r}", location)
    major = _bounded_number(match.group("major"))
    minor = _bounded_number(match.group("minor"))
    patch = _bounded_number(match.group("patch"))
    if major is None or minor is None or patch is None:
        return _error(
            SEMVER_INVALID,
            "SemVer numeric identifier is outside signed 64-bit range",
            location,
        )
    prerelease: list[PrereleaseIdentifier] = []
    for identifier in (match.group("prerelease") or "").split("."):
        if not identifier:
            continue
        if identifier.isdigit():
            if len(identifier) > 1 and identifier.startswith("0"):
                return _error(
                    SEMVER_INVALID,
                    f"numeric prerelease identifier has a leading zero: {identifier!r}",
                    location,
                )
            numeric_identifier = _bounded_number(identifier)
            if numeric_identifier is None:
                return _error(
                    SEMVER_INVALID,
                    "SemVer numeric identifier is outside signed 64-bit range",
                    location,
                )
            prerelease.append(numeric_identifier)
        else:
            prerelease.append(identifier)
    build = tuple((match.group("build") or "").split(".")) if match.group("build") else ()
    return Ok(
        SemVer(
            major,
            minor,
            patch,
            tuple(prerelease),
            build,
        )
    )


def version_bounds(
    min_inclusive: SemVer | None,
    max_exclusive: SemVer | None,
    *,
    location: SourceLocation | None = None,
) -> Result[VersionBounds]:
    if (
        min_inclusive is not None
        and max_exclusive is not None
        and not min_inclusive < max_exclusive
    ):
        return _error(
            VERSION_BOUNDS_INVALID,
            f"minimum {min_inclusive} must precede maximum {max_exclusive}",
            location,
        )
    return Ok(VersionBounds(min_inclusive, max_exclusive))
