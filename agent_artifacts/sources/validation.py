"""Pure native-source validation bridge for acquired candidates."""

from __future__ import annotations

from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.protocol.native_tree import load_native_source

from .model import SourceValidationRequest, ValidatedSourceCandidate


def validate_source_candidate(
    request: SourceValidationRequest,
) -> Result[ValidatedSourceCandidate]:
    loaded = load_native_source(
        request.candidate.snapshot,
        executable_version=request.executable_version,
        available_capabilities=request.available_capabilities,
    )
    if isinstance(loaded, Err):
        return loaded
    return Ok(
        ValidatedSourceCandidate(
            request.candidate,
            loaded.value.manifest.source_id,
        )
    )
