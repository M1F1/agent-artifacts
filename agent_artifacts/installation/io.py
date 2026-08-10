"""Local no-follow adapter for reviewed Copy installation transactions."""

from __future__ import annotations

import fcntl
import os
import posixpath
import shutil
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from agent_artifacts.application.store import (
    ReferenceUpdatePorts,
    ReferenceUpdateRequest,
    replace_references,
)
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import ObjectDigest
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.install_state.model import InstallState
from agent_artifacts.install_state.schema import install_state_bytes, parse_install_state
from agent_artifacts.io.object_store import read_object
from agent_artifacts.io.reference_store import read_references, write_references
from agent_artifacts.io.store_lock import acquire_store_lock, release_store_lock
from agent_artifacts.protocol.hashing import sha256_bytes
from agent_artifacts.protocol.paths import parse_relative_path
from agent_artifacts.store.model import ObjectReadRequest, ReferenceIndex, ReferenceKind

from .application import InstallApplyPorts
from .model import (
    CopyTreeOperation,
    EffectOutcome,
    InstallOperation,
    InstallOutcome,
    InstallPlan,
    InstallStatus,
    MergeJsonOperation,
    PathSnapshot,
    TreeMember,
    WriteFileOperation,
)

INSTALL_IO_FAILED = DiagnosticCode("install-io-failed")
INSTALL_PRECONDITION_CHANGED = DiagnosticCode("install-precondition-changed")
_MAX_FILES = 10_000
_MAX_ENTRIES = 20_000
_MAX_FILE_BYTES = 10 * 1024 * 1024
_MAX_TOTAL_BYTES = 100 * 1024 * 1024
_MAX_DEPTH = 64


def _error(code: DiagnosticCode, message: str) -> Err:
    return Err((Diagnostic(code, Severity.ERROR, message),))


def _safe_parent(directory: Path) -> None:
    probe = directory
    missing: list[Path] = []
    while not os.path.lexists(probe):
        missing.append(probe)
        if probe == probe.parent:
            break
        probe = probe.parent
    if os.path.lexists(probe):
        info = probe.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise OSError(f"install parent is not a real directory: {probe}")
    for item in reversed(missing):
        item.mkdir(mode=0o700)
    current = directory
    while current != current.parent:
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise OSError(f"install parent is not a real directory: {current}")
        if current == probe:
            break
        current = current.parent


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_regular(path: Path) -> tuple[bytes, bool]:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise OSError(f"install path is not a regular file: {path}")
        if info.st_size > _MAX_FILE_BYTES:
            raise OSError(f"install file exceeds {_MAX_FILE_BYTES} bytes: {path}")
        chunks: list[bytes] = []
        remaining = _MAX_FILE_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        if len(content) > _MAX_FILE_BYTES:
            raise OSError(f"install file exceeds {_MAX_FILE_BYTES} bytes: {path}")
        return content, bool(info.st_mode & 0o111)
    finally:
        os.close(descriptor)


