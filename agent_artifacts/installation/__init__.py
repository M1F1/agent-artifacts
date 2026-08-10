"""Canonical source-aware installation planning and application."""

from .application import finalize_install, prepare_install
from .model import (
    InstallLocation,
    InstallOutcome,
    InstallPlan,
    InstallRequest,
    InstallStatus,
)

__all__ = [
    "InstallLocation",
    "InstallOutcome",
    "InstallPlan",
    "InstallRequest",
    "InstallStatus",
    "finalize_install",
    "prepare_install",
]
