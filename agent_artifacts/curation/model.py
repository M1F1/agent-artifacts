"""IO-free values and render projections for canonical Maintainer curation."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from enum import Enum
from typing import Literal

from agent_artifacts.domain.identifiers import ObjectDigest
from agent_artifacts.protocol.hashing import json_digest
from agent_artifacts.protocol.json import JsonArray, JsonObject
from agent_artifacts.runtime_contract import EXECUTABLE_VERSION

_SLUG_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_KINDS = frozenset({"skill", "guideline", "mcp", "hook", "memory"})
_SCOPES = frozenset({"project", "user"})
_MODES = frozenset({"copy", "symlink"})
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


# A registry initialised today is written in the current dialect, so its floor is the AART
# that wrote it and its ceiling is the next major.  Literals here go stale on every release
# and, once the floor reaches the old literal ceiling, make the pair unsatisfiable.
_DEFAULT_MINIMUM_AART = str(EXECUTABLE_VERSION)
_DEFAULT_MAXIMUM_AART = f"{EXECUTABLE_VERSION.major + 1}.0.0"


class CurationAction(str, Enum):
    INIT = "init"
    SCAFFOLD = "scaffold"
    FORMAT = "format"
    PROMOTE_NATIVE = "promote-native"
    REFRESH_NATIVE = "refresh-native"
    VENDOR = "vendor"
    REVENDOR = "revendor"
    LOCK = "lock"
    BUILD = "build"
    VALIDATE = "validate"
    AUDIT = "audit"
    DIFF = "diff"


CurationChangeStatus = Literal["added", "changed", "removed", "unchanged"]
CurationOutcomeStatus = Literal["succeeded", "no-op", "failed"]


def _one_line(value: str) -> bool:
    return bool(value) and value == value.strip() and "\n" not in value and "\r" not in value


def _valid_digest(value: object) -> bool:
    return (
        isinstance(value, ObjectDigest)
        and value.algorithm == "sha256"
        and _DIGEST_RE.fullmatch(value.value) is not None
    )


@dataclass(frozen=True, slots=True)
class CurationRequest:
    action: CurationAction
    workspace: str
    kind: str | None = None
    name: str | None = None
    summary: str | None = None
    # `None` means the maintainer did not state one.  Re-vendoring needs that distinction: upstream
    # movement without a stated version is reported, never applied (design §4), and a default would
    # silently answer the one question the command exists to ask.
    artifact_version: str | None = "1.0.0"
    # The licence the registry records for a vendored copy.  `None` means the maintainer did not
    # state one, which is not the same as none existing: the taken subtree may settle it.
    artifact_license: str | None = None
    profiles: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ()
    scopes: tuple[str, ...] = ("project",)
    modes: tuple[str, ...] = ("copy",)
    url: str | None = None
    ref: str = "main"
    path: str | None = None
    # A package-relative recipe path, declared only when the maintainer has authored a setup
    # recipe beside the vendored payload.  It names content, so it is validated as a path fragment
    # rather than trusted from the flag.
    setup_recipe: str | None = None
    review_policy: str = "manual-review-v1"
    source_id: str | None = None
    display_name: str | None = None
    minimum_version: str = _DEFAULT_MINIMUM_AART
    maximum_version: str = _DEFAULT_MAXIMUM_AART

    def __post_init__(self) -> None:
        if (
            not isinstance(self.action, CurationAction)
            or not os.path.isabs(self.workspace)
            or os.path.normpath(self.workspace) != self.workspace
            or (self.kind is not None and self.kind not in _KINDS)
            or (self.name is not None and _SLUG_RE.fullmatch(self.name) is None)
            or (self.summary is not None and not _one_line(self.summary))
            or any(_SLUG_RE.fullmatch(value) is None for value in self.profiles + self.platforms)
            or not set(self.scopes) <= _SCOPES
            or not set(self.modes) <= _MODES
            or any(
                value is not None and (not value or "\n" in value or "\r" in value)
                for value in (
                    self.url,
                    self.path,
                    self.artifact_license,
                    self.setup_recipe,
                    self.source_id,
                    self.display_name,
                )
            )
            or not _one_line(self.ref)
            or not _one_line(self.review_policy)
        ):
            raise ValueError("curation request is invalid")
        object.__setattr__(self, "profiles", tuple(sorted(set(self.profiles))))
        object.__setattr__(self, "platforms", tuple(sorted(set(self.platforms))))
        object.__setattr__(self, "scopes", tuple(sorted(set(self.scopes))))
        object.__setattr__(self, "modes", tuple(sorted(set(self.modes))))


@dataclass(frozen=True, slots=True, order=True)
class CurationChange:
    path: str
    status: CurationChangeStatus

    def __post_init__(self) -> None:
        if (
            not _one_line(self.path)
            or self.path.startswith("/")
            or "\\" in self.path
            or any(part in {"", ".", ".."} for part in self.path.split("/"))
            or self.status not in {"added", "changed", "removed", "unchanged"}
        ):
            raise ValueError("curation change is invalid")


@dataclass(frozen=True, slots=True)
class CurationCheck:
    name: str
    passed: bool
    details: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            _SLUG_RE.fullmatch(self.name) is None
            or not isinstance(self.passed, bool)
            or any(not _one_line(item) for item in self.details)
        ):
            raise ValueError("curation check is invalid")


def curation_review_digest(
    action: CurationAction,
    snapshot_digest: ObjectDigest,
    changes: tuple[CurationChange, ...],
    checks: tuple[CurationCheck, ...],
    warnings: tuple[str, ...],
) -> ObjectDigest:
    return json_digest(
        JsonObject(
            (
                ("action", action.value),
                (
                    "changes",
                    JsonArray(
                        tuple(
                            JsonObject((("path", item.path), ("status", item.status)))
                            for item in changes
                        )
                    ),
                ),
                (
                    "checks",
                    JsonArray(
                        tuple(
                            JsonObject(
                                (
                                    ("details", JsonArray(item.details)),
                                    ("name", item.name),
                                    ("passed", item.passed),
                                )
                            )
                            for item in checks
                        )
                    ),
                ),
                ("snapshot_digest", str(snapshot_digest)),
                ("warnings", JsonArray(warnings)),
            )
        )
    )


@dataclass(frozen=True, slots=True)
class CurationReview:
    action: CurationAction
    workspace: str
    mutating: bool
    review_digest: ObjectDigest
    snapshot_digest: ObjectDigest
    changes: tuple[CurationChange, ...] = ()
    checks: tuple[CurationCheck, ...] = ()
    warnings: tuple[str, ...] = ()
    follow_up_commands: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.action, CurationAction)
            or not os.path.isabs(self.workspace)
            or os.path.normpath(self.workspace) != self.workspace
            or not isinstance(self.mutating, bool)
            or not _valid_digest(self.review_digest)
            or not _valid_digest(self.snapshot_digest)
            or any(not isinstance(item, CurationChange) for item in self.changes)
            or any(not isinstance(item, CurationCheck) for item in self.checks)
            or any(not _one_line(item) for item in self.warnings + self.follow_up_commands)
        ):
            raise ValueError("curation review is invalid")
        object.__setattr__(self, "changes", tuple(sorted(self.changes)))
        object.__setattr__(self, "checks", tuple(sorted(self.checks, key=lambda item: item.name)))


@dataclass(frozen=True, slots=True)
class CurationOutcome:
    action: CurationAction
    status: CurationOutcomeStatus
    changed_paths: int
    observed_paths: int = 0
    checks: tuple[CurationCheck, ...] = ()
    warnings: tuple[str, ...] = ()
    follow_up_commands: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.action, CurationAction)
            or self.status not in {"succeeded", "no-op", "failed"}
            or not isinstance(self.changed_paths, int)
            or isinstance(self.changed_paths, bool)
            or self.changed_paths < 0
            or not isinstance(self.observed_paths, int)
            or isinstance(self.observed_paths, bool)
            or self.observed_paths < 0
            or (self.status == "no-op" and self.changed_paths != 0)
            or (self.status == "failed" and self.changed_paths != 0)
            or any(not isinstance(item, CurationCheck) for item in self.checks)
            or any(not _one_line(item) for item in self.warnings + self.follow_up_commands)
        ):
            raise ValueError("curation outcome is invalid")


def render_curation_review(review: CurationReview) -> tuple[str, ...]:
    lines = [
        f"Review canonical Maintainer action: {review.action.value}",
        f"  Workspace: {review.workspace}",
        f"  Review digest: {review.review_digest}",
        f"  Mutation: {'yes, only on Finalize' if review.mutating else 'no (read-only)'}",
    ]
    for change in review.changes:
        lines.append(f"  - {change.status}: {change.path}")
    for check in review.checks:
        lines.append(f"  - check {check.name}: {'passed' if check.passed else 'failed'}")
        lines.extend(f"      {detail}" for detail in check.details)
    lines.extend(f"  warning: {warning}" for warning in review.warnings)
    if review.mutating:
        lines.append("  AART will not commit or push; review the working-tree diff afterward.")
    return tuple(lines)


def render_curation_outcome(outcome: CurationOutcome) -> tuple[str, ...]:
    if outcome.status == "failed":
        headline = f"{outcome.action.value}: failed; no managed paths were changed."
    elif outcome.status == "no-op":
        headline = f"{outcome.action.value}: no changes were required."
    elif outcome.changed_paths == 0:
        headline = f"{outcome.action.value}: completed read-only; no managed paths were changed."
    else:
        suffix = "path" if outcome.changed_paths == 1 else "paths"
        headline = f"{outcome.action.value}: Changed {outcome.changed_paths} managed {suffix}."
    lines = [headline]
    if outcome.observed_paths:
        suffix = "path" if outcome.observed_paths == 1 else "paths"
        lines.append(f"  observed: {outcome.observed_paths} review {suffix}")
    for check in outcome.checks:
        lines.append(f"  check {check.name}: {'passed' if check.passed else 'failed'}")
        lines.extend(f"    {detail}" for detail in check.details)
    lines.extend(f"  warning: {warning}" for warning in outcome.warnings)
    lines.extend(f"  next: {command}" for command in outcome.follow_up_commands)
    return tuple(lines)
