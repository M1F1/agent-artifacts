"""Frozen values for reviewed canonical installation plans and outcomes."""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from enum import Enum
from typing import Literal, TypeAlias

from agent_artifacts.domain.identifiers import (
    ArtifactCoordinate,
    ArtifactIdentity,
    ObjectDigest,
    SourceAlias,
)
from agent_artifacts.domain.result import Ok
from agent_artifacts.install_state.model import (
    ArtifactEvidence,
    EffectProof,
    InstallationRecord,
    InstallScope,
    InstallState,
    MemoryMode,
    SourceEvidence,
)
from agent_artifacts.install_state.schema import install_state_bytes
from agent_artifacts.protocol.hashing import (
    directory_entry,
    file_entry,
    json_digest,
    sha256_bytes,
    tree_digest,
)
from agent_artifacts.protocol.json import JsonArray, JsonObject, JsonValue
from agent_artifacts.protocol.paths import SafeRelativePath, parse_relative_path
from agent_artifacts.protocol.semver import parse_semver
from agent_artifacts.store.model import ObjectCandidate, ObjectStorePaths

InstallMode = Literal["copy", "symlink"]
LinkSemantics = Literal["immutable-object", "mutable-local"]
SnapshotKind = Literal["absent", "file", "tree", "symlink", "special"]
EffectStatus = Literal["changed", "current", "skipped", "failed", "rolled-back"]
_SLUG_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
_REFERENCE_OWNER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")
_TRUST_CLASSES = frozenset(
    {"unverified", "local", "direct-source", "registry-reviewed", "company-reviewed"}
)
_ARTIFACT_KINDS = frozenset({"skill", "guideline", "mcp", "hook", "memory"})


def _valid_digest(value: object) -> bool:
    return (
        isinstance(value, ObjectDigest)
        and value.algorithm == "sha256"
        and _HEX_RE.fullmatch(value.value) is not None
    )


def _absolute(path: str, label: str) -> str:
    if (
        not isinstance(path, str)
        or not posixpath.isabs(path)
        or posixpath.normpath(path) != path
        or path == "/"
        or "\x00" in path
        or "\r" in path
        or "\n" in path
    ):
        raise ValueError(f"{label} must be a normalized non-root absolute path")
    return path


def _safe_relative(path: str, label: str) -> str:
    parsed = parse_relative_path(path)
    if not isinstance(parsed, Ok):
        raise ValueError(f"{label} must be a safe relative path")
    if str(parsed.value) != path:
        raise ValueError(f"{label} must be a canonical relative path")
    return path


@dataclass(frozen=True, slots=True)
class InstallLocation:
    project_root: str
    user_home: str
    data_root: str

    def __post_init__(self) -> None:
        _absolute(self.project_root, "project root")
        _absolute(self.user_home, "user home")
        _absolute(self.data_root, "data root")


@dataclass(frozen=True, slots=True)
class InstallRequest:
    identity: ArtifactIdentity
    source: SourceAlias | None = None
    version: str | None = None
    profile: str = "claude"
    profile_version: int = 1
    platform: str = "darwin"
    scope: InstallScope = "project"
    mode: InstallMode = "copy"
    force: bool = False
    offline: bool = False
    memory_mode: MemoryMode = "prepend"
    mutable_local_payload_root: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.identity, ArtifactIdentity)
            or self.identity.kind not in _ARTIFACT_KINDS
            or _SLUG_RE.fullmatch(self.identity.name) is None
            or (self.source is not None and not isinstance(self.source, SourceAlias))
            or (self.source is not None and _SLUG_RE.fullmatch(self.source.value) is None)
            or (self.version is not None and not isinstance(parse_semver(self.version), Ok))
            or _SLUG_RE.fullmatch(self.profile) is None
            or not isinstance(self.profile_version, int)
            or isinstance(self.profile_version, bool)
            or not 1 <= self.profile_version <= 2**63 - 1
            or not self.platform
            or "\n" in self.platform
            or self.scope not in {"project", "user"}
            or self.mode not in {"copy", "symlink"}
            or not isinstance(self.force, bool)
            or not isinstance(self.offline, bool)
            or self.memory_mode not in {"replace", "prepend", "append", "skip"}
            or (
                self.mutable_local_payload_root is not None
                and (
                    self.mode != "symlink"
                    or not posixpath.isabs(self.mutable_local_payload_root)
                    or posixpath.normpath(self.mutable_local_payload_root)
                    != self.mutable_local_payload_root
                    or self.mutable_local_payload_root == "/"
                    or "\x00" in self.mutable_local_payload_root
                    or "\r" in self.mutable_local_payload_root
                    or "\n" in self.mutable_local_payload_root
                )
            )
        ):
            raise ValueError("canonical install request is invalid")


