"""Frozen values for setup bound to an installed canonical artifact object."""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from enum import Enum

from agent_artifacts.domain.identifiers import ArtifactCoordinate, ObjectDigest
from agent_artifacts.domain.result import Ok, Result
from agent_artifacts.install_state.model import InstallationRecord, InstallScope, InstallState
from agent_artifacts.install_state.schema import install_state_bytes
from agent_artifacts.installation.model import PathSnapshot
from agent_artifacts.model import SetupManualReference, SetupStateRecord
from agent_artifacts.model import SetupPlan as LegacySetupPlan
from agent_artifacts.protocol.capabilities import Capability
from agent_artifacts.protocol.hashing import json_digest, sha256_bytes
from agent_artifacts.protocol.json import JsonArray, JsonObject
from agent_artifacts.protocol.paths import SafeRelativePath
from agent_artifacts.store.model import ObjectCandidate, ObjectStorePaths

_PROFILE_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_SETUP_REF_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,255}$")
_TRUST = frozenset(
    {"unverified", "local", "direct-source", "registry-reviewed", "company-reviewed"}
)


class PayloadStatus(str, Enum):
    INSTALLED = "installed"


class SetupExecutionStatus(str, Enum):
    CONFIGURED = "configured"
    ALREADY_CONFIGURED = "already-configured"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"
    UNSUPPORTED = "unsupported"
    PREREQUISITE_MISSING = "prerequisite-missing"
    APPLY_FAILED_ROLLED_BACK = "apply-failed-rolled-back"
    ROLLBACK_INCOMPLETE = "rollback-incomplete"
    VERIFICATION_FAILED = "verification-failed"
    CONFLICTED = "conflicted"
    FAILED = "failed"
    ROLLED_BACK = "rolled-back"


_SUCCESS = frozenset({SetupExecutionStatus.CONFIGURED, SetupExecutionStatus.ALREADY_CONFIGURED})


@dataclass(frozen=True, slots=True)
class SetupRequest:
    coordinate: ArtifactCoordinate
    profile: str
    scope: InstallScope
    authorize_untrusted_source: bool = False
    authorize_custom_entrypoint: bool = False
    platform: str = "darwin"

    def __post_init__(self) -> None:
        if (
            not isinstance(self.coordinate, ArtifactCoordinate)
            or self.coordinate.version is not None
            or _PROFILE_RE.fullmatch(self.profile) is None
            or self.scope not in {"project", "user"}
            or not isinstance(self.authorize_untrusted_source, bool)
            or not isinstance(self.authorize_custom_entrypoint, bool)
            or not isinstance(self.platform, str)
            or not self.platform
            or self.platform != self.platform.strip()
            or "\r" in self.platform
            or "\n" in self.platform
        ):
            raise ValueError("canonical setup request is invalid")


def _installation_digest(record: InstallationRecord) -> ObjectDigest:
    return sha256_bytes(install_state_bytes(InstallState(2, (record,))))


def _snapshot_value(snapshot: PathSnapshot) -> JsonObject:
    return JsonObject(
        (
            ("path", snapshot.path),
            ("kind", snapshot.kind),
            ("digest", None if snapshot.digest is None else str(snapshot.digest)),
        )
    )


def _capability_value(capabilities: tuple[Capability, ...], plan_hash: str) -> JsonObject:
    return JsonObject(
        (
            ("capabilities", JsonArray(tuple(str(item) for item in capabilities))),
            ("effect_plan_digest", f"sha256:{plan_hash}"),
        )
    )


def setup_review_value(plan: CanonicalSetupPlan) -> JsonObject:
    return JsonObject(
        (
            ("schema_version", 1),
            ("coordinate", str(plan.request.coordinate)),
            ("profile", plan.request.profile),
            ("scope", plan.request.scope),
            ("platform", plan.request.platform),
            ("authorize_untrusted_source", plan.request.authorize_untrusted_source),
            ("authorize_custom_entrypoint", plan.request.authorize_custom_entrypoint),
            ("installation_digest", str(_installation_digest(plan.installation))),
            ("trust", plan.trust),
            ("trust_evidence_digest", str(plan.trust_evidence_digest)),
            ("policy_digest", str(plan.policy_digest)),
            ("object_digest", str(plan.object_digest)),
            ("object_root", plan.object_root),
            ("recipe_path", str(plan.recipe_path)),
            ("recipe_digest", str(plan.recipe_digest)),
            (
                "custom_entrypoint_path",
                None if plan.custom_entrypoint_path is None else str(plan.custom_entrypoint_path),
            ),
            (
                "custom_entrypoint_digest",
                (
                    None
                    if plan.custom_entrypoint_digest is None
                    else str(plan.custom_entrypoint_digest)
                ),
            ),
            (
                "capabilities",
                JsonArray(tuple(str(item) for item in plan.capabilities)),
            ),
            ("capability_plan_digest", str(plan.capability_plan_digest)),
            ("effect_plan_digest", f"sha256:{plan.legacy_plan.plan_hash}"),
            ("target_root", plan.legacy_plan.target_root),
            ("home_root", plan.legacy_plan.home_root),
            ("run_root", plan.legacy_plan.run_root),
            ("setup_state_ref", plan.setup_state_ref),
            ("setup_state_path", plan.setup_state_path),
            ("setup_state_precondition", _snapshot_value(plan.setup_state_precondition)),
            ("setup_reference_owner", plan.setup_reference_owner),
            (
                "setup_reference_precondition",
                JsonArray(tuple(str(item) for item in plan.setup_reference_precondition)),
            ),
        )
    )


