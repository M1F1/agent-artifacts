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
import sys
import textwrap
from dataclasses import dataclass, replace
from typing import Callable, List, Literal, Mapping, Optional, Sequence, Tuple

from . import __version__
from .catalog import resolve_bundle
from .compatibility import check_profile_compatibility
from .configuration.model import (
    ConfiguredSource,
    OrganizationPolicy,
    SourceKind,
    UserConfiguration,
    default_user_configuration,
    git_location_parts,
)
from .configuration.schema import configured_source_from_input
from .consumer import (
    ConsumerActionRequest,
    ConsumerApplicationService,
    ConsumerOutcome,
    ConsumerReview,
    render_consumer_outcome,
    render_consumer_review,
)
from .curation.model import (
    CurationAction,
    CurationRequest,
    render_curation_outcome,
    render_curation_review,
)
from .curation.runtime import CurationService, PreparedCuration
from .domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from .domain.identifiers import ArtifactCoordinate, SourceAlias
from .domain.result import Err as DomainErr
from .domain.result import Ok as DomainOk
from .domain.result import Result as DomainResult
from .install_modes import supports_symlink
from .marketplace.model import MarketplaceCatalog
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
from .reporting.application import ReportingApplicationService
from .reporting.model import ReportingPlan, UsageReport
from .reporting.projection import (
    RegistryUsageReport,
    SetupReportState,
    usage_report_from_consumer,
    usage_reports_by_registry_from_consumer,
)
from .setup import build_queue, recovery_messages
from .source import open_source
from .sources.model import HealthStatus, SourceHealth
from .tui_layout import (
    BOX_CHECKED,
    BOX_DISABLED,
    BOX_EMPTY,
    CHROME_ROWS,
    HINT_ORDER,
    STAGE_CURRENT,
    status_bar,
)
from .tui_marketplace import MarketplaceArtifactRow, MarketplaceTarget, render_marketplace_row
from .tui_sources import (
    SourceAdditionRequest,
    SourceManagementRequest,
    SourceSelection,
    SourceStageView,
    build_source_stage,
    plan_source_addition,
    plan_source_management,
    render_source_addition_review,
    render_source_row,
)
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

