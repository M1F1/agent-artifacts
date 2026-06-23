"""Pure planning helpers for maintainer-side upstream check/update."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping, Optional, Tuple

from .model import CopyTree, Err, Ok, Plan, RemovePath, Result, Warn, WriteFile
from .upstream_source import ResolvedUpstream
from .upstreams import UpstreamEntry, UpstreamKey

UpstreamState = Literal[
    "up_to_date",
    "changed",
    "local_drift",
    "missing_upstream",
    "invalid",
    "conflict",
]


@dataclass(frozen=True, slots=True)
class UpstreamStatus:
    key: UpstreamKey
    state: UpstreamState
    base_sha: Optional[str] = None
    head_sha: Optional[str] = None
    base_hash: Optional[str] = None
    head_hash: Optional[str] = None
    message: str = ""


@dataclass(frozen=True, slots=True)
class UpstreamUpdatePlan:
    plan: Plan
    entries: Tuple[UpstreamEntry, ...]
    statuses: Tuple[UpstreamStatus, ...]
    conflict: bool = False


def plan_upstream_check(
    entries: Tuple[UpstreamEntry, ...],
    resolved: Tuple[ResolvedUpstream, ...],
    *,
    local_hashes: Optional[Mapping[object, str]] = None,
    validation_errors: Optional[Mapping[object, str]] = None,
) -> Result:
    by_key = _resolved_by_key(resolved)
    statuses = tuple(
        _status_for(
            entry,
            by_key.get(entry.key),
            local_hashes=local_hashes,
            validation_errors=validation_errors,
            update=False,
        )
        for entry in entries
    )
    return Ok(statuses)


def plan_upstream_update(
    entries: Tuple[UpstreamEntry, ...],
    resolved: Tuple[ResolvedUpstream, ...],
    *,
    force: bool = False,
    local_hashes: Optional[Mapping[object, str]] = None,
    validation_errors: Optional[Mapping[object, str]] = None,
    file_contents: Optional[Mapping[object, bytes]] = None,
    catalog_root: str = "",
) -> Result:
    by_key = _resolved_by_key(resolved)
    statuses = []
    actions = []
    has_conflict = False

    for entry in entries:
        key = entry.key
        resolved_entry = by_key.get(key)
        status = _status_for(
            entry,
            resolved_entry,
            local_hashes=local_hashes,
            validation_errors=validation_errors,
            update=True,
        )

        if status.state == "missing_upstream":
            actions.append(Warn(message=f"{_key_label(key)}: upstream path missing"))
            statuses.append(status)
            continue

        if status.state == "invalid":
            has_conflict = True
            actions.append(
                Warn(message=f"{_key_label(key)}: invalid staged artifact: {status.message}")
            )
            statuses.append(status)
            continue

        if resolved_entry is None:
            statuses.append(status)
            continue

        base_hash = _base_hash(entry)
        local_hash = _local_hash(entry, local_hashes)
        local_clean = _hash_matches(local_hash, base_hash)
        upstream_changed = not _hash_matches(resolved_entry.content_hash, base_hash)

        if status.state == "conflict":
            if not force:
                has_conflict = True
                actions.append(
                    Warn(
                        message=(
                            f"{_key_label(key)}: local catalog and upstream both differ "
                            "from last synced upstream; use --force to overwrite local changes"
                        )
                    )
                )
                sidecar = _sidecar_actions(entry, resolved_entry, file_contents, catalog_root)
                if isinstance(sidecar, Err):
                    actions.append(
                        Warn(
                            message=(
                                f"{_key_label(key)}: could not stage upstream candidate: "
                                f"{sidecar.reason}"
                            )
                        )
                    )
                else:
                    actions.extend(sidecar.value)
                statuses.append(status)
                continue
            status = UpstreamStatus(
                key=key,
                state="changed",
                base_sha=_base_sha(entry),
                head_sha=resolved_entry.sha,
                base_hash=base_hash,
                head_hash=resolved_entry.content_hash,
                message="forced update over local catalog drift",
            )

        if status.state == "local_drift" and not force:
            actions.append(
                Warn(message=f"{_key_label(key)}: local catalog differs from last synced upstream")
            )
            statuses.append(status)
            continue

        should_write = status.state == "changed" or (force and not local_clean)
        if should_write and (upstream_changed or force):
            planned = _update_actions(entry, resolved_entry, file_contents, catalog_root)
            if isinstance(planned, Err):
                has_conflict = True
                status = UpstreamStatus(
                    key=key,
                    state="invalid",
                    base_sha=_base_sha(entry),
                    head_sha=resolved_entry.sha,
                    base_hash=base_hash,
                    head_hash=resolved_entry.content_hash,
                    message=planned.reason,
                )
                actions.append(
                    Warn(message=f"{_key_label(key)}: invalid staged artifact: {planned.reason}")
                )
                statuses.append(status)
                continue
            actions.extend(planned.value)

        statuses.append(status)

    return Ok(
        UpstreamUpdatePlan(
            plan=tuple(actions),
            entries=entries,
            statuses=tuple(statuses),
            conflict=has_conflict,
        )
    )


def _resolved_by_key(
    resolved: Tuple[ResolvedUpstream, ...],
) -> Mapping[UpstreamKey, ResolvedUpstream]:
    return {item.entry.key: item for item in resolved}


def _status_for(
    entry: UpstreamEntry,
    resolved: Optional[ResolvedUpstream],
    *,
    local_hashes: Optional[Mapping[object, str]],
    validation_errors: Optional[Mapping[object, str]],
    update: bool,
) -> UpstreamStatus:
    key = entry.key
    base_sha = _base_sha(entry)
    base_hash = _base_hash(entry)

    if resolved is None:
        return UpstreamStatus(
            key=key,
            state="missing_upstream",
            base_sha=base_sha,
            base_hash=base_hash,
            message="upstream path missing",
        )

    validation_error = _lookup(validation_errors, key)
    if validation_error:
        return UpstreamStatus(
            key=key,
            state="invalid",
            base_sha=base_sha,
            head_sha=resolved.sha,
            base_hash=base_hash,
            head_hash=resolved.content_hash,
            message=str(validation_error),
        )

    local_hash = _local_hash(entry, local_hashes)
    local_clean = _hash_matches(local_hash, base_hash)
    upstream_changed = not _hash_matches(resolved.content_hash, base_hash)

    if not local_clean:
        state: UpstreamState = "conflict" if update and upstream_changed else "local_drift"
        return UpstreamStatus(
            key=key,
            state=state,
            base_sha=base_sha,
            head_sha=resolved.sha,
            base_hash=base_hash,
            head_hash=resolved.content_hash,
            message="local catalog differs from last synced upstream",
        )

    return UpstreamStatus(
        key=key,
        state="changed" if upstream_changed else "up_to_date",
        base_sha=base_sha,
        head_sha=resolved.sha,
        base_hash=base_hash,
        head_hash=resolved.content_hash,
    )


def _update_actions(
    entry: UpstreamEntry,
    resolved: ResolvedUpstream,
    file_contents: Optional[Mapping[object, bytes]],
    catalog_root: str,
) -> Result:
    dst = _catalog_destination(entry.key, catalog_root)
    src = _staged_path(resolved)

    if entry.key.type in ("skill", "hook"):
        return Ok((RemovePath(path=dst), CopyTree(src=src, dst=dst)))

    content = _lookup(file_contents, entry.key)
    if content is None:
        try:
            with open(src, "rb") as f:
                content = f.read()
        except OSError as exc:
            return Err(f"could not read staged file {src}: {exc}")

    return Ok((WriteFile(path=dst, content=content),))


def _sidecar_actions(
    entry: UpstreamEntry,
    resolved: ResolvedUpstream,
    file_contents: Optional[Mapping[object, bytes]],
    catalog_root: str,
) -> Result:
    dst = _catalog_destination(entry.key, catalog_root) + ".agent-artifacts-upstream-new"
    src = _staged_path(resolved)

    if entry.key.type in ("skill", "hook"):
        return Ok((RemovePath(path=dst), CopyTree(src=src, dst=dst)))

    content = _lookup(file_contents, entry.key)
    if content is None:
        try:
            with open(src, "rb") as f:
                content = f.read()
        except OSError as exc:
            return Err(f"could not read staged file {src}: {exc}")

    return Ok((WriteFile(path=dst, content=content),))


def _catalog_destination(key: UpstreamKey, catalog_root: str = "") -> str:
    if key.type == "skill":
        rel = _join("skills", key.name)
    elif key.type == "hook":
        rel = _join("hooks", key.name)
    elif key.type == "guideline":
        rel = _join("guidelines", f"{key.name}.md")
    elif key.type == "mcp":
        rel = _join("mcp", f"{key.name}.json")
    elif key.type == "memory":
        rel = _join("memory", f"{key.name}.md")
    else:
        rel = _join(str(key.type), key.name)
    return _join(catalog_root, rel)


def _base_sha(entry: UpstreamEntry) -> Optional[str]:
    return entry.last_synced.sha if entry.last_synced is not None else None


def _base_hash(entry: UpstreamEntry) -> Optional[str]:
    return entry.last_synced.content_hash if entry.last_synced is not None else None


def _local_hash(
    entry: UpstreamEntry, local_hashes: Optional[Mapping[object, str]]
) -> Optional[str]:
    return _lookup(local_hashes, entry.key, default=_base_hash(entry))


def _lookup(mapping: Optional[Mapping[object, object]], key: UpstreamKey, default=None):
    if mapping is None:
        return default
    if key in mapping:
        return mapping[key]
    label = _key_label(key)
    if label in mapping:
        return mapping[label]
    return default


def _hash_matches(left: Optional[str], right: Optional[str]) -> bool:
    return left == right


def _key_label(key: UpstreamKey) -> str:
    return f"{key.type}/{key.name}"


def _staged_path(resolved: ResolvedUpstream) -> str:
    if resolved.path.startswith("/"):
        return resolved.path
    return _join(resolved.root, resolved.path)


def _join(*parts: str) -> str:
    cleaned = []
    for i, part in enumerate(parts):
        if part == "":
            continue
        seg = part if i == 0 else part.lstrip("/")
        seg = seg if i == len(parts) - 1 else seg.rstrip("/")
        cleaned.append(seg)
    return "/".join(cleaned)
