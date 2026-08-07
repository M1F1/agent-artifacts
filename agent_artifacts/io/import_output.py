"""Filesystem staging and atomic replacement for reviewed canonical importer output."""

from __future__ import annotations

import os
import re
import shutil
import stat
import tempfile

from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import ObjectDigest
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.importers.model import AppliedImport, StagedImport
from agent_artifacts.protocol.native_tree import (
    SnapshotEntry,
    SnapshotEntryKind,
    SnapshotOrigin,
    SourceSnapshot,
)
from agent_artifacts.protocol.paths import parse_relative_path
from agent_artifacts.sources.model import source_snapshot_digest

IMPORT_OUTPUT_INVALID = DiagnosticCode("import-output-invalid")
IMPORT_STALE = DiagnosticCode("import-stale")
IMPORT_APPLY_FAILED = DiagnosticCode("import-apply-failed")
_NAME_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_MAX_FILES = 100_000
_MAX_FILE_BYTES = 16 * 1024 * 1024
_MAX_TOTAL_BYTES = 256 * 1024 * 1024
_MAX_DEPTH = 64


def _error(code: DiagnosticCode, message: str) -> Err:
    return Err((Diagnostic(code, Severity.ERROR, message),))


def _fsync_directory(path: str) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _safe_parent(path: str) -> bool:
    if not os.path.isabs(path) or os.path.normpath(path) != path:
        return False
    try:
        status = os.stat(path, follow_symlinks=False)
    except OSError:
        return False
    return stat.S_ISDIR(status.st_mode) and not stat.S_ISLNK(status.st_mode)


