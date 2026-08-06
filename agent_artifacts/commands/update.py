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
    CatalogSubscription,
    CopyTree,
    Err,
    Manifest,
    ManifestEntry,
    MergeJson,
    Ok,
    Plan,
    Profile,
    RemovePath,
    Request,
    SkippedTarget,
    SymlinkTree,
    Warn,
    WriteFile,
)
from ..policy import classify, decision_action
from ..profiles.loader import load_profiles
from ..source import open_source
from ..subscriptions import (
    group_entries_by_subscription,
    has_source_override,
    request_for_subscription,
    subscription_from_request,
)
from . import _common


# --------------------------------------------------------------------------- #
# Entry point                                                                  #
# --------------------------------------------------------------------------- #
def run(request: Request) -> int:
    """Re-pull installed artifacts and apply the §9 per-file update policy."""
    # 1. Load and select manifest entries before resolving sources.  The selected entries carry
    #    the subscriptions that decide which catalog(s) must be reopened.
    man_result = _common.load_manifest(request)
    if isinstance(man_result, Err):
        print(man_result.reason)
        return _common.exit_code(man_result)
    manifest: Manifest = man_result.value

    project = _common.project_root(request)
    profiles = load_profiles(project)

    selected, others = _select_entries(manifest, request)

    # 2. Resolve and plan every subscription group before executing anything.  This preserves
    #    all-or-nothing planning safety when one project contains entries from several catalogs.
    source_groups: Tuple[Tuple[Request, Tuple[ManifestEntry, ...]], ...]
    if has_source_override(request):
        source_groups = ((request, selected),) if selected else ()
    else:
        source_groups = tuple(
            (
                request
                if group.subscription is None
                else request_for_subscription(request, group.subscription),
                group.entries,
            )
            for group in group_entries_by_subscription(selected)
        )

    update_plan: Plan = ()
    new_entries: Tuple[ManifestEntry, ...] = ()
    skipped: Tuple[SkippedTarget, ...] = ()
    conflict = False
    for source_request, group_entries in source_groups:
        src_result = open_source(source_request)
        if isinstance(src_result, Err):
            print(src_result.reason)
            return _common.NETWORK
        src = src_result.value

        cat_result = src.catalog()
        if isinstance(cat_result, Err):
            print(cat_result.reason)
            return _common.exit_code(cat_result)

        subscription = subscription_from_request(source_request, src.root)
        desired_result = _build_desired_plan(
            source_request,
            cat_result.value,
            profiles,
            src,
            group_entries,
            source_label=src.label(),
            subscription=subscription,
        )
        if isinstance(desired_result, Err):
            print(desired_result.reason)
            return _common.exit_code(desired_result)
        desired_plan, group_new_entries, group_skipped = desired_result.value
        group_plan, group_conflict = _apply_policy(
            desired_plan,
            group_entries,
            project,
            force=request.force,
            source_root=src.root,
        )
        update_plan += _common.rebase_plan(
            group_plan,
            source_root=src.root,
            project_root=project,
        )
        new_entries += group_new_entries
        skipped += group_skipped
        conflict = conflict or group_conflict

    # 3. --prune: append removals for entries dropped from the selection.
    pruned_manifest = manifest
    if request.prune and others:
        prune_actions, pruned_manifest = _prune(manifest, selected)
        update_plan += _common.rebase_plan(
            prune_actions,
            source_root="",
            project_root=project,
        )

    # 4. --dry-run: present the fully planned multi-source operation, touch nothing.
    if request.dry_run:
        _emit(update_plan, json_mode=request.json, skipped=skipped)
        return _common.CONFLICT if conflict and not request.force else _common.OK

    # 5. Execute once after every source group planned successfully, then persist subscriptions.
    report = execute(update_plan)
    final_manifest = _merge_entries(pruned_manifest, new_entries)
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
    ``update NAME --profile tabnine`` selects only installed ``NAME`` entries for ``tabnine``.
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
    *,
    source_label: str,
    subscription: CatalogSubscription,
):
    """Re-derive each selected entry's desired install Plan from the *current* source.

    Returns ``Ok((plan_without_manifest, new_entries, skipped))`` or an `Err` from the planner.
    The trailing ``WriteManifest`` is split off so the shell can persist the manifest itself
    with the refreshed source label (see `_merge_entries`).
    """
    targets: List[Tuple[Artifact, str]] = []
    files: Dict[str, object] = {
        "__targets__": targets,
        "__installed_at__": "",
        "__source_root__": src.root,
    }
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
        files[f"source:{entry.artifact}"] = source_label
        files[f"subscription:{entry.artifact}"] = subscription
        files[f"bundle:{entry.artifact}"] = entry.bundle
        files[f"install-mode:{profile_name}:{artifact.name}"] = entry.install.requested_mode
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
    source_root: str = "",
) -> Tuple[Plan, bool]:
    """Rewrite each desired ``WriteFile`` through the §9 decision table.

    ``CopyTree``/``SymlinkTree`` (skills, hook scripts) and ``MergeJson`` (mcp/hook registration) are kept
    verbatim: re-copy / re-merge of *our own* entry is idempotent, so an MVP update doesn't
    diff their per-file content (a deliberate simplification — docs/design/DESIGN.md §9 covers WriteFiles).

    Returns ``(update_plan, conflict_occurred)``.
    """
    base_for = _base_hash_index(selected)
    out: List = []
    conflict = False

    for action in desired_plan:
        if isinstance(action, SymlinkTree):
            rewritten, symlink_conflict = _symlink_update_actions(
                action,
                project,
                source_root=source_root,
                force=force,
            )
            out.extend(rewritten)
            conflict = conflict or symlink_conflict
            continue
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


def _expected_symlink_target(action: SymlinkTree, source_root: str) -> str:
    if os.path.isabs(action.src):
        return os.path.normpath(action.src)
    return os.path.normpath(os.path.join(source_root, action.src))


def _actual_symlink_target(abs_path: str) -> Optional[str]:
    if not os.path.islink(abs_path):
        return None
    raw = os.readlink(abs_path)
    if os.path.isabs(raw):
        return os.path.normpath(raw)
    return os.path.normpath(os.path.join(os.path.dirname(abs_path), raw))


def _symlink_update_actions(
    action: SymlinkTree,
    project: str,
    *,
    source_root: str,
    force: bool,
) -> Tuple[Plan, bool]:
    """Update policy for live-linked directory artifacts.

    Correct existing links are already live, so update reports them instead of re-linking.
    Missing links are recreated. Replaced/retargeted paths require ``--force`` before relinking.
    """
    abs_path = os.path.join(project, action.dst)
    expected = _expected_symlink_target(action, source_root)
    if not os.path.lexists(abs_path):
        return (action,), False
    actual = _actual_symlink_target(abs_path)
    if actual == expected and os.path.exists(actual):
        return (Warn(message=f"live-linked: {action.dst} -> {expected}; no copy needed"),), False
    if not force:
        return (
            Warn(
                message=(
                    f"symlink {action.dst} changed or broken; use --force to relink to {expected}"
                )
            ),
        ), True
    return (RemovePath(path=action.dst), action), False


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
def _merge_entries(manifest: Manifest, new_entries: Tuple[ManifestEntry, ...]) -> Manifest:
    """Upsert freshly-planned entries with their per-source proof and subscription.

    Each refreshed entry carries re-derived file hashes, the resolved source label, and the
    subscription needed to reopen its catalog on the next update.
    """
    from ..manifest import upsert

    out = manifest
    for entry in new_entries:
        out = upsert(out, entry)
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