@dataclass(frozen=True, slots=True)
class InstallProvenance:
    origin_url: str
    resolved_commit: str
    path: SafeRelativePath

    def __post_init__(self) -> None:
        if (
            not self.origin_url
            or self.origin_url != self.origin_url.strip()
            or "\r" in self.origin_url
            or "\n" in self.origin_url
            or "://" in self.origin_url
            or "@" in self.origin_url
            or "/" not in self.origin_url
            or _COMMIT_RE.fullmatch(self.resolved_commit) is None
        ):
            raise ValueError("install provenance is invalid")
        parsed = parse_relative_path(str(self.path))
        if not isinstance(self.path, SafeRelativePath) or not isinstance(parsed, Ok):
            raise ValueError("install provenance path is invalid")
        if parsed.value != self.path:
            raise ValueError("install provenance path is not canonical")


@dataclass(frozen=True, slots=True)
class TreeMember:
    path: SafeRelativePath
    kind: Literal["directory", "file"]
    content: bytes = b""
    executable: bool = False

    def __post_init__(self) -> None:
        parsed = parse_relative_path(str(self.path))
        if not isinstance(self.path, SafeRelativePath) or not isinstance(parsed, Ok):
            raise ValueError("tree member path is invalid")
        if parsed.value != self.path:
            raise ValueError("tree member path is not canonical")
        if self.kind == "directory":
            if self.content or self.executable:
                raise ValueError("tree directory cannot contain file metadata")
        elif self.kind == "file":
            if not isinstance(self.content, bytes) or not isinstance(self.executable, bool):
                raise ValueError("tree file metadata is invalid")
        else:
            raise ValueError("tree member kind is invalid")


def tree_members_digest(members: tuple[TreeMember, ...]) -> ObjectDigest:
    entries = tuple(
        directory_entry(member.path)
        if member.kind == "directory"
        else file_entry(member.path, member.content, executable=member.executable)
        for member in members
    )
    digest = tree_digest(entries)
    if not isinstance(digest, Ok):
        raise ValueError("tree members cannot be hashed")
    return digest.value


def file_snapshot_digest(content: bytes, executable: bool = False) -> ObjectDigest:
    marker = b"x" if executable else b"-"
    return sha256_bytes(b"file\0" + marker + len(content).to_bytes(8, "big") + content)


def link_snapshot_digest(target: str) -> ObjectDigest:
    if not target or "\x00" in target or "\r" in target or "\n" in target:
        raise ValueError("link target must be one non-empty path")
    return sha256_bytes(b"symlink\0" + target.encode("utf-8", errors="surrogateescape"))


