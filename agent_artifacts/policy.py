"""Update policy — pure (WP-2). The per-file decision table from DESIGN.md §9.

`classify` is total over ``(disk, base, new)`` hash triples (each may be ``None``):
  - ``disk`` — hash of the file currently on disk, or None if absent
  - ``base`` — hash recorded in the manifest at install time, or None if we never installed it
  - ``new``  — hash of the incoming version from the source, or None if removed upstream

`decision_action` turns a decision into Plan `Action`s. Conflicts never overwrite silently:
they write ``<file>.agent-artifacts-new`` and warn (unless `force`).
"""

from __future__ import annotations

from typing import Literal, Optional, Tuple

from .model import Action, RemovePath, Warn, WriteFile

# "remove" extends the DESIGN.md §9 table to keep `classify` total (upstream-deleted files).
Decision = Literal["create", "noop", "overwrite", "keep-drift", "conflict", "remove"]

NEW_SUFFIX = ".agent-artifacts-new"


def classify(disk: Optional[str], base: Optional[str], new: Optional[str]) -> Decision:
    if new is None:  # removed in the new version
        if disk is None:
            return "noop"
        return "remove" if disk == base else "keep-drift"
    if disk is None:  # missing locally -> (re)create
        return "create"
    if base is None:  # never installed by us, yet a file exists on disk
        return "noop" if disk == new else "conflict"
    if disk == base:
        return "noop" if new == base else "overwrite"
    # disk != base (locally modified)
    return "keep-drift" if new == base else "conflict"


def decision_action(
    decision: Decision,
    path: str,
    content: Optional[bytes],
    *,
    force: bool = False,
) -> Tuple[Action, ...]:
    if decision in ("create", "overwrite"):
        return (WriteFile(path=path, content=content or b""),)
    if decision == "noop":
        return ()
    if decision == "remove":
        return (RemovePath(path=path),)
    if decision == "keep-drift":
        return (Warn(message=f"drift: kept local changes to {path}"),)
    if decision == "conflict":
        if force:
            return (WriteFile(path=path, content=content or b""),
                    Warn(message=f"forced overwrite of locally-modified {path}"))
        return (WriteFile(path=path + NEW_SUFFIX, content=content or b""),
                Warn(message=f"conflict: {path} changed both locally and upstream; "
                             f"wrote {path}{NEW_SUFFIX} (use --force to overwrite)"))
    raise ValueError(f"unknown decision: {decision!r}")  # pragma: no cover
