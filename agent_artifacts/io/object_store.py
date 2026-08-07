"""Non-following read-only content-addressed artifact object store."""

from __future__ import annotations

import os
import secrets
import shutil
import stat
import tempfile
from pathlib import Path

from agent_artifacts.compiler.model import ObjectPlan, ObjectReceipt
from agent_artifacts.configuration.policy import redact_text
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import ObjectDigest
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.protocol.native_tree import SnapshotEntry, SnapshotEntryKind
from agent_artifacts.protocol.paths import parse_relative_path
from agent_artifacts.store.model import (
    ObjectCandidate,
    ObjectDeleteCommand,
    ObjectInventory,
    ObjectPublishCommand,
    ObjectPublishReceipt,
    ObjectReadRequest,
    ObjectStorePaths,
    StoredObject,
    make_object_candidate,
    parse_object_candidate,
)

STORE_INVALID = DiagnosticCode("store-invalid")
STORE_UNAVAILABLE = DiagnosticCode("store-unavailable")
STORE_UNSAFE_ENTRY = DiagnosticCode("store-unsafe-entry")
_MAX_FILES = 10_000
_MAX_ENTRIES = 20_000
_MAX_FILE_BYTES = 10 * 1024 * 1024
_MAX_TOTAL_BYTES = 100 * 1024 * 1024
_MAX_DEPTH = 64
_HEX = frozenset("0123456789abcdef")


def _error(code: DiagnosticCode, message: str) -> Err:
    return Err((Diagnostic(code, Severity.ERROR, redact_text(message)),))


def _warning(message: str) -> Diagnostic:
    return Diagnostic(STORE_UNSAFE_ENTRY, Severity.WARNING, redact_text(message))


def _real_directory(path: Path) -> bool:
    try:
        return stat.S_ISDIR(os.stat(path, follow_symlinks=False).st_mode)
    except OSError:
        return False


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _object_root(paths: ObjectStorePaths, digest: ObjectDigest) -> Path:
    return Path(paths.objects) / digest.value[:2] / digest.value[2:]


def _managed_components(
    paths: ObjectStorePaths,
    prefix: Path | None = None,
) -> tuple[Path, ...]:
    root = Path(paths.root)
    components = (root, root / "objects", Path(paths.objects))
    return components if prefix is None else (*components, prefix)


def _existing_components_are_real(components: tuple[Path, ...]) -> bool:
    return all(not os.path.lexists(path) or _real_directory(path) for path in components)


def _make_writable_tree(root: Path) -> None:
    if not _real_directory(root):
        return
    for directory, children, files in os.walk(root, topdown=False, followlinks=False):
        current = Path(directory)
        for name in files:
            target = current / name
            try:
                if target.is_symlink():
                    continue
                mode = os.stat(target, follow_symlinks=False).st_mode
                os.chmod(
                    target,
                    0o700 if mode & 0o111 else 0o600,
                    follow_symlinks=False,
                )
            except OSError:
                pass
        for name in children:
            target = current / name
            try:
                if target.is_symlink():
                    continue
                os.chmod(target, 0o700, follow_symlinks=False)
            except OSError:
                pass
        try:
            os.chmod(current, 0o700, follow_symlinks=False)
        except OSError:
            pass


def _remove_tree(root: Path) -> None:
    _make_writable_tree(root)
    shutil.rmtree(root)


def _restore_gc_tombstone(
    tombstone: Path,
    target: Path,
    digest: ObjectDigest,
) -> bool:
    if os.path.lexists(target) or not _real_directory(tombstone):
        return False
    verified = _read_candidate(tombstone, digest)
    if isinstance(verified, Err):
        return False
    try:
        os.rename(tombstone, target)
        _freeze_existing_tree(target)
        _fsync_directory(target.parent)
        _fsync_directory(tombstone.parent)
        return True
    except OSError:
        try:
            if _real_directory(target):
                _freeze_existing_tree(target)
            elif _real_directory(tombstone):
                _freeze_existing_tree(tombstone)
        except OSError:
            pass
        return False


def _freeze_tree(root: Path, entries: tuple[SnapshotEntry, ...]) -> None:
    for entry in entries:
        target = root.joinpath(*entry.path.parts)
        if entry.kind is SnapshotEntryKind.FILE:
            os.chmod(target, 0o500 if entry.executable else 0o400, follow_symlinks=False)
    for directory, _children, _files in os.walk(root, topdown=False, followlinks=False):
        current = Path(directory)
        os.chmod(current, 0o700 if current == root else 0o500, follow_symlinks=False)


