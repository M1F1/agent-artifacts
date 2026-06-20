"""Consumer manifest — pure (WP-4). Build/diff/prune/serialize (DESIGN.md §12).

Reading/writing the manifest file is the shell's job; this module operates on text and
`Manifest` values only.
"""

from __future__ import annotations

from typing import Tuple

from .model import Manifest, ManifestEntry, Plan, Result

_TODO = "WP-4: not implemented"


def parse_manifest(text: str) -> Result:
    """Parse manifest JSON text -> Ok[Manifest] | Err (corrupt)."""
    raise NotImplementedError(_TODO)


def dump_manifest(m: Manifest) -> str:
    raise NotImplementedError(_TODO)


def empty_manifest(repo: str) -> Manifest:
    return Manifest(repo=repo, installed=())


def upsert(m: Manifest, entry: ManifestEntry) -> Manifest:
    """Return a new manifest with `entry` replacing any existing (artifact, profile)."""
    raise NotImplementedError(_TODO)


def remove_entry(m: Manifest, artifact: str, profile: str) -> Manifest:
    raise NotImplementedError(_TODO)


def entries_for(m: Manifest, profile: str) -> Tuple[ManifestEntry, ...]:
    raise NotImplementedError(_TODO)


def prune_plan(m: Manifest, keep: Tuple[Tuple[str, str], ...]) -> Plan:
    """Plan removal of installed entries whose (artifact, profile) is not in `keep`."""
    raise NotImplementedError(_TODO)
