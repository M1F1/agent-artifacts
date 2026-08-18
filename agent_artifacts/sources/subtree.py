"""Take one subtree of an acquired snapshot, for vendoring (VN-1).

`registry promote-native` requires the upstream repository to already speak AART. Vendoring exists
for the ones that do not (design §1), so what it acquires is a *part* of a repository that has no
markers, no `artifact_roots`, and no manifest — `--path servers/foo` rather than a whole source.

This module is that step and only that step: it re-roots one subtree of an already acquired
snapshot, applies `SnapshotLimits` to what was taken rather than to the repository it came from, and
returns the deterministic digest of the result — the value that becomes
`OriginProvenance.input_digest`, so two vendorings of one upstream state are comparable.

It acquires nothing itself. Everything AART already applies to a source snapshot has therefore
already applied: credential-free URLs, a cleared Git environment, `SafeRelativePath`, and the
refusals in `git.py` and `local.py`. What is added here fails closed in three ways — a subtree that
would produce an empty package, an entry the canonical package format cannot carry, and a symlink
whose target leaves the subtree (design §5).
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass

from agent_artifacts.domain.diagnostics import Diagnostic, Severity
from agent_artifacts.domain.identifiers import ObjectDigest
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.protocol.native_tree import (
    SnapshotEntry,
    SnapshotEntryKind,
    SnapshotOrigin,
    SourceSnapshot,
)
from agent_artifacts.protocol.paths import SafeRelativePath, parse_relative_path

from .model import SOURCE_INVALID, SnapshotLimits, source_snapshot_digest

# The default bound, as one value rather than a call in a signature: `SnapshotLimits()` already
# carries AART's standing limits, and vendoring has no reason to hold a different set.
_DEFAULT_LIMITS = SnapshotLimits()


def _error(message: str) -> Err:
    return Err((Diagnostic(SOURCE_INVALID, Severity.ERROR, message),))


@dataclass(frozen=True, slots=True)
class TakenSubtree:
    """One subtree, re-rooted, with the evidence a vendored package has to record."""

    path: SafeRelativePath
    snapshot: SourceSnapshot
    input_digest: ObjectDigest
    files: int
    total_bytes: int


def _symlink_target(entry: SnapshotEntry, link: str) -> Result[str]:
    try:
        target = entry.content.decode("utf-8")
    except UnicodeDecodeError:
        return _error(f"subtree symlink target is not UTF-8: {link}")
    if not target:
        return _error(f"subtree symlink has an empty target: {link}")
    return Ok(target)


def _escapes(link: str, target: str) -> bool:
    """Does following ``target`` from ``link`` leave the subtree?

    Judged inside the subtree's own coordinate space, after re-rooting, because that is the tree the
    maintainer reviewed and the one the vendored package will contain. An absolute target leaves it
    by definition — there is no root to be relative to once the bytes are in someone else's registry.
    """

    if posixpath.isabs(target):
        return True
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(link), target))
    return resolved == ".." or resolved.startswith("../")


def take_subtree(
    snapshot: SourceSnapshot,
    path: SafeRelativePath,
    *,
    limits: SnapshotLimits = _DEFAULT_LIMITS,
) -> Result[TakenSubtree]:
    """Re-root ``path`` out of ``snapshot``, or refuse and say which rule refused.

    The origin must be immutable Git: a vendored artifact's provenance binds a resolved commit, and
    a local tree has none to bind. Limits apply to the taken subtree, not to the repository — a
    monorepo far past `max_total_bytes` may still hold one small vendorable directory, and refusing
    it for the size of content nobody asked for would be the wrong boundary.
    """

    if snapshot.origin is not SnapshotOrigin.IMMUTABLE_GIT:
        return _error("a vendored subtree must be taken from an immutable Git snapshot")
    prefix = f"{path}/"
    at_path = next((item for item in snapshot.entries if str(item.path) == str(path)), None)
    single_file = at_path is not None and at_path.kind is SnapshotEntryKind.FILE
    entries: list[SnapshotEntry] = []
    files = 0
    total_bytes = 0
    for entry in snapshot.entries:
        raw = str(entry.path)
        if single_file:
            if entry is not at_path:
                continue
            relative = path.parts[-1]
        else:
            if not raw.startswith(prefix):
                continue
            relative = raw.removeprefix(prefix)
        parsed = parse_relative_path(relative)
        if isinstance(parsed, Err):
            return _error(f"the subtree contains an unsafe relative path: {raw}")
        if len(parsed.value.parts) > limits.max_depth:
            return _error(f"the subtree exceeds the configured directory depth: {relative}")
        if entry.kind is SnapshotEntryKind.SYMLINK:
            target = _symlink_target(entry, relative)
            if isinstance(target, Err):
                return target
            if _escapes(relative, target.value):
                return _error(f"the subtree symlink {relative} leaves it, targeting {target.value}")
            # A contained link is refused too, and for a different reason worth stating: the
            # canonical package tree has no symlink representation at all — `tree_digest` knows
            # files and directories — so carrying one is a format change, not a policy choice.
            return _error(
                f"a canonical package cannot carry the subtree symlink {relative} "
                f"targeting {target.value}"
            )
        if entry.kind is SnapshotEntryKind.SPECIAL:
            return _error(f"the subtree contains a special file: {relative}")
        if entry.kind is SnapshotEntryKind.DIRECTORY:
            entries.append(SnapshotEntry(parsed.value, SnapshotEntryKind.DIRECTORY))
            continue
        files += 1
        if files > limits.max_files:
            return _error("the subtree exceeds the configured file-count limit")
        if len(entry.content) > limits.max_file_bytes:
            return _error(f"the subtree file exceeds the configured size limit: {relative}")
        total_bytes += len(entry.content)
        if total_bytes > limits.max_total_bytes:
            return _error("the subtree exceeds the configured total-size limit")
        entries.append(
            SnapshotEntry(
                parsed.value,
                SnapshotEntryKind.FILE,
                entry.content,
                entry.executable,
            )
        )
    if not files:
        return _error(f"the requested subtree holds no files: {path}")
    taken = SourceSnapshot(SnapshotOrigin.IMMUTABLE_GIT, tuple(entries))
    digest = source_snapshot_digest(taken)
    if isinstance(digest, Err):
        return digest
    return Ok(TakenSubtree(path, taken, digest.value, files, total_bytes))
