"""Pure immutable object-envelope, reference, and garbage-collection values."""

from __future__ import annotations

import base64
import binascii
import posixpath
import re
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from agent_artifacts.domain.diagnostics import (
    Diagnostic,
    DiagnosticCode,
    Severity,
    sort_diagnostics,
)
from agent_artifacts.domain.identifiers import ObjectDigest
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.protocol.hashing import sha256_bytes
from agent_artifacts.protocol.json import (
    JsonArray,
    JsonObject,
    JsonValue,
    canonical_json_bytes,
    parse_json,
)
from agent_artifacts.protocol.native_tree import SnapshotEntry, SnapshotEntryKind
from agent_artifacts.protocol.paths import parse_relative_path

STORE_INVALID = DiagnosticCode("store-invalid")
DIGEST_MISMATCH = DiagnosticCode("digest-mismatch")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_FILES = 10_000
_MAX_ENTRIES = 20_000
_MAX_FILE_BYTES = 10 * 1024 * 1024
_MAX_TOTAL_BYTES = 100 * 1024 * 1024
_MAX_DEPTH = 64
_MAX_ENVELOPE_BYTES = 150 * 1024 * 1024
_MAX_REFERENCES = 100_000
_OWNER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")


def _error(message: str, *, code: DiagnosticCode = STORE_INVALID) -> Err:
    return Err((Diagnostic(code, Severity.ERROR, message),))


def _valid_digest(digest: ObjectDigest) -> bool:
    return digest.algorithm == "sha256" and _DIGEST_RE.fullmatch(digest.value) is not None


@dataclass(frozen=True, slots=True)
class ObjectStorePaths:
    root: str
    objects: str
    state: str
    references_file: str
    lock_directory: str
    temporary_root: str
    quarantine: str

    def __post_init__(self) -> None:
        if self.root == "/":
            raise ValueError("object store root cannot be the filesystem root")
        for path in (
            self.root,
            self.objects,
            self.state,
            self.references_file,
            self.lock_directory,
            self.temporary_root,
            self.quarantine,
        ):
            if not posixpath.isabs(path) or posixpath.normpath(path) != path:
                raise ValueError("object store paths must be normalized and absolute")
        expected = (
            posixpath.join(self.root, "objects", "sha256"),
            posixpath.join(self.root, "state"),
            posixpath.join(self.root, "state", "object-references.json"),
            posixpath.join(self.root, "locks", "store.lock"),
            posixpath.join(self.root, "tmp", "objects"),
            posixpath.join(self.root, "objects", "quarantine"),
        )
        actual = (
            self.objects,
            self.state,
            self.references_file,
            self.lock_directory,
            self.temporary_root,
            self.quarantine,
        )
        if actual != expected:
            raise ValueError("object store paths must use the managed layout")


def object_store_paths(data_root: str) -> ObjectStorePaths:
    if not posixpath.isabs(data_root) or posixpath.normpath(data_root) != data_root:
        raise ValueError("object store data root must be normalized and absolute")
    return ObjectStorePaths(
        data_root,
        posixpath.join(data_root, "objects", "sha256"),
        posixpath.join(data_root, "state"),
        posixpath.join(data_root, "state", "object-references.json"),
        posixpath.join(data_root, "locks", "store.lock"),
        posixpath.join(data_root, "tmp", "objects"),
        posixpath.join(data_root, "objects", "quarantine"),
    )


