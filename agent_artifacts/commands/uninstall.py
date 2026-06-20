"""uninstall command (WP-14). Reverse files AND merges; remove only our own entries.

This is the inverse of `install` (WP-12). For each selected `ManifestEntry` it:

- removes the entry's on-disk **files** (skills/guideline copies/hook scripts) — except for
  append-sentinel guidelines, whose "file" is a shared file (e.g. ``CLAUDE.md``): there we
  strip only our name-scoped sentinel block and rewrite the file (deleting it only when it
  becomes empty AND we created it);
- reverses the entry's **merge** (`ManifestEntry.merge`, a `MergeProof`): for ``mode=="key"``
  we delete our key under ``merge.json_path``; for ``mode=="list"`` we drop the single list
  element matching the recorded ``merge.identity`` — foreign entries are never touched. If the
  container empties out and ``merge.created_file`` is set, the config file is removed; otherwise
  the pruned config is written back.

Selection mirrors `install`: positional ``NAME…`` (matched against ``entry.artifact``),
``--bundle`` (``entry.bundle``), or ``--all``, optionally narrowed by ``--profile``.

The pure decision-making (what to remove, what the reversed config looks like) is kept in
small helpers; the imperative shell (reading/writing files, deleting paths) is confined to
`run` and the few `fs`-touching helpers it calls.

Exit codes (PLAN.md §7): OK=0, USAGE=2 (unknown ``NAME``), CORRUPT_MANIFEST=5 (bad manifest).
"""

from __future__ import annotations

import json
import os
from typing import List, Tuple

from ..executor import render_plan
from ..io import fs
from ..manifest import remove_entry
from ..model import (
    Err,
    Manifest,
    ManifestEntry,
    MergeProof,
    RemovePath,
)
from ..planners import sentinel_markers
from . import _common

OK = _common.OK
USAGE = _common.USAGE


# --------------------------------------------------------------------------- #
# Selection (pure): which installed entries does this invocation target?       #
# --------------------------------------------------------------------------- #
def _select(
    manifest: Manifest,
    *,
    names: Tuple[str, ...],
    bundles: Tuple[str, ...],
    all_: bool,
    profiles: Tuple[str, ...],
) -> Tuple[Tuple[ManifestEntry, ...], Tuple[str, ...]]:
    """Return ``(selected_entries, unknown_names)`` for this invocation.

    An entry is selected when it matches the requested ``--all`` / ``--bundle`` / ``NAME``
    criterion AND (if ``--profile`` was given) belongs to one of those profiles. ``names``
    that match no installed entry are reported back as ``unknown_names`` so the caller can
    fail with a USAGE error.
    """
    prof_filter = set(profiles)

    def in_profile(e: ManifestEntry) -> bool:
        return not prof_filter or e.profile in prof_filter

    selected: List[ManifestEntry] = []
    if all_:
        selected = [e for e in manifest.installed if in_profile(e)]
        return tuple(selected), ()

    if bundles:
        bset = set(bundles)
        selected = [e for e in manifest.installed if e.bundle in bset and in_profile(e)]

    unknown: List[str] = []
    for name in names:
        matches = [e for e in manifest.installed if e.artifact == name and in_profile(e)]
        if not matches:
            unknown.append(name)
        else:
            selected.extend(matches)

    # De-duplicate by (artifact, profile) preserving first-seen order.
    seen = set()
    deduped: List[ManifestEntry] = []
    for e in selected:
        key = (e.artifact, e.profile)
        if key not in seen:
            seen.add(key)
            deduped.append(e)
    return tuple(deduped), tuple(unknown)


# --------------------------------------------------------------------------- #
# Sentinel-block detection (pure): is a file path an append-sentinel guideline? #
# --------------------------------------------------------------------------- #
def _is_sentinel_file(entry: ManifestEntry, text: str) -> bool:
    """A guideline file is append-sentinel iff it carries our begin/end markers."""
    if entry.type != "guideline":
        return False
    begin, _ = sentinel_markers(entry.artifact)
    return begin in text


def _strip_sentinel_block(text: str, name: str) -> str:
    """Remove our ``name`` sentinel block from `text`, preserving foreign content.

    Inverse of ``planners._replace_sentinel_block``: deletes everything from the begin marker
    through the end marker (and one trailing newline), then tidies the surrounding blank line
    we inserted between foreign content and our block on install.
    """
    begin, end = sentinel_markers(name)
    start = text.find(begin)
    if start == -1:
        return text
    stop = text.find(end, start)
    if stop == -1:
        # Begin marker without a matching end: our block ran to EOF.
        cut = text[:start]
    else:
        stop_end = stop + len(end)
        tail = text[stop_end:]
        if tail.startswith("\n"):
            tail = tail[1:]
        cut = text[:start] + tail
    # On install we inserted one blank line before our block; drop the now-dangling one.
    if cut.endswith("\n\n"):
        cut = cut[:-1]
    return cut