CANONICAL_MAINTAINER_ACTIONS: Tuple[Tuple[str, str], ...] = (
    ("validate", "Validate canonical registry protocol and generated evidence"),
    ("scaffold", "Scaffold one native artifact package for review"),
    ("promote-native", "Promote one reviewed native Git reference"),
    ("import-foreign", "Convert a pinned legacy catalog with explicit warnings"),
    ("update-upstream", "Check and review one locked native upstream update"),
    ("lock", "Resolve approved references into the committed lock"),
    ("build", "Build the payload-free marketplace index"),
    ("audit", "Audit review, provenance, setup, license, and security evidence"),
    ("diff", "Preview deterministic canonical-format diff without writing"),
    ("init", "Initialize an empty registry checkout"),
    ("user", "Enter User workflows; AART never commits or pushes Maintainer changes"),
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
SourceFinalizeFn = Callable[[SourceManagementRequest], DomainResult[object]]
SourceAdditionFinalizeFn = Callable[[SourceAdditionRequest], DomainResult[object]]
ConsumerServiceFactory = Callable[[UserConfiguration], DomainResult[ConsumerApplicationService]]
ReportingServiceFactory = Callable[[UserConfiguration], DomainResult[ReportingApplicationService]]
CurationServiceFactory = Callable[[str], DomainResult[CurationService]]


@dataclass(frozen=True, slots=True)
class _RuntimeSourceStage:
    """The imperative source boundary injected into either human TUI frontend."""

    view: SourceStageView
    source_finalizer: SourceFinalizeFn | None
    source_addition_finalizer: SourceAdditionFinalizeFn | None


SourceStageLoader = Callable[[], DomainResult[_RuntimeSourceStage]]


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
    qualified_key: str = ""


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
        label += f" ({status})"
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


@dataclass(frozen=True, slots=True)
class _CanonicalSetupRun:
    exit_code: int
    reporting: Tuple[SetupReportState, ...]


def _setup_reporting_failure(status: str) -> Tuple[str, str] | None:
    if status in {"configured", "already-configured", "not-required"}:
        return None
    if status == "verification-failed":
        return ("verification", "setup-verification-failed")
    if status in {"rollback-incomplete", "rolled-back"}:
        return ("rollback", f"setup-{status}")
    if status in {"queue-declined", "planning-failed"}:
        return ("queue", f"setup-{status}")
    return ("setup-installer", f"setup-{status}")


def _setup_reporting_key(
    review: ConsumerReview,
    coordinate: ArtifactCoordinate,
    profile: str,
    scope: str,
) -> str:
    """Bind an unversioned setup identity back to its exact consumer Review item."""

    matches = tuple(
        item.key
        for item in review.items
        if item.coordinate.source == coordinate.source
        and item.coordinate.artifact == coordinate.artifact
        and item.profile == profile
        and item.scope == scope
    )
    if len(matches) == 1:
        return matches[0]
    return f"{coordinate}#{profile}/{scope}"


def _canonical_setup_run(
    service: ConsumerApplicationService,
    review: ConsumerReview,
    outcome: ConsumerOutcome,
    *,
    read: ReadFn,
    write: WriteFn,
) -> _CanonicalSetupRun:
    """Prepare, separately review, and sequentially execute canonical post-payload setup."""

    if not any(item.setup_status == "pending" for item in outcome.items):
        return _CanonicalSetupRun(0, ())
    queue = service.setup_queue(review, outcome)
    if queue.failures and all("authoriz" in item.detail.casefold() for item in queue.failures):
        write("Setup needs explicit permission for untrusted/custom source capabilities.")
        answer = _read_line(read, "Authorize these reviewed setup capabilities? [y/N]: ")
        if answer is not None and answer.strip().lower() in ("y", "yes"):
            queue = service.setup_queue(
                review,
                outcome,
                authorize_untrusted_source=True,
                authorize_custom_entrypoint=True,
            )
    for failure in queue.failures:
        write(f"Setup planning failed for {failure.key}: {failure.detail}")
        write(f"  Retry: aart setup retry --artifact {failure.key.split('#', 1)[0]}")
    if not queue.plans:
        plan_failures = tuple(
            SetupReportState(
                failure.key,
                "planning-failed",
                failure_phase="queue",
                failure_code="setup-planning-failed",
            )
            for failure in queue.failures
        )
        return _CanonicalSetupRun(1 if queue.failures else 0, plan_failures)
    write("Review setup queue (runs sequentially after installed payloads):")
    for plan in queue.plans:
        write(
            f"  - {plan.request.coordinate}#{plan.request.profile}/{plan.request.scope}, "
            f"trust {plan.trust}, recipe {plan.recipe_path}, review {plan.review_digest}"
        )
        for effect in plan.legacy_plan.effects:
            write(
                f"      {effect.module}: {effect.summary}"
                + (f" -> {effect.target}" if effect.target else "")
            )
    answer = _read_line(read, "Finalize this setup queue? [y/N]: ")
    if answer is None or answer.strip().lower() not in ("y", "yes"):
        write("Setup remains pending; installed payloads were not rolled back.")
        declined = tuple(
            SetupReportState(
                _setup_reporting_key(
                    review,
                    plan.request.coordinate,
                    plan.request.profile,
                    plan.request.scope,
                ),
                "queue-declined",
                plan.recipe_digest,
                "queue",
                "setup-queue-declined",
            )
            for plan in queue.plans
        )
        planning = tuple(
            SetupReportState(
                failure.key,
                "planning-failed",
                failure_phase="queue",
                failure_code="setup-planning-failed",
            )
            for failure in queue.failures
        )
        return _CanonicalSetupRun(1, (*declined, *planning))

    def consent(effect) -> bool:
        write(
            f"Approve {effect.module}: {effect.summary} "
            f"[{'reversible' if effect.reversible else 'not automatically reversible'}]"
        )
        decision = _read_line(read, "Approve this exact effect? [y/N]: ")
        return decision is not None and decision.strip().lower() in ("y", "yes")

    setup_outcome = service.finalize_setup_queue(queue, consent=consent)
    write(
        f"Setup outcome: configured={setup_outcome.configured}, "
        f"incomplete={setup_outcome.incomplete}."
    )
    for item in setup_outcome.items:
        write(
            f"  - {item.coordinate}#{item.profile}/{item.scope}: "
            f"{item.setup_status.value} — {item.detail}"
        )
        if not item.successful:
            write(f"    Retry: aart setup retry --artifact {item.coordinate}")
    plan_by_key = {
        f"{plan.request.coordinate}#{plan.request.profile}/{plan.request.scope}": plan
        for plan in queue.plans
    }
    reported_states: List[SetupReportState] = []
    for item in setup_outcome.items:
        key = f"{item.coordinate}#{item.profile}/{item.scope}"
        reporting_key = _setup_reporting_key(
            review,
            item.coordinate,
            item.profile,
            item.scope,
        )
        status = item.setup_status.value
        failure_spec = _setup_reporting_failure(status)
        setup_plan = plan_by_key.get(key)
        reported_states.append(
            SetupReportState(
                reporting_key,
                status,
                None if setup_plan is None else setup_plan.recipe_digest,
                None if failure_spec is None else failure_spec[0],
                None if failure_spec is None else failure_spec[1],
            )
        )
    reported_states.extend(
        SetupReportState(
            queue_failure.key,
            "planning-failed",
            failure_phase="queue",
            failure_code="setup-planning-failed",
        )
        for queue_failure in queue.failures
    )
    return _CanonicalSetupRun(
        0 if setup_outcome.incomplete == 0 and not queue.failures else 1,
        tuple(reported_states),
    )


def _run_canonical_setup_queue(
    service: ConsumerApplicationService,
    review: ConsumerReview,
    outcome: ConsumerOutcome,
    *,
    read: ReadFn,
    write: WriteFn,
) -> int:
    return _canonical_setup_run(service, review, outcome, read=read, write=write).exit_code


def _offer_usage_report(
    service: ReportingApplicationService | None,
    event: UsageReport,
    *,
    read: ReadFn,
    write: WriteFn,
) -> None:
    """Offer/submit after terminal outcomes; every failure is warning-only."""

    if service is None:
        return
    prepared = service.prepare(event)
    if isinstance(prepared, DomainErr):
        write("warning: usage report could not be prepared; the artifact outcome is unchanged")
        return
    plan = prepared.value
    if plan is None:
        return
    _offer_prepared_usage_report(service, plan, read=read, write=write)


def _offer_prepared_usage_report(
    service: ReportingApplicationService,
    plan: ReportingPlan,
    *,
    read: ReadFn,
    write: WriteFn,
) -> None:
    target = f"{plan.destination.host}/{plan.destination.repository}"
    if plan.destination.mode.value == "prompt":
        answer = _read_line(read, f"Share this redacted usage report with {target}? [y/N]: ")
        if answer is None or answer.strip().lower() not in ("y", "yes"):
            write("Usage report was not submitted.")
            return
    write("Exact redacted usage report payload:")
    write(plan.payload.decode("utf-8").strip())
    if plan.destination.mode.value == "prompt":
        answer = _read_line(read, "Open the prefilled GitHub issue? [y/N]: ")
        if answer is None or answer.strip().lower() not in ("y", "yes"):
            write("Usage report was not submitted.")
            return
    submitted = service.submit(plan)
    if isinstance(submitted, DomainErr):
        write("warning: usage report submission failed; the artifact outcome is unchanged")
        return
    write(
        "Usage report opened in the browser."
        if submitted.value.status == "browser-opened"
        else "Usage report submitted."
    )


def _offer_routed_usage_reports(
    service: ReportingApplicationService | None,
    combined: UsageReport,
    routed: Tuple[RegistryUsageReport, ...],
    *,
    read: ReadFn,
    write: WriteFn,
) -> None:
    if service is None:
        return
    prepared = service.prepare_routed(combined, routed)
    if isinstance(prepared, DomainErr):
        write("warning: usage reports could not be prepared; the artifact outcome is unchanged")
        return
    if prepared.value:
        write("Optional redacted usage reports are available for these artifact registries:")
        for plan in prepared.value:
            write(f"  - {plan.destination.host}/{plan.destination.repository}")
    for plan in prepared.value:
        _offer_prepared_usage_report(service, plan, read=read, write=write)


def _complete_canonical_consumer_action(
    consumer: ConsumerApplicationService,
    review: ConsumerReview,
    outcome: ConsumerOutcome,
    reporting: ReportingApplicationService | None,
    *,
    read: ReadFn,
    write: WriteFn,
) -> int:
    setup = _canonical_setup_run(consumer, review, outcome, read=read, write=write)
    try:
        event = usage_report_from_consumer(
            review,
            outcome,
            setup.reporting,
            aart_version=__version__,
            interface="tui",
        )
        routed = usage_reports_by_registry_from_consumer(
            review,
            outcome,
            setup.reporting,
            aart_version=__version__,
            interface="tui",
        )
    except ValueError:
        write("warning: usage report projection failed; the artifact outcome is unchanged")
        return setup.exit_code
    _offer_routed_usage_reports(reporting, event, routed, read=read, write=write)
    return setup.exit_code


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


def _legacy_source_stage_view(
    *,
    source_dir: Optional[str],
    repo: Optional[str],
) -> SourceStageView:
    """Describe one explicitly requested legacy source without touching the executable checkout."""

    if source_dir is not None:
        source = ConfiguredSource(
            SourceAlias("explicit-local"),
            SourceKind.SOURCE_LOCAL,
            os.path.abspath(source_dir),
            None,
            True,
        )
    elif repo is not None:
        source = ConfiguredSource(
            SourceAlias("explicit-git"),
            SourceKind.SOURCE_GIT,
            f"https://github.com/{repo.removesuffix('.git')}.git",
            "main",
            True,
        )
    else:
        raise ValueError("legacy source stage requires an explicit --source or --repo")
    baseline = default_user_configuration()
    configuration = UserConfiguration(
        baseline.schema_version,
        (source,),
        None,
        baseline.sync,
        baseline.reporting,
    )
    projected = build_source_stage(
        configuration,
        OrganizationPolicy(1),
        {source.alias: SourceHealth(HealthStatus.MISSING, None, None)},
        first_run=True,
    )
    assert isinstance(projected, DomainOk)
    return projected.value


def _empty_source_stage_view() -> SourceStageView:
    """Return the real no-source state for private frontend tests without filesystem effects."""

    projected = build_source_stage(
        default_user_configuration(),
        OrganizationPolicy(1),
        {},
        first_run=True,
    )
    assert isinstance(projected, DomainOk)
    return projected.value


def _runtime_source_stage_context(
    *,
    source_dir: Optional[str],
    repo: Optional[str],
    user_home: Optional[str],
) -> DomainResult[_RuntimeSourceStage]:
    """Load configured sources and current managed health at the imperative TUI boundary."""

    if source_dir is not None or repo is not None:
        return DomainOk(
            _RuntimeSourceStage(
                _legacy_source_stage_view(source_dir=source_dir, repo=repo),
                None,
                None,
            )
        )

    import time

    from .application.configuration import (
        ConfigurationPorts,
        ConfigurationRequest,
        load_configuration,
        save_user_configuration_checked,
    )
    from .application.source_management import (
        finalize_source_addition,
        finalize_source_management,
    )
    from .application.sources import SourceStatusRequest, source_status
    from .configuration.paths import Platform, resolve_config_paths
    from .configuration.policy import RuntimeOverrides
    from .io.config_cas import checked_config_writer
    from .io.config_store import (
        read_configuration,
        recover_configuration,
        write_configuration,
    )
    from .io.source_store import read_current_source
    from .sources.model import CurrentSourceRequest, source_instance_id, source_store_paths

    platform = Platform.DARWIN if sys.platform == "darwin" else Platform.LINUX
    home = os.path.abspath(user_home or os.path.expanduser("~"))
    paths = resolve_config_paths(
        platform,
        home=home,
        xdg_config_home=os.environ.get("XDG_CONFIG_HOME"),
        xdg_data_home=os.environ.get("XDG_DATA_HOME"),
        xdg_cache_home=os.environ.get("XDG_CACHE_HOME"),
    )
    ports = ConfigurationPorts(
        read_configuration,
        write_configuration,
        recover_configuration,
        checked_config_writer,
    )
    loaded = load_configuration(
        ConfigurationRequest(paths, RuntimeOverrides(), content_required=False),
        ports,
    )
    if isinstance(loaded, DomainErr):
        return loaded
    configuration = loaded.value.user_configuration
    policy = loaded.value.effective.policy
    now = int(time.time())
    health = {}
    for source in configuration.sources:
        store_paths = source_store_paths(paths.data_root, source_instance_id(source))
        health[source.alias] = source_status(
            SourceStatusRequest(
                CurrentSourceRequest(store_paths, source.alias),
                now,
                configuration.sync.max_age_seconds,
            ),
            read_current_source,
        )
    projected = build_source_stage(
        configuration,
        policy,
        health,
        first_run=loaded.value.first_run is not None,
    )
    if isinstance(projected, DomainErr):
        return projected

    def refreshed_configuration(
        expected_before: UserConfiguration, expected_policy: OrganizationPolicy
    ):
        refreshed = load_configuration(
            ConfigurationRequest(paths, RuntimeOverrides(), content_required=False),
            ports,
        )
        if isinstance(refreshed, DomainErr):
            return refreshed
        if refreshed.value.recovery is not None:
            return DomainErr(
                (
                    Diagnostic(
                        DiagnosticCode("config-invalid"),
                        Severity.ERROR,
                        "user configuration is invalid; recover it before changing sources",
                        remediation=("recover the configuration and retry",),
                    ),
                )
            )
        if (
            refreshed.value.user_configuration != expected_before
            or refreshed.value.effective.policy != expected_policy
        ):
            return DomainErr(
                (
                    Diagnostic(
                        DiagnosticCode("source-selection-invalid"),
                        Severity.ERROR,
                        "source configuration or organization policy changed after Review",
                        remediation=("return to Sources and review the latest values",),
                    ),
                )
            )
        return DomainOk(refreshed.value)

    def finalize(request: SourceManagementRequest) -> DomainResult[object]:
        refreshed = refreshed_configuration(request.before, request.policy)
        if isinstance(refreshed, DomainErr):
            return refreshed
        return finalize_source_management(
            request,
            # CFG02: name the exact state just revalidated, so a writer that lands between this
            # check and the replace is refused instead of silently overwritten.
            lambda desired, active_policy: save_user_configuration_checked(
                desired,
                active_policy,
                paths,
                ports,
                expected_digest=refreshed.value.observed_digest,
            ),
        )

    def finalize_addition(request: SourceAdditionRequest) -> DomainResult[object]:
        """Acquire a safe immutable snapshot before writing the new configured origin."""

        current = refreshed_configuration(request.before, request.policy)
        if isinstance(current, DomainErr):
            return current
        from .sources.runtime import sync_configured_source

        synchronized = sync_configured_source(request.source, data_root=paths.data_root)
        if isinstance(synchronized, DomainErr):
            return synchronized
        # Source fetching can take time; fail closed if config or policy changed before its write.
        after_sync = refreshed_configuration(request.before, request.policy)
        if isinstance(after_sync, DomainErr):
            return after_sync
        return finalize_source_addition(
            request,
            lambda desired, active_policy: save_user_configuration_checked(
                desired,
                active_policy,
                paths,
                ports,
                expected_digest=after_sync.value.observed_digest,
            ),
        )

    return DomainOk(_RuntimeSourceStage(projected.value, finalize, finalize_addition))


def _automatic_source_selection(view: SourceStageView) -> SourceSelection:
    aliases = tuple(row.source.alias for row in view.rows if row.source.enabled)
    planned = plan_source_management(view, aliases, no_source=not aliases)
    assert isinstance(planned, DomainOk)
    return planned.value


def _source_choice_rows(view: SourceStageView) -> Tuple[_Choice, ...]:
    rows = tuple(
        _Choice(
            "profile",
            row.source.alias.value,
            None,
            render_source_row(row),
            description=(
                "Use this source in the marketplace. "
                + (row.reason if row.reason else "Its health and policy facts are shown above.")
            ),
            enabled=row.selectable,
            reason=row.reason,
        )
        for row in view.rows
    )
    if view.allow_no_source:
        rows += (
            _Choice(
                "profile",
                "no-source",
                None,
                "Continue without sources — exit cleanly without installing artifacts.",
                description="Do not force a registry or direct source during this run.",
            ),
        )
    return rows


def _source_selection_from_indices(
    view: SourceStageView,
    indices: Sequence[int],
) -> DomainErr | SourceSelection:
    no_source_index = len(view.rows)
    no_source = view.allow_no_source and no_source_index in indices
    aliases = tuple(
        view.rows[index].source.alias for index in indices if 0 <= index < len(view.rows)
    )
    planned = plan_source_management(view, aliases, no_source=no_source)
    return planned if isinstance(planned, DomainErr) else planned.value


def _prompt_source_stage_text(
    session: WizardSession,
    view: SourceStageView,
    read: ReadFn,
    write: WriteFn,
) -> WizardInput | SourceSelection:
    write(
        "Choose enabled artifact sources. Registries are optional unless organization policy "
        "marks one as required."
    )
    choices = _source_choice_rows(view)
    for index, choice in enumerate(choices, start=1):
        write(f"  {index:>2}. {choice.label}")
    if not view.rows:
        write("No sources are configured. Enter 'a' to add a registry or compatible source.")
    else:
        write("Enter 'a' to add another registry or compatible source.")
    if view.unconfigured_recommended:
        write(
            "Organization-recommended aliases needing configuration: "
            + ", ".join(alias.value for alias in view.unconfigured_recommended)
        )
    if view.unconfigured_required:
        write(
            "Organization-required aliases needing configuration: "
            + ", ".join(alias.value for alias in view.unconfigured_required)
        )
    selected_aliases = (
        set() if session.source_selection is None else set(session.source_selection.enabled_aliases)
    )
    selected = tuple(
        index for index, row in enumerate(view.rows) if row.source.alias in selected_aliases
    )
    if session.source_selection is not None and session.source_selection.no_source:
        selected += (len(view.rows),)
    elif session.source_selection is None:
        selected = tuple(index for index, row in enumerate(view.rows) if row.source.enabled)
    write(f"Selected: {len(selected)} source option(s)")
    while True:
        event = _prompt_wizard_indices(
            read,
            write,
            "Source(s) (a=add, b=back, q=quit): ",
            choices,
            selected=selected,
            allow_add=True,
        )
        if event.kind != "confirm":
            return event
        planned = _source_selection_from_indices(view, event.selected)
        if isinstance(planned, DomainErr):
            for diagnostic in planned.diagnostics:
                write(f"{diagnostic.severity.value}: {diagnostic.message}")
            continue
        return planned


def _source_kind_choices(view: SourceStageView) -> tuple[tuple[SourceKind, str], ...]:
    choices: tuple[tuple[SourceKind, str], ...] = (
        (
            SourceKind.REGISTRY_GIT,
            "Registry Git source — reviewed marketplace with compiled lock and index.",
        ),
    )
    if view.allow_direct_sources:
        choices += (
            (
                SourceKind.SOURCE_GIT,
                "Direct Git source — any compatible native artifact repository.",
            ),
            (
                SourceKind.SOURCE_LOCAL,
                "Local source — a compatible directory on this machine.",
            ),
        )
    return choices


def _prompt_source_value(
    read: ReadFn,
    prompt: str,
    *,
    default: str | None = None,
) -> str | WizardInput:
    """Read one source-setup field without leaking blank/quit/back ambiguity into callers."""

    line = _read_line(read, prompt)
    if line is None:
        return WizardInput("quit")
    answer = line.strip()
    if answer.lower() in ("q", "quit"):
        return WizardInput("quit")
    if answer.lower() in ("b", "back"):
        return WizardInput("back")
    if not answer and default is not None:
        return default
    return answer


def _prompt_source_addition_text(
    view: SourceStageView,
    read: ReadFn,
    write: WriteFn,
) -> WizardInput | SourceAdditionRequest:
    """Collect and review one source origin before its sync-and-save runtime boundary."""

    choices = _source_kind_choices(view)
    write("Add an artifact source:")
    for index, (_kind, label) in enumerate(choices, start=1):
        write(f"  {index:>2}. {label}")
    while True:
        raw_kind = _prompt_source_value(
            read,
            "Source type (b=back, q=quit): ",
        )
        if isinstance(raw_kind, WizardInput):
            return raw_kind
        if not raw_kind.isdigit() or not 1 <= int(raw_kind) <= len(choices):
            write(f"Please enter a number between 1 and {len(choices)}, 'b', or 'q'.")
            continue
        kind = choices[int(raw_kind) - 1][0]
        default_alias = {
            SourceKind.REGISTRY_GIT: "registry",
            SourceKind.SOURCE_GIT: "source",
            SourceKind.SOURCE_LOCAL: "local",
        }[kind]
        alias = _prompt_source_value(
            read,
            f"Source alias [{default_alias}] (b=back, q=quit): ",
            default=default_alias,
        )
        if isinstance(alias, WizardInput):
            return alias
        location_label = "Local directory" if kind is SourceKind.SOURCE_LOCAL else "Git URL"
        location = _prompt_source_value(read, f"{location_label} (b=back, q=quit): ")
        if isinstance(location, WizardInput):
            return location
        if not location:
            write(f"{location_label} is required.")
            continue
        ref: str | None = None
        if kind is not SourceKind.SOURCE_LOCAL:
            prompted_ref = _prompt_source_value(
                read,
                "Git ref [main] (b=back, q=quit): ",
                default="main",
            )
            if isinstance(prompted_ref, WizardInput):
                return prompted_ref
            ref = prompted_ref
        parsed = configured_source_from_input(alias, kind, location, ref)
        if isinstance(parsed, DomainErr):
            _write_domain_diagnostics(parsed, write)
            continue
        planned = plan_source_addition(
            view,
            parsed.value,
            make_default=not any(row.source.is_registry for row in view.rows),
        )
        if isinstance(planned, DomainErr):
            _write_domain_diagnostics(planned, write)
            continue
        for line in render_source_addition_review(planned.value):
            write(line)
        answer = _read_line(
            read,
            "Synchronize and save this source? [y/N] (b=back, q=quit): ",
        )
        choice = "q" if answer is None else answer.strip().lower()
        if choice in ("b", "back"):
            return WizardInput("back")
        if choice in ("q", "quit"):
            return WizardInput("quit")
        if choice in ("y", "yes", "f", "finalize"):
            return planned.value
        write("Source setup was not finalized; no source was synchronized or saved.")
        return WizardInput("back")


def _selected_legacy_source_arguments(
    view: SourceStageView,
    selection: SourceSelection,
    *,
    source_dir: Optional[str],
    repo: Optional[str],
) -> DomainResult[Tuple[Optional[str], Optional[str]]]:
    """Bridge one selected source to the 0.1 command core until TUI02 owns source unions."""

    if len(selection.enabled_aliases) != 1:
        return DomainErr(
            (
                Diagnostic(
                    DiagnosticCode("source-selection-invalid"),
                    Severity.ERROR,
                    "the current consumer view accepts one source; select one source before "
                    "continuing to artifact choices",
                    remediation=("use aart source commands to manage the wider source set",),
                ),
            )
        )
    selected = selection.enabled_aliases[0]
    row = next((row for row in view.rows if row.source.alias == selected), None)
    if row is None:
        return DomainErr(
            (
                Diagnostic(
                    DiagnosticCode("source-selection-invalid"),
                    Severity.ERROR,
                    "selected source is absent from the reviewed source view",
                ),
            )
        )
    if row.source.kind is SourceKind.SOURCE_LOCAL:
        return DomainOk((row.source.location, None))
    if row.source.kind is SourceKind.REGISTRY_GIT:
        return DomainErr(
            (
                Diagnostic(
                    DiagnosticCode("source-incompatible"),
                    Severity.ERROR,
                    f"registry {selected} is ready for source management, but artifact browsing "
                    "requires the federated marketplace view",
                ),
            )
        )
    parts = git_location_parts(row.source.location)
    if parts is not None and parts[0] == "github.com" and row.source.ref == "main":
        return DomainOk((None, parts[1]))
    return DomainErr(
        (
            Diagnostic(
                DiagnosticCode("source-incompatible"),
                Severity.ERROR,
                f"source {selected} requires its managed snapshot before this consumer view can "
                "open its Git host",
                remediation=("sync the source and retry",),
            ),
        )
    )


def _finalize_source_selection(
    session: WizardSession,
    source_finalizer: Optional[SourceFinalizeFn],
    write: WriteFn,
) -> Optional[int]:
    selected = session.source_selection
    if selected is None or not selected.request.operations:
        return None
    if source_finalizer is None:
        write("error: source configuration cannot be saved by this TUI runtime")
        write("No artifact action was dispatched.")
        return 2
    finalized = source_finalizer(selected.request)
    if isinstance(finalized, DomainErr):
        for diagnostic in finalized.diagnostics:
            write(f"{diagnostic.severity.value}: {diagnostic.message}")
        write("No artifact action was dispatched.")
        return 2
    count = len(selected.request.operations)
    write(f"Sources: applied {count} reviewed configuration change(s).")
    return None


@dataclass(frozen=True, slots=True)
class _UserWizardReadModel:
    catalog: Catalog
    manifest: Optional[Manifest]
    choices: Tuple[_Choice, ...]
    profiles_map: Mapping[str, Profile]
    source_label: str = ""
    source_root: str = ""
    marketplace_rows: Tuple[MarketplaceArtifactRow, ...] = ()


def _basket_key(choice: _Choice) -> str:
    if choice.qualified_key:
        return choice.qualified_key
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


def _canonical_choice(row: MarketplaceArtifactRow) -> _Choice:
    providers = ", ".join(row.security.provider_versions) or "none"
    evidence_age = (
        "unknown"
        if row.security.evidence_age_seconds is None
        else f"{row.security.evidence_age_seconds}s"
    )
    remediation = "; ".join(row.security.remediation) or "none"
    details = (
        f"{row.summary} Source {row.source_alias} at {row.source_revision}; trust {row.trust}; "
        f"security {row.security.installation_risk} ({row.security.assessment_status}), max severity "
        f"{row.security.max_finding_severity}, coverage "
        f"{row.security.coverage_completed}/{row.security.coverage_expected}, providers {providers}, "
        f"evidence age {evidence_age}, remediation {remediation}; manifest {row.manifest_digest}; "
        f"payload {row.payload_digest}; object {row.object_digest}."
    )
    if row.reasons:
        details += " Compatibility: " + "; ".join(reason.message for reason in row.reasons)
    return _Choice(
        "artifact",
        row.identity.name,
        row.identity.kind,  # type: ignore[arg-type]
        render_marketplace_row(row),
        description=details,
        enabled=row.compatible,
        reason="; ".join(reason.message for reason in row.reasons),
        linked_count=sum(mode == "symlink" for mode in row.actual_modes),
        copied_count=sum(mode == "copy" for mode in row.actual_modes),
        qualified_key=row.key,
    )


def _canonical_collection_choices(
    catalog: MarketplaceCatalog,
    rows: Tuple[MarketplaceArtifactRow, ...],
    *,
    sources: Tuple[SourceAlias, ...] = (),
) -> Tuple[_Choice, ...]:
    by_coordinate = {row.coordinate: row for row in rows}
    selected_sources = frozenset(sources)
    choices = []
    for collection in catalog.collections:
        if selected_sources and collection.coordinate.source not in selected_sources:
            continue
        member_rows = tuple(by_coordinate.get(member) for member in collection.members)
        missing = sum(row is None for row in member_rows)
        available = tuple(row for row in member_rows if row is not None)
        reasons = tuple(sorted({reason.message for row in available for reason in row.reasons}))
        enabled = missing == 0 and all(row.compatible for row in available)
        reason_parts = []
        if missing:
            reason_parts.append(f"{missing} member(s) unavailable")
        reason_parts.extend(reasons)
        reason = "; ".join(reason_parts)
        status = "" if enabled else f" — unavailable: {reason}"
        members = ", ".join(str(member) for member in collection.members)
        choices.append(
            _Choice(
                "bundle",
                collection.coordinate.name,
                None,
                f"[collection] {collection.coordinate} — {collection.summary} "
                f"({len(collection.members)} members){status}",
                description=f"{collection.summary} Members: {members}.",
                enabled=enabled,
                reason=reason,
                linked_count=sum("symlink" in row.actual_modes for row in available),
                copied_count=sum("copy" in row.actual_modes for row in available),
                qualified_key=str(collection.coordinate),
            )
        )
    return tuple(choices)


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
    allow_add: bool = False,
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
        if allow_add and low in ("a", "add"):
            return WizardInput("add")
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
    consumer_service: Optional[ConsumerApplicationService] = None,
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
    if consumer_service is not None:
        selected_sources = (
            () if session.source_selection is None else session.source_selection.enabled_aliases
        )
        projected = consumer_service.browse(
            MarketplaceTarget(
                tuple(sorted(session.profiles)),
                "darwin" if sys.platform == "darwin" else "linux",
                scope,  # type: ignore[arg-type]
                session.install_mode,  # type: ignore[arg-type]
            ),
            sources=selected_sources,
        )
        if isinstance(projected, DomainErr):
            return Err("; ".join(item.message for item in projected.diagnostics), code=2)
        rows = projected.value
        if session.action in ("update", "uninstall"):
            rows = tuple(row for row in rows if row.installed)
        choices = tuple(_canonical_choice(row) for row in rows)
        if session.action == "install":
            choices += _canonical_collection_choices(
                consumer_service.context.catalog,
                rows,
                sources=selected_sources,
            )
        return _UserWizardReadModel(
            Catalog(artifacts={}, bundles={}),
            None,
            choices,
            profiles_map,
            "federated configured marketplace",
            consumer_service.context.store_paths.root,
            rows,
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
    source_finalizer: Optional[SourceFinalizeFn] = None,
    consumer_service: Optional[ConsumerApplicationService] = None,
    reporting_service: Optional[ReportingApplicationService] = None,
) -> int | WizardSession:
    read_model: Optional[_UserWizardReadModel] = None
    read_key: Optional[tuple] = None
    profile_names = tuple(sorted(load_profiles(project)))
    while True:
        if session.current in ("role", "source", "maintainer_action"):
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
                    consumer_service=consumer_service,
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
            canonical_review: Optional[ConsumerReview] = None
            if consumer_service is not None:
                coordinates: tuple = ()
                if read_model is not None:
                    selected_keys = {item.key for item in session.basket}
                    selected_coordinates = {
                        row.coordinate
                        for row in read_model.marketplace_rows
                        if row.key in selected_keys
                    }
                    for collection in consumer_service.context.catalog.collections:
                        if str(collection.coordinate) in selected_keys:
                            selected_coordinates.update(collection.members)
                    coordinates = tuple(sorted(selected_coordinates, key=str))
                prepared = consumer_service.prepare(
                    ConsumerActionRequest(
                        session.action or "status",  # type: ignore[arg-type]
                        coordinates,
                        tuple(sorted(session.profiles)),
                        session.scope,  # type: ignore[arg-type]
                        session.install_mode,  # type: ignore[arg-type]
                    )
                )
                if isinstance(prepared, DomainErr):
                    for diagnostic in prepared.diagnostics:
                        write(f"{diagnostic.severity.value}: {diagnostic.message}")
                    return 2
                canonical_review = prepared.value
                for line in render_consumer_review(canonical_review):
                    write(line)
            elif session.action == "install":
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
            source_code = _finalize_source_selection(session, source_finalizer, write)
            if source_code is not None:
                return source_code
            if canonical_review is not None:
                finalized = consumer_service.finalize(  # type: ignore[union-attr]
                    canonical_review,
                    canonical_review.review_digest,
                )
                if isinstance(finalized, DomainErr):
                    for diagnostic in finalized.diagnostics:
                        write(f"{diagnostic.severity.value}: {diagnostic.message}")
                    return 2
                for line in render_consumer_outcome(finalized.value):
                    write(line)
                return _complete_canonical_consumer_action(
                    consumer_service,  # type: ignore[arg-type]
                    canonical_review,
                    finalized.value,
                    reporting_service,
                    read=read,
                    write=write,
                )
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
    source_stage_view: Optional[SourceStageView] = None,
    source_finalizer: Optional[SourceFinalizeFn] = None,
    source_addition_finalizer: Optional[SourceAdditionFinalizeFn] = None,
    source_stage_loader: Optional[SourceStageLoader] = None,
    consumer_service: Optional[ConsumerApplicationService] = None,
    consumer_service_factory: Optional[ConsumerServiceFactory] = None,
    reporting_service: Optional[ReportingApplicationService] = None,
    reporting_service_factory: Optional[ReportingServiceFactory] = None,
    curation_service_factory: Optional[CurationServiceFactory] = None,
) -> int:
    """Persistent onboarding/role wizard shared by the fallback and headless tests."""

    session = initial_session()
    buffered_role: Optional[str] = None
    legacy_source_dir = source_dir
    legacy_repo = repo
    stage_view = source_stage_view or (
        _legacy_source_stage_view(source_dir=source_dir, repo=repo)
        if source_dir is not None or repo is not None
        else _empty_source_stage_view()
    )
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
            continue
        if session.current == "source":
            if source_stage_view is None and (source_dir is not None or repo is not None):
                selected_source: WizardInput | SourceSelection = _automatic_source_selection(
                    stage_view
                )
            else:
                _write_wizard_header(session, write)
                selected_source = _prompt_source_stage_text(session, stage_view, read, write)
            if isinstance(selected_source, WizardInput):
                if selected_source.kind == "back":
                    session = wizard_back(session)
                elif selected_source.kind == "add":
                    if source_addition_finalizer is None or source_stage_loader is None:
                        write("error: source setup is unavailable in this TUI runtime")
                        continue
                    addition = _prompt_source_addition_text(stage_view, read, write)
                    if isinstance(addition, WizardInput):
                        if addition.kind == "quit" and _confirm_wizard_quit(session, read, write):
                            return _cancel(write)
                        continue
                    finalized_addition = source_addition_finalizer(addition)
                    if isinstance(finalized_addition, DomainErr):
                        _write_domain_diagnostics(finalized_addition, write)
                        write("Source was not saved; choose another source or retry setup.")
                        continue
                    refreshed = source_stage_loader()
                    if isinstance(refreshed, DomainErr):
                        _write_domain_diagnostics(refreshed, write)
                        write("Source was saved but the Sources screen could not be refreshed.")
                        continue
                    stage_view = refreshed.value.view
                    source_finalizer = refreshed.value.source_finalizer
                    source_addition_finalizer = refreshed.value.source_addition_finalizer
                    session = replace(
                        session,
                        source_selection=None,
                        revision=session.revision + 1,
                    )
                    write(
                        f"Sources: synchronized and saved {addition.source.alias}. "
                        "Choose enabled source(s) to continue."
                    )
                elif _confirm_wizard_quit(session, read, write):
                    return _cancel(write)
                continue
            session = wizard_select(session, "source", selected_source)
            session = wizard_advance(session)
            if selected_source.no_source:
                return _cancel(
                    write,
                    "No sources selected; no registry was forced and no changes were made.",
                )
            active_consumer_service = consumer_service
            active_reporting_service = reporting_service
            if consumer_service_factory is not None and session.role == "user":
                loaded_consumer = consumer_service_factory(selected_source.request.after)
                if isinstance(loaded_consumer, DomainErr):
                    for diagnostic in loaded_consumer.diagnostics:
                        write(f"{diagnostic.severity.value}: {diagnostic.message}")
                    session = wizard_back(session)
                    continue
                active_consumer_service = loaded_consumer.value
            if reporting_service_factory is not None and session.role == "user":
                loaded_reporting = reporting_service_factory(selected_source.request.after)
                if isinstance(loaded_reporting, DomainErr):
                    write(
                        "warning: usage reporting is unavailable; artifact installation remains "
                        "available"
                    )
                    active_reporting_service = None
                else:
                    active_reporting_service = loaded_reporting.value
            if active_consumer_service is None or session.role != "user":
                source_arguments = _selected_legacy_source_arguments(
                    stage_view,
                    selected_source,
                    source_dir=legacy_source_dir,
                    repo=legacy_repo,
                )
                if isinstance(source_arguments, DomainErr):
                    for diagnostic in source_arguments.diagnostics:
                        write(f"{diagnostic.severity.value}: {diagnostic.message}")
                    session = wizard_back(session)
                    continue
                source_dir, repo = source_arguments.value
            if session.role == "user":
                result = _run_user_text_wizard(
                    session,
                    read,
                    write,
                    source_factory=source_factory,
                    source_dir=source_dir,
                    repo=repo,
                    project=project,
                    user_home=user_home,
                    source_finalizer=source_finalizer,
                    consumer_service=active_consumer_service,
                    reporting_service=active_reporting_service,
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
                user_home=user_home,
                source_finalizer=source_finalizer,
                consumer_service_factory=consumer_service_factory,
                reporting_service_factory=reporting_service_factory,
                consumer_configuration=selected_source.request.after,
                curation_service_factory=curation_service_factory,
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


def _is_canonical_maintainer_workspace(root: str) -> bool:
    """Recognize a registry or an empty Git checkout without reclassifying legacy catalogs."""

    if os.path.isfile(os.path.join(root, "aart-registry.json")):
        return True
    git = os.path.join(root, ".git")
    if not (os.path.isdir(git) or os.path.isfile(git)):
        return False
    legacy_markers = (
        "bundles.json",
        "upstreams.json",
        "skills",
        "guidelines",
        "mcp",
        "hooks",
        "memory",
    )
    return not any(os.path.exists(os.path.join(root, marker)) for marker in legacy_markers)


def _default_curation_service_factory(root: str) -> DomainResult[CurationService]:
    from .curation.runtime import load_local_curation_service

    return load_local_curation_service(root)


def _write_domain_diagnostics(result: DomainErr, write: WriteFn) -> None:
    for diagnostic in result.diagnostics:
        write(f"{diagnostic.severity.value}: {diagnostic.message}")
        for remediation in diagnostic.remediation:
            write(f"  remediation: {remediation}")


def _prompt_wizard_csv(
    read: ReadFn,
    write: WriteFn,
    prompt: str,
    *,
    current: Tuple[str, ...] = (),
    default: Tuple[str, ...] = (),
) -> Tuple[str, ...] | WizardInput:
    while True:
        line = _read_line(read, prompt)
        if line is None:
            return WizardInput("quit")
        answer = line.strip()
        if answer.lower() in ("q", "quit"):
            return WizardInput("quit")
        if answer.lower() in ("b", "back"):
            return WizardInput("back")
        if not answer:
            return current or default
        values = tuple(item.strip() for item in answer.split(",") if item.strip())
        if values:
            return values
        write("Enter one or more comma-separated values, 'b' to go back, or 'q' to quit.")


def _prompt_curation_request(
    action: CurationAction,
    workspace: str,
    read: ReadFn,
    write: WriteFn,
    *,
    existing: Optional[CurationRequest],
) -> CurationRequest | WizardInput:
    def value(
        prompt: str,
        field: str,
        *,
        required: bool = True,
        default: Optional[str] = None,
    ) -> str | None | WizardInput:
        current = getattr(existing, field) if existing is not None else default
        return _prompt_wizard_value(
            read,
            write,
            prompt,
            current=current,
            required=required,
        )

    if action is CurationAction.INIT:
        source_id = value("Registry/source ID: ", "source_id")
        if isinstance(source_id, WizardInput):
            return source_id
        display_name = value("Registry display name: ", "display_name")
        if isinstance(display_name, WizardInput):
            return display_name
        minimum = value("Minimum AART version [1.0.0]: ", "minimum_version", default="1.0.0")
        if isinstance(minimum, WizardInput):
            return minimum
        maximum = value(
            "Maximum AART version (exclusive) [2.0.0]: ", "maximum_version", default="2.0.0"
        )
        if isinstance(maximum, WizardInput):
            return maximum
        return CurationRequest(
            action,
            workspace,
            source_id=source_id,
            display_name=display_name,
            minimum_version=minimum or "1.0.0",
            maximum_version=maximum or "2.0.0",
        )

    if action is CurationAction.SCAFFOLD:
        kind = value("Artifact kind (skill/guideline/mcp/hook/memory): ", "kind")
        if isinstance(kind, WizardInput):
            return kind
        name = value("Artifact name: ", "name")
        if isinstance(name, WizardInput):
            return name
        summary = value("One-line value description: ", "summary")
        if isinstance(summary, WizardInput):
            return summary
        version = value("Artifact version [1.0.0]: ", "artifact_version", default="1.0.0")
        if isinstance(version, WizardInput):
            return version
        profiles = _prompt_wizard_csv(
            read,
            write,
            "Harness profiles (comma-separated): ",
            current=existing.profiles if existing else (),
        )
        if isinstance(profiles, WizardInput):
            return profiles
        platforms = _prompt_wizard_csv(
            read,
            write,
            "Platforms (comma-separated): ",
            current=existing.platforms if existing else (),
        )
        if isinstance(platforms, WizardInput):
            return platforms
        scopes = _prompt_wizard_csv(
            read,
            write,
            "Install scopes [project]: ",
            current=existing.scopes if existing else (),
            default=("project",),
        )
        if isinstance(scopes, WizardInput):
            return scopes
        modes = _prompt_wizard_csv(
            read,
            write,
            "Install modes [copy]: ",
            current=existing.modes if existing else (),
            default=("copy",),
        )
        if isinstance(modes, WizardInput):
            return modes
        return CurationRequest(
            action,
            workspace,
            kind=kind,
            name=name,
            summary=summary,
            artifact_version=version or "1.0.0",
            profiles=profiles,
            platforms=platforms,
            scopes=scopes,
            modes=modes,
        )

    if action is CurationAction.PROMOTE_NATIVE:
        kind = value("Artifact kind: ", "kind")
        if isinstance(kind, WizardInput):
            return kind
        name = value("Artifact name: ", "name")
        if isinstance(name, WizardInput):
            return name
        url = value("Credential-free Git URL: ", "url")
        if isinstance(url, WizardInput):
            return url
        ref = value("Git ref [main]: ", "ref", default="main")
        if isinstance(ref, WizardInput):
            return ref
        path = value("Canonical package path: ", "path")
        if isinstance(path, WizardInput):
            return path
        policy = value(
            "Review policy [manual-review-v1]: ",
            "review_policy",
            default="manual-review-v1",
        )
        if isinstance(policy, WizardInput):
            return policy
        return CurationRequest(
            action,
            workspace,
            kind=kind,
            name=name,
            url=url,
            ref=ref or "main",
            path=path,
            review_policy=policy or "manual-review-v1",
        )

    if action is CurationAction.UPDATE_UPSTREAM:
        kind = value("Locked artifact kind: ", "kind")
        if isinstance(kind, WizardInput):
            return kind
        name = value("Locked artifact name: ", "name")
        if isinstance(name, WizardInput):
            return name
        return CurationRequest(action, workspace, kind=kind, name=name)

    if action is CurationAction.IMPORT_FOREIGN:
        legacy = value("Pinned legacy Git URL or local checkout: ", "legacy_source")
        if isinstance(legacy, WizardInput):
            return legacy
        origin = value(
            "Origin URL for a local checkout (blank for remote): ",
            "origin_url",
            required=False,
        )
        if isinstance(origin, WizardInput):
            return origin
        ref = value("Legacy Git ref [HEAD]: ", "ref", default="HEAD")
        if isinstance(ref, WizardInput):
            return ref
        source_id = value("New registry/source ID: ", "source_id")
        if isinstance(source_id, WizardInput):
            return source_id
        display_name = value("New registry display name: ", "display_name")
        if isinstance(display_name, WizardInput):
            return display_name
        version = value("Imported artifact version [1.0.0]: ", "artifact_version", default="1.0.0")
        if isinstance(version, WizardInput):
            return version
        profiles = _prompt_wizard_csv(
            read,
            write,
            "Harness profiles (comma-separated): ",
            current=existing.profiles if existing else (),
        )
        if isinstance(profiles, WizardInput):
            return profiles
        platforms = _prompt_wizard_csv(
            read,
            write,
            "Platforms [darwin]: ",
            current=existing.platforms if existing else (),
            default=("darwin",),
        )
        if isinstance(platforms, WizardInput):
            return platforms
        return CurationRequest(
            action,
            workspace,
            legacy_source=legacy,
            origin_url=origin,
            ref=ref or "HEAD",
            source_id=source_id,
            display_name=display_name,
            artifact_version=version or "1.0.0",
            profiles=profiles,
            platforms=platforms,
        )

    return CurationRequest(action, workspace)


def _run_canonical_maintainer_text(
    session: WizardSession,
    read: ReadFn,
    write: WriteFn,
    *,
    workspace: str,
    project: Optional[str],
    user_home: Optional[str],
    source_finalizer: Optional[SourceFinalizeFn],
    consumer_service_factory: Optional[ConsumerServiceFactory],
    reporting_service_factory: Optional[ReportingServiceFactory],
    consumer_configuration: Optional[UserConfiguration],
    curation_service_factory: Optional[CurationServiceFactory],
) -> int | WizardSession:
    factory = curation_service_factory or _default_curation_service_factory
    loaded = factory(workspace)
    if isinstance(loaded, DomainErr):
        _write_domain_diagnostics(loaded, write)
        return 2
    service = loaded.value
    request: Optional[CurationRequest] = None
    prepared: Optional[PreparedCuration] = None
    while True:
        if session.current == "role":
            return session
        _write_wizard_header(session, write)
        if session.current == "maintainer_action":
            write(f"Canonical registry checkout: {workspace}")
            write("Maintainer action:")
            for index, (_action, label) in enumerate(CANONICAL_MAINTAINER_ACTIONS, start=1):
                write(f"  {index:>2}. {label}")
            selected = _prompt_maintainer_action_wizard(
                read,
                write,
                CANONICAL_MAINTAINER_ACTIONS,
            )
            if isinstance(selected, WizardInput):
                if selected.kind == "back":
                    return wizard_back(session)
                return _cancel(write)
            session = replace(session, basket=(), notices=())
            session = wizard_select(session, "maintainer_action", selected)
            session = wizard_advance(session)
            request = None
            prepared = None
            if selected == "user":
                consumer_service: Optional[ConsumerApplicationService] = None
                reporting_service: Optional[ReportingApplicationService] = None
                active_consumer_factory = consumer_service_factory
                if active_consumer_factory is None and consumer_configuration is not None:
                    from .consumer.runtime import load_local_consumer_service

                    def active_consumer_factory(
                        configuration: UserConfiguration,
                    ) -> DomainResult[ConsumerApplicationService]:
                        return load_local_consumer_service(
                            project=project,
                            user_home=user_home,
                            configuration=configuration,
                        )

                if active_consumer_factory is not None and consumer_configuration is not None:
                    loaded_consumer = active_consumer_factory(consumer_configuration)
                    if isinstance(loaded_consumer, DomainErr):
                        _write_domain_diagnostics(loaded_consumer, write)
                        session = wizard_back(session)
                        continue
                    consumer_service = loaded_consumer.value
                if reporting_service_factory is not None and consumer_configuration is not None:
                    loaded_reporting = reporting_service_factory(consumer_configuration)
                    if isinstance(loaded_reporting, DomainErr):
                        write(
                            "warning: usage reporting is unavailable; artifact installation "
                            "remains available"
                        )
                    else:
                        reporting_service = loaded_reporting.value
                result = _run_user_text_wizard(
                    session,
                    read,
                    write,
                    source_factory=open_source,
                    source_dir=workspace,
                    repo=None,
                    project=project,
                    user_home=user_home,
                    source_finalizer=source_finalizer,
                    consumer_service=consumer_service,
                    reporting_service=reporting_service,
                )
                if isinstance(result, WizardSession):
                    session = result
                    continue
                return result
            continue

        action_name = session.maintainer_action
        assert action_name is not None and action_name != "user"
        action = CurationAction(action_name)
        if session.current == "upstream_details":
            previous_request = request
            try:
                prompted = _prompt_curation_request(
                    action,
                    workspace,
                    read,
                    write,
                    existing=request,
                )
            except ValueError as error:
                write(f"error: {error}")
                continue
            if isinstance(prompted, WizardInput):
                if prompted.kind == "back":
                    session = wizard_back(session)
                    continue
                if _confirm_wizard_quit(session, read, write):
                    return _cancel(write)
                continue
            request = prompted
            label = (
                f"{request.kind}/{request.name}"
                if request.kind is not None and request.name is not None
                else action.value
            )
            session = replace(
                session,
                basket=(BasketItem("upstream", label, label),),
                revision=session.revision + 1,
            )
            session = wizard_advance(session)
            if request != previous_request:
                prepared = None
            continue

        if session.current != "review":
            return 2
        if request is None:
            request = CurationRequest(action, workspace)
        if prepared is None:
            planned = service.prepare(request)
            if isinstance(planned, DomainErr):
                _write_domain_diagnostics(planned, write)
                write("Preview failed; no registry changes were applied.")
                return 2
            prepared = planned.value
        for line in render_curation_review(prepared.review):
            write(line)
        finalized_line = _read_line(
            read, "Finalize exact reviewed action? [y/N] (b=back, q=quit): "
        )
        answer = "q" if finalized_line is None else finalized_line.strip().lower()
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
        source_code = _finalize_source_selection(session, source_finalizer, write)
        if source_code is not None:
            return source_code
        finalized = service.finalize(prepared, prepared.review.review_digest)
        if isinstance(finalized, DomainErr):
            _write_domain_diagnostics(finalized, write)
            write("Finalize failed; use the remediation above and rerun the same reviewed action.")
            return 2
        for rendered in render_curation_outcome(finalized.value):
            write(rendered)
        return 2 if finalized.value.status == "failed" else 0


def _run_maintainer_text(
    session: WizardSession,
    read: ReadFn,
    write: WriteFn,
    *,
    source_factory: SourceFactory,
    source_dir: Optional[str],
    repo: Optional[str],
    project: Optional[str],
    user_home: Optional[str] = None,
    source_finalizer: Optional[SourceFinalizeFn] = None,
    consumer_service_factory: Optional[ConsumerServiceFactory] = None,
    reporting_service_factory: Optional[ReportingServiceFactory] = None,
    consumer_configuration: Optional[UserConfiguration] = None,
    curation_service_factory: Optional[CurationServiceFactory] = None,
) -> int | WizardSession:
    """Drive Maintainer stages and expose apply only at the Review Finalize boundary."""
    del source_factory  # maintainer source resolution belongs to the upstream command core
    from .commands import upstream

    catalog_root = os.path.abspath(source_dir or ".")
    if _is_canonical_maintainer_workspace(catalog_root):
        return _run_canonical_maintainer_text(
            session,
            read,
            write,
            workspace=catalog_root,
            project=project,
            user_home=user_home,
            source_finalizer=source_finalizer,
            consumer_service_factory=consumer_service_factory,
            reporting_service_factory=reporting_service_factory,
            consumer_configuration=consumer_configuration,
            curation_service_factory=curation_service_factory,
        )
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
                consumer_service: Optional[ConsumerApplicationService] = None
                reporting_service: Optional[ReportingApplicationService] = None
                if consumer_service_factory is not None and consumer_configuration is not None:
                    loaded_consumer = consumer_service_factory(consumer_configuration)
                    if isinstance(loaded_consumer, DomainErr):
                        for diagnostic in loaded_consumer.diagnostics:
                            write(f"{diagnostic.severity.value}: {diagnostic.message}")
                        session = wizard_back(session)
                        continue
                    consumer_service = loaded_consumer.value
                if reporting_service_factory is not None and consumer_configuration is not None:
                    loaded_reporting = reporting_service_factory(consumer_configuration)
                    if isinstance(loaded_reporting, DomainErr):
                        write(
                            "warning: usage reporting is unavailable; artifact installation "
                            "remains available"
                        )
                    else:
                        reporting_service = loaded_reporting.value
                result = _run_user_text_wizard(
                    session,
                    read,
                    write,
                    source_factory=open_source,
                    source_dir=source_dir,
                    repo=repo,
                    project=project,
                    user_home=user_home,
                    source_finalizer=source_finalizer,
                    consumer_service=consumer_service,
                    reporting_service=reporting_service,
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
        source_code = _finalize_source_selection(session, source_finalizer, write)
        if source_code is not None:
            return source_code
        if is_mutation:
            return _apply_maintainer_mutation(request, write)
        return _dispatch(request)


def _prompt_maintainer_action_wizard(
    read: ReadFn,
    write: WriteFn,
    actions: Tuple[Tuple[str, str], ...] = MAINTAINER_ACTIONS,
) -> str | WizardInput:
    while True:
        line = _read_line(read, "Maintainer action (b=back, q=quit): ")
        if line is None:
            return WizardInput("quit")
        answer = line.strip().lower()
        if answer in ("q", "quit"):
            return WizardInput("quit")
        if answer in ("b", "back"):
            return WizardInput("back")
        by_name = {name: name for name, _label in actions}
        if answer in by_name:
            return by_name[answer]
        if answer.isdigit() and 1 <= int(answer) <= len(actions):
            return actions[int(answer) - 1][0]
        write(f"Please enter 1-{len(actions)}, 'b', or 'q'.")


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
    allow_add: bool = False,
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
            allow_add=allow_add,
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


def _curses_empty_source_event(curses, stdscr, session: WizardSession) -> WizardInput:
    """Keep source onboarding navigable when policy leaves no selectable source rows.

    A required source may be named by policy before the user has configured its origin.  There
    is deliberately no synthetic, untrusted row to toggle in that case; ``a`` remains the only
    productive action.  This has a dedicated screen rather than relying on the generic checkbox
    widget, whose empty-list result is a confirmation with no selection.
    """

    required = ("clear", "addstr", "refresh", "getch")
    if not all(hasattr(stdscr, name) for name in required):
        return WizardInput("quit")
    backspace = {getattr(curses, "KEY_BACKSPACE", -1), 127, 8}
    lines = _curses_header(stdscr, session) + (
        "Sources",
        "No sources are configured.",
        "Press a to add a source, Backspace to return, or q to quit.",
    )
    while True:
        stdscr.clear()
        available = max(_width(stdscr) - 1, 0)
        for row, line in enumerate(lines[: _height(stdscr)]):
            stdscr.addstr(row, 0, _ellipsize(line, available))
        stdscr.refresh()
        key = stdscr.getch()
        if key in (ord("a"), ord("A")):
            return WizardInput("add")
        if key in (ord("q"), 27):
            return WizardInput("quit")
        if key in backspace:
            return WizardInput("back")


def _curses_source_event(
    curses,
    stdscr,
    session: WizardSession,
    view: SourceStageView,
) -> Tuple[WizardInput, Optional[SourceSelection], Optional[DomainErr]]:
    choices = _source_choice_rows(view)
    if not choices:
        return _curses_empty_source_event(curses, stdscr, session), None, None
    selected_aliases = (
        set() if session.source_selection is None else set(session.source_selection.enabled_aliases)
    )
    selected = tuple(
        index for index, row in enumerate(view.rows) if row.source.alias in selected_aliases
    )
    if session.source_selection is not None and session.source_selection.no_source:
        selected += (len(view.rows),)
    elif session.source_selection is None:
        selected = tuple(index for index, row in enumerate(view.rows) if row.source.enabled)
    missing = view.unconfigured_required or view.unconfigured_recommended
    suffix = "" if not missing else " — configure: " + ", ".join(item.value for item in missing)
    event = _curses_multi_event(
        curses,
        stdscr,
        f"Sources{suffix}",
        tuple(choice.label for choice in choices),
        session,
        selected=selected,
        details=tuple(choice.description for choice in choices),
        disabled=tuple(not choice.enabled for choice in choices),
        allow_add=True,
    )
    if event.kind != "confirm":
        return event, None, None
    planned = _source_selection_from_indices(view, event.selected)
    if isinstance(planned, DomainErr):
        return event, None, planned
    return event, planned, None


def _curses_text_input(
    curses,
    stdscr,
    session: WizardSession,
    prompt: str,
    *,
    default: str | None = None,
    maximum_length: int = 512,
) -> str | WizardInput:
    """Collect one bounded printable source field without leaving the full-screen wizard."""

    required = ("clear", "addstr", "refresh", "getch")
    if not all(hasattr(stdscr, name) for name in required):
        return WizardInput("quit")
    buffer = ""
    backspace = {getattr(curses, "KEY_BACKSPACE", -1), 127, 8}
    enter = {getattr(curses, "KEY_ENTER", -1), 10, 13}
    while True:
        stdscr.clear()
        available = max(_width(stdscr) - 1, 1)
        lines = _curses_header(stdscr, session) + (prompt,)
        for row, line in enumerate(lines):
            if row >= max(_height(stdscr) - 2, 0):
                break
            stdscr.addstr(row, 0, _ellipsize(line, available))
        input_row = min(len(lines) + 1, max(_height(stdscr) - 2, 0))
        shown = buffer or ("" if default is None else f"[{default}]")
        stdscr.addstr(input_row, 0, _ellipsize(f"> {shown}", available))
        if _height(stdscr) > 0:
            stdscr.addstr(
                _height(stdscr) - 1,
                0,
                status_bar(
                    (
                        ("enter", "continue"),
                        ("backspace", "back when empty"),
                        ("q", "quit when empty"),
                    ),
                    width=available,
                ),
            )
        stdscr.refresh()
        key = stdscr.getch()
        if key in enter:
            return buffer or (default or "")
        if key in backspace:
            if buffer:
                buffer = buffer[:-1]
            else:
                return WizardInput("back")
            continue
        if key in (27,) or (key in (ord("q"), ord("Q")) and not buffer):
            return WizardInput("quit")
        if 32 <= key <= 126 and len(buffer) < maximum_length:
            buffer += chr(key)


def _curses_notice(
    stdscr,
    session: WizardSession,
    title: str,
    lines: Sequence[str],
) -> None:
    """Show one bounded source-flow outcome before returning to the Sources stage.

    Curses has no scrollback after a form closes.  A short acknowledgement keeps parser,
    policy, sync, and success outcomes observable instead of silently dropping the user back at
    the checkbox list.
    """

    required = ("clear", "addstr", "refresh", "getch")
    if not all(hasattr(stdscr, name) for name in required):
        return
    content = _curses_header(stdscr, session) + (title, *lines)
    available = max(_width(stdscr) - 1, 1)
    stdscr.clear()
    for row, line in enumerate(content[: max(_height(stdscr) - 1, 0)]):
        stdscr.addstr(row, 0, _ellipsize(line, available))
    if _height(stdscr) > 0:
        stdscr.addstr(_height(stdscr) - 1, 0, _ellipsize("Press any key to continue.", available))
    stdscr.refresh()
    stdscr.getch()


def _source_addition_diagnostics(result: DomainErr) -> tuple[str, ...]:
    return tuple(
        f"{diagnostic.severity.value}: {diagnostic.message}" for diagnostic in result.diagnostics
    )


def _curses_source_addition_review(
    curses,
    stdscr,
    session: WizardSession,
    request: SourceAdditionRequest,
) -> bool | WizardInput:
    """Confirm the exact source-only effect before network acquisition and config persistence."""

    required = ("clear", "addstr", "refresh", "getch")
    if not all(hasattr(stdscr, name) for name in required):
        return WizardInput("quit")
    lines = _curses_header(stdscr, session) + render_source_addition_review(request)
    available = max(_width(stdscr) - 1, 1)
    backspace = {getattr(curses, "KEY_BACKSPACE", -1), 127, 8}
    enter = {getattr(curses, "KEY_ENTER", -1), 10, 13}
    while True:
        stdscr.clear()
        for row, line in enumerate(lines[: max(_height(stdscr) - 1, 0)]):
            stdscr.addstr(row, 0, _ellipsize(line, available))
        if _height(stdscr) > 0:
            stdscr.addstr(
                _height(stdscr) - 1,
                0,
                status_bar(
                    (("enter", "save"), ("b", "back"), ("q", "quit")),
                    width=available,
                ),
            )
        stdscr.refresh()
        key = stdscr.getch()
        if key in enter or key in (ord("y"), ord("Y")):
            return True
        if key in backspace or key in (ord("n"), ord("N"), ord("b")):
            return WizardInput("back")
        if key in (ord("q"), 27):
            return WizardInput("quit")


def _curses_source_addition(
    curses,
    stdscr,
    session: WizardSession,
    view: SourceStageView,
) -> WizardInput | SourceAdditionRequest:
    """Curses counterpart of the text source setup form with the same parser and planner."""

    choices = _source_kind_choices(view)
    kind_event = _curses_single_event(
        curses,
        stdscr,
        "Add source",
        tuple(label for _kind, label in choices),
        session,
    )
    if kind_event.kind != "confirm":
        return kind_event
    kind = choices[kind_event.selected[0]][0]
    default_alias = {
        SourceKind.REGISTRY_GIT: "registry",
        SourceKind.SOURCE_GIT: "source",
        SourceKind.SOURCE_LOCAL: "local",
    }[kind]
    alias = _curses_text_input(
        curses,
        stdscr,
        session,
        "Source alias:",
        default=default_alias,
    )
    if isinstance(alias, WizardInput):
        return alias
    location = _curses_text_input(
        curses,
        stdscr,
        session,
        "Local directory:" if kind is SourceKind.SOURCE_LOCAL else "Git URL:",
    )
    if isinstance(location, WizardInput):
        return location
    if not location:
        _curses_notice(
            stdscr,
            session,
            "Source setup error",
            ("A local directory or Git URL is required. Choose Add to retry.",),
        )
        return WizardInput("back")
    ref: str | None = None
    if kind is not SourceKind.SOURCE_LOCAL:
        prompted_ref = _curses_text_input(
            curses,
            stdscr,
            session,
            "Git ref:",
            default="main",
        )
        if isinstance(prompted_ref, WizardInput):
            return prompted_ref
        ref = prompted_ref
    parsed = configured_source_from_input(alias, kind, location, ref)
    if isinstance(parsed, DomainErr):
        _curses_notice(
            stdscr,
            session,
            "Source setup error",
            (*_source_addition_diagnostics(parsed), "Choose Add to retry."),
        )
        return WizardInput("back")
    planned = plan_source_addition(
        view,
        parsed.value,
        make_default=not any(row.source.is_registry for row in view.rows),
    )
    if isinstance(planned, DomainErr):
        _curses_notice(
            stdscr,
            session,
            "Source setup error",
            (*_source_addition_diagnostics(planned), "Choose Add to retry."),
        )
        return WizardInput("back")
    reviewed = _curses_source_addition_review(curses, stdscr, session, planned.value)
    if isinstance(reviewed, WizardInput):
        return reviewed
    if reviewed:
        return planned.value
    return WizardInput("back")


def _curses_confirm_discard(curses, stdscr, session: WizardSession) -> bool:
    if request_quit(session) == "quit":
        return True
    if not all(hasattr(stdscr, name) for name in ("clear", "addstr", "refresh", "getch")):
        return True
    lines = _curses_header(stdscr, session) + (
        f"Discard {len(session.basket)} selected basket item(s)?",
    )
    while True:
        stdscr.clear()
        available = max(_width(stdscr) - 1, 0)
        height = _height(stdscr)
        for row, line in enumerate(lines[: max(height - 1, 1)]):
            stdscr.addstr(row, 0, _ellipsize(line, available))
        if height:
            stdscr.addstr(
                height - 1,
                0,
                status_bar((("y", "discard"), ("n", "return")), width=available),
            )
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
                status_bar(
                    (("enter", "finalize"), ("b", "back"), ("q", "quit")),
                    width=available,
                ),
            )
        stdscr.refresh()
        key = stdscr.getch()
        if key in (curses.KEY_ENTER, 10, 13, ord("y"), ord("Y")):
            return True
        if key in (getattr(curses, "KEY_BACKSPACE", -1), 127, 8, ord("b")):
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
    consumer_service: Optional[ConsumerApplicationService] = None,
) -> WizardSession:
    profile_names = tuple(sorted(load_profiles(project)))
    read_model: Optional[_UserWizardReadModel] = None
    read_key: Optional[tuple] = None
    while session.current not in ("role", "source", "maintainer_action"):
        if session.current == "profiles":
            selected = tuple(
                index for index, name in enumerate(profile_names) if name in session.profiles
            )
            event = _curses_multi_event(
                curses,
                stdscr,
                "Select profiles",
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
                "Action",
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
                    consumer_service=consumer_service,
                )
                if isinstance(loaded, Err):
                    selection["error"] = (loaded.reason, loaded.code)
                    return session
                read_model = loaded
                read_key = key
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
                "Select artifacts and bundles",
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
            canonical_review: Optional[ConsumerReview] = None
            if consumer_service is not None:
                selected_keys = {item.key for item in session.basket}
                selected_coordinates = (
                    set()
                    if read_model is None
                    else {
                        row.coordinate
                        for row in read_model.marketplace_rows
                        if row.key in selected_keys
                    }
                )
                for collection in consumer_service.context.catalog.collections:
                    if str(collection.coordinate) in selected_keys:
                        selected_coordinates.update(collection.members)
                coordinates = tuple(sorted(selected_coordinates, key=str))
                prepared = consumer_service.prepare(
                    ConsumerActionRequest(
                        session.action or "status",  # type: ignore[arg-type]
                        coordinates,
                        tuple(sorted(session.profiles)),
                        session.scope,  # type: ignore[arg-type]
                        session.install_mode,  # type: ignore[arg-type]
                    )
                )
                if isinstance(prepared, DomainErr):
                    selection["error"] = (
                        "; ".join(item.message for item in prepared.diagnostics),
                        2,
                    )
                    return session
                canonical_review = prepared.value
                review = _curses_review(
                    curses,
                    stdscr,
                    session,
                    render_consumer_review(canonical_review),
                )
            elif session.action == "install":
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
            selection["consumer_review"] = canonical_review
            selection["wizard_session"] = session
            return session

    return session


