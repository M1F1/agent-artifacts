"""Canonical source-aware installation lifecycle boundary."""

from .application import (
    check_installations,
    finalize_uninstall,
    finalize_update,
    prepare_uninstall,
    prepare_update,
    reconcile_installations,
    status_installations,
)
from .io import LocalLifecycleAdapter
from .model import (
    LifecycleEffect,
    LifecycleItem,
    LifecycleKey,
    LifecycleOutcome,
    LifecycleSelection,
    LifecycleStatus,
    UninstallOperation,
    UninstallPlan,
    UpdatePlan,
)

__all__ = [
    "LifecycleEffect",
    "LifecycleItem",
    "LifecycleKey",
    "LifecycleOutcome",
    "LifecycleSelection",
    "LifecycleStatus",
    "LocalLifecycleAdapter",
    "UninstallOperation",
    "UninstallPlan",
    "UpdatePlan",
    "check_installations",
    "finalize_uninstall",
    "finalize_update",
    "prepare_uninstall",
    "prepare_update",
    "reconcile_installations",
    "status_installations",
]