def _read_directory(root: str) -> Result[SourceSnapshot]:
    try:
        root_descriptor = os.open(
            root,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        root_before = os.fstat(root_descriptor)
    except OSError as error:
        return _error(IMPORT_OUTPUT_INVALID, f"cannot inspect importer output: {error}")
    try:
        if not stat.S_ISDIR(root_before.st_mode):
            return _error(IMPORT_OUTPUT_INVALID, "importer output must be a real directory")
        entries: list[SnapshotEntry] = []
        file_count = 0
        total_bytes = 0

        def walk(directory_descriptor: int, relative_directory: str, depth: int) -> Result[None]:
            nonlocal file_count, total_bytes
            if depth > _MAX_DEPTH:
                return _error(IMPORT_OUTPUT_INVALID, "importer output exceeds directory depth")
            try:
                with os.scandir(directory_descriptor) as scan:
                    names = tuple(sorted((child.name for child in scan)))
            except OSError as error:
                return _error(IMPORT_OUTPUT_INVALID, f"cannot read importer output: {error}")
            for name in names:
                relative = name if not relative_directory else f"{relative_directory}/{name}"
                parsed = parse_relative_path(relative)
                if isinstance(parsed, Err):
                    return _error(
                        IMPORT_OUTPUT_INVALID,
                        f"unsafe importer output path: {relative!r}",
                    )
                try:
                    before = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
                except OSError as error:
                    return _error(IMPORT_OUTPUT_INVALID, f"cannot inspect importer output: {error}")
                if stat.S_ISLNK(before.st_mode):
                    return _error(
                        IMPORT_OUTPUT_INVALID,
                        f"importer output contains a symlink: {relative}",
                    )
                if stat.S_ISDIR(before.st_mode):
                    try:
                        child_descriptor = os.open(
                            name,
                            os.O_RDONLY
                            | getattr(os, "O_DIRECTORY", 0)
                            | getattr(os, "O_NOFOLLOW", 0),
                            dir_fd=directory_descriptor,
                        )
                    except OSError as error:
                        return _error(
                            IMPORT_OUTPUT_INVALID,
                            f"cannot open importer output directory: {error}",
                        )
                    try:
                        opened = os.fstat(child_descriptor)
                        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                            return _error(
                                IMPORT_OUTPUT_INVALID,
                                "importer output directory changed while opening",
                            )
                        entries.append(SnapshotEntry(parsed.value, SnapshotEntryKind.DIRECTORY))
                        if len(entries) > _MAX_FILES:
                            return _error(
                                IMPORT_OUTPUT_INVALID,
                                "importer output exceeds filesystem bounds",
                            )
                        descended = walk(child_descriptor, relative, depth + 1)
                        if isinstance(descended, Err):
                            return descended
                        directory_after = os.fstat(child_descriptor)
                        if (
                            directory_after.st_mtime_ns != opened.st_mtime_ns
                            or directory_after.st_ctime_ns != opened.st_ctime_ns
                        ):
                            return _error(
                                IMPORT_OUTPUT_INVALID,
                                "importer output directory changed while reading",
                            )
                    finally:
                        os.close(child_descriptor)
                    continue
                if not stat.S_ISREG(before.st_mode):
                    return _error(
                        IMPORT_OUTPUT_INVALID,
                        f"importer output contains a special file: {relative}",
                    )
                file_count += 1
                if file_count > _MAX_FILES or before.st_size > _MAX_FILE_BYTES:
                    return _error(
                        IMPORT_OUTPUT_INVALID,
                        "importer output exceeds filesystem bounds",
                    )
                total_bytes += before.st_size
                if total_bytes > _MAX_TOTAL_BYTES:
                    return _error(
                        IMPORT_OUTPUT_INVALID,
                        "importer output exceeds filesystem bounds",
                    )
                try:
                    descriptor = os.open(
                        name,
                        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                        dir_fd=directory_descriptor,
                    )
                    with os.fdopen(descriptor, "rb") as stream:
                        opened = os.fstat(stream.fileno())
                        if (
                            opened.st_dev != before.st_dev
                            or opened.st_ino != before.st_ino
                            or opened.st_size != before.st_size
                            or not stat.S_ISREG(opened.st_mode)
                        ):
                            return _error(
                                IMPORT_OUTPUT_INVALID,
                                "importer output changed while opening",
                            )
                        content = stream.read(_MAX_FILE_BYTES + 1)
                        after = os.fstat(stream.fileno())
                except OSError as error:
                    return _error(IMPORT_OUTPUT_INVALID, f"cannot read importer output: {error}")
                if (
                    len(content) != before.st_size
                    or len(content) > _MAX_FILE_BYTES
                    or after.st_size != before.st_size
                    or after.st_mtime_ns != before.st_mtime_ns
                    or after.st_ctime_ns != before.st_ctime_ns
                ):
                    return _error(IMPORT_OUTPUT_INVALID, "importer output changed while reading")
                entries.append(
                    SnapshotEntry(
                        parsed.value,
                        SnapshotEntryKind.FILE,
                        content,
                        bool(before.st_mode & 0o111),
                    )
                )
                if len(entries) > _MAX_FILES:
                    return _error(
                        IMPORT_OUTPUT_INVALID,
                        "importer output exceeds filesystem bounds",
                    )
            return Ok(None)

        walked = walk(root_descriptor, "", 0)
        if isinstance(walked, Err):
            return walked
        try:
            root_after = os.stat(root, follow_symlinks=False)
        except OSError:
            return _error(IMPORT_OUTPUT_INVALID, "importer output changed while reading")
        if (
            (root_before.st_dev, root_before.st_ino) != (root_after.st_dev, root_after.st_ino)
            or root_before.st_mtime_ns != root_after.st_mtime_ns
            or root_before.st_ctime_ns != root_after.st_ctime_ns
        ):
            return _error(IMPORT_OUTPUT_INVALID, "importer output changed while reading")
        return Ok(SourceSnapshot(SnapshotOrigin.LOCAL, tuple(entries)))
    finally:
        os.close(root_descriptor)


class FilesystemImportOutput:
    """Stage one tree beside a named destination and replace it after exact review."""

    def __init__(self, parent: str, destination_name: str):
        if not _safe_parent(parent) or _NAME_RE.fullmatch(destination_name) is None:
            raise ValueError("import output requires a real absolute parent and slug destination")
        self.parent = os.path.realpath(parent)
        self.destination_name = destination_name
        self.destination = os.path.join(self.parent, destination_name)
        self._stage_prefix = f".{destination_name}.aart-import-stage-"
        self._active_stages: set[str] = set()

    def current(self) -> Result[SourceSnapshot | None]:
        try:
            os.stat(self.destination, follow_symlinks=False)
        except FileNotFoundError:
            return Ok(None)
        except OSError as error:
            return _error(IMPORT_OUTPUT_INVALID, f"cannot inspect import destination: {error}")
        return _read_directory(self.destination)

    def _stage_path(self, stage_id: str) -> bool:
        return os.path.dirname(stage_id) == self.parent and os.path.basename(stage_id).startswith(
            self._stage_prefix
        )

    def _recognized_stage(self, stage_id: str) -> bool:
        return stage_id in self._active_stages and self._stage_path(stage_id)

    def stage(
        self,
        snapshot: SourceSnapshot,
        output_digest: ObjectDigest,
    ) -> Result[StagedImport]:
        if len(snapshot.entries) > _MAX_FILES:
            return _error(IMPORT_OUTPUT_INVALID, "staged snapshot exceeds filesystem bounds")
        file_entries = tuple(
            entry for entry in snapshot.entries if entry.kind is SnapshotEntryKind.FILE
        )
        if (
            any(len(entry.content) > _MAX_FILE_BYTES for entry in file_entries)
            or sum(len(entry.content) for entry in file_entries) > _MAX_TOTAL_BYTES
        ):
            return _error(IMPORT_OUTPUT_INVALID, "staged snapshot exceeds filesystem bounds")
        calculated = source_snapshot_digest(snapshot)
        if isinstance(calculated, Err) or calculated.value != output_digest:
            return _error(IMPORT_OUTPUT_INVALID, "staged snapshot digest does not match")
        if not _safe_parent(self.parent):
            return _error(IMPORT_OUTPUT_INVALID, "import output parent became unsafe")
        try:
            stage = tempfile.mkdtemp(prefix=self._stage_prefix, dir=self.parent)
            directories = tuple(
                sorted(
                    (
                        entry
                        for entry in snapshot.entries
                        if entry.kind is SnapshotEntryKind.DIRECTORY
                    ),
                    key=lambda entry: (len(entry.path.parts), str(entry.path)),
                )
            )
            files = tuple(
                entry for entry in snapshot.entries if entry.kind is SnapshotEntryKind.FILE
            )
            for entry in directories:
                os.mkdir(os.path.join(stage, *entry.path.parts), 0o755)
            for entry in files:
                path = os.path.join(stage, *entry.path.parts)
                descriptor = os.open(
                    path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o755 if entry.executable else 0o644,
                )
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(entry.content)
                    stream.flush()
                    os.fsync(stream.fileno())
            for entry in reversed(directories):
                _fsync_directory(os.path.join(stage, *entry.path.parts))
            _fsync_directory(stage)
            _fsync_directory(self.parent)
        except OSError as error:
            if "stage" in locals() and self._stage_path(stage):
                shutil.rmtree(stage, ignore_errors=True)
            return _error(IMPORT_APPLY_FAILED, f"cannot stage importer output: {error}")
        verified = _read_directory(stage)
        if isinstance(verified, Err):
            shutil.rmtree(stage, ignore_errors=True)
            return verified
        verified_digest = source_snapshot_digest(verified.value)
        if isinstance(verified_digest, Err) or verified_digest.value != output_digest:
            shutil.rmtree(stage, ignore_errors=True)
            return _error(
                IMPORT_OUTPUT_INVALID, "staged filesystem tree failed digest verification"
            )
        self._active_stages.add(stage)
        return Ok(StagedImport(stage, output_digest))

    def apply(
        self,
        staged: StagedImport,
        *,
        expected_destination_digest: ObjectDigest | None,
        changed_paths: int,
    ) -> Result[AppliedImport]:
        if (
            not isinstance(changed_paths, int)
            or isinstance(changed_paths, bool)
            or changed_paths < 0
        ):
            return _error(IMPORT_OUTPUT_INVALID, "changed path count is invalid")
        if not self._recognized_stage(staged.stage_id):
            return _error(IMPORT_OUTPUT_INVALID, "staged importer receipt is outside its parent")
        verified_stage = _read_directory(staged.stage_id)
        if isinstance(verified_stage, Err):
            return verified_stage
        stage_digest = source_snapshot_digest(verified_stage.value)
        if isinstance(stage_digest, Err) or stage_digest.value != staged.output_digest:
            return _error(IMPORT_STALE, "staged importer output changed before apply")
        current = self.current()
        if isinstance(current, Err):
            return current
        current_digest: ObjectDigest | None = None
        if current.value is not None:
            calculated = source_snapshot_digest(current.value)
            if isinstance(calculated, Err):
                return _error(IMPORT_OUTPUT_INVALID, "current import destination cannot be hashed")
            current_digest = calculated.value
        if current_digest != expected_destination_digest:
            return _error(IMPORT_STALE, "import destination changed after review")
        backup = f"{staged.stage_id}.previous"
        if os.path.lexists(backup):
            return _error(IMPORT_OUTPUT_INVALID, "import backup path already exists")
        moved_previous = False
        try:
            if current.value is not None:
                os.replace(self.destination, backup)
                moved_previous = True
                backup_snapshot = _read_directory(backup)
                if isinstance(backup_snapshot, Err):
                    os.replace(backup, self.destination)
                    return backup_snapshot
                backup_digest = source_snapshot_digest(backup_snapshot.value)
                if (
                    isinstance(backup_digest, Err)
                    or backup_digest.value != expected_destination_digest
                ):
                    os.replace(backup, self.destination)
                    return _error(IMPORT_STALE, "import destination changed during apply")
            os.replace(staged.stage_id, self.destination)
            published = _read_directory(self.destination)
            published_digest = (
                published if isinstance(published, Err) else source_snapshot_digest(published.value)
            )
            if isinstance(published_digest, Err) or published_digest.value != staged.output_digest:
                failed = f"{staged.stage_id}.failed"
                os.replace(self.destination, failed)
                if moved_previous:
                    os.replace(backup, self.destination)
                shutil.rmtree(failed, ignore_errors=True)
                return _error(IMPORT_APPLY_FAILED, "published importer output failed verification")
            warnings: tuple[str, ...] = ()
            if moved_previous:
                try:
                    shutil.rmtree(backup)
                except OSError:
                    warnings = ("previous importer output remains in a private sibling backup",)
            try:
                _fsync_directory(self.parent)
            except OSError:
                warnings = (
                    *warnings,
                    "published importer output could not be directory-fsynced",
                )
            self._active_stages.discard(staged.stage_id)
            return Ok(AppliedImport(staged.output_digest, changed_paths, warnings))
        except OSError as error:
            try:
                if (
                    moved_previous
                    and not os.path.lexists(self.destination)
                    and os.path.lexists(backup)
                ):
                    os.replace(backup, self.destination)
            except OSError:
                return _error(
                    IMPORT_APPLY_FAILED,
                    f"import apply failed and rollback was incomplete: {error}",
                )
            return _error(IMPORT_APPLY_FAILED, f"cannot apply importer output: {error}")

    def discard(self, staged: StagedImport) -> Result[None]:
        if not self._recognized_stage(staged.stage_id):
            return _error(IMPORT_OUTPUT_INVALID, "staged importer receipt is outside its parent")
        if not os.path.lexists(staged.stage_id):
            self._active_stages.discard(staged.stage_id)
            return Ok(None)
        try:
            status = os.stat(staged.stage_id, follow_symlinks=False)
            if not stat.S_ISDIR(status.st_mode) or stat.S_ISLNK(status.st_mode):
                return _error(
                    IMPORT_OUTPUT_INVALID, "staged importer output is not a real directory"
                )
            shutil.rmtree(staged.stage_id)
            _fsync_directory(self.parent)
            self._active_stages.discard(staged.stage_id)
            return Ok(None)
        except OSError as error:
            return _error(IMPORT_APPLY_FAILED, f"cannot discard staged importer output: {error}")