def _normalized_entries(entries: Iterable[SnapshotEntry]) -> Result[tuple[SnapshotEntry, ...]]:
    explicit: dict[str, SnapshotEntry] = {}
    file_count = 0
    total_bytes = 0
    for entry_count, entry in enumerate(entries, start=1):
        if entry_count > _MAX_ENTRIES:
            return _error("object exceeds maximum entry count")
        raw = str(entry.path)
        parsed = parse_relative_path(raw)
        if isinstance(parsed, Err) or parsed.value != entry.path or raw in explicit:
            return _error(f"object entry path is invalid or duplicated: {raw!r}")
        if len(entry.path.parts) > _MAX_DEPTH:
            return _error(f"object entry exceeds maximum depth: {raw}")
        if entry.kind is SnapshotEntryKind.DIRECTORY:
            if entry.content or entry.executable:
                return _error(f"object directory has file metadata: {raw}")
        elif entry.kind is SnapshotEntryKind.FILE:
            if not isinstance(entry.content, bytes) or not isinstance(entry.executable, bool):
                return _error(f"object file metadata is invalid: {raw}")
            file_count += 1
            total_bytes += len(entry.content)
            if file_count > _MAX_FILES:
                return _error("object exceeds maximum file count")
            if len(entry.content) > _MAX_FILE_BYTES:
                return _error(f"object file exceeds maximum size: {raw}")
            if total_bytes > _MAX_TOTAL_BYTES:
                return _error("object exceeds maximum total size")
        else:
            return _error(f"object contains forbidden {entry.kind.value}: {raw}")
        explicit[raw] = entry
    if not explicit:
        return _error("object must contain at least one entry")
    normalized = dict(explicit)
    for _raw, entry in tuple(explicit.items()):
        for length in range(1, len(entry.path.parts)):
            directory = "/".join(entry.path.parts[:length])
            existing = normalized.get(directory)
            if existing is not None and existing.kind is not SnapshotEntryKind.DIRECTORY:
                return _error(f"object file conflicts with required directory: {directory}")
            if existing is None:
                parsed = parse_relative_path(directory)
                assert isinstance(parsed, Ok)
                normalized[directory] = SnapshotEntry(
                    parsed.value,
                    SnapshotEntryKind.DIRECTORY,
                )
    return Ok(tuple(sorted(normalized.values(), key=lambda item: str(item.path))))


def _entry_json(entry: SnapshotEntry) -> JsonObject:
    values: list[tuple[str, JsonValue]] = [
        ("executable", entry.executable),
        ("kind", entry.kind.value),
        ("path", str(entry.path)),
    ]
    if entry.kind is SnapshotEntryKind.FILE:
        values.append(("content_base64", base64.b64encode(entry.content).decode("ascii")))
    return JsonObject(tuple(values))


def _canonical_object_bytes(entries: tuple[SnapshotEntry, ...]) -> bytes:
    return canonical_json_bytes(
        JsonObject(
            (
                ("entries", JsonArray(tuple(_entry_json(entry) for entry in entries))),
                ("schema_version", 1),
            )
        )
    )


@dataclass(frozen=True, slots=True)
class ObjectCandidate:
    digest: ObjectDigest
    entries: tuple[SnapshotEntry, ...]
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        normalized = _normalized_entries(self.entries)
        if (
            not _valid_digest(self.digest)
            or not isinstance(self.canonical_bytes, bytes)
            or len(self.canonical_bytes) > _MAX_ENVELOPE_BYTES
            or sha256_bytes(self.canonical_bytes) != self.digest
            or not isinstance(normalized, Ok)
            or normalized.value != self.entries
            or _canonical_object_bytes(normalized.value) != self.canonical_bytes
        ):
            raise ValueError("object candidate must bind the exact safe canonical tree and bytes")


def make_object_candidate(
    entries: Iterable[SnapshotEntry],
    *,
    expected_digest: ObjectDigest | None = None,
) -> Result[ObjectCandidate]:
    normalized = _normalized_entries(entries)
    if isinstance(normalized, Err):
        return normalized
    canonical = _canonical_object_bytes(normalized.value)
    if len(canonical) > _MAX_ENVELOPE_BYTES:
        return _error("canonical object envelope exceeds maximum size")
    digest = sha256_bytes(canonical)
    if expected_digest is not None and (
        not _valid_digest(expected_digest) or digest != expected_digest
    ):
        return _error("object bytes do not match expected digest", code=DIGEST_MISMATCH)
    return Ok(ObjectCandidate(digest, normalized.value, canonical))


def _object_fields(value: JsonObject, required: frozenset[str]) -> Result[dict[str, JsonValue]]:
    fields = dict(value.entries)
    if frozenset(fields) != required:
        return _error("object envelope fields are invalid")
    return Ok(fields)


