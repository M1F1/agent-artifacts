"""Shared command helpers (Wave 2 integration glue).

These are the small, cross-cutting pieces every command needs: the exit-code vocabulary
(PLAN.md §7), consumer-project / manifest paths, manifest load, target & profile resolution,
and JSON output. Pure-ish: the only IO is reading the manifest file (via io.fs). Commands
own their own orchestration and import from here read-only — this module is shared and must
not grow command-specific logic.
"""

from __future__ import annotations

import json
import os
from typing import List, Tuple

from .. import fp
from ..catalog import resolve_bundle
from ..io import fs
from ..manifest import empty_manifest, parse_manifest
from ..model import (
    Artifact,
    ArtifactType,
    Catalog,
    Err,
    Manifest,
    Ok,
    Profile,
    Request,
    Result,
)
from ..profiles.loader import load_profiles

# --- exit codes (PLAN.md §7) ------------------------------------------------ #
OK = 0
ERROR = 1            # generic failure
USAGE = 2            # bad invocation / unknown name
NETWORK = 3          # network / remote failure
CONFLICT = 4         # conflict needs --force
CORRUPT_MANIFEST = 5

# Default source-of-truth repo (compiled in; overridable via --repo / Request.repo, DESIGN.md §17).
DEFAULT_REPO = "org/agent-artifacts"

_TYPES: Tuple[ArtifactType, ...] = ("skill", "guideline", "mcp", "hook")


# --- project / repo / manifest paths --------------------------------------- #
def project_root(request: Request) -> str:
    """The consumer project directory (defaults to the current working directory)."""
    return request.project or "."


def repo_of(request: Request) -> str:
    return request.repo or DEFAULT_REPO


def manifest_path(project: str) -> str:
    return os.path.join(project, ".agent-artifacts", "manifest.json")


def load_manifest(request: Request) -> Result:
    """Load the consumer manifest -> Ok[Manifest]; missing file -> Ok[empty]; corrupt -> Err(5)."""
    project = project_root(request)
    path = manifest_path(project)
    if not fs.exists(path):
        return Ok(empty_manifest(repo_of(request)))
    try:
        text = fs.read_text(path)
    except OSError as exc:  # pragma: no cover - defensive
        return Err(f"cannot read manifest at {path}: {exc}", code=ERROR)
    return parse_manifest(text)  # Err(code=5) on corruption


# --- result -> process exit code ------------------------------------------- #
def exit_code(result: Result) -> int:
    """Map a `Result` to a process exit code (Ok -> 0, Err -> its `.code`)."""
    return OK if isinstance(result, Ok) else getattr(result, "code", ERROR)


def print_json(obj) -> None:
    print(json.dumps(obj, indent=2, sort_keys=False))


# --- target (artifact) resolution ------------------------------------------ #
def resolve_artifacts(request: Request, catalog: Catalog) -> Result:
    """Resolve the requested ``--all`` / ``--bundle`` / ``NAME…`` selection to artifacts.

    Returns ``Ok[Tuple[Artifact, ...]]`` (ordered, de-duplicated) or an `Err` listing every
    unresolved name/bundle (accumulated). Honors ``request.type_filter`` for bare names.
    """
    if request.all:
        arts = [a for (t, _), a in catalog.artifacts.items()
                if request.type_filter in (None, t)]
        return Ok(_dedup(arts))

    out: List[Artifact] = []
    errs: List[Err] = []

    for bundle_name in request.bundles:
        res = resolve_bundle(catalog, bundle_name)
        if isinstance(res, Err):
            errs.append(res)
            continue
        for (t, name) in res.value.artifacts:
            art = catalog.artifacts.get((t, name))
            if art is None:
                errs.append(Err(f"bundle {bundle_name!r}: unresolved artifact {name!r}", code=USAGE))
            else:
                out.append(art)

    for name in request.names:
        matches = _lookup_name(catalog, name, request.type_filter)
        if not matches:
            errs.append(Err(f"unknown artifact {name!r}", code=USAGE))
        else:
            out.extend(matches)

    if errs:
        return Err("; ".join(e.reason for e in errs), code=USAGE)
    return Ok(_dedup(out))


def _lookup_name(catalog: Catalog, name: str, type_filter) -> List[Artifact]:
    if type_filter is not None:
        art = catalog.artifacts.get((type_filter, name))
        return [art] if art is not None else []
    return [catalog.artifacts[(t, name)] for t in _TYPES if (t, name) in catalog.artifacts]


def _dedup(arts) -> Tuple[Artifact, ...]:
    seen = set()
    out = []
    for a in arts:
        key = (a.type, a.name)
        if key not in seen:
            seen.add(key)
            out.append(a)
    return tuple(out)


# --- profile resolution ----------------------------------------------------- #
def resolve_profiles(request: Request) -> Result:
    """Resolve ``--profile P,P`` to ``Ok[Tuple[Tuple[str, Profile], ...]]`` or an `Err`.

    Empty selection is a usage error for write commands (the caller decides whether to default).
    """
    available = load_profiles(project_root(request))
    if not request.profiles:
        return Err("no profile selected (use --profile NAME[,NAME])", code=USAGE)
    out: List[Tuple[str, Profile]] = []
    for pname in request.profiles:
        prof = available.get(pname)
        if prof is None:
            return Err(f"unknown profile {pname!r} (known: {', '.join(sorted(available))})", code=USAGE)
        out.append((pname, prof))
    return Ok(tuple(out))
