"""Pure persistent wizard/session domain for the text and curses TUI (issue #21)."""

from __future__ import annotations

import textwrap
from dataclasses import dataclass, replace
from typing import Literal, Mapping, Optional, Tuple

from agent_artifacts.tui_layout import (
    STAGE_CONFIRMED,
    STAGE_CURRENT,
    STAGE_JOIN,
    STAGE_PENDING,
    STAGE_PROJECTION,
)
from agent_artifacts.tui_sources import SourceSelection

WizardStage = Literal[
    "onboarding",
    "role",
    "maintainer_action",
    "profiles",
    "action",
    "scope",
    "source",
    "mode",
    "artifacts",
    "native_details",
    "review",
]
WizardRole = Literal["user", "maintainer"]
WizardDecision = Literal["quit", "confirm_quit"]
# ``add`` is a navigation event owned by the Sources screen.  It does not mutate the
# persistent wizard session by itself; the frontend collects a separately reviewed
# source-addition request before returning to the same Sources stage.
WizardInputKind = Literal["confirm", "back", "quit", "add", "sync", "remove", "retry"]

_STAGE_LABELS: Mapping[WizardStage, str] = {
    "onboarding": "How it works",
    "role": "Role",
    "maintainer_action": "Maintainer action",
    "profiles": "Harness",
    "action": "Action",
    "scope": "Scope",
    "source": "Sources",
    "mode": "Mode",
    "artifacts": "Artifacts",
    "native_details": "Native reference details",
    "review": "Review",
}


@dataclass(frozen=True, slots=True)
class WizardPosition:
    stage: WizardStage
    cursor: int = 0
    scroll: int = 0


@dataclass(frozen=True, slots=True)
class BasketItem:
    kind: Literal["artifact", "bundle", "reference"]
    key: str
    label: str
    description: str = ""


@dataclass(frozen=True, slots=True)
class WizardNotice:
    stage: WizardStage
    value: str
    reason: str


@dataclass(frozen=True, slots=True)
class WizardInput:
    kind: WizardInputKind
    selected: Tuple[int, ...] = ()
    cursor: int = 0
    scroll: int = 0


@dataclass(frozen=True, slots=True)
class WizardSession:
    current: WizardStage = "onboarding"
    visited: Tuple[WizardStage, ...] = ()
    confirmed: Tuple[WizardStage, ...] = ()
    role: Optional[WizardRole] = None
    maintainer_action: Optional[str] = None
    profiles: Tuple[str, ...] = ()
    action: Optional[str] = None
    scope: str = "project"
    install_mode: str = "copy"
    source_label: str = ""
    source_root: str = ""
    source_selection: Optional[SourceSelection] = None
    maintainer_checkout: bool = False
    basket: Tuple[BasketItem, ...] = ()
    positions: Tuple[WizardPosition, ...] = ()
    notices: Tuple[WizardNotice, ...] = ()
    revision: int = 0


def initial_session() -> WizardSession:
    return WizardSession()


def _user_stages(
    session: WizardSession, *, prefix: Tuple[WizardStage, ...]
) -> Tuple[WizardStage, ...]:
    stages = prefix + ("profiles", "action")
    if session.action is None:
        return stages
    stages += ("scope",)
    if session.action == "install":
        return stages + ("mode", "artifacts", "review")
    if session.action == "update":
        return stages + ("artifacts", "review")
    if session.action == "uninstall":
        return stages + ("artifacts", "review")
    if session.action == "status":
        return stages + ("review",)
    return stages


def _path_is_settled(session: WizardSession) -> bool:
    """True when no fork that could still change the remaining stages is open."""

    if session.role is None:
        return False
    if session.role == "user":
        return session.action is not None
    if session.maintainer_action is None:
        return False
    if session.maintainer_action == "user":
        return session.action is not None
    return True


def projected_stages_for(session: WizardSession) -> Tuple[Tuple[WizardStage, ...], bool]:
    """Return the stages to display and whether the tail is still a projection.

    ``stages_for`` only returns stages whose existence is already determined, because the path
    forks on role and again on action. The stepper shows the whole journey from the first screen,
    so before the role fork is resolved the user path stands in as the default continuation. The
    boolean is what keeps that honest: callers mark a projected tail rather than presenting a
    guess as a certainty.
    """

    projected = not _path_is_settled(session)
    if session.role is None:
        return stages_for(replace(session, role="user")), projected
    return stages_for(session), projected


