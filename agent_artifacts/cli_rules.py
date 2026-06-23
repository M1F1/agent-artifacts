"""Semantic flag-combination validation (GitHub issue #4 + full Class 2).

The argparse layer (``cli.build_parser``) checks *syntax*: known flags, valid choices, required
positionals. It cannot see that two individually-valid flags make no sense *together*, or that a
global flag attached to every subcommand via the shared ``glob`` parent is silently ignored by a
particular command. Both gaps let a user express an intent the tool then quietly drops.

This module is the missing *semantic* layer: one pure function, :func:`validate_flags`, that maps
a parsed :class:`~agent_artifacts.model.Request` to ``Optional[Err]`` (errors as values, DESIGN.md
§14). ``cli.main`` calls it as a thin wiring step between ``_to_request`` and dispatch; a returned
``Err`` is printed to stderr and becomes exit code ``2`` (``USAGE``) — the same code argparse uses
for its own usage errors (PLAN.md §7).

Two failure classes are covered (see issue #4 for the motivating discussion):

**Class 1 — silent precedence.** Two flags that both feed one decision, where the core silently
lets one win:

* ``--repo`` + ``--source`` — both name the catalog source; ``source.open_source`` short-circuits
  on ``--source`` and never looks at ``--repo``.
* ``--source`` + ``--version`` — a local checkout has no ref to resolve, so ``--version`` is
  dropped on the floor.
* ``--all`` + ``NAME`` / ``--bundle`` — ``--all`` expands to the whole catalog and the explicit
  selectors are ignored (``_common.resolve_artifacts`` / ``upstreams.select_upstreams``).

**Class 2 — inherited-but-ignored globals.** The ``glob`` parent attaches ``--repo``/``--project``/
``--source`` to every subcommand, but most commands read only a subset. Passing one a command never
consumes is a no-op today; here it becomes an explicit usage error with a command-specific message.
The per-command forbidden set (:data:`_FORBIDDEN`) is derived from which globals each command's
``run`` actually reads.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

from .commands._common import USAGE
from .model import Err, Request

# Request field name -> the flag spelling to show in diagnostics.
_FLAG: Dict[str, str] = {
    "repo": "--repo",
    "project": "--project",
    "source_dir": "--source",
    "version": "--version",
}

# Globals a command accepts on the parser (via the shared ``glob`` parent) but never reads. Keyed
# by command, and by ``"upstream:<action>"`` for the nested maintainer subcommands. Each tuple
# lists the ``Request`` fields whose presence is a silent no-op for that command — rejecting them
# turns "quietly ignored" into an explicit usage error. Commands absent from this map (``install``,
# ``update``) consume every global they accept.
_FORBIDDEN: Dict[str, Tuple[str, ...]] = {
    "list": ("project",),                  # lists the source catalog; never touches the project
    "uninstall": ("repo", "source_dir"),   # reverses from the manifest; no source is opened
    "status": ("source_dir",),             # local-only; reads the manifest, not the source
    "check": ("source_dir",),              # remote-only freshness check against --repo@--version
    "upgrade": ("project", "source_dir"),  # self-update from --repo@--version or a local wheel
    "upstream:check": ("repo", "project"),    # operates on the catalog repo (--source / cwd)
    "upstream:update": ("repo", "project"),   # ""
    "upstream:add": ("repo", "project"),      # ""
}


def _context(request: Request) -> Tuple[str, str]:
    """Return ``(lookup_key, human_label)`` for `request`'s (sub)command.

    The nested ``upstream`` verbs are disambiguated by their action so both the `_FORBIDDEN`
    lookup and the error message name the exact subcommand (e.g. ``"upstream check"``).
    """
    if request.command == "upstream" and request.upstream_action:
        return f"upstream:{request.upstream_action}", f"upstream {request.upstream_action}"
    return request.command, request.command


def validate_flags(request: Request) -> Optional[Err]:
    """Return an ``Err(code=USAGE)`` for an incompatible flag combination, else ``None``.

    Class 2 (forbidden-here globals) is checked first so the user gets the most specific message
    — "``status does not accept --source``" beats the generic mutual-exclusion text when both
    could apply. The Class 1 pairwise rules then run globally; they are naturally scoped, because
    the conflicting flag only survives to this point on commands that genuinely accept both (any
    forbidden side was already rejected above, and flags a command never attaches stay ``None``).
    """
    key, label = _context(request)

    # Class 2 — a global this command never reads was supplied.
    for field in _FORBIDDEN.get(key, ()):
        if getattr(request, field) is not None:
            return Err(f"{label} does not accept {_FLAG[field]}", code=USAGE)

    # Class 1 — silent-precedence conflicts among flags the command does accept.
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
