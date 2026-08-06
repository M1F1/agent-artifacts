"""uninstall command (WP-14). Reverse files AND merges; remove only our own entries.

This is the inverse of `install` (WP-12). For each selected `ManifestEntry` it:

- removes the entry's on-disk **files** (skills/guideline copies/hook scripts) — except for
  sentinel-wrapped **memory** files (``prepend``/``append`` into a shared file like
  ``CLAUDE.md``): there we strip only our name-scoped block and rewrite the file (deleting it
  only when it becomes empty);
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

Exit codes (docs/plan/PLAN.md §7): OK=0, USAGE=2 (unknown ``NAME``), CORRUPT_MANIFEST=5 (bad manifest).
"""

from __future__ import annotations

import json
import os
from typing import List, Optional, Tuple

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
from ..outcomes import (
    ActionSummary,
    CommandOutcome,
    OutcomeItem,
    OutcomeStatus,
    outcome_key,
    outcome_payload,
    render_outcome,
)
from ..planners import memory_sentinel_markers
from . import _common

OK = _common.OK
USAGE = _common.USAGE

# Suffix of the backup file `plan_memory` writes before a destructive ``replace`` (mirrors
# ``planners._BAK_SUFFIX``); uninstall restores it when removing a replaced ``memory`` file.
_BAK_SUFFIX = ".agent-artifacts-bak"


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
# Sentinel-block detection (pure): does a shared file carry OUR marker block?    #
# --------------------------------------------------------------------------- #
def _markers_for(entry: ManifestEntry) -> Tuple[str, str]:
    """The ``(begin, end)`` HTML-comment markers wrapping our ``memory`` block.

    Only ``memory`` entries carry a marker block (docs/design/DESIGN-memory.md §3.3); they are stripped
    by `_strip_block` on uninstall.
    """
    return memory_sentinel_markers(entry.artifact)


def _is_sentinel_file(entry: ManifestEntry, text: str) -> bool:
    """A shared ``memory`` file is sentinel-managed iff it carries our begin marker.

    Only ``memory`` (``prepend``/``append``) entries write a marker block; a copied or
    replaced file (including every guideline) carries no begin marker and is removed normally.
    """
    if entry.type != "memory":
        return False
    begin, _ = _markers_for(entry)
    return begin in text


def _strip_block(text: str, begin: str, end: str) -> str:
    """Remove the ``begin…end`` block from `text`, preserving foreign content.

    Inverse of ``planners._replace_marked_block``: deletes everything from the begin marker
    through the end marker (and one trailing newline), then tidies the blank line we inserted
    between foreign content and our block on install (used by the ``memory`` reversal).
    """
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
    # On install we inserted one blank line beside our block; drop the now-dangling one.
    if cut.endswith("\n\n"):
        cut = cut[:-1]
    # A "prepend" block sits at the top, so the dangling blank line is leading, not trailing.
    if cut.startswith("\n"):
        cut = cut[1:]
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


def _resolve_link_target(link_path: str, raw_target: str) -> str:
    if os.path.isabs(raw_target):
        return os.path.normpath(raw_target)
    return os.path.normpath(os.path.join(os.path.dirname(link_path), raw_target))


def _link_conflicts(project: str, entries: Tuple[ManifestEntry, ...]) -> Tuple[str, ...]:
    """Symlink-managed paths that were replaced or retargeted and need ``--force``."""
    conflicts: List[str] = []
    for entry in entries:
        for link in entry.install.links:
            abs_path = _project_path(project, link.path)
            if not os.path.lexists(abs_path):
                continue
            if not os.path.islink(abs_path):
                conflicts.append(f"{link.path}: replaced")
                continue
            actual = _resolve_link_target(abs_path, os.readlink(abs_path))
            if os.path.normpath(actual) != os.path.normpath(link.target):
                conflicts.append(f"{link.path}: retargeted to {actual}")
    return tuple(conflicts)


