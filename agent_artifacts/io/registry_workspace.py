"""Non-following local registry checkout reader and reviewed file applier."""

from __future__ import annotations

import errno
import fcntl
import os
import stat
import tempfile
from pathlib import Path

from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.io.git import GitProcessRequest, run_git_process
from agent_artifacts.protocol.hashing import sha256_bytes
from agent_artifacts.protocol.native_tree import (
    SnapshotEntry,
    SnapshotEntryKind,
    SnapshotOrigin,
    SourceSnapshot,
)
from agent_artifacts.protocol.paths import SafeRelativePath, parse_relative_path
from agent_artifacts.registry_commands.model import (
    RegistryApplyCommand,
    RegistryApplyReceipt,
    WorkspaceChangeKind,
)
from agent_artifacts.registry_commands.planning import project_registry_workspace_plan

REGISTRY_WORKSPACE_INVALID = DiagnosticCode("registry-workspace-invalid")
REGISTRY_WORKSPACE_STALE = DiagnosticCode("registry-workspace-stale")
REGISTRY_WORKSPACE_APPLY_FAILED = DiagnosticCode("registry-workspace-apply-failed")
_ROOT_FILES = frozenset(
    {"aart-registry.json", "aart-source.json", "aart.lock.json", "aart.index.json", ".gitignore"}
)
# `security/` holds committed assessment evidence.  The reader has to see it for two reasons: a
# plan that writes an attestation is verified against a re-read snapshot, and `registry audit` reads
# `security/index.json` out of that same snapshot — a root it could not see was a root whose
# evidence it could never report.
_ROOT_DIRECTORIES = frozenset({"entries", "artifacts", "collections", "security"})
_GITHUB_DIRECTORIES = frozenset({".github", ".github/workflows", ".github/ISSUE_TEMPLATE"})
_GITHUB_FILES = frozenset(
    {
        ".github/ISSUE_TEMPLATE/usage-report.yml",
        ".github/workflows/aart-registry.yml",
        ".github/workflows/aart-usage-dashboard.yml",
        ".github/workflows/aart-usage-validate.yml",
    }
)
_MAX_ENTRIES = 100_000
_MAX_FILE_BYTES = 16 * 1024 * 1024
_MAX_TOTAL_BYTES = 256 * 1024 * 1024


def _error(code: DiagnosticCode, message: str, remediation: tuple[str, ...] = ()) -> Err:
    return Err((Diagnostic(code, Severity.ERROR, message, remediation=remediation),))


def _real_directory(path: Path) -> bool:
    try:
        return stat.S_ISDIR(os.stat(path, follow_symlinks=False).st_mode) and not path.is_symlink()
    except OSError:
        return False


def _managed(relative: str) -> bool:
    if relative in _ROOT_FILES or relative in _GITHUB_DIRECTORIES or relative in _GITHUB_FILES:
        return True
    return relative.split("/", 1)[0] in _ROOT_DIRECTORIES


def _safe_path(root: Path, relative: SafeRelativePath) -> Result[Path]:
    current = root
    for part in relative.parts[:-1]:
        current = current / part
        if not os.path.lexists(current):
            continue
        try:
            mode = os.stat(current, follow_symlinks=False).st_mode
        except OSError as error:
            return _error(REGISTRY_WORKSPACE_INVALID, f"cannot inspect registry path: {error}")
        if not stat.S_ISDIR(mode) or stat.S_ISLNK(mode):
            return _error(
                REGISTRY_WORKSPACE_INVALID,
                f"registry path parent is not a real directory: {relative}",
            )
    return Ok(root.joinpath(*relative.parts))


def _read_regular(path: Path, expected: os.stat_result) -> Result[bytes]:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_dev != expected.st_dev
                or opened.st_ino != expected.st_ino
                or opened.st_size != expected.st_size
            ):
                return _error(
                    REGISTRY_WORKSPACE_INVALID,
                    "registry file changed while being opened",
                )
            content = stream.read(_MAX_FILE_BYTES + 1)
    except OSError as error:
        return _error(REGISTRY_WORKSPACE_INVALID, f"cannot read registry file: {error}")
    if len(content) != expected.st_size or len(content) > _MAX_FILE_BYTES:
        return _error(REGISTRY_WORKSPACE_INVALID, "registry file changed while being read")
    return Ok(content)


