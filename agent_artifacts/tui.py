"""Persistent interactive wizard. The second "skin" over the one command core.

docs/design/DESIGN.md §13 ("one core, two skins"): a bare ``agent-artifacts`` on a TTY launches this
selector; otherwise the CLI runs in flag mode. This module owns **no** consumer or upstream
mutation logic — it gathers role/action selections, assembles
:class:`~agent_artifacts.model.Request` values, and dispatches them through the exact same command
handlers the flag-mode CLI uses. The decision logic stays in the pure core / commands.

Two front-ends, one body:

* ``run()`` — the entry point ``cli._run_bare`` calls on a TTY. It prefers a ``curses``
  full-screen selector and **degrades to a plain ``input()``/``print()`` flow** when curses
  is unavailable or fails to initialise (no TTY, dumb terminal, ``curses`` import/`setupterm`
  error). Either way the *same* selection→Request→dispatch path runs.
* ``_run_text(read, write, ...)`` — the fallback flow, factored so I/O and source resolution are
  injectable. Text and curses fold explicit input events into the same immutable
  :class:`~agent_artifacts.wizard.WizardSession`, then map only a finalized Review to the command
  core. This keeps the complete interaction headlessly testable without a real terminal.

Dispatch is resilient to integration order: it prefers ``cli.DISPATCH`` (WP-19) when present
and otherwise imports the command modules directly. Both routes call the *same* ``run``
functions, so no command logic is ever duplicated here.
"""

from __future__ import annotations

import os
import shutil
import textwrap
from dataclasses import dataclass, replace
from typing import Callable, List, Literal, Mapping, Optional, Sequence, Tuple

from .catalog import resolve_bundle
from .compatibility import check_profile_compatibility
from .install_modes import supports_symlink
from .model import (
    Artifact,
    ArtifactType,
    Catalog,
    Err,
    InstallMode,
    InstallScope,
    Manifest,
    ManifestEntry,
    Profile,
    Request,
    Result,
    SetupQueueItem,
)
from .outcomes import ActionSummary, CommandOutcome, OutcomeItem, render_outcome
from .planners import install_target_paths
from .profiles.loader import load_profiles
from .profiles.scope import profile_for_scope
from .setup import build_queue, recovery_messages
from .source import open_source
from .wizard import (
    BasketItem,
    WizardInput,
    WizardSession,
    can_finalize,
    initial_session,
    onboarding_lines,
    reconcile_basket,
    remember_position,
    render_header,
    request_quit,
)
from .wizard import (
    advance as wizard_advance,
)
from .wizard import (
    back as wizard_back,
)
from .wizard import (
    select as wizard_select,
)

# The three write actions the selector can drive; these are the verbs that build and dispatch a
# Request.
ACTIONS: Tuple[str, ...] = ("install", "update", "uninstall", "status")


@dataclass(frozen=True, slots=True)
class _RoleChoice:
    name: Literal["user", "maintainer"]
    label: str
    description: str


ROLES: Tuple[_RoleChoice, ...] = (
    _RoleChoice(
        "user",
        "User",
        "Install, update, or remove harness artifacts from subscribed catalogs.",
    ),
    _RoleChoice(
        "maintainer",
        "Maintainer",
        "Do the same, plus curate the catalog and manage third-party upstreams.",
    ),
)

MAINTAINER_ACTIONS: Tuple[Tuple[str, str], ...] = (
    ("health", "Show catalog health"),
    ("validate", "Validate the local catalog"),
    ("add", "Add one upstream from GitHub"),
    ("import", "Scan and import artifacts from GitHub"),
    ("check", "Check tracked upstreams"),
    ("update", "Preview and update tracked upstreams"),
    ("user", "Enter User workflows"),
)

# Canonical artifact-type display order (matches commands.list / docs/design/DESIGN.md §4).
_TYPE_ORDER: Tuple[ArtifactType, ...] = ("skill", "guideline", "mcp", "hook", "memory")
_TYPE_ATTR = {
    "skill": "skills",
    "guideline": "guidelines",
    "mcp": "mcp",
    "hook": "hooks",
    "memory": "memory",
}

ReadFn = Callable[[str], str]
WriteFn = Callable[[str], None]
SourceFactory = Callable[[Request], Result]
DispatchFn = Callable[[Request], int]


@dataclass(frozen=True, slots=True)
class InstallModeChoice:
    """One user-facing installation-mode choice."""

    mode: InstallMode
    label: str
    description: str


