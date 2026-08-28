from __future__ import annotations

import json
from pathlib import Path

from agent_artifacts.domain.result import Ok
from agent_artifacts.protocol.native_tree import (
    SnapshotEntry,
    SnapshotEntryKind,
    SnapshotOrigin,
    SourceSnapshot,
)
from agent_artifacts.protocol.paths import parse_relative_path
from agent_artifacts.protocol.registry_models import RegistryEntry
from agent_artifacts.protocol.registry_schema import parse_registry_entry

NATIVE_FIXTURE = Path("tests/fixtures/protocol/native-source-v1")


def _file(path: str, content: bytes) -> SnapshotEntry:
    parsed = parse_relative_path(path)
    assert isinstance(parsed, Ok)
    return SnapshotEntry(parsed.value, SnapshotEntryKind.FILE, content)


def tree_snapshot(root: Path, origin: SnapshotOrigin) -> SourceSnapshot:
    entries: list[SnapshotEntry] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        parsed = parse_relative_path(relative)
        assert isinstance(parsed, Ok)
        if path.is_dir():
            entries.append(SnapshotEntry(parsed.value, SnapshotEntryKind.DIRECTORY))
        else:
            entries.append(
                SnapshotEntry(
                    parsed.value,
                    SnapshotEntryKind.FILE,
                    path.read_bytes(),
                    bool(path.stat().st_mode & 0o111),
                )
            )
    return SourceSnapshot(origin, tuple(entries))


def empty_registry_snapshot() -> SourceSnapshot:
    registry = {
        "schema_version": 1,
        "protocol_version": 1,
        "registry_id": "test-registry",
        "display_name": "Test Registry",
        "requires_aart": {"min_inclusive": "0.0.1", "max_exclusive": "3.0.0"},
        "required_capabilities": [],
        "default_channel": "main",
        "services": {},
    }
    source = {
        "schema_version": 1,
        "protocol_version": 1,
        "source_id": "test-registry",
        "display_name": "Test Registry",
        "requires_aart": {"min_inclusive": "0.0.1", "max_exclusive": "3.0.0"},
        "required_capabilities": [],
        "artifact_roots": ["artifacts"],
        "collection_roots": [],
    }
    return SourceSnapshot(
        SnapshotOrigin.LOCAL,
        (
            _file("aart-registry.json", json.dumps(registry).encode()),
            _file("aart-source.json", json.dumps(source).encode()),
        ),
    )


def native_snapshot() -> SourceSnapshot:
    return tree_snapshot(NATIVE_FIXTURE, SnapshotOrigin.IMMUTABLE_GIT)


def registry_entry(
    *,
    name: str = "code-review",
    review_status: str = "approved",
) -> RegistryEntry:
    result = parse_registry_entry(
        json.dumps(
            {
                "schema_version": 1,
                "type": "skill",
                "name": name,
                "source": {
                    "kind": "git",
                    "url": "https://github.com/example/reference-skills.git",
                    "ref": "main",
                    "path": f"artifacts/skill/{name}",
                },
                "review": {
                    "status": review_status,
                    "policy": "company-review-v1",
                },
            }
        )
    )
    assert isinstance(result, Ok), result
    return result.value


def renamed_native_snapshot(name: str) -> SourceSnapshot:
    """The reference snapshot with only the ``code-review`` package renamed.

    The rename must follow the path, never every manifest in the snapshot: a package whose
    directory was not renamed keeps its own identity, and rewriting its ``name`` would produce a
    manifest that disagrees with its package path — which the loader correctly rejects.
    """

    entries: list[SnapshotEntry] = []
    for entry in native_snapshot().entries:
        original = str(entry.path)
        raw = original.replace("/code-review", f"/{name}")
        parsed = parse_relative_path(raw)
        assert isinstance(parsed, Ok)
        content = entry.content
        if raw != original:
            if raw.endswith("/artifact.json"):
                value = json.loads(content)
                value["name"] = name
                content = json.dumps(value).encode()
            elif raw.endswith("/payload/SKILL.md"):
                content = content.replace(b"name: code-review", f"name: {name}".encode())
        entries.append(SnapshotEntry(parsed.value, entry.kind, content, entry.executable))
    return SourceSnapshot(SnapshotOrigin.IMMUTABLE_GIT, tuple(entries))


def registry_with_owned_package() -> SourceSnapshot:
    base = empty_registry_snapshot()
    native = native_snapshot()
    owned = tuple(
        SnapshotEntry(entry.path, entry.kind, entry.content, entry.executable)
        for entry in native.entries
        if str(entry.path).startswith("artifacts/")
    )
    return SourceSnapshot(SnapshotOrigin.LOCAL, (*base.entries, *owned))


def replace_snapshot_file(
    snapshot: SourceSnapshot,
    path: str,
    content: bytes,
) -> SourceSnapshot:
    return SourceSnapshot(
        snapshot.origin,
        tuple(
            SnapshotEntry(entry.path, entry.kind, content, entry.executable)
            if str(entry.path) == path
            else entry
            for entry in snapshot.entries
        ),
    )


def append_snapshot_file(
    snapshot: SourceSnapshot,
    path: str,
    content: bytes,
) -> SourceSnapshot:
    parsed = parse_relative_path(path)
    assert isinstance(parsed, Ok)
    return SourceSnapshot(
        snapshot.origin,
        (*snapshot.entries, SnapshotEntry(parsed.value, SnapshotEntryKind.FILE, content)),
    )


def snapshot_file(snapshot: SourceSnapshot, path: str) -> bytes:
    return next(entry.content for entry in snapshot.entries if str(entry.path) == path)


def without_snapshot_paths(snapshot: SourceSnapshot, *paths: str) -> SourceSnapshot:
    removed = set(paths)
    return SourceSnapshot(
        snapshot.origin,
        tuple(entry for entry in snapshot.entries if str(entry.path) not in removed),
    )