@dataclass(frozen=True, slots=True)
class CanonicalSetupPlan:
    request: SetupRequest
    installation: InstallationRecord
    install_state_path: str
    install_state_lock_path: str
    trust: str
    trust_evidence_digest: ObjectDigest
    policy_digest: ObjectDigest
    object_store_paths: ObjectStorePaths
    object_candidate: ObjectCandidate
    object_root: str
    object_digest: ObjectDigest
    recipe_path: SafeRelativePath
    recipe_digest: ObjectDigest
    custom_entrypoint_path: SafeRelativePath | None
    custom_entrypoint_digest: ObjectDigest | None
    capabilities: tuple[Capability, ...]
    capability_plan_digest: ObjectDigest
    legacy_plan: LegacySetupPlan
    setup_state_ref: str
    setup_state_path: str
    setup_state_precondition: PathSnapshot
    previous_record: SetupStateRecord | None
    setup_reference_owner: str
    setup_reference_precondition: tuple[ObjectDigest, ...]
    review_digest: ObjectDigest

    def __post_init__(self) -> None:
        expected_root = posixpath.join(
            self.object_store_paths.objects,
            self.object_digest.value[:2],
            self.object_digest.value[2:],
        )
        expected_state_path = posixpath.join(
            self.object_store_paths.root,
            "state",
            "setup",
            f"{self.setup_state_ref}.json",
        )
        capabilities = tuple(sorted(set(self.capabilities)))
        expected_capability = json_digest(
            _capability_value(capabilities, self.legacy_plan.plan_hash)
        )
        expected_review = json_digest(setup_review_value(self))
        placeholder = sha256_bytes(b"unreviewed-setup-plan")
        item = self.legacy_plan.item
        expected_custom_path = (
            None
            if item.installer.custom_entrypoint is None
            else SafeRelativePath((*self.recipe_path.parts[:-1], item.installer.custom_entrypoint))
        )
        if (
            self.installation.coordinate != self.request.coordinate
            or self.installation.profile != self.request.profile
            or self.installation.scope != self.request.scope
            or self.installation.artifact.object_digest != self.object_digest
            or self.object_candidate.digest != self.object_digest
            or self.object_root != expected_root
            or self.legacy_plan.run_root != self.object_store_paths.root
            or self.recipe_digest.value != item.installer.descriptor_hash
            or item.installer.descriptor_path != str(self.recipe_path)
            or item.source_root != self.object_root
            or item.source_label != str(self.installation.coordinate.source)
            or item.artifact_type != self.installation.artifact.identity.kind
            or item.artifact_name != self.installation.artifact.identity.name
            or item.profile != self.installation.profile
            or item.scope != self.installation.scope
            or (self.custom_entrypoint_path is None) != (self.custom_entrypoint_digest is None)
            or self.custom_entrypoint_path != expected_custom_path
            or (
                self.custom_entrypoint_digest is not None
                and self.custom_entrypoint_digest.value != (item.installer.custom_hash or "")
            )
            or capabilities != self.capabilities
            or self.capability_plan_digest != expected_capability
            or self.trust not in _TRUST
            or _SETUP_REF_RE.fullmatch(self.setup_state_ref) is None
            or self.setup_reference_owner != f"setup/{self.setup_state_ref}"
            or not posixpath.isabs(self.install_state_path)
            or not posixpath.isabs(self.install_state_lock_path)
            or not posixpath.isabs(self.setup_state_path)
            or self.setup_state_path != expected_state_path
            or self.setup_state_precondition.path != self.setup_state_path
            or tuple(sorted(set(self.setup_reference_precondition), key=str))
            != self.setup_reference_precondition
            or self.review_digest not in {placeholder, expected_review}
        ):
            raise ValueError("canonical setup plan is invalid")


@dataclass(frozen=True, slots=True)
class CanonicalSetupAttempt:
    """One planning attempt: its typed result plus any manual route already proven valid."""

    result: Result[CanonicalSetupPlan]
    manual: SetupManualReference | None = None

    def __post_init__(self) -> None:
        if isinstance(self.result, Ok) and self.manual is None:
            raise ValueError("a planned setup attempt must carry its manual route")


@dataclass(frozen=True, slots=True)
class SetupOutcome:
    coordinate: ArtifactCoordinate
    profile: str
    scope: InstallScope
    payload_status: PayloadStatus
    setup_status: SetupExecutionStatus
    detail: str
    review_digest: ObjectDigest
    setup_state_ref: str
    state_written: bool
    record: SetupStateRecord | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.coordinate, ArtifactCoordinate)
            or _PROFILE_RE.fullmatch(self.profile) is None
            or self.scope not in {"project", "user"}
            or not isinstance(self.payload_status, PayloadStatus)
            or not isinstance(self.setup_status, SetupExecutionStatus)
            or not isinstance(self.detail, str)
            or "\r" in self.detail
            or "\n" in self.detail
            or _SETUP_REF_RE.fullmatch(self.setup_state_ref) is None
            or not isinstance(self.state_written, bool)
        ):
            raise ValueError("canonical setup outcome is invalid")

    @property
    def successful(self) -> bool:
        return self.setup_status in _SUCCESS

    @property
    def key(self) -> tuple[str, str, str]:
        return (str(self.coordinate), self.profile, self.scope)


@dataclass(frozen=True, slots=True)
class SetupQueueOutcome:
    items: tuple[SetupOutcome, ...]

    def __post_init__(self) -> None:
        keys = tuple(item.key for item in self.items)
        if len(set(keys)) != len(keys):
            raise ValueError("setup queue outcomes must have unique item identities")

    @property
    def payload_installed(self) -> int:
        return sum(item.payload_status is PayloadStatus.INSTALLED for item in self.items)

    @property
    def configured(self) -> int:
        return sum(item.successful for item in self.items)

    @property
    def incomplete(self) -> int:
        return len(self.items) - self.configured
