"""Static analyzer suite declarations; discovery never installs optional tools."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .tool_adapters import BUILTIN_TOOL_ADAPTERS

_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
_KNOWN_OPTIONAL_PROVIDERS = frozenset(item.provider_id for item in BUILTIN_TOOL_ADAPTERS)


@dataclass(frozen=True, slots=True)
class AnalyzerSuite:
    id: str
    summary: str
    required_provider_ids: tuple[str, ...]
    optional_provider_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        required = tuple(sorted(set(self.required_provider_ids)))
        optional = tuple(sorted(set(self.optional_provider_ids)))
        if (
            _ID_RE.fullmatch(self.id) is None
            or not self.summary
            or self.summary != self.summary.strip()
            or "\n" in self.summary
            or "\r" in self.summary
            or len(self.summary) > 256
            or required != self.required_provider_ids
            or optional != self.optional_provider_ids
            or set(required) & set(optional)
            or required != ("aart-baseline",)
            or not set(optional) <= _KNOWN_OPTIONAL_PROVIDERS
        ):
            raise ValueError("analyzer suite is invalid")


BUILTIN_ANALYZER_SUITES = tuple(
    sorted(
        (
            AnalyzerSuite(
                "baseline",
                "Run AART's zero-dependency structural installation-risk assessment.",
                ("aart-baseline",),
                (),
            ),
            AnalyzerSuite(
                "recommended",
                "Add locally installed static, secret, and shell analyzers without network access.",
                ("aart-baseline",),
                ("bandit", "detect-secrets", "ruff", "shellcheck"),
            ),
            AnalyzerSuite(
                "extended",
                "Add every discovered analyzer, including the network-using dependency advisory provider.",
                ("aart-baseline",),
                ("bandit", "detect-secrets", "pip-audit", "ruff", "shellcheck"),
            ),
        ),
        key=lambda item: item.id,
    )
)


__all__ = ["AnalyzerSuite", "BUILTIN_ANALYZER_SUITES"]
