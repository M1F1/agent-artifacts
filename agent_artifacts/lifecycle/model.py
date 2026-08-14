"""Pure values for canonical installation lifecycle status, update, and uninstall."""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from enum import Enum
from typing import Literal

from agent_artifacts.domain.identifiers import ArtifactCoordinate, ObjectDigest
from agent_artifacts.domain.result import Err
from agent_artifacts.install_state.model import (
    EffectProof,
    InstallationRecord,
    InstallScope,
    InstallState,
)
from agent_artifacts.install_state.schema import install_state_bytes, parse_install_state
from agent_artifacts.installation.model import InstallLocation, InstallPlan, PathSnapshot
from agent_artifacts.protocol.hashing import sha256_bytes
from agent_artifacts.protocol.json import JsonArray, JsonObject, canonical_json_bytes
from agent_artifacts.store.model import ObjectStorePaths, ReferenceIndex
from agent_artifacts.store.references import reference_index_bytes

LifecycleAction = Literal["status", "check", "update", "uninstall"]
MutationKind = Literal["none", "remove", "write"]
_PROFILE_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")


class LifecycleStatus(str, Enum):
    CURRENT = "current"
    UPDATE_AVAILABLE = "update-available"
    CHANGED = "changed"
    REMOVED = "removed"
    REMOVED_UPSTREAM = "removed-upstream"
    SOURCE_UNAVAILABLE = "source-unavailable"
    IDENTITY_CHANGED = "identity-changed"
    MISSING = "missing"
    DRIFTED = "drifted"
    BROKEN = "broken"
    RETARGETED = "retargeted"
    REPLACED = "replaced"
    CONFLICT = "conflict"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True, order=True)
class LifecycleKey:
    coordinate: ArtifactCoordinate
    profile: str
    scope: InstallScope

    def __post_init__(self) -> None:
        if (
            not isinstance(self.coordinate, ArtifactCoordinate)
            or not isinstance(self.profile, str)
            or _PROFILE_RE.fullmatch(self.profile) is None
            or self.scope not in {"project", "user"}
        ):
            raise ValueError("lifecycle key is invalid")

    @classmethod
    def from_record(cls, record: InstallationRecord) -> LifecycleKey:
        return cls(record.coordinate, record.profile, record.scope)


@dataclass(frozen=True, slots=True)
class LifecycleSelection:
    scope: InstallScope
    coordinates: tuple[ArtifactCoordinate, ...] = ()
    profiles: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            self.scope not in {"project", "user"}
            or any(not isinstance(item, ArtifactCoordinate) for item in self.coordinates)
            or any(not isinstance(item, str) for item in self.profiles)
        ):
            raise ValueError("lifecycle selection is invalid")
        coordinates = tuple(sorted(set(self.coordinates), key=str))
        profiles = tuple(sorted(set(self.profiles)))
        if (
            len(coordinates) != len(self.coordinates)
            or len(profiles) != len(self.profiles)
            or any(_PROFILE_RE.fullmatch(profile) is None for profile in profiles)
        ):
            raise ValueError("lifecycle selection is invalid")
        object.__setattr__(self, "coordinates", coordinates)
        object.__setattr__(self, "profiles", profiles)


def select_installations(
    state: InstallState, selection: LifecycleSelection
) -> tuple[InstallationRecord, ...]:
    coordinates = set(selection.coordinates)
    profiles = set(selection.profiles)
    return tuple(
        record
        for record in state.installations
        if record.scope == selection.scope
        and (not coordinates or record.coordinate in coordinates)
        and (not profiles or record.profile in profiles)
    )


@dataclass(frozen=True, slots=True)
class LifecycleEffect:
    kind: str
    destination: str
    status: LifecycleStatus
    detail: str = ""

    def __post_init__(self) -> None:
        if (
            not self.kind
            or not self.destination
            or not isinstance(self.status, LifecycleStatus)
            or not isinstance(self.detail, str)
            or "\r" in self.detail
        ):
            raise ValueError("lifecycle effect outcome is invalid")


@dataclass(frozen=True, slots=True)
class LifecycleItem:
    key: LifecycleKey
    status: LifecycleStatus
    effects: tuple[LifecycleEffect, ...] = ()
    detail: str = ""

    def __post_init__(self) -> None:
        if (
            not isinstance(self.key, LifecycleKey)
            or not isinstance(self.status, LifecycleStatus)
            or any(not isinstance(effect, LifecycleEffect) for effect in self.effects)
            or not isinstance(self.detail, str)
            or "\r" in self.detail
        ):
            raise ValueError("lifecycle item outcome is invalid")