# --------------------------------------------------------------------------- #
# Merge identity matching (pure): does a list element belong to OUR entry?      #
# --------------------------------------------------------------------------- #
def _collect_scalar_values(node) -> set:
    """All scalar values reachable inside `node` (dicts/lists recursed)."""
    out: set = set()
    if isinstance(node, dict):
        for v in node.values():
            out |= _collect_scalar_values(v)
    elif isinstance(node, list):
        for v in node:
            out |= _collect_scalar_values(v)
    elif isinstance(node, (str, int, float, bool)) or node is None:
        out.add(node)
    return out


def _element_matches_identity(element, identity) -> bool:
    """True when a list element carries every recorded identity field/value.

    The merge `entry_template` may nest an identity field (e.g. ``command`` lives inside
    ``hooks[].command`` while ``matcher`` is top-level), so we match each recorded
    ``field -> value`` if the value appears anywhere in the element's reachable scalars.
    Empty identity never matches (we must not remove an arbitrary element).
    """
    if not identity:
        return False
    values = _collect_scalar_values(element)
    return all(v in values for v in identity.values())


# --------------------------------------------------------------------------- #
# Merge reversal (pure-ish): compute the pruned config + whether to delete it.  #
# --------------------------------------------------------------------------- #
def _navigate(root: dict, json_path: str):
    """Walk `root` along the dotted `json_path`; return ``None`` if any segment is missing."""
    node = root
    for part in json_path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _reverse_merge(root: dict, proof: MergeProof) -> Tuple[dict, bool, bool]:
    """Return ``(new_root, changed, container_empty)`` after removing OUR merge from `root`.

    - key mode: ``proof.json_path`` is ``<container_path>.<our_key>``; delete that key.
    - list mode: ``proof.json_path`` addresses the list; drop the element matching
      ``proof.identity`` (only ours — foreign elements stay).
    ``container_empty`` reports whether the directly-containing collection is now empty (used
    with ``proof.created_file`` to decide file deletion).
    """
    parts = proof.json_path.split(".")
    if proof.mode == "key":
        parent = _navigate(root, ".".join(parts[:-1])) if len(parts) > 1 else root
        key = parts[-1]
        changed = isinstance(parent, dict) and key in parent
        if changed:
            del parent[key]
        container_empty = isinstance(parent, dict) and len(parent) == 0
        return root, changed, container_empty

    # list mode
    parent = _navigate(root, ".".join(parts[:-1])) if len(parts) > 1 else root
    list_key = parts[-1]
    current = parent.get(list_key) if isinstance(parent, dict) else None
    if not isinstance(current, list):
        return root, False, False
    kept = [el for el in current if not _element_matches_identity(el, proof.identity)]
    changed = len(kept) != len(current)
    parent[list_key] = kept
    container_empty = len(kept) == 0
    return root, changed, container_empty


# --------------------------------------------------------------------------- #
# Description helpers (for --dry-run / --json).                                 #
# --------------------------------------------------------------------------- #
def _describe_merge_reversal(proof: MergeProof) -> str:
    if proof.mode == "key":
        return f"merge-undo  {proof.file} [key] delete '{proof.json_path}'"
    ident = ", ".join(f"{k}={v!r}" for k, v in proof.identity.items())
    return f"merge-undo  {proof.file} [list] drop element at '{proof.json_path}' where {ident}"


# --------------------------------------------------------------------------- #
# Imperative shell: build & apply the reversal for one entry.                  #
# --------------------------------------------------------------------------- #
def _project_path(project: str, rel: str) -> str:
    return rel if os.path.isabs(rel) else os.path.normpath(os.path.join(project, rel))


def _file_actions(project: str, entry: ManifestEntry) -> Tuple[Tuple[RemovePath, ...], List[str]]:
    """Plan the file-side removals for `entry`.

    Returns ``(remove_actions, sentinel_paths)``: ordinary files become `RemovePath`
    actions; append-sentinel guideline files are handled separately (they're stripped, not
    deleted) and their resolved paths are returned for the shell to rewrite.
    """
    removes: List[RemovePath] = []
    sentinels: List[str] = []
    for rel in entry.files:
        abs_path = _project_path(project, rel)
        if entry.type == "guideline" and fs.exists(abs_path):
            text = fs.read_text(abs_path)
            if _is_sentinel_file(entry, text):
                sentinels.append(abs_path)
                continue
        removes.append(RemovePath(path=abs_path))
    return tuple(removes), sentinels