class FilesystemRegistryWorkspace:
    """Read checks anywhere, but apply only to a writable local Git checkout."""

    def __init__(self, root: str):
        if not os.path.isabs(root) or os.path.normpath(root) != root:
            raise ValueError("registry workspace root must be normalized and absolute")
        self.root = Path(root)

    def snapshot(self) -> Result[SourceSnapshot]:
        if not _real_directory(self.root):
            return _error(REGISTRY_WORKSPACE_INVALID, "registry workspace must be a real directory")
        entries: list[SnapshotEntry] = []
        total_bytes = 0
        try:
            for directory, children, files in os.walk(self.root, topdown=True, followlinks=False):
                relative_directory = Path(directory).relative_to(self.root).as_posix()
                relative_directory = "" if relative_directory == "." else relative_directory
                children[:] = sorted(
                    child
                    for child in children
                    if child != ".git"
                    and _managed(
                        child if not relative_directory else f"{relative_directory}/{child}"
                    )
                )
                for child in children:
                    relative = child if not relative_directory else f"{relative_directory}/{child}"
                    target = Path(directory) / child
                    mode = os.stat(target, follow_symlinks=False).st_mode
                    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
                        return _error(
                            REGISTRY_WORKSPACE_INVALID,
                            f"registry managed directory is unsafe: {relative}",
                        )
                    parsed = parse_relative_path(relative)
                    if isinstance(parsed, Err):
                        return _error(REGISTRY_WORKSPACE_INVALID, "registry path is unsafe")
                    entries.append(SnapshotEntry(parsed.value, SnapshotEntryKind.DIRECTORY))
                for filename in sorted(files):
                    relative = (
                        filename if not relative_directory else f"{relative_directory}/{filename}"
                    )
                    if relative.startswith(".git/") or not _managed(relative):
                        continue
                    target = Path(directory) / filename
                    status = os.stat(target, follow_symlinks=False)
                    mode = status.st_mode
                    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
                        return _error(
                            REGISTRY_WORKSPACE_INVALID,
                            f"registry managed file is unsafe: {relative}",
                        )
                    size = status.st_size
                    if size > _MAX_FILE_BYTES:
                        return _error(
                            REGISTRY_WORKSPACE_INVALID, "registry file exceeds size bound"
                        )
                    read = _read_regular(target, status)
                    if isinstance(read, Err):
                        return read
                    total_bytes += len(read.value)
                    if total_bytes > _MAX_TOTAL_BYTES:
                        return _error(
                            REGISTRY_WORKSPACE_INVALID, "registry exceeds total-size bound"
                        )
                    parsed = parse_relative_path(relative)
                    if isinstance(parsed, Err):
                        return _error(REGISTRY_WORKSPACE_INVALID, "registry path is unsafe")
                    entries.append(
                        SnapshotEntry(
                            parsed.value,
                            SnapshotEntryKind.FILE,
                            read.value,
                            bool(mode & 0o111),
                        )
                    )
                    if len(entries) > _MAX_ENTRIES:
                        return _error(REGISTRY_WORKSPACE_INVALID, "registry exceeds entry bound")
        except OSError as error:
            return _error(REGISTRY_WORKSPACE_INVALID, f"cannot read registry workspace: {error}")
        return Ok(SourceSnapshot(SnapshotOrigin.LOCAL, tuple(entries)))

    def current(self) -> Result[SourceSnapshot]:
        """Port-compatible alias that keeps snapshot acquisition explicit and read-only."""

        return self.snapshot()

    def _writable_checkout(self) -> bool:
        if not _real_directory(self.root):
            return False
        try:
            mode = os.stat(self.root, follow_symlinks=False).st_mode
            git = self.root / ".git"
            git_mode = os.stat(git, follow_symlinks=False).st_mode
        except OSError:
            return False
        structurally_writable = (
            bool(mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
            and (stat.S_ISDIR(git_mode) or stat.S_ISREG(git_mode))
            and not git.is_symlink()
        )
        if not structurally_writable:
            return False
        verified = run_git_process(
            GitProcessRequest(
                (
                    "git",
                    "-c",
                    "core.hooksPath=/dev/null",
                    "-C",
                    str(self.root),
                    "rev-parse",
                    "--is-inside-work-tree",
                ),
                str(self.root),
                10,
                max_output_bytes=128,
            )
        )
        return isinstance(verified, Ok) and verified.value.stdout.strip() == b"true"

    def verify_mutation_target(self) -> Result[None]:
        """Prove that reviewed writes would target an explicit writable local Git checkout."""

        if not self._writable_checkout():
            nested = run_git_process(
                GitProcessRequest(
                    (
                        "git",
                        "-c",
                        "core.hooksPath=/dev/null",
                        "-C",
                        str(self.root),
                        "rev-parse",
                        "--show-toplevel",
                    ),
                    str(self.root),
                    10,
                    max_output_bytes=4096,
                )
            )
            top = os.fsdecode(nested.value.stdout).strip() if isinstance(nested, Ok) else ""
            if top and os.path.abspath(top) != str(self.root):
                remediation = (
                    f"the registry must be the repository root, not {self.root} inside {top}; "
                    "move it to its own checkout or use the repository root as --source",
                )
            elif not os.path.lexists(self.root / ".git"):
                remediation = (f"initialize this registry checkout with: git -C {self.root} init",)
            else:
                remediation = (
                    f"make {self.root} writable and repair its Git checkout, then run git status",
                )
            return _error(
                REGISTRY_WORKSPACE_INVALID,
                "registry mutation requires a writable local Git checkout",
                remediation,
            )
        return Ok(None)

    def _write(self, path: SafeRelativePath, content: bytes, executable: bool) -> Result[None]:
        target = _safe_path(self.root, path)
        if isinstance(target, Err):
            return target
        try:
            target.value.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            descriptor, temporary = tempfile.mkstemp(
                prefix=f".{target.value.name}.aart-registry-",
                dir=target.value.parent,
            )
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.chmod(temporary, 0o700 if executable else 0o600)
                os.replace(temporary, target.value)
            finally:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass
            return Ok(None)
        except OSError as error:
            return _error(REGISTRY_WORKSPACE_APPLY_FAILED, f"cannot write registry file: {error}")

    def _remove(self, path: SafeRelativePath) -> Result[None]:
        """Unlink one reviewed file, leaving the directory that held it.

        Rollback restores the bytes from the backup taken immediately before, so a removal is as
        recoverable as an overwrite. The emptied directory stays because Git does not track empty
        directories and the applier verifies itself against a re-read snapshot that would still
        contain it.
        """

        target = _safe_path(self.root, path)
        if isinstance(target, Err):
            return target
        try:
            os.unlink(target.value)
        except FileNotFoundError:
            return Ok(None)
        except OSError as error:
            return _error(REGISTRY_WORKSPACE_APPLY_FAILED, f"cannot remove registry file: {error}")
        return Ok(None)

    def _backup(self, path: SafeRelativePath) -> Result[tuple[bytes | None, bool]]:
        safe = _safe_path(self.root, path)
        if isinstance(safe, Err):
            return safe
        try:
            status = os.stat(safe.value, follow_symlinks=False)
        except FileNotFoundError:
            return Ok((None, False))
        except OSError as error:
            return _error(
                REGISTRY_WORKSPACE_INVALID,
                f"cannot inspect registry mutation target: {error}",
            )
        if stat.S_ISLNK(status.st_mode) or not stat.S_ISREG(status.st_mode):
            return _error(
                REGISTRY_WORKSPACE_INVALID,
                f"registry mutation target is not a regular file: {path}",
            )
        content = _read_regular(safe.value, status)
        if isinstance(content, Err):
            return content
        return Ok((content.value, bool(status.st_mode & 0o111)))

    def _rollback(
        self,
        backups: list[tuple[SafeRelativePath, bytes | None, bool]],
        preserved_directories: set[str],
    ) -> Result[None]:
        for path, content, was_executable in reversed(backups):
            target = self.root.joinpath(*path.parts)
            if content is None:
                try:
                    target.unlink()
                except FileNotFoundError:
                    pass
                except OSError as error:
                    return _error(
                        REGISTRY_WORKSPACE_APPLY_FAILED,
                        f"cannot roll back registry file: {error}",
                    )
            else:
                restored = self._write(path, content, was_executable)
                if isinstance(restored, Err):
                    return restored
        parents = {
            "/".join(path.parts[:length])
            for path, content, _executable in backups
            if content is None
            for length in range(1, len(path.parts))
        }
        for relative in sorted(parents, key=lambda item: (-item.count("/"), item)):
            if relative in preserved_directories:
                continue
            try:
                self.root.joinpath(*relative.split("/")).rmdir()
            except FileNotFoundError:
                pass
            except OSError as error:
                if error.errno != errno.ENOTEMPTY:
                    return _error(
                        REGISTRY_WORKSPACE_APPLY_FAILED,
                        f"cannot roll back registry directory: {error}",
                    )
        return Ok(None)

    def apply(self, command: RegistryApplyCommand) -> Result[RegistryApplyReceipt]:
        target = self.verify_mutation_target()
        if isinstance(target, Err):
            return target
        descriptor: int | None = None
        try:
            descriptor = os.open(self.root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if descriptor is not None:
                os.close(descriptor)
            return _error(
                REGISTRY_WORKSPACE_STALE,
                "another registry mutation is already in progress",
            )
        except OSError as error:
            if descriptor is not None:
                os.close(descriptor)
            return _error(
                REGISTRY_WORKSPACE_INVALID,
                f"cannot lock registry workspace: {error}",
            )
        assert descriptor is not None
        try:
            return self._apply_locked(command)
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _apply_locked(self, command: RegistryApplyCommand) -> Result[RegistryApplyReceipt]:
        current = self.snapshot()
        if isinstance(current, Err):
            return current
        projected = project_registry_workspace_plan(current.value, command.plan)
        if isinstance(projected, Err):
            return _error(REGISTRY_WORKSPACE_STALE, "registry workspace changed after review")
        preserved_directories = {
            str(item.path)
            for item in current.value.entries
            if item.kind is SnapshotEntryKind.DIRECTORY
        }
        backups: list[tuple[SafeRelativePath, bytes | None, bool]] = []
        for change in command.plan.changes:
            if change.kind is WorkspaceChangeKind.UNCHANGED:
                continue
            backup = self._backup(change.path)
            if isinstance(backup, Err):
                rolled_back = self._rollback(backups, preserved_directories)
                return backup if isinstance(rolled_back, Ok) else rolled_back
            before, executable = backup.value
            actual_before_digest = None if before is None else sha256_bytes(before)
            if actual_before_digest != change.before_digest or (
                before is not None and executable != change.executable
            ):
                rolled_back = self._rollback(backups, preserved_directories)
                if isinstance(rolled_back, Err):
                    return rolled_back
                return _error(
                    REGISTRY_WORKSPACE_STALE,
                    f"registry mutation target changed after review: {change.path}",
                )
            backups.append((change.path, before, executable))
            written = (
                self._remove(change.path)
                if change.kind is WorkspaceChangeKind.REMOVED
                else self._write(change.path, change.content, change.executable)
            )
            if isinstance(written, Err):
                rolled_back = self._rollback(backups, preserved_directories)
                return written if isinstance(rolled_back, Ok) else rolled_back
        verified = self.snapshot()
        if isinstance(verified, Err):
            rolled_back = self._rollback(backups, preserved_directories)
            return verified if isinstance(rolled_back, Ok) else rolled_back
        verified_projection = project_registry_workspace_plan(current.value, command.plan)
        assert isinstance(verified_projection, Ok)
        if verified.value != verified_projection.value:
            failed = _error(
                REGISTRY_WORKSPACE_APPLY_FAILED,
                "registry apply verification failed",
            )
            rolled_back = self._rollback(backups, preserved_directories)
            return failed if isinstance(rolled_back, Ok) else rolled_back
        return Ok(
            RegistryApplyReceipt(
                command.plan.review_digest,
                command.plan.next_snapshot_digest,
                command.plan.changed_paths,
            )
        )
