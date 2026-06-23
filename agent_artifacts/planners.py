"""Type planners — pure (WP-5). Compose policy (WP-2) + merge (WP-3) into a `Plan`.

Each `plan_<type>` takes the resolved artifact plus the bytes/values read from the source
and the current on-disk state, and returns ``Result[Plan]``. The hook planner emits both
copy actions (scripts) and a `MergeJson` action (registration) — the hybrid of DESIGN.md §5.4.
``plan_install`` is the top-level aggregator that accumulates errors across artifacts.

Everything here is **pure**: no filesystem or network access. Planners build immutable
``Action`` tuples; the shell (WP-9 executor) is the only thing that touches disk.
"""

from __future__ import annotations

from typing import Callable, Mapping, Optional, Sequence, Tuple

from . import fp, merge
from .hashing import sha256_bytes
from .model import (
    Action,
    Artifact,
    ArtifactType,
    CopyTree,
    Err,
    GuidelineTarget,
    HookTarget,
    ManifestEntry,
    MemoryTarget,
    MergeJson,
    MergeProof,
    MergeSpec,
    Ok,
    Plan,
    Profile,
    Result,
    Warn,
    WriteFile,
    WriteManifest,
)

# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #
_NAME_PLACEHOLDER = "<name>"


def _substitute_name(template: str, name: str) -> str:
    """Replace the literal ``<name>`` placeholder in a profile path with `name`."""
    return template.replace(_NAME_PLACEHOLDER, name)


def _join(*parts: str) -> str:
    """Join path segments with ``/`` without collapsing into an absolute path.

    Pure string join (no ``os.path``) so the result is deterministic and golden-testable
    on any platform: trailing/leading slashes between segments are normalised to one.
    """
    cleaned = []
    for i, part in enumerate(parts):
        if part == "":
            continue
        seg = part if i == 0 else part.lstrip("/")
        seg = seg if i == len(parts) - 1 else seg.rstrip("/")
        cleaned.append(seg)
    return "/".join(cleaned)


def memory_sentinel_markers(name: str) -> Tuple[str, str]:
    """Return the ``(begin, end)`` HTML-comment markers wrapping our ``memory`` block.

    The memory file *is* the instruction context the model reads, so the markers are **HTML
    comments** (invisible in rendered markdown) and **name-scoped** (``memory:<name>``):
    stable markers let `plan_memory` replace exactly our prior block on re-install
    (idempotent) while leaving foreign content untouched (DESIGN-memory.md §3.3). Guidelines
    do NOT use sentinels — they are standalone copied files, never merged into a shared file.
    """
    return (
        f"<!-- >>> agent-artifacts memory:{name} >>> -->",
        f"<!-- <<< agent-artifacts memory:{name} <<< -->",
    )


def _replace_marked_block(
    existing_text: Optional[str],
    markers: Tuple[str, str],
    body: str,
    *,
    position: str = "bottom",
) -> str:
    """Insert/replace the ``markers`` block inside `existing_text`.

    Generalization of the sentinel placement used by both guidelines and memory. The block
    is ``begin\\n<body>\\nend``. Idempotent in either position: if a block with the same
    markers already exists it is replaced **in place** (preserving its location), otherwise
    a fresh block is inserted at ``position`` — ``"bottom"`` after foreign content (the
    historical guideline behaviour, byte-for-byte) or ``"top"`` before it. Content outside
    the markers is preserved verbatim.
    """
    begin, end = markers
    block = f"{begin}\n{body.rstrip(chr(10))}\n{end}"

    base = existing_text or ""
    start = base.find(begin)
    if start != -1:
        # Replace our existing block in place, wherever it currently sits.
        stop = base.find(end, start)
        if stop != -1:
            stop_end = stop + len(end)
            # Swallow a trailing newline so repeated installs don't grow blank lines.
            tail = base[stop_end:]
            if tail.startswith("\n"):
                tail = tail[1:]
            return base[:start] + block + ("\n" + tail if tail else "\n")
        # Begin marker without a matching end: treat the rest of the file as the block.
        return base[:start] + block + "\n"

    if position == "top":
        # Our block goes first; foreign content (if any) follows after one blank line.
        if base == "":
            return block + "\n"
        if not base.endswith("\n"):
            base += "\n"
        return block + "\n\n" + base

    # position == "bottom": append after foreign content (historical guideline behaviour).
    if base and not base.endswith("\n"):
        base += "\n"
    if base:
        base += "\n"  # one blank line between foreign content and our block
    return base + block + "\n"