class CursesUnavailable(Exception):
    """The terminal cannot host the curses wizard.

    Raised only for import, TTY, or curses initialisation failure detected **before** the wizard
    interacts with the user. It is the sole condition under which the text wizard may start as a
    fallback. Any failure after interaction begins propagates instead, so a defect is never
    mistaken for a missing terminal and never silently restarts the wizard at onboarding with the
    user's selections discarded.
    """


INTERNAL_FAILURE_CODE = "tui-stage-internal"


def internal_failure_lines(error: BaseException) -> Tuple[str, ...]:
    """Project a defect into stable, redacted terminal lines.

    Only the exception *type* is disclosed. Messages can carry filesystem paths, subprocess
    output, or setup input, so they are withheld by default; the opt-in local debug channel that
    reveals more is ERR05b in PLAN-typed-wizard-errors.
    """

    return (
        f"internal error: {INTERNAL_FAILURE_CODE}",
        f"  type: {type(error).__name__}",
        "next: rerun the command; if it repeats, report it with the steps that reached this screen.",
    )


def _render_internal_failure(error: BaseException) -> int:
    for line in internal_failure_lines(error):
        print(line)
    return 2


def _run_curses(
    *,
    source_dir: Optional[str] = None,
    repo: Optional[str] = None,
    project: Optional[str] = None,
    user_home: Optional[str] = None,
    source_stage_view: Optional[SourceStageView] = None,
    source_finalizer: Optional[SourceFinalizeFn] = None,
    source_addition_finalizer: Optional[SourceAdditionFinalizeFn] = None,
    source_stage_loader: Optional[SourceStageLoader] = None,
    consumer_service: Optional[ConsumerApplicationService] = None,
    consumer_service_factory: Optional[ConsumerServiceFactory] = None,
    reporting_service: Optional[ReportingApplicationService] = None,
    reporting_service_factory: Optional[ReportingServiceFactory] = None,
    curation_service_factory: Optional[CurationServiceFactory] = None,
) -> int:
    """Collect a persistent wizard session and dispatch only after curses teardown."""
    import curses  # stdlib; imported lazily so the text path needs no terminal at all.

    if not load_profiles(project):  # pragma: no cover - built-ins always present
        print("No profiles available.")
        return 0
    selection: dict = {}
    interacted = False
    stage_view = source_stage_view or (
        _legacy_source_stage_view(source_dir=source_dir, repo=repo)
        if source_dir is not None or repo is not None
        else _empty_source_stage_view()
    )

    def _ui(stdscr) -> None:
        nonlocal stage_view, source_stage_view, source_finalizer, source_addition_finalizer
        nonlocal interacted
        curses.curs_set(0)
        # Past this point curses is initialised and the screen is ours: any later failure is a
        # defect in the wizard, not a terminal that cannot host it.
        interacted = True
        session = initial_session()
        onboarding = _curses_onboarding(curses, stdscr)
        if onboarding.kind == "quit":
            selection["cancelled"] = True
            return
        session = wizard_advance(session)
        while session.current in ("role", "source"):
            if session.current == "role":
                event = _curses_single_event(
                    curses,
                    stdscr,
                    "Choose how you want to use aart",
                    tuple(f"{role.label} - {role.description}" for role in ROLES),
                    session,
                )
                session = remember_position(
                    session, "role", cursor=event.cursor, scroll=event.scroll
                )
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

            assert session.current == "source"
            if source_stage_view is None and (source_dir is not None or repo is not None):
                selected_source_value = _automatic_source_selection(stage_view)
            else:
                event, maybe_selected_source, source_error = _curses_source_event(
                    curses,
                    stdscr,
                    session,
                    stage_view,
                )
                session = remember_position(
                    session, "source", cursor=event.cursor, scroll=event.scroll
                )
                if event.kind == "back":
                    session = wizard_back(session)
                    continue
                if event.kind == "quit":
                    selection["cancelled"] = True
                    return
                if event.kind == "add":
                    if source_addition_finalizer is None or source_stage_loader is None:
                        selection["error"] = ("source setup is unavailable in this TUI runtime", 2)
                        return
                    addition = _curses_source_addition(curses, stdscr, session, stage_view)
                    if isinstance(addition, WizardInput):
                        if addition.kind == "quit":
                            selection["cancelled"] = True
                            return
                        continue
                    if all(hasattr(stdscr, name) for name in ("clear", "addstr", "refresh")):
                        stdscr.clear()
                        stdscr.addstr(0, 0, "Synchronizing and validating the source…")
                        stdscr.refresh()
                    finalized_addition = source_addition_finalizer(addition)
                    if isinstance(finalized_addition, DomainErr):
                        _curses_notice(
                            stdscr,
                            session,
                            "Source setup failed",
                            (
                                *_source_addition_diagnostics(finalized_addition),
                                "The source was not saved. Choose Add to retry.",
                            ),
                        )
                        continue
                    refreshed = source_stage_loader()
                    if isinstance(refreshed, DomainErr):
                        _curses_notice(
                            stdscr,
                            session,
                            "Source setup incomplete",
                            (
                                *_source_addition_diagnostics(refreshed),
                                "The source was saved, but restart aart to reload Sources.",
                            ),
                        )
                        continue
                    stage_view = refreshed.value.view
                    # The text fallback below receives ``source_stage_view``.  Keep it in sync
                    # with the live curses value so a later terminal exception does not make a
                    # successfully saved source look absent (and provoke a duplicate add).
                    source_stage_view = stage_view
                    source_finalizer = refreshed.value.source_finalizer
                    source_addition_finalizer = refreshed.value.source_addition_finalizer
                    session = replace(
                        session,
                        source_selection=None,
                        revision=session.revision + 1,
                    )
                    _curses_notice(
                        stdscr,
                        session,
                        "Source setup complete",
                        (
                            f"Sources: synchronized and saved {addition.source.alias}.",
                            "Choose enabled source(s) to continue.",
                        ),
                    )
                    continue
                if source_error is not None:
                    selection["error"] = (
                        "; ".join(item.message for item in source_error.diagnostics),
                        2,
                    )
                    return
                assert maybe_selected_source is not None
                selected_source_value = maybe_selected_source
            session = wizard_select(session, "source", selected_source_value)
            session = wizard_advance(session)
            if selected_source_value.no_source:
                selection["no_source"] = True
                return
            selected_role = session.role
            assert selected_role is not None
            active_consumer_service = consumer_service
            active_reporting_service = reporting_service
            active_reporting_failed = False
            if consumer_service_factory is not None and selected_role == "user":
                loaded_consumer = consumer_service_factory(selected_source_value.request.after)
                if isinstance(loaded_consumer, DomainErr):
                    selection["error"] = (
                        "; ".join(item.message for item in loaded_consumer.diagnostics),
                        2,
                    )
                    return
                active_consumer_service = loaded_consumer.value
            if reporting_service_factory is not None and selected_role == "user":
                loaded_reporting = reporting_service_factory(selected_source_value.request.after)
                if isinstance(loaded_reporting, DomainErr):
                    active_reporting_service = None
                    active_reporting_failed = True
                else:
                    active_reporting_service = loaded_reporting.value
            active_source_dir, active_repo = source_dir, repo
            if active_consumer_service is None or selected_role != "user":
                source_arguments = _selected_legacy_source_arguments(
                    stage_view,
                    selected_source_value,
                    source_dir=source_dir,
                    repo=repo,
                )
                if isinstance(source_arguments, DomainErr):
                    selection["error"] = (
                        "; ".join(item.message for item in source_arguments.diagnostics),
                        2,
                    )
                    return
                active_source_dir, active_repo = source_arguments.value
            if selected_role == "user":
                session = _run_user_curses_wizard(
                    curses,
                    stdscr,
                    session,
                    selection,
                    source_dir=active_source_dir,
                    repo=active_repo,
                    project=project,
                    user_home=user_home,
                    consumer_service=active_consumer_service,
                )
                if selection.get("consumer_review") is not None:
                    selection["active_consumer_service"] = active_consumer_service
                    selection["active_reporting_service"] = active_reporting_service
                    if active_reporting_failed:
                        selection["reporting_warning"] = True
                if selection:
                    return
                if session.current in ("role", "source"):
                    continue
                return

            catalog_root = os.path.abspath(active_source_dir or ".")
            canonical_curation = _is_canonical_maintainer_workspace(catalog_root)
            context_result = None
            maintainer_actions = CANONICAL_MAINTAINER_ACTIONS
            if not canonical_curation:
                from .commands import upstream

                context_result = upstream.load_maintainer_context(
                    Request(
                        command="upstream",
                        upstream_action="validate",
                        source_dir=catalog_root,
                        repo=active_repo,
                    )
                )
                if isinstance(context_result, Err):
                    selection["error"] = (context_result.reason, context_result.code)
                    return
                maintainer_actions = MAINTAINER_ACTIONS
            while session.current == "maintainer_action":
                event = _curses_single_event(
                    curses,
                    stdscr,
                    f"Maintainer - {catalog_root}",
                    tuple(label for _action, label in maintainer_actions),
                    session,
                )
                if event.kind == "back":
                    session = wizard_back(session)
                    break
                if event.kind == "quit":
                    selection["cancelled"] = True
                    return
                action = maintainer_actions[event.selected[0]][0]
                session = wizard_select(session, "maintainer_action", action)
                session = wizard_advance(session)
                if action == "user":
                    maintainer_consumer_service = consumer_service
                    maintainer_reporting_service = reporting_service
                    maintainer_reporting_failed = False
                    active_consumer_factory = consumer_service_factory
                    if active_consumer_factory is None and canonical_curation:
                        from .consumer.runtime import load_local_consumer_service

                        def active_consumer_factory(
                            configuration: UserConfiguration,
                        ) -> DomainResult[ConsumerApplicationService]:
                            return load_local_consumer_service(
                                project=project,
                                user_home=user_home,
                                configuration=configuration,
                            )

                    if active_consumer_factory is not None:
                        loaded_consumer = active_consumer_factory(
                            selected_source_value.request.after
                        )
                        if isinstance(loaded_consumer, DomainErr):
                            selection["error"] = (
                                "; ".join(item.message for item in loaded_consumer.diagnostics),
                                2,
                            )
                            return
                        maintainer_consumer_service = loaded_consumer.value
                    if reporting_service_factory is not None:
                        loaded_reporting = reporting_service_factory(
                            selected_source_value.request.after
                        )
                        if isinstance(loaded_reporting, DomainErr):
                            maintainer_reporting_service = None
                            maintainer_reporting_failed = True
                        else:
                            maintainer_reporting_service = loaded_reporting.value
                    session = _run_user_curses_wizard(
                        curses,
                        stdscr,
                        session,
                        selection,
                        source_dir=active_source_dir,
                        repo=active_repo,
                        project=project,
                        user_home=user_home,
                        consumer_service=maintainer_consumer_service,
                    )
                    if selection.get("consumer_review") is not None:
                        selection["active_consumer_service"] = maintainer_consumer_service
                        selection["active_reporting_service"] = maintainer_reporting_service
                        if maintainer_reporting_failed:
                            selection["reporting_warning"] = True
                    if selection or session.current != "maintainer_action":
                        return
                    continue
                selection["maintainer_action"] = action
                if context_result is not None:
                    assert not isinstance(context_result, Err)
                    selection["maintainer_context"] = context_result.value
                selection["maintainer_session"] = session
                selection["source_arguments"] = (active_source_dir, active_repo)
                selection["consumer_configuration"] = selected_source_value.request.after
                return

    try:
        curses.wrapper(_ui)
    except Exception as error:
        if interacted:
            # The wizard was live; this is a defect. Let it reach the crash boundary in ``run``
            # rather than discarding the session behind a second wizard.
            raise
        raise CursesUnavailable("the curses wizard could not start") from error

    if "error" in selection:
        reason, code = selection["error"]
        print(f"error: {reason}")
        return code
    if "empty" in selection:
        action, profiles = selection["empty"]
        print(_empty_choices_message(action, profiles))
        return _render_result(CommandOutcome(0, ActionSummary(action=action)), print)
    if "no_source" in selection:
        return _cancel(
            print,
            "No sources selected; no registry was forced and no changes were made.",
        )
    if "maintainer_action" in selection:
        active_source_dir, active_repo = selection.get(
            "source_arguments",
            (source_dir, repo),
        )
        result = _run_maintainer_text(
            selection["maintainer_session"],
            input,
            print,
            source_factory=open_source,
            source_dir=active_source_dir,
            repo=active_repo,
            project=project,
            user_home=user_home,
            source_finalizer=source_finalizer,
            consumer_service_factory=consumer_service_factory,
            reporting_service_factory=reporting_service_factory,
            consumer_configuration=selection.get("consumer_configuration"),
            curation_service_factory=curation_service_factory,
        )
        return _cancel(print) if isinstance(result, WizardSession) else result
    if "request" not in selection:
        if "empty_selection" in selection:
            return _cancel(print, "No artifacts selected; no changes were made.")
        return _cancel(print)

    request = selection["request"]
    source_code = _finalize_source_selection(
        selection["wizard_session"],
        source_finalizer,
        print,
    )
    if source_code is not None:
        return source_code
    consumer_review = selection.get("consumer_review")
    if consumer_review is not None:
        active_consumer_service = selection.get("active_consumer_service", consumer_service)
        assert active_consumer_service is not None
        finalized = active_consumer_service.finalize(
            consumer_review,
            consumer_review.review_digest,
        )
        if isinstance(finalized, DomainErr):
            for diagnostic in finalized.diagnostics:
                print(f"{diagnostic.severity.value}: {diagnostic.message}")
            return 2
        for line in render_consumer_outcome(finalized.value):
            print(line)
        if selection.get("reporting_warning"):
            print(
                "warning: usage reporting is unavailable; artifact installation remains available"
            )
        return _complete_canonical_consumer_action(
            active_consumer_service,
            consumer_review,
            finalized.value,
            selection.get("active_reporting_service", reporting_service),
            read=input,
            write=print,
        )
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
    allow_add: bool = False,
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
    back_keys = {getattr(curses, "KEY_BACKSPACE", -1), 127, 8, ord("b")}
    hints = _list_hints(
        toggle=True, back=wizard, details=details is not None, add=wizard and allow_add
    )
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
            hints=hints,
        )
        ch = stdscr.getch()
        if ch in (ord("q"), 27):  # q / ESC
            return WizardInput("quit", cursor=cursor, scroll=scroll) if wizard else None
        elif wizard and ch in back_keys:
            return WizardInput("back", cursor=cursor, scroll=scroll)
        elif wizard and allow_add and ch in (ord("a"), ord("A")):
            return WizardInput("add", cursor=cursor, scroll=scroll)
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
    back_keys = {getattr(curses, "KEY_BACKSPACE", -1), 127, 8, ord("b")}
    hints = _list_hints(toggle=False, back=wizard, details=False, add=False)
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
            hints=hints,
        )
        ch = stdscr.getch()
        if ch in (ord("q"), 27):
            return WizardInput("quit", cursor=cursor, scroll=scroll) if wizard else None
        elif wizard and ch in back_keys:
            return WizardInput("back", cursor=cursor, scroll=scroll)
        elif ch in (curses.KEY_UP, ord("k")):
            cursor = (cursor - 1) % len(labels)
        elif ch in (curses.KEY_DOWN, ord("j")):
            cursor = (cursor + 1) % len(labels)
        elif ch in (curses.KEY_ENTER, 10, 13):
            return WizardInput("confirm", (cursor,), cursor, scroll) if wizard else cursor