def _inspect_tree(root: Path) -> tuple[TreeMember, ...]:
    members: list[TreeMember] = []
    total = 0
    files = 0

    def raise_walk_error(error: OSError) -> None:
        raise error

    for directory, dirnames, filenames in os.walk(
        root,
        followlinks=False,
        onerror=raise_walk_error,
    ):
        directory_path = Path(directory)
        dirnames.sort()
        filenames.sort()
        for dirname in dirnames:
            child = directory_path / dirname
            info = child.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise OSError(f"install tree contains an unsafe entry: {child}")
            relative = child.relative_to(root).as_posix()
            parsed = parse_relative_path(relative)
            if not isinstance(parsed, Ok) or len(parsed.value.parts) > _MAX_DEPTH:
                raise OSError(f"install tree path is unsafe: {relative}")
            members.append(TreeMember(parsed.value, "directory"))
            if len(members) > _MAX_ENTRIES:
                raise OSError("install tree exceeds safe entry bounds")
        for filename in filenames:
            child = directory_path / filename
            info = child.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                raise OSError(f"install tree contains an unsafe entry: {child}")
            content, executable = _read_regular(child)
            files += 1
            total += len(content)
            if files > _MAX_FILES or total > _MAX_TOTAL_BYTES:
                raise OSError("install tree exceeds safe inspection bounds")
            relative = child.relative_to(root).as_posix()
            parsed = parse_relative_path(relative)
            if not isinstance(parsed, Ok) or len(parsed.value.parts) > _MAX_DEPTH:
                raise OSError(f"install tree path is unsafe: {relative}")
            members.append(TreeMember(parsed.value, "file", content, executable))
            if len(members) > _MAX_ENTRIES:
                raise OSError("install tree exceeds safe entry bounds")
    if not members:
        raise OSError(f"empty destination trees are not managed: {root}")
    return tuple(sorted(members, key=lambda member: str(member.path)))


def _inspect(path: Path) -> PathSnapshot:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return PathSnapshot.absent(str(path))
    if stat.S_ISREG(info.st_mode):
        content, executable = _read_regular(path)
        return PathSnapshot.file(str(path), content, executable=executable)
    if stat.S_ISDIR(info.st_mode):
        return PathSnapshot.tree(str(path), _inspect_tree(path))
    if stat.S_ISLNK(info.st_mode):
        target = os.readlink(path).encode("utf-8", errors="surrogateescape")
        return PathSnapshot(str(path), "symlink", sha256_bytes(b"symlink\0" + target))
    return PathSnapshot(
        str(path), "special", sha256_bytes(b"special\0" + str(info.st_mode).encode())
    )


def _write_atomic(path: Path, content: bytes, *, mode: int = 0o600) -> None:
    _safe_parent(path.parent)
    stage: str | None = None
    try:
        descriptor, stage = tempfile.mkstemp(prefix=".aart-install-", dir=path.parent)
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(stage, path)
        stage = None
        os.chmod(path, mode, follow_symlinks=False)
        _fsync_directory(path.parent)
    finally:
        if stage is not None:
            try:
                os.unlink(stage)
            except OSError:
                pass


def _remove(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode):
        shutil.rmtree(path)
    else:
        path.unlink()
    _fsync_directory(path.parent)


def _write_tree(path: Path, members: tuple[TreeMember, ...]) -> None:
    _safe_parent(path.parent)
    stage = Path(tempfile.mkdtemp(prefix=".aart-tree-", dir=path.parent))
    try:
        for member in members:
            target = stage.joinpath(*member.path.parts)
            if member.kind == "directory":
                target.mkdir(parents=True, exist_ok=True, mode=0o755)
                continue
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
            with target.open("xb") as stream:
                stream.write(member.content)
                stream.flush()
                os.fsync(stream.fileno())
            target.chmod(0o755 if member.executable else 0o644)
        _remove(path)
        os.replace(stage, path)
        _fsync_directory(path.parent)
    finally:
        if os.path.lexists(stage):
            shutil.rmtree(stage, ignore_errors=True)


def _restore(snapshot: PathSnapshot) -> None:
    path = Path(snapshot.path)
    if snapshot.kind == "absent":
        _remove(path)
    elif snapshot.kind == "file":
        _remove(path)
        _write_atomic(path, snapshot.content, mode=0o755 if snapshot.executable else 0o600)
    elif snapshot.kind == "tree":
        _write_tree(path, snapshot.members)
    else:
        raise OSError(f"cannot restore unsafe install path kind: {snapshot.kind}")


@contextmanager
def _lock(path: Path) -> Iterator[None]:
    _safe_parent(path.parent)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("another canonical install is active for this scope") from error
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _kind(operation: InstallOperation) -> str:
    if isinstance(operation, CopyTreeOperation):
        return "copy-tree"
    if isinstance(operation, WriteFileOperation):
        return operation.effect_kind
    return "merge-json"


