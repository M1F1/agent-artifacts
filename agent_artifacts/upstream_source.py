"""Resolve and hash upstream artifact sources.

The first implementation targets GitHub repos using the existing network/cache layer.
"""

from __future__ import annotations

import hashlib
import os
import posixpath
import tarfile
from dataclasses import dataclass
from typing import Optional

from .github_source import resolve_github_location
from .hashing import sha256_file
from .io import cache, net
from .model import Err, Ok, Result
from .upstreams import UpstreamEntry


@dataclass(frozen=True, slots=True)
class ResolvedUpstream:
    entry: UpstreamEntry
    sha: str
    root: str
    path: str
    content_hash: str


def resolve_upstream_source(entry: UpstreamEntry, *, opener=None, token=None) -> Result:
    """Resolve, materialize, and hash one upstream entry.

    The implementation is intentionally GitHub-only for the first upstream tracking slice.
    Network access stays injectable through ``opener`` and immutable snapshots are delegated
    to :mod:`agent_artifacts.io.cache`.
    """
    source = entry.source
    if source.kind != "github":
        return Err(f"unsupported upstream source kind: {source.kind!r}", code=2)

    location = resolve_github_location(source)
    if isinstance(location, Err):
        return location

    rel = _normalise_snapshot_path(source.path)
    if rel is None:
        return Err(f"invalid upstream path {source.path!r}", code=2)

    resolved = net.resolve_ref(
        location.value.repo,
        source.ref,
        token=token,
        opener=opener,
        api_url=location.value.api_url,
    )
    if isinstance(resolved, Err):
        return resolved
    sha = resolved.value

    try:
        root = cache.ensure_snapshot(
            location.value.cache_key,
            sha,
            lambda: net.fetch_tarball(
                location.value.repo,
                sha,
                token=token,
                opener=opener,
                api_url=location.value.api_url,
            ),
        )
    except (OSError, tarfile.TarError, EOFError) as exc:
        return Err(f"failed to materialise upstream {location.value.repo}@{sha}: {exc}", code=3)

    path = os.path.abspath(os.path.join(root, *rel.split("/"))) if rel else os.path.abspath(root)
    root_abs = os.path.abspath(root)
    if path != root_abs and not path.startswith(root_abs + os.sep):
        return Err(f"invalid upstream path {source.path!r}", code=2)

    if not os.path.exists(path):
        return Err(
            f"missing_upstream: {location.value.repo}@{sha} has no path {source.path!r}",
            code=3,
        )

    try:
        content_hash = hash_upstream_path(path)
    except OSError as exc:
        return Err(f"failed to hash upstream path {source.path!r}: {exc}", code=3)

    return Ok(
        ResolvedUpstream(
            entry=entry,
            sha=sha,
            root=root_abs,
            path=path,
            content_hash=content_hash,
        )
    )


def hash_upstream_path(path: str) -> str:
    """Return a deterministic ``sha256:...`` hash for a file or directory tree."""
    if os.path.islink(path):
        return _hash_symlink(path)
    if os.path.isfile(path):
        return sha256_file(path)
    if os.path.isdir(path):
        return _hash_tree(path)
    raise FileNotFoundError(path)


def _normalise_snapshot_path(path: str) -> Optional[str]:
    raw = path.strip()
    if not raw:
        return ""
    if raw.startswith("/"):
        return None
    norm = posixpath.normpath(raw)
    if norm == ".":
        return ""
    if norm == ".." or norm.startswith("../"):
        return None
    return norm


def _hash_tree(path: str) -> str:
    h = hashlib.sha256()
    _update_token(h, b"agent-artifacts-tree-v1")
    root = os.path.abspath(path)

    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        dirs.sort()
        files.sort()

        kept_dirs = []
        for dirname in dirs:
            full = os.path.join(current, dirname)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if os.path.islink(full):
                _hash_tree_symlink_entry(h, rel, full)
            else:
                _update_token(h, b"dir")
                _update_token(h, rel.encode("utf-8"))
                kept_dirs.append(dirname)
        dirs[:] = kept_dirs

        for filename in files:
            full = os.path.join(current, filename)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if os.path.islink(full):
                _hash_tree_symlink_entry(h, rel, full)
            elif os.path.isfile(full):
                _hash_tree_file_entry(h, rel, full)

    return "sha256:" + h.hexdigest()


def _hash_tree_file_entry(h: "hashlib._Hash", rel: str, path: str) -> None:
    _update_token(h, b"file")
    _update_token(h, rel.encode("utf-8"))
    _update_token(h, str(os.path.getsize(path)).encode("ascii"))
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)


def _hash_tree_symlink_entry(h: "hashlib._Hash", rel: str, path: str) -> None:
    _update_token(h, b"symlink")
    _update_token(h, rel.encode("utf-8"))
    _update_token(h, os.readlink(path).encode("utf-8", "surrogateescape"))


def _hash_symlink(path: str) -> str:
    h = hashlib.sha256()
    _update_token(h, b"agent-artifacts-symlink-v1")
    _update_token(h, os.readlink(path).encode("utf-8", "surrogateescape"))
    return "sha256:" + h.hexdigest()


def _update_token(h: "hashlib._Hash", data: bytes) -> None:
    h.update(str(len(data)).encode("ascii"))
    h.update(b":")
    h.update(data)
    h.update(b";")