@dataclass(frozen=True, slots=True)
class PathSnapshot:
    path: str
    kind: SnapshotKind
    digest: ObjectDigest | None = None
    content: bytes = b""
    executable: bool = False
    members: tuple[TreeMember, ...] = ()
    link_target: str | None = None
    target_exists: bool | None = None

    def __post_init__(self) -> None:
        _absolute(self.path, "snapshot path")
        if self.kind == "absent":
            valid = (
                self.digest is None
                and not self.content
                and not self.executable
                and not self.members
                and self.link_target is None
                and self.target_exists is None
            )
        elif self.kind == "file":
            valid = (
                self.digest == file_snapshot_digest(self.content, self.executable)
                and not self.members
                and self.link_target is None
                and self.target_exists is None
            )
        elif self.kind == "tree":
            ordered = tuple(sorted(self.members, key=lambda member: str(member.path)))
            valid = (
                bool(ordered)
                and ordered == self.members
                and self.digest == tree_members_digest(ordered)
                and not self.content
                and not self.executable
                and self.link_target is None
                and self.target_exists is None
            )
        elif self.kind == "symlink":
            valid = (
                isinstance(self.link_target, str)
                and self.digest == link_snapshot_digest(self.link_target)
                and isinstance(self.target_exists, bool)
                and not self.content
                and not self.members
                and not self.executable
            )
        elif self.kind == "special":
            valid = (
                _valid_digest(self.digest)
                and not self.content
                and not self.members
                and not self.executable
                and self.link_target is None
                and self.target_exists is None
            )
        else:
            valid = False
        if not valid:
            raise ValueError("path snapshot does not bind its exact observed state")

    @classmethod
    def absent(cls, path: str) -> PathSnapshot:
        return cls(path, "absent")

    @classmethod
    def file(cls, path: str, content: bytes, *, executable: bool = False) -> PathSnapshot:
        return cls(
            path,
            "file",
            file_snapshot_digest(content, executable),
            content,
            executable,
        )

    @classmethod
    def tree(cls, path: str, members: tuple[TreeMember, ...]) -> PathSnapshot:
        ordered = tuple(sorted(members, key=lambda member: str(member.path)))
        return cls(path, "tree", tree_members_digest(ordered), members=ordered)

    @classmethod
    def symlink(cls, path: str, target: str, *, target_exists: bool) -> PathSnapshot:
        return cls(
            path,
            "symlink",
            link_snapshot_digest(target),
            link_target=target,
            target_exists=target_exists,
        )


@dataclass(frozen=True, slots=True)
class CopyTreeOperation:
    source_path: str
    destination: str
    absolute_destination: str
    members: tuple[TreeMember, ...]
    desired_digest: ObjectDigest
    precondition: PathSnapshot
    overwrote: bool = False

    def __post_init__(self) -> None:
        _safe_relative(self.source_path, "copy source path")
        _absolute(self.absolute_destination, "copy destination")
        if (
            self.precondition.path != self.absolute_destination
            or not self.members
            or tuple(sorted(self.members, key=lambda item: str(item.path))) != self.members
            or tree_members_digest(self.members) != self.desired_digest
            or not isinstance(self.overwrote, bool)
        ):
            raise ValueError("copy-tree operation is not exactly bound")


@dataclass(frozen=True, slots=True)
class WriteFileOperation:
    source_path: str
    destination: str
    absolute_destination: str
    content: bytes
    executable: bool
    desired_digest: ObjectDigest
    precondition: PathSnapshot
    effect_kind: Literal["write-file", "managed-block"] = "write-file"
    overwrote: bool = False
    # Set only on a memory ``replace`` that displaced foreign content: names the sibling write
    # holding the displaced bytes, so uninstall restores rather than deletes.
    restores_from: str | None = None

    def __post_init__(self) -> None:
        _safe_relative(self.source_path, "file source path")
        _absolute(self.absolute_destination, "file destination")
        if (
            self.precondition.path != self.absolute_destination
            or self.desired_digest != file_snapshot_digest(self.content, self.executable)
            or self.effect_kind not in {"write-file", "managed-block"}
            or not isinstance(self.overwrote, bool)
            or (self.restores_from is not None and self.restores_from == self.destination)
        ):
            raise ValueError("write-file operation is not exactly bound")


@dataclass(frozen=True, slots=True)
class LinkOperation:
    source_path: str
    destination: str
    absolute_destination: str
    target: str
    target_kind: Literal["file", "tree"]
    semantics: LinkSemantics
    target_content_digest: ObjectDigest
    desired_digest: ObjectDigest
    target_precondition: PathSnapshot
    precondition: PathSnapshot
    overwrote: bool = False

    def __post_init__(self) -> None:
        _safe_relative(self.source_path, "link source path")
        _absolute(self.absolute_destination, "link destination")
        _absolute(self.target, "link target")
        if (
            self.precondition.path != self.absolute_destination
            or self.target_precondition.path != self.target
            or self.target_precondition.kind != self.target_kind
            or self.target_precondition.digest != self.target_content_digest
            or self.target_kind not in {"file", "tree"}
            or self.semantics not in {"immutable-object", "mutable-local"}
            or not _valid_digest(self.target_content_digest)
            or self.desired_digest != link_snapshot_digest(self.target)
            or not isinstance(self.overwrote, bool)
        ):
            raise ValueError("link operation is not exactly bound")