def _apply_operation(operation: InstallOperation) -> None:
    path = Path(operation.absolute_destination)
    if isinstance(operation, CopyTreeOperation):
        _write_tree(path, operation.members)
    elif isinstance(operation, WriteFileOperation):
        _remove(path)
        _write_atomic(path, operation.content, mode=0o755 if operation.executable else 0o600)
    elif isinstance(operation, MergeJsonOperation):
        _remove(path)
        _write_atomic(path, operation.content)
    else:  # pragma: no cover - closed operation union
        raise TypeError(f"unsupported install operation: {type(operation).__name__}")


def _preconditions_current(plan: InstallPlan, adapter: LocalInstallAdapter) -> bool:
    loaded = adapter.read_object(ObjectReadRequest(plan.object_store_paths, plan.object_digest))
    if not isinstance(loaded, Ok) or loaded.value is None:
        return False
    if loaded.value.candidate != plan.object_candidate or loaded.value.root != plan.object_root:
        return False
    for operation in plan.operations:
        observed = adapter.inspect_path(operation.absolute_destination)
        if not isinstance(observed, Ok) or observed.value != operation.precondition:
            return False
    state = adapter.inspect_path(plan.state_path)
    return isinstance(state, Ok) and state.value == plan.state_precondition


def _replace_reference(
    plan: InstallPlan,
    kind: ReferenceKind,
    owner: str,
    digests: tuple[ObjectDigest, ...],
) -> Result[ReferenceIndex]:
    return replace_references(
        ReferenceUpdateRequest(plan.object_store_paths, kind, owner, digests),
        ReferenceUpdatePorts(
            acquire_store_lock,
            release_store_lock,
            read_references,
            write_references,
        ),
    )


