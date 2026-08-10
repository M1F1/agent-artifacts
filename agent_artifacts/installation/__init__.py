"""Canonical source-aware installation planning and application."""

from .application import finalize_install, prepare_install
from .model import (
    InstallLocation,
    InstallOutcome,
    InstallPlan,
    InstallRequest,
    InstallStatus,
    LinkOperation,
    LinkStatus,
    classify_link,
)

__all__ = [
    "InstallLocation",
    "InstallOutcome",
    "InstallPlan",
    "InstallRequest",
    "InstallStatus",
    "LinkOperation",
    "LinkStatus",
    "classify_link",
    "finalize_install",
    "prepare_install",
]