@dataclass(frozen=True, slots=True)
class MergeJsonOperation:
    destination: str
    absolute_destination: str
    json_path: str
    merge_mode: Literal["key", "list"]
    identity: tuple[str, ...]
    identity_evidence: JsonValue
    value_digest: ObjectDigest
    identity_digest: ObjectDigest
    content: bytes
    desired_digest: ObjectDigest
    precondition: PathSnapshot
    overwrote: bool = False

    def __post_init__(self) -> None:
        _absolute(self.absolute_destination, "merge destination")
        if (
            self.precondition.path != self.absolute_destination
            or not self.json_path
            or self.merge_mode not in {"key", "list"}
            or not self.identity
            or any(not item or "\n" in item for item in self.identity)
            or self.desired_digest != file_snapshot_digest(self.content)
            or self.identity_digest != json_digest(self.identity_evidence)
            or not isinstance(self.value_digest, ObjectDigest)
            or not isinstance(self.overwrote, bool)
        ):
            raise ValueError("merge-json operation is not exactly bound")


InstallOperation: TypeAlias = (
    CopyTreeOperation | WriteFileOperation | LinkOperation | MergeJsonOperation
)


def operation_is_current(operation: InstallOperation) -> bool:
    observed = operation.precondition
    if isinstance(operation, LinkOperation):
        return (
            observed.kind == "symlink"
            and observed.digest == operation.desired_digest
            and observed.link_target == operation.target
            and observed.target_exists is True
        )
    return observed.digest == operation.desired_digest


def _snapshot_json(snapshot: PathSnapshot) -> JsonObject:
    return JsonObject(
        (
            ("path", snapshot.path),
            ("kind", snapshot.kind),
            ("digest", None if snapshot.digest is None else str(snapshot.digest)),
            ("link_target", snapshot.link_target),
            ("target_exists", snapshot.target_exists),
        )
    )


def _operation_json(operation: InstallOperation) -> JsonObject:
    common = (
        ("destination", operation.destination),
        ("absolute_destination", operation.absolute_destination),
        ("desired_digest", str(operation.desired_digest)),
        ("precondition", _snapshot_json(operation.precondition)),
        ("overwrote", operation.overwrote),
    )
    if isinstance(operation, CopyTreeOperation):
        return JsonObject((("kind", "copy-tree"), ("source_path", operation.source_path), *common))
    if isinstance(operation, WriteFileOperation):
        return JsonObject(
            (
                ("kind", operation.effect_kind),
                ("source_path", operation.source_path),
                ("restores_from", operation.restores_from),
                *common,
            )
        )
    if isinstance(operation, LinkOperation):
        return JsonObject(
            (
                (
                    "kind",
                    "symlink-tree" if operation.target_kind == "tree" else "symlink-file",
                ),
                ("source_path", operation.source_path),
                ("target", operation.target),
                ("target_kind", operation.target_kind),
                ("semantics", operation.semantics),
                ("target_content_digest", str(operation.target_content_digest)),
                ("target_precondition", _snapshot_json(operation.target_precondition)),
                *common,
            )
        )
    return JsonObject(
        (
            ("kind", "merge-json"),
            ("json_path", operation.json_path),
            ("merge_mode", operation.merge_mode),
            ("identity", JsonArray(tuple(operation.identity))),
            ("identity_evidence", operation.identity_evidence),
            ("value_digest", str(operation.value_digest)),
            ("identity_digest", str(operation.identity_digest)),
            *common,
        )
    )


