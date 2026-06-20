"""Profile loader — WP-8. Built-ins overlaid by ``<project>/.agent-artifacts/profiles.json``."""

from __future__ import annotations

from typing import Mapping, Optional

from ..model import Profile

_TODO = "WP-8: not implemented"


def load_profiles(project: Optional[str] = None) -> Mapping[str, Profile]:
    """Built-in profiles merged with the project's override file (pure merge over data)."""
    raise NotImplementedError(_TODO)
