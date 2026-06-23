"""install command (WP-12). Gather configs -> plan_install -> execute/render -> manifest upsert.

Orchestration only (imperative shell, DESIGN.md §14). The decision logic lives in the pure
core: source resolution (WP-11), target/profile resolution + manifest glue (`_common`), and
`planners.plan_install` (WP-5). This module's single job is to assemble the inputs those
pieces need, thread `--dry-run`/`--json`/`--force`, run the executor, and persist the manifest.

Flow (matches the WP-12 contract):

1. ``open_source`` -> ``Source``.
2. ``Source.catalog()`` -> ``Catalog``.
3. ``_common.resolve_artifacts`` + ``_common.resolve_profiles``.
4. Assemble the ``files`` mapping (targets, guideline bodies, descriptors, source labels,
   per-profile memory-file pre-reads for the sentinel/replace merge).
5. Build ``profiles_map`` and ``configs`` (per-profile harness config for collision detection).
6. ``planners.plan_install`` -> ``Plan``.
7. ``_common.split_manifest`` + ``_common.rebase_plan`` (project-relative -> absolute).
8. ``--dry-run``: print the rendered/JSON plan and return without touching disk.
9. ``executor.execute`` the rebased plan.
10. Merge the manifest entries into the on-disk manifest (real `WriteFile` hashes from the
    pure plan; `CopyTree` payload hashes are left empty by the core — see DESIGN.md §12).
11. Print a human summary or JSON; return ``OK``.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Mapping, Tuple

from .. import catalog as catalog_mod
from .. import executor, manifest, planners
from ..compatibility import (
    INCOMPATIBLE_PROFILE,
    check_profile_compatibility,
    skipped_target_to_dict,
)
from ..io import fs
from ..model import Artifact, Profile, Request, SkippedTarget
from ..source import Source, open_source
from . import _common

# Type -> the `Profile` attribute that targets it. A `None` value on that attribute means the
# harness does not support that type (DESIGN-memory.md §5).
_TYPE_ATTR = {
    "skill": "skills",
    "guideline": "guidelines",
    "mcp": "mcp",
    "hook": "hooks",
    "memory": "memory",
}
UNSUPPORTED_TYPE = "unsupported-type"


def _err(message: str) -> None:
    """Emit a single diagnostic line to stderr (commands are quiet on the happy path)."""
    print(message, file=sys.stderr)


def _supports(profile: Profile, art_type: str) -> bool:
    """True when `profile` declares a target for `art_type` (DESIGN-memory.md §5)."""
    return getattr(profile, _TYPE_ATTR[art_type], None) is not None


def _skip_message(skipped: SkippedTarget) -> str:
    """Human-readable warning for a structured skipped target."""
    if skipped.reason == INCOMPATIBLE_PROFILE and skipped.allowed_profiles:
        allowed = ", ".join(skipped.allowed_profiles)
        return (
            f"skipped {skipped.type} {skipped.artifact!r} for profile {skipped.profile!r}: "
            f"{skipped.reason} (allowed: {allowed})"
        )
    if skipped.reason == UNSUPPORTED_TYPE:
        return (
            f"skipped {skipped.type} {skipped.artifact!r}: "
            f"profile {skipped.profile!r} does not support it"
        )
    return (
        f"skipped {skipped.type} {skipped.artifact!r} for profile {skipped.profile!r}: "
        f"{skipped.reason}"
    )


def _compat_error(a: Artifact, profile_name: str, allowed: Tuple[str, ...]) -> str:
    allowed_text = ", ".join(allowed)
    return (
        f"{a.type} {a.name!r} is not compatible with profile {profile_name!r} "
        f"(allowed: {allowed_text})"
    )


def _resolve_memory_mode(request: Request, body: str) -> str:
    """Resolve the effective install mode for one ``memory`` artifact (DESIGN-memory §3.4).

    Precedence, highest wins: the CLI flag ``request.memory_mode`` → the artifact's
    frontmatter ``mode:`` → the built-in default ``"prepend"``.
    """
    if request.memory_mode:
        return request.memory_mode
    _found, fields, _body = catalog_mod._split_frontmatter(body)
    mode = fields.get("mode")
    return mode if mode else "prepend"


def _memory_dest(profile: Profile, project: str, name: str) -> str:
    """Absolute destination path the planner will write for an ``memory`` artifact.

    ``kind="file"`` → the shared instruction file itself; ``kind="dir"`` → ``<dir>/<name>.md``.
    Mirrors `planners.plan_memory` so install's pre-read of the existing dest text matches what
    the planner merges against.
    """
    target = profile.memory
    assert target is not None  # callers gate on memory support before calling
    if target.kind == "dir":
        return os.path.normpath(os.path.join(project, target.dest, f"{name}.md"))
    return os.path.normpath(os.path.join(project, target.dest))


def run(request: Request) -> int:
    """Install the requested artifacts into the selected profiles.

    Returns a process exit code (PLAN.md §7): ``OK`` (0) on success or dry-run; ``USAGE``
    (2) for a bad selection (unknown name/bundle/profile or no profile); ``NETWORK`` (3)
    for a remote-source failure; ``CONFLICT`` (4) for a merge collision needing ``--force``;
    ``CORRUPT_MANIFEST`` (5) for an unreadable manifest; ``ERROR`` (1) otherwise.
    """
    # 1. Resolve the source (local dir or remote snapshot).
    src_res = open_source(request)
    if isinstance(src_res, _common.Err):
        _err(src_res.reason)
        return _common.exit_code(src_res)
    src: Source = src_res.value

    # 2. Build the catalog from the source.
    cat_res = src.catalog()
    if isinstance(cat_res, _common.Err):
        _err(cat_res.reason)
        return _common.exit_code(cat_res)
    catalog = cat_res.value

    # 3. Resolve the requested artifacts and profiles.
    arts_res = _common.resolve_artifacts(request, catalog)
    if isinstance(arts_res, _common.Err):
        _err(arts_res.reason)
        return _common.USAGE
    profs_res = _common.resolve_profiles(request)
    if isinstance(profs_res, _common.Err):
        _err(profs_res.reason)
        return _common.USAGE

    arts: Tuple[Artifact, ...] = arts_res.value
    profs: Tuple[Tuple[str, Profile], ...] = profs_res.value
    project = _common.project_root(request)

    # 4. Partition every artifact×profile target by type support and artifact compatibility.
    #    Explicit by-name requests are hard errors; broad selections skip with structured
    #    reasons so --json/dry-run callers do not have to parse warning strings.
    by_name = set(request.names)
    kept_targets: List[Tuple[Artifact, str]] = []
    support_errors: List[str] = []
    compatibility_errors: List[str] = []
    skipped_targets: List[SkippedTarget] = []
    for a in arts:
        for pname, prof in profs:
            explicit = a.name in by_name
            if not _supports(prof, a.type):
                skipped = SkippedTarget(
                    artifact=a.name,
                    type=a.type,
                    profile=pname,
                    reason=UNSUPPORTED_TYPE,
                )
                if explicit:
                    support_errors.append(
                        f"profile {pname!r} does not support {a.type} {a.name!r}"
                    )
                else:
                    skipped_targets.append(skipped)
                continue

            decision = check_profile_compatibility(a, pname)
            if not decision.ok:
                skipped = SkippedTarget(
                    artifact=a.name,
                    type=a.type,
                    profile=pname,
                    reason=decision.reason or INCOMPATIBLE_PROFILE,
                    allowed_profiles=decision.allowed_profiles,
                )
                if explicit:
                    compatibility_errors.append(
                        _compat_error(a, pname, decision.allowed_profiles)
                    )
                else:
                    skipped_targets.append(skipped)
                continue

            kept_targets.append((a, pname))

    if support_errors or compatibility_errors:
        for msg in support_errors + compatibility_errors:
            _err(msg)
        return _common.USAGE

    # 5. Assemble the `files` mapping that plan_install consumes (kept targets only).
    installed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    files: Dict[str, object] = {
        "__targets__": tuple(kept_targets),
        "__installed_at__": installed_at,
    }
    kept_artifacts = {a.name: a for (a, _pname) in kept_targets}

    for a in arts:
        if a.name not in kept_artifacts:
            continue  # every target for this artifact was dropped (unsupported, by-bundle)
        files[f"source:{a.name}"] = src.label()
        if a.type == "guideline":
            # A guideline is copied verbatim as a standalone reference doc — no shared-file
            # merge, so nothing to pre-read from the destination.
            body = src.read(a.root).decode("utf-8")
            _found, _fields, stripped_body = catalog_mod._split_frontmatter(body)
            files[f"guideline:{a.name}"] = stripped_body
        elif a.type in ("mcp", "hook"):
            # mcp descriptor lives at a.root (e.g. "mcp/postgres.json"); a hook's lives at
            # a.root + "/hook.json" (e.g. "hooks/block-secrets/hook.json").
            rel = a.root if a.type == "mcp" else f"{a.root}/hook.json"
            files[f"descriptor:{a.name}"] = json.loads(src.read(rel).decode("utf-8"))
        elif a.type == "memory":
            body = src.read(a.root).decode("utf-8")
            _found, _fields, stripped_body = catalog_mod._split_frontmatter(body)
            files[f"memory:{a.name}"] = stripped_body
            files[f"memory-mode:{a.name}"] = _resolve_memory_mode(request, body)
            # Per supported file-profile, pre-read the destination's existence + text so the
            # planner can merge/replace against it (the EXACT keys plan_memory reads).
            for pname, prof in profs:
                if prof.memory is None:
                    continue
                dest = _memory_dest(prof, project, a.name)
                exists = fs.exists(dest)
                files[f"memory-exists:{pname}:{a.name}"] = exists
                if exists:
                    files[f"existing-memory:{pname}:{a.name}"] = fs.read_text(dest)

    # 6. Build profile map + per-profile harness configs (for merge collision detection).
    #
    # LIMITATION: collision detection in plan_mcp/plan_hook is per-profile against a SINGLE
    # already-loaded config dict. We load each profile's mcp merge file from the project if
    # it exists and pass it as that profile's config. This catches collisions against
    # *previously written* config but not collisions between two artifacts merged in the
    # same run targeting the same key (the executor's merge performer is last-writer-wins /
    # dedup-on-equal for those). Hooks merge into a different file (list mode); we use the
    # same single dict, which is sufficient for the built-in profiles where mcp and hook
    # merge files differ. Downstream commands needing exact pre-merge state should reload.
    profiles_map: Dict[str, Profile] = {pname: prof for (pname, prof) in profs}
    configs: Dict[str, Mapping] = {}
    for pname, prof in profs:
        cfg: Mapping = {}
        if prof.mcp is None:
            configs[pname] = cfg  # harness has no MCP target (e.g. vibe) — nothing to load
            continue
        merge_file = os.path.normpath(os.path.join(project, prof.mcp.file))
        if fs.exists(merge_file):
            try:
                loaded = fs.read_json(merge_file)
                if isinstance(loaded, dict):
                    # Hand the planner the sub-mapping it collision-checks against
                    # (json_path under the merge file, e.g. "mcpServers").
                    node = loaded
                    for part in (prof.mcp.json_path.split(".") if prof.mcp.json_path else []):
                        nxt = node.get(part) if isinstance(node, dict) else None
                        node = nxt if isinstance(nxt, dict) else {}
                    cfg = node if isinstance(node, dict) else {}
            except (OSError, json.JSONDecodeError, ValueError):  # pragma: no cover
                cfg = {}
        configs[pname] = cfg

    # 6. Build the full plan (pure). Accumulates every target's failure.
    manifest_res = _common.load_manifest(request)
    if isinstance(manifest_res, _common.Err):
        _err(manifest_res.reason)
        return _common.exit_code(manifest_res)

    plan_res = planners.plan_install(
        request, catalog, files, profiles_map, manifest_res.value, configs
    )
    if isinstance(plan_res, _common.Err):
        _err(plan_res.reason)
        return _common.exit_code(plan_res)
    plan = plan_res.value

    # 7. Split off the manifest entries; rebase the executable actions onto real roots.
    file_actions, entries = _common.split_manifest(plan)
    rebased = _common.rebase_plan(
        file_actions, source_root=src.root, project_root=project
    )

    # 8. Dry-run: print the plan and return without touching disk.
    if request.dry_run:
        warnings = [_skip_message(s) for s in skipped_targets]
        if request.json:
            if skipped_targets:
                _common.print_json(
                    {
                        "actions": json.loads(executor.plan_to_json(rebased)),
                        "skipped": [skipped_target_to_dict(s) for s in skipped_targets],
                        "warnings": warnings,
                    }
                )
            else:
                print(executor.plan_to_json(rebased))
        else:
            rendered = executor.render_plan(rebased)
            warn_lines = [f"warn        {w}" for w in warnings]
            lines = warn_lines + ([rendered] if rendered else [])
            print("\n".join(lines))
        return _common.OK

    # 9. Execute the rebased plan (the only disk-touching step).
    report = executor.execute(rebased)

    # 10. Persist the consumer manifest (the command owns this — rebase_plan passes the
    #     WriteManifest through untouched because the executor writes it relative to CWD).
    m = manifest_res.value
    for entry in entries:
        m = manifest.upsert(m, entry)
    _common.save_manifest(project, m)

    # 11. Report (include the unsupported-type skip warnings from the §5 partition).
    all_warnings = [_skip_message(s) for s in skipped_targets] + list(report.warnings)
    if request.json:
        _common.print_json(
            {
                "installed": [
                    {"artifact": e.artifact, "type": e.type, "profile": e.profile}
                    for e in entries
                ],
                "skipped": [skipped_target_to_dict(s) for s in skipped_targets],
                "performed": list(report.performed),
                "warnings": all_warnings,
                "manifest": _common.manifest_path(project),
            }
        )
    else:
        _print_summary(entries, all_warnings)
    return _common.OK


def _print_summary(entries, warnings) -> None:
    """Print a concise human-readable install summary."""
    n = len(entries)
    print(f"Installed {n} artifact{'s' if n != 1 else ''}:")
    for e in entries:
        print(f"  - {e.type:<9} {e.artifact} -> {e.profile}")
    for w in warnings:
        print(f"warning: {w}")