def stages_for(session: WizardSession) -> Tuple[WizardStage, ...]:
    common: Tuple[WizardStage, ...] = ("onboarding", "role")
    if session.role is None:
        return common
    if session.role == "user":
        return _user_stages(session, prefix=common + ("source",))

    maintainer = (
        common + (() if session.maintainer_checkout else ("source",)) + ("maintainer_action",)
    )
    action = session.maintainer_action
    if action is None:
        return maintainer
    if action in ("health", "validate", "audit", "diff", "lock", "build"):
        return maintainer + ("review",)
    if action in (
        "init",
        "scaffold",
        "promote-native",
        "refresh-native",
    ):
        return maintainer + ("native_details", "review")
    if action == "user":
        return _user_stages(session, prefix=maintainer)
    return maintainer


def _append_once(values: Tuple[WizardStage, ...], stage: WizardStage) -> Tuple[WizardStage, ...]:
    return values if stage in values else values + (stage,)


def _stage_ready(session: WizardSession, stage: WizardStage) -> bool:
    if stage == "role":
        return session.role is not None
    if stage == "maintainer_action":
        return session.maintainer_action is not None
    if stage == "source":
        return session.source_selection is not None
    if stage == "profiles":
        return bool(session.profiles)
    if stage == "action":
        return session.action is not None
    if stage == "artifacts":
        return bool(session.basket)
    return True


def _unconfirm_from(
    confirmed: Tuple[WizardStage, ...], stages: Tuple[WizardStage, ...], stage: WizardStage
) -> Tuple[WizardStage, ...]:
    if stage not in stages:
        return confirmed
    affected = set(stages[stages.index(stage) :])
    return tuple(item for item in confirmed if item not in affected)


def select(session: WizardSession, stage: WizardStage, value: object) -> WizardSession:
    """Set one stage value and invalidate that stage plus applicable downstream confirmation."""

    if stage == "role":
        if value not in ("user", "maintainer"):
            return session
        changed = replace(session, role=value, maintainer_checkout=False)
    elif stage == "maintainer_action":
        changed = replace(session, maintainer_action=str(value))
    elif stage == "profiles":
        if not isinstance(value, (tuple, list)):
            return session
        changed = replace(session, profiles=tuple(str(item) for item in value))
    elif stage == "action":
        changed = replace(session, action=str(value))
    elif stage == "scope":
        changed = replace(session, scope=str(value))
    elif stage == "mode":
        changed = replace(session, install_mode=str(value))
    elif stage == "artifacts":
        if not isinstance(value, (tuple, list)) or not all(
            isinstance(item, BasketItem) for item in value
        ):
            return session
        changed = replace(session, basket=tuple(value))
    elif stage == "source":
        if not isinstance(value, SourceSelection):
            return session
        changed = replace(session, source_selection=value)
    else:
        return session
    if changed == session:
        return session
    stages = stages_for(changed)
    current = changed.current if changed.current in stages else stage
    return replace(
        changed,
        current=current,
        confirmed=_unconfirm_from(changed.confirmed, stages, stage),
        notices=(),
        revision=changed.revision + 1,
    )


def use_current_checkout(session: WizardSession) -> WizardSession:
    """Mark the default Maintainer route as a checkout workflow, not a source subscription."""

    if session.role != "maintainer" or session.maintainer_checkout:
        return session
    changed = replace(session, maintainer_checkout=True, source_selection=None)
    stages = stages_for(changed)
    current = changed.current if changed.current in stages else "maintainer_action"
    return replace(
        changed,
        current=current,
        confirmed=_unconfirm_from(changed.confirmed, stages, "maintainer_action"),
        notices=(),
        revision=changed.revision + 1,
    )


def advance(session: WizardSession) -> WizardSession:
    stages = stages_for(session)
    if session.current not in stages or not _stage_ready(session, session.current):
        return session
    index = stages.index(session.current)
    visited = _append_once(session.visited, session.current)
    confirmed = _append_once(session.confirmed, session.current)
    if index + 1 >= len(stages):
        return replace(session, visited=visited, confirmed=confirmed)
    return replace(
        session,
        current=stages[index + 1],
        visited=visited,
        confirmed=confirmed,
    )


def back(session: WizardSession) -> WizardSession:
    stages = stages_for(session)
    if session.current not in stages:
        return replace(session, current=stages[-1] if stages else "onboarding")
    index = stages.index(session.current)
    if index == 0:
        return session
    target = stages[index - 1]
    return replace(
        session,
        current=target,
        visited=_append_once(session.visited, session.current),
        confirmed=_unconfirm_from(session.confirmed, stages, target),
        revision=session.revision + 1,
    )


def remember_position(
    session: WizardSession,
    stage: WizardStage,
    *,
    cursor: int,
    scroll: int,
) -> WizardSession:
    position = WizardPosition(stage, max(cursor, 0), max(scroll, 0))
    positions = tuple(item for item in session.positions if item.stage != stage) + (position,)
    return replace(session, positions=positions)


