"""Frozen source-aware consumer requests, reviewed baskets, and terminal outcomes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Mapping, TypeAlias

from agent_artifacts.configuration.policy import EffectiveConfiguration
from agent_artifacts.domain.identifiers import ArtifactCoordinate, ObjectDigest
from agent_artifacts.install_state.model import InstallScope
from agent_artifacts.installation.model import InstallLocation, InstallMode, InstallPlan
from agent_artifacts.lifecycle.model import LifecycleItem, UninstallPlan, UpdatePlan
from agent_artifacts.marketplace.model import MarketplaceCatalog
from agent_artifacts.model import SetupManualReference
from agent_artifacts.profiles.model import Profile
from agent_artifacts.protocol.hashing import json_digest, sha256_bytes
from agent_artifacts.protocol.json import JsonArray, JsonObject
from agent_artifacts.security.aggregation import ArtifactSecurityEvidence
from agent_artifacts.setup_engine.model import CanonicalSetupPlan
from agent_artifacts.store.model import ObjectStorePaths

ConsumerAction = Literal["install", "update", "uninstall", "status", "check"]
ConsumerPlan: TypeAlias = InstallPlan | UpdatePlan | UninstallPlan | LifecycleItem
_PROFILE_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_TERMINAL_STATUSES = frozenset(
    {
        "changed",
        "current",
        "update-available",
        "removed",
        "removed-upstream",
        "source-unavailable",
        "missing",
        "drifted",
        "broken",
        "retargeted",
        "replaced",
        "conflict",
        "failed",
        "skipped",
    }
)


@dataclass(frozen=True, slots=True)
class ConsumerActionRequest:
    action: ConsumerAction
    coordinates: tuple[ArtifactCoordinate, ...]
    profiles: tuple[str, ...]
    scope: InstallScope = "project"
    mode: InstallMode = "copy"
    platform: str = "darwin"
    force: bool = False
    offline: bool = False
    prune: bool = False

    def __post_init__(self) -> None:
        coordinates = tuple(sorted(set(self.coordinates), key=str))
        profiles = tuple(sorted(set(self.profiles)))
        if (
            self.action not in {"install", "update", "uninstall", "status", "check"}
            or coordinates != self.coordinates
            or profiles != self.profiles
            or not profiles
            or any(_PROFILE_RE.fullmatch(profile) is None for profile in profiles)
            or self.scope not in {"project", "user"}
            or self.mode not in {"copy", "symlink"}
            or not self.platform
            or "\r" in self.platform
            or "\n" in self.platform
            or not isinstance(self.force, bool)
            or not isinstance(self.offline, bool)
            or not isinstance(self.prune, bool)
            or (self.action == "install" and any(item.version is None for item in coordinates))
            or (self.action in {"install", "update", "uninstall"} and not coordinates)
        ):
            raise ValueError("consumer action request is invalid")


@dataclass(frozen=True, slots=True)
class ConsumerContext:
    catalog: MarketplaceCatalog
    effective: EffectiveConfiguration
    profiles: Mapping[str, Profile]
    location: InstallLocation
    store_paths: ObjectStorePaths
    security: tuple[ArtifactSecurityEvidence, ...] = ()

    def __post_init__(self) -> None:
        if (
            any(
                not isinstance(name, str) or name != profile.name
                for name, profile in self.profiles.items()
            )
            or any(not isinstance(item, ArtifactSecurityEvidence) for item in self.security)
            or len({item.coordinate for item in self.security}) != len(self.security)
        ):
            raise ValueError("consumer context is invalid")


@dataclass(frozen=True, slots=True)
class ConsumerReviewEffect:
    kind: str
    destination: str
    actual_mode: InstallMode

    def __post_init__(self) -> None:
        if (
            not self.kind
            or not self.destination
            or "\r" in self.destination
            or self.actual_mode not in {"copy", "symlink"}
        ):
            raise ValueError("consumer review effect is invalid")


@dataclass(frozen=True, slots=True)
class ConsumerSetupDeclaration:
    recipe: str
    platforms: tuple[str, ...]
    capabilities: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            not self.recipe
            or tuple(sorted(set(self.platforms))) != self.platforms
            or tuple(sorted(set(self.capabilities))) != self.capabilities
        ):
            raise ValueError("consumer setup declaration is invalid")


@dataclass(frozen=True, slots=True)
class ConsumerReviewItem:
    key: str
    coordinate: ArtifactCoordinate
    profile: str
    scope: InstallScope
    action: ConsumerAction
    source_revision: str
    trust: str
    manifest_digest: str
    payload_digest: str
    object_digest: str
    security_status: str
    installation_risk: str
    effects: tuple[ConsumerReviewEffect, ...]
    setup: ConsumerSetupDeclaration | None
    plan_digest: ObjectDigest
    plan: ConsumerPlan

    def __post_init__(self) -> None:
        expected_key = f"{self.coordinate}#{self.profile}/{self.scope}"
        if (
            self.key != expected_key
            or _PROFILE_RE.fullmatch(self.profile) is None
            or self.scope not in {"project", "user"}
            or self.action not in {"install", "update", "uninstall", "status", "check"}
            or not self.source_revision
            or not self.trust
            or not self.manifest_digest
            or not self.payload_digest
            or not self.object_digest
            or not self.security_status
            or not self.installation_risk
            or not isinstance(self.plan_digest, ObjectDigest)
        ):
            raise ValueError("consumer review item is invalid")


def _review_value(review: ConsumerReview) -> JsonObject:
    request = review.request
    return JsonObject(
        (
            ("action", request.action),
            ("scope", request.scope),
            ("mode", request.mode),
            ("platform", request.platform),
            ("force", request.force),
            ("offline", request.offline),
            ("prune", request.prune),
            (
                "items",
                JsonArray(
                    tuple(
                        JsonObject(
                            (
                                ("key", item.key),
                                ("plan_digest", str(item.plan_digest)),
                                ("trust", item.trust),
                                ("security_status", item.security_status),
                                ("installation_risk", item.installation_risk),
                                ("manifest_digest", item.manifest_digest),
                                ("payload_digest", item.payload_digest),
                                ("object_digest", item.object_digest),
                                (
                                    "destinations",
                                    JsonArray(tuple(effect.destination for effect in item.effects)),
                                ),
                                (
                                    "actual_modes",
                                    JsonArray(tuple(effect.actual_mode for effect in item.effects)),
                                ),
                                (
                                    "setup_recipe",
                                    None if item.setup is None else item.setup.recipe,
                                ),
                            )
                        )
                        for item in review.items
                    )
                ),
            ),
        )
    )


@dataclass(frozen=True, slots=True)
class ConsumerReview:
    request: ConsumerActionRequest
    items: tuple[ConsumerReviewItem, ...]
    review_digest: ObjectDigest

    def __post_init__(self) -> None:
        placeholder = sha256_bytes(b"unreviewed-consumer-action")
        expected = json_digest(_review_value(self))
        if (
            len({item.key for item in self.items}) != len(self.items)
            or any(item.action != self.request.action for item in self.items)
            or self.review_digest not in {placeholder, expected}
        ):
            raise ValueError("consumer Review does not bind its exact item plans")
        if self.review_digest == placeholder:
            object.__setattr__(self, "review_digest", expected)


@dataclass(frozen=True, slots=True)
class ConsumerTerminalItem:
    key: str
    status: str
    detail: str = ""
    setup_status: str = "not-required"

    def __post_init__(self) -> None:
        if (
            not self.key
            or self.status not in _TERMINAL_STATUSES
            or "\r" in self.detail
            or self.setup_status not in {"not-required", "pending", "skipped"}
        ):
            raise ValueError("consumer terminal item is invalid")


@dataclass(frozen=True, slots=True)
class ConsumerOutcome:
    action: ConsumerAction
    items: tuple[ConsumerTerminalItem, ...]
    offline_last_known_good: bool = False

    def __post_init__(self) -> None:
        if (
            self.action not in {"install", "update", "uninstall", "status", "check"}
            or len({item.key for item in self.items}) != len(self.items)
            or not isinstance(self.offline_last_known_good, bool)
        ):
            raise ValueError("consumer outcome is invalid")

    @property
    def selected(self) -> int:
        return len(self.items)

    @property
    def counts(self) -> tuple[tuple[str, int], ...]:
        statuses = tuple(sorted({item.status for item in self.items}))
        return tuple(
            (status, sum(item.status == status for item in self.items)) for status in statuses
        )

    @property
    def session_status(self) -> str:
        failed = sum(item.status in {"failed", "conflict"} for item in self.items)
        changed = sum(item.status in {"changed", "removed"} for item in self.items)
        if not self.items or (not failed and not changed):
            return "no-op"
        if failed == len(self.items):
            return "failed"
        if failed:
            return "partial"
        return "succeeded"


@dataclass(frozen=True, slots=True)
class ConsumerSetupFailure:
    key: str
    detail: str
    manual: SetupManualReference | None = None

    def __post_init__(self) -> None:
        if not self.key or not self.detail or "\r" in self.detail:
            raise ValueError("consumer setup planning failure is invalid")


@dataclass(frozen=True, slots=True)
class ConsumerSetupQueue:
    plans: tuple[CanonicalSetupPlan, ...]
    failures: tuple[ConsumerSetupFailure, ...] = ()

    def __post_init__(self) -> None:
        plan_keys = tuple(
            (str(plan.request.coordinate), plan.request.profile, plan.request.scope)
            for plan in self.plans
        )
        if len(set(plan_keys)) != len(plan_keys) or len(
            {item.key for item in self.failures}
        ) != len(self.failures):
            raise ValueError("consumer setup queue identities must be unique")


def consumer_review_value(review: ConsumerReview) -> JsonObject:
    """The exact canonical value the Review digest is computed over.

    Agents need to see what they are about to authorize, and it must be the same bytes the digest
    binds — not a parallel rendering that could drift from it.
    """

    return _review_value(review)


def render_consumer_review(review: ConsumerReview) -> tuple[str, ...]:
    request = review.request
    lines: tuple[str, ...] = (
        "Review consumer action",
        f"  Action: {request.action.title()}",
        f"  Scope: {request.scope}",
        f"  Requested mode: {request.mode}",
        f"  Selected targets: {len(review.items)}",
        f"  Review digest: {review.review_digest}",
    )
    for item in review.items:
        modes = ", ".join(sorted({effect.actual_mode for effect in item.effects})) or "none"
        lines += (
            f"  - {item.key}",
            f"    source revision: {item.source_revision}",
            f"    trust/security: {item.trust}; {item.installation_risk} ({item.security_status})",
            f"    digests: manifest={item.manifest_digest}; object={item.object_digest}",
            f"    actual modes: {modes}",
        )
        lines += tuple(f"    destination: {effect.destination}" for effect in item.effects)
        if item.setup is not None:
            lines += (
                f"    setup queue: {item.setup.recipe} "
                f"[{', '.join(item.setup.capabilities) or 'no declared capabilities'}]",
            )
    return lines


def render_consumer_outcome(outcome: ConsumerOutcome) -> tuple[str, ...]:
    counts = ", ".join(f"{name}={count}" for name, count in outcome.counts) or "none=0"
    lines: tuple[str, ...] = (
        f"{outcome.action.title()} outcome: {outcome.session_status}",
        f"  Selected: {outcome.selected}; {counts}",
    )
    if outcome.offline_last_known_good:
        lines += ("  Source mode: offline last-known-good snapshot and cached objects.",)
    lines += tuple(
        f"  - {item.key}: {item.status}"
        + (f" — {item.detail}" if item.detail else "")
        + (f" · setup {item.setup_status}" if item.setup_status != "not-required" else "")
        for item in outcome.items
    )
    return lines


__all__ = [
    "ConsumerAction",
    "ConsumerActionRequest",
    "ConsumerContext",
    "ConsumerOutcome",
    "ConsumerPlan",
    "ConsumerReview",
    "ConsumerReviewEffect",
    "ConsumerReviewItem",
    "ConsumerSetupDeclaration",
    "ConsumerSetupFailure",
    "ConsumerSetupQueue",
    "ConsumerTerminalItem",
    "consumer_review_value",
    "render_consumer_outcome",
    "render_consumer_review",
]