def _file_actions(
    project: str, entry: ManifestEntry
) -> Tuple[Tuple[RemovePath, ...], List[str], List[str]]:
    """Plan the file-side removals for `entry`.

    Returns ``(remove_actions, sentinel_paths, restore_paths)``:

    - ordinary files (skill/guideline copies, hook scripts) become `RemovePath` actions;
    - a memory (``prepend``/``append``) file carrying our marker block is stripped, not
      deleted — its resolved path lands in ``sentinel_paths`` for the shell to rewrite;
    - a removed **memory** file (``replace`` or ``dir`` copy) is recorded in ``restore_paths``
      so the shell can restore a sibling ``<dest>.agent-artifacts-bak`` afterwards, undoing a
      destructive ``replace`` (docs/design/DESIGN-memory.md §8.3).
    """
    removes: List[RemovePath] = []
    sentinels: List[str] = []
    restores: List[str] = []
    for rel in entry.files:
        abs_path = _project_path(project, rel)
        if entry.type == "memory" and fs.exists(abs_path):
            text = fs.read_text(abs_path)
            if _is_sentinel_file(entry, text):
                sentinels.append(abs_path)
                continue
        removes.append(RemovePath(path=abs_path))
        if entry.type == "memory":
            # A non-sentinel memory file is a replace/dir copy: try the .bak restore on removal.
            restores.append(abs_path)
    return tuple(removes), sentinels, restores


def _apply_sentinel(project: str, entry: ManifestEntry, abs_path: str) -> str:
    """Strip our marker block from a shared ``memory`` file; rewrite or delete it.

    Removes the whole file only when stripping our block leaves it empty (a shared file like
    ``CLAUDE.md`` that now holds nothing but our former block). Foreign content keeps the
    file alive. Returns a description.
    """
    if not os.path.exists(abs_path):
        return f"sentinel    {abs_path} (already removed)"
    text = fs.read_text(abs_path)
    begin, end = _markers_for(entry)
    stripped = _strip_block(text, begin, end)
    if stripped.strip() == "":
        fs.remove_path(abs_path)
        return f"sentinel    {abs_path} (block stripped, file emptied & removed)"
    fs.write_atomic(abs_path, stripped.encode("utf-8"))
    return f"sentinel    {abs_path} (block stripped)"


def _restore_bak(abs_path: str) -> Optional[str]:
    """Restore ``<abs_path>.agent-artifacts-bak`` over `abs_path` if the backup exists.

    Undoes a destructive ``replace`` install: on install `plan_memory` backed the prior
    (foreign) content up to the ``.bak`` sidecar; on uninstall we removed our file, so move the
    backup back into place. Returns a report line, or ``None`` when there is no backup.
    """
    bak = abs_path + _BAK_SUFFIX
    if not fs.exists(bak):
        return None
    fs.write_atomic(abs_path, fs.read_bytes(bak))
    fs.remove_path(bak)
    return f"restore     {abs_path} (from {os.path.basename(bak)})"


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
def _failure(request, reason: str, code: int) -> CommandOutcome:
    status: OutcomeStatus = "conflict" if code == _common.CONFLICT else "failed"
    return CommandOutcome(
        exit_code=code,
        summary=ActionSummary(
            action="uninstall",
            selected=0,
            items=(OutcomeItem("uninstall-request", status, detail=reason),),
        ),
        payload={"ok": False, "error": reason, "code": code},
    )


