"""Advisory artifact runtime requirements and repository-supplied environment health.

Runtime requirements deliberately do not participate in installation compatibility.  AART stores
and installs artifacts; a consuming repository describes the runtime it intends to use and may
interpret this read-only health report according to its own policy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from agent_artifacts.domain.diagnostics import (
    Diagnostic,
    DiagnosticCode,
    Severity,
    SourceLocation,
)
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.protocol.json import JsonArray, JsonObject, JsonValue, parse_json
from agent_artifacts.protocol.native_models import ArtifactManifest
from agent_artifacts.protocol.semver import (
    SemVer,
    VersionBounds,
    parse_semver,
    version_bounds,
    version_bounds_label,
)

RUNTIME_REQUIREMENTS_EXTENSION = "aart.runtime-requirements"
RETIRED_RUNTIME_REQUIREMENTS_EXTENSION = "com.m1f1.runtime-requirements"
RUNTIME_REQUIREMENTS_INVALID = DiagnosticCode("runtime-requirements-invalid")
RUNTIME_REQUIREMENTS_MIGRATION = DiagnosticCode("runtime-requirements-migration-required")
RUNTIME_ENVIRONMENT_INVALID = DiagnosticCode("runtime-environment-invalid")

_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")


class RuntimeRequirementStatus(str, Enum):
    SATISFIED = "satisfied"
    UNSATISFIED = "unsatisfied"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True, order=True)
class RuntimeRequirement:
    id: str
    version: VersionBounds = VersionBounds()
    reason: str | None = None


@dataclass(frozen=True, slots=True, order=True)
class RuntimeCapability:
    id: str
    version: SemVer | None = None


@dataclass(frozen=True, slots=True)
class RuntimeEnvironment:
    schema_version: int
    capabilities: tuple[RuntimeCapability, ...]
    name: str | None = None


@dataclass(frozen=True, slots=True)
class RuntimeRequirementCheck:
    requirement: RuntimeRequirement
    status: RuntimeRequirementStatus
    observed: RuntimeCapability | None
    detail: str


def _error(
    code: DiagnosticCode,
    message: str,
    *,
    path: str,
    pointer: str | None = None,
    remediation: tuple[str, ...] = (),
) -> Err:
    return Err(
        (
            Diagnostic(
                code,
                Severity.ERROR,
                message,
                SourceLocation(path=path, pointer=pointer),
                remediation=remediation,
            ),
        )
    )


def _fields(
    value: JsonValue,
    *,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
    label: str,
    code: DiagnosticCode,
    path: str,
    pointer: str,
) -> Result[dict[str, JsonValue]]:
    if not isinstance(value, JsonObject):
        return _error(code, f"{label} must be an object", path=path, pointer=pointer)
    fields = dict(value.entries)
    missing = sorted(required - fields.keys())
    unknown = sorted(fields.keys() - required - optional)
    if missing:
        return _error(
            code,
            f"{label} is missing required field {missing[0]!r}",
            path=path,
            pointer=pointer,
        )
    if unknown:
        return _error(
            code,
            f"{label} has unknown field {unknown[0]!r}",
            path=path,
            pointer=pointer,
        )
    return Ok(fields)


def _schema_version(
    value: JsonValue,
    *,
    label: str,
    code: DiagnosticCode,
    path: str,
    pointer: str,
) -> Result[int]:
    if not isinstance(value, int) or isinstance(value, bool):
        return _error(code, f"{label} must be an integer", path=path, pointer=pointer)
    if value != 1:
        return _error(code, f"unsupported {label} {value}", path=path, pointer=pointer)
    return Ok(value)


def _identifier(
    value: JsonValue,
    *,
    label: str,
    code: DiagnosticCode,
    path: str,
    pointer: str,
) -> Result[str]:
    if not isinstance(value, str) or _IDENTIFIER_RE.fullmatch(value) is None:
        return _error(
            code,
            f"{label} must be a lowercase dotted or dashed identifier",
            path=path,
            pointer=pointer,
        )
    return Ok(value)


def _single_line(
    value: JsonValue,
    *,
    label: str,
    code: DiagnosticCode,
    path: str,
    pointer: str,
) -> Result[str]:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\n" in value
        or "\r" in value
    ):
        return _error(
            code,
            f"{label} must be a non-empty single-line string",
            path=path,
            pointer=pointer,
        )
    return Ok(value)


def _bounds(
    value: JsonValue,
    *,
    code: DiagnosticCode,
    path: str,
    pointer: str,
) -> Result[VersionBounds]:
    parsed_fields = _fields(
        value,
        required=frozenset(),
        optional=frozenset({"min_inclusive", "max_exclusive"}),
        label="runtime requirement version",
        code=code,
        path=path,
        pointer=pointer,
    )
    if isinstance(parsed_fields, Err):
        return parsed_fields
    if not parsed_fields.value:
        return _error(
            code,
            "runtime requirement version must declare at least one bound",
            path=path,
            pointer=pointer,
        )
    minimum = None
    maximum = None
    for field, target in (("min_inclusive", "minimum"), ("max_exclusive", "maximum")):
        raw = parsed_fields.value.get(field)
        if raw is None:
            continue
        if not isinstance(raw, str):
            return _error(
                code,
                f"runtime requirement {field} must be a SemVer string",
                path=path,
                pointer=f"{pointer}/{field}",
            )
        parsed = parse_semver(raw, location=SourceLocation(path=path, pointer=f"{pointer}/{field}"))
        if isinstance(parsed, Err):
            return _error(
                code,
                f"runtime requirement {field} must be valid SemVer: {raw!r}",
                path=path,
                pointer=f"{pointer}/{field}",
            )
        if target == "minimum":
            minimum = parsed.value
        else:
            maximum = parsed.value
    checked = version_bounds(minimum, maximum)
    if isinstance(checked, Err):
        return _error(
            code,
            "runtime requirement minimum must precede maximum",
            path=path,
            pointer=pointer,
        )
    return checked


def parse_runtime_requirements(
    manifest: ArtifactManifest,
    *,
    path: str = "artifact.json",
) -> Result[tuple[RuntimeRequirement, ...]]:
    """Parse the optional namespaced extension while leaving native v1 compatibility unchanged."""

    extensions = dict(manifest.extensions)
    if RETIRED_RUNTIME_REQUIREMENTS_EXTENSION in extensions:
        return _error(
            RUNTIME_REQUIREMENTS_MIGRATION,
            f"runtime requirements extension {RETIRED_RUNTIME_REQUIREMENTS_EXTENSION!r} is retired",
            path=path,
            pointer=f"/{RETIRED_RUNTIME_REQUIREMENTS_EXTENSION}",
            remediation=(
                f"rename the extension to {RUNTIME_REQUIREMENTS_EXTENSION!r}; only the current key is accepted",
            ),
        )
    extension = extensions.get(RUNTIME_REQUIREMENTS_EXTENSION)
    if extension is None:
        return Ok(())
    root_pointer = f"/{RUNTIME_REQUIREMENTS_EXTENSION}"
    root = _fields(
        extension,
        required=frozenset({"schema_version", "requirements"}),
        label="runtime requirements extension",
        code=RUNTIME_REQUIREMENTS_INVALID,
        path=path,
        pointer=root_pointer,
    )
    if isinstance(root, Err):
        return root
    schema = _schema_version(
        root.value["schema_version"],
        label="runtime requirements schema_version",
        code=RUNTIME_REQUIREMENTS_INVALID,
        path=path,
        pointer=f"{root_pointer}/schema_version",
    )
    if isinstance(schema, Err):
        return schema
    raw_requirements = root.value["requirements"]
    if not isinstance(raw_requirements, JsonArray) or not raw_requirements.items:
        return _error(
            RUNTIME_REQUIREMENTS_INVALID,
            "runtime requirements must be a non-empty array",
            path=path,
            pointer=f"{root_pointer}/requirements",
        )
    requirements: list[RuntimeRequirement] = []
    for index, raw in enumerate(raw_requirements.items):
        pointer = f"{root_pointer}/requirements/{index}"
        item = _fields(
            raw,
            required=frozenset({"id"}),
            optional=frozenset({"version", "reason"}),
            label="runtime requirement",
            code=RUNTIME_REQUIREMENTS_INVALID,
            path=path,
            pointer=pointer,
        )
        if isinstance(item, Err):
            return item
        identifier = _identifier(
            item.value["id"],
            label="runtime requirement id",
            code=RUNTIME_REQUIREMENTS_INVALID,
            path=path,
            pointer=f"{pointer}/id",
        )
        if isinstance(identifier, Err):
            return identifier
        bounds = VersionBounds()
        if "version" in item.value:
            parsed_bounds = _bounds(
                item.value["version"],
                code=RUNTIME_REQUIREMENTS_INVALID,
                path=path,
                pointer=f"{pointer}/version",
            )
            if isinstance(parsed_bounds, Err):
                return parsed_bounds
            bounds = parsed_bounds.value
        reason = None
        if "reason" in item.value:
            parsed_reason = _single_line(
                item.value["reason"],
                label="runtime requirement reason",
                code=RUNTIME_REQUIREMENTS_INVALID,
                path=path,
                pointer=f"{pointer}/reason",
            )
            if isinstance(parsed_reason, Err):
                return parsed_reason
            reason = parsed_reason.value
        requirements.append(RuntimeRequirement(identifier.value, bounds, reason))
    identifiers = tuple(item.id for item in requirements)
    if len(set(identifiers)) != len(identifiers):
        return _error(
            RUNTIME_REQUIREMENTS_INVALID,
            "runtime requirement ids must be unique",
            path=path,
            pointer=f"{root_pointer}/requirements",
        )
    return Ok(tuple(sorted(requirements)))


def parse_runtime_environment(
    data: bytes | str,
    *,
    path: str = "runtime-environment.json",
) -> Result[RuntimeEnvironment]:
    """Parse a repository-owned runtime inventory without inspecting the current process."""

    parsed = parse_json(data, location=SourceLocation(path=path))
    if isinstance(parsed, Err):
        return parsed
    root = _fields(
        parsed.value,
        required=frozenset({"schema_version", "capabilities"}),
        optional=frozenset({"name"}),
        label="runtime environment",
        code=RUNTIME_ENVIRONMENT_INVALID,
        path=path,
        pointer="",
    )
    if isinstance(root, Err):
        return root
    schema = _schema_version(
        root.value["schema_version"],
        label="runtime environment schema_version",
        code=RUNTIME_ENVIRONMENT_INVALID,
        path=path,
        pointer="/schema_version",
    )
    if isinstance(schema, Err):
        return schema
    name = None
    if "name" in root.value:
        parsed_name = _single_line(
            root.value["name"],
            label="runtime environment name",
            code=RUNTIME_ENVIRONMENT_INVALID,
            path=path,
            pointer="/name",
        )
        if isinstance(parsed_name, Err):
            return parsed_name
        name = parsed_name.value
    raw_capabilities = root.value["capabilities"]
    if not isinstance(raw_capabilities, JsonArray):
        return _error(
            RUNTIME_ENVIRONMENT_INVALID,
            "runtime environment capabilities must be an array",
            path=path,
            pointer="/capabilities",
        )
    capabilities: list[RuntimeCapability] = []
    for index, raw in enumerate(raw_capabilities.items):
        pointer = f"/capabilities/{index}"
        item = _fields(
            raw,
            required=frozenset({"id"}),
            optional=frozenset({"version"}),
            label="runtime capability",
            code=RUNTIME_ENVIRONMENT_INVALID,
            path=path,
            pointer=pointer,
        )
        if isinstance(item, Err):
            return item
        identifier = _identifier(
            item.value["id"],
            label="runtime capability id",
            code=RUNTIME_ENVIRONMENT_INVALID,
            path=path,
            pointer=f"{pointer}/id",
        )
        if isinstance(identifier, Err):
            return identifier
        version = None
        if "version" in item.value:
            raw_version = item.value["version"]
            if not isinstance(raw_version, str):
                return _error(
                    RUNTIME_ENVIRONMENT_INVALID,
                    "runtime capability version must be a SemVer string",
                    path=path,
                    pointer=f"{pointer}/version",
                )
            parsed_version = parse_semver(
                raw_version,
                location=SourceLocation(path=path, pointer=f"{pointer}/version"),
            )
            if isinstance(parsed_version, Err):
                return _error(
                    RUNTIME_ENVIRONMENT_INVALID,
                    f"runtime capability version must be valid SemVer: {raw_version!r}",
                    path=path,
                    pointer=f"{pointer}/version",
                )
            version = parsed_version.value
        capabilities.append(RuntimeCapability(identifier.value, version))
    identifiers = tuple(item.id for item in capabilities)
    if len(set(identifiers)) != len(identifiers):
        return _error(
            RUNTIME_ENVIRONMENT_INVALID,
            "runtime capability ids must be unique",
            path=path,
            pointer="/capabilities",
        )
    return Ok(RuntimeEnvironment(schema.value, tuple(sorted(capabilities)), name))


def evaluate_runtime_requirements(
    requirements: tuple[RuntimeRequirement, ...],
    environment: RuntimeEnvironment,
) -> tuple[RuntimeRequirementCheck, ...]:
    """Compare declarations to an inventory; missing evidence is unknown, never a denial."""

    available = {item.id: item for item in environment.capabilities}
    checks = []
    for requirement in requirements:
        observed = available.get(requirement.id)
        expected = version_bounds_label(requirement.version)
        if observed is None:
            status = RuntimeRequirementStatus.UNKNOWN
            detail = "capability is not described by the supplied environment"
        elif requirement.version == VersionBounds():
            status = RuntimeRequirementStatus.SATISFIED
            detail = "capability is declared by the supplied environment"
        elif observed.version is None:
            status = RuntimeRequirementStatus.UNKNOWN
            detail = f"environment does not declare a version; expected {expected}"
        elif requirement.version.allows(observed.version):
            status = RuntimeRequirementStatus.SATISFIED
            detail = f"observed {observed.version}; expected {expected}"
        else:
            status = RuntimeRequirementStatus.UNSATISFIED
            detail = f"observed {observed.version}; expected {expected}"
        checks.append(RuntimeRequirementCheck(requirement, status, observed, detail))
    return tuple(checks)


def runtime_requirement_to_data(requirement: RuntimeRequirement) -> dict[str, object]:
    bounds: dict[str, str] = {}
    if requirement.version.min_inclusive is not None:
        bounds["min_inclusive"] = str(requirement.version.min_inclusive)
    if requirement.version.max_exclusive is not None:
        bounds["max_exclusive"] = str(requirement.version.max_exclusive)
    data: dict[str, object] = {"id": requirement.id}
    if bounds:
        data["version"] = bounds
    if requirement.reason is not None:
        data["reason"] = requirement.reason
    return data


def runtime_capability_to_data(capability: RuntimeCapability) -> dict[str, object]:
    data: dict[str, object] = {"id": capability.id}
    if capability.version is not None:
        data["version"] = str(capability.version)
    return data


def runtime_check_to_data(check: RuntimeRequirementCheck) -> dict[str, object]:
    data = runtime_requirement_to_data(check.requirement)
    data.update(
        {
            "status": check.status.value,
            "observed": (
                None if check.observed is None else runtime_capability_to_data(check.observed)
            ),
            "detail": check.detail,
        }
    )
    return data


__all__ = [
    "RUNTIME_ENVIRONMENT_INVALID",
    "RUNTIME_REQUIREMENTS_EXTENSION",
    "RETIRED_RUNTIME_REQUIREMENTS_EXTENSION",
    "RUNTIME_REQUIREMENTS_INVALID",
    "RUNTIME_REQUIREMENTS_MIGRATION",
    "RuntimeCapability",
    "RuntimeEnvironment",
    "RuntimeRequirement",
    "RuntimeRequirementCheck",
    "RuntimeRequirementStatus",
    "evaluate_runtime_requirements",
    "parse_runtime_environment",
    "parse_runtime_requirements",
    "runtime_capability_to_data",
    "runtime_check_to_data",
    "runtime_requirement_to_data",
]
