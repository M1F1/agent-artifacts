"""Frozen command plans, reports, and options for registry maintenance."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from agent_artifacts.domain.diagnostics import Diagnostic, Severity, sort_diagnostics
from agent_artifacts.domain.identifiers import ArtifactIdentity, ObjectDigest
from agent_artifacts.protocol.hashing import json_digest, sha256_bytes
from agent_artifacts.protocol.json import JsonArray, JsonObject
from agent_artifacts.protocol.paths import SafeRelativePath
from agent_artifacts.protocol.semver import SemVer
from agent_artifacts.registry_maintenance.model import NativeReferenceDisposition
from agent_artifacts.registry_maintenance.vendoring import DeliveryFinding, LicenseFinding
from agent_artifacts.security.model import SecurityAssessment

_SLUG_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_KINDS = frozenset({"skill", "guideline", "mcp", "hook", "memory"})
_SCOPES = frozenset({"project", "user"})
_MODES = frozenset({"copy", "symlink"})


def _valid_digest(value: object) -> bool:
    return (
        isinstance(value, ObjectDigest)
        and value.algorithm == "sha256"
        and _DIGEST_RE.fullmatch(value.value) is not None
    )


def _one_safe_line(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and all(character.isprintable() for character in value)
    )


class RegistryOperation(str, Enum):
    INIT = "init"
    SCAFFOLD = "scaffold"
    COLLECTION = "collection"
    FORMAT = "format"
    LOCK = "lock"
    BUILD = "build"
    MIGRATE = "migrate"
    # Vendoring writes payload bytes under `artifacts/`, which the registry-input mutation plan
    # cannot carry — its allowed paths are the lock, the index, and `entries/`.  So a vendor is a
    # workspace operation like `scaffold`, not a mutation like `promote-native`, even though the two
    # commands read as siblings.
    VENDOR = "vendor"
    VENDOR_BATCH = "vendor-batch"
    PUBLISH = "publish"
    REVENDOR = "revendor"


class WorkspaceChangeKind(str, Enum):
    ADDED = "added"
    CHANGED = "changed"
    UNCHANGED = "unchanged"
    # Only re-vendoring produces this: upstream deleted a file the registry copied, and keeping it
    # would leave a package that is quietly no longer the thing that was vendored.  Every other
    # registry operation writes a fixed set of derived documents and has nothing to remove.
    REMOVED = "removed"


@dataclass(frozen=True, slots=True)
class RegistryInitOptions:
    registry_id: str
    display_name: str
    minimum_aart: SemVer
    maximum_aart_exclusive: SemVer

    def __post_init__(self) -> None:
        if (
            _SLUG_RE.fullmatch(self.registry_id) is None
            or not _one_safe_line(self.display_name)
            or not isinstance(self.minimum_aart, SemVer)
            or not isinstance(self.maximum_aart_exclusive, SemVer)
            or not self.minimum_aart < self.maximum_aart_exclusive
        ):
            raise ValueError("registry init options are invalid")


@dataclass(frozen=True, slots=True)
class ArtifactScaffoldOptions:
    kind: str
    name: str
    version: SemVer
    summary: str
    profiles: tuple[str, ...]
    platforms: tuple[str, ...]
    scopes: tuple[str, ...]
    modes: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            self.kind not in _KINDS
            or _SLUG_RE.fullmatch(self.name) is None
            or not isinstance(self.version, SemVer)
            or not _one_safe_line(self.summary)
            or not self.profiles
            or not self.platforms
            or not self.scopes
            or not self.modes
            or any(_SLUG_RE.fullmatch(value) is None for value in self.profiles + self.platforms)
            or not set(self.scopes) <= _SCOPES
            or not set(self.modes) <= _MODES
        ):
            raise ValueError("artifact scaffold options are invalid")
        object.__setattr__(self, "profiles", tuple(sorted(set(self.profiles))))
        object.__setattr__(self, "platforms", tuple(sorted(set(self.platforms))))
        object.__setattr__(self, "scopes", tuple(sorted(set(self.scopes))))
        object.__setattr__(self, "modes", tuple(sorted(set(self.modes))))


@dataclass(frozen=True, slots=True)
class CollectionAuthorOptions:
    name: str
    summary: str
    members: tuple[ArtifactIdentity, ...]

    def __post_init__(self) -> None:
        if (
            _SLUG_RE.fullmatch(self.name) is None
            or not _one_safe_line(self.summary)
            or not self.members
            or any(not isinstance(member, ArtifactIdentity) for member in self.members)
        ):
            raise ValueError("collection author options are invalid")
        object.__setattr__(self, "members", tuple(sorted(set(self.members), key=str)))


@dataclass(frozen=True, slots=True, order=True)
class RegistryWorkspaceChange:
    path: SafeRelativePath
    kind: WorkspaceChangeKind
    content: bytes
    before_digest: ObjectDigest | None
    # `None` only for a removal, where there is no resulting file to name.  Every other kind carries
    # the digest of exactly the bytes it writes.
    after_digest: ObjectDigest | None
    executable: bool = False

    def __post_init__(self) -> None:
        removal = self.kind is WorkspaceChangeKind.REMOVED
        if (
            not isinstance(self.path, SafeRelativePath)
            or not _managed_path(self.path)
            or not isinstance(self.kind, WorkspaceChangeKind)
            or not isinstance(self.content, bytes)
            or not isinstance(self.executable, bool)
            or (not removal and not _valid_digest(self.after_digest))
            or (not removal and sha256_bytes(self.content) != self.after_digest)
            or (self.before_digest is not None and not _valid_digest(self.before_digest))
        ):
            raise ValueError("registry workspace change is invalid")
        if removal and (
            self.after_digest is not None
            or self.content != b""
            or not _valid_digest(self.before_digest)
        ):
            raise ValueError("removed workspace file names only what it removes")
        if self.kind is WorkspaceChangeKind.ADDED and self.before_digest is not None:
            raise ValueError("added workspace file cannot have a previous digest")
        if self.kind is WorkspaceChangeKind.CHANGED and (
            self.before_digest is None or self.before_digest == self.after_digest
        ):
            raise ValueError("changed workspace file requires distinct digests")
        if self.kind is WorkspaceChangeKind.UNCHANGED and self.before_digest != self.after_digest:
            raise ValueError("unchanged workspace file requires equal digests")


def _managed_path(path: SafeRelativePath) -> bool:
    raw = str(path)
    if raw in {
        "aart-registry.json",
        "aart-source.json",
        "aart.lock.json",
        "aart.index.json",
        ".gitignore",
        ".github/workflows/aart-registry.yml",
        ".github/ISSUE_TEMPLATE/usage-report.yml",
        ".github/workflows/aart-usage-dashboard.yml",
        ".github/workflows/aart-usage-validate.yml",
    }:
        return True
    # `security/` carries committed assessment evidence.  It is not a registry input — the inputs
    # digest ignores it — so a plan may write evidence without making the lock and index stale.
    return path.parts[0] in {"entries", "artifacts", "collections", "security"}


def registry_workspace_review_digest(
    operation: RegistryOperation,
    expected_snapshot_digest: ObjectDigest,
    next_snapshot_digest: ObjectDigest,
    changes: tuple[RegistryWorkspaceChange, ...],
) -> ObjectDigest:
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
                                    (
                                        "after_digest",
                                        None
                                        if item.after_digest is None
                                        else str(item.after_digest),
                                    ),
                                    (
                                        "before_digest",
                                        None
                                        if item.before_digest is None
                                        else str(item.before_digest),
                                    ),
                                    ("executable", item.executable),
                                    ("kind", item.kind.value),
                                    ("path", str(item.path)),
                                )
                            )
                            for item in ordered
                        )
                    ),
                ),
                ("expected_snapshot_digest", str(expected_snapshot_digest)),
                ("next_snapshot_digest", str(next_snapshot_digest)),
                ("operation", operation.value),
            )
        )
    )


@dataclass(frozen=True, slots=True)
class RegistryWorkspacePlan:
    operation: RegistryOperation
    expected_snapshot_digest: ObjectDigest
    next_snapshot_digest: ObjectDigest
    changes: tuple[RegistryWorkspaceChange, ...]
    review_digest: ObjectDigest

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.changes, key=lambda item: str(item.path)))
        paths = tuple(item.path for item in ordered)
        if (
            not isinstance(self.operation, RegistryOperation)
            or not _valid_digest(self.expected_snapshot_digest)
            or not _valid_digest(self.next_snapshot_digest)
            or not ordered
            or len(set(paths)) != len(paths)
            or not _valid_digest(self.review_digest)
            or self.review_digest
            != registry_workspace_review_digest(
                self.operation,
                self.expected_snapshot_digest,
                self.next_snapshot_digest,
                ordered,
            )
        ):
            raise ValueError("registry workspace plan is invalid")
        object.__setattr__(self, "changes", ordered)

    @property
    def changed_paths(self) -> int:
        return sum(item.kind is not WorkspaceChangeKind.UNCHANGED for item in self.changes)


@dataclass(frozen=True, slots=True)
class VendoredArtifactPlan:
    """A vendoring plan and the assessment of the exact bytes it would write.

    They travel together because the review presents both, and recomputing the assessment at render
    time would let the two drift: the maintainer would approve a digest covering one thing while
    reading another.
    """

    plan: RegistryWorkspacePlan
    assessment: SecurityAssessment
    license: LicenseFinding
    # Absent for every type whose payload reaches the consumer whole, which is four of the five.
    delivery: DeliveryFinding | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.plan, RegistryWorkspacePlan)
            or not isinstance(self.assessment, SecurityAssessment)
            or not isinstance(self.license, LicenseFinding)
            or (self.delivery is not None and not isinstance(self.delivery, DeliveryFinding))
        ):
            raise ValueError("vendored artifact plan is invalid")


@dataclass(frozen=True, slots=True)
class VendoredArtifactCheck:
    """What re-resolving one vendored artifact's upstream found.

    The plan is present only when upstream moved *and* the maintainer supplied the version that
    movement deserves (design §4). `up-to-date` has nothing to write, and `unreachable` must never
    be able to write: a maintainer who lost access to an upstream is told that, not that their copy
    is current.
    """

    disposition: NativeReferenceDisposition
    resolved_commit: str | None
    recorded_commit: str
    added: int
    changed: int
    removed: int
    plan: RegistryWorkspacePlan | None = None
    assessment: SecurityAssessment | None = None
    delivery: DeliveryFinding | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.disposition, NativeReferenceDisposition)
            or not isinstance(self.recorded_commit, str)
            or any(
                not isinstance(value, int) or isinstance(value, bool) or value < 0
                for value in (self.added, self.changed, self.removed)
            )
            or (self.plan is not None and not isinstance(self.plan, RegistryWorkspacePlan))
            or (self.assessment is not None and not isinstance(self.assessment, SecurityAssessment))
            or (self.plan is None) != (self.assessment is None)
        ):
            raise ValueError("vendored artifact check is invalid")
        if self.disposition is not NativeReferenceDisposition.CHANGED and self.plan is not None:
            raise ValueError("only a changed upstream may carry a plan")
        if self.disposition is NativeReferenceDisposition.UNREACHABLE and (
            self.resolved_commit is not None
        ):
            raise ValueError("an unreachable upstream resolved no commit")


@dataclass(frozen=True, slots=True)
class RegistryApplyCommand:
    plan: RegistryWorkspacePlan

    def __post_init__(self) -> None:
        if not isinstance(self.plan, RegistryWorkspacePlan):
            raise ValueError("registry apply command requires an exact reviewed plan")


@dataclass(frozen=True, slots=True)
class RegistryApplyReceipt:
    review_digest: ObjectDigest
    snapshot_digest: ObjectDigest
    changed_paths: int

    def __post_init__(self) -> None:
        if (
            not _valid_digest(self.review_digest)
            or not _valid_digest(self.snapshot_digest)
            or not isinstance(self.changed_paths, int)
            or isinstance(self.changed_paths, bool)
            or self.changed_paths < 0
        ):
            raise ValueError("registry apply receipt is invalid")


@dataclass(frozen=True, slots=True)
class RegistryQualityCheck:
    name: str
    diagnostics: tuple[Diagnostic, ...] = ()

    def __post_init__(self) -> None:
        if _SLUG_RE.fullmatch(self.name) is None:
            raise ValueError("registry quality check name must be a slug")
        object.__setattr__(self, "diagnostics", sort_diagnostics(self.diagnostics))

    @property
    def passed(self) -> bool:
        return not any(item.severity is Severity.ERROR for item in self.diagnostics)


@dataclass(frozen=True, slots=True)
class RegistryQualityReport:
    checks: tuple[RegistryQualityCheck, ...]

    def __post_init__(self) -> None:
        if not self.checks or len({item.name for item in self.checks}) != len(self.checks):
            raise ValueError("registry quality report requires unique checks")

    @property
    def passed(self) -> bool:
        return all(item.passed for item in self.checks)
