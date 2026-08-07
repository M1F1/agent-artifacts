"""Nominal identity values shared by AART bounded contexts.

Validation and parsing rules are introduced by the protocol context. These frozen values keep
source aliases, declared IDs, origins, artifact identities, and object digests distinct meanwhile.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ArtifactKind = Literal["skill", "guideline", "mcp", "hook", "memory", "collection"]


@dataclass(frozen=True, slots=True, order=True)
class SourceAlias:
    value: str

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True, order=True)
class SourceId:
    value: str

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True, order=True)
class SourceOrigin:
    value: str

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True, order=True)
class ArtifactIdentity:
    kind: ArtifactKind
    name: str

    def __str__(self) -> str:
        return f"{self.kind}/{self.name}"


@dataclass(frozen=True, slots=True)
class ArtifactCoordinate:
    source: SourceAlias
    artifact: ArtifactIdentity
    version: str | None = None

    def __str__(self) -> str:
        version = "" if self.version is None else f"@{self.version}"
        return f"{self.source}/{self.artifact}{version}"


@dataclass(frozen=True, slots=True, order=True)
class ObjectDigest:
    algorithm: str
    value: str

    def __str__(self) -> str:
        return f"{self.algorithm}:{self.value}"
