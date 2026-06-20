"""list command (WP-18). Catalog view with --bundle/--type/--version/--source/--json filters."""

from __future__ import annotations

from typing import Dict, List, Tuple

from ..model import Artifact, ArtifactType, Bundle, Catalog, Err, Ok, Request
from ..source import open_source
from . import _common

# Canonical type display order.
_TYPE_ORDER: Tuple[ArtifactType, ...] = ("skill", "guideline", "mcp", "hook")


def run(request: Request) -> int:
    """List artifacts (and bundles) from the catalog.

    Supports ``--bundle B``, ``--type T``, ``--json``, and combinations thereof.
    ``--version REF`` and ``--source DIR`` are handled by :func:`open_source`.
    """
    # 1. Open source & build catalog.
    src_result = open_source(request)
    if isinstance(src_result, Err):
        print(src_result.reason)
        return _common.exit_code(src_result)
    cat_result = src_result.value.catalog()
    if isinstance(cat_result, Err):
        print(cat_result.reason)
        return _common.exit_code(cat_result)
    catalog: Catalog = cat_result.value

    # 2. Select artifacts.
    artifacts = _select_artifacts(request, catalog)
    if isinstance(artifacts, Err):
        print(artifacts.reason)
        return _common.exit_code(artifacts)
    selected: Tuple[Artifact, ...] = artifacts.value

    # 3. Decide whether to include bundles.
    #    Bundles are shown unless a --type filter is given (DESIGN.md §13).
    show_bundles = request.type_filter is None

    # 4. Output.
    if request.json:
        _print_json(request, selected, catalog, show_bundles)
    else:
        _print_text(selected, catalog, show_bundles)

    return _common.OK


# --------------------------------------------------------------------------- #
# Selection logic                                                              #
# --------------------------------------------------------------------------- #
def _select_artifacts(request: Request, catalog: Catalog):
    """Resolve the artifact selection from the request.

    - ``--bundle B`` (possibly combined with ``--type T``): delegate to
      ``_common.resolve_artifacts`` and then apply type filter.
    - ``--type T`` alone: all artifacts of that type.
    - neither: all artifacts in the catalog.

    Returns ``Ok[Tuple[Artifact, ...]]`` or ``Err``.
    """
    has_bundle = bool(request.bundles)
    has_type = request.type_filter is not None

    if has_bundle:
        # resolve_artifacts handles bundle expansion; apply type_filter afterwards
        # if resolve_artifacts doesn't already respect it for bundle mode.
        result = _common.resolve_artifacts(request, catalog)
        if isinstance(result, Err):
            return result
        arts = result.value
        if has_type:
            arts = tuple(a for a in arts if a.type == request.type_filter)
        return Ok(arts)

    if has_type:
        # All artifacts of the given type.
        arts = tuple(
            a for (t, _), a in catalog.artifacts.items()
            if t == request.type_filter
        )
        return Ok(arts)

    # No selector — everything.
    arts = tuple(catalog.artifacts.values())
    return Ok(arts)


# --------------------------------------------------------------------------- #
# Text output                                                                  #
# --------------------------------------------------------------------------- #
def _print_text(
    artifacts: Tuple[Artifact, ...],
    catalog: Catalog,
    show_bundles: bool,
) -> None:
    """Human-readable grouped listing."""
    grouped = _group_by_type(artifacts)

    first_section = True
    for art_type in _TYPE_ORDER:
        items = grouped.get(art_type, [])
        if not items:
            continue
        if not first_section:
            print()
        first_section = False
        for art in sorted(items, key=lambda a: a.name):
            print(f"{art.type:<12s}{art.name}")

    if show_bundles and catalog.bundles:
        if not first_section:
            print()
        print("bundles:")
        for name in sorted(catalog.bundles):
            bundle = catalog.bundles[name]
            extends_str = ""
            if bundle.extends:
                extends_str = f"  (extends: {', '.join(bundle.extends)})"
            print(f"  {name:<14s}{bundle.description}{extends_str}")


def _group_by_type(
    artifacts: Tuple[Artifact, ...],
) -> Dict[ArtifactType, List[Artifact]]:
    groups: Dict[ArtifactType, List[Artifact]] = {}
    for art in artifacts:
        groups.setdefault(art.type, []).append(art)
    return groups


# --------------------------------------------------------------------------- #
# JSON output                                                                  #
# --------------------------------------------------------------------------- #
def _print_json(
    request: Request,
    artifacts: Tuple[Artifact, ...],
    catalog: Catalog,
    show_bundles: bool,
) -> None:
    """Stable JSON shape (DESIGN.md §13)."""
    obj: dict = {
        "version": request.version or "main",
        "artifacts": [
            {"type": a.type, "name": a.name, "root": a.root}
            for a in sorted(artifacts, key=lambda a: (_TYPE_ORDER.index(a.type), a.name))
        ],
    }
    if show_bundles:
        obj["bundles"] = [
            _bundle_to_dict(catalog.bundles[name])
            for name in sorted(catalog.bundles)
        ]
    _common.print_json(obj)


def _bundle_to_dict(bundle: Bundle) -> dict:
    includes: dict = {}
    for art_type in _TYPE_ORDER:
        names = bundle.includes.get(art_type, ())
        if names:
            includes[art_type] = list(names)
    return {
        "name": bundle.name,
        "description": bundle.description,
        "extends": list(bundle.extends),
        "includes": includes,
    }
