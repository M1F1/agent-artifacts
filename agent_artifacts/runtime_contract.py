"""Published executable protocol contract shared by runtime composition roots."""

from __future__ import annotations

from agent_artifacts.protocol.capabilities import Capability
from agent_artifacts.protocol.semver import SemVer

EXECUTABLE_VERSION = SemVer(2, 1, 0)
EXECUTABLE_CAPABILITIES = tuple(
    Capability(value)
    for value in (
        "artifact-manifest-v1",
        "keychain-secret",
        "lockfile-v1",
        "managed-file",
        "open-browser",
        "registry-entry-v1",
    )
)

__all__ = ["EXECUTABLE_CAPABILITIES", "EXECUTABLE_VERSION"]