def _apply_sentinel(project: str, entry: ManifestEntry, abs_path: str) -> str:
    """Strip our sentinel block from a shared guideline file; rewrite or delete it.

    Removes the whole file only when stripping our block leaves it empty (a shared file like
    ``CLAUDE.md`` that now holds nothing but our former block). Foreign content keeps the
    file alive. Returns a one-line description for the report.
    """
    text = fs.read_text(abs_path)
    stripped = _strip_sentinel_block(text, entry.artifact)
    if stripped.strip() == "":
        fs.remove_path(abs_path)
        return f"sentinel    {abs_path} (block stripped, file emptied & removed)"
    fs.write_atomic(abs_path, stripped.encode("utf-8"))
    return f"sentinel    {abs_path} (block stripped)"


def _apply_merge(project: str, proof: MergeProof) -> str:
    """Reverse one merge on disk: prune our entry, then rewrite or delete the config file."""
    abs_file = _project_path(project, proof.file)
    if not fs.exists(abs_file):
        return f"merge-undo  {abs_file} (absent, nothing to do)"
    try:
        root = fs.read_json(abs_file)
    except (OSError, ValueError):
        return f"merge-undo  {abs_file} (unreadable, skipped)"
    if not isinstance(root, dict):
        return f"merge-undo  {abs_file} (not an object, skipped)"

    root, changed, container_empty = _reverse_merge(root, proof)
    if not changed:
        return f"merge-undo  {abs_file} (our entry not present)"

    if container_empty and proof.created_file:
        fs.remove_path(abs_file)
        return f"merge-undo  {abs_file} (emptied & removed)"

    fs.write_atomic(abs_file, json.dumps(root, indent=2).encode("utf-8"))
    return f"merge-undo  {abs_file} (our entry removed)"


# --------------------------------------------------------------------------- #
# Entry point.                                                                  #
# --------------------------------------------------------------------------- #
def run(request) -> int:
    project = _common.project_root(request)

    loaded = _common.load_manifest(request)
    if isinstance(loaded, Err):
        if request.json:
            _common.print_json({"ok": False, "error": loaded.reason, "code": loaded.code})
        else:
            print(loaded.reason)
        return loaded.code
    manifest: Manifest = loaded.value

    selected, unknown = _select(
        manifest,
        names=request.names,
        bundles=request.bundles,
        all_=request.all,
        profiles=request.profiles,
    )

    if unknown:
        msg = f"unknown installed artifact(s): {', '.join(sorted(unknown))}"
        if request.json:
            _common.print_json({"ok": False, "error": msg, "code": USAGE})
        else:
            print(msg)
        return USAGE

    if not selected:
        msg = "nothing to uninstall (no matching installed entries)"
        if request.json:
            _common.print_json({"ok": True, "removed": [], "message": msg})
        else:
            print(msg)
        return OK

    # Build the reversal plan (files + sentinel rewrites + merge undos) per entry.
    plan_removes: List[RemovePath] = []
    sentinel_jobs: List[Tuple[ManifestEntry, str]] = []
    merge_descs: List[str] = []
    file_render: List[RemovePath] = []
    for entry in selected:
        removes, sentinels = _file_actions(project, entry)
        plan_removes.extend(removes)
        file_render.extend(removes)
        for path in sentinels:
            sentinel_jobs.append((entry, path))
        if entry.merge is not None:
            merge_descs.append(_describe_merge_reversal(entry.merge))

    if request.dry_run:
        lines: List[str] = []
        if file_render:
            lines.append(render_plan(tuple(file_render)))
        for _, path in sentinel_jobs:
            lines.append(f"sentinel    {path} (strip our block)")
        lines.extend(merge_descs)
        text = "\n".join(l for l in lines if l)
        if request.json:
            _common.print_json({
                "ok": True,
                "dry_run": True,
                "removed_entries": [
                    {"artifact": e.artifact, "profile": e.profile, "type": e.type}
                    for e in selected
                ],
                "actions": text.splitlines(),
            })
        else:
            print(text or "nothing to do")
        return OK

    # --- execute (imperative shell) --- #
    performed: List[str] = []
    for action in plan_removes:
        fs.remove_path(action.path)
        performed.append(f"remove-path {action.path}")
    for entry, path in sentinel_jobs:
        performed.append(_apply_sentinel(project, entry, path))
    for entry in selected:
        if entry.merge is not None:
            performed.append(_apply_merge(project, entry.merge))

    # Update the manifest: drop each removed (artifact, profile) entry.
    new_manifest = manifest
    for entry in selected:
        new_manifest = remove_entry(new_manifest, entry.artifact, entry.profile)
    _common.save_manifest(project, new_manifest)

    if request.json:
        _common.print_json({
            "ok": True,
            "removed_entries": [
                {"artifact": e.artifact, "profile": e.profile, "type": e.type}
                for e in selected
            ],
            "actions": performed,
        })
    else:
        for line in performed:
            print(line)
        print(f"uninstalled {len(selected)} artifact(s)")
    return OK
