"""Pure catalog-subscription transformations for consumer manifests and updates."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import List, Optional, Tuple

from .model import CatalogSubscription, ManifestEntry, Request


@dataclass(frozen=True, slots=True)
class SubscriptionGroup:
    """Installed entries sharing one catalog subscription, in stable input order."""

    subscription: Optional[CatalogSubscription]
    entries: Tuple[ManifestEntry, ...]


def subscription_from_request(request: Request, source_root: str) -> CatalogSubscription:
    """Derive the durable subscription represented by a resolved request/source pair."""
    if request.source_dir is not None:
        return CatalogSubscription(kind="local", location=source_root)
    if request.repo is not None:
        return CatalogSubscription(
            kind="github",
            location=request.repo,
            ref=request.version or "main",
        )
    return CatalogSubscription(kind="package", location=source_root)


def request_for_subscription(request: Request, subscription: CatalogSubscription) -> Request:
    """Return ``request`` retargeted to a recorded subscription without stale source fields."""
    if subscription.kind == "package":
        return replace(request, source_dir=None, repo=None, version=None)
    if subscription.kind == "local":
        return replace(
            request,
            source_dir=subscription.location,
            repo=None,
            version=None,
        )
    return replace(
        request,
        source_dir=None,
        repo=subscription.location,
        version=None if subscription.ref == "main" else subscription.ref,
    )


def has_source_override(request: Request) -> bool:
    """Whether update should intentionally ignore recorded subscriptions."""
    return request.source_dir is not None or request.repo is not None or request.version is not None


def group_entries_by_subscription(
    entries: Tuple[ManifestEntry, ...],
) -> Tuple[SubscriptionGroup, ...]:
    """Partition entries by subscription while preserving group and entry order."""
    keys: List[Optional[CatalogSubscription]] = []
    grouped: dict[Optional[CatalogSubscription], List[ManifestEntry]] = {}
    for entry in entries:
        key = entry.subscription
        if key not in grouped:
            keys.append(key)
            grouped[key] = []
        grouped[key].append(entry)
    return tuple(SubscriptionGroup(key, tuple(grouped[key])) for key in keys)
