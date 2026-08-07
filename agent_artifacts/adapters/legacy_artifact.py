"""Incremental metadata adapter from the 0.1.x catalog to native protocol v1 values."""

from __future__ import annotations

import re
from types import MappingProxyType
from typing import Mapping

from agent_artifacts import model as legacy
from agent_artifacts.domain.diagnostics import Diagnostic, Severity
from agent_artifacts.domain.identifiers import ArtifactIdentity
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.protocol.codes import ARTIFACT_INVALID
from agent_artifacts.protocol.native_models import (
    PAYLOAD_FORMAT_BY_TYPE,
    ArtifactManifest,
    CompatibilitySpec,
    InstallEffect,
    InstallMode,
    InstallSpec,
    PayloadSpec,
    SetupReference,
)
from agent_artifacts.protocol.paths import parse_relative_path
from agent_artifacts.protocol.semver import SemVer

_DEFAULT_PROFILES = ("claude", "opencode", "tabnine", "vibe")
_DEFAULT_PLATFORMS = ("darwin", "linux")
_SLUG_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_EFFECTS: Mapping[legacy.ArtifactType, tuple[InstallEffect, ...]] = MappingProxyType(
    {
        "skill": ("copy-tree",),
        "guideline": ("write-file",),
        "mcp": ("merge-json",),
        "hook": ("copy-tree", "merge-json"),
        "memory": ("managed-block",),
    }
)


def _error(message: str) -> Err:
    return Err((Diagnostic(ARTIFACT_INVALID, Severity.ERROR, message),))


def _setup_reference(installer: legacy.SetupInstaller) -> Result[SetupReference]:
    marker = "/setup/"
    recipe = (
        f"setup/{installer.descriptor_path.split(marker, 1)[1]}"
        if marker in installer.descriptor_path
        else installer.descriptor_path
    )
    parsed = parse_relative_path(recipe)
    if isinstance(parsed, Err) or parsed.value.parts[0] != "setup":
        return _error("legacy setup descriptor is not package-relative below setup/")
    return Ok(SetupReference(parsed.value, tuple(sorted(set(installer.platforms)))))


def artifact_manifest_from_legacy(
    artifact: legacy.Artifact,
    version: SemVer,
) -> Result[ArtifactManifest]:
    """Map legacy metadata only; payload materialization remains an importer responsibility."""

    summary = artifact.description.strip()
    if not summary or "\n" in summary or "\r" in summary:
        return _error("legacy artifact requires a non-empty single-line description")
    if _SLUG_RE.fullmatch(artifact.name) is None:
        return _error("legacy artifact name must be a lowercase slug")
    payload_root = parse_relative_path("payload")
    if isinstance(payload_root, Err):
        return payload_root
    profiles = (
        _DEFAULT_PROFILES
        if artifact.compatibility is None
        else tuple(sorted(set(artifact.compatibility.profiles)))
    )
    if not profiles:
        return _error("legacy artifact compatibility must contain at least one profile")
    if any(_SLUG_RE.fullmatch(profile) is None for profile in profiles):
        return _error("legacy artifact compatibility contains an invalid profile")
    setup: SetupReference | None = None
    if artifact.setup is not None:
        parsed_setup = _setup_reference(artifact.setup)
        if isinstance(parsed_setup, Err):
            return parsed_setup
        setup = parsed_setup.value
    modes: tuple[InstallMode, ...] = (
        ("copy", "symlink") if artifact.type in {"skill", "hook"} else ("copy",)
    )
    return Ok(
        ArtifactManifest(
            schema_version=1,
            identity=ArtifactIdentity(artifact.type, artifact.name),
            version=version,
            summary=summary,
            payload=PayloadSpec(payload_root.value, PAYLOAD_FORMAT_BY_TYPE[artifact.type]),
            compatibility=CompatibilitySpec(profiles, _DEFAULT_PLATFORMS),
            install=InstallSpec(("project", "user"), modes, _EFFECTS[artifact.type]),
            setup=setup,
        )
    )
