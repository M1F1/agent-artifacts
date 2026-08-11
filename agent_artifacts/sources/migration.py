"""Plan the v1 -> v2 (ref-aware) source-store migration.

Planning is a pure function of the configuration and the directory names that actually exist, so a
migration can be reviewed — including as JSON — before any user data moves.  See
``docs/design/DESIGN-src02-ref-aware-sources.md``.

The planner refuses two situations rather than resolving them:

* a legacy *and* a ref-aware directory both exist for one source — both hold real pointers, and a
  rename would destroy one of them;
* one legacy directory could belong to either of two configured refs — ``current.json`` records a
  resolved revision, not the ref it was configured from, so attributing it would be a guess.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from agent_artifacts.configuration.model import UserConfiguration
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import SourceAlias
from agent_artifacts.domain.result import Err, Ok, Result

from .model import legacy_source_instance_id, source_instance_id

SOURCE_STORE_SCHEMA_VERSION = 2
SOURCE_STORE_VERSION_FILE = "store.json"

SOURCE_STORE_CONFLICT = DiagnosticCode("source-store-conflict")
SOURCE_STORE_AMBIGUOUS = DiagnosticCode("source-store-ambiguous")


class RebindAction(str, Enum):
    REBIND = "rebind"


@dataclass(frozen=True, slots=True)
class SourceStoreRebind:
    """One directory rename that re-keys a stored source to its ref-aware identity."""

    alias: SourceAlias
    source_directory: str
    target_directory: str
    action: RebindAction = RebindAction.REBIND


@dataclass(frozen=True, slots=True)
class SourceStoreMigrationPlan:
    rebinds: tuple[SourceStoreRebind, ...]
    stored_schema_version: int | None
    schema_version: int = SOURCE_STORE_SCHEMA_VERSION

    @property
    def required(self) -> bool:
        """Whether applying this plan would change anything on disk."""

        return bool(self.rebinds) or self.stored_schema_version != self.schema_version


def _error(code: DiagnosticCode, message: str, *remediation: str) -> Err:
    return Err((Diagnostic(code, Severity.ERROR, message, remediation=remediation),))


def plan_source_store_migration(
    configuration: UserConfiguration,
    *,
    existing: tuple[str, ...],
    stored_schema_version: int | None = None,
) -> Result[SourceStoreMigrationPlan]:
    """Plan the rebinds needed to move a v1 source store to ref-aware identities."""

    if stored_schema_version == SOURCE_STORE_SCHEMA_VERSION:
        return Ok(SourceStoreMigrationPlan((), stored_schema_version))
    present = frozenset(existing)

    # A legacy directory is shared by every configured source with the same origin.  In a v1
    # configuration that was always exactly one source; more than one means the configuration was
    # authored after ref-awareness and the legacy directory cannot be attributed.
    by_legacy: dict[str, list[SourceAlias]] = {}
    for source in configuration.sources:
        if source.ref is None:
            continue
        by_legacy.setdefault(legacy_source_instance_id(source).value, []).append(source.alias)

    rebinds: list[SourceStoreRebind] = []
    for source in configuration.sources:
        if source.ref is None:
            continue
        legacy = legacy_source_instance_id(source).value
        target = source_instance_id(source).value
        if legacy == target or legacy not in present:
            continue
        claimants = by_legacy[legacy]
        if len(claimants) > 1:
            aliases = ", ".join(sorted(alias.value for alias in claimants))
            return _error(
                SOURCE_STORE_AMBIGUOUS,
                f"legacy source directory {legacy} could belong to any of: {aliases}",
                "synchronize these sources to create correct per-ref directories",
                f"then remove the unattributable legacy directory {legacy}",
            )
        if target in present:
            return _error(
                SOURCE_STORE_CONFLICT,
                f"both a legacy ({legacy}) and a ref-aware ({target}) directory exist for "
                f"source {source.alias}",
                "inspect both directories and remove the one that is no longer current",
            )
        rebinds.append(SourceStoreRebind(source.alias, legacy, target))
    return Ok(
        SourceStoreMigrationPlan(
            tuple(sorted(rebinds, key=lambda item: item.alias.value)),
            stored_schema_version,
        )
    )


__all__ = [
    "SOURCE_STORE_AMBIGUOUS",
    "SOURCE_STORE_CONFLICT",
    "SOURCE_STORE_SCHEMA_VERSION",
    "SOURCE_STORE_VERSION_FILE",
    "RebindAction",
    "SourceStoreMigrationPlan",
    "SourceStoreRebind",
    "plan_source_store_migration",
]
