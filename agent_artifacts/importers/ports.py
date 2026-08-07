"""Effect ports for staging and applying reviewed importer output."""

from __future__ import annotations

from typing import Protocol

from agent_artifacts.domain.identifiers import ObjectDigest
from agent_artifacts.domain.result import Result
from agent_artifacts.protocol.native_tree import SourceSnapshot

from .model import AppliedImport, StagedImport


class ImportOutputPort(Protocol):
    def current(self) -> Result[SourceSnapshot | None]: ...

    def stage(
        self, snapshot: SourceSnapshot, output_digest: ObjectDigest
    ) -> Result[StagedImport]: ...

    def apply(
        self,
        staged: StagedImport,
        *,
        expected_destination_digest: ObjectDigest | None,
        changed_paths: int,
    ) -> Result[AppliedImport]: ...

    def discard(self, staged: StagedImport) -> Result[None]: ...
