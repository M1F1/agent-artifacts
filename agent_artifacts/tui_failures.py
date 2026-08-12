"""Pure presentation context for expected wizard-stage failures."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from agent_artifacts.domain.diagnostics import Diagnostic
from agent_artifacts.domain.result import Err
from agent_artifacts.tui_layout import CONTENT_MEASURE, field_block, wrap
from agent_artifacts.wizard import WizardSession, WizardStage, stage_label

WizardOperation = Literal["load", "review", "finalize", "setup", "reporting"]
WizardRecoveryChoice = Literal["retry", "back", "quit"]

_OPERATION_PAST = {
    "load": "loaded",
    "review": "reviewed",
    "finalize": "finalized",
    "setup": "set up",
    "reporting": "reported",
}
_ALLOWED_DETAIL_KEYS = frozenset(
    {
        "artifact",
        "coordinate",
        "detected_schema",
        "profile",
        "required_schema",
        "schema_version",
        "scope",
    }
)
_RECOVERY_LABELS = {
    "retry": "Retry = r",
    "back": "Back = b",
    "quit": "Quit = q",
}


@dataclass(frozen=True, slots=True)
class WizardStageFailure:
    """Expected diagnostics plus immutable frontend context and safe recovery choices."""

    stage: WizardStage
    operation: WizardOperation
    diagnostics: tuple[Diagnostic, ...]
    action: str | None
    scope: str | None
    project: str | None
    recoverable: bool
    choices: tuple[WizardRecoveryChoice, ...]

    def __post_init__(self) -> None:
        if not self.diagnostics:
            raise ValueError("wizard stage failure requires at least one diagnostic")
        if not self.choices or "quit" not in self.choices:
            raise ValueError("wizard stage failure must offer quit")
        if "retry" in self.choices and not self.recoverable:
            raise ValueError("retry requires a recoverable wizard stage failure")


def wizard_stage_failure(
    session: WizardSession,
    operation: WizardOperation,
    result: Err,
    *,
    project: str | None = None,
    stage: WizardStage | None = None,
    recoverable: bool | None = None,
) -> WizardStageFailure:
    """Add stage context without transforming the domain diagnostics themselves."""

    can_retry = operation == "load" if recoverable is None else recoverable
    choices: tuple[WizardRecoveryChoice, ...] = (
        ("retry", "back", "quit") if can_retry else ("back", "quit")
    )
    return WizardStageFailure(
        stage=session.current if stage is None else stage,
        operation=operation,
        diagnostics=result.diagnostics,
        action=session.action,
        scope=session.scope,
        project=project,
        recoverable=can_retry,
        choices=choices,
    )


def _indented_lines(text: str, *, indent: int, width: int) -> tuple[str, ...]:
    prefix = " " * indent
    return tuple(prefix + line for line in wrap(text, width=max(width - len(prefix), 1)))


def render_wizard_stage_failure(
    failure: WizardStageFailure,
    *,
    width: int = CONTENT_MEASURE,
) -> tuple[str, ...]:
    """Project a stage failure into bounded terminal lines for either frontend."""

    bounded_width = min(max(width, 1), CONTENT_MEASURE)
    title = f"{stage_label(failure.stage)} could not be {_OPERATION_PAST[failure.operation]}"
    lines: list[str] = [*wrap(title, width=bounded_width), ""]
    context = []
    if failure.action is not None:
        context.append(("action", failure.action))
    if failure.scope is not None:
        context.append(("scope", failure.scope))
    if failure.project is not None:
        context.append(("project", failure.project))
    if context:
        lines.extend(field_block(context, indent=2, width=bounded_width))
    for diagnostic in failure.diagnostics:
        if lines and lines[-1] != "":
            lines.append("")
        lines.extend(
            wrap(
                f"{diagnostic.severity.value} [{diagnostic.code.value}]: {diagnostic.message}",
                width=bounded_width,
            )
        )
        fields = []
        if diagnostic.location is not None:
            if diagnostic.location.source is not None:
                fields.append(("source", diagnostic.location.source.value))
            if diagnostic.location.path is not None:
                fields.append(("path", diagnostic.location.path))
            if diagnostic.location.pointer is not None:
                fields.append(("pointer", diagnostic.location.pointer))
            if diagnostic.location.line is not None:
                position = f"line {diagnostic.location.line}"
                if diagnostic.location.column is not None:
                    position += f", column {diagnostic.location.column}"
                fields.append(("position", position))
        fields.extend(
            (key.replace("_", " "), value)
            for key, value in diagnostic.details
            if key in _ALLOWED_DETAIL_KEYS
        )
        lines.extend(field_block(fields, indent=2, width=bounded_width))
        if diagnostic.remediation:
            lines.extend(("", "Next steps:"))
            for remediation in diagnostic.remediation:
                lines.extend(_indented_lines(remediation, indent=2, width=bounded_width))
    lines.extend(("", "Recovery:"))
    for choice in failure.choices:
        lines.extend(_indented_lines(_RECOVERY_LABELS[choice], indent=2, width=bounded_width))
    return tuple(lines)