def _freeze_existing_tree(root: Path) -> None:
    if not _real_directory(root):
        return
    for directory, children, files in os.walk(root, topdown=False, followlinks=False):
        current = Path(directory)
        for name in files:
            target = current / name
            if target.is_symlink():
                continue
            mode = os.stat(target, follow_symlinks=False).st_mode
            os.chmod(target, 0o500 if mode & 0o111 else 0o400, follow_symlinks=False)
        for name in children:
            target = current / name
            if not target.is_symlink():
                os.chmod(target, 0o500, follow_symlinks=False)
        os.chmod(current, 0o500, follow_symlinks=False)


def _write_candidate(stage: Path, candidate: ObjectCandidate) -> Result[None]:
    try:
        for entry in candidate.entries:
            target = stage.joinpath(*entry.path.parts)
            if entry.kind is SnapshotEntryKind.DIRECTORY:
                target.mkdir(parents=True, exist_ok=True, mode=0o700)
                continue
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            descriptor = os.open(
                target,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o700 if entry.executable else 0o600,
            )
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(entry.content)
                stream.flush()
                os.fsync(stream.fileno())
        for directory, _children, _files in os.walk(stage, topdown=False):
            _fsync_directory(Path(directory))
        _freeze_tree(stage, candidate.entries)
        return Ok(None)
    except OSError as error:
        return _error(STORE_UNAVAILABLE, f"cannot stage artifact object: {error}")


def _read_candidate(root: Path, expected: ObjectDigest) -> Result[ObjectCandidate]:
    if not _real_directory(root):
        return _error(STORE_UNSAFE_ENTRY, "artifact object root is not a real directory")
    entries: list[SnapshotEntry] = []
    pending: list[tuple[Path, str, int, tuple[int, int] | None]] = [(root, "", 0, None)]
    file_count = 0
    entry_count = 0
    total_bytes = 0
    while pending:
        directory, relative_directory, depth, expected_identity = pending.pop()
        if depth > _MAX_DEPTH:
            return _error(STORE_INVALID, "artifact object exceeds maximum depth")
        descriptor: int | None = None
        try:
            descriptor = os.open(
                directory,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
            )
            opened_directory = os.fstat(descriptor)
            if not stat.S_ISDIR(opened_directory.st_mode) or (
                expected_identity is not None
                and (opened_directory.st_dev, opened_directory.st_ino) != expected_identity
            ):
                return _error(
                    STORE_UNSAFE_ENTRY,
                    "artifact object directory changed while opening",
                )
            with os.scandir(descriptor) as scan:
                children = tuple(sorted(scan, key=lambda item: item.name, reverse=True))
            for child in children:
                entry_count += 1
                if entry_count > _MAX_ENTRIES:
                    return _error(STORE_INVALID, "artifact object exceeds maximum entry count")
                relative = (
                    child.name if not relative_directory else f"{relative_directory}/{child.name}"
                )
                parsed = parse_relative_path(relative)
                if isinstance(parsed, Err):
                    return _error(
                        STORE_UNSAFE_ENTRY,
                        f"artifact object path is unsafe: {relative!r}",
                    )
                child_status = child.stat(follow_symlinks=False)
                if stat.S_ISLNK(child_status.st_mode):
                    return _error(
                        STORE_UNSAFE_ENTRY,
                        f"artifact object symlink is forbidden: {relative}",
                    )
                if stat.S_ISDIR(child_status.st_mode):
                    entries.append(SnapshotEntry(parsed.value, SnapshotEntryKind.DIRECTORY))
                    pending.append(
                        (
                            directory / child.name,
                            relative,
                            depth + 1,
                            (child_status.st_dev, child_status.st_ino),
                        )
                    )
                    continue
                if not stat.S_ISREG(child_status.st_mode):
                    return _error(
                        STORE_UNSAFE_ENTRY,
                        f"artifact object special file is forbidden: {relative}",
                    )
                file_count += 1
                total_bytes += child_status.st_size
                if file_count > _MAX_FILES or child_status.st_size > _MAX_FILE_BYTES:
                    return _error(STORE_INVALID, "artifact object exceeds file bounds")
                if total_bytes > _MAX_TOTAL_BYTES:
                    return _error(STORE_INVALID, "artifact object exceeds total-size bound")
                file_descriptor = os.open(
                    child.name,
                    os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=descriptor,
                )
                with os.fdopen(file_descriptor, "rb") as stream:
                    opened = os.fstat(stream.fileno())
                    if (
                        not stat.S_ISREG(opened.st_mode)
                        or opened.st_dev != child_status.st_dev
                        or opened.st_ino != child_status.st_ino
                        or opened.st_size != child_status.st_size
                    ):
                        return _error(STORE_UNSAFE_ENTRY, "artifact object changed while opening")
                    content = stream.read(_MAX_FILE_BYTES + 1)
                if len(content) != child_status.st_size:
                    return _error(STORE_UNSAFE_ENTRY, "artifact object changed while reading")
                entries.append(
                    SnapshotEntry(
                        parsed.value,
                        SnapshotEntryKind.FILE,
                        content,
                        bool(child_status.st_mode & 0o111),
                    )
                )
        except OSError as error:
            return _error(STORE_UNAVAILABLE, f"cannot read artifact object: {error}")
        finally:
            if descriptor is not None:
                os.close(descriptor)
    return make_object_candidate(entries, expected_digest=expected)