def _plan_review_value(plan: InstallPlan) -> JsonObject:
    # Every entry must be stable while the world is: a review digest is consent a human carries to a
    # later finalize. ``source_health`` and ``source_age_seconds`` are deliberately absent — both are
    # read off the wall clock, and including them made the digest change on an untouched workspace.
    # Freshness belongs in the rendered review, not in the identity of the plan.
    request = plan.request
    return JsonObject(
        (
            ("schema_version", 1),
            ("coordinate", str(plan.coordinate)),
            ("requested_identity", str(request.identity)),
            ("requested_source", None if request.source is None else request.source.value),
            ("requested_version", request.version),
            ("profile", request.profile),
            ("profile_version", request.profile_version),
            ("platform", request.platform),
            ("scope", request.scope),
            ("mode", request.mode),
            ("force", request.force),
            ("offline", request.offline),
            ("memory_mode", request.memory_mode),
            ("mutable_local_payload_root", request.mutable_local_payload_root),
            ("source_alias", plan.source.alias.value),
            ("source_id", plan.source.declared_id.value),
            ("source_kind", plan.source.kind.value),
            ("source_origin", plan.source.origin),
            ("resolved_commit", plan.source.resolved_commit),
            ("subscription_ref", plan.source.subscription_ref),
            ("source_snapshot_digest", str(plan.source_snapshot_digest)),
            ("artifact_version", str(plan.artifact.version)),
            ("manifest_digest", str(plan.artifact.manifest_digest)),
            ("payload_digest", str(plan.artifact.payload_digest)),
            ("object_digest", str(plan.object_digest)),
            ("object_store_root", plan.object_store_paths.root),
            ("object_root", plan.object_root),
            (
                "provenance",
                None
                if plan.provenance is None
                else JsonObject(
                    (
                        ("origin_url", plan.provenance.origin_url),
                        ("resolved_commit", plan.provenance.resolved_commit),
                        ("path", str(plan.provenance.path)),
                    )
                ),
            ),
            ("trust", plan.trust),
            ("trust_evidence_digest", str(plan.trust_evidence_digest)),
            ("policy_digest", str(plan.policy_digest)),
            ("operations", JsonArray(tuple(_operation_json(item) for item in plan.operations))),
            ("state_path", plan.state_path),
            ("state_lock_path", plan.state_lock_path),
            ("state_precondition", _snapshot_json(plan.state_precondition)),
            ("replacement_state_digest", str(plan.replacement_state_digest)),
            ("reference_owner", plan.reference_owner),
        )
    )


def _effect_matches_operation(effect: EffectProof, operation: InstallOperation) -> bool:
    if effect.destination != operation.destination:
        return False
    if isinstance(operation, LinkOperation):
        return (
            effect.kind == ("symlink-tree" if operation.target_kind == "tree" else "symlink-file")
            and effect.actual_mode == "symlink"
            and effect.installed_digest == operation.target_content_digest
            and effect.source_path == operation.source_path
            and effect.link_target == operation.target
            and effect.link_semantics == operation.semantics
            and effect.json_path is None
        )
    if effect.actual_mode != "copy":
        return False
    if isinstance(operation, CopyTreeOperation):
        return (
            effect.kind == "copy-tree"
            and effect.installed_digest == operation.desired_digest
            and effect.source_path == operation.source_path
            and effect.json_path is None
        )
    if isinstance(operation, WriteFileOperation):
        return (
            effect.kind == operation.effect_kind
            and effect.installed_digest == operation.desired_digest
            and effect.source_path
            == (operation.source_path if operation.effect_kind == "write-file" else None)
            and effect.json_path is None
        )
    return (
        effect.kind == "merge-json"
        and effect.installed_digest == operation.value_digest
        and effect.source_path is None
        and effect.json_path == operation.json_path
        and effect.merge_mode == operation.merge_mode
        and effect.identity_digest == operation.identity_digest
        and effect.identity_evidence == operation.identity_evidence
    )


def _replacement_record(plan: InstallPlan) -> InstallationRecord | None:
    return next(
        (
            record
            for record in plan.replacement_state.installations
            if record.coordinate.source == plan.coordinate.source
            and record.coordinate.artifact == plan.coordinate.artifact
            and record.profile == plan.request.profile
            and record.scope == plan.request.scope
        ),
        None,
    )