def execute(request) -> CommandOutcome:
    scope_error = _common.validate_scope(request)
    if scope_error is not None:
        return _failure(request, scope_error.reason, scope_error.code)

    project = _common.project_root(request)

    loaded = _common.load_manifest(request)
    if isinstance(loaded, Err):
        return _failure(request, loaded.reason, loaded.code)
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
        return _failure(request, msg, USAGE)

    if not selected:
        msg = "nothing to uninstall (no matching installed entries)"
        return CommandOutcome(
            exit_code=OK,
            summary=ActionSummary(action="uninstall", selected=0),
            payload={"ok": True, "removed": [], "message": msg},
        )

    conflicts = _link_conflicts(project, selected)
    if conflicts and not request.force:
        msg = "refusing to remove changed symlink install(s) without --force: " + "; ".join(
            conflicts
        )
        return CommandOutcome(
            exit_code=_common.CONFLICT,
            summary=ActionSummary(
                action="uninstall",
                selected=len(selected),
                items=tuple(
                    OutcomeItem(
                        outcome_key(entry.type, entry.artifact, entry.profile),
                        "conflict",
                        artifact=entry.artifact,
                        artifact_type=entry.type,
                        profile=entry.profile,
                        mode=entry.install.mode,
                        detail=msg,
                    )
                    for entry in selected
                ),
                recovery=("Rerun with --force after reviewing the changed symlink paths.",),
            ),
            payload={"ok": False, "error": msg, "code": _common.CONFLICT},
        )

    # Build the reversal plan (files + sentinel rewrites + .bak restores + merge undos).
    plan_removes: List[Tuple[ManifestEntry, RemovePath]] = []
    sentinel_jobs: List[Tuple[ManifestEntry, str]] = []
    restore_paths: List[Tuple[ManifestEntry, str]] = []
    merge_descs: List[str] = []
    file_render: List[RemovePath] = []
    for entry in selected:
        removes, sentinels, restores = _file_actions(project, entry)
        plan_removes.extend((entry, action) for action in removes)
        file_render.extend(removes)
        for path in sentinels:
            sentinel_jobs.append((entry, path))
        restore_paths.extend((entry, path) for path in restores)
        if entry.merge is not None:
            merge_descs.append(_describe_merge_reversal(entry.merge))

    if request.dry_run:
        lines: List[str] = []
        if file_render:
            lines.append(render_plan(tuple(file_render)))
        for _, path in sentinel_jobs:
            lines.append(f"sentinel    {path} (strip our block)")
        for _, path in restore_paths:
            if fs.exists(path + _BAK_SUFFIX):
                lines.append(f"restore     {path} (from {os.path.basename(path)}{_BAK_SUFFIX})")
        lines.extend(merge_descs)
        text = "\n".join(line for line in lines if line)
        return CommandOutcome(
            exit_code=OK,
            summary=ActionSummary(
                action="uninstall",
                selected=len(selected),
                items=tuple(
                    OutcomeItem(
                        outcome_key(entry.type, entry.artifact, entry.profile),
                        "removed",
                        artifact=entry.artifact,
                        artifact_type=entry.type,
                        profile=entry.profile,
                        mode=entry.install.mode,
                        detail="would remove",
                    )
                    for entry in selected
                ),
                dry_run=True,
            ),
            details=tuple(text.splitlines()) if text else ("nothing to do",),
            payload={
                "ok": True,
                "dry_run": True,
                "removed_entries": [
                    {"artifact": e.artifact, "profile": e.profile, "type": e.type} for e in selected
                ],
                "actions": text.splitlines(),
            },
        )

    # --- execute (imperative shell) --- #
    performed: List[str] = []
    outcome_details: List[OutcomeItem] = []
    failures: dict[Tuple[str, str], str] = {}

    def record_failure(entry: ManifestEntry, operation: str, exc: Exception) -> None:
        failures[(entry.artifact, entry.profile)] = f"{operation}: {exc}"

    for entry, action in plan_removes:
        existed = os.path.lexists(action.path)
        try:
            fs.remove_path(action.path)
            performed.append(f"remove-path {action.path}")
            if not existed:
                outcome_details.append(
                    OutcomeItem(
                        action.path,
                        "already_absent",
                        artifact=entry.artifact,
                        artifact_type=entry.type,
                        profile=entry.profile,
                        detail="managed path was already missing",
                    )
                )
        except Exception as exc:
            record_failure(entry, f"remove {action.path}", exc)
    # After removing a replaced memory file, restore its backup so the replace is undone.
    for entry, path in restore_paths:
        try:
            line = _restore_bak(path)
            if line is not None:
                performed.append(line)
                outcome_details.append(
                    OutcomeItem(
                        path,
                        "preserved",
                        artifact=entry.artifact,
                        artifact_type=entry.type,
                        profile=entry.profile,
                        detail="restored pre-install backup",
                    )
                )
        except Exception as exc:
            record_failure(entry, f"restore {path}", exc)
    for entry, path in sentinel_jobs:
        try:
            line = _apply_sentinel(project, entry, path)
            performed.append(line)
            if "already removed" in line:
                outcome_details.append(
                    OutcomeItem(
                        path,
                        "already_absent",
                        artifact=entry.artifact,
                        artifact_type=entry.type,
                        profile=entry.profile,
                        detail="managed block file was already missing",
                    )
                )
            elif "file emptied & removed" not in line:
                outcome_details.append(
                    OutcomeItem(
                        path,
                        "preserved",
                        artifact=entry.artifact,
                        artifact_type=entry.type,
                        profile=entry.profile,
                        detail="user content preserved after managed block removal",
                    )
                )
        except Exception as exc:
            record_failure(entry, f"strip managed block from {path}", exc)
    for entry in selected:
        if entry.merge is not None:
            try:
                line = _apply_merge(project, entry.merge)
                performed.append(line)
                if "unreadable" in line or "not an object" in line:
                    failures[(entry.artifact, entry.profile)] = line
                elif "not present" in line or "absent, nothing to do" in line:
                    outcome_details.append(
                        OutcomeItem(
                            entry.merge.file,
                            "already_absent",
                            artifact=entry.artifact,
                            artifact_type=entry.type,
                            profile=entry.profile,
                            detail="managed config entry was already missing",
                        )
                    )
            except Exception as exc:
                record_failure(entry, f"reverse merge in {entry.merge.file}", exc)

    # Update the manifest: drop each removed (artifact, profile) entry.
    new_manifest = manifest
    for entry in selected:
        if (entry.artifact, entry.profile) not in failures:
            new_manifest = remove_entry(new_manifest, entry.artifact, entry.profile)
    manifest_error: Optional[str] = None
    try:
        _common.save_manifest(request, new_manifest)
    except OSError as exc:
        manifest_error = f"could not save consumer manifest: {exc}"
        for entry in selected:
            failures[(entry.artifact, entry.profile)] = manifest_error

    items = tuple(
        OutcomeItem(
            outcome_key(entry.type, entry.artifact, entry.profile),
            "failed" if (entry.artifact, entry.profile) in failures else "removed",
            artifact=entry.artifact,
            artifact_type=entry.type,
            profile=entry.profile,
            mode=entry.install.mode,
            detail=failures.get((entry.artifact, entry.profile)),
        )
        for entry in selected
    ) + tuple(outcome_details)
    warnings = tuple(dict.fromkeys(failures.values()))
    successful = tuple(
        entry for entry in selected if (entry.artifact, entry.profile) not in failures
    )
    exit_code = _common.ERROR if failures or manifest_error else OK
    return CommandOutcome(
        exit_code=exit_code,
        summary=ActionSummary(
            action="uninstall",
            selected=len(selected),
            items=items,
            warnings=warnings,
            recovery=(
                ("Fix the reported filesystem errors and rerun uninstall for failed artifacts.",)
                if failures
                else ()
            ),
        ),
        details=tuple(performed),
        payload={
            "ok": not failures,
            "removed_entries": [
                {"artifact": e.artifact, "profile": e.profile, "type": e.type} for e in successful
            ],
            "actions": performed,
            "warnings": list(warnings),
        },
    )


def run(request) -> int:
    """Execute and render uninstall while retaining the integer CLI contract."""

    result = execute(request)
    if request.json:
        _common.print_json(outcome_payload(result))
    else:
        for line in render_outcome(result):
            print(line)
    return result.exit_code
