"""Pure presentation context for expected wizard-stage failures."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from agent_artifacts.domain.diagnostics import Diagnostic
from agent_artifacts.domain.result import Err
from agent_artifacts.wizard import WizardSession, WizardStage

WizardOperation = Literal["load", "review", "finalize", "setup", "reporting"]
WizardRecoveryChoice = Literal["retry", "back", "quit"]


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
) -> WizardStageFailure:
    """Add stage context without transforming the domain diagnostics themselves."""

    choices: tuple[WizardRecoveryChoice, ...] = (
        ("retry", "back", "quit") if operation == "load" else ("back", "quit")
    )
    return WizardStageFailure(
        stage=session.current,
        operation=operation,
        diagnostics=result.diagnostics,
        action=session.action,
        scope=session.scope,
        project=None,
        recoverable=operation == "load",
        choices=choices,
    )