def read_object(request: ObjectReadRequest) -> Result[StoredObject | None]:
    objects = Path(request.paths.objects)
    prefix = objects / request.digest.value[:2]
    if not _existing_components_are_real(_managed_components(request.paths, prefix)):
        return _error(STORE_UNSAFE_ENTRY, "artifact object store path is not a real directory")
    if not os.path.lexists(objects) or not os.path.lexists(prefix):
        return Ok(None)
    root = _object_root(request.paths, request.digest)
    if not os.path.lexists(root):
        return Ok(None)
    candidate = _read_candidate(root, request.digest)
    if isinstance(candidate, Err):
        return candidate
    return Ok(StoredObject(candidate.value, str(root)))


def _prepare_store(paths: ObjectStorePaths, digest: ObjectDigest) -> Result[Path]:
    objects = Path(paths.objects)
    prefix = objects / digest.value[:2]
    components = _managed_components(paths, prefix)
    if not _existing_components_are_real(components):
        return _error(STORE_UNSAFE_ENTRY, "artifact object store path is not a real directory")
    try:
        for component in components:
            component.mkdir(parents=True, exist_ok=True, mode=0o700)
            if not _real_directory(component):
                return _error(
                    STORE_UNSAFE_ENTRY,
                    "artifact object store path is not a real directory",
                )
        return Ok(prefix)
    except OSError as error:
        return _error(STORE_UNAVAILABLE, f"cannot prepare artifact object store: {error}")


def _stored_receipt(
    command: ObjectPublishCommand,
    *,
    created: bool,
    repaired: bool,
) -> Result[ObjectPublishReceipt]:
    loaded = read_object(ObjectReadRequest(command.paths, command.candidate.digest))
    if isinstance(loaded, Err):
        return loaded
    if loaded.value is None or loaded.value.candidate != command.candidate:
        return _error(STORE_INVALID, "published artifact object does not match candidate")
    return Ok(ObjectPublishReceipt(loaded.value, created, repaired))


def publish_object(command: ObjectPublishCommand) -> Result[ObjectPublishReceipt]:
    prepared = _prepare_store(command.paths, command.candidate.digest)
    if isinstance(prepared, Err):
        return prepared
    prefix = prepared.value
    target = _object_root(command.paths, command.candidate.digest)
    try:
        created_stage = Path(tempfile.mkdtemp(prefix=".stage-", dir=prefix))
        os.chmod(created_stage, 0o700)
    except OSError as error:
        return _error(STORE_UNAVAILABLE, f"cannot prepare artifact object stage: {error}")
    stage: Path | None = created_stage
    try:
        written = _write_candidate(created_stage, command.candidate)
        if isinstance(written, Err):
            return written
        repaired = False
        for _attempt in range(4):
            try:
                assert stage is not None
                os.rename(stage, target)
                stage = None
                os.chmod(target, 0o500, follow_symlinks=False)
                _fsync_directory(prefix)
                return _stored_receipt(command, created=not repaired, repaired=repaired)
            except OSError as publish_error:
                if not os.path.lexists(target):
                    return _error(
                        STORE_UNAVAILABLE,
                        f"cannot publish artifact object: {publish_error}",
                    )
                if not _real_directory(target):
                    return _error(
                        STORE_UNSAFE_ENTRY,
                        "artifact object target is not a real directory",
                    )
                existing = read_object(ObjectReadRequest(command.paths, command.candidate.digest))
                if isinstance(existing, Ok) and existing.value is not None:
                    return Ok(ObjectPublishReceipt(existing.value, False, repaired))
                if isinstance(existing, Err) and any(
                    diagnostic.code.value not in {"digest-mismatch", "store-invalid"}
                    for diagnostic in existing.diagnostics
                ):
                    return existing
                quarantine = Path(command.paths.quarantine)
                try:
                    quarantine.mkdir(parents=True, exist_ok=True, mode=0o700)
                    if not _real_directory(quarantine):
                        return _error(
                            STORE_UNSAFE_ENTRY,
                            "artifact object quarantine is not a real directory",
                        )
                    abandoned = quarantine / (
                        f"{command.candidate.digest.value}-{secrets.token_hex(8)}"
                    )
                    os.chmod(target, 0o700, follow_symlinks=False)
                    os.rename(target, abandoned)
                except FileNotFoundError:
                    continue
                except OSError as error:
                    try:
                        if _real_directory(target):
                            os.chmod(target, 0o500, follow_symlinks=False)
                    except OSError:
                        pass
                    return _error(STORE_UNAVAILABLE, f"cannot quarantine corrupt object: {error}")
                try:
                    assert stage is not None
                    os.rename(stage, target)
                    stage = None
                    os.chmod(target, 0o500, follow_symlinks=False)
                    repaired = True
                    _fsync_directory(prefix)
                except OSError as error:
                    try:
                        if not os.path.lexists(target):
                            os.rename(abandoned, target)
                            _freeze_existing_tree(target)
                    except OSError:
                        pass
                    return _error(STORE_UNAVAILABLE, f"cannot repair corrupt object: {error}")
                try:
                    _remove_tree(abandoned)
                except OSError:
                    pass
                return _stored_receipt(command, created=False, repaired=True)
        return _error(STORE_UNAVAILABLE, "artifact object publication did not converge")
    finally:
        if stage is not None and _real_directory(stage):
            try:
                _remove_tree(stage)
            except OSError:
                pass


