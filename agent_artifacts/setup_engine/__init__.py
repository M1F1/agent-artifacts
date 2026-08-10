"""Canonical object/trust/policy-bound setup application boundary."""

from .application import (
    execute_setup_queue,
    finalize_setup,
    prepare_setup,
    retryable_plans,
    rollback_setup,
    setup_outcome_event,
)
from .io import LocalSetupAdapter
from .model import (
    CanonicalSetupPlan,
    PayloadStatus,
    SetupExecutionStatus,
    SetupOutcome,
    SetupQueueOutcome,
    SetupRequest,
)

__all__ = [
    "CanonicalSetupPlan",
    "LocalSetupAdapter",
    "PayloadStatus",
    "SetupExecutionStatus",
    "SetupOutcome",
    "SetupQueueOutcome",
    "SetupRequest",
    "execute_setup_queue",
    "finalize_setup",
    "prepare_setup",
    "retryable_plans",
    "rollback_setup",
    "setup_outcome_event",
]