def parse_object_candidate(
    data: bytes,
    expected_digest: ObjectDigest | None = None,
) -> Result[ObjectCandidate]:
    if not isinstance(data, bytes) or len(data) > _MAX_ENVELOPE_BYTES:
        return _error("object envelope must be bounded bytes")
    parsed = parse_json(data, max_string_length=15 * 1024 * 1024)
    if isinstance(parsed, Err) or not isinstance(parsed.value, JsonObject):
        return _error("object envelope is not strict JSON")
    root = _object_fields(parsed.value, frozenset({"schema_version", "entries"}))
    if isinstance(root, Err):
        return root
    if root.value["schema_version"] != 1 or isinstance(root.value["schema_version"], bool):
        return _error("object envelope schema version is unsupported")
    raw_entries = root.value["entries"]
    if not isinstance(raw_entries, JsonArray):
        return _error("object envelope entries must be an array")
    if len(raw_entries.items) > _MAX_ENTRIES:
        return _error("object envelope exceeds maximum entry count")
    entries: list[SnapshotEntry] = []
    for value in raw_entries.items:
        if not isinstance(value, JsonObject):
            return _error("object envelope entry must be an object")
        fields = dict(value.entries)
        kind = fields.get("kind")
        expected_fields = (
            frozenset({"path", "kind", "executable", "content_base64"})
            if kind == "file"
            else frozenset({"path", "kind", "executable"})
        )
        if frozenset(fields) != expected_fields:
            return _error("object envelope entry fields are invalid")
        raw_path = fields["path"]
        executable = fields["executable"]
        if not isinstance(raw_path, str) or not isinstance(executable, bool):
            return _error("object envelope entry types are invalid")
        path = parse_relative_path(raw_path)
        if isinstance(path, Err):
            return _error(f"object envelope path is unsafe: {raw_path!r}")
        if kind == "directory":
            if executable:
                return _error(f"object envelope directory is executable: {raw_path}")
            entries.append(SnapshotEntry(path.value, SnapshotEntryKind.DIRECTORY))
            continue
        raw_content = fields.get("content_base64")
        if kind != "file" or not isinstance(raw_content, str):
            return _error("object envelope entry kind is invalid")
        try:
            content = base64.b64decode(raw_content, validate=True)
        except (binascii.Error, ValueError):
            return _error(f"object envelope content is not canonical base64: {raw_path}")
        entries.append(SnapshotEntry(path.value, SnapshotEntryKind.FILE, content, executable))
    candidate = make_object_candidate(entries, expected_digest=expected_digest)
    if isinstance(candidate, Err):
        return candidate
    if candidate.value.canonical_bytes != data:
        return _error("object envelope is not in canonical representation")
    return candidate


@dataclass(frozen=True, slots=True)
class StoredObject:
    candidate: ObjectCandidate
    root: str

    def __post_init__(self) -> None:
        if not posixpath.isabs(self.root) or posixpath.normpath(self.root) != self.root:
            raise ValueError("stored object root must be normalized and absolute")


@dataclass(frozen=True, slots=True)
class ObjectReadRequest:
    paths: ObjectStorePaths
    digest: ObjectDigest

    def __post_init__(self) -> None:
        if not _valid_digest(self.digest):
            raise ValueError("object read digest must be canonical SHA-256")


@dataclass(frozen=True, slots=True)
class ObjectPublishCommand:
    paths: ObjectStorePaths
    candidate: ObjectCandidate


@dataclass(frozen=True, slots=True)
class ObjectPublishReceipt:
    stored: StoredObject
    created: bool
    repaired: bool


class ObjectStatusKind(str, Enum):
    MISSING = "missing"
    VERIFIED = "verified"
    DEGRADED = "degraded"


@dataclass(frozen=True, slots=True)
class ObjectStatus:
    kind: ObjectStatusKind
    digest: ObjectDigest
    stored: StoredObject | None = None
    diagnostics: tuple[Diagnostic, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ObjectStatusKind) or not _valid_digest(self.digest):
            raise ValueError("object status digest must be canonical SHA-256")
        if self.kind is ObjectStatusKind.VERIFIED and self.stored is None:
            raise ValueError("verified object status requires a stored object")
        if self.kind is not ObjectStatusKind.VERIFIED and self.stored is not None:
            raise ValueError("non-verified object status cannot contain a stored object")
        if self.stored is not None and self.stored.candidate.digest != self.digest:
            raise ValueError("object status digest must match its stored object")
        object.__setattr__(self, "diagnostics", sort_diagnostics(self.diagnostics))


@dataclass(frozen=True, slots=True)
class ObjectDeleteCommand:
    paths: ObjectStorePaths
    digest: ObjectDigest

    def __post_init__(self) -> None:
        if not _valid_digest(self.digest):
            raise ValueError("object delete digest must be canonical SHA-256")


class ReferenceKind(str, Enum):
    INSTALLED = "installed"
    SETUP = "setup"
    SOURCE_CURRENT = "source-current"
    RETAINED = "retained"
    ROLLBACK = "rollback"
    TRANSACTION = "transaction"


