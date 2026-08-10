"""Pure managed-path values for the local security assessment cache."""

from __future__ import annotations

import posixpath
from dataclasses import dataclass

from agent_artifacts.domain.identifiers import ObjectDigest

from .attestations import AssessmentCacheKey, cache_key_digest


@dataclass(frozen=True, slots=True)
class SecurityCachePaths:
    root: str
    attestations: str
    temporary: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.root, str)
            or not posixpath.isabs(self.root)
            or posixpath.normpath(self.root) != self.root
            or self.root == "/"
            or self.attestations != posixpath.join(self.root, "attestations", "sha256")
            or self.temporary != posixpath.join(self.root, "tmp")
        ):
            raise ValueError("security cache paths are invalid")


def security_cache_paths(root: str) -> SecurityCachePaths:
    return SecurityCachePaths(
        root,
        posixpath.join(root, "attestations", "sha256"),
        posixpath.join(root, "tmp"),
    )


def cached_attestation_path(paths: SecurityCachePaths, key: AssessmentCacheKey) -> str:
    digest = cache_key_digest(key).value
    return posixpath.join(paths.attestations, digest[:2], f"{digest[2:]}.json")


@dataclass(frozen=True, slots=True)
class CacheWriteReceipt:
    path: str
    cache_key_digest: ObjectDigest
    attestation_digest: ObjectDigest
    created: bool

    def __post_init__(self) -> None:
        if (
            not isinstance(self.path, str)
            or not posixpath.isabs(self.path)
            or posixpath.normpath(self.path) != self.path
            or not isinstance(self.created, bool)
        ):
            raise ValueError("security cache write receipt is invalid")


__all__ = [
    "CacheWriteReceipt",
    "SecurityCachePaths",
    "cached_attestation_path",
    "security_cache_paths",
]
