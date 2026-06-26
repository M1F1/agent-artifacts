"""Semantic flag-combination validation (GitHub issue #4 + full Class 1).

The argparse layer (``cli.build_parser``) checks *syntax*: known flags, valid choices, required
positionals. It cannot see that two individually-valid flags make no sense *together*.

This module is the missing *semantic* layer: one pure function, :func:`validate_flags`, that maps
a parsed :class:`~agent_artifacts.model.Request` to ``Optional[Err]`` (errors as values, docs/design/DESIGN.md
§14). ``cli.main`` calls it as a thin wiring step between ``_to_request`` and dispatch; a returned
``Err`` is printed to stderr and becomes exit code ``2`` (``USAGE``) — the same code argparse uses
for its own usage errors (docs/plan/PLAN.md §7).

**Class 1 — silent precedence.** Two flags that both feed one decision, where the core silently
lets one win:

* ``--repo`` + ``--source`` — both name the catalog source; ``source.open_source`` short-circuits
  on ``--source`` and never looks at ``--repo``.
* ``--source`` + ``--version`` — a local checkout has no ref to resolve, so ``--version`` is
  dropped on the floor.
* ``--all`` + ``NAME`` / ``--bundle`` — ``--all`` expands to the whole catalog and the explicit
  selectors are ignored (``_common.resolve_artifacts`` / ``upstreams.select_upstreams``).
"""

from __future__ import annotations

from typing import Optional

from .commands._common import USAGE
from .model import Err, Request


def validate_flags(request: Request) -> Optional[Err]:
    """Return an ``Err(code=USAGE)`` for an incompatible flag combination, else ``None``.

    Checks cross-cutting rules argparse cannot express:
    * --repo and --source are mutually exclusive
    * --source and --version are mutually exclusive
    * --all cannot be combined with named artifacts or --bundle
    """
    if request.repo is not None and request.source_dir is not None:
        return Err(
            "--repo and --source are mutually exclusive (both name the catalog source)",
            code=USAGE,
        )
    if request.source_dir is not None and request.version is not None:
        return Err(
            "--source and --version are mutually exclusive "
            "(a local checkout has no ref to resolve)",
            code=USAGE,
        )
    if request.all and (request.names or request.bundles):
        return Err(
            "--all cannot be combined with named artifacts or --bundle",
            code=USAGE,
        )

    return None
