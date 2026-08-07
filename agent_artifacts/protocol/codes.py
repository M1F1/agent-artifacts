"""Stable diagnostic codes owned by the AART protocol context."""

from __future__ import annotations

from agent_artifacts.domain.diagnostics import DiagnosticCode

JSON_INVALID = DiagnosticCode("protocol-json-invalid")
JSON_DUPLICATE_KEY = DiagnosticCode("protocol-json-duplicate-key")
JSON_FLOAT = DiagnosticCode("protocol-json-float")
JSON_INTEGER_RANGE = DiagnosticCode("protocol-json-integer-range")
JSON_UNICODE = DiagnosticCode("protocol-json-unicode")
JSON_DEPTH = DiagnosticCode("protocol-json-depth")
JSON_STRING_LENGTH = DiagnosticCode("protocol-json-string-length")
SCHEMA_TYPE = DiagnosticCode("protocol-schema-type")
SCHEMA_MISSING_FIELD = DiagnosticCode("protocol-schema-missing-field")
SCHEMA_UNKNOWN_FIELD = DiagnosticCode("protocol-schema-unknown-field")
SCHEMA_EXTENSION_KEY = DiagnosticCode("protocol-schema-extension-key")
PATH_INVALID = DiagnosticCode("protocol-path-invalid")
SEMVER_INVALID = DiagnosticCode("protocol-semver-invalid")
VERSION_BOUNDS_INVALID = DiagnosticCode("protocol-version-bounds-invalid")
DIGEST_INVALID = DiagnosticCode("protocol-digest-invalid")
TREE_INVALID = DiagnosticCode("protocol-tree-invalid")
CAPABILITY_INVALID = DiagnosticCode("protocol-capability-invalid")
SOURCE_INVALID = DiagnosticCode("source-invalid")
SOURCE_INCOMPATIBLE = DiagnosticCode("source-incompatible")
SOURCE_MARKER_MISSING = DiagnosticCode("source-marker-missing")
SOURCE_TREE_INVALID = DiagnosticCode("source-tree-invalid")
ARTIFACT_INVALID = DiagnosticCode("artifact-invalid")
PROVENANCE_INVALID = DiagnosticCode("provenance-invalid")
COLLECTION_INVALID = DiagnosticCode("collection-invalid")