def reconcile_basket(
    session: WizardSession,
    availability: Mapping[str, str],
) -> WizardSession:
    """Keep enabled keys and explain only the values removed by the current read model."""

    retained = []
    removed = []
    for item in session.basket:
        reason = availability.get(item.key)
        if reason == "":
            retained.append(item)
        else:
            removed.append(
                WizardNotice(
                    "artifacts",
                    item.key,
                    reason or "no longer available for the selected choices",
                )
            )
    basket = tuple(retained)
    notices = tuple(removed)
    last_index = max(len(availability) - 1, 0)
    positions = tuple(
        replace(
            position,
            cursor=min(position.cursor, last_index),
            scroll=min(position.scroll, last_index),
        )
        if position.stage == "artifacts"
        else position
        for position in session.positions
    )
    if basket == session.basket and notices == session.notices and positions == session.positions:
        return session
    stages = stages_for(session)
    return replace(
        session,
        basket=basket,
        notices=notices,
        positions=positions,
        confirmed=_unconfirm_from(session.confirmed, stages, "artifacts"),
        revision=session.revision + 1,
    )


def can_finalize(session: WizardSession, *, revision: Optional[int] = None) -> bool:
    if revision is not None and revision != session.revision:
        return False
    stages = stages_for(session)
    if session.current != "review" or not stages or stages[-1] != "review":
        return False
    required = tuple(stage for stage in stages if stage != "review")
    return all(stage in session.confirmed for stage in required)


def request_quit(session: WizardSession) -> WizardDecision:
    return "confirm_quit" if session.basket else "quit"


def onboarding_lines(frontend: Literal["text", "curses"]) -> Tuple[str, ...]:
    """Explain what the bar cannot: what aart does, the two roles, and where artifacts come from.

    D11 removed the control list that used to live here. Keys are now permanently on screen in the
    status bar, so repeating them on the first screen only delayed the first real choice.
    """

    del frontend  # Both frontends now say the same thing; the keys differed, the meaning did not.
    return (
        "How aart works",
        "",
        "aart installs your team's AI artifacts - skills, guidelines, MCP",
        "configs, hooks, memory - from a source repository into the harnesses",
        "you actually use.",
        "",
        "User installs artifacts into a project or a home directory.",
        "Maintainer curates what a team is offered and where it comes from.",
    )


def _fit(text: str, width: int) -> Tuple[str, ...]:
    if width <= 0:
        return ("",)
    return tuple(
        textwrap.wrap(
            text.replace("\r", " ").replace("\n", " "),
            width=width,
            break_long_words=True,
            break_on_hyphens=False,
        )
        or ("",)
    )


def _stage_token(session: WizardSession, stage: WizardStage) -> str:
    if stage == session.current:
        marker = STAGE_CURRENT
    elif stage in session.confirmed:
        marker = STAGE_CONFIRMED
    else:
        marker = STAGE_PENDING
    return f"{marker} {_STAGE_LABELS[stage]}"


def stage_label(stage: WizardStage) -> str:
    """Return the stable human label for a typed stage context."""

    return _STAGE_LABELS[stage]


def render_stepper(session: WizardSession, *, width: int) -> Tuple[str, ...]:
    stages, projected = projected_stages_for(session)
    tokens = [_stage_token(session, stage) for stage in stages]
    if projected:
        tokens.append(STAGE_PROJECTION)
    tokens = [
        token if len(token) <= width else token[: max(width - 1, 0)] + STAGE_PROJECTION
        for token in tokens
    ]
    join = f" {STAGE_JOIN} "
    lines = []
    current = ""
    for token in tokens:
        candidate = token if not current else f"{current}{join}{token}"
        if current and len(candidate) > width:
            lines.append(current)
            current = token
        else:
            current = candidate
    if current or not lines:
        lines.append(current)
    return tuple(lines)


def render_header(
    session: WizardSession,
    *,
    width: int,
    frontend: Literal["text", "curses"],
) -> Tuple[str, ...]:
    lines = render_stepper(session, width=width)
    # D4: the stepper's ``▸`` already names the current stage, so there is no ``Stage:`` line.
    # The one exception is a stepper too narrow to show that token intact — then, and only then,
    # the position would otherwise be unavailable.
    token = _stage_token(session, session.current)
    if not any(token in line for line in lines):
        lines += _fit(token, width)
    if session.basket:
        lines += _fit(f"Basket: {len(session.basket)} selected", width)
    for notice in session.notices:
        lines += _fit(f"Removed {notice.value}: {notice.reason}", width)
    # D2: key hints live in the pinned status bar, not here.
    return lines
