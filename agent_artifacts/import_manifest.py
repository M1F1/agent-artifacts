"""Manifest-mode parser for batch upstream import."""

from __future__ import annotations

import json
import os
import posixpath
from dataclasses import dataclass, field
from typing import Mapping, Optional, Tuple, cast

from .model import ArtifactType, Err, Ok, Result

MANIFEST_PATHS = ("agent-artifacts.import.json", ".agent-artifacts/import.json")


@dataclass(frozen=True, slots=True)
class ImportManifestArtifact:
    type: ArtifactType
    name: str
    path: str
    description: str = ""
    bundle: Optional[str] = None


@dataclass(frozen=True, slots=True)
class ImportManifestBundle:
    name: str
    description: str = ""
    includes: Mapping[str, Tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ImportManifest:
    artifacts: Tuple[ImportManifestArtifact, ...]
    bundles: Tuple[ImportManifestBundle, ...] = ()


_ARTIFACT_TYPES = {"skill", "guideline", "mcp", "hook", "memory"}


def find_manifest(root: str) -> Optional[str]:
    for rel in MANIFEST_PATHS:
        path = os.path.join(root, *rel.split("/"))
        if os.path.isfile(path):
            return path
    return None


def parse_import_manifest(text: str) -> Result:
    try:
        raw = json.loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        return Err(f"import manifest: invalid JSON ({exc})", code=2)
    if not isinstance(raw, dict):
        return Err("import manifest: expected a JSON object", code=2)
    if raw.get("version") != 1:
        return Err("import manifest: version must be 1", code=2)

    artifacts_raw = raw.get("artifacts")
    if not isinstance(artifacts_raw, list):
        return Err("import manifest: artifacts must be a list", code=2)

    errors = []
    artifacts = []
    seen = set()
    for i, item in enumerate(artifacts_raw):
        label = f"import manifest: artifacts[{i}]"
        if not isinstance(item, dict):
            errors.append(f"{label} must be an object")
            continue
        artifact_type = item.get("type")
        name = item.get("name")
        path = item.get("path")
        if artifact_type not in _ARTIFACT_TYPES:
            errors.append(f"{label}.type must be one of {', '.join(sorted(_ARTIFACT_TYPES))}")
            continue
        if not _non_empty_str(name):
            errors.append(f"{label}.name must be a non-empty string")
            continue
        if not _non_empty_str(path):
            errors.append(f"{label}.path must be a non-empty string")
            continue
        artifact_type = cast(ArtifactType, artifact_type)
        assert isinstance(name, str)
        assert isinstance(path, str)
        norm = _normalise_rel(path)
        if norm is None:
            errors.append(f"{label}.path must be a relative path inside the scan root")
            continue
        key = (artifact_type, name)
        if key in seen:
            errors.append(f"import manifest: duplicate artifact {artifact_type}/{name}")
            continue
        seen.add(key)
        description = item.get("description", "")
        bundle = item.get("bundle")
        if not isinstance(description, str):
            errors.append(f"{label}.description must be a string when present")
            continue
        if bundle is not None and not _non_empty_str(bundle):
            errors.append(f"{label}.bundle must be a non-empty string when present")
            continue
        artifacts.append(
            ImportManifestArtifact(
                type=artifact_type,
                name=name,
                path=norm,
                description=description,
                bundle=bundle,
            )
        )

    bundles_res = _parse_bundles(raw.get("bundles", ()), seen)
    if isinstance(bundles_res, Err):
        errors.append(bundles_res.reason)

    if errors:
        return Err("; ".join(errors), code=2)
    bundles = bundles_res.value if isinstance(bundles_res, Ok) else ()
    return Ok(ImportManifest(artifacts=tuple(artifacts), bundles=bundles))


def _parse_bundles(raw_bundles, known_keys: set) -> Result:
    if raw_bundles in (None, ()):
        return Ok(())
    if not isinstance(raw_bundles, list):
        return Err("import manifest: bundles must be a list", code=2)

    errors = []
    bundles = []
    names = set()
    for i, item in enumerate(raw_bundles):
        label = f"import manifest: bundles[{i}]"
        if not isinstance(item, dict):
            errors.append(f"{label} must be an object")
            continue
        name = item.get("name")
        if not _non_empty_str(name):
            errors.append(f"{label}.name must be a non-empty string")
            continue
        assert isinstance(name, str)
        if name in names:
            errors.append(f"import manifest: duplicate bundle {name!r}")
            continue
        names.add(name)
        description = item.get("description", "")
        if not isinstance(description, str):
            errors.append(f"{label}.description must be a string when present")
            continue
        includes_raw = item.get("includes", {})
        if not isinstance(includes_raw, dict):
            errors.append(f"{label}.includes must be an object when present")
            continue
        includes = {}
        for section, values in includes_raw.items():
            artifact_type = _section_to_type(section)
            if artifact_type is None:
                errors.append(f"{label}.includes has unknown section {section!r}")
                continue
            if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
                errors.append(f"{label}.includes.{section} must be a list of strings")
                continue
            missing = [v for v in values if (artifact_type, v) not in known_keys]
            if missing:
                errors.append(
                    f"{label}.includes.{section} references unknown artifact(s) "
                    + ", ".join(missing)
                )
                continue
            includes[section] = tuple(values)
        bundles.append(ImportManifestBundle(name=name, description=description, includes=includes))
    if errors:
        return Err("; ".join(errors), code=2)
    return Ok(tuple(bundles))


def _section_to_type(section: str) -> Optional[ArtifactType]:
    mapping: dict[str, ArtifactType] = {
        "skill": "skill",
        "skills": "skill",
        "guideline": "guideline",
        "guidelines": "guideline",
        "mcp": "mcp",
        "mcps": "mcp",
        "hook": "hook",
        "hooks": "hook",
        "memory": "memory",
        "memories": "memory",
    }
    return mapping.get(section)


def _normalise_rel(path: str) -> Optional[str]:
    if path.startswith("/"):
        return None
    norm = posixpath.normpath(path)
    if norm == ".":
        return ""
    if norm == ".." or norm.startswith("../"):
        return None
    return norm


def _non_empty_str(value) -> bool:
    return isinstance(value, str) and value != ""
