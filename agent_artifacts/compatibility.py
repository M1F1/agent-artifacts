"""Per-artifact profile compatibility helpers.

Compatibility is source metadata: an artifact may optionally declare the profiles it is
intended for. The command layer decides whether an incompatible target is a hard usage error
or a broad-selection skip; this module only parses and answers the pure domain question.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Tuple

from .model import Artifact, Compatibility, CompatibilityDecision, Err, Ok, Result

INCOMPATIBLE_PROFILE = "incompatible-profile"
_KEY = "compatibility"
_PROFILES = "profiles"
_FRONTMATTER_KEY = "compatibility.profiles"
_PROFILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def parse_profile_allow_list(value: object) -> Result:
    """Parse and validate a compatibility profile allow-list.

    JSON descriptors pass a list of strings. Markdown/frontmatter descriptors pass a string,
    usually ``"claude, tabnine"`` and optionally bracketed as ``"[claude, tabnine]"``.
    Duplicate names are removed while preserving first-seen order.
    """
    raw_items: Tuple[object, ...]
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("[") and text.endswith("]"):
            text = text[1:-1].strip()
        raw_items = tuple(part.strip() for part in text.split(","))
    elif isinstance(value, list):
        raw_items = tuple(value)
    elif isinstance(value, tuple):
        raw_items = value
    else:
        return Err("compatibility.profiles must be a list of profile names")

    profiles = []
    seen = set()
    for item in raw_items:
        if not isinstance(item, str):
            return Err("compatibility.profiles must contain only strings")
        profile = item.strip()
        if not profile:
            continue
        if not _PROFILE_RE.match(profile):
            return Err(f"invalid profile name in compatibility.profiles: {profile!r}")
        if profile not in seen:
            seen.add(profile)
            profiles.append(profile)

    if not profiles:
        return Err("compatibility.profiles must not be empty")
    return Ok(tuple(profiles))


def compatibility_from_json(data: Mapping[str, object], label: str) -> Result:
    """Extract optional ``compatibility.profiles`` from a JSON artifact descriptor."""
    if _KEY not in data:
        return Ok(None)
    raw = data[_KEY]
    if not isinstance(raw, Mapping):
        return Err(f"{label}: compatibility must be an object")
    if _PROFILES not in raw:
        return Err(f"{label}: compatibility.profiles is required when compatibility is set")
    parsed = parse_profile_allow_list(raw[_PROFILES])
    if isinstance(parsed, Err):
        return Err(f"{label}: {parsed.reason}")
    return Ok(Compatibility(profiles=parsed.value))


def compatibility_from_frontmatter(fields: Mapping[str, str], label: str) -> Result:
    """Extract optional ``compatibility.profiles`` from flat Markdown frontmatter."""
    if _FRONTMATTER_KEY not in fields:
        return Ok(None)
    parsed = parse_profile_allow_list(fields[_FRONTMATTER_KEY])
    if isinstance(parsed, Err):
        return Err(f"{label}: {parsed.reason}")
    return Ok(Compatibility(profiles=parsed.value))


def check_profile_compatibility(
    artifact: Artifact, profile_name: str
) -> CompatibilityDecision:
    """Return whether ``artifact`` may target ``profile_name``."""
    if artifact.compatibility is None:
        return CompatibilityDecision(ok=True)
    allowed = artifact.compatibility.profiles
    if profile_name in allowed:
        return CompatibilityDecision(ok=True, allowed_profiles=allowed)
    return CompatibilityDecision(
        ok=False,
        reason=INCOMPATIBLE_PROFILE,
        allowed_profiles=allowed,
    )


def skipped_target_to_dict(skipped) -> dict:
    """Serialize a SkippedTarget-like object for command JSON output."""
    out = {
        "artifact": skipped.artifact,
        "type": skipped.type,
        "profile": skipped.profile,
        "reason": skipped.reason,
    }
    if skipped.allowed_profiles:
        out["allowed_profiles"] = list(skipped.allowed_profiles)
    return out
