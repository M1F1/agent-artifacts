"""Local adapter combining canonical install, lifecycle, and setup persistence ports."""

from __future__ import annotations

from agent_artifacts.lifecycle.io import LocalLifecycleAdapter
from agent_artifacts.setup_engine.io import LocalSetupAdapter

from .application import ConsumerPorts


class LocalConsumerAdapter(LocalLifecycleAdapter, LocalSetupAdapter, ConsumerPorts):
    """One no-follow transactional adapter for the complete consumer workflow."""


__all__ = ["LocalConsumerAdapter"]