# --------------------------------------------------------------------------- #
# Skill planner                                                                #
# --------------------------------------------------------------------------- #
def plan_skill(
    artifact: Artifact,
    target_dir: str,
    *,
    force: bool = False,
) -> Result:
    """Plan installation of a skill: copy its whole tree into the profile's skills dir.

    Args:
        artifact: the resolved skill `Artifact` (``artifact.root`` is the source tree).
        target_dir: the profile's skills directory template, e.g.
            ``".claude/skills/<name>/"``. The ``<name>`` placeholder is replaced with
            ``artifact.name``; if absent, the tree is copied *into* ``target_dir/<name>``.
        force: accepted for signature symmetry; copy semantics don't branch on it (the
            executor applies the per-file update policy at run time).

    Returns:
        ``Ok((CopyTree(src=artifact.root, dst=<resolved dir>),))``.
    """
    if _NAME_PLACEHOLDER in target_dir:
        dst = _substitute_name(target_dir, artifact.name)
    else:
        dst = _join(target_dir, artifact.name)
    dst = dst.rstrip("/")
    return Ok((CopyTree(src=artifact.root, dst=dst),))


# --------------------------------------------------------------------------- #
# Guideline planner                                                            #
# --------------------------------------------------------------------------- #
def plan_guideline(
    artifact: Artifact,
    target: GuidelineTarget,
    text: str,
    *,
    force: bool = False,
) -> Result:
    """Plan installation of a guideline — a standalone reference doc (copy-only).

    We write the guideline body verbatim as ``<target.dest>/<artifact.name>.md``
    (``target.dest`` is a directory). Guidelines never merge into a shared file, so there is
    no mode, no ``existing_text``, and no sentinel wrapping — that behaviour belongs to the
    ``memory`` artifact (`plan_memory`).

    Args:
        artifact: the resolved guideline `Artifact`.
        target: the profile's `GuidelineTarget` (just a destination directory).
        text: the guideline body read from the source.
        force: accepted for signature symmetry; copy semantics don't branch on it (the
            executor applies the per-file update policy at run time).

    Returns:
        ``Ok((WriteFile(path, content),))``.
    """
    dest_path = _join(target.dest, f"{artifact.name}.md")
    return Ok((WriteFile(path=dest_path, content=text.encode("utf-8")),))


# --------------------------------------------------------------------------- #
# Memory planner (DESIGN-memory.md §3.2 / §8.1)                                #
# --------------------------------------------------------------------------- #
_BAK_SUFFIX = ".agent-artifacts-bak"


def plan_memory(
    artifact: Artifact,
    target: MemoryTarget,
    text: str,
    existing_text: Optional[str],
    exists: bool,
    *,
    mode: str,
    force: bool = False,
) -> Result:
    """Plan installation of an ``memory`` instruction file (DESIGN-memory.md §3.2/§8.1).

    The destination is either a single shared instruction file (``target.kind == "file"``,
    e.g. ``CLAUDE.md``/``AGENTS.md`` — all four modes apply) or a directory the harness has
    no single instruction file for (``target.kind == "dir"`` — copy as ``<name>.md``; only
    ``skip`` is meaningful, the content-merge modes don't apply). Every mode reduces to the
    existing `WriteFile`/`Warn` actions — no new `Action` type.

    Args:
        artifact: the resolved ``memory`` `Artifact`.
        target: the profile's `MemoryTarget` (``kind`` + ``dest``).
        text: our instruction-file body read from the source artifact.
        existing_text: current contents of the destination file (``None`` if absent). Only
            consulted for ``kind == "file"`` content-merge / replace-backup decisions.
        exists: whether the destination already exists on disk. Drives ``skip`` (both kinds)
            without forcing a body read for the dir case.
        mode: the resolved install mode (``replace``/``prepend``/``append``/``skip``).
        force: gate for the destructive ``replace`` over non-empty existing content.

    Returns:
        ``Ok(plan)`` for the resolved mode, or ``Err`` (``code=4`` for a ``replace``
        conflict without ``--force``; ``code=1`` for an unknown mode).
    """
    if target.kind == "dir":
        dest_path = _join(target.dest, f"{artifact.name}.md")
        if mode == "skip" and exists:
            return Ok(())  # seed-if-missing: leave the existing file untouched
        return Ok((WriteFile(path=dest_path, content=text.encode("utf-8")),))

    # target.kind == "file" — the four content modes.
    dest = target.dest

    if mode == "skip":
        if exists:
            return Ok((Warn(message=f"memory {artifact.name!r}: {dest} exists; skipped"),))
        return Ok((WriteFile(path=dest, content=text.encode("utf-8")),))

    if mode == "replace":
        nonempty = bool((existing_text or "").strip())
        if nonempty and not force:
            return Err(
                f"memory {artifact.name!r}: {dest} exists; use --force to replace",
                code=4,
            )
        actions: Tuple[Action, ...] = ()
        if nonempty:
            actions += (
                WriteFile(
                    path=dest + _BAK_SUFFIX,
                    content=(existing_text or "").encode("utf-8"),
                ),
            )
        actions += (WriteFile(path=dest, content=text.encode("utf-8")),)
        return Ok(actions)

    if mode in ("prepend", "append"):
        position = "top" if mode == "prepend" else "bottom"
        markers = memory_sentinel_markers(artifact.name)
        merged = _replace_marked_block(existing_text, markers, text, position=position)
        return Ok((WriteFile(path=dest, content=merged.encode("utf-8")),))

    return Err(f"unknown memory mode: {mode!r}")