def inventory_objects(paths: ObjectStorePaths) -> Result[ObjectInventory]:
    objects = Path(paths.objects)
    if not _existing_components_are_real(_managed_components(paths)):
        return _error(STORE_UNSAFE_ENTRY, "artifact object store root is not a real directory")
    if not os.path.lexists(objects):
        return Ok(ObjectInventory(()))
    digests: list[ObjectDigest] = []
    diagnostics: list[Diagnostic] = []
    try:
        with os.scandir(objects) as prefixes:
            for prefix in sorted(prefixes, key=lambda item: item.name):
                prefix_status = prefix.stat(follow_symlinks=False)
                if (
                    len(prefix.name) != 2
                    or any(character not in _HEX for character in prefix.name)
                    or not stat.S_ISDIR(prefix_status.st_mode)
                ):
                    diagnostics.append(
                        _warning(f"ignored unsafe object-store entry: {prefix.name}")
                    )
                    continue
                with os.scandir(prefix.path) as suffixes:
                    for suffix in sorted(suffixes, key=lambda item: item.name):
                        suffix_status = suffix.stat(follow_symlinks=False)
                        if (
                            len(suffix.name) != 62
                            or any(character not in _HEX for character in suffix.name)
                            or not stat.S_ISDIR(suffix_status.st_mode)
                        ):
                            diagnostics.append(
                                _warning(
                                    f"ignored unsafe object-store entry: {prefix.name}/{suffix.name}"
                                )
                            )
                            continue
                        digests.append(ObjectDigest("sha256", prefix.name + suffix.name))
    except OSError as error:
        return _error(STORE_UNAVAILABLE, f"cannot inventory artifact objects: {error}")
    return Ok(ObjectInventory(tuple(digests), tuple(diagnostics)))


def delete_object(command: ObjectDeleteCommand) -> Result[None]:
    objects = Path(command.paths.objects)
    prefix = objects / command.digest.value[:2]
    if not _existing_components_are_real(_managed_components(command.paths, prefix)):
        return _error(STORE_UNSAFE_ENTRY, "artifact object store path is unsafe")
    if not os.path.lexists(objects) or not os.path.lexists(prefix):
        return Ok(None)
    target = _object_root(command.paths, command.digest)
    if not os.path.lexists(target):
        return Ok(None)
    if not _real_directory(target):
        return _error(STORE_UNSAFE_ENTRY, "refusing to delete a non-directory object target")
    quarantine = Path(command.paths.quarantine)
    tombstone: Path | None = None
    try:
        quarantine.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not _real_directory(quarantine):
            return _error(STORE_UNSAFE_ENTRY, "artifact object quarantine is unsafe")
        tombstone = quarantine / f"gc-{command.digest.value}-{secrets.token_hex(8)}"
        os.chmod(target, 0o700, follow_symlinks=False)
        os.rename(target, tombstone)
        _fsync_directory(target.parent)
        _remove_tree(tombstone)
        _fsync_directory(quarantine)
        return Ok(None)
    except OSError as error:
        try:
            if _real_directory(target):
                _freeze_existing_tree(target)
            elif tombstone is not None:
                _restore_gc_tombstone(tombstone, target, command.digest)
        except OSError:
            pass
        return _error(STORE_UNAVAILABLE, f"cannot delete artifact object: {error}")


def materialize_compiler_object(
    paths: ObjectStorePaths,
    plan: ObjectPlan,
) -> Result[ObjectReceipt]:
    candidate = parse_object_candidate(plan.content, plan.digest)
    if isinstance(candidate, Err):
        return candidate
    published = publish_object(ObjectPublishCommand(paths, candidate.value))
    if isinstance(published, Err):
        return published
    return Ok(ObjectReceipt(published.value.stored.candidate.digest))