def _operations_match_artifact(plan: InstallPlan) -> bool:
    operations = plan.operations
    kind = plan.request.identity.kind
    if kind == "skill":
        return len(operations) == 1 and (
            isinstance(operations[0], CopyTreeOperation)
            or (isinstance(operations[0], LinkOperation) and operations[0].target_kind == "tree")
        )
    if kind == "guideline":
        return len(operations) == 1 and (
            isinstance(operations[0], WriteFileOperation)
            or (isinstance(operations[0], LinkOperation) and operations[0].target_kind == "file")
        )
    if kind == "mcp":
        return len(operations) == 1 and isinstance(operations[0], MergeJsonOperation)
    if kind == "hook":
        return (
            len(operations) == 2
            and (
                isinstance(operations[0], CopyTreeOperation)
                or (
                    isinstance(operations[0], LinkOperation) and operations[0].target_kind == "tree"
                )
            )
            and isinstance(operations[1], MergeJsonOperation)
        )
    # memory: one write, or the backup sidecar followed by the destination that restores from it.
    # Nothing else — the pair is the only shape in which a replace may displace foreign content,
    # and requiring the link here keeps an unattached sidecar out of a reviewed plan.
    if len(operations) == 2:
        sidecar, destination = operations
        return (
            isinstance(sidecar, WriteFileOperation)
            and isinstance(destination, WriteFileOperation)
            and sidecar.restores_from is None
            and destination.restores_from == sidecar.destination
        )
    return len(operations) == 1 and isinstance(operations[0], WriteFileOperation)