@dataclass(frozen=True, slots=True)
class LifecycleOutcome:
    action: LifecycleAction
    selected: int
    items: tuple[LifecycleItem, ...]

    def __post_init__(self) -> None:
        if (
            self.action not in {"status", "check", "update", "uninstall"}
            or not isinstance(self.selected, int)
            or isinstance(self.selected, bool)
            or self.selected < 0
            or self.selected != len(self.items)
            or any(not isinstance(item, LifecycleItem) for item in self.items)
            or len({item.key for item in self.items}) != len(self.items)
        ):
            raise ValueError("lifecycle outcome must contain one terminal item per selection")


def absolute_effect_path(
    effect: EffectProof, scope: InstallScope, location: InstallLocation
) -> str:
    if scope == "user":
        if not posixpath.isabs(effect.destination):
            raise ValueError("user lifecycle destination must be absolute")
        return effect.destination
    if posixpath.isabs(effect.destination):
        raise ValueError("project lifecycle destination must be relative")
    return posixpath.normpath(posixpath.join(location.project_root, effect.destination))


@dataclass(frozen=True, slots=True)
class UninstallOperation:
    effect: EffectProof
    absolute_destination: str
    precondition: PathSnapshot
    mutation: MutationKind
    replacement_content: bytes = b""

    def __post_init__(self) -> None:
        if (
            not isinstance(self.effect, EffectProof)
            or not isinstance(self.precondition, PathSnapshot)
            or not posixpath.isabs(self.absolute_destination)
            or posixpath.normpath(self.absolute_destination) != self.absolute_destination
            or self.absolute_destination == "/"
            or self.precondition.path != self.absolute_destination
            or self.mutation not in {"none", "remove", "write"}
            or (self.mutation != "write" and self.replacement_content)
        ):
            raise ValueError("uninstall operation is invalid")


def reference_owner(record: InstallationRecord) -> str:
    return (
        f"{record.scope}/{record.coordinate.source.value}/{record.artifact.identity.kind}/"
        f"{record.artifact.identity.name}/{record.profile}"
    )


def _snapshot_json(snapshot: PathSnapshot) -> JsonObject:
    return JsonObject(
        (
            ("digest", None if snapshot.digest is None else str(snapshot.digest)),
            ("kind", snapshot.kind),
            ("link_target", snapshot.link_target),
            ("path", snapshot.path),
            ("target_exists", snapshot.target_exists),
        )
    )


def _uninstall_review_value(plan: UninstallPlan) -> JsonObject:
    return JsonObject(
        (
            ("action", "uninstall"),
            ("force", plan.force),
            ("record", install_state_bytes(InstallState(2, (plan.record,))).decode("utf-8")),
            ("state_path", plan.state_path),
            ("state_lock_path", plan.state_lock_path),
            ("state_precondition", _snapshot_json(plan.state_precondition)),
            ("replacement_state_digest", str(plan.replacement_state_digest)),
            ("reference_owner", plan.reference_owner),
            ("object_store_root", plan.object_store_paths.root),
            ("references_file", plan.object_store_paths.references_file),
            (
                "reference_precondition",
                reference_index_bytes(plan.reference_precondition).decode("utf-8"),
            ),
            (
                "reference_replacement",
                reference_index_bytes(plan.reference_replacement).decode("utf-8"),
            ),
            (
                "operations",
                JsonArray(
                    tuple(
                        JsonObject(
                            (
                                ("destination", operation.absolute_destination),
                                ("effect_kind", operation.effect.kind),
                                ("mutation", operation.mutation),
                                ("precondition", _snapshot_json(operation.precondition)),
                                (
                                    "replacement_digest",
                                    str(sha256_bytes(operation.replacement_content)),
                                ),
                            )
                        )
                        for operation in plan.operations
                    )
                ),
            ),
            ("terminal", None if plan.terminal is None else plan.terminal.value),
            ("detail", plan.detail),
        )
    )


