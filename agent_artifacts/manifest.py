"""Consumer manifest — pure (WP-4). Build/diff/prune/serialize (DESIGN.md §12).

Reading/writing the manifest file is the shell's job; this module operates on text and
`Manifest` values only.
"""

from __future__ import annotations

import json
from typing import Tuple

from .fp import Err, Ok
from .model import (
    Manifest,
    ManifestEntry,
    MergeProof,
    Plan,
    RemovePath,
    Result,
    WriteManifest,
)

_TODO = "WP-4: not implemented"

# Exit code for a corrupt manifest (PLAN.md §7).
_CORRUPT = 5


# --------------------------------------------------------------------------- #
# Serialization (deterministic, stable field order).                          #
# --------------------------------------------------------------------------- #
def _merge_to_dict(p: MergeProof) -> dict:
    """`MergeProof` -> plain dict with a stable field order. Omits identity when empty."""
    out: dict = {
        "file": p.file,
        "json_path": p.json_path,
        "mode": p.mode,
    }
    # identity is only meaningful for list-mode merges (DESIGN.md §12 examples).
    if p.identity:
        out["identity"] = dict(p.identity)
    out["value_hash"] = p.value_hash
    out["created_file"] = p.created_file
    out["overwrote"] = p.overwrote
    return out


def _entry_to_dict(e: ManifestEntry) -> dict:
    """`ManifestEntry` -> plain dict. Omits `bundle`/`merge` when None; `files` always present."""
    out: dict = {
        "artifact": e.artifact,
        "type": e.type,
        "profile": e.profile,
        "source": e.source,
    }
    if e.bundle is not None:
        out["bundle"] = e.bundle
    out["files"] = dict(e.files)
    if e.merge is not None:
        out["merge"] = _merge_to_dict(e.merge)
    out["installed_at"] = e.installed_at
    return out


def dump_manifest(m: Manifest) -> str:
    """Serialize a `Manifest` to deterministic, indented JSON text.

    Field order is stable (we build ordered dicts and pass ``sort_keys=False``) so that
    round-tripping through `parse_manifest` and re-dumping is a no-op.
    """
    payload = {
        "repo": m.repo,
        "installed": [_entry_to_dict(e) for e in m.installed],
    }
    return json.dumps(payload, indent=2, sort_keys=False)


# --------------------------------------------------------------------------- #
# Parsing (text -> Result[Manifest]).                                         #
# --------------------------------------------------------------------------- #
class _Corrupt(Exception):
    """Internal signal for a structurally invalid manifest."""


def _require(obj: object, key: str) -> object:
    if not isinstance(obj, dict) or key not in obj:
        raise _Corrupt(f"missing required field: {key!r}")
    return obj[key]


def _merge_from_dict(d: object) -> MergeProof:
    if not isinstance(d, dict):
        raise _Corrupt("merge must be an object")
    identity = d.get("identity", {})
    if not isinstance(identity, dict):
        raise _Corrupt("merge.identity must be an object")
    return MergeProof(
        file=_require(d, "file"),
        json_path=_require(d, "json_path"),
        mode=_require(d, "mode"),
        identity=dict(identity),
        value_hash=_require(d, "value_hash"),
        created_file=bool(d.get("created_file", False)),
        overwrote=bool(d.get("overwrote", False)),
    )


def _entry_from_dict(d: object) -> ManifestEntry:
    if not isinstance(d, dict):
        raise _Corrupt("installed entry must be an object")
    files = d.get("files", {})
    if not isinstance(files, dict):
        raise _Corrupt("entry.files must be an object")
    merge = d.get("merge")
    return ManifestEntry(
        artifact=_require(d, "artifact"),
        type=_require(d, "type"),
        profile=_require(d, "profile"),
        source=_require(d, "source"),
        bundle=d.get("bundle"),
        files=dict(files),
        merge=_merge_from_dict(merge) if merge is not None else None,
        installed_at=d.get("installed_at", ""),
    )


def parse_manifest(text: str) -> Result:
    """Parse manifest JSON text -> Ok[Manifest] | Err (corrupt, code 5)."""
    try:
        raw = json.loads(text)
        if not isinstance(raw, dict):
            raise _Corrupt("manifest must be a JSON object")
        repo = _require(raw, "repo")
        installed_raw = raw.get("installed", [])
        if not isinstance(installed_raw, list):
            raise _Corrupt("installed must be a list")
        entries = tuple(_entry_from_dict(e) for e in installed_raw)
        return Ok(Manifest(repo=repo, installed=entries))
    except (json.JSONDecodeError, _Corrupt) as exc:
        return Err(f"corrupt manifest: {exc}", code=_CORRUPT)


# --------------------------------------------------------------------------- #
# Construction.                                                               #
# --------------------------------------------------------------------------- #
def empty_manifest(repo: str) -> Manifest:
    return Manifest(repo=repo, installed=())


def upsert(m: Manifest, entry: ManifestEntry) -> Manifest:
    """Return a new manifest with `entry` replacing any existing (artifact, profile).

    If no entry shares the `(artifact, profile)` key, `entry` is appended; otherwise it
    replaces the match in place, preserving the order of all other entries.
    """
    key = (entry.artifact, entry.profile)
    replaced = False
    out = []
    for existing in m.installed:
        if (existing.artifact, existing.profile) == key:
            out.append(entry)
            replaced = True
        else:
            out.append(existing)
    if not replaced:
        out.append(entry)
    return Manifest(repo=m.repo, installed=tuple(out))


def remove_entry(m: Manifest, artifact: str, profile: str) -> Manifest:
    """Return a new manifest with the `(artifact, profile)` entry filtered out."""
    key = (artifact, profile)
    kept = tuple(
        e for e in m.installed if (e.artifact, e.profile) != key
    )
    return Manifest(repo=m.repo, installed=kept)


def entries_for(m: Manifest, profile: str) -> Tuple[ManifestEntry, ...]:
    """All installed entries belonging to `profile`, in manifest order."""
    return tuple(e for e in m.installed if e.profile == profile)


# --------------------------------------------------------------------------- #
# Pruning (manifest -> Plan).                                                 #
# --------------------------------------------------------------------------- #
def prune_plan(m: Manifest, keep: Tuple[Tuple[str, str], ...]) -> Plan:
    """Plan removal of installed entries whose `(artifact, profile)` is not in `keep`.

    Emits a `RemovePath` for every file of each dropped entry (in manifest/file order),
    then a single trailing `WriteManifest` carrying only the surviving (kept) entries.
    """
    keep_set = set(keep)
    actions: list = []
    survivors = []
    for entry in m.installed:
        if (entry.artifact, entry.profile) in keep_set:
            survivors.append(entry)
        else:
            for path in entry.files:
                actions.append(RemovePath(path=path))
    actions.append(WriteManifest(entries=tuple(survivors)))
    return tuple(actions)
