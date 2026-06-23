"""Generic merge engine — pure (WP-3). Drives MCP (`key`) and hooks (`list`), DESIGN.md §10.

Operates on an already-loaded config `dict` (the shell reads/writes the file). Produces a
`MergeJson` Action or an `Err` on a key collision. Idempotency for list-mode (don't append a
deeply-equal entry twice) is enforced by the executor's performer (WP-9).
"""

from __future__ import annotations

import re
from typing import Mapping, Optional, Tuple

from .model import Err, MergeJson, MergeSpec, Ok, Result

_PLACEHOLDER = re.compile(r"\$\{([^}]+)\}")


def render(template, descriptor: Mapping):
    """Fill ``${field}`` placeholders from `descriptor`, preserving type for whole-field refs."""
    if isinstance(template, str):
        whole = _PLACEHOLDER.fullmatch(template)
        if whole:
            return descriptor.get(whole.group(1))
        return _PLACEHOLDER.sub(lambda m: str(descriptor.get(m.group(1), "")), template)
    if isinstance(template, Mapping):
        return {k: render(v, descriptor) for k, v in template.items()}
    if isinstance(template, (list, tuple)):
        return [render(v, descriptor) for v in template]
    return template


def identity_of(spec: MergeSpec, descriptor: Mapping) -> Tuple[Tuple[str, object], ...]:
    """Stable identity from the descriptor's `spec.identity` fields (used in the manifest)."""
    return tuple((field, descriptor.get(field)) for field in spec.identity)


def _dig(obj, json_path: str):
    cur = obj
    for part in json_path.split("."):
        if not isinstance(cur, Mapping) or part not in cur:
            return None
        cur = cur[part]
    return cur


def plan_merge(
    spec: MergeSpec,
    value,
    existing: Mapping,
    *,
    key: Optional[str] = None,
    force: bool = False,
) -> Result:
    """Plan one merge into `existing` config.

    key-mode: set ``<json_path>.<key> = value``; collision (key present, different value)
    is an `Err` unless `force`. list-mode: append `value` to the array at ``<json_path>``.
    """
    container = _dig(existing, spec.json_path)
    if spec.mode == "key":
        if key is None:
            return Err("key-mode merge requires a key")
        current = container.get(key) if isinstance(container, Mapping) else None
        overwrote = current is not None and current != value
        if overwrote and not force:
            return Err(
                f"'{spec.json_path}.{key}' already exists and differs; use --force",
                code=4,
            )
        return Ok(
            MergeJson(
                file=spec.file, json_path=spec.json_path, mode="key", value=value, identity=(key,)
            )
        )
    # list-mode: coexist with foreign entries; executor dedups by deep equality.
    return Ok(
        MergeJson(file=spec.file, json_path=spec.json_path, mode="list", value=value, identity=())
    )