@dataclass(frozen=True, slots=True)
class UninstallPlan:
    record: InstallationRecord
    force: bool
    operations: tuple[UninstallOperation, ...]
    state_path: str
    state_lock_path: str
    state_precondition: PathSnapshot
    replacement_state: InstallState
    replacement_state_digest: ObjectDigest
    object_store_paths: ObjectStorePaths
    reference_owner: str
    reference_precondition: ReferenceIndex
    reference_replacement: ReferenceIndex
    terminal: LifecycleStatus | None
    detail: str
    review_digest: ObjectDigest

    def __post_init__(self) -> None:
        parsed_state = (
            parse_install_state(self.state_precondition.content, path=self.state_path)
            if self.state_precondition.kind == "file"
            else None
        )
        current_state = (
            None if parsed_state is None or isinstance(parsed_state, Err) else parsed_state.value
        )
        expected_state = (
            None
            if current_state is None or self.record not in current_state.installations
            else InstallState(
                2,
                tuple(item for item in current_state.installations if item.key != self.record.key),
            )
        )
        project_root = posixpath.dirname(posixpath.dirname(self.state_path))
        destinations_are_scoped = all(
            operation.absolute_destination
            == (
                posixpath.join(project_root, operation.effect.destination)
                if self.record.scope == "project"
                else operation.effect.destination
            )
            for operation in self.operations
        )
        if (
            not isinstance(self.force, bool)
            or not posixpath.isabs(self.state_path)
            or not posixpath.isabs(self.state_lock_path)
            or self.state_precondition.path != self.state_path
            or self.state_lock_path
            != posixpath.join(posixpath.dirname(self.state_path), "state.lock")
            or sha256_bytes(install_state_bytes(self.replacement_state))
            != self.replacement_state_digest
            or expected_state is None
            or expected_state != self.replacement_state
            or self.reference_owner != reference_owner(self.record)
            or self.terminal not in {None, LifecycleStatus.CONFLICT}
            or (self.terminal is None and len(self.operations) != len(self.record.effects))
            or (self.terminal is not None and self.operations)
            or not destinations_are_scoped
            or (
                self.terminal is None
                and any(
                    operation.effect != effect
                    for operation, effect in zip(
                        self.operations,
                        self.record.effects,
                        strict=True,
                    )
                )
            )
            or self.reference_replacement
            != ReferenceIndex(
                1,
                tuple(
                    item
                    for item in self.reference_precondition.references
                    if not (item.kind.value == "installed" and item.owner == self.reference_owner)
                ),
            )
        ):
            raise ValueError("uninstall plan is not exactly bound")
        expected_review = sha256_bytes(canonical_json_bytes(_uninstall_review_value(self)))
        unreviewed = sha256_bytes(b"unreviewed-uninstall-plan")
        if self.review_digest not in {unreviewed, expected_review}:
            raise ValueError("uninstall review digest does not bind the plan")
        if self.review_digest == unreviewed:
            object.__setattr__(self, "review_digest", expected_review)


def uninstall_review_digest(plan: UninstallPlan) -> ObjectDigest:
    return sha256_bytes(canonical_json_bytes(_uninstall_review_value(plan)))


def _update_review_value(plan: UpdatePlan) -> JsonObject:
    nested = (
        str(plan.install_plan.review_digest)
        if plan.install_plan is not None
        else (
            str(plan.uninstall_plan.review_digest)
            if plan.uninstall_plan is not None
            else plan.terminal.status.value
            if plan.terminal is not None
            else "invalid"
        )
    )
    return JsonObject(
        (
            ("action", "update"),
            ("record", install_state_bytes(InstallState(2, (plan.record,))).decode("utf-8")),
            ("prune", plan.prune),
            ("nested_review", nested),
            ("detail", "" if plan.terminal is None else plan.terminal.detail),
        )
    )


@dataclass(frozen=True, slots=True)
class UpdatePlan:
    record: InstallationRecord
    prune: bool
    install_plan: InstallPlan | None
    uninstall_plan: UninstallPlan | None
    terminal: LifecycleItem | None
    review_digest: ObjectDigest

    def __post_init__(self) -> None:
        choices = sum(
            item is not None for item in (self.install_plan, self.uninstall_plan, self.terminal)
        )
        if (
            not isinstance(self.prune, bool)
            or choices != 1
            or (self.uninstall_plan is not None and not self.prune)
            or (
                self.install_plan is not None
                and (
                    self.install_plan.coordinate.source != self.record.coordinate.source
                    or self.install_plan.coordinate.artifact != self.record.coordinate.artifact
                    or self.install_plan.request.profile != self.record.profile
                    or self.install_plan.request.profile_version != self.record.profile_version
                    or self.install_plan.request.scope != self.record.scope
                    or self.install_plan.request.mode != self.record.requested_mode
                    or self.install_plan.request.identity != self.record.artifact.identity
                    or self.install_plan.request.source != self.record.source.alias
                    or self.install_plan.request.memory_mode
                    != (self.record.memory_mode or "prepend")
                )
            )
            or (self.uninstall_plan is not None and self.uninstall_plan.record != self.record)
            or (
                self.terminal is not None
                and self.terminal.key != LifecycleKey.from_record(self.record)
            )
            or self.review_digest
            not in {
                sha256_bytes(b"unreviewed-update-plan"),
                sha256_bytes(canonical_json_bytes(_update_review_value(self))),
            }
        ):
            raise ValueError("update plan is not exactly bound")
        if self.review_digest == sha256_bytes(b"unreviewed-update-plan"):
            object.__setattr__(
                self,
                "review_digest",
                sha256_bytes(canonical_json_bytes(_update_review_value(self))),
            )


def update_review_digest(plan: UpdatePlan) -> ObjectDigest:
    return sha256_bytes(canonical_json_bytes(_update_review_value(plan)))
