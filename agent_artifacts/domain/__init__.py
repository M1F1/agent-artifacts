"""IO-free AART 1.0 domain kernel.

Bounded contexts import the smallest owning module directly; these re-exports support interfaces
and adapters that intentionally work across the shared kernel boundary.
"""

from .diagnostics import Diagnostic, DiagnosticCode, Severity, SourceLocation
from .identifiers import (
    ArtifactCoordinate,
    ArtifactIdentity,
    ObjectDigest,
    SourceAlias,
    SourceId,
    SourceOrigin,
)
from .outcomes import OperationOutcome, TerminalItem, TerminalStatus
from .result import Err, Ok, Result

__all__ = [
    "ArtifactCoordinate",
    "ArtifactIdentity",
    "Diagnostic",
    "DiagnosticCode",
    "Err",
    "ObjectDigest",
    "Ok",
    "OperationOutcome",
    "Result",
    "Severity",
    "SourceAlias",
    "SourceId",
    "SourceLocation",
    "SourceOrigin",
    "TerminalItem",
    "TerminalStatus",
]
