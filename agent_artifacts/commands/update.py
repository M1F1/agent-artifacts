"""update command (WP-13). Re-pull from main/pin, apply the §9 update policy + optional --prune.

Imperative shell: re-pull the source, load the consumer manifest, recompute each installed
artifact's *desired* install plan from the current source (reusing ``planners.plan_install``
exactly as ``install`` does), then turn every desired ``WriteFile`` into an UPDATE action by
running it through ``policy.classify`` / ``policy.decision_action`` (overwrite / keep-drift /
conflict-sidecar). ``CopyTree`` (skills, hook scripts) and ``MergeJson`` (mcp/hook registration)
are kept as-is — re-copy / re-merge for *our own* entry is idempotent (MVP simplification).

Exit-code behaviour (docs/plan/PLAN.md §7):
  * source open failure          -> 3 (NETWORK)
  * corrupt manifest             -> 5 (CORRUPT_MANIFEST)
  * planning error (bad catalog) -> the planner's code (1)
  * a conflict occurred and no --force -> 4 (CONFLICT). The sidecar ``<path>.agent-artifacts-new``
    is still written and the manifest still refreshed (the update "succeeded" — the user just has
    a decision to make), but we surface a non-zero code so scripts/CI notice. ``--force`` resolves
    the conflict by overwriting and the run exits 0.
  * otherwise                    -> 0 (OK)
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Mapping, Optional, Tuple

from .. import planners
from ..compatibility import (
    INCOMPATIBLE_PROFILE,
    check_profile_compatibility,
    skipped_target_to_dict,
)
from ..executor import execute, plan_to_json, render_plan
from ..hashing import sha256_bytes, sha256_file
from ..io import fs
from ..manifest import prune_plan
from ..model import (
    Artifact,
    CopyTree,
    Err,
    Manifest,
    ManifestEntry,
    MergeJson,
    Ok,
    Plan,
    Profile,
    Request,
    SkippedTarget,
    WriteFile,
)
from ..policy import classify, decision_action
from ..profiles.loader import load_profiles
from ..source import open_source
from . import _common


# --------------------------------------------------------------------------- #
# Entry point                                                                  #
# --------------------------------------------------------------------------- #
def run(request: Request) -> int:
    """Re-pull installed artifacts and apply the §9 per-file update policy."""
    # 1. Re-pull the source (Err -> print + NETWORK).
    src_result = open_source(request)
    if isinstance(src_result, Err):
        print(src_result.reason)
        return _common.NETWORK
    src = src_result.value

    cat_result = src.catalog()
    if isinstance(cat_result, Err):
        print(cat_result.reason)
        return _common.exit_code(cat_result)
    catalog = cat_result.value

    # 2. Load the current manifest (corrupt -> CORRUPT_MANIFEST).
    man_result = _common.load_manifest(request)
    if isinstance(man_result, Err):
        print(man_result.reason)
        return _common.exit_code(man_result)
    manifest: Manifest = man_result.value

    project = _common.project_root(request)
    profiles = load_profiles(project)

    # 2b. Select which installed entries to update.
    selected, others = _select_entries(manifest, request)

    # 3. Recompute the desired install plan for each selected entry, then apply §9.
    desired_result = _build_desired_plan(request, catalog, profiles, src, selected)
    if isinstance(desired_result, Err):
        print(desired_result.reason)
        return _common.exit_code(desired_result)
    desired_plan, new_entries, skipped = desired_result.value

    update_plan, conflict = _apply_policy(desired_plan, selected, project, force=request.force)

    # 4. --prune: append removals for entries dropped from the selection.
    pruned_manifest = manifest
    if request.prune and others:
        prune_actions, pruned_manifest = _prune(manifest, selected)
        update_plan = update_plan + prune_actions

    # 5. Rebase onto the real source/project roots.
    rebased = _common.rebase_plan(update_plan, source_root=src.root, project_root=project)

    # 5b. --dry-run: present the plan, touch nothing.
    if request.dry_run:
        _emit(rebased, json_mode=request.json, skipped=skipped)
        return _common.CONFLICT if conflict and not request.force else _common.OK

    # 5c. Execute and persist the refreshed manifest.
    report = execute(rebased)
    final_manifest = _merge_entries(pruned_manifest, new_entries, src.label())
    _common.save_manifest(project, final_manifest)

    # 6. Output + exit code.
    if request.json:
        _common.print_json(
            {
                "performed": list(report.performed),
                "warnings": list(report.warnings),
                "skipped": [skipped_target_to_dict(s) for s in skipped],
                "conflict": conflict,
            }
        )
    else:
        for s in skipped:
            print(_skip_message(s))
        for w in report.warnings:
            print(w)

    return _common.CONFLICT if conflict and not request.force else _common.OK


# --------------------------------------------------------------------------- #
# Entry selection                                                              #
# --------------------------------------------------------------------------- #
def _select_entries(
    manifest: Manifest, request: Request
) -> Tuple[Tuple[ManifestEntry, ...], Tuple[ManifestEntry, ...]]:
    """Partition installed entries into ``(selected, others)`` by the request filters.

    No ``--bundle`` / ``--profile`` / ``NAME`` filter given -> every installed entry is selected.
    When multiple filters are present, they narrow the selection together. For example,
    ``update NAME --profile claude`` selects only installed ``NAME`` entries for ``claude``.
    """
    name_set = set(request.names)
    profile_set = set(request.profiles)
    bundle_set = set(request.bundles)
    has_filter = bool(name_set or profile_set or bundle_set)

    if not has_filter:
        return manifest.installed, ()

    selected: List[ManifestEntry] = []
    others: List[ManifestEntry] = []
    for entry in manifest.installed:
        keep = (
            (not name_set or entry.artifact in name_set)
            and (not profile_set or entry.profile in profile_set)
            and (not bundle_set or entry.bundle in bundle_set)
        )
        (selected if keep else others).append(entry)
    return tuple(selected), tuple(others)


# --------------------------------------------------------------------------- #
# Desired-plan reconstruction (mirrors the install command's input assembly)    #
# --------------------------------------------------------------------------- #
def _build_desired_plan(
    request: Request,
    catalog,
    profiles: Mapping[str, Profile],
    src,
    selected: Tuple[ManifestEntry, ...],
):
    """Re-derive each selected entry's desired install Plan from the *current* source.

    Returns ``Ok((plan_without_manifest, new_entries, skipped))`` or an `Err` from the planner.
    The trailing ``WriteManifest`` is split off so the shell can persist the manifest itself
    with the refreshed source label (see `_merge_entries`).
    """
    targets: List[Tuple[Artifact, str]] = []
    files: Dict[str, object] = {"__targets__": targets, "__installed_at__": ""}
    configs: Dict[str, Mapping] = {}
    skipped: List[SkippedTarget] = []
    explicit_errors: List[str] = []
    explicit_names = set(request.names)

    for entry in selected:
        artifact = catalog.artifacts.get((entry.type, entry.artifact))
        if artifact is None:
            # Artifact no longer exists upstream — skip (the entry simply isn't refreshed).
            continue
        profile_name = entry.profile
        decision = check_profile_compatibility(artifact, profile_name)
        if not decision.ok:
            skipped_target = SkippedTarget(
                artifact=artifact.name,
                type=artifact.type,
                profile=profile_name,
                reason=decision.reason or INCOMPATIBLE_PROFILE,
                allowed_profiles=decision.allowed_profiles,
            )
            if entry.artifact in explicit_names:
                explicit_errors.append(
                    _compat_error(artifact, profile_name, decision.allowed_profiles)
                )
            else:
                skipped.append(skipped_target)
            continue
        targets.append((artifact, profile_name))
        files[f"bundle:{entry.artifact}"] = entry.bundle
        _gather_inputs(
            artifact,
            profile_name,
            profiles,
            src,
            project=_common.project_root(request),
            files=files,
            configs=configs,
        )

    if explicit_errors:
        return Err("; ".join(explicit_errors), code=_common.USAGE)

    if not targets:
        return Ok(((), (), tuple(skipped)))

    plan_result = planners.plan_install(
        request, catalog, files, profiles, manifest=None, configs=configs
    )
    if isinstance(plan_result, Err):
        return plan_result

    plan = plan_result.value
    file_actions, entries = _common.split_manifest(plan)
    return Ok((file_actions, entries, tuple(skipped)))


def _compat_error(artifact: Artifact, profile_name: str, allowed: Tuple[str, ...]) -> str:
    allowed_text = ", ".join(allowed)
    return (
        f"{artifact.type} {artifact.name!r} is not compatible with profile {profile_name!r} "
        f"(allowed: {allowed_text})"
    )


def _skip_message(skipped: SkippedTarget) -> str:
    if skipped.allowed_profiles:
        allowed = ", ".join(skipped.allowed_profiles)
        return (
            f"skipped {skipped.type} {skipped.artifact!r} for profile {skipped.profile!r}: "
            f"{skipped.reason} (allowed: {allowed})"
        )
    return (
        f"skipped {skipped.type} {skipped.artifact!r} for profile {skipped.profile!r}: "
        f"{skipped.reason}"
    )


def _gather_inputs(
    artifact: Artifact,
    profile_name: str,
    profiles: Mapping[str, Profile],
    src,
    *,
    project: str,
    files: Dict[str, object],
    configs: Dict[str, Mapping],
) -> None:
    """Populate `files`/`configs` for one artifact×profile, reading bytes from the source."""
    profile = profiles.get(profile_name)

    if artifact.type == "guideline":
        # Guidelines are copied verbatim as standalone docs — no shared-file merge.
        body = src.read(artifact.root).decode("utf-8")
        from ..catalog import _split_frontmatter

        _found, _fields, stripped_body = _split_frontmatter(body)
        files[f"guideline:{artifact.name}"] = stripped_body
        return

    if artifact.type in ("mcp", "hook"):
        descriptor = _read_descriptor(artifact, src)
        if descriptor is not None:
            files[f"descriptor:{artifact.name}"] = descriptor
        # NB: deliberately do NOT pass ``scripts:{name}`` — install doesn't either, so the
        # hook planner copies the whole script tree (one CopyTree of artifact.root). Passing
        # an explicit per-file list makes the planner emit a CopyTree per *file*, which the
        # executor's dir-based copy can't perform. Mirroring install keeps update's plan and
        # manifest proof identical to the original install (idempotent re-copy under §9).
        # Load the existing harness config for collision detection (mirrors install).
        if profile is not None:
            spec = (
                profile.mcp
                if artifact.type == "mcp"
                else (profile.hooks.merge if profile.hooks is not None else None)
            )
            if spec is not None:
                configs[profile_name] = _read_config(project, spec.file)
        return

    if artifact.type == "memory":
        body = src.read(artifact.root).decode("utf-8")
        from ..catalog import _split_frontmatter

        _found, _fields, stripped_body = _split_frontmatter(body)
        files[f"memory:{artifact.name}"] = stripped_body
        # update has no --memory-mode flag in MVP: frontmatter `mode:` else "prepend".
        files[f"memory-mode:{artifact.name}"] = _memory_mode_from_body(body)
        # For the entry's own (file) profile, pre-read the destination so the planner can
        # merge/replace against it (the EXACT keys plan_memory reads — mirrors install).
        if profile is not None and profile.memory is not None:
            target = profile.memory
            if target.kind == "dir":
                dest = os.path.join(project, target.dest, f"{artifact.name}.md")
            else:
                dest = os.path.join(project, target.dest)
            exists = fs.exists(dest)
            files[f"memory-exists:{profile_name}:{artifact.name}"] = exists
            if exists:
                files[f"existing-memory:{profile_name}:{artifact.name}"] = fs.read_text(dest)
        return

    # skill: nothing extra — the planner copies artifact.root.


def _memory_mode_from_body(body: str) -> str:
    """Resolve an ``memory`` artifact's install mode for update: frontmatter ``mode:`` else
    ``"prepend"`` (update has no ``--memory-mode`` flag in MVP — docs/design/DESIGN-memory.md §3.4)."""
    from ..catalog import _split_frontmatter

    _found, fields, _body = _split_frontmatter(body)
    mode = fields.get("mode")
    return mode if mode else "prepend"


def _read_descriptor(artifact: Artifact, src) -> Optional[Mapping]:
    """Read an MCP descriptor or hooks/<name>/hook.json descriptor from the source."""
    import json

    rel = artifact.root if artifact.type == "mcp" else os.path.join(artifact.root, "hook.json")
    try:
        data = json.loads(src.read(rel).decode("utf-8"))
    except Exception:
        return None
    return data if isinstance(data, Mapping) else None


def _read_config(project: str, rel_file: str) -> Mapping:
    """Read a harness config file (``{}`` when absent or malformed)."""
    import json

    path = os.path.join(project, rel_file)
    if not fs.exists(path):
        return {}
    try:
        data = json.loads(fs.read_text(path))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


# --------------------------------------------------------------------------- #
# §9 policy application                                                         #
# --------------------------------------------------------------------------- #
def _apply_policy(
    desired_plan: Plan,
    selected: Tuple[ManifestEntry, ...],
    project: str,
    *,
    force: bool,
) -> Tuple[Plan, bool]:
    """Rewrite each desired ``WriteFile`` through the §9 decision table.

    ``CopyTree`` (skills, hook scripts) and ``MergeJson`` (mcp/hook registration) are kept
    verbatim: re-copy / re-merge of *our own* entry is idempotent, so an MVP update doesn't
    diff their per-file content (a deliberate simplification — docs/design/DESIGN.md §9 covers WriteFiles).

    Returns ``(update_plan, conflict_occurred)``.
    """
    base_for = _base_hash_index(selected)
    out: List = []
    conflict = False

    for action in desired_plan:
        if isinstance(action, (CopyTree, MergeJson)):
            out.append(action)
            continue
        if not isinstance(action, WriteFile):
            out.append(action)  # Warn or anything else — pass through
            continue

        path = action.path
        base = base_for.get(path)  # recorded install hash, or None if never tracked
        disk_path = os.path.join(project, path)
        disk = sha256_file(disk_path) if fs.exists(disk_path) else None
        new = sha256_bytes(action.content)

        decision = classify(disk, base, new)
        if decision == "conflict" and not force:
            conflict = True
        out.extend(decision_action(decision, path, action.content, force=force))

    return tuple(out), conflict


def _base_hash_index(selected: Tuple[ManifestEntry, ...]) -> Dict[str, Optional[str]]:
    """Map ``project-relative path -> recorded install hash`` across all selected entries.

    An empty string (copy-tree placeholder) is treated as "no base hash" (``None``) so the
    policy doesn't misclassify it; real ``WriteFile`` paths carry a ``sha256:`` value.
    """
    index: Dict[str, Optional[str]] = {}
    for entry in selected:
        for path, h in entry.files.items():
            index[path] = h or None
    return index


# --------------------------------------------------------------------------- #
# Pruning                                                                       #
# --------------------------------------------------------------------------- #
def _prune(manifest: Manifest, selected: Tuple[ManifestEntry, ...]) -> Tuple[Plan, Manifest]:
    """Remove non-selected entries' files and drop them from the manifest.

    Uses ``manifest.prune_plan`` (keep == the selected (artifact, profile) keys), then strips
    its trailing ``WriteManifest`` — the surviving entries become the new manifest, which the
    shell persists itself (so we keep the file actions and apply the entry set directly).
    """
    keep = tuple((e.artifact, e.profile) for e in selected)
    plan = prune_plan(manifest, keep)
    file_actions, entries = _common.split_manifest(plan)
    survivors = Manifest(repo=manifest.repo, installed=tuple(entries))
    return file_actions, survivors


# --------------------------------------------------------------------------- #
# Manifest refresh                                                              #
# --------------------------------------------------------------------------- #
def _merge_entries(
    manifest: Manifest, new_entries: Tuple[ManifestEntry, ...], source_label: str
) -> Manifest:
    """Upsert the freshly-planned entries (with the new source label) into `manifest`.

    Each refreshed entry carries the re-derived file hashes from `plan_install` and the
    current source label, so a subsequent update sees the just-applied content as its base.
    """
    from ..manifest import upsert

    out = manifest
    for entry in new_entries:
        refreshed = ManifestEntry(
            artifact=entry.artifact,
            type=entry.type,
            profile=entry.profile,
            source=source_label,
            bundle=entry.bundle,
            files=entry.files,
            merge=entry.merge,
            installed_at=entry.installed_at,
        )
        out = upsert(out, refreshed)
    return out


# --------------------------------------------------------------------------- #
# Rendering                                                                     #
# --------------------------------------------------------------------------- #
def _emit(plan: Plan, *, json_mode: bool, skipped: Tuple[SkippedTarget, ...] = ()) -> None:
    if json_mode:
        if skipped:
            _common.print_json(
                {
                    "actions": json.loads(plan_to_json(plan)),
                    "skipped": [skipped_target_to_dict(s) for s in skipped],
                    "warnings": [_skip_message(s) for s in skipped],
                }
            )
        else:
            print(plan_to_json(plan))
    else:
        rendered = render_plan(plan)
        lines = [f"warn        {_skip_message(s)}" for s in skipped]
        if rendered:
            lines.append(rendered)
        print("\n".join(lines))