class LocalInstallAdapter(InstallApplyPorts):
    """Bounded local adapter; apply is serialized and compensates partial Copy failures."""

    def read_object(self, request: ObjectReadRequest):
        return read_object(request)

    def read_state(self, path: str) -> Result[InstallState | None]:
        observed = self.inspect_path(path)
        if isinstance(observed, Err):
            return observed
        if observed.value.kind == "absent":
            return Ok(None)
        if observed.value.kind != "file":
            return _error(INSTALL_IO_FAILED, f"installation state is not a regular file: {path}")
        return parse_install_state(observed.value.content, path=path)

    def inspect_path(self, path: str) -> Result[PathSnapshot]:
        if not posixpath.isabs(path) or posixpath.normpath(path) != path or path == "/":
            return _error(INSTALL_IO_FAILED, f"install inspection path is unsafe: {path}")
        try:
            return Ok(_inspect(Path(path)))
        except OSError as error:
            return _error(INSTALL_IO_FAILED, f"cannot inspect install path {path}: {error}")

    def apply_plan(self, plan: InstallPlan) -> Result[InstallOutcome]:
        desired_state = install_state_bytes(plan.replacement_state)
        outcomes: list[EffectOutcome] = []
        attempted: list[tuple[int, InstallOperation, PathSnapshot]] = []
        applied_indexes: set[int] = set()
        failed_index: int | None = None
        state_attempted = False
        state_changed = False
        transaction_owner = f"transaction/{plan.reference_owner}"
        transaction_retained = False
        try:
            with _lock(Path(plan.state_lock_path)):
                if not _preconditions_current(plan, self):
                    return Ok(
                        InstallOutcome(
                            plan.review_digest,
                            InstallStatus.CONFLICTED,
                            tuple(
                                EffectOutcome(
                                    _kind(operation),
                                    operation.destination,
                                    "skipped",
                                    "precondition changed while acquiring install lock",
                                )
                                for operation in plan.operations
                            ),
                            False,
                        )
                    )
                retained = _replace_reference(
                    plan,
                    ReferenceKind.TRANSACTION,
                    transaction_owner,
                    (plan.object_digest,),
                )
                if isinstance(retained, Err):
                    message = "; ".join(item.message for item in retained.diagnostics)
                    raise OSError(f"cannot retain transaction object reference: {message}")
                transaction_retained = True
                state_is_current = (
                    plan.state_precondition.kind == "file"
                    and plan.state_precondition.content == desired_state
                )
                for index, operation in enumerate(plan.operations):
                    if operation.precondition.digest == operation.desired_digest:
                        outcomes.append(
                            EffectOutcome(_kind(operation), operation.destination, "current")
                        )
                        continue
                    attempted.append((index, operation, operation.precondition))
                    try:
                        _apply_operation(operation)
                    except OSError:
                        failed_index = index
                        raise
                    applied_indexes.add(index)
                    outcomes.append(
                        EffectOutcome(_kind(operation), operation.destination, "changed")
                    )
                if not state_is_current:
                    state_attempted = True
                    _write_atomic(Path(plan.state_path), desired_state)
                    state_changed = True
                referenced = _replace_reference(
                    plan,
                    ReferenceKind.INSTALLED,
                    plan.reference_owner,
                    (plan.object_digest,),
                )
                if isinstance(referenced, Err):
                    message = "; ".join(item.message for item in referenced.diagnostics)
                    raise OSError(f"cannot retain installed object reference: {message}")
                released = _replace_reference(
                    plan,
                    ReferenceKind.TRANSACTION,
                    transaction_owner,
                    (),
                )
                transaction_retained = isinstance(released, Err)
                if isinstance(released, Err) and outcomes:
                    first = outcomes[0]
                    outcomes[0] = EffectOutcome(
                        first.kind,
                        first.destination,
                        first.status,
                        "installed safely; stale transaction reference cleanup is pending",
                    )
                terminal = (
                    InstallStatus.CURRENT
                    if not applied_indexes and not state_changed
                    else InstallStatus.APPLIED
                )
                return Ok(
                    InstallOutcome(
                        plan.review_digest,
                        terminal,
                        tuple(outcomes),
                        state_changed,
                    )
                )
        except (OSError, RuntimeError) as error:
            rollback_errors: list[str] = []
            if state_attempted:
                try:
                    _restore(plan.state_precondition)
                except OSError as rollback_error:
                    rollback_errors.append(f"state: {rollback_error}")
            for _index, operation, snapshot in reversed(attempted):
                try:
                    _restore(snapshot)
                except OSError as rollback_error:
                    rollback_errors.append(f"{operation.destination}: {rollback_error}")
            if transaction_retained:
                released = _replace_reference(
                    plan,
                    ReferenceKind.TRANSACTION,
                    transaction_owner,
                    (),
                )
                if isinstance(released, Err):
                    rollback_errors.append("transaction object reference cleanup is pending")
            failure: list[EffectOutcome] = []
            for index, operation in enumerate(plan.operations):
                if index == failed_index:
                    detail = str(error)
                    if rollback_errors:
                        detail += "; rollback incomplete: " + "; ".join(rollback_errors)
                    failure.append(
                        EffectOutcome(_kind(operation), operation.destination, "failed", detail)
                    )
                elif index in applied_indexes:
                    failure.append(
                        EffectOutcome(
                            _kind(operation), operation.destination, "rolled-back", str(error)
                        )
                    )
                elif operation.precondition.digest == operation.desired_digest:
                    failure.append(
                        EffectOutcome(
                            _kind(operation), operation.destination, "current", str(error)
                        )
                    )
                else:
                    failure.append(
                        EffectOutcome(
                            _kind(operation), operation.destination, "skipped", str(error)
                        )
                    )
            return Ok(
                InstallOutcome(
                    plan.review_digest,
                    InstallStatus.FAILED,
                    tuple(failure),
                    False,
                )
            )