# --------------------------------------------------------------------------- #
# MCP planner                                                                  #
# --------------------------------------------------------------------------- #
def plan_mcp(
    artifact: Artifact,
    descriptor: Mapping,
    spec: MergeSpec,
    existing_config: Mapping,
    *,
    force: bool = False,
) -> Result:
    """Plan installation of an MCP server: merge ``name -> server`` into the harness config.

    Args:
        artifact: the resolved mcp `Artifact`.
        descriptor: the parsed ``mcp/<name>.json`` dict, with at least ``name`` and
            ``server`` keys (DESIGN.md §5.3).
        spec: the profile's key-mode `MergeSpec` (e.g. ``.mcp.json`` · ``mcpServers``).
        existing_config: the already-loaded target config dict (``{}`` if the file is
            absent). Used only to detect a collision; never mutated.
        force: overwrite an existing, differing entry instead of failing.

    Returns:
        ``Ok((MergeJson(...),))`` or the `Err` propagated from `merge.plan_merge` on a
        collision (existing key present and different, no force).
    """
    key = descriptor.get("name", artifact.name)
    value = descriptor.get("server", {})
    result = merge.plan_merge(spec, value, existing_config, key=key, force=force)
    return fp.map_ok(result, lambda action: (action,))


# --------------------------------------------------------------------------- #
# Hook planner                                                                 #
# --------------------------------------------------------------------------- #
def plan_hook(
    artifact: Artifact,
    descriptor: Mapping,
    hooks: HookTarget,
    existing_config: Mapping = {},
    *,
    force: bool = False,
) -> Result:
    """Plan installation of a hook: copy scripts (skill mechanics) + merge registration.

    A hook is a hybrid (DESIGN.md §5.4): its script files land on disk like a skill, and
    its *registration* is merged into the harness's shared config like an MCP entry. This
    planner therefore always emits BOTH a copy action AND one `MergeJson`.

    Args:
        artifact: the resolved hook `Artifact` (``artifact.root`` is the source folder).
        descriptor: the parsed ``hook.json`` dict (``name``, ``command``, ``matcher``,
            ``events``, ``files`` …). Rendered through ``hooks.merge.entry_template`` to
            produce the harness-shaped registration entry.
        hooks: the profile's `HookTarget` (``scripts_dir`` template + merge `MergeSpec`).
        existing_config: the already-loaded target config dict (``{}`` if absent). For the
            built-in list-mode hooks this is informational; key-mode would collision-check.
        force: overwrite a colliding registration entry instead of failing.

    Returns:
        ``Ok(plan)`` where ``plan`` is one `CopyTree` of the whole script tree followed by
        one `MergeJson`, or the `Err` propagated from `merge.plan_merge`.
    """
    scripts_dir = _substitute_name(hooks.scripts_dir, artifact.name).rstrip("/")
    copy_actions: Tuple[Action, ...] = (CopyTree(src=artifact.root, dst=scripts_dir),)

    rendered = merge.render(hooks.merge.entry_template, descriptor)
    merge_result = merge.plan_merge(
        hooks.merge,
        rendered,
        existing_config,
        key=descriptor.get("name", artifact.name),
        force=force,
    )
    return fp.map_ok(merge_result, lambda action: copy_actions + (action,))


# --------------------------------------------------------------------------- #
# Dispatch table (value-keyed, not subclasses — DESIGN.md §14)                 #
# --------------------------------------------------------------------------- #
PLANNERS: Mapping[ArtifactType, Callable[..., Result]] = {
    "skill": plan_skill,
    "guideline": plan_guideline,
    "mcp": plan_mcp,
    "hook": plan_hook,
    "memory": plan_memory,
}


