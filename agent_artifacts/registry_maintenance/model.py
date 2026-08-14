"""Frozen values for reviewed registry curation and native-reference refreshes."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from agent_artifacts.domain.identifiers import ObjectDigest
from agent_artifacts.domain.result import Result
from agent_artifacts.protocol.hashing import json_digest, sha256_bytes
from agent_artifacts.protocol.json import JsonArray, JsonObject
from agent_artifacts.protocol.native_tree import SnapshotOrigin, SourceSnapshot
from agent_artifacts.protocol.paths import SafeRelativePath

_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


def _valid_digest(value: object) -> bool:
    return (
        isinstance(value, ObjectDigest)
        and value.algorithm == "sha256"
        and _DIGEST_RE.fullmatch(value.value) is not None
    )


class RegistryChangeKind(str, Enum):
    ADDED = "added"
    CHANGED = "changed"
    UNCHANGED = "unchanged"


class NativeReferenceDisposition(str, Enum):
    UP_TO_DATE = "up-to-date"
    CHANGED = "changed"
    # A pinned reference cannot be unreachable at check time — `check_native_reference` has already
    # acquired the snapshot it compares.  A vendored copy can: re-vendoring is the one check whose
    # first step is reaching an upstream that may be gone, and that must not read as `up-to-date`.
    UNREACHABLE = "unreachable"


@dataclass(frozen=True, slots=True)
class NativeReferenceAcquisition:
    url: str
    requested_ref: str
    resolved_commit: str
    snapshot: SourceSnapshot

    def __post_init__(self) -> None:
        if (
            not isinstance(self.url, str)
            or not self.url
            or any(character in self.url for character in "\r\n")
            or not isinstance(self.requested_ref, str)
            or not self.requested_ref
            or any(character in self.requested_ref for character in "\r\n")
            or not isinstance(self.resolved_commit, str)
            or _COMMIT_RE.fullmatch(self.resolved_commit) is None
            or not isinstance(self.snapshot, SourceSnapshot)
            or self.snapshot.origin is not SnapshotOrigin.IMMUTABLE_GIT
        ):
            raise ValueError("native reference acquisition must be immutable pinned Git content")


# Resolving one `(url, ref)` against a real upstream, injected wherever a check needs the network.
# Declared beside the acquisition it produces so that a pure planner can accept one without
# importing the runtime that builds Git snapshots.
NativeAcquirer = Callable[[str, str], Result[NativeReferenceAcquisition]]


@dataclass(frozen=True, slots=True, order=True)
class RegistryFileChange:
    path: SafeRelativePath
    kind: RegistryChangeKind
    content: bytes
    before_digest: ObjectDigest | None
    after_digest: ObjectDigest

    def __post_init__(self) -> None:
        if (
            not isinstance(self.path, SafeRelativePath)
            or not isinstance(self.kind, RegistryChangeKind)
            or not isinstance(self.content, bytes)
            or not _valid_digest(self.after_digest)
            or sha256_bytes(self.content) != self.after_digest
            or (self.before_digest is not None and not _valid_digest(self.before_digest))
        ):
            raise ValueError("registry file change is invalid")
        if self.kind is RegistryChangeKind.ADDED and self.before_digest is not None:
            raise ValueError("added registry file cannot have a previous digest")
        if self.kind is RegistryChangeKind.CHANGED and (
            self.before_digest is None or self.before_digest == self.after_digest
        ):
            raise ValueError("changed registry file requires distinct exact digests")
        if self.kind is RegistryChangeKind.UNCHANGED and self.before_digest != self.after_digest:
            raise ValueError("unchanged registry file requires equal exact digests")


def _allowed_mutation_path(path: SafeRelativePath) -> bool:
    raw = str(path)
    if raw in {"aart.lock.json", "aart.index.json"}:
        return True
    parts = path.parts
    return (
        len(parts) == 3
        and parts[0] == "entries"
        and parts[1] in {"skill", "guideline", "mcp", "hook", "memory"}
        and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*\.json", parts[2]) is not None
    )


def registry_mutation_review_digest(
    expected_inputs_digest: ObjectDigest,
    next_inputs_digest: ObjectDigest,
    changes: tuple[RegistryFileChange, ...],
) -> ObjectDigest:
    """Bind review approval to the exact ordered mutation and workspace states."""

    ordered = tuple(sorted(changes, key=lambda item: str(item.path)))
    return json_digest(
        JsonObject(
            (
                (
                    "changes",
                    JsonArray(
                        tuple(
                            JsonObject(
                                (
                                    ("after_digest", str(item.after_digest)),
                                    (
                                        "before_digest",
                                        None
                                        if item.before_digest is None
                                        else str(item.before_digest),
                                    ),
                                    ("kind", item.kind.value),
                                    ("path", str(item.path)),
                                )
                            )
                            for item in ordered
                        )
                    ),
                ),
                ("expected_inputs_digest", str(expected_inputs_digest)),
                ("next_inputs_digest", str(next_inputs_digest)),
            )
        )
    )


@dataclass(frozen=True, slots=True)
class RegistryMutationPlan:
    expected_inputs_digest: ObjectDigest
    next_inputs_digest: ObjectDigest
    changes: tuple[RegistryFileChange, ...]
    review_digest: ObjectDigest

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.changes, key=lambda item: str(item.path)))
        paths = tuple(item.path for item in ordered)
        if (
            not _valid_digest(self.expected_inputs_digest)
            or not _valid_digest(self.next_inputs_digest)
            or not ordered
            or len(set(paths)) != len(paths)
            or any(not _allowed_mutation_path(item.path) for item in ordered)
            or not _valid_digest(self.review_digest)
            or self.review_digest
            != registry_mutation_review_digest(
                self.expected_inputs_digest,
                self.next_inputs_digest,
                ordered,
            )
        ):
            raise ValueError("registry mutation plan is invalid")
        object.__setattr__(self, "changes", ordered)

    @property
    def changed_paths(self) -> int:
        return sum(item.kind is not RegistryChangeKind.UNCHANGED for item in self.changes)


@dataclass(frozen=True, slots=True)
class NativeReferenceCheck:
    disposition: NativeReferenceDisposition
    plan: RegistryMutationPlan

    def __post_init__(self) -> None:
        if not isinstance(self.plan, RegistryMutationPlan):
            raise ValueError("native reference check requires a registry mutation plan")
        expected = (
            NativeReferenceDisposition.UP_TO_DATE
            if self.plan.changed_paths == 0
            else NativeReferenceDisposition.CHANGED
        )
        if (
            not isinstance(self.disposition, NativeReferenceDisposition)
            or self.disposition is not expected
        ):
            raise ValueError("native reference disposition does not match its exact diff")


@dataclass(frozen=True, slots=True)
class RegistryApplyCommand:
    plan: RegistryMutationPlan

    def __post_init__(self) -> None:
        if not isinstance(self.plan, RegistryMutationPlan):
            raise ValueError("registry apply command requires a reviewed plan")


@dataclass(frozen=True, slots=True)
class RegistryApplyReceipt:
    review_digest: ObjectDigest
    inputs_digest: ObjectDigest
    changed_paths: int

    def __post_init__(self) -> None:
        if (
            not _valid_digest(self.review_digest)
            or not _valid_digest(self.inputs_digest)
            or not isinstance(self.changed_paths, int)
            or isinstance(self.changed_paths, bool)
            or self.changed_paths < 0
        ):
            raise ValueError("registry apply receipt is invalid")
