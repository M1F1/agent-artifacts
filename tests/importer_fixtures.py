from __future__ import annotations

from pathlib import Path

from agent_artifacts.domain.result import Ok
from agent_artifacts.importers.model import ImporterInput, ImportOrigin
from agent_artifacts.protocol.native_tree import (
    SnapshotEntry,
    SnapshotEntryKind,
    SnapshotOrigin,
    SourceSnapshot,
)
from agent_artifacts.protocol.paths import parse_relative_path

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "importers" / "legacy_catalog"


def fixture_snapshot() -> SourceSnapshot:
    entries: list[SnapshotEntry] = []
    for path in sorted(FIXTURE_ROOT.rglob("*")):
        relative = path.relative_to(FIXTURE_ROOT).as_posix()
        parsed = parse_relative_path(relative)
        assert isinstance(parsed, Ok), parsed
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
    return SourceSnapshot(SnapshotOrigin.IMMUTABLE_GIT, tuple(entries))


def importer_input(snapshot: SourceSnapshot | None = None) -> ImporterInput:
    return ImporterInput(
        ImportOrigin(
            "https://github.com/example/legacy-catalog.git",
            "a" * 40,
            None,
        ),
        fixture_snapshot() if snapshot is None else snapshot,
    )


def replace_file(snapshot: SourceSnapshot, path: str, content: bytes) -> SourceSnapshot:
    return SourceSnapshot(
        snapshot.origin,
        tuple(
            SnapshotEntry(entry.path, entry.kind, content, entry.executable)
            if str(entry.path) == path
            else entry
            for entry in snapshot.entries
        ),
    )


def add_file(snapshot: SourceSnapshot, path: str, content: bytes) -> SourceSnapshot:
    parsed = parse_relative_path(path)
    assert isinstance(parsed, Ok), parsed
    return SourceSnapshot(
        snapshot.origin,
        (*snapshot.entries, SnapshotEntry(parsed.value, SnapshotEntryKind.FILE, content)),
    )