@dataclass(frozen=True, slots=True)
class InstallPlan:
    request: InstallRequest
    coordinate: ArtifactCoordinate
    source: SourceEvidence
    source_health: str
    source_age_seconds: int
    source_snapshot_digest: ObjectDigest
    artifact: ArtifactEvidence
    trust: str
    trust_evidence_digest: ObjectDigest
    policy_digest: ObjectDigest
    object_store_paths: ObjectStorePaths
    object_candidate: ObjectCandidate
    object_root: str
    object_digest: ObjectDigest
    provenance: InstallProvenance | None
    operations: tuple[InstallOperation, ...]
    state_path: str
    state_lock_path: str
    state_precondition: PathSnapshot
    replacement_state: InstallState
    replacement_state_digest: ObjectDigest
    reference_owner: str
    review_digest: ObjectDigest

    def __post_init__(self) -> None:
        _absolute(self.object_root, "object root")
        _absolute(self.state_path, "state path")
        _absolute(self.state_lock_path, "state lock path")
        expected_review = json_digest(_plan_review_value(self))
        state_bytes = install_state_bytes(self.replacement_state)
        unreviewed = sha256_bytes(b"unreviewed-install-plan")
        expected_object_root = posixpath.join(
            self.object_store_paths.objects,
            self.object_digest.value[:2],
            self.object_digest.value[2:],
        )
        replacement = _replacement_record(self)
        project_root = posixpath.dirname(posixpath.dirname(self.state_path))
        destinations_are_scoped = all(
            (
                operation.absolute_destination
                == posixpath.join(project_root, operation.destination)
                if self.request.scope == "project"
                else operation.absolute_destination == operation.destination
            )
            for operation in self.operations
        )
        links = tuple(
            operation for operation in self.operations if isinstance(operation, LinkOperation)
        )
        immutable_payload_root = posixpath.join(self.object_root, "payload")

        def expected_link_target(operation: LinkOperation) -> str | None:
            base = (
                immutable_payload_root
                if operation.semantics == "immutable-object"
                else self.request.mutable_local_payload_root
            )
            if base is None:
                return None
            if operation.source_path == "payload":
                return base
            if operation.source_path.startswith("payload/"):
                return posixpath.join(
                    base,
                    operation.source_path.removeprefix("payload/"),
                )
            return None

        mutable_root_is_safe = self.request.mutable_local_payload_root is None or (
            self.source.kind.value == "source-local"
            and posixpath.commonpath((self.source.origin, self.request.mutable_local_payload_root))
            == self.source.origin
        )
        links_are_safe = all(
            operation.target == expected_link_target(operation) for operation in links
        )
        if (
            self.coordinate.source != self.source.alias
            or self.coordinate.artifact != self.artifact.identity
            or self.coordinate.version != str(self.artifact.version)
            or self.object_candidate.digest != self.object_digest
            or self.artifact.object_digest != self.object_digest
            or not all(
                _valid_digest(value)
                for value in (
                    self.trust_evidence_digest,
                    self.policy_digest,
                    self.source_snapshot_digest,
                    self.object_digest,
                    self.replacement_state_digest,
                    self.review_digest,
                )
            )
            or self.object_root != expected_object_root
            or (self.provenance is not None and not isinstance(self.provenance, InstallProvenance))
            or self.source_health not in {"healthy", "stale", "degraded"}
            or not isinstance(self.source_age_seconds, int)
            or isinstance(self.source_age_seconds, bool)
            or self.source_age_seconds < 0
            or self.trust not in _TRUST_CLASSES
            or not self.operations
            or not _operations_match_artifact(self)
            or len({item.absolute_destination for item in self.operations}) != len(self.operations)
            or not destinations_are_scoped
            or (self.request.mode == "copy" and bool(links))
            or (self.request.mutable_local_payload_root is not None and not links)
            or any(
                operation.semantics
                != (
                    "mutable-local"
                    if self.request.mutable_local_payload_root is not None
                    else "immutable-object"
                )
                for operation in links
            )
            or not mutable_root_is_safe
            or not links_are_safe
            or self.state_precondition.path != self.state_path
            or sha256_bytes(state_bytes) != self.replacement_state_digest
            or _REFERENCE_OWNER_RE.fullmatch(self.reference_owner) is None
            or len(self.reference_owner) > 499
            or replacement is None
            or replacement.source != self.source
            or replacement.artifact != self.artifact
            or replacement.profile_version != self.request.profile_version
            or replacement.requested_mode != self.request.mode
            or replacement.memory_mode
            != (self.request.memory_mode if self.request.identity.kind == "memory" else None)
            or len(replacement.effects) != len(self.operations)
            or not all(
                _effect_matches_operation(effect, operation)
                for effect, operation in zip(
                    replacement.effects,
                    self.operations,
                    strict=True,
                )
            )
            or self.review_digest not in {unreviewed, expected_review}
        ):
            raise ValueError("canonical install plan is not exactly review-bound")
        if self.review_digest == unreviewed:
            object.__setattr__(self, "review_digest", expected_review)


class InstallStatus(str, Enum):
    APPLIED = "applied"
    CURRENT = "current"
    CONFLICTED = "conflicted"
    FAILED = "failed"


class LinkStatus(str, Enum):
    CURRENT = "current"
    MUTABLE_LOCAL = "mutable-local"
    BROKEN = "broken"
    RETARGETED = "retargeted"
    REPLACED = "replaced"


def classify_link(effect: EffectProof, observed: PathSnapshot) -> LinkStatus:
    if effect.kind not in {"symlink-file", "symlink-tree"} or effect.link_target is None:
        raise ValueError("link status requires a managed link effect")
    if observed.kind != "symlink":
        return LinkStatus.REPLACED
    if observed.link_target != effect.link_target:
        return LinkStatus.RETARGETED
    if not observed.target_exists:
        return LinkStatus.BROKEN
    if effect.link_semantics == "mutable-local":
        return LinkStatus.MUTABLE_LOCAL
    return LinkStatus.CURRENT


@dataclass(frozen=True, slots=True)
class EffectOutcome:
    kind: str
    destination: str
    status: EffectStatus
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class InstallOutcome:
    review_digest: ObjectDigest
    status: InstallStatus
    effects: tuple[EffectOutcome, ...]
    state_written: bool

    @property
    def changed(self) -> int:
        return sum(item.status == "changed" for item in self.effects)