INSTALL_MODE_CHOICES: Tuple[InstallModeChoice, ...] = (
    InstallModeChoice(
        "copy",
        "Copy (recommended)",
        "Install an independent snapshot into the target harness.",
    ),
    InstallModeChoice(
        "symlink",
        "Symlink",
        (
            "Live-link supported skills and hooks to a local catalog; file and merged "
            "artifacts selected through bundles use copy semantics."
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class InstallScopeChoice:
    """One explicit consumer configuration/state boundary."""

    scope: InstallScope
    label: str
    description: str


INSTALL_SCOPE_CHOICES: Tuple[InstallScopeChoice, ...] = (
    InstallScopeChoice(
        "project",
        "Project (recommended)",
        "Configure only the current repository.",
    ),
    InstallScopeChoice(
        "user",
        "User",
        "Configure the selected harnesses for the current user across projects.",
    ),
)


@dataclass(frozen=True, slots=True)
class InstallModeCounts:
    """Projected artifact/profile targets by actual installation mode."""

    linked: int = 0
    copied: int = 0


@dataclass(frozen=True, slots=True)
class InstallConfirmation:
    """Immutable facts rendered by both Install confirmation frontends."""

    source_label: str
    source_root: str
    destination_root: str
    profiles: Tuple[str, ...]
    requested_mode: InstallMode
    selected: Tuple[str, ...]
    modes: InstallModeCounts
    scope: InstallScope = "project"
    destinations: Tuple[str, ...] = ()
    setup_queue: Tuple[SetupQueueItem, ...] = ()


# --------------------------------------------------------------------------- #
# Choice model — a flat, ordered menu derived from the catalog (pure).         #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class _Choice:
    """One selectable catalog row: either a single artifact or a whole bundle.

    ``kind`` is ``"artifact"`` or ``"bundle"``. ``label`` is the human row text. ``key`` is
    ``(type, name)`` for an artifact (so we can build ``Request.names`` + ``type_filter``-free
    selection) or the bundle name for a bundle.
    """

    kind: Literal["artifact", "bundle", "profile"]
    name: str
    type: Optional[ArtifactType]
    label: str
    description: str = ""
    hidden_count: int = 0
    complete: bool = True
    enabled: bool = True
    reason: str = ""
    linked_count: int = 0
    copied_count: int = 0


def _type_rank(t: ArtifactType) -> int:
    return _TYPE_ORDER.index(t) if t in _TYPE_ORDER else len(_TYPE_ORDER)


def _profile_supports(profile: Profile, art_type: ArtifactType) -> bool:
    """True when a profile has a target for ``art_type``."""
    return getattr(profile, _TYPE_ATTR[art_type], None) is not None


def _linkable(artifact: Artifact) -> bool:
    """Whether the existing install core can live-link this artifact's payload."""

    return supports_symlink(artifact.type)


def _choice_label(
    kind: Literal["artifact", "bundle", "profile"],
    name: str,
    art_type: Optional[ArtifactType],
    description: str,
    status: str = "",
) -> str:
    """Render a one-line choice label from structured choice data."""
    if kind == "artifact" and art_type is not None:
        label = f"[{art_type}] {name}"
    elif kind == "bundle":
        label = f"[bundle] {name}"
    else:
        label = name
    if description:
        label += f" — {description}"
    if status:
        label += f" · {status}"
    return label


def artifact_visible_for_profiles(
    artifact: Artifact,
    profile_names: Sequence[str],
    profiles: Mapping[str, Profile],
) -> bool:
    """Whether ``artifact`` is installable for every selected profile.

    This is intentionally an intersection check: selecting ``claude,vibe`` hides MCP/hooks
    because ``vibe`` cannot install them.
    """
    if not profile_names:
        return False
    for profile_name in profile_names:
        profile = profiles.get(profile_name)
        if profile is None:
            return False
        if not _profile_supports(profile, artifact.type):
            return False
        if not check_profile_compatibility(artifact, profile_name).ok:
            return False
    return True


def build_install_choices(
    catalog: Catalog,
    profile_names: Sequence[str],
    profiles: Mapping[str, Profile],
    *,
    install_mode: InstallMode = "copy",
    scope: InstallScope = "project",
) -> Tuple[_Choice, ...]:
    """Build installable artifact/bundle choices for selected profiles."""
    out: List[_Choice] = []
    arts: List[Artifact] = list(catalog.artifacts.values())
    arts.sort(key=lambda a: (_type_rank(a.type), a.name))
    for artifact in arts:
        visible = artifact_visible_for_profiles(artifact, profile_names, profiles)
        if visible:
            linkable = _linkable(artifact)
            enabled = install_mode == "copy" or linkable
            reason = (
                "copy-only; choose Copy or select a mixed bundle"
                if install_mode == "symlink" and not linkable
                else ""
            )
            status = ""
            if install_mode == "symlink":
                status = "will symlink" if linkable else reason
            out.append(
                _Choice(
                    "artifact",
                    artifact.name,
                    artifact.type,
                    _choice_label(
                        "artifact",
                        artifact.name,
                        artifact.type,
                        artifact.description,
                        status,
                    ),
                    description=artifact.description,
                    enabled=enabled,
                    reason=reason,
                    linked_count=(
                        len(profile_names) if install_mode == "symlink" and linkable else 0
                    ),
                    copied_count=(
                        len(profile_names) if install_mode == "copy" or not linkable else 0
                    ),
                )
            )
        elif scope == "user":
            reasons = []
            for profile_name in profile_names:
                profile = profiles.get(profile_name)
                if profile is None:
                    continue
                if not _profile_supports(profile, artifact.type):
                    reasons.append(
                        profile.unsupported.get(
                            artifact.type,
                            f"{profile_name} does not support {artifact.type} in user scope",
                        )
                    )
                elif not check_profile_compatibility(artifact, profile_name).ok:
                    reasons.append(f"not compatible with {profile_name}")
            reason = "; ".join(dict.fromkeys(reasons)) or "unavailable in user scope"
            out.append(
                _Choice(
                    "artifact",
                    artifact.name,
                    artifact.type,
                    _choice_label(
                        "artifact",
                        artifact.name,
                        artifact.type,
                        artifact.description,
                        reason,
                    ),
                    description=artifact.description,
                    enabled=False,
                    reason=reason,
                )
            )

    for bundle_name in sorted(catalog.bundles):
        resolved = resolve_bundle(catalog, bundle_name)
        if isinstance(resolved, Err):
            continue

        visible_artifacts: List[Artifact] = []
        hidden_count = 0
        for artifact_type, artifact_name in resolved.value.artifacts:
            bundle_artifact = catalog.artifacts.get((artifact_type, artifact_name))
            if bundle_artifact is None:
                continue
            if artifact_visible_for_profiles(bundle_artifact, profile_names, profiles):
                visible_artifacts.append(bundle_artifact)
            else:
                hidden_count += 1

        visible_count = len(visible_artifacts)
        if visible_count == 0:
            continue

        bundle = catalog.bundles[bundle_name]
        linked_count = 0
        copied_count = visible_count * len(profile_names)
        status_parts = []
        if install_mode == "symlink":
            linked_count = sum(1 for artifact in visible_artifacts if _linkable(artifact)) * len(
                profile_names
            )
            copied_count = visible_count * len(profile_names) - linked_count
            status_parts.append(f"{linked_count} linked, {copied_count} copied")
        if hidden_count:
            status_parts.append(
                f"{visible_count} installable, {hidden_count} hidden for selected profile(s)"
            )
        status = "; ".join(status_parts)
        out.append(
            _Choice(
                "bundle",
                bundle_name,
                None,
                _choice_label("bundle", bundle_name, None, bundle.description, status),
                description=bundle.description,
                hidden_count=hidden_count,
                complete=hidden_count == 0,
                linked_count=linked_count,
                copied_count=copied_count,
            )
        )

    return tuple(out)


def build_action_choices(
    action: str,
    catalog: Catalog,
    manifest: Optional[Manifest],
    profile_names: Sequence[str],
    profiles: Mapping[str, Profile],
    *,
    install_mode: InstallMode = "copy",
    scope: InstallScope = "project",
) -> Tuple[_Choice, ...]:
    """Build the selectable rows for an action after profile selection."""
    if action == "install":
        return build_install_choices(
            catalog,
            profile_names,
            profiles,
            install_mode=install_mode,
            scope=scope,
        )
    if action in ("update", "uninstall"):
        if manifest is None:
            return ()
        return _build_manifest_choices(action, catalog, manifest, profile_names, profiles)
    return ()


def _selected_install_artifacts(
    catalog: Catalog,
    choices: Sequence[_Choice],
    profile_names: Sequence[str],
    profiles: Mapping[str, Profile],
) -> Tuple[Artifact, ...]:
    """Resolve and de-duplicate eligible artifacts represented by selected rows."""

    keys: List[Tuple[ArtifactType, str]] = []
    seen = set()
    for choice in choices:
        choice_keys: Sequence[Tuple[ArtifactType, str]] = ()
        if choice.kind == "artifact" and choice.type is not None:
            choice_keys = ((choice.type, choice.name),)
        elif choice.kind == "bundle":
            resolved = resolve_bundle(catalog, choice.name)
            if not isinstance(resolved, Err):
                choice_keys = resolved.value.artifacts
        for key in choice_keys:
            if key not in seen:
                seen.add(key)
                keys.append(key)

    return tuple(
        artifact
        for key in keys
        if (artifact := catalog.artifacts.get(key)) is not None
        and artifact_visible_for_profiles(artifact, profile_names, profiles)
    )


def install_selection_mode_counts(
    catalog: Catalog,
    choices: Sequence[_Choice],
    profile_names: Sequence[str],
    profiles: Mapping[str, Profile],
    install_mode: InstallMode,
) -> InstallModeCounts:
    """Count projected actual modes over de-duplicated artifact/profile targets."""

    artifacts = _selected_install_artifacts(catalog, choices, profile_names, profiles)
    target_multiplier = len(profile_names)
    if install_mode == "copy":
        return InstallModeCounts(copied=len(artifacts) * target_multiplier)
    linked = sum(1 for artifact in artifacts if _linkable(artifact)) * target_multiplier
    return InstallModeCounts(
        linked=linked,
        copied=len(artifacts) * target_multiplier - linked,
    )


def build_install_confirmation(
    *,
    source_label: str,
    source_root: str,
    project: Optional[str],
    profiles: Sequence[str],
    requested_mode: InstallMode,
    catalog: Catalog,
    choices: Sequence[_Choice],
    profiles_map: Mapping[str, Profile],
    scope: InstallScope = "project",
    user_home: Optional[str] = None,
) -> InstallConfirmation:
    """Build the shared immutable confirmation model for an Install selection."""

    destination_root = (
        os.path.abspath(user_home or os.path.expanduser("~"))
        if scope == "user"
        else os.path.abspath(project or ".")
    )
    destinations: List[str] = []
    seen_destinations = set()
    artifacts = _selected_install_artifacts(catalog, choices, profiles, profiles_map)
    for artifact in artifacts:
        for profile_name in profiles:
            profile = profiles_map.get(profile_name)
            if profile is None:
                continue
            for target in install_target_paths(artifact, profile):
                absolute = (
                    target if os.path.isabs(target) else os.path.join(destination_root, target)
                )
                absolute = os.path.normpath(absolute)
                if absolute not in seen_destinations:
                    seen_destinations.add(absolute)
                    destinations.append(absolute)
    return InstallConfirmation(
        source_label=source_label,
        source_root=os.path.abspath(source_root),
        destination_root=destination_root,
        profiles=tuple(profiles),
        requested_mode=requested_mode,
        selected=tuple(choice.name for choice in choices),
        modes=install_selection_mode_counts(
            catalog,
            choices,
            profiles,
            profiles_map,
            requested_mode,
        ),
        scope=scope,
        destinations=tuple(destinations),
        setup_queue=build_queue(
            artifacts,
            profiles,
            scope=scope,
            source_label=source_label,
            source_root=os.path.abspath(source_root),
        ),
    )


def render_install_confirmation(confirmation: InstallConfirmation) -> Tuple[str, ...]:
    """Pure text projection shared by text and curses Install confirmation."""

    mode_label = "Symlink" if confirmation.requested_mode == "symlink" else "Copy"
    scope_label = "User" if confirmation.scope == "user" else "Project"
    lines: Tuple[str, ...] = (
        "Review installation",
        "  Role: User",
        "  Action: Install",
        f"  Source: {confirmation.source_label} ({confirmation.source_root})",
        f"  Destination: {scope_label} — {confirmation.destination_root}",
        f"  Harnesses: {', '.join(confirmation.profiles)}",
        f"  Requested mode: {mode_label}",
        (
            f"  Projected modes: {confirmation.modes.linked} linked, "
            f"{confirmation.modes.copied} copied"
        ),
        f"  Selected count: {len(confirmation.selected)}",
        f"  Selected: {', '.join(confirmation.selected)}",
        "  Expected mutation: install managed artifacts and record their manifest state.",
    )
    if confirmation.modes.linked and confirmation.modes.copied:
        lines += ("  Warning: mixed-mode fallback copies targets that cannot be safely symlinked.",)
    if confirmation.scope == "user" and confirmation.destinations:
        lines += ("  Resolved destinations:",) + tuple(
            f"    - {path}" for path in confirmation.destinations
        )
    if confirmation.setup_queue:
        lines += ("  Setup queue (runs after artifact installation):",) + tuple(
            (
                f"    - {item.artifact_type}/{item.artifact_name}@{item.profile}: "
                f"{item.installer.purpose}"
            )
            for item in confirmation.setup_queue
        )
    return lines


def _build_manifest_choices(
    action: str,
    catalog: Catalog,
    manifest: Manifest,
    profile_names: Sequence[str],
    profiles: Mapping[str, Profile],
) -> Tuple[_Choice, ...]:
    """Build update/uninstall choices from installed manifest entries."""
    profile_set = set(profile_names)
    entries = [entry for entry in manifest.installed if entry.profile in profile_set]
    out: List[_Choice] = []
    seen_names = set()
    bundle_names = set()

    for entry in entries:
        artifact = catalog.artifacts.get((entry.type, entry.artifact))
        if action == "update":
            if artifact is not None and not artifact_visible_for_profiles(
                artifact, (entry.profile,), profiles
            ):
                continue

        if entry.artifact not in seen_names:
            seen_names.add(entry.artifact)
            description = artifact.description if artifact is not None else ""
            out.append(
                _Choice(
                    "artifact",
                    entry.artifact,
                    entry.type,
                    _choice_label("artifact", entry.artifact, entry.type, description),
                    description=description,
                )
            )
        if entry.bundle:
            bundle_names.add(entry.bundle)

    for bundle_name in sorted(bundle_names):
        bundle = catalog.bundles.get(bundle_name)
        description = bundle.description if bundle is not None else ""
        out.append(
            _Choice(
                "bundle",
                bundle_name,
                None,
                _choice_label("bundle", bundle_name, None, description, "installed"),
                description=description,
            )
        )
    return tuple(out)


# --------------------------------------------------------------------------- #
# Request assembly + dispatch (the single bridge into the command core).        #
# --------------------------------------------------------------------------- #
def _build_request(
    action: str,
    chosen: Sequence[_Choice],
    profiles: Sequence[str],
    *,
    source_dir: Optional[str],
    repo: Optional[str],
    project: Optional[str],
    install_mode: InstallMode = "copy",
    scope: InstallScope = "project",
    user_home: Optional[str] = None,
) -> Request:
    """Assemble the `Request` for *action* from the picked rows + profiles.

    Bundle rows populate ``Request.bundles``; artifact rows populate ``Request.names``. The
    selection is left untyped (no ``type_filter``) so a bare name resolves across types via
    ``_common.resolve_artifacts`` exactly as flag-mode does. ``yes=True`` because the user
    already confirmed interactively; we never re-prompt at the command layer.
    """
    names = tuple(c.name for c in chosen if c.kind == "artifact")
    bundles = tuple(c.name for c in chosen if c.kind == "bundle")
    return Request(
        command=action,
        names=names,
        bundles=bundles,
        profiles=tuple(profiles),
        source_dir=source_dir,
        repo=repo,
        project=project if scope == "project" else None,
        scope=scope,
        user_home=user_home,
        yes=True,
        install_mode=install_mode,
    )


def _dispatch(request: Request) -> int:
    """Route *request* through the same handlers the flag-mode CLI uses.

    Prefers ``cli.DISPATCH`` (WP-19) when it exists; otherwise imports the command module
    for ``request.command`` directly. Both paths call the identical ``run`` function — this
    module duplicates **no** command logic.
    """
    try:
        from . import cli

        dispatch = getattr(cli, "DISPATCH", None)
    except Exception:  # pragma: no cover - cli import is trivial
        dispatch = None

    if isinstance(dispatch, Mapping) and request.command in dispatch:
        return int(dispatch[request.command](request))

    # Fallback: import the specific command module on demand (avoids importing all of them
    # and keeps this independent of WP-19's merge state).
    from importlib import import_module

    module = import_module(f".commands.{request.command}", package=__package__)
    return int(module.run(request))


_ORIGINAL_DISPATCH = _dispatch


def _dispatch_result(request: Request) -> CommandOutcome:
    """Dispatch a command through its structured result contract."""

    # Preserve the long-standing injectable dispatch seam used by headless frontend tests and
    # embedders. Production keeps the original function and takes the structured path below.
    if _dispatch is not _ORIGINAL_DISPATCH:
        code = int(_dispatch(request))
        item = (
            OutcomeItem(f"{request.command}-request", "up_to_date")
            if code == 0
            else OutcomeItem(f"{request.command}-request", "failed")
        )
        return CommandOutcome(
            exit_code=code,
            summary=ActionSummary(action=request.command, items=(item,)),
        )

    try:
        from . import cli

        dispatch = getattr(cli, "RESULT_DISPATCH", None)
    except Exception:  # pragma: no cover - cli import is trivial
        dispatch = None

    if isinstance(dispatch, Mapping) and request.command in dispatch:
        return dispatch[request.command](request)

    from importlib import import_module

    module = import_module(f".commands.{request.command}", package=__package__)
    execute = getattr(module, "execute", None)
    if callable(execute):
        return execute(request)

    code = _dispatch(request)
    item = (
        OutcomeItem(f"{request.command}-request", "up_to_date")
        if code == 0
        else OutcomeItem(f"{request.command}-request", "failed")
    )
    return CommandOutcome(
        exit_code=code,
        summary=ActionSummary(
            action=request.command,
            items=(item,),
        ),
    )


def _run_post_install_setup(
    queue: Sequence[SetupQueueItem],
    request: Request,
    *,
    scope_root: str,
    read: ReadFn,
    write: WriteFn,
) -> int:
    """Run the reviewed setup queue in the foreground after the core install succeeds."""

    if not queue:
        return 0
    from .commands import setup as setup_command

    setup_request = replace(
        request,
        command="setup",
        setup_action="run",
        yes=False,
        dry_run=False,
    )
    result = setup_command.run_queue(
        queue,
        scope_root=scope_root,
        target_root=os.path.abspath(request.user_home or os.path.expanduser("~")),
        request=setup_request,
        read=read,
        write=write,
    )
    if isinstance(result, Err):
        write(f"error: {result.reason}")
        return result.code
    for record in result:
        write(
            f"Setup {record.artifact_type}/{record.artifact_name}@{record.profile}: "
            f"{record.status} — {record.detail}"
        )
        if record.retry_command:
            write(f"  Retry: {record.retry_command}")
        if record.rollback_command:
            write(f"  Rollback: {record.rollback_command}")
        for message in recovery_messages(record):
            write(f"  Recovery: {message}")
    incomplete = tuple(
        record for record in result if record.status not in ("configured", "already_configured")
    )
    if not incomplete:
        return 0
    try:
        answer = read("Retry incomplete setup now? [Y/n]: ").strip().lower()
    except EOFError:
        answer = "n"
    if answer in ("", "y", "yes"):
        failed_keys = {
            (record.artifact_type, record.artifact_name, record.profile) for record in incomplete
        }
        retry_queue = tuple(
            item
            for item in queue
            if (item.artifact_type, item.artifact_name, item.profile) in failed_keys
        )
        retried = setup_command.run_queue(
            retry_queue,
            scope_root=scope_root,
            target_root=os.path.abspath(request.user_home or os.path.expanduser("~")),
            request=replace(setup_request, setup_action="retry"),
            read=read,
            write=write,
        )
        if isinstance(retried, Err):
            write(f"error: {retried.reason}")
            return retried.code
        for record in retried:
            write(
                f"Setup retry {record.artifact_type}/{record.artifact_name}@{record.profile}: "
                f"{record.status} — {record.detail}"
            )
            if record.rollback_command:
                write(f"  Rollback: {record.rollback_command}")
            for message in recovery_messages(record):
                write(f"  Recovery: {message}")
        return (
            0
            if all(record.status in ("configured", "already_configured") for record in retried)
            else 1
        )
    return 1


def _render_result(result: CommandOutcome, write: WriteFn) -> int:
    for line in render_outcome(result):
        write(line)
    return result.exit_code


def _cancel(write: WriteFn, message: str = "Cancelled; no changes were made.") -> int:
    if message != "Cancelled; no changes were made.":
        write(message)
        return 0
    return _render_result(
        CommandOutcome(
            0,
            ActionSummary(
                action="cancelled",
                items=(OutcomeItem("selection", "cancelled"),),
            ),
        ),
        write,
    )


# --------------------------------------------------------------------------- #
# Text / fallback flow — fully injectable, headless-testable.                   #
# --------------------------------------------------------------------------- #
def _run_user_text(
    read: ReadFn = input,
    write: WriteFn = print,
    *,
    source_factory: SourceFactory = open_source,
    source_dir: Optional[str] = None,
    repo: Optional[str] = None,
    project: Optional[str] = None,
    user_home: Optional[str] = None,
) -> int:
    """Plain prompt-driven selector. Returns a process exit code.

    Drives profile -> action -> filtered artifact/bundle prompts, assembles a `Request`, and
    dispatches it through the command core. Blank input or ``q`` at any prompt is a clean quit
    (returns 0 without dispatching). Bad numbers re-prompt rather than crash; EOF on the input
    stream is treated as a quit.

    Injection points (so the flow is testable with no real terminal):

    * ``read`` / ``write`` — the I/O channels (default ``input`` / ``print``).
    * ``source_factory`` — ``(Request) -> Result[Source]`` (default :func:`open_source`); a
      test points this at a fixture-backed source.
    * ``source_dir`` / ``repo`` / ``project`` — threaded into every `Request` so the catalog
      shown and the command dispatched resolve against the **same** source (offline-friendly).
    """
    base_profiles = load_profiles(project)
    profile_names = sorted(base_profiles)
    if not profile_names:  # pragma: no cover - built-ins always present
        write("No profiles available.")
        return _cancel(write, "No profiles available; no changes were made.")

    write("Select profile(s):")
    for i, pname in enumerate(profile_names, start=1):
        write(f"  {i:>2}. {pname}")
    prof_choices = tuple(_Choice("profile", p, None, p) for p in profile_names)
    picked_profiles = _prompt_indices(read, write, "Profile (e.g. 1): ", prof_choices)
    if not picked_profiles:
        return _cancel(write)
    profiles = [profile_names[idx] for idx in picked_profiles]

    install_mode: InstallMode = "copy"
    scope: InstallScope = "project"
    profiles_map: Mapping[str, Profile] = base_profiles
    install_source = None
    while True:
        write("Action:")
        for i, act in enumerate(ACTIONS, start=1):
            write(f"  {i:>2}. {act}")
        action = _prompt_action(read, write)
        if action is None:
            return _cancel(write)

        selected_scope = _prompt_install_scope(read, write)
        if selected_scope is None:
            return _cancel(write)
        scope = selected_scope
        resolved_home = os.path.abspath(user_home or os.path.expanduser("~"))
        profiles_map = (
            base_profiles
            if scope == "project"
            else {
                name: profile_for_scope(profile, scope, resolved_home)
                for name, profile in base_profiles.items()
            }
        )
        request_project = project if scope == "project" else None

        if action == "status":
            request = Request(
                command="status",
                project=request_project,
                scope=scope,
                user_home=user_home,
            )
            return _render_result(_dispatch_result(request), write)

        catalog = Catalog(artifacts={}, bundles={})
        if action in ("install", "update"):
            base = Request(
                command=action,
                source_dir=source_dir,
                repo=repo,
                project=request_project,
                scope=scope,
                user_home=user_home,
            )
            src_res = source_factory(base)
            if isinstance(src_res, Err):
                write(f"error: {src_res.reason}")
                return getattr(src_res, "code", 1)
            source = src_res.value

            cat_res = source.catalog()
            if isinstance(cat_res, Err):
                write(f"error: {cat_res.reason}")
                return getattr(cat_res, "code", 1)
            catalog = cat_res.value
            if action == "update" and source_dir is None and repo is None:
                write("Source: recorded catalog subscription(s) from the consumer manifest")
            else:
                write(f"Source: {source.label()}")
            if action == "install":
                selected_mode = _prompt_install_mode(read, write)
                if selected_mode is None:
                    return _cancel(write)
                if selected_mode == "back":
                    continue
                install_mode = selected_mode
                if install_mode == "symlink" and not source.label().startswith("local:"):
                    write(
                        "Symlink requires a durable local catalog; the selected source is remote."
                    )
                    write(
                        "Choose a local catalog with flag mode: "
                        "aart install ... --source DIR --link"
                    )
                    return 2
                install_source = source
        elif action == "uninstall":
            # Descriptions improve the manifest-driven uninstall menu when its source is available,
            # but source/network failure must never make removal unavailable.
            base = Request(
                command=action,
                source_dir=source_dir,
                repo=repo,
                project=request_project,
                scope=scope,
                user_home=user_home,
            )
            src_res = source_factory(base)
            if not isinstance(src_res, Err):
                cat_res = src_res.value.catalog()
                if not isinstance(cat_res, Err):
                    catalog = cat_res.value
        break

    manifest: Optional[Manifest] = None
    if action in ("update", "uninstall"):
        manifest_res = _load_manifest_for_action(
            action,
            source_dir=source_dir,
            repo=repo,
            project=project if scope == "project" else None,
            scope=scope,
            user_home=user_home,
        )
        if isinstance(manifest_res, Err):
            write(f"error: {manifest_res.reason}")
            return getattr(manifest_res, "code", 1)
        manifest = manifest_res.value

    choices = build_action_choices(
        action,
        catalog,
        manifest,
        profiles,
        profiles_map,
        install_mode=install_mode,
        scope=scope,
    )
    if not choices:
        write(_empty_choices_message(action, profiles))
        return _render_result(CommandOutcome(0, ActionSummary(action=action)), write)

    write(f"Select artifact(s)/bundle(s) for {_profiles_label(profiles)}:")
    terminal_width = shutil.get_terminal_size(fallback=(200, 24)).columns
    for i, c in enumerate(choices, start=1):
        write(_text_choice_line(i, c, terminal_width))
    write("Enter ?N to view the full description for item N.")

    picked = _prompt_indices(read, write, "Selection (e.g. 1,3): ", choices)
    if not picked:
        return _cancel(write, "No artifacts selected; no changes were made.")

    chosen = [choices[i] for i in picked]
    request = _build_request(
        action,
        chosen,
        profiles,
        source_dir=source_dir,
        repo=repo,
        project=project,
        install_mode=install_mode,
        scope=scope,
        user_home=user_home,
    )
    confirmation: Optional[InstallConfirmation] = None
    if action == "install":
        assert install_source is not None
        confirmation = build_install_confirmation(
            source_label=install_source.label(),
            source_root=install_source.root,
            project=project,
            profiles=profiles,
            requested_mode=install_mode,
            catalog=catalog,
            choices=chosen,
            profiles_map=profiles_map,
            scope=scope,
            user_home=user_home,
        )
        for line in render_install_confirmation(confirmation):
            write(line)
        if not _prompt_install_confirmation(read):
            return _cancel(write)
    outcome = _dispatch_result(request)
    code = _render_result(outcome, write)
    if code != 0 or confirmation is None:
        return code
    return _run_post_install_setup(
        confirmation.setup_queue,
        request,
        scope_root=confirmation.destination_root,
        read=read,
        write=write,
    )


@dataclass(frozen=True, slots=True)
class _UserWizardReadModel:
    catalog: Catalog
    manifest: Optional[Manifest]
    choices: Tuple[_Choice, ...]
    profiles_map: Mapping[str, Profile]
    source_label: str = ""
    source_root: str = ""


def _basket_key(choice: _Choice) -> str:
    return (
        f"{choice.type}/{choice.name}"
        if choice.kind == "artifact" and choice.type is not None
        else f"{choice.kind}/{choice.name}"
    )


def _basket_item(choice: _Choice) -> BasketItem:
    return BasketItem(
        "bundle" if choice.kind == "bundle" else "artifact",
        _basket_key(choice),
        choice.label,
        choice.description,
    )


def _user_review_lines(
    session: WizardSession,
    read_model: Optional[_UserWizardReadModel],
    *,
    project: Optional[str],
    user_home: Optional[str],
) -> Tuple[str, ...]:
    """Project complete non-Install Review facts without performing effects."""
    scope_root = os.path.abspath(
        user_home or os.path.expanduser("~") if session.scope == "user" else project or "."
    )
    lines: Tuple[str, ...] = (
        "Review action",
        "  Role: User",
        f"  Action: {(session.action or 'status').title()}",
        f"  Harnesses: {_profiles_label(session.profiles)}",
        f"  Scope: {session.scope.title()} — {scope_root}",
    )
    if read_model is not None and read_model.source_label:
        lines += (f"  Catalog source: {read_model.source_label}",)

    entries: Tuple[ManifestEntry, ...] = ()
    if read_model is not None and read_model.manifest is not None:
        selected_artifacts = {
            item.key.split("/", 1)[1]
            for item in session.basket
            if item.kind == "artifact" and "/" in item.key
        }
        selected_bundles = {
            item.key.split("/", 1)[1]
            for item in session.basket
            if item.kind == "bundle" and "/" in item.key
        }
        entries = tuple(
            entry
            for entry in read_model.manifest.installed
            if entry.profile in session.profiles
            and (entry.artifact in selected_artifacts or entry.bundle in selected_bundles)
        )
        subscriptions = tuple(
            dict.fromkeys(
                (
                    f"{entry.subscription.kind}:{entry.subscription.location}"
                    + (f"@{entry.subscription.ref}" if entry.subscription.ref else "")
                )
                for entry in entries
                if entry.subscription is not None
            )
        )
        for subscription in subscriptions:
            lines += (f"  Recorded subscription: {subscription}",)

    lines += (f"  Selected count: {len(session.basket)}",)
    for item in session.basket:
        description = f" — {item.description}" if item.description else ""
        lines += (f"  Selected: {item.label}{description}",)

    destinations: List[str] = []
    for entry in entries:
        destinations.extend(entry.files)
        if entry.merge is not None:
            destinations.append(entry.merge.file)
        destinations.extend(link.path for link in entry.install.links)
    for destination in dict.fromkeys(destinations):
        resolved = (
            destination
            if os.path.isabs(destination)
            else os.path.abspath(os.path.join(scope_root, destination))
        )
        lines += (f"  Resolved destination: {resolved}",)
    if session.action == "status":
        lines += ("  Expected mutation: none; Status is read-only.",)
    else:
        lines += (f"  Expected mutation: {session.action} only the selected managed artifacts.",)
    return lines


def _write_wizard_header(session: WizardSession, write: WriteFn) -> None:
    width = shutil.get_terminal_size(fallback=(100, 24)).columns
    for line in render_header(session, width=max(width, 1), frontend="text"):
        write(line)


def _prompt_wizard_indices(
    read: ReadFn,
    write: WriteFn,
    prompt: str,
    choices: Sequence[_Choice],
    *,
    selected: Sequence[int] = (),
) -> WizardInput:
    selected_tuple = tuple(dict.fromkeys(selected))
    while True:
        line = _read_line(read, prompt)
        if line is None:
            return WizardInput("quit")
        answer = line.strip()
        low = answer.lower()
        if low in ("q", "quit"):
            return WizardInput("quit")
        if low in ("b", "back"):
            return WizardInput("back")
        if not answer and selected_tuple:
            return WizardInput("confirm", selected_tuple)
        if answer.startswith("?"):
            number = answer[1:].strip()
            if number.isdigit() and 1 <= int(number) <= len(choices):
                choice = choices[int(number) - 1]
                identity = _choice_label(choice.kind, choice.name, choice.type, "")
                write(f"{identity}: {choice.description or 'No catalog description is available.'}")
                continue
            write(f"Enter ?N with a number between 1 and {len(choices)}.")
            continue
        parsed = _parse_indices(answer, len(choices))
        if parsed:
            disabled = tuple(choices[index] for index in parsed if not choices[index].enabled)
            if disabled:
                for choice in disabled:
                    write(f"{choice.name}: {choice.reason or 'this item is unavailable'}.")
                continue
            return WizardInput("confirm", parsed)
        write(
            f"Please enter number(s) between 1 and {len(choices)}, 'b' to go back, or 'q' to quit."
        )


def _prompt_wizard_action(read: ReadFn, write: WriteFn) -> WizardInput | str:
    while True:
        line = _read_line(read, "Action (b=back, q=quit): ")
        if line is None:
            return WizardInput("quit")
        answer = line.strip().lower()
        if answer in ("q", "quit"):
            return WizardInput("quit")
        if answer in ("b", "back"):
            return WizardInput("back")
        if answer in ACTIONS:
            return answer
        if answer.isdigit() and 1 <= int(answer) <= len(ACTIONS):
            return ACTIONS[int(answer) - 1]
        write(f"Please enter 1-{len(ACTIONS)}, an action name, 'b', or 'q'.")


def _prompt_wizard_scope(read: ReadFn, write: WriteFn) -> WizardInput | InstallScope:
    while True:
        line = _read_line(read, "Installation scope [1] (b=back, q=quit): ")
        if line is None:
            return WizardInput("quit")
        answer = line.strip().lower()
        if answer in ("q", "quit"):
            return WizardInput("quit")
        if answer in ("b", "back"):
            return WizardInput("back")
        if answer in ("", "1", "project"):
            return "project"
        if answer in ("2", "user", "global"):
            return "user"
        write("Please enter 1 (Project), 2 (User), 'b' to go back, or 'q' to quit.")


def _load_user_wizard_read_model(
    session: WizardSession,
    *,
    source_factory: SourceFactory,
    source_dir: Optional[str],
    repo: Optional[str],
    project: Optional[str],
    user_home: Optional[str],
) -> _UserWizardReadModel | Err:
    assert session.action is not None
    base_profiles = load_profiles(project)
    resolved_home = os.path.abspath(user_home or os.path.expanduser("~"))
    scope = session.scope
    profiles_map: Mapping[str, Profile] = (
        base_profiles
        if scope == "project"
        else {
            name: profile_for_scope(profile, "user", resolved_home)
            for name, profile in base_profiles.items()
        }
    )
    request_project = project if scope == "project" else None
    catalog = Catalog(artifacts={}, bundles={})
    source_label = ""
    source_root = ""
    if session.action in ("install", "update"):
        source_result = source_factory(
            Request(
                command=session.action,
                source_dir=source_dir,
                repo=repo,
                project=request_project,
                scope=scope,  # type: ignore[arg-type]
                user_home=user_home,
            )
        )
        if isinstance(source_result, Err):
            return source_result
        source = source_result.value
        catalog_result = source.catalog()
        if isinstance(catalog_result, Err):
            return catalog_result
        catalog = catalog_result.value
        source_label = source.label()
        source_root = getattr(source, "root", source_label.removeprefix("local:"))
        if (
            session.action == "install"
            and session.install_mode == "symlink"
            and not source_label.startswith("local:")
        ):
            return Err(
                "Symlink requires a durable local catalog; choose one with "
                "aart install ... --source DIR --link",
                code=2,
            )
    elif session.action == "uninstall":
        source_result = source_factory(
            Request(
                command="uninstall",
                source_dir=source_dir,
                repo=repo,
                project=request_project,
                scope=scope,  # type: ignore[arg-type]
                user_home=user_home,
            )
        )
        if not isinstance(source_result, Err):
            catalog_result = source_result.value.catalog()
            if not isinstance(catalog_result, Err):
                catalog = catalog_result.value
                source_label = source_result.value.label()
                source_root = source_result.value.root

    manifest: Optional[Manifest] = None
    if session.action in ("update", "uninstall"):
        manifest_result = _load_manifest_for_action(
            session.action,
            source_dir=source_dir,
            repo=repo,
            project=request_project,
            scope=scope,  # type: ignore[arg-type]
            user_home=user_home,
        )
        if isinstance(manifest_result, Err):
            return manifest_result
        manifest = manifest_result.value
    choices = build_action_choices(
        session.action,
        catalog,
        manifest,
        session.profiles,
        profiles_map,
        install_mode=session.install_mode,  # type: ignore[arg-type]
        scope=scope,  # type: ignore[arg-type]
    )
    return _UserWizardReadModel(
        catalog,
        manifest,
        choices,
        profiles_map,
        source_label,
        source_root,
    )


def _confirm_wizard_quit(session: WizardSession, read: ReadFn, write: WriteFn) -> bool:
    if request_quit(session) == "quit":
        return True
    write(f"Discard {len(session.basket)} selected basket item(s)?")
    line = _read_line(read, f"Discard {len(session.basket)} selected basket item(s)? [y/N]: ")
    if line is None:
        write("Input ended; the basket was discarded and no changes were made.")
        return True
    if line.strip().lower() in ("y", "yes"):
        return True
    write("Returning to the wizard; no changes were made.")
    return False


def _run_user_text_wizard(
    session: WizardSession,
    read: ReadFn,
    write: WriteFn,
    *,
    source_factory: SourceFactory,
    source_dir: Optional[str],
    repo: Optional[str],
    project: Optional[str],
    user_home: Optional[str],
) -> int | WizardSession:
    read_model: Optional[_UserWizardReadModel] = None
    read_key: Optional[tuple] = None
    profile_names = tuple(sorted(load_profiles(project)))
    while True:
        if session.current in ("role", "maintainer_action"):
            return session
        _write_wizard_header(session, write)
        if session.current == "profiles":
            write("Select profile(s):")
            choices = tuple(_Choice("profile", name, None, name) for name in profile_names)
            for index, choice in enumerate(choices, start=1):
                write(f"  {index:>2}. {choice.label}")
            selected = tuple(
                index for index, name in enumerate(profile_names) if name in session.profiles
            )
            write(f"Selected: {len(selected)} profile(s)")
            event = _prompt_wizard_indices(
                read,
                write,
                "Profile(s) (b=back, q=quit): ",
                choices,
                selected=selected,
            )
            if event.kind == "back":
                session = wizard_back(session)
                continue
            if event.kind == "quit":
                if _confirm_wizard_quit(session, read, write):
                    return _cancel(write)
                continue
            session = wizard_select(
                session, "profiles", tuple(profile_names[index] for index in event.selected)
            )
            session = wizard_advance(session)
            continue
        if session.current == "action":
            write("Action:")
            for index, action in enumerate(ACTIONS, start=1):
                write(f"  {index:>2}. {action}")
            selected_action = _prompt_wizard_action(read, write)
            if isinstance(selected_action, WizardInput):
                if selected_action.kind == "back":
                    session = wizard_back(session)
                elif _confirm_wizard_quit(session, read, write):
                    return _cancel(write)
                continue
            session = wizard_select(session, "action", selected_action)
            if selected_action == "status" and session.basket:
                session = reconcile_basket(
                    session,
                    {item.key: "not applicable to the Status action" for item in session.basket},
                )
            session = wizard_advance(session)
            read_model = None
            continue
        if session.current == "scope":
            write("Installation scope:")
            for index, scope_choice in enumerate(INSTALL_SCOPE_CHOICES, start=1):
                write(f"  {index:>2}. {scope_choice.label:<23} {scope_choice.description}")
            selected_scope = _prompt_wizard_scope(read, write)
            if isinstance(selected_scope, WizardInput):
                if selected_scope.kind == "back":
                    session = wizard_back(session)
                elif _confirm_wizard_quit(session, read, write):
                    return _cancel(write)
                continue
            session = wizard_select(session, "scope", selected_scope)
            session = wizard_advance(session)
            read_model = None
            continue
        if session.current == "mode":
            selected_mode = _prompt_install_mode(read, write)
            if selected_mode is None:
                if _confirm_wizard_quit(session, read, write):
                    return _cancel(write)
                continue
            if selected_mode == "back":
                session = wizard_back(session)
                continue
            session = wizard_select(session, "mode", selected_mode)
            session = wizard_advance(session)
            read_model = None
            continue
        if session.current == "artifacts":
            key = (
                session.action,
                session.profiles,
                session.scope,
                session.install_mode,
            )
            if read_model is None or read_key != key:
                loaded = _load_user_wizard_read_model(
                    session,
                    source_factory=source_factory,
                    source_dir=source_dir,
                    repo=repo,
                    project=project,
                    user_home=user_home,
                )
                if isinstance(loaded, Err):
                    write(f"error: {loaded.reason}")
                    return loaded.code
                read_model = loaded
                read_key = key
            if not read_model.choices:
                write(_empty_choices_message(session.action or "", session.profiles))
                return _render_result(
                    CommandOutcome(0, ActionSummary(action=session.action or "selection")), write
                )
            availability = {
                _basket_key(choice): "" if choice.enabled else choice.reason
                for choice in read_model.choices
            }
            session = reconcile_basket(session, availability)
            write(f"Select artifact(s)/bundle(s) for {_profiles_label(session.profiles)}:")
            width = shutil.get_terminal_size(fallback=(200, 24)).columns
            for index, choice in enumerate(read_model.choices, start=1):
                write(_text_choice_line(index, choice, width))
            write("Enter ?N for details; blank keeps the current basket.")
            selected = tuple(
                index
                for index, choice in enumerate(read_model.choices)
                if _basket_key(choice) in {item.key for item in session.basket}
            )
            write(f"Selected: {len(selected)} basket item(s)")
            event = _prompt_wizard_indices(
                read,
                write,
                "Selection (b=back, q=quit): ",
                read_model.choices,
                selected=selected,
            )
            if event.kind == "back":
                session = wizard_back(session)
                continue
            if event.kind == "quit":
                if _confirm_wizard_quit(session, read, write):
                    return _cancel(write)
                continue
            if not event.selected:
                write("Select at least one artifact or bundle before continuing.")
                continue
            session = wizard_select(
                session,
                "artifacts",
                tuple(_basket_item(read_model.choices[index]) for index in event.selected),
            )
            session = wizard_advance(session)
            continue
        if session.current == "review":
            chosen: Tuple[_Choice, ...] = ()
            if read_model is not None:
                by_key = {_basket_key(choice): choice for choice in read_model.choices}
                chosen = tuple(by_key[item.key] for item in session.basket if item.key in by_key)
            request = _build_request(
                session.action or "status",
                chosen,
                session.profiles,
                source_dir=source_dir,
                repo=repo,
                project=project,
                install_mode=session.install_mode,  # type: ignore[arg-type]
                scope=session.scope,  # type: ignore[arg-type]
                user_home=user_home,
            )
            confirmation: Optional[InstallConfirmation] = None
            if session.action == "install":
                assert read_model is not None
                confirmation = build_install_confirmation(
                    source_label=read_model.source_label,
                    source_root=read_model.source_root,
                    project=project,
                    profiles=session.profiles,
                    requested_mode=session.install_mode,  # type: ignore[arg-type]
                    catalog=read_model.catalog,
                    choices=chosen,
                    profiles_map=read_model.profiles_map,
                    scope=session.scope,  # type: ignore[arg-type]
                    user_home=user_home,
                )
                for line in render_install_confirmation(confirmation):
                    write(line)
            else:
                for line in _user_review_lines(
                    session, read_model, project=project, user_home=user_home
                ):
                    write(line)
            write("Finalize applies this reviewed action; Back edits without changes.")
            review_answer = _read_line(read, "Finalize? [y/N] (b=back, q=quit): ")
            answer = "q" if review_answer is None else review_answer.strip().lower()
            if answer in ("b", "back"):
                session = wizard_back(session)
                continue
            if answer in ("q", "quit"):
                if _confirm_wizard_quit(session, read, write):
                    return _cancel(write)
                continue
            if answer not in ("y", "yes", "f", "finalize"):
                write("Review not finalized; no changes were made.")
                continue
            if not can_finalize(session, revision=session.revision):
                write("Wizard state changed; review it again before Finalize.")
                continue
            outcome = _dispatch_result(request)
            code = _render_result(outcome, write)
            if code != 0 or confirmation is None:
                return code
            return _run_post_install_setup(
                confirmation.setup_queue,
                request,
                scope_root=confirmation.destination_root,
                read=read,
                write=write,
            )


def _run_text(
    read: ReadFn = input,
    write: WriteFn = print,
    *,
    source_factory: SourceFactory = open_source,
    source_dir: Optional[str] = None,
    repo: Optional[str] = None,
    project: Optional[str] = None,
    user_home: Optional[str] = None,
) -> int:
    """Persistent onboarding/role wizard shared by the fallback and headless tests."""

    session = initial_session()
    buffered_role: Optional[str] = None
    while True:
        if session.current == "onboarding":
            for line in onboarding_lines("text"):
                write(line)
            _write_wizard_header(session, write)
            onboarding_answer = _read_line(read, "Press Enter to start (q=quit): ")
            if onboarding_answer is None or onboarding_answer.strip().lower() in ("q", "quit"):
                return _cancel(write)
            buffered_role = onboarding_answer if onboarding_answer.strip() else None
            session = wizard_advance(session)
            continue
        if session.current == "role":
            _write_wizard_header(session, write)
            role = _prompt_role(read, write, initial_answer=buffered_role)
            buffered_role = None
            if role is None:
                return _cancel(write)
            if role == "back":
                session = wizard_back(session)
                continue
            session = wizard_select(session, "role", role)
            session = wizard_advance(session)
            if role == "user":
                result = _run_user_text_wizard(
                    session,
                    read,
                    write,
                    source_factory=source_factory,
                    source_dir=source_dir,
                    repo=repo,
                    project=project,
                    user_home=user_home,
                )
                if isinstance(result, WizardSession):
                    session = result
                    continue
                return result
            result = _run_maintainer_text(
                session,
                read,
                write,
                source_factory=source_factory,
                source_dir=source_dir,
                repo=repo,
                project=project,
            )
            if isinstance(result, WizardSession):
                session = result
                continue
            return result


def _prompt_role(
    read: ReadFn, write: WriteFn, *, initial_answer: Optional[str] = None
) -> Optional[str]:
    write("Choose how you want to use aart:")
    for index, role in enumerate(ROLES, start=1):
        write(f"  {index:>2}. {role.label:<10} {role.description}")
    while True:
        line = initial_answer
        initial_answer = None
        if line is None:
            line = _read_line(read, "Role (1=User, 2=Maintainer, b=back, q=quit): ")
        if line is None:
            return None
        answer = line.strip().lower()
        if answer in ("", "q"):
            return None
        if answer in ("b", "back"):
            return "back"
        if answer in ("1", "user"):
            return "user"
        if answer in ("2", "maintainer"):
            return "maintainer"
        write("Please enter 1 (User), 2 (Maintainer), or 'q' to quit.")


def _run_maintainer_text(
    session: WizardSession,
    read: ReadFn,
    write: WriteFn,
    *,
    source_factory: SourceFactory,
    source_dir: Optional[str],
    repo: Optional[str],
    project: Optional[str],
) -> int | WizardSession:
    """Drive Maintainer stages and expose apply only at the Review Finalize boundary."""
    del source_factory  # maintainer source resolution belongs to the upstream command core
    from .commands import upstream

    catalog_root = os.path.abspath(source_dir or ".")
    context_request = Request(
        command="upstream",
        upstream_action="validate",
        source_dir=catalog_root,
        repo=repo,
    )
    context_result = upstream.load_maintainer_context(context_request)
    if isinstance(context_result, Err):
        write(f"error: {context_result.reason}")
        return getattr(context_result, "code", 1)
    context = context_result.value

    request: Optional[Request] = None
    previewed: Optional[Request] = None
    while True:
        if session.current == "role":
            return session
        _write_wizard_header(session, write)
        if session.current == "maintainer_action":
            write(f"Catalog: {context.root}")
            write("Maintainer action:")
            for index, (_action, label) in enumerate(MAINTAINER_ACTIONS, start=1):
                write(f"  {index:>2}. {label}")
            selected = _prompt_maintainer_action_wizard(read, write)
            if isinstance(selected, WizardInput):
                if selected.kind == "back":
                    return wizard_back(session)
                return _cancel(write)
            session = replace(session, basket=(), notices=())
            session = wizard_select(session, "maintainer_action", selected)
            session = wizard_advance(session)
            request = None
            previewed = None
            if selected == "user":
                result = _run_user_text_wizard(
                    session,
                    read,
                    write,
                    source_factory=open_source,
                    source_dir=source_dir,
                    repo=repo,
                    project=project,
                    user_home=None,
                )
                if isinstance(result, WizardSession):
                    session = result
                    continue
                return result
            continue

        action = session.maintainer_action
        assert action is not None
        if session.current == "upstream_details":
            if action == "add":
                add_prompted = _prompt_upstream_add_wizard(
                    read, write, context.root, existing=request
                )
                if isinstance(add_prompted, WizardInput):
                    if add_prompted.kind == "back":
                        session = wizard_back(session)
                        continue
                    if _confirm_wizard_quit(session, read, write):
                        return _cancel(write)
                    continue
                request = add_prompted
                session = wizard_select(
                    session,
                    "artifacts",
                    (BasketItem("upstream", request.names[0], request.names[0]),),
                )
                session = wizard_advance(session)
                previewed = None
                continue
            if action == "import":
                import_request, code = _prompt_upstream_import(read, write, context.root)
                if import_request is None:
                    if code:
                        return code
                    if _confirm_wizard_quit(session, read, write):
                        return _cancel(write)
                    continue
                request = import_request
                session = wizard_select(
                    session,
                    "artifacts",
                    tuple(BasketItem("upstream", name, name) for name in request.names),
                )
                session = wizard_advance(wizard_advance(session))
                previewed = None
                continue

        if session.current == "artifacts":
            if action in ("check", "update"):
                tracked_prompted = _prompt_tracked_upstreams_wizard(
                    read, write, context, existing=request
                )
                if isinstance(tracked_prompted, WizardInput):
                    if tracked_prompted.kind == "back":
                        session = wizard_back(session)
                        continue
                    if _confirm_wizard_quit(session, read, write):
                        return _cancel(write)
                    continue
                names, all_selected = tracked_prompted
                request = Request(
                    command="upstream",
                    upstream_action=action,
                    names=names,
                    all=all_selected,
                    source_dir=context.root,
                )
                basket_names = names or (("all tracked upstreams",) if all_selected else ())
                session = wizard_select(
                    session,
                    "artifacts",
                    tuple(BasketItem("upstream", name, name) for name in basket_names),
                )
                session = wizard_advance(session)
                previewed = None
                continue
            if action == "import":
                write("Selected import candidates:")
                for item in session.basket:
                    write(f"  - {item.label}")
                line = _read_line(read, "Enter=continue, b=back, q=quit: ")
                answer = "q" if line is None else line.strip().lower()
                if answer in ("b", "back"):
                    session = wizard_back(session)
                    continue
                if answer in ("q", "quit"):
                    if _confirm_wizard_quit(session, read, write):
                        return _cancel(write)
                    continue
                session = wizard_advance(session)
                continue

        if session.current != "review":
            return 2
        if request is None:
            request = Request(
                command="upstream",
                upstream_action=action,
                source_dir=context.root,
            )
        is_mutation = action in ("add", "import", "update")
        if is_mutation and previewed != request:
            preview_code = _preview_maintainer_mutation(request, write)
            if preview_code:
                return preview_code
            previewed = request
        write("Review maintainer action")
        write(f"  Catalog: {context.root}")
        write(f"  Action: {action}")
        if request.names:
            write(f"  Selected: {', '.join(request.names)}")
        if request.all:
            write("  Selected: all tracked upstreams")
        if request.url:
            write(f"  URL: {request.url}")
        if is_mutation:
            write("  Preview succeeded; Finalize applies the reviewed catalog changes.")
        else:
            write("  Finalize runs the reviewed read-only command.")
        line = _read_line(read, "Finalize? [y/N] (b=back, q=quit): ")
        answer = "q" if line is None else line.strip().lower()
        if answer in ("b", "back"):
            session = wizard_back(session)
            continue
        if answer in ("q", "quit"):
            if _confirm_wizard_quit(session, read, write):
                return _cancel(write)
            continue
        if answer not in ("y", "yes", "f", "finalize"):
            write("Review not finalized; no changes were made.")
            continue
        if not can_finalize(session, revision=session.revision):
            write("Wizard state changed; review it again before Finalize.")
            continue
        if is_mutation:
            return _apply_maintainer_mutation(request, write)
        return _dispatch(request)


def _prompt_maintainer_action_wizard(read: ReadFn, write: WriteFn) -> str | WizardInput:
    while True:
        line = _read_line(read, "Maintainer action (b=back, q=quit): ")
        if line is None:
            return WizardInput("quit")
        answer = line.strip().lower()
        if answer in ("q", "quit"):
            return WizardInput("quit")
        if answer in ("b", "back"):
            return WizardInput("back")
        by_name = {name: name for name, _label in MAINTAINER_ACTIONS}
        if answer in by_name:
            return by_name[answer]
        if answer.isdigit() and 1 <= int(answer) <= len(MAINTAINER_ACTIONS):
            return MAINTAINER_ACTIONS[int(answer) - 1][0]
        write(f"Please enter 1-{len(MAINTAINER_ACTIONS)}, 'b', or 'q'.")


def _prompt_wizard_value(
    read: ReadFn,
    write: WriteFn,
    prompt: str,
    *,
    current: Optional[str] = None,
    required: bool,
) -> str | None | WizardInput:
    while True:
        line = _read_line(read, prompt)
        if line is None:
            return WizardInput("quit")
        answer = line.strip()
        lower = answer.lower()
        if lower in ("q", "quit"):
            return WizardInput("quit")
        if lower in ("b", "back"):
            return WizardInput("back")
        if answer:
            return answer
        if current is not None:
            return current
        if not required:
            return None
        write("A value is required (or enter 'b' to go back, 'q' to quit).")


def _prompt_upstream_add_wizard(
    read: ReadFn,
    write: WriteFn,
    catalog_root: str,
    *,
    existing: Optional[Request] = None,
) -> Request | WizardInput:
    key = _prompt_wizard_value(
        read,
        write,
        "Artifact key (TYPE/NAME): ",
        current=existing.names[0] if existing and existing.names else None,
        required=True,
    )
    if isinstance(key, WizardInput):
        return key
    url = _prompt_wizard_value(
        read,
        write,
        "GitHub URL: ",
        current=existing.url if existing else None,
        required=True,
    )
    if isinstance(url, WizardInput):
        return url
    ref = _prompt_wizard_value(
        read,
        write,
        "Ref override (blank to infer): ",
        current=existing.ref if existing else None,
        required=False,
    )
    if isinstance(ref, WizardInput):
        return ref
    path = _prompt_wizard_value(
        read,
        write,
        "Path override (blank to infer): ",
        current=existing.path if existing else None,
        required=False,
    )
    if isinstance(path, WizardInput):
        return path
    assert isinstance(key, str)
    assert isinstance(url, str)
    return Request(
        command="upstream",
        upstream_action="add",
        names=(key,),
        url=url,
        ref=ref,
        path=path,
        source_dir=catalog_root,
    )


def _prompt_required(read: ReadFn, write: WriteFn, prompt: str) -> Optional[str]:
    while True:
        line = _read_line(read, prompt)
        if line is None:
            return None
        answer = line.strip()
        if answer.lower() == "q":
            return None
        if answer:
            return answer
        write("A value is required (or enter 'q' to cancel).")


def _prompt_optional(read: ReadFn, prompt: str) -> Optional[str]:
    line = _read_line(read, prompt)
    if line is None:
        return None
    answer = line.strip()
    return answer or None


def _prompt_upstream_import(
    read: ReadFn, write: WriteFn, catalog_root: str
) -> Tuple[Optional[Request], int]:
    from .commands import upstream
    from .import_candidates import candidate_label

    url = _prompt_required(read, write, "GitHub repository/tree URL: ")
    if url is None:
        return None, 0
    scan_request = Request(
        command="upstream",
        upstream_action="scan",
        url=url,
        import_mode="auto",
        source_dir=catalog_root,
    )
    scan_result = upstream.scan_import_candidates(scan_request)
    if isinstance(scan_result, Err):
        write(f"error: {scan_result.reason}")
        return None, getattr(scan_result, "code", 1)
    candidates = scan_result.value.candidates
    if not candidates:
        write("No importable artifacts detected.")
        return None, 0
    choices = tuple(
        _Choice(
            "artifact",
            candidate_label(candidate),
            candidate.key.type,
            f"{candidate_label(candidate)} [{candidate.confidence}] {candidate.source.path}",
        )
        for candidate in candidates
    )
    write("Detected artifacts:")
    for index, choice in enumerate(choices, start=1):
        write(f"  {index:>2}. {choice.label}")
    picked = _prompt_indices(read, write, "Import selection: ", choices)
    if not picked:
        return None, 0
    bundle = _prompt_optional(read, "Bundle name (blank for none): ")
    bundle_description = None
    if bundle is not None:
        bundle_description = _prompt_optional(read, "Bundle description (blank for default): ")
    return (
        replace(
            scan_request,
            upstream_action="import",
            names=tuple(choices[index].name for index in picked),
            bundles=(bundle,) if bundle else (),
            bundle_description=bundle_description,
            bundle_mode="append",
        ),
        0,
    )


def _prompt_tracked_upstreams_wizard(
    read: ReadFn,
    write: WriteFn,
    context,
    *,
    existing: Optional[Request] = None,
) -> Tuple[Tuple[str, ...], bool] | WizardInput:
    from .upstreams import format_upstream_key

    labels = tuple(
        format_upstream_key(key)
        for key in sorted(context.upstreams.entries, key=format_upstream_key)
    )
    if not labels:
        write(f"No tracked upstreams in {context.root}.")
        return WizardInput("quit")
    write("Tracked upstreams:")
    for index, label in enumerate(labels, start=1):
        marker = "x" if existing and (existing.all or label in existing.names) else " "
        write(f"  {index:>2}. [{marker}] {label}")
    while True:
        line = _read_line(read, "Selection (numbers, 'a'=all, b=back, q=quit): ")
        if line is None:
            return WizardInput("quit")
        answer = line.strip().lower()
        if answer in ("q", "quit"):
            return WizardInput("quit")
        if answer in ("b", "back"):
            return WizardInput("back")
        if answer == "" and existing is not None:
            return existing.names, existing.all
        if answer in ("a", "all"):
            return (), True
        picked = _parse_indices(answer, len(labels))
        if picked:
            return tuple(labels[index] for index in picked), False
        write(f"Please enter number(s) between 1 and {len(labels)}, 'a', 'b', or 'q'.")


def _run_maintainer_mutation(
    request: Request,
    read: ReadFn,
    write: WriteFn,
    *,
    dispatch: Optional[DispatchFn] = None,
) -> int:
    """Validate -> preview -> confirm -> apply -> validate, with no hidden mutation."""
    dispatch_fn = dispatch or _dispatch
    preview = _preview_maintainer_mutation(request, write, dispatch=dispatch_fn)
    if preview != 0:
        return preview

    answer = _read_line(read, "Apply these catalog changes? [y/N]: ")
    if answer is None or answer.strip().lower() not in ("y", "yes"):
        write("Cancelled; no catalog changes were applied.")
        return 0
    return _apply_maintainer_mutation(request, write, dispatch=dispatch_fn)


def _preview_maintainer_mutation(
    request: Request,
    write: WriteFn,
    *,
    dispatch: Optional[DispatchFn] = None,
) -> int:
    """Run the non-mutating validation and dry-run half of a maintainer change."""
    dispatch_fn = dispatch or _dispatch
    validation = Request(
        command="upstream",
        upstream_action="validate",
        source_dir=request.source_dir,
    )
    before = dispatch_fn(validation)
    if before != 0:
        write(f"Catalog validation failed before mutation: {request.source_dir}")
        return before

    preview = dispatch_fn(replace(request, dry_run=True))
    if preview != 0:
        write("Preview failed; no catalog changes were applied.")
        return preview
    write("Preview succeeded; no catalog changes have been applied yet.")
    return 0


def _apply_maintainer_mutation(
    request: Request,
    write: WriteFn,
    *,
    dispatch: Optional[DispatchFn] = None,
) -> int:
    """Apply an already-previewed maintainer request and validate the result."""
    dispatch_fn = dispatch or _dispatch
    applied = dispatch_fn(replace(request, dry_run=False))
    if applied != 0:
        return applied
    validation = Request(
        command="upstream",
        upstream_action="validate",
        source_dir=request.source_dir,
    )
    after = dispatch_fn(validation)
    if after != 0:
        write(f"Catalog validation failed after mutation: {request.source_dir}")
        return after
    write(
        f"Next: review the working-tree diff in {request.source_dir} and run "
        f"`aart upstream validate --source {request.source_dir}`."
    )
    return 0


def _load_manifest_for_action(
    action: str,
    *,
    source_dir: Optional[str],
    repo: Optional[str],
    project: Optional[str],
    scope: InstallScope = "project",
    user_home: Optional[str] = None,
) -> Result:
    """Load the consumer manifest for update/uninstall choice building."""
    from .commands import _common

    return _common.load_manifest(
        Request(
            command=action,
            source_dir=source_dir,
            repo=repo,
            project=project if scope == "project" else None,
            scope=scope,
            user_home=user_home,
        )
    )


def _profiles_label(profile_names: Sequence[str]) -> str:
    return ", ".join(profile_names)


def _empty_choices_message(action: str, profile_names: Sequence[str]) -> str:
    profiles = _profiles_label(profile_names)
    if action == "install":
        return f"No installable artifacts or bundles for profile(s): {profiles}."
    if action == "update":
        return f"No installed artifacts to update for profile(s): {profiles}."
    if action == "uninstall":
        return f"No installed artifacts to uninstall for profile(s): {profiles}."
    return f"No choices for profile(s): {profiles}."


def _read_line(read: ReadFn, prompt: str) -> Optional[str]:
    """Read one line; map EOF (``input`` raising ``EOFError``) to ``None`` (= quit)."""
    try:
        return read(prompt)
    except EOFError:
        return None


def _prompt_indices(
    read: ReadFn, write: WriteFn, prompt: str, choices: Sequence[_Choice]
) -> Tuple[int, ...]:
    """Prompt for a comma/space-separated 1-based selection; return 0-based indices.

    Blank or ``q`` -> empty tuple (quit). Out-of-range / non-numeric tokens re-prompt with a
    short message rather than crashing. Duplicates are de-duplicated, original order kept.
    """
    while True:
        line = _read_line(read, prompt)
        if line is None:
            return ()
        line = line.strip()
        if line == "" or line.lower() == "q":
            return ()
        if line.startswith("?"):
            number = line[1:].strip()
            if number.isdigit() and 1 <= int(number) <= len(choices):
                choice = choices[int(number) - 1]
                identity = _choice_label(choice.kind, choice.name, choice.type, "")
                detail = choice.description or "No catalog description is available."
                write(f"{identity}: {detail}")
                continue
            write(f"Enter ?N with a number between 1 and {len(choices)}.")
            continue
        parsed = _parse_indices(line, len(choices))
        if parsed:
            disabled = tuple(choices[index] for index in parsed if not choices[index].enabled)
            if disabled:
                for choice in disabled:
                    reason = choice.reason or "this item is unavailable"
                    write(f"{choice.name}: {reason}.")
                continue
            return parsed
        write(f"Please enter number(s) between 1 and {len(choices)} (or 'q' to quit).")


def _parse_indices(line: str, choice_count: int) -> Tuple[int, ...]:
    """Pure 1-based comma/space selection parser used by both text menus."""
    tokens = [token for token in line.replace(",", " ").split() if token]
    out: List[int] = []
    seen = set()
    for token in tokens:
        if not token.isdigit():
            return ()
        number = int(token)
        if not (1 <= number <= choice_count):
            return ()
        index = number - 1
        if index not in seen:
            seen.add(index)
            out.append(index)
    return tuple(out)


def _text_choice_line(index: int, choice: _Choice, width: int) -> str:
    """Render one numbered text-frontend row within the terminal width."""
    prefix = f"  {index:>2}. "
    if width <= len(prefix):
        return _ellipsize(prefix, width)
    return prefix + _ellipsize(choice.label, max(width - len(prefix), 0))


def _prompt_install_scope(read: ReadFn, write: WriteFn) -> Optional[InstallScope]:
    """Select the state/destination boundary; blank keeps the project default."""

    write("Installation scope:")
    for index, choice in enumerate(INSTALL_SCOPE_CHOICES, start=1):
        write(f"  {index:>2}. {choice.label:<23} {choice.description}")
    while True:
        line = _read_line(read, "Installation scope [1] (q=quit): ")
        if line is None:
            return None
        answer = line.strip().lower()
        if answer in ("q", "quit"):
            return None
        if answer in ("", "1", "project"):
            return "project"
        if answer in ("2", "user", "global"):
            return "user"
        write("Please enter 1 (Project), 2 (User), or 'q' to quit.")


def _prompt_install_mode(
    read: ReadFn,
    write: WriteFn,
) -> Optional[Literal["copy", "symlink", "back"]]:
    """Select the Install-only mode; blank is Copy and back returns to Action."""

    write("Installation mode:")
    for index, choice in enumerate(INSTALL_MODE_CHOICES, start=1):
        write(f"  {index:>2}. {choice.label:<20} {choice.description}")
    while True:
        line = _read_line(read, "Installation mode [1] (b=back, q=quit): ")
        if line is None:
            return None
        answer = line.strip().lower()
        if answer in ("q", "quit"):
            return None
        if answer in ("b", "back"):
            return "back"
        if answer in ("", "1", "copy"):
            return "copy"
        if answer in ("2", "symlink", "link"):
            return "symlink"
        write("Please enter 1 (Copy), 2 (Symlink), 'b' to go back, or 'q' to quit.")


def _prompt_install_confirmation(read: ReadFn) -> bool:
    """Return true only for an explicit affirmative Install confirmation."""

    line = _read_line(read, "Proceed with installation? [y/N]: ")
    return line is not None and line.strip().lower() in ("y", "yes")


def _prompt_action(read: ReadFn, write: WriteFn) -> Optional[str]:
    """Prompt for one action by number or name. Blank/``q`` -> ``None`` (quit)."""
    while True:
        line = _read_line(read, "Action (e.g. 1): ")
        if line is None:
            return None
        line = line.strip()
        if line == "" or line.lower() == "q":
            return None
        low = line.lower()
        if low in ACTIONS:
            return low
        if line.isdigit():
            n = int(line)
            if 1 <= n <= len(ACTIONS):
                return ACTIONS[n - 1]
        write(f"Please enter 1-{len(ACTIONS)} or one of: {', '.join(ACTIONS)}.")


# --------------------------------------------------------------------------- #
# curses front-end — gather an immutable session, dispatch only after teardown. #
# --------------------------------------------------------------------------- #
def _curses_header(stdscr, session: WizardSession) -> Tuple[str, ...]:
    width = _width(stdscr) if hasattr(stdscr, "getmaxyx") else 80
    return render_header(session, width=max(width - 1, 1), frontend="curses")


def _position(session: WizardSession, stage: str) -> Tuple[int, int]:
    for position in session.positions:
        if position.stage == stage:
            return position.cursor, position.scroll
    return 0, 0


def _curses_single_event(curses, stdscr, title, labels, session: WizardSession) -> WizardInput:
    cursor, scroll = _position(session, session.current)
    try:
        result = _curses_singleselect(
            curses,
            stdscr,
            title,
            labels,
            wizard=True,
            initial_cursor=cursor,
            initial_scroll=scroll,
            header=_curses_header(stdscr, session),
        )
    except TypeError as error:
        if "unexpected keyword argument" not in str(error):
            raise
        result = _curses_singleselect(curses, stdscr, title, labels)
    if isinstance(result, WizardInput):
        return result
    if result is None:
        return WizardInput("quit", cursor=cursor, scroll=scroll)
    selected = int(result)
    return WizardInput("confirm", (selected,), selected, scroll)


def _curses_multi_event(
    curses,
    stdscr,
    title,
    labels,
    session: WizardSession,
    *,
    selected: Sequence[int] = (),
    details: Optional[Sequence[str]] = None,
    disabled: Optional[Sequence[bool]] = None,
) -> WizardInput:
    cursor, scroll = _position(session, session.current)
    try:
        result = _curses_multiselect(
            curses,
            stdscr,
            title,
            labels,
            details=details,
            disabled=disabled,
            wizard=True,
            initial_checked=selected,
            initial_cursor=cursor,
            initial_scroll=scroll,
            header=_curses_header(stdscr, session),
        )
    except TypeError as error:
        if "unexpected keyword argument" not in str(error):
            raise
        result = _curses_multiselect(curses, stdscr, title, labels, details, disabled)
    if isinstance(result, WizardInput):
        return result
    if result is None:
        return WizardInput("quit", cursor=cursor, scroll=scroll)
    picked = tuple(int(index) for index in result)
    return WizardInput("confirm", picked, cursor, scroll)


def _curses_confirm_discard(curses, stdscr, session: WizardSession) -> bool:
    if request_quit(session) == "quit":
        return True
    if not all(hasattr(stdscr, name) for name in ("clear", "addstr", "refresh", "getch")):
        return True
    lines = _curses_header(stdscr, session) + (
        f"Discard {len(session.basket)} selected basket item(s)?",
        "y = discard · n/Backspace = return",
    )
    while True:
        stdscr.clear()
        available = max(_width(stdscr) - 1, 0)
        for row, line in enumerate(lines[: _height(stdscr)]):
            stdscr.addstr(row, 0, _ellipsize(line, available))
        stdscr.refresh()
        key = stdscr.getch()
        if key in (ord("y"), ord("Y")):
            return True
        if key in (
            ord("n"),
            ord("N"),
            getattr(curses, "KEY_BACKSPACE", -1),
            127,
            8,
        ):
            return False


def _curses_review(curses, stdscr, session: WizardSession, lines: Sequence[str]):
    if not all(hasattr(stdscr, name) for name in ("clear", "addstr", "refresh", "getch")):
        return False
    content = _curses_header(stdscr, session) + tuple(lines)
    offset = 0
    while True:
        stdscr.clear()
        available = max(_width(stdscr) - 1, 0)
        height = _height(stdscr)
        body_height = max(height - 1, 1)
        max_offset = max(len(content) - body_height, 0)
        offset = min(offset, max_offset)
        for row, line in enumerate(content[offset : offset + body_height]):
            stdscr.addstr(row, 0, _ellipsize(line, available))
        if height:
            stdscr.addstr(
                height - 1,
                0,
                _ellipsize(
                    "↑/↓ = scroll · Enter/y = Finalize · Backspace = back · q = quit",
                    available,
                ),
            )
        stdscr.refresh()
        key = stdscr.getch()
        if key in (curses.KEY_ENTER, 10, 13, ord("y"), ord("Y")):
            return True
        if key in (getattr(curses, "KEY_BACKSPACE", -1), 127, 8):
            return "back"
        if key in (ord("q"), 27):
            return "quit"
        if key in (ord("n"), ord("N")):
            return False
        if key in (curses.KEY_DOWN, ord("j")) and offset < max_offset:
            offset += 1
        elif key in (curses.KEY_UP, ord("k")) and offset > 0:
            offset -= 1
        elif key == getattr(curses, "KEY_NPAGE", -1) and offset < max_offset:
            offset = min(offset + body_height, max_offset)
        elif key == getattr(curses, "KEY_PPAGE", -1) and offset > 0:
            offset = max(offset - body_height, 0)


def _run_user_curses_wizard(
    curses,
    stdscr,
    session: WizardSession,
    selection: dict,
    *,
    source_dir: Optional[str],
    repo: Optional[str],
    project: Optional[str],
    user_home: Optional[str],
) -> WizardSession:
    profile_names = tuple(sorted(load_profiles(project)))
    read_model: Optional[_UserWizardReadModel] = None
    read_key: Optional[tuple] = None
    while session.current not in ("role", "maintainer_action"):
        if session.current == "profiles":
            selected = tuple(
                index for index, name in enumerate(profile_names) if name in session.profiles
            )
            event = _curses_multi_event(
                curses,
                stdscr,
                "Select profile(s)  (space=toggle, enter=confirm, q=quit)",
                profile_names,
                session,
                selected=selected,
            )
            session = remember_position(
                session, "profiles", cursor=event.cursor, scroll=event.scroll
            )
            if event.kind == "back":
                session = wizard_back(session)
                continue
            if event.kind == "quit":
                if _curses_confirm_discard(curses, stdscr, session):
                    selection["cancelled"] = True
                    return session
                continue
            if not event.selected:
                selection["empty_selection"] = True
                return session
            session = wizard_select(
                session,
                "profiles",
                tuple(profile_names[index] for index in event.selected),
            )
            session = wizard_advance(session)
            continue

        if session.current == "action":
            event = _curses_single_event(
                curses,
                stdscr,
                "Action  (enter=confirm, q=quit)",
                ACTIONS,
                session,
            )
            session = remember_position(session, "action", cursor=event.cursor, scroll=event.scroll)
            if event.kind == "back":
                session = wizard_back(session)
                continue
            if event.kind == "quit":
                if _curses_confirm_discard(curses, stdscr, session):
                    selection["cancelled"] = True
                    return session
                continue
            action = ACTIONS[event.selected[0]]
            session = wizard_select(session, "action", action)
            if action == "status" and session.basket:
                session = reconcile_basket(
                    session,
                    {item.key: "not applicable to the Status action" for item in session.basket},
                )
            session = wizard_advance(session)
            read_model = None
            continue

        if session.current == "scope":
            cursor, scroll = _position(session, "scope")
            try:
                result = _curses_install_scope(
                    curses,
                    stdscr,
                    wizard=True,
                    initial_cursor=cursor,
                    initial_scroll=scroll,
                    header=_curses_header(stdscr, session),
                )
            except TypeError as error:
                if "unexpected keyword argument" not in str(error):
                    raise
                result = _curses_install_scope(curses, stdscr)
            if isinstance(result, WizardInput):
                event = result
                scope = INSTALL_SCOPE_CHOICES[event.selected[0]].scope if event.selected else None
            else:
                scope = result
                event = (
                    WizardInput("quit", cursor=cursor, scroll=scroll)
                    if scope is None
                    else WizardInput(
                        "confirm",
                        (0 if scope == "project" else 1,),
                        0 if scope == "project" else 1,
                        scroll,
                    )
                )
            session = remember_position(session, "scope", cursor=event.cursor, scroll=event.scroll)
            if event.kind == "back":
                session = wizard_back(session)
                continue
            if event.kind == "quit":
                if _curses_confirm_discard(curses, stdscr, session):
                    selection["cancelled"] = True
                    return session
                continue
            assert scope is not None
            session = wizard_select(session, "scope", scope)
            session = wizard_advance(session)
            read_model = None
            continue

        if session.current == "mode":
            cursor, scroll = _position(session, "mode")
            try:
                result = _curses_install_mode(
                    curses,
                    stdscr,
                    wizard=True,
                    initial_cursor=cursor,
                    initial_scroll=scroll,
                    header=_curses_header(stdscr, session),
                )
            except TypeError as error:
                if "unexpected keyword argument" not in str(error):
                    raise
                result = _curses_install_mode(curses, stdscr)
            if isinstance(result, WizardInput):
                event = result
                mode = INSTALL_MODE_CHOICES[event.selected[0]].mode if event.selected else None
            else:
                mode = result
                if result == "back":
                    event = WizardInput("back", cursor=cursor, scroll=scroll)
                elif result is None:
                    event = WizardInput("quit", cursor=cursor, scroll=scroll)
                else:
                    index = 0 if result == "copy" else 1
                    event = WizardInput("confirm", (index,), index, scroll)
            session = remember_position(session, "mode", cursor=event.cursor, scroll=event.scroll)
            if event.kind == "back":
                session = wizard_back(session)
                continue
            if event.kind == "quit":
                if _curses_confirm_discard(curses, stdscr, session):
                    selection["cancelled"] = True
                    return session
                continue
            assert mode is not None
            session = wizard_select(session, "mode", mode)
            session = wizard_advance(session)
            read_model = None
            continue

        if session.current == "artifacts":
            key = (session.action, session.profiles, session.scope, session.install_mode)
            if read_model is None or read_key != key:
                loaded = _load_user_wizard_read_model(
                    session,
                    source_factory=open_source,
                    source_dir=source_dir,
                    repo=repo,
                    project=project,
                    user_home=user_home,
                )
                if isinstance(loaded, Err):
                    selection["error"] = (loaded.reason, loaded.code)
                    return session
                read_model = loaded
                read_key = key
                if loaded.source_label:
                    session = wizard_select(
                        session, "source", (loaded.source_label, loaded.source_root)
                    )
            if not read_model.choices:
                selection["empty"] = (session.action or "selection", session.profiles)
                return session
            availability = {
                _basket_key(choice): "" if choice.enabled else choice.reason
                for choice in read_model.choices
            }
            session = reconcile_basket(session, availability)
            basket_keys = {item.key for item in session.basket}
            selected = tuple(
                index
                for index, choice in enumerate(read_model.choices)
                if _basket_key(choice) in basket_keys
            )
            event = _curses_multi_event(
                curses,
                stdscr,
                "Select artifact(s)/bundle(s)  (space=toggle, ?=details, enter=confirm, q=quit)",
                tuple(choice.label for choice in read_model.choices),
                session,
                selected=selected,
                details=tuple(choice.description for choice in read_model.choices),
                disabled=tuple(not choice.enabled for choice in read_model.choices),
            )
            session = remember_position(
                session, "artifacts", cursor=event.cursor, scroll=event.scroll
            )
            if event.kind == "back":
                session = wizard_back(session)
                continue
            if event.kind == "quit":
                if _curses_confirm_discard(curses, stdscr, session):
                    selection["cancelled"] = True
                    return session
                continue
            if not event.selected:
                selection["empty_selection"] = True
                return session
            disabled_picks = tuple(
                index for index in event.selected if not read_model.choices[index].enabled
            )
            if disabled_picks:
                choice = read_model.choices[disabled_picks[0]]
                selection["error"] = (f"{choice.name}: {choice.reason}", 2)
                return session
            session = wizard_select(
                session,
                "artifacts",
                tuple(_basket_item(read_model.choices[index]) for index in event.selected),
            )
            session = wizard_advance(session)
            continue

        if session.current == "review":
            chosen: Tuple[_Choice, ...] = ()
            if read_model is not None:
                by_key = {_basket_key(choice): choice for choice in read_model.choices}
                chosen = tuple(by_key[item.key] for item in session.basket if item.key in by_key)
            request = _build_request(
                session.action or "status",
                chosen,
                session.profiles,
                source_dir=source_dir,
                repo=repo,
                project=project,
                install_mode=session.install_mode,  # type: ignore[arg-type]
                scope=session.scope,  # type: ignore[arg-type]
                user_home=user_home,
            )
            confirmation: Optional[InstallConfirmation] = None
            if session.action == "install":
                assert read_model is not None
                confirmation = build_install_confirmation(
                    source_label=read_model.source_label,
                    source_root=read_model.source_root,
                    project=project,
                    profiles=session.profiles,
                    requested_mode=session.install_mode,  # type: ignore[arg-type]
                    catalog=read_model.catalog,
                    choices=chosen,
                    profiles_map=read_model.profiles_map,
                    scope=session.scope,  # type: ignore[arg-type]
                    user_home=user_home,
                )
                try:
                    review = _curses_confirm_install(
                        curses,
                        stdscr,
                        confirmation,
                        header=_curses_header(stdscr, session),
                    )
                except TypeError as error:
                    if "unexpected keyword argument" not in str(error):
                        raise
                    review = _curses_confirm_install(curses, stdscr, confirmation)
            else:
                review = _curses_review(
                    curses,
                    stdscr,
                    session,
                    _user_review_lines(
                        session,
                        read_model,
                        project=project,
                        user_home=user_home,
                    ),
                )
            if review == "back":
                session = wizard_back(session)
                continue
            if review == "quit":
                if _curses_confirm_discard(curses, stdscr, session):
                    selection["cancelled"] = True
                    return session
                continue
            if not review:
                selection["cancelled"] = True
                return session
            if not can_finalize(session, revision=session.revision):
                selection["error"] = ("Wizard state changed; review it again before Finalize.", 2)
                return session
            selection["request"] = request
            selection["confirmation"] = confirmation
            return session

    return session


def _run_curses(
    *,
    source_dir: Optional[str] = None,
    repo: Optional[str] = None,
    project: Optional[str] = None,
    user_home: Optional[str] = None,
) -> int:
    """Collect a persistent wizard session and dispatch only after curses teardown."""
    import curses  # stdlib; imported lazily so the text path needs no terminal at all.

    if not load_profiles(project):  # pragma: no cover - built-ins always present
        print("No profiles available.")
        return 0
    selection: dict = {}

    def _ui(stdscr) -> None:
        curses.curs_set(0)
        session = initial_session()
        onboarding = _curses_onboarding(curses, stdscr)
        if onboarding.kind == "quit":
            selection["cancelled"] = True
            return
        session = wizard_advance(session)
        while session.current == "role":
            event = _curses_single_event(
                curses,
                stdscr,
                "Choose how you want to use aart  (enter=confirm, q=quit)",
                tuple(f"{role.label} - {role.description}" for role in ROLES),
                session,
            )
            session = remember_position(session, "role", cursor=event.cursor, scroll=event.scroll)
            if event.kind == "back":
                onboarding = _curses_onboarding(curses, stdscr)
                if onboarding.kind == "quit":
                    selection["cancelled"] = True
                    return
                continue
            if event.kind == "quit":
                selection["cancelled"] = True
                return
            role = ROLES[event.selected[0]].name
            session = wizard_select(session, "role", role)
            session = wizard_advance(session)
            if role == "user":
                session = _run_user_curses_wizard(
                    curses,
                    stdscr,
                    session,
                    selection,
                    source_dir=source_dir,
                    repo=repo,
                    project=project,
                    user_home=user_home,
                )
                if selection or session.current != "role":
                    return
                continue

            from .commands import upstream

            catalog_root = os.path.abspath(source_dir or ".")
            context_result = upstream.load_maintainer_context(
                Request(
                    command="upstream",
                    upstream_action="validate",
                    source_dir=catalog_root,
                    repo=repo,
                )
            )
            if isinstance(context_result, Err):
                selection["error"] = (context_result.reason, context_result.code)
                return
            while session.current == "maintainer_action":
                event = _curses_single_event(
                    curses,
                    stdscr,
                    f"Maintainer - {catalog_root}  (enter=confirm, q=quit)",
                    tuple(label for _action, label in MAINTAINER_ACTIONS),
                    session,
                )
                if event.kind == "back":
                    session = wizard_back(session)
                    break
                if event.kind == "quit":
                    selection["cancelled"] = True
                    return
                action = MAINTAINER_ACTIONS[event.selected[0]][0]
                session = wizard_select(session, "maintainer_action", action)
                session = wizard_advance(session)
                if action == "user":
                    session = _run_user_curses_wizard(
                        curses,
                        stdscr,
                        session,
                        selection,
                        source_dir=source_dir,
                        repo=repo,
                        project=project,
                        user_home=user_home,
                    )
                    if selection or session.current != "maintainer_action":
                        return
                    continue
                selection["maintainer_action"] = action
                selection["maintainer_context"] = context_result.value
                selection["maintainer_session"] = session
                return

    try:
        curses.wrapper(_ui)
    except Exception:
        return _run_text(
            source_dir=source_dir,
            repo=repo,
            project=project,
            user_home=user_home,
        )

    if "error" in selection:
        reason, code = selection["error"]
        print(f"error: {reason}")
        return code
    if "empty" in selection:
        action, profiles = selection["empty"]
        print(_empty_choices_message(action, profiles))
        return _render_result(CommandOutcome(0, ActionSummary(action=action)), print)
    if "maintainer_action" in selection:
        result = _run_maintainer_text(
            selection["maintainer_session"],
            input,
            print,
            source_factory=open_source,
            source_dir=source_dir,
            repo=repo,
            project=project,
        )
        return _cancel(print) if isinstance(result, WizardSession) else result
    if "request" not in selection:
        if "empty_selection" in selection:
            return _cancel(print, "No artifacts selected; no changes were made.")
        return _cancel(print)

    request = selection["request"]
    outcome = _dispatch_result(request)
    code = _render_result(outcome, print)
    confirmation = selection.get("confirmation")
    if code != 0 or confirmation is None:
        return code
    return _run_post_install_setup(
        confirmation.setup_queue,
        request,
        scope_root=confirmation.destination_root,
        read=input,
        write=print,
    )


def _curses_multiselect(
    curses,
    stdscr,
    title: str,
    labels: Sequence[str],
    details: Optional[Sequence[str]] = None,
    disabled: Optional[Sequence[bool]] = None,
    *,
    wizard: bool = False,
    initial_checked: Sequence[int] = (),
    initial_cursor: int = 0,
    initial_scroll: int = 0,
    header: Sequence[str] = (),
):
    """A checkbox list, optionally returning explicit wizard navigation and position."""
    if not labels:
        return WizardInput("confirm") if wizard else ()
    cursor = min(max(initial_cursor, 0), len(labels) - 1)
    scroll = max(initial_scroll, 0)
    checked = [False] * len(labels)
    for index in initial_checked:
        if 0 <= index < len(checked) and (disabled is None or not disabled[index]):
            checked[index] = True
    backspace_keys = {getattr(curses, "KEY_BACKSPACE", -1), 127, 8}
    while True:
        scroll = _draw_list(
            curses,
            stdscr,
            title,
            labels,
            cursor,
            checked,
            disabled=disabled,
            header=header,
            scroll=scroll,
        )
        ch = stdscr.getch()
        if ch in (ord("q"), 27):  # q / ESC
            return WizardInput("quit", cursor=cursor, scroll=scroll) if wizard else None
        elif wizard and ch in backspace_keys:
            return WizardInput("back", cursor=cursor, scroll=scroll)
        elif ch in (curses.KEY_UP, ord("k")):
            cursor = (cursor - 1) % len(labels)
        elif ch in (curses.KEY_DOWN, ord("j")):
            cursor = (cursor + 1) % len(labels)
        elif ch == ord(" "):
            if disabled is None or not disabled[cursor]:
                checked[cursor] = not checked[cursor]
        elif ch == ord("?") and details is not None and cursor < len(details):
            _draw_detail(curses, stdscr, labels[cursor], details[cursor])
        elif ch in (curses.KEY_ENTER, 10, 13):
            selected = tuple(i for i, on in enumerate(checked) if on)
            return (
                WizardInput("confirm", selected, cursor=cursor, scroll=scroll)
                if wizard
                else selected
            )


def _curses_singleselect(
    curses,
    stdscr,
    title: str,
    labels: Sequence[str],
    *,
    wizard: bool = False,
    initial_cursor: int = 0,
    initial_scroll: int = 0,
    header: Sequence[str] = (),
):
    """A single-choice list, optionally returning explicit wizard navigation."""
    cursor = min(max(initial_cursor, 0), max(len(labels) - 1, 0))
    scroll = max(initial_scroll, 0)
    backspace_keys = {getattr(curses, "KEY_BACKSPACE", -1), 127, 8}
    while True:
        scroll = _draw_list(
            curses,
            stdscr,
            title,
            labels,
            cursor,
            None,
            header=header,
            scroll=scroll,
        )
        ch = stdscr.getch()
        if ch in (ord("q"), 27):
            return WizardInput("quit", cursor=cursor, scroll=scroll) if wizard else None
        elif wizard and ch in backspace_keys:
            return WizardInput("back", cursor=cursor, scroll=scroll)
        elif ch in (curses.KEY_UP, ord("k")):
            cursor = (cursor - 1) % len(labels)
        elif ch in (curses.KEY_DOWN, ord("j")):
            cursor = (cursor + 1) % len(labels)
        elif ch in (curses.KEY_ENTER, 10, 13):
            return WizardInput("confirm", (cursor,), cursor, scroll) if wizard else cursor


def _draw_list(
    curses,
    stdscr,
    title: str,
    labels,
    cursor: int,
    checked,
    *,
    disabled: Optional[Sequence[bool]] = None,
    header: Sequence[str] = (),
    scroll: int = 0,
) -> int:
    """Render *title* + the labels, marking the cursor row and any checked rows."""
    stdscr.clear()
    available = max(_width(stdscr) - 1, 0)
    height = _height(stdscr)
    header_budget = max(height - 4, 1)
    if len(header) > header_budget:
        priorities = (
            lambda line: "[●]" in line,
            lambda line: line.startswith("Stage:"),
            lambda line: line.startswith("Basket:"),
            lambda line: line.startswith("Removed "),
            lambda line: "back" in line.lower() and "quit" in line.lower(),
        )
        picked: List[int] = []
        for predicate in priorities:
            picked.extend(
                index
                for index, line in enumerate(header)
                if predicate(line) and index not in picked
            )
        picked.extend(index for index in range(len(header)) if index not in picked)
        visible_indices = set(picked[:header_budget])
        header = tuple(line for index, line in enumerate(header) if index in visible_indices)
    row = 0
    for line in header:
        if row >= height:
            break
        stdscr.addstr(row, 0, _ellipsize(line, available))
        row += 1
    if row < height:
        stdscr.addstr(row, 0, _ellipsize(title, available))
    list_start = row + 2
    if checked is not None:
        selected_count = sum(
            1
            for index, value in enumerate(checked)
            if value and (disabled is None or not disabled[index])
        )
        if row + 1 < height:
            stdscr.addstr(
                row + 1,
                0,
                _ellipsize(f"Selected: {selected_count}", available),
            )
        list_start = row + 3
    visible_rows = max(height - list_start, 1)
    max_scroll = max(len(labels) - visible_rows, 0)
    scroll = min(max(scroll, 0), max_scroll)
    if cursor < scroll:
        scroll = cursor
    elif cursor >= scroll + visible_rows:
        scroll = cursor - visible_rows + 1
    for display_row, i in enumerate(range(scroll, min(len(labels), scroll + visible_rows))):
        label = labels[i]
        prefix = "> " if i == cursor else "  "
        box = ""
        if checked is not None:
            if disabled is not None and disabled[i]:
                box = "[-] "
            else:
                box = "[x] " if checked[i] else "[ ] "
        line = f"{prefix}{box}{label}"
        target_row = list_start + display_row
        if target_row < height:
            stdscr.addstr(target_row, 0, _ellipsize(line, available))
    stdscr.refresh()
    return scroll


def _curses_onboarding(curses, stdscr) -> WizardInput:
    """Render the first-screen controls; test doubles without a screen auto-confirm."""

    if not all(hasattr(stdscr, name) for name in ("clear", "addstr", "refresh", "getch")):
        return WizardInput("confirm")
    session = initial_session()
    offset = 0
    while True:
        stdscr.clear()
        available = max(_width(stdscr) - 1, 0)
        lines = onboarding_lines("curses") + render_header(
            session, width=max(available, 1), frontend="curses"
        )
        height = _height(stdscr)
        body_height = max(height - 1, 1)
        max_offset = max(len(lines) - body_height, 0)
        offset = min(offset, max_offset)
        for row, line in enumerate(lines[offset : offset + body_height]):
            stdscr.addstr(row, 0, _ellipsize(line, available))
        if height:
            stdscr.addstr(
                height - 1,
                0,
                _ellipsize("Enter = start · ↑/↓ = scroll · q = quit", available),
            )
        stdscr.refresh()
        ch = stdscr.getch()
        if ch in (curses.KEY_ENTER, 10, 13):
            return WizardInput("confirm")
        if ch in (ord("q"), 27):
            return WizardInput("quit")
        if ch in (curses.KEY_DOWN, ord("j")) and offset < max_offset:
            offset += 1
        elif ch in (curses.KEY_UP, ord("k")) and offset > 0:
            offset -= 1
        elif ch == getattr(curses, "KEY_NPAGE", -1) and offset < max_offset:
            offset = min(offset + body_height, max_offset)
        elif ch == getattr(curses, "KEY_PPAGE", -1) and offset > 0:
            offset = max(offset - body_height, 0)


def _curses_install_scope(
    curses,
    stdscr,
    *,
    wizard: bool = False,
    initial_cursor: int = 0,
    initial_scroll: int = 0,
    header: Sequence[str] = (),
):
    """Scope selector with Project under the initial cursor."""

    labels = [f"{choice.label} — {choice.description}" for choice in INSTALL_SCOPE_CHOICES]
    selected = _curses_singleselect(
        curses,
        stdscr,
        "Installation scope  (enter=confirm, q=quit)",
        labels,
        wizard=wizard,
        initial_cursor=initial_cursor,
        initial_scroll=initial_scroll,
        header=header,
    )
    if isinstance(selected, WizardInput):
        return selected
    if selected is None:
        return None
    return INSTALL_SCOPE_CHOICES[selected].scope


def _curses_install_mode(
    curses,
    stdscr,
    *,
    wizard: bool = False,
    initial_cursor: int = 0,
    initial_scroll: int = 0,
    header: Sequence[str] = (),
):
    """Install-only mode selector with Copy under the initial cursor."""

    labels = [f"{choice.label} — {choice.description}" for choice in INSTALL_MODE_CHOICES]
    cursor = min(max(initial_cursor, 0), len(labels) - 1)
    scroll = max(initial_scroll, 0)
    backspace_keys = {getattr(curses, "KEY_BACKSPACE", -1), 127, 8}
    while True:
        scroll = _draw_list(
            curses,
            stdscr,
            "Installation mode  (enter=confirm, backspace=back, q=quit)",
            labels,
            cursor,
            None,
            header=header,
            scroll=scroll,
        )
        ch = stdscr.getch()
        if ch in (ord("q"), 27):
            return WizardInput("quit", cursor=cursor, scroll=scroll) if wizard else None
        if ch in backspace_keys:
            return WizardInput("back", cursor=cursor, scroll=scroll) if wizard else "back"
        if ch in (curses.KEY_UP, ord("k")):
            cursor = (cursor - 1) % len(labels)
        elif ch in (curses.KEY_DOWN, ord("j")):
            cursor = (cursor + 1) % len(labels)
        elif ch in (curses.KEY_ENTER, 10, 13):
            return (
                WizardInput("confirm", (cursor,), cursor, scroll)
                if wizard
                else INSTALL_MODE_CHOICES[cursor].mode
            )


def _curses_confirm_install(
    curses,
    stdscr,
    confirmation: InstallConfirmation,
    *,
    header: Sequence[str] = (),
):
    """Render shared confirmation facts and return true only on explicit confirmation."""

    lines = tuple(header) + render_install_confirmation(confirmation)
    available = max(_width(stdscr) - 1, 0)
    height = _height(stdscr)
    body_height = max(height - 1, 1)
    max_offset = max(len(lines) - body_height, 0)
    offset = 0
    while True:
        stdscr.clear()
        for row, line in enumerate(lines[offset : offset + body_height]):
            stdscr.addstr(row, 0, _ellipsize(line, available))
        if height > 0:
            stdscr.addstr(
                height - 1,
                0,
                _ellipsize(
                    "↑/↓ = scroll · Enter/y = Finalize · Backspace = back · n/q = cancel",
                    available,
                ),
            )
        stdscr.refresh()
        ch = stdscr.getch()
        if ch in (curses.KEY_ENTER, 10, 13, ord("y"), ord("Y")):
            return True
        if ch in (getattr(curses, "KEY_BACKSPACE", -1), 127, 8):
            return "back"
        if ch in (ord("q"), 27):
            return "quit"
        if ch in (ord("n"), ord("N")):
            return False
        if ch in (curses.KEY_DOWN, ord("j")) and offset < max_offset:
            offset += 1
        elif ch in (curses.KEY_UP, ord("k")) and offset > 0:
            offset -= 1
        elif ch == getattr(curses, "KEY_NPAGE", -1) and offset < max_offset:
            offset = min(offset + body_height, max_offset)
        elif ch == getattr(curses, "KEY_PPAGE", -1) and offset > 0:
            offset = max(offset - body_height, 0)


def _ellipsize(text: str, width: int) -> str:
    """Return one visual line no wider than ``width``, marking truncation with ``…``."""
    one_line = text.replace("\r", " ").replace("\n", " ")
    if width <= 0:
        return ""
    if len(one_line) <= width:
        return one_line
    if width == 1:
        return "…"
    return one_line[: width - 1] + "…"


def _draw_detail(curses, stdscr, label: str, description: str) -> None:
    """Show the complete description in a wrapped, scrollable curses detail view."""
    available = max(_width(stdscr) - 1, 1)
    height = _height(stdscr)
    content_top = 3
    content_height = max(height - content_top - 1, 1)
    wrapped = textwrap.wrap(description or "No catalog description is available.", available) or [
        ""
    ]
    max_offset = max(len(wrapped) - content_height, 0)
    offset = 0

    while True:
        stdscr.clear()
        if height > 0:
            stdscr.addstr(0, 0, _ellipsize("Artifact details", available))
        if height > 1:
            stdscr.addstr(1, 0, _ellipsize(label, available))
        for relative_row, line in enumerate(wrapped[offset : offset + content_height]):
            row = content_top + relative_row
            if row >= max(height - 1, 0):
                break
            stdscr.addstr(row, 0, _ellipsize(line, available))
        if height > 0:
            footer = (
                "↑/↓/Pg scroll · other key returns" if max_offset else "Press any key to return."
            )
            stdscr.addstr(height - 1, 0, _ellipsize(footer, available))
        stdscr.refresh()

        ch = stdscr.getch()
        if ch in (curses.KEY_DOWN, ord("j")) and offset < max_offset:
            offset += 1
        elif ch in (curses.KEY_UP, ord("k")) and offset > 0:
            offset -= 1
        elif ch == curses.KEY_NPAGE and offset < max_offset:
            offset = min(offset + content_height, max_offset)
        elif ch == curses.KEY_PPAGE and offset > 0:
            offset = max(offset - content_height, 0)
        else:
            return


def _height(stdscr) -> int:
    return stdscr.getmaxyx()[0]


def _width(stdscr) -> int:
    return stdscr.getmaxyx()[1]


# --------------------------------------------------------------------------- #
# Entry point — chooses curses vs text and delegates.                           #
# --------------------------------------------------------------------------- #
def run(
    *,
    source_dir: Optional[str] = None,
    repo: Optional[str] = None,
    project: Optional[str] = None,
    user_home: Optional[str] = None,
) -> int:
    """Launch the interactive selector; return a process exit code.

    Called by ``cli._run_bare`` on a bare TTY invocation. Tries the ``curses`` selector and
    **degrades to the ``input()`` flow** if curses cannot be imported or initialised. A clean
    quit (no selection) returns 0. ``source_dir`` / ``repo`` / ``project`` default to ``None``
    so the standard source resolution (default repo, or env/flags handled upstream) applies.
    """
    try:
        import curses  # noqa: F401  (presence check only)
        import sys

        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            raise RuntimeError("not a tty")
    except Exception:
        return _run_text(
            source_dir=source_dir,
            repo=repo,
            project=project,
            user_home=user_home,
        )

    try:
        return _run_curses(
            source_dir=source_dir,
            repo=repo,
            project=project,
            user_home=user_home,
        )
    except Exception:  # pragma: no cover - last-resort guard around the curses path
        return _run_text(
            source_dir=source_dir,
            repo=repo,
            project=project,
            user_home=user_home,
        )
