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
from .model import (
    Action,
    Artifact,
    ArtifactType,
    CopyTree,
    Err,
    GuidelineTarget,
    HookTarget,
    ManifestEntry,
    MergeJson,
    MergeProof,
    MergeSpec,
    Ok,
    Plan,
    Profile,
    Result,
    WriteFile,
    WriteManifest,
)
from .hashing import sha256_bytes

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


def sentinel_markers(name: str) -> Tuple[str, str]:
    """Return the ``(begin, end)`` sentinel lines that wrap our guideline block.

    Stable, name-scoped markers let `plan_guideline` replace exactly our prior block on
    re-install (idempotent) while leaving foreign content untouched.
    """
    return (
        f"# >>> agent-artifacts: {name} >>>",
        f"# <<< agent-artifacts: {name} <<<",
    )


def _replace_sentinel_block(existing_text: Optional[str], name: str, body: str) -> str:
    """Insert/replace the ``name`` sentinel block inside `existing_text`.

    Idempotent: if a block with the same markers already exists it is replaced in place;
    otherwise the block is appended. Content outside the markers is preserved verbatim.
    """
    begin, end = sentinel_markers(name)
    block = f"{begin}\n{body.rstrip(chr(10))}\n{end}"

    base = existing_text or ""
    start = base.find(begin)
    if start != -1:
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
    existing_text: Optional[str] = None,
    *,
    force: bool = False,
) -> Result:
    """Plan installation of a guideline file.

    Two modes, selected by ``target.mode``:

    - ``"copy"``: write our content as a standalone file at
      ``<target.dest>/<artifact.name>.md`` (``target.dest`` is a directory).
    - ``"append-sentinel"``: ``target.dest`` is a single shared file (e.g. ``CLAUDE.md``).
      We emit ONE `WriteFile` of the whole file with our content wrapped in name-scoped
      sentinel markers, replacing any existing same-named block in `existing_text`
      (idempotent — re-installing yields a byte-identical block).

    Args:
        artifact: the resolved guideline `Artifact`.
        target: the profile's `GuidelineTarget` (mode + dest).
        text: the guideline body read from the source.
        existing_text: current contents of the destination file (``None`` if absent).
            Only consulted in ``append-sentinel`` mode.
        force: accepted for signature symmetry; not used (sentinel replacement is always
            in-place and conflict-free for our own block).

    Returns:
        ``Ok((WriteFile(path, content),))`` or ``Err`` for an unknown mode.
    """
    if target.mode == "copy":
        dest_path = _join(target.dest, f"{artifact.name}.md")
        return Ok((WriteFile(path=dest_path, content=text.encode("utf-8")),))
    if target.mode == "append-sentinel":
        merged = _replace_sentinel_block(existing_text, artifact.name, text)
        return Ok((WriteFile(path=target.dest, content=merged.encode("utf-8")),))
    return Err(f"unknown guideline mode: {target.mode!r}")


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
    script_files: Sequence[str] = (),
    existing_config: Mapping = {},
    *,
    force: bool = False,
) -> Result:
    """Plan installation of a hook: copy scripts (skill mechanics) + merge registration.

    A hook is a hybrid (DESIGN.md §5.4): its script files land on disk like a skill, and
    its *registration* is merged into the harness's shared config like an MCP entry. This
    planner therefore always emits BOTH at least one copy action AND one `MergeJson`.

    Args:
        artifact: the resolved hook `Artifact` (``artifact.root`` is the source folder).
        descriptor: the parsed ``hook.json`` dict (``name``, ``command``, ``matcher``,
            ``events``, ``files`` …). Rendered through ``hooks.merge.entry_template`` to
            produce the harness-shaped registration entry.
        hooks: the profile's `HookTarget` (``scripts_dir`` template + merge `MergeSpec`).
        script_files: optional explicit per-file relative paths under ``artifact.root``.
            When empty, the whole tree is copied (``CopyTree``). When given, each file is
            an individual ``CopyTree`` from ``artifact.root/<file>`` into the resolved
            scripts dir (preserving the relative sub-path).
        existing_config: the already-loaded target config dict (``{}`` if absent). For the
            built-in list-mode hooks this is informational; key-mode would collision-check.
        force: overwrite a colliding registration entry instead of failing.

    Returns:
        ``Ok(plan)`` where ``plan`` contains one-or-more `CopyTree` actions followed by one
        `MergeJson`, or the `Err` propagated from `merge.plan_merge`.
    """
    scripts_dir = _substitute_name(hooks.scripts_dir, artifact.name).rstrip("/")

    copy_actions: Tuple[Action, ...]
    if script_files:
        copy_actions = tuple(
            CopyTree(src=_join(artifact.root, rel), dst=_join(scripts_dir, rel))
            for rel in script_files
        )
    else:
        copy_actions = (CopyTree(src=artifact.root, dst=scripts_dir),)

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
        * for each **guideline** ``a``: ``f"guideline:{a.name}"`` -> ``str`` body text, and
          optionally ``f"existing:{profile}:{a.name}"`` -> current destination file text.
        * for each **mcp**/**hook** ``a``: ``f"descriptor:{a.name}"`` -> ``dict`` (parsed
          ``mcp/<name>.json`` or ``hook.json``); for hooks optionally
          ``f"scripts:{a.name}"`` -> ``Sequence[str]`` of relative script paths.
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
    for (artifact, profile_name), sub_plan in zip(targets, accumulated.value):
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
        return plan_skill(artifact, profile.skills.dir, force=force)

    if artifact.type == "guideline":
        text = files.get(f"guideline:{artifact.name}")
        if not isinstance(text, str):
            return Err(f"missing guideline text for {artifact.name!r}")
        existing = files.get(f"existing:{profile_name}:{artifact.name}")
        existing_text = existing if isinstance(existing, str) else None
        return plan_guideline(
            artifact, profile.guidelines, text, existing_text, force=force
        )

    if artifact.type == "mcp":
        descriptor = files.get(f"descriptor:{artifact.name}")
        if not isinstance(descriptor, Mapping):
            return Err(f"missing mcp descriptor for {artifact.name!r}")
        return plan_mcp(artifact, descriptor, profile.mcp, config, force=force)

    if artifact.type == "hook":
        descriptor = files.get(f"descriptor:{artifact.name}")
        if not isinstance(descriptor, Mapping):
            return Err(f"missing hook descriptor for {artifact.name!r}")
        scripts = files.get(f"scripts:{artifact.name}", ())
        script_files = tuple(scripts) if isinstance(scripts, Sequence) and not isinstance(scripts, str) else ()
        return plan_hook(
            artifact, descriptor, profile.hooks, script_files, config, force=force
        )

    return Err(f"unhandled artifact type: {artifact.type!r}")  # pragma: no cover
