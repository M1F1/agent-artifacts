"""Catalog parsing & bundle resolution — pure (WP-1).

Parses artifacts/bundles from already-read text into the `model` records and resolves a
bundle (expand `extends` with cycle detection, merge `pins`, validate references).
Reading files from disk is the shell's job (source.py / io.fs); this module is pure.
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional, Tuple

from . import compatibility, fp
from .fp import Err, Ok
from .model import Artifact, ArtifactType, Bundle, Catalog, ResolvedBundle, Result

_TODO = "WP-1: not implemented"

# Ordered artifact-type sections inside a bundle's `includes`.
_INCLUDE_TYPES: Tuple[ArtifactType, ...] = ("skill", "guideline", "mcp", "hook", "memory")

# Install modes a declared `memory` frontmatter `mode:` may name (DESIGN-memory.md §3.2/§3.4).
_MEMORY_MODES: Tuple[str, ...] = ("replace", "prepend", "append", "skip")


# --------------------------------------------------------------------------- #
# Frontmatter — parse YAML-ish `key: value` block by hand (no pyyaml).         #
# --------------------------------------------------------------------------- #
def _split_frontmatter(text: str) -> Tuple[bool, Dict[str, str], str]:
    """Return ``(found, fields, body)``.

    A frontmatter block is the region between a leading ``---`` line and the next
    ``---`` line. Only flat ``key: value`` scalar pairs are parsed (enough for the
    `name`/`description` keys artifacts use). ``found`` is False when there is no
    leading ``---`` delimiter at all.
    """
    lines = text.splitlines()
    # Skip a leading BOM / blank lines before the opening fence.
    idx = 0
    while idx < len(lines) and lines[idx].strip() == "":
        idx += 1
    if idx >= len(lines) or lines[idx].strip() != "---":
        return False, {}, text

    fields: Dict[str, str] = {}
    closed = False
    body_start = len(lines)
    for j in range(idx + 1, len(lines)):
        if lines[j].strip() == "---":
            closed = True
            body_start = j + 1
            break
        raw = lines[j]
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if ":" not in raw:
            continue
        key, _, value = raw.partition(":")
        fields[key.strip()] = _unquote(value.strip())

    if not closed:
        # An opening fence with no closing fence is malformed.
        return True, fields, ""
    body = "\n".join(lines[body_start:])
    return True, fields, body


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def _frontmatter_well_formed(text: str) -> bool:
    """True only when a leading ``---`` fence is also properly closed."""
    lines = text.splitlines()
    idx = 0
    while idx < len(lines) and lines[idx].strip() == "":
        idx += 1
    if idx >= len(lines) or lines[idx].strip() != "---":
        return False
    return any(lines[j].strip() == "---" for j in range(idx + 1, len(lines)))


# --------------------------------------------------------------------------- #
# Artifact parsers (all pure, operate on already-read text).                   #
# --------------------------------------------------------------------------- #
def parse_skill(text: str, name: str) -> Result:
    """Parse a SKILL.md: require a closed frontmatter block with a matching ``name``."""
    if not _frontmatter_well_formed(text):
        return Err(f"skill {name!r}: missing or unterminated YAML frontmatter")
    _, fields, _ = _split_frontmatter(text)
    if "name" not in fields:
        return Err(f"skill {name!r}: frontmatter missing required 'name' key")
    if fields["name"] != name:
        return Err(f"skill {name!r}: frontmatter name {fields['name']!r} does not match {name!r}")
    compat = compatibility.compatibility_from_frontmatter(fields, f"skill {name!r}")
    if isinstance(compat, Err):
        return compat
    return Ok(
        Artifact(
            type="skill",
            name=name,
            root=f"skills/{name}",
            compatibility=compat.value,
        )
    )


def parse_guideline(text: str, name: str) -> Result:
    """Parse a guideline markdown file. Frontmatter is optional; if present it must
    close and any ``name`` it declares must match."""
    found, fields, _ = _split_frontmatter(text)
    if found:
        if not _frontmatter_well_formed(text):
            return Err(f"guideline {name!r}: unterminated YAML frontmatter")
        if "name" in fields and fields["name"] != name:
            return Err(
                f"guideline {name!r}: frontmatter name {fields['name']!r} does not match {name!r}"
            )
    compat = compatibility.compatibility_from_frontmatter(fields, f"guideline {name!r}")
    if isinstance(compat, Err):
        return compat
    return Ok(
        Artifact(
            type="guideline",
            name=name,
            root=f"guidelines/{name}.md",
            compatibility=compat.value,
        )
    )


def parse_memory(text: str, name: str) -> Result:
    """Parse an ``memory/<name>.md`` instruction-file artifact (DESIGN-memory.md §3.1).

    Frontmatter is optional (like a guideline); if present it must close. A declared
    ``name`` must match, and a declared ``mode`` must be one of
    ``replace|prepend|append|skip`` (DESIGN-memory.md §3.2). The body is the verbatim
    instruction content (not inspected here)."""
    found, fields, _ = _split_frontmatter(text)
    if found:
        if not _frontmatter_well_formed(text):
            return Err(f"memory {name!r}: unterminated YAML frontmatter")
        if "name" in fields and fields["name"] != name:
            return Err(
                f"memory {name!r}: frontmatter name {fields['name']!r} does not match {name!r}"
            )
        if "mode" in fields and fields["mode"] not in _MEMORY_MODES:
            return Err(
                f"memory {name!r}: invalid mode {fields['mode']!r} "
                f"(expected one of {', '.join(_MEMORY_MODES)})"
            )
    compat = compatibility.compatibility_from_frontmatter(fields, f"memory {name!r}")
    if isinstance(compat, Err):
        return compat
    return Ok(
        Artifact(
            type="memory",
            name=name,
            root=f"memory/{name}.md",
            compatibility=compat.value,
        )
    )


def parse_mcp(text: str, name: str) -> Result:
    """Parse an ``mcp/<name>.json`` server definition: require ``name`` and ``server``."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        return Err(f"mcp {name!r}: invalid JSON ({exc})")
    if not isinstance(data, dict):
        return Err(f"mcp {name!r}: expected a JSON object")
    missing = [k for k in ("name", "server") if k not in data]
    if missing:
        return Err(f"mcp {name!r}: missing required key(s) {', '.join(missing)}")
    if data["name"] != name:
        return Err(f"mcp {name!r}: declared name {data['name']!r} does not match {name!r}")
    compat = compatibility.compatibility_from_json(data, f"mcp {name!r}")
    if isinstance(compat, Err):
        return compat
    return Ok(
        Artifact(
            type="mcp",
            name=name,
            root=f"mcp/{name}.json",
            compatibility=compat.value,
        )
    )