# --------------------------------------------------------------------------- #
# Manifest-entry construction (proof of install, DESIGN.md §12)                #
# --------------------------------------------------------------------------- #
def _files_proof(plan: Plan) -> Mapping[str, str]:
    """Collect ``path -> sha256`` proofs for the copy/write actions in `plan`.

    `WriteFile` content is hashed directly. `CopyTree` payloads aren't known to the pure
    core (the bytes live on disk), so the path is recorded with an empty hash for the shell
    (WP-9/WP-12) to fill in after copying.
    """
    proof = {}
    for action in plan:
        if isinstance(action, WriteFile):
            if action.path.endswith(_BAK_SUFFIX):
                # The replace-mode backup sidecar is not an installed file: uninstall restores
                # it rather than tracking/removing it (DESIGN-memory.md §8.3). Recording it
                # would make uninstall delete the backup before it could be restored.
                continue
            proof[action.path] = sha256_bytes(action.content)
        elif isinstance(action, CopyTree):
            proof[action.dst] = ""
    return proof


def _merge_proof(plan: Plan) -> Optional[MergeProof]:
    """Build a `MergeProof` from the (last) `MergeJson` in `plan`, if any."""
    for action in reversed(plan):
        if isinstance(action, MergeJson):
            json_path = action.json_path
            if action.mode == "key" and action.identity:
                json_path = f"{action.json_path}.{action.identity[0]}"
            return MergeProof(
                file=action.file,
                json_path=json_path,
                mode=action.mode,
                identity={k: None for k in action.identity},
                value_hash=sha256_bytes(repr(action.value).encode("utf-8")),
            )
    return None


def _manifest_entry(
    artifact: Artifact,
    profile_name: str,
    plan: Plan,
    *,
    source: str,
    bundle: Optional[str],
    installed_at: str,
) -> ManifestEntry:
    """Assemble a `ManifestEntry` (proof of install) for one artifact×profile Plan."""
    return ManifestEntry(
        artifact=artifact.name,
        type=artifact.type,
        profile=profile_name,
        source=source,
        bundle=bundle,
        files=_files_proof(plan),
        merge=_merge_proof(plan),
        installed_at=installed_at,
    )


# --------------------------------------------------------------------------- #
# Top-level aggregator                                                         #
# --------------------------------------------------------------------------- #
def plan_install(
    request,
    catalog,
    files: Mapping[str, object],
    profiles: Mapping[str, Profile],
    manifest,
    configs: Mapping[str, Mapping],
) -> Result:
    """Build the full install `Plan` for every target artifact×profile.

    Pure aggregator: for each resolved target it looks up the planner via
    ``PLANNERS[artifact.type]``, gathers that planner's inputs from `files`/`configs`,
    calls it, **accumulates** errors across all targets (via `fp.collect`), concatenates
    the per-artifact Plans, and appends a trailing `WriteManifest`.

    Input shapes (Wave-2 ``install`` command is responsible for assembling these):

    - ``request`` — the parsed `Request`. Only ``request.force`` is consulted here.
    - ``catalog`` — accepted for symmetry / future use; targets are taken from
      ``request`` (see below). Not dereferenced in this function.
    - ``targets`` — derived from ``(request.names, request.profiles)``; each target is the
      tuple ``(artifact: Artifact, profile_name: str)``. (In this WP we read them off
      ``request.names`` paired with ``request.profiles`` via the catalog the caller passed
      in ``files["__targets__"]`` — see below — keeping `plan_install` decoupled from the
      WP-1 resolver.)
    - ``files`` — a mapping that MUST contain:
        * ``"__targets__"`` -> ``Sequence[Tuple[Artifact, str]]`` — the resolved
          ``(artifact, profile_name)`` pairs to install.
        * for each **skill**: nothing extra (copy uses ``artifact.root``).
        * for each **guideline** ``a``: ``f"guideline:{a.name}"`` -> ``str`` body text
          (copied verbatim into the profile's guidelines dir as ``<name>.md``).
        * for each **mcp**/**hook** ``a``: ``f"descriptor:{a.name}"`` -> ``dict`` (parsed
          ``mcp/<name>.json`` or ``hook.json``). Hooks copy their whole script tree.
      Optional metadata keys (used only to fill manifest proofs, all default sensibly):
        * ``f"source:{a.name}"`` -> ``str`` resolved source label (default ``"main:?"``).
        * ``f"bundle:{a.name}"`` -> ``str`` bundle name (default ``None``).
        * ``"__installed_at__"`` -> ISO timestamp string (default ``""``).
    - ``profiles`` — ``profile_name -> Profile`` (built-ins + overrides, WP-8).
    - ``manifest`` — current `Manifest`; accepted for symmetry (drift/diff is WP-13's
      concern). Not dereferenced here.
    - ``configs`` — ``profile_name -> config dict`` (the already-loaded harness config used
      for collision detection by the mcp/hook planners; ``{}`` when the file is absent).

    Returns:
        ``Ok(plan + (WriteManifest(entries),))`` on success, or a single `Err` whose
        reason concatenates EVERY target's failure (collision messages, missing inputs,
        unknown modes) — so the command reports all problems at once.
    """
    force = bool(getattr(request, "force", False))
    installed_at = str(files.get("__installed_at__", ""))
    targets: Sequence[Tuple[Artifact, str]] = files.get("__targets__", ())  # type: ignore[assignment]

    per_target_results = tuple(
        _plan_one(artifact, profile_name, files, profiles, configs, force=force)
        for artifact, profile_name in targets
    )

    accumulated = fp.collect(per_target_results)
    if isinstance(accumulated, Err):
        return accumulated

    plan: Tuple[Action, ...] = ()
    entries: Tuple[ManifestEntry, ...] = ()
    for (artifact, profile_name), sub_plan in zip(targets, accumulated.value, strict=True):
        plan += sub_plan
        entries += (
            _manifest_entry(
                artifact,
                profile_name,
                sub_plan,
                source=str(files.get(f"source:{artifact.name}", "main:?")),
                bundle=files.get(f"bundle:{artifact.name}"),  # type: ignore[arg-type]
                installed_at=installed_at,
            ),
        )

    return Ok(plan + (WriteManifest(entries=entries),))


