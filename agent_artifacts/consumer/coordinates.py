"""Pure parsing of agent-supplied artifact and collection selectors.

An agent addresses marketplace entries by text. This module converts that text into an explicit selector
without contacting a source, reading configuration, or guessing a missing source alias.  A selector
that omits its source stays unbound here; :func:`agent_artifacts.marketplace.catalog.resolve_artifact`
is the single place allowed to bind it, so ambiguity is reported against the real catalog rather
than assumed away at parse time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import get_args

from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import ArtifactIdentity, ArtifactKind, SourceAlias
from agent_artifacts.domain.result import Err, Ok, Result

CONSUMER_INVALID = DiagnosticCode("consumer-invalid")

_SELECTABLE_KINDS: frozenset[str] = frozenset(get_args(ArtifactKind))
_GRAMMAR = "<source>/<kind>/<name>[@<version>]"


@dataclass(frozen=True, slots=True)
class ArtifactSelector:
    """One requested artifact, with its source deliberately optional."""

    identity: ArtifactIdentity
    source: SourceAlias | None = None
    version: str | None = None

    def __str__(self) -> str:
        source = "" if self.source is None else f"{self.source}/"
        version = "" if self.version is None else f"@{self.version}"
        return f"{source}{self.identity}{version}"


def _invalid(raw: str, detail: str, *remediation: str) -> Err:
    return Err(
        (
            Diagnostic(
                CONSUMER_INVALID,
                Severity.ERROR,
                f"artifact selector {raw!r} is invalid: {detail}",
                remediation=remediation or (f"use {_GRAMMAR}",),
            ),
        )
    )


def _split_version(raw: str) -> Result[tuple[str, str | None]]:
    if "@" not in raw:
        return Ok((raw, None))
    body, _, version = raw.rpartition("@")
    if not body or not version:
        return _invalid(raw, "an '@' version suffix needs both a coordinate and a version")
    return Ok((body, version))


def parse_artifact_selector(raw: str) -> Result[ArtifactSelector]:
    """Parse one selector, refusing to infer a missing kind, name, source, or version."""

    candidate = raw.strip()
    if not candidate:
        return _invalid(raw, "a selector cannot be empty")
    split = _split_version(candidate)
    if isinstance(split, Err):
        return split
    body, version = split.value
    segments = body.split("/")
    if any(not segment for segment in segments):
        return _invalid(raw, f"every segment must be non-empty in {_GRAMMAR}")
    if len(segments) == 2:
        source_value, kind, name = None, segments[0], segments[1]
    elif len(segments) == 3:
        source_value, kind, name = segments[0], segments[1], segments[2]
    else:
        return _invalid(
            raw,
            f"expected {_GRAMMAR} or <kind>/<name>, not {len(segments)} path segments",
        )
    if kind not in _SELECTABLE_KINDS:
        return _invalid(
            raw,
            f"unknown artifact kind {kind!r}",
            "use one of: " + ", ".join(sorted(_SELECTABLE_KINDS)),
        )
    if kind == "collection" and version is not None:
        return _invalid(raw, "collections are not versioned; remove the '@<version>' suffix")
    return Ok(
        ArtifactSelector(
            ArtifactIdentity(kind, name),  # type: ignore[arg-type]
            source=None if source_value is None else SourceAlias(source_value),
            version=version,
        )
    )


def parse_artifact_selectors(raw: tuple[str, ...]) -> Result[tuple[ArtifactSelector, ...]]:
    """Parse every selector, reporting all invalid entries in one deterministic result."""

    selectors: list[ArtifactSelector] = []
    diagnostics: list[Diagnostic] = []
    for entry in raw:
        parsed = parse_artifact_selector(entry)
        if isinstance(parsed, Err):
            diagnostics.extend(parsed.diagnostics)
            continue
        selectors.append(parsed.value)
    if diagnostics:
        return Err(tuple(diagnostics))
    # Order by rendered text: an optional source makes field ordering partial (``None`` is not
    # comparable to a ``SourceAlias``), while the rendered selector is always totally ordered.
    return Ok(tuple(sorted(set(selectors), key=str)))


__all__ = [
    "CONSUMER_INVALID",
    "ArtifactSelector",
    "parse_artifact_selector",
    "parse_artifact_selectors",
]
