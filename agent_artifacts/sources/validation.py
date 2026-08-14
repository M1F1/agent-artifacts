"""Pure source-kind-aware validation bridges for acquired candidates."""

from __future__ import annotations

from agent_artifacts.configuration.model import ConfiguredSource, SourceKind
from agent_artifacts.domain.diagnostics import Diagnostic, Severity
from agent_artifacts.domain.identifiers import SourceId
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.protocol.native_schema import parse_source_manifest
from agent_artifacts.protocol.native_tree import SnapshotEntryKind, load_native_source
from agent_artifacts.protocol.registry_schema import parse_registry_manifest
from agent_artifacts.registry_commands.planning import validate_registry_workspace

from .model import (
    SOURCE_INVALID,
    SourceValidationRequest,
    ValidatedSourceCandidate,
    source_instance_id,
)

_REGISTRY_MARKER = "aart-registry.json"
_SOURCE_MARKER = "aart-source.json"


def validate_source_candidate(
    request: SourceValidationRequest,
) -> Result[ValidatedSourceCandidate]:
    """Validate a direct or local source against the native source protocol."""

    loaded = load_native_source(
        request.candidate.snapshot,
        executable_version=request.executable_version,
        available_capabilities=request.available_capabilities,
    )
    if isinstance(loaded, Err):
        return loaded
    # A native source that also publishes a registry marker is a registry being consumed through
    # the direct path.  The value the whole subscription model pins is its identity, and until now
    # no consumer-side gate compared the two documents that declare it — the publisher's own
    # `registry validate --strict --frozen` did, and the one-way adaptation rule says a consumer
    # does not soften a rule the publisher's tooling enforces.
    disagreement = _identity_disagreement(request)
    if disagreement is not None:
        return Err((disagreement,))
    return Ok(
        ValidatedSourceCandidate(
            request.candidate,
            loaded.value.manifest.source_id,
        )
    )


def _error(message: str) -> Err:
    return Err((Diagnostic(SOURCE_INVALID, Severity.ERROR, message),))


def _root_file(request: SourceValidationRequest, path: str) -> Result[bytes]:
    entry = next(
        (item for item in request.candidate.snapshot.entries if str(item.path) == path),
        None,
    )
    if entry is None or entry.kind is not SnapshotEntryKind.FILE:
        return _error(f"registry source requires a regular {path}")
    return Ok(entry.content)


def _identity_disagreement(request: SourceValidationRequest) -> Diagnostic | None:
    """The refusal when the two identity documents disagree, ``None`` when there is nothing to compare.

    "Nothing to compare" is deliberately narrow: only a snapshot that carries both markers as
    regular files, each parsing as its own protocol document, has an agreement to check.  A source
    publishing `aart-source.json` alone is not a registry and is unaffected; a malformed
    `aart-registry.json` is the registry path's refusal to make, not this one's.
    """

    registry_file = _root_file(request, _REGISTRY_MARKER)
    source_file = _root_file(request, _SOURCE_MARKER)
    if isinstance(registry_file, Err) or isinstance(source_file, Err):
        return None
    registry = parse_registry_manifest(registry_file.value)
    source = parse_source_manifest(source_file.value)
    if isinstance(registry, Err) or isinstance(source, Err):
        return None
    if registry.value.registry_id == source.value.source_id:
        return None
    return Diagnostic(
        SOURCE_INVALID,
        Severity.ERROR,
        (
            f"the two identity documents disagree: {_REGISTRY_MARKER} declares registry_id "
            f"{registry.value.registry_id}; {_SOURCE_MARKER} declares source_id "
            f"{source.value.source_id}"
        ),
        remediation=(
            f"in the registry, make source_id in {_SOURCE_MARKER} equal registry_id in "
            f"{_REGISTRY_MARKER}",
            "then re-run `aart registry validate --strict --frozen` there before republishing",
        ),
    )


def _registry_identity(request: SourceValidationRequest) -> Result[SourceId]:
    registry_file = _root_file(request, _REGISTRY_MARKER)
    source_file = _root_file(request, _SOURCE_MARKER)
    if isinstance(registry_file, Err):
        return registry_file
    if isinstance(source_file, Err):
        return source_file
    registry = parse_registry_manifest(registry_file.value)
    source = parse_source_manifest(source_file.value)
    if isinstance(registry, Err):
        return registry
    if isinstance(source, Err):
        return source
    disagreement = _identity_disagreement(request)
    if disagreement is not None:
        return Err((disagreement,))
    return Ok(registry.value.registry_id)


def validate_registry_source_candidate(
    request: SourceValidationRequest,
) -> Result[ValidatedSourceCandidate]:
    """Require a current compiled registry before admitting it as a marketplace source."""

    checked = validate_registry_workspace(
        request.candidate.snapshot,
        executable_version=request.executable_version,
        available_capabilities=request.available_capabilities,
        require_compiled=True,
    )
    if isinstance(checked, Err):
        return checked
    if not checked.value.passed:
        diagnostics = tuple(
            diagnostic for check in checked.value.checks for diagnostic in check.diagnostics
        )
        assert diagnostics
        return Err(diagnostics)
    identity = _registry_identity(request)
    if isinstance(identity, Err):
        return identity
    return Ok(ValidatedSourceCandidate(request.candidate, identity.value))


def validate_configured_source_candidate(
    source: ConfiguredSource,
    request: SourceValidationRequest,
) -> Result[ValidatedSourceCandidate]:
    """Validate one acquired candidate using the protocol selected by its configured kind."""

    if (
        request.candidate.alias != source.alias
        or request.candidate.instance_id != source_instance_id(source)
    ):
        return _error("source validator received a candidate for another configured source")
    if source.kind is SourceKind.REGISTRY_GIT:
        return validate_registry_source_candidate(request)
    return validate_source_candidate(request)