def _plan_one(
    artifact: Artifact,
    profile_name: str,
    files: Mapping[str, object],
    profiles: Mapping[str, Profile],
    configs: Mapping[str, Mapping],
    *,
    force: bool,
) -> Result:
    """Dispatch a single artifact×profile to its planner, gathering inputs from `files`."""
    profile = profiles.get(profile_name)
    if profile is None:
        return Err(f"unknown profile: {profile_name!r}")

    planner = PLANNERS.get(artifact.type)
    if planner is None:
        return Err(f"no planner for artifact type: {artifact.type!r}")

    config = configs.get(profile_name, {})

    if artifact.type == "skill":
        if profile.skills is None:
            return Err(f"profile {profile_name!r} does not support skills")
        return plan_skill(artifact, profile.skills.dir, force=force)

    if artifact.type == "guideline":
        text = files.get(f"guideline:{artifact.name}")
        if not isinstance(text, str):
            return Err(f"missing guideline text for {artifact.name!r}")
        if profile.guidelines is None:
            return Err(f"profile {profile_name!r} does not support guidelines")
        return plan_guideline(artifact, profile.guidelines, text, force=force)

    if artifact.type == "mcp":
        descriptor = files.get(f"descriptor:{artifact.name}")
        if not isinstance(descriptor, Mapping):
            return Err(f"missing mcp descriptor for {artifact.name!r}")
        if profile.mcp is None:
            return Err(f"profile {profile_name!r} does not support mcp")
        return plan_mcp(artifact, descriptor, profile.mcp, config, force=force)

    if artifact.type == "hook":
        descriptor = files.get(f"descriptor:{artifact.name}")
        if not isinstance(descriptor, Mapping):
            return Err(f"missing hook descriptor for {artifact.name!r}")
        if profile.hooks is None:
            return Err(f"profile {profile_name!r} does not support hooks")
        return plan_hook(artifact, descriptor, profile.hooks, config, force=force)

    if artifact.type == "memory":
        if profile.memory is None:
            return Err(f"profile {profile_name!r} does not support memory")
        body = files.get(f"memory:{artifact.name}")
        if not isinstance(body, str):
            return Err(f"missing memory text for {artifact.name!r}")
        existing = files.get(f"existing-memory:{profile_name}:{artifact.name}")
        existing_text = existing if isinstance(existing, str) else None
        exists = bool(files.get(f"memory-exists:{profile_name}:{artifact.name}", False))
        mode = str(files.get(f"memory-mode:{artifact.name}", "prepend"))
        return plan_memory(
            artifact,
            profile.memory,
            body,
            existing_text,
            exists,
            mode=mode,
            force=force,
        )

    return Err(f"unhandled artifact type: {artifact.type!r}")  # pragma: no cover