def parse_hook(text: str, name: str) -> Result:
    """Parse a ``hooks/<name>/hook.json`` descriptor: require ``name``, ``events``, ``command``."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        return Err(f"hook {name!r}: invalid JSON ({exc})")
    if not isinstance(data, dict):
        return Err(f"hook {name!r}: expected a JSON object")
    missing = [k for k in ("name", "events", "command") if k not in data]
    if missing:
        return Err(f"hook {name!r}: missing required key(s) {', '.join(missing)}")
    if data["name"] != name:
        return Err(f"hook {name!r}: declared name {data['name']!r} does not match {name!r}")
    compat = compatibility.compatibility_from_json(data, f"hook {name!r}")
    if isinstance(compat, Err):
        return compat
    return Ok(
        Artifact(
            type="hook",
            name=name,
            root=f"hooks/{name}",
            compatibility=compat.value,
        )
    )


def parse_bundle(text: str, name: str) -> Result:
    """Parse a ``bundles/<name>.json`` into a `Bundle`.

    Optional keys default to empty. ``extends`` becomes a tuple; ``includes`` a
    mapping of artifact-type -> tuple of names; ``pins`` a plain mapping.
    """
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        return Err(f"bundle {name!r}: invalid JSON ({exc})")
    if not isinstance(data, dict):
        return Err(f"bundle {name!r}: expected a JSON object")

    description = data.get("description", "")
    if not isinstance(description, str):
        return Err(f"bundle {name!r}: 'description' must be a string")

    extends_raw = data.get("extends", [])
    if not isinstance(extends_raw, list) or not all(isinstance(e, str) for e in extends_raw):
        return Err(f"bundle {name!r}: 'extends' must be a list of strings")
    extends = tuple(extends_raw)

    includes_raw = data.get("includes", {})
    if not isinstance(includes_raw, dict):
        return Err(f"bundle {name!r}: 'includes' must be an object")
    includes: Dict[ArtifactType, Tuple[str, ...]] = {}
    for section, names in includes_raw.items():
        artifact_type = _section_to_type(section)
        if artifact_type is None:
            return Err(f"bundle {name!r}: unknown includes section {section!r}")
        if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
            return Err(f"bundle {name!r}: includes.{section} must be a list of strings")
        includes[artifact_type] = tuple(names)

    pins_raw = data.get("pins", {})
    if not isinstance(pins_raw, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in pins_raw.items()
    ):
        return Err(f"bundle {name!r}: 'pins' must be an object of string -> string")
    pins = dict(pins_raw)

    return Ok(
        Bundle(
            name=name,
            description=description,
            extends=extends,
            includes=includes,
            pins=pins,
        )
    )


def _section_to_type(section: str) -> Optional[ArtifactType]:
    """Map an `includes` section key to an `ArtifactType` (plural or singular)."""
    mapping: Dict[str, ArtifactType] = {
        "skills": "skill",
        "skill": "skill",
        "guidelines": "guideline",
        "guideline": "guideline",
        "mcp": "mcp",
        "mcps": "mcp",
        "hooks": "hook",
        "hook": "hook",
        "memory": "memory",
        "memories": "memory",
    }
    return mapping.get(section)


# --------------------------------------------------------------------------- #
# Bundle resolution — expand `extends`, merge `pins`, validate references.      #
# --------------------------------------------------------------------------- #
def resolve_bundle(catalog: Catalog, name: str) -> Result:
    """Expand `extends` (union, cycle detection), merge `pins`, validate -> Ok[ResolvedBundle].

    - ``extends`` is expanded recursively. A cycle anywhere in the chain -> `Err`.
    - The resolved artifact set is the ordered, de-duplicated union of every bundle's
      ``includes`` along the chain (base bundles contribute first; a derived bundle's
      own includes come last).
    - ``pins`` merge with **derived-bundle-wins** on conflict.
    - Every referenced ``(type, name)`` must exist in ``catalog.artifacts``; all dangling
      references are accumulated into a single `Err`.
    """
    if name not in catalog.bundles:
        return Err(f"bundle {name!r}: not found in catalog")

    ordered_artifacts: List[Tuple[ArtifactType, str]] = []
    seen: set = set()
    pins: Dict[str, str] = {}

    def visit(bundle_name: str, stack: Tuple[str, ...]) -> Result:
        if bundle_name in stack:
            chain = " -> ".join(stack + (bundle_name,))
            return Err(f"bundle {name!r}: cycle in extends ({chain})")
        if bundle_name not in catalog.bundles:
            return Err(f"bundle {name!r}: extends unknown bundle {bundle_name!r}")
        bundle = catalog.bundles[bundle_name]
        # Bases first (depth-first), so derived includes/pins land later and win.
        for parent in bundle.extends:
            res = visit(parent, stack + (bundle_name,))
            if isinstance(res, Err):
                return res
        for artifact_type in _INCLUDE_TYPES:
            for artifact_name in bundle.includes.get(artifact_type, ()):
                key = (artifact_type, artifact_name)
                if key not in seen:
                    seen.add(key)
                    ordered_artifacts.append(key)
        # Derived-wins: later assignment overwrites an earlier (base) pin.
        for pin_name, pin_ref in bundle.pins.items():
            pins[pin_name] = pin_ref
        return Ok(None)

    walk = visit(name, ())
    if isinstance(walk, Err):
        return walk

    # Validate every referenced artifact exists; accumulate all dangling refs.
    checks = [
        Ok(key)
        if key in catalog.artifacts
        else Err(f"bundle {name!r}: dangling reference {key[0]} {key[1]!r}")
        for key in ordered_artifacts
    ]
    collected = fp.collect(checks)
    if isinstance(collected, Err):
        return collected

    return Ok(
        ResolvedBundle(
            name=name,
            artifacts=tuple(ordered_artifacts),
            pins=pins,
        )
    )


def validate_catalog(catalog: Catalog) -> Tuple:
    """Resolve every bundle; return a tuple of `Err` for each problem (empty == valid)."""
    errors: List[Err] = []
    for bundle_name in catalog.bundles:
        res = resolve_bundle(catalog, bundle_name)
        if isinstance(res, Err):
            errors.append(res)
    return tuple(errors)