@dataclass(frozen=True, slots=True, order=True)
class ObjectReference:
    kind: ReferenceKind
    owner: str
    digest: ObjectDigest

    def __post_init__(self) -> None:
        if (
            not isinstance(self.kind, ReferenceKind)
            or _OWNER_RE.fullmatch(self.owner) is None
            or not _valid_digest(self.digest)
        ):
            raise ValueError("object reference identity is invalid")


@dataclass(frozen=True, slots=True)
class ReferenceIndex:
    schema_version: int
    references: tuple[ObjectReference, ...]

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("object reference schema version must be 1")
        ordered = tuple(sorted(self.references))
        if len(ordered) > _MAX_REFERENCES or len(set(ordered)) != len(ordered):
            raise ValueError("object references must be unique")
        object.__setattr__(self, "references", ordered)


@dataclass(frozen=True, slots=True)
class ReferenceReadRequest:
    paths: ObjectStorePaths


@dataclass(frozen=True, slots=True)
class ReferenceWriteCommand:
    paths: ObjectStorePaths
    index: ReferenceIndex


@dataclass(frozen=True, slots=True)
class StoreLockRequest:
    lock_directory: str
    timeout_seconds: float = 30.0
    stale_after_seconds: int = 300

    def __post_init__(self) -> None:
        if (
            not posixpath.isabs(self.lock_directory)
            or posixpath.normpath(self.lock_directory) != self.lock_directory
            or not isinstance(self.timeout_seconds, (int, float))
            or isinstance(self.timeout_seconds, bool)
            or self.timeout_seconds <= 0
            or not isinstance(self.stale_after_seconds, int)
            or isinstance(self.stale_after_seconds, bool)
            or self.stale_after_seconds <= 0
        ):
            raise ValueError("store lock request is invalid")


@dataclass(frozen=True, slots=True)
class StoreLockLease:
    lock_directory: str
    token: str

    def __post_init__(self) -> None:
        if not posixpath.isabs(self.lock_directory) or not self.token:
            raise ValueError("store lock lease is invalid")


@dataclass(frozen=True, slots=True)
class ObjectInventory:
    digests: tuple[ObjectDigest, ...]
    diagnostics: tuple[Diagnostic, ...] = ()

    def __post_init__(self) -> None:
        ordered = tuple(sorted(set(self.digests), key=str))
        if len(ordered) != len(self.digests) or any(not _valid_digest(item) for item in ordered):
            raise ValueError("object inventory digests must be unique canonical SHA-256")
        object.__setattr__(self, "digests", ordered)
        object.__setattr__(self, "diagnostics", sort_diagnostics(self.diagnostics))


@dataclass(frozen=True, slots=True)
class GcRequest:
    paths: ObjectStorePaths
    execute: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.execute, bool):
            raise ValueError("garbage collection execute flag must be boolean")


@dataclass(frozen=True, slots=True)
class GcPlan:
    referenced: tuple[ObjectDigest, ...]
    candidates: tuple[ObjectDigest, ...]
    diagnostics: tuple[Diagnostic, ...] = ()

    def __post_init__(self) -> None:
        referenced = tuple(sorted(set(self.referenced), key=str))
        candidates = tuple(sorted(set(self.candidates), key=str))
        if (
            len(referenced) != len(self.referenced)
            or len(candidates) != len(self.candidates)
            or set(referenced) & set(candidates)
            or any(not _valid_digest(item) for item in (*referenced, *candidates))
        ):
            raise ValueError("garbage collection plan must partition canonical digests")
        object.__setattr__(self, "referenced", referenced)
        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(self, "diagnostics", sort_diagnostics(self.diagnostics))


@dataclass(frozen=True, slots=True)
class GcOutcome:
    plan: GcPlan
    executed: bool
    deleted: tuple[ObjectDigest, ...] = ()

    def __post_init__(self) -> None:
        deleted = tuple(sorted(set(self.deleted), key=str))
        if (
            not isinstance(self.executed, bool)
            or len(deleted) != len(self.deleted)
            or any(item not in self.plan.candidates for item in deleted)
        ):
            raise ValueError("garbage collection outcome is invalid")
        if not self.executed and deleted:
            raise ValueError("dry-run garbage collection cannot report deletions")
        object.__setattr__(self, "deleted", deleted)