def _list_hints(
    *, toggle: bool, back: bool, details: bool, add: bool
) -> Tuple[Tuple[str, str], ...]:
    """The canonical hint table filtered down to the keys this screen actually accepts (D2)."""

    enabled = {"space": toggle, "enter": True, "b": back, "?": details, "a": add, "q": True}
    return tuple(hint for hint in HINT_ORDER if enabled[hint[0]])


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
    hints: Sequence[Tuple[str, str]] = (),
) -> int:
    """Render *title* + the labels, marking the cursor row and any checked rows.

    The last row belongs to the status bar and to nothing else (D2). Everything above it — header,
    title and the list viewport — is laid out inside ``height - 1``, the same reservation
    ``_curses_onboarding`` already makes for its footer.
    """
    stdscr.clear()
    available = max(_width(stdscr) - 1, 0)
    height = _height(stdscr)
    body_height = max(height - 1, 1)
    header_budget = max(body_height - CHROME_ROWS, 1)
    if len(header) > header_budget:
        # Keep whatever says where the user is before anything else. These match the marker
        # vocabulary in tui_layout, not prose, so they survive wording changes.
        priorities = (
            lambda line: STAGE_CURRENT in line,
            lambda line: line.startswith("Basket:"),
            lambda line: line.startswith("Removed "),
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
        if row >= body_height:
            break
        stdscr.addstr(row, 0, _ellipsize(line, available))
        row += 1
    if row < body_height:
        stdscr.addstr(row, 0, _ellipsize(title, available))
    list_start = row + 2
    visible_rows = max(body_height - list_start, 1)
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
                box = f"{BOX_DISABLED} "
            else:
                box = f"{BOX_CHECKED} " if checked[i] else f"{BOX_EMPTY} "
        line = f"{prefix}{box}{label}"
        target_row = list_start + display_row
        if target_row < body_height:
            stdscr.addstr(target_row, 0, _ellipsize(line, available))
    if height:
        stdscr.addstr(
            height - 1,
            0,
            status_bar(
                hints,
                counters=_list_counters(labels, checked, disabled, scroll, visible_rows),
                width=available,
            ),
        )
    stdscr.refresh()
    return scroll


def _list_counters(
    labels,
    checked,
    disabled: Optional[Sequence[bool]],
    scroll: int,
    visible_rows: int,
) -> Tuple[str, ...]:
    """The bar's right-hand counters, cheapest to lose last (D2)."""

    counters = []
    if checked is not None:
        selected = sum(
            1
            for index, value in enumerate(checked)
            if value and (disabled is None or not disabled[index])
        )
        counters.append(f"{selected} selected")
    if len(labels) > visible_rows:
        last = min(len(labels), scroll + visible_rows)
        counters.append(f"{scroll + 1}-{last} of {len(labels)}")
    return tuple(counters)


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
                status_bar((("enter", "start"), ("q", "quit")), width=available),
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
        "Installation scope",
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
    back_keys = {getattr(curses, "KEY_BACKSPACE", -1), 127, 8, ord("b")}
    hints = _list_hints(toggle=False, back=True, details=False, add=False)
    while True:
        scroll = _draw_list(
            curses,
            stdscr,
            "Installation mode",
            labels,
            cursor,
            None,
            header=header,
            scroll=scroll,
            hints=hints,
        )
        ch = stdscr.getch()
        if ch in (ord("q"), 27):
            return WizardInput("quit", cursor=cursor, scroll=scroll) if wizard else None
        if ch in back_keys:
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
                status_bar(
                    (("enter", "finalize"), ("b", "back"), ("q", "cancel")),
                    width=available,
                ),
            )
        stdscr.refresh()
        ch = stdscr.getch()
        if ch in (curses.KEY_ENTER, 10, 13, ord("y"), ord("Y")):
            return True
        if ch in (getattr(curses, "KEY_BACKSPACE", -1), 127, 8, ord("b")):
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
            hints = (("↑/↓", "scroll"), ("q", "return")) if max_offset else (("q", "return"),)
            stdscr.addstr(height - 1, 0, status_bar(hints, width=available))
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
    source_context = _runtime_source_stage_context(
        source_dir=source_dir,
        repo=repo,
        user_home=user_home,
    )
    if isinstance(source_context, DomainErr):
        for diagnostic in source_context.diagnostics:
            print(f"{diagnostic.severity.value}: {diagnostic.message}")
        return 2
    source_runtime = source_context.value
    source_stage_view = source_runtime.view
    source_finalizer = source_runtime.source_finalizer
    source_addition_finalizer = source_runtime.source_addition_finalizer

    def reload_source_stage() -> DomainResult[_RuntimeSourceStage]:
        return _runtime_source_stage_context(
            source_dir=source_dir,
            repo=repo,
            user_home=user_home,
        )

    consumer_service: Optional[ConsumerApplicationService] = None
    consumer_service_factory: Optional[ConsumerServiceFactory] = None
    reporting_service: Optional[ReportingApplicationService] = None
    reporting_service_factory: Optional[ReportingServiceFactory] = None
    if source_dir is None and repo is None:
        from .consumer.runtime import load_local_consumer_service
        from .reporting.runtime import load_local_reporting_service

        def runtime_consumer_service(
            configuration: UserConfiguration,
        ) -> DomainResult[ConsumerApplicationService]:
            return load_local_consumer_service(
                project=project,
                user_home=user_home,
                configuration=configuration,
            )

        consumer_service_factory = runtime_consumer_service

        def runtime_reporting_service(
            configuration: UserConfiguration,
        ) -> DomainResult[ReportingApplicationService]:
            return load_local_reporting_service(
                user_home=user_home,
                configuration=configuration,
            )

        reporting_service_factory = runtime_reporting_service
    try:
        import curses  # noqa: F401  (presence check only)

        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            raise RuntimeError("not a tty")
    except Exception:
        return _run_text(
            source_dir=source_dir,
            repo=repo,
            project=project,
            user_home=user_home,
            source_stage_view=source_stage_view,
            source_finalizer=source_finalizer,
            source_addition_finalizer=source_addition_finalizer,
            source_stage_loader=reload_source_stage,
            consumer_service=consumer_service,
            consumer_service_factory=consumer_service_factory,
            reporting_service=reporting_service,
            reporting_service_factory=reporting_service_factory,
        )

    try:
        return _run_curses(
            source_dir=source_dir,
            repo=repo,
            project=project,
            user_home=user_home,
            source_stage_view=source_stage_view,
            source_finalizer=source_finalizer,
            source_addition_finalizer=source_addition_finalizer,
            source_stage_loader=reload_source_stage,
            consumer_service=consumer_service,
            consumer_service_factory=consumer_service_factory,
            reporting_service=reporting_service,
            reporting_service_factory=reporting_service_factory,
        )
    except CursesUnavailable:
        return _run_text(
            source_dir=source_dir,
            repo=repo,
            project=project,
            user_home=user_home,
            source_stage_view=source_stage_view,
            source_finalizer=source_finalizer,
            source_addition_finalizer=source_addition_finalizer,
            source_stage_loader=reload_source_stage,
            consumer_service=consumer_service,
            consumer_service_factory=consumer_service_factory,
            reporting_service=reporting_service,
            reporting_service_factory=reporting_service_factory,
        )
    except Exception as error:
        # The outermost crash boundary. ``curses.wrapper`` has already restored the terminal.
        # Broad catching is permitted here for rendering only, never to start a second wizard.
        return _render_internal_failure(error)
