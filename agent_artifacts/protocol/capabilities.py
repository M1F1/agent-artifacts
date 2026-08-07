"""Strict capability names and deterministic required/optional negotiation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from agent_artifacts.domain.diagnostics import Diagnostic, Severity, SourceLocation
from agent_artifacts.domain.result import Err, Ok, Result

from .codes import CAPABILITY_INVALID

_CAPABILITY_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")


@dataclass(frozen=True, slots=True, order=True)
class Capability:
    value: str

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class CapabilityDecision:
    required: tuple[Capability, ...]
    optional: tuple[Capability, ...]
    available: tuple[Capability, ...]
    enabled: tuple[Capability, ...]
    missing_required: tuple[Capability, ...]
    unsupported_optional: tuple[Capability, ...]

    @property
    def compatible(self) -> bool:
        return not self.missing_required


def parse_capability(
    raw: str,
    *,
    location: SourceLocation | None = None,
) -> Result[Capability]:
    if _CAPABILITY_RE.fullmatch(raw) is None:
        return Err(
            (
                Diagnostic(
                    CAPABILITY_INVALID,
                    Severity.ERROR,
                    f"invalid capability name: {raw!r}",
                    location,
                ),
            )
        )
    return Ok(Capability(raw))


def _normalized(values: Iterable[Capability]) -> tuple[Capability, ...]:
    return tuple(sorted(set(values)))


def negotiate_capabilities(
    required: Iterable[Capability],
    optional: Iterable[Capability],
    available: Iterable[Capability],
) -> CapabilityDecision:
    normalized_required = _normalized(required)
    required_set = frozenset(normalized_required)
    normalized_optional = tuple(
        capability for capability in _normalized(optional) if capability not in required_set
    )
    normalized_available = _normalized(available)
    available_set = frozenset(normalized_available)
    enabled = _normalized(
        capability
        for capability in (*normalized_required, *normalized_optional)
        if capability in available_set
    )
    return CapabilityDecision(
        required=normalized_required,
        optional=normalized_optional,
        available=normalized_available,
        enabled=enabled,
        missing_required=tuple(
            capability for capability in normalized_required if capability not in available_set
        ),
        unsupported_optional=tuple(
            capability for capability in normalized_optional if capability not in available_set
        ),
    )
