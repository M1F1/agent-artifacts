"""Source-side upstream tracking metadata for vendored artifacts.

This module owns the pure metadata contract for ``upstreams.json``. Behaviour lands in the
implementation WPs; these records are intentionally source-side and separate from consumer
manifests.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, Iterable, List, Literal, Mapping, Optional, Tuple

from .catalog import resolve_bundle
from .github_source import github_source_errors
from .model import Artifact, ArtifactType, Catalog, Err, Ok, Request, Result

_ARTIFACT_TYPES: Tuple[ArtifactType, ...] = ("skill", "guideline", "mcp", "hook", "memory")
_USAGE = 2


@dataclass(frozen=True, slots=True)
class UpstreamKey:
    type: ArtifactType
    name: str

    @classmethod
    def parse(cls, text: str) -> Result:
        return parse_upstream_key(text)

    def format(self) -> str:
        return format_upstream_key(self)

    def __str__(self) -> str:
        return self.format()


@dataclass(frozen=True, slots=True)
class UpstreamSource:
    kind: Literal["github"]
    repo: str
    ref: str
    path: str
    api_url: Optional[str] = None
    web_url: Optional[str] = None


@dataclass(frozen=True, slots=True)
class UpstreamSync:
    sha: str
    content_hash: str
    synced_at: str = ""


@dataclass(frozen=True, slots=True)
class UpstreamEntry:
    key: UpstreamKey
    source: UpstreamSource
    last_synced: Optional[UpstreamSync] = None


@dataclass(frozen=True, slots=True)
class UpstreamCatalog:
    version: int
    entries: Mapping[UpstreamKey, UpstreamEntry]


@dataclass(frozen=True, slots=True)
class UpstreamSelection:
    entries: Tuple[UpstreamEntry, ...]
    warnings: Tuple[str, ...] = ()


def parse_upstreams(text: str) -> Result:
    try:
        raw = json.loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        return Err(f"upstreams.json: invalid JSON ({exc})")

    if not isinstance(raw, dict):
        return Err("upstreams.json: expected a JSON object")

    errors: List[str] = []
    version = raw.get("version")
    if version != 1:
        errors.append("version must be 1")

    artifacts = raw.get("artifacts")
    if not isinstance(artifacts, dict):
        errors.append("artifacts must be an object")
        artifacts = {}

    entries: Dict[UpstreamKey, UpstreamEntry] = {}
    for raw_key, raw_entry in artifacts.items():
        if not isinstance(raw_key, str):
            errors.append("artifact keys must be strings")
            continue

        key_res = parse_upstream_key(raw_key)
        key: Optional[UpstreamKey] = None
        if isinstance(key_res, Err):
            errors.append(f"artifact key {raw_key!r}: {key_res.reason}")
        else:
            key = key_res.value

        if not isinstance(raw_entry, dict):
            errors.append(f"{raw_key}: entry must be an object")
            continue

        source = _parse_source(raw_key, raw_entry.get("source"), errors)
        last_synced = _parse_last_synced(raw_key, raw_entry.get("last_synced"), errors)

        if key is not None and source is not None and last_synced is not _INVALID:
            entries[key] = UpstreamEntry(
                key=key,
                source=source,
                last_synced=last_synced,
            )

    if errors:
        return Err("; ".join(errors))
    return Ok(UpstreamCatalog(version=1, entries=entries))


def dump_upstreams(catalog: UpstreamCatalog) -> str:
    artifacts = {}
    for key in sorted(catalog.entries, key=format_upstream_key):
        entry = catalog.entries[key]
        payload = {
            "source": {
                "kind": entry.source.kind,
                "repo": entry.source.repo,
                "ref": entry.source.ref,
                "path": entry.source.path,
            }
        }
        if entry.source.api_url is not None:
            payload["source"]["api_url"] = entry.source.api_url
        if entry.source.web_url is not None:
            payload["source"]["web_url"] = entry.source.web_url
        if entry.last_synced is not None:
            payload["last_synced"] = {
                "sha": entry.last_synced.sha,
                "content_hash": entry.last_synced.content_hash,
                "synced_at": entry.last_synced.synced_at,
            }
        artifacts[format_upstream_key(key)] = payload
    data = {"version": catalog.version, "artifacts": artifacts}
    return json.dumps(data, indent=2, sort_keys=False) + "\n"


def select_upstreams(request: Request, catalog: Catalog, upstreams: UpstreamCatalog) -> Result:
    warnings: List[str] = []
    selected: List[UpstreamEntry] = []
    errors: List[Err] = []

    if request.all or _has_no_selector(request):
        selected.extend(
            _tracked_catalog_entries(
                catalog,
                upstreams,
                type_filter=request.type_filter,
            )
        )
        return Ok(UpstreamSelection(entries=_dedup_entries(selected), warnings=()))

    for bundle_name in request.bundles:
        res = resolve_bundle(catalog, bundle_name)
        if isinstance(res, Err):
            errors.append(Err(res.reason, code=_USAGE))
            continue
        for artifact_type, artifact_name in res.value.artifacts:
            if request.type_filter is not None and artifact_type != request.type_filter:
                continue
            key = UpstreamKey(artifact_type, artifact_name)
            entry = upstreams.entries.get(key)
            if entry is None:
                warnings.append(
                    f"bundle {bundle_name!r}: skipped untracked artifact {format_upstream_key(key)}"
                )
            else:
                selected.append(entry)

    for name in request.names:
        if "/" in name:
            key_res = parse_upstream_key(name)
            if isinstance(key_res, Err):
                errors.append(Err(key_res.reason, code=_USAGE))
                continue
            key = key_res.value
            if request.type_filter is not None and key.type != request.type_filter:
                errors.append(
                    Err(
                        f"artifact {name!r} does not match --type {request.type_filter!r}",
                        code=_USAGE,
                    )
                )
                continue
            _append_explicit_key(key, catalog, upstreams, selected, errors)
            continue

        matches = _lookup_catalog_name(catalog, name, request.type_filter)
        if not matches:
            errors.append(Err(f"unknown artifact {name!r}", code=_USAGE))
            continue
        for artifact in matches:
            _append_explicit_key(
                UpstreamKey(artifact.type, artifact.name),
                catalog,
                upstreams,
                selected,
                errors,
            )

    if errors:
        return Err("; ".join(err.reason for err in errors), code=_USAGE)
    return Ok(UpstreamSelection(entries=_dedup_entries(selected), warnings=tuple(warnings)))


def validate_upstreams(upstreams: UpstreamCatalog, catalog: Catalog) -> Tuple[Err, ...]:
    errors: List[Err] = []
    for key in sorted(upstreams.entries, key=format_upstream_key):
        entry = upstreams.entries[key]
        label = format_upstream_key(key)
        artifact = catalog.artifacts.get((key.type, key.name))
        if artifact is None:
            errors.append(Err(f"unknown artifact {label}", code=_USAGE))
        elif artifact.root != _expected_root(key):
            errors.append(
                Err(
                    f"{label}: expected catalog root {_expected_root(key)}, found {artifact.root}",
                    code=_USAGE,
                )
            )

        if entry.source.kind != "github":
            errors.append(Err(f"{label}: source.kind must be 'github'", code=_USAGE))
        for reason in github_source_errors(entry.source):
            errors.append(Err(f"{label}: source.{reason}", code=_USAGE))
        if not _non_empty_str(entry.source.ref):
            errors.append(Err(f"{label}: source.ref must be a non-empty string", code=_USAGE))
        if not _non_empty_str(entry.source.path):
            errors.append(Err(f"{label}: source.path must be a non-empty string", code=_USAGE))

        sync = entry.last_synced
        if sync is None:
            errors.append(Err(f"{label}: last_synced is required", code=_USAGE))
        else:
            if not _non_empty_str(sync.sha):
                errors.append(
                    Err(f"{label}: last_synced.sha must be a non-empty string", code=_USAGE)
                )
            if not _non_empty_str(sync.content_hash):
                errors.append(
                    Err(
                        f"{label}: last_synced.content_hash must be a non-empty string",
                        code=_USAGE,
                    )
                )
            if not isinstance(sync.synced_at, str):
                errors.append(
                    Err(f"{label}: last_synced.synced_at must be a string", code=_USAGE)
                )

    return tuple(errors)


def parse_upstream_key(text: str) -> Result:
    parts = text.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return Err(f"{text!r}: expected '<type>/<name>'")
    artifact_type, name = parts
    if artifact_type not in _ARTIFACT_TYPES:
        return Err(f"{text!r}: unknown type {artifact_type!r}")
    return Ok(UpstreamKey(artifact_type, name))


def format_upstream_key(key: UpstreamKey) -> str:
    return f"{key.type}/{key.name}"


_INVALID = object()


def _parse_source(raw_key: str, raw_source, errors: List[str]) -> Optional[UpstreamSource]:
    if not isinstance(raw_source, dict):
        errors.append(f"{raw_key}: source must be an object")
        return None

    kind = raw_source.get("kind")
    repo = raw_source.get("repo")
    ref = raw_source.get("ref")
    path = raw_source.get("path")
    api_url = raw_source.get("api_url")
    web_url = raw_source.get("web_url")

    ok = True
    if kind != "github":
        errors.append(f"{raw_key}: source.kind must be 'github'")
        ok = False
    if not _non_empty_str(repo):
        errors.append(f"{raw_key}: source.repo must be a non-empty string")
        ok = False
    if not _non_empty_str(ref):
        errors.append(f"{raw_key}: source.ref must be a non-empty string")
        ok = False
    if not _non_empty_str(path):
        errors.append(f"{raw_key}: source.path must be a non-empty string")
        ok = False
    if api_url is not None and not _non_empty_str(api_url):
        errors.append(f"{raw_key}: source.api_url must be a non-empty string when present")
        ok = False
    if web_url is not None and not _non_empty_str(web_url):
        errors.append(f"{raw_key}: source.web_url must be a non-empty string when present")
        ok = False
    if not ok:
        return None
    assert isinstance(repo, str)
    assert isinstance(ref, str)
    assert isinstance(path, str)
    assert api_url is None or isinstance(api_url, str)
    assert web_url is None or isinstance(web_url, str)
    return UpstreamSource(
        kind="github",
        repo=repo,
        ref=ref,
        path=path,
        api_url=api_url,
        web_url=web_url,
    )


def _parse_last_synced(raw_key: str, raw_sync, errors: List[str]):
    if raw_sync is None:
        return None
    if not isinstance(raw_sync, dict):
        errors.append(f"{raw_key}: last_synced must be an object")
        return _INVALID

    sha = raw_sync.get("sha")
    content_hash = raw_sync.get("content_hash")
    synced_at = raw_sync.get("synced_at", "")

    ok = True
    if not _non_empty_str(sha):
        errors.append(f"{raw_key}: last_synced.sha must be a non-empty string")
        ok = False
    if not _non_empty_str(content_hash):
        errors.append(f"{raw_key}: last_synced.content_hash must be a non-empty string")
        ok = False
    if not isinstance(synced_at, str):
        errors.append(f"{raw_key}: last_synced.synced_at must be a string")
        ok = False
    if not ok:
        return _INVALID
    assert isinstance(sha, str)
    assert isinstance(content_hash, str)
    return UpstreamSync(sha=sha, content_hash=content_hash, synced_at=synced_at)


def _non_empty_str(value) -> bool:
    return isinstance(value, str) and value != ""


def _expected_root(key: UpstreamKey) -> str:
    if key.type == "skill":
        return f"skills/{key.name}"
    if key.type == "guideline":
        return f"guidelines/{key.name}.md"
    if key.type == "mcp":
        return f"mcp/{key.name}.json"
    if key.type == "hook":
        return f"hooks/{key.name}"
    if key.type == "memory":
        return f"memory/{key.name}.md"
    return f"{key.type}/{key.name}"


def _has_no_selector(request: Request) -> bool:
    return not request.names and not request.bundles


def _tracked_catalog_entries(
    catalog: Catalog,
    upstreams: UpstreamCatalog,
    *,
    type_filter: Optional[ArtifactType],
) -> Tuple[UpstreamEntry, ...]:
    entries: List[UpstreamEntry] = []
    for artifact_type, artifact_name in sorted(catalog.artifacts):
        if type_filter is not None and artifact_type != type_filter:
            continue
        entry = upstreams.entries.get(UpstreamKey(artifact_type, artifact_name))
        if entry is not None:
            entries.append(entry)
    return tuple(entries)


def _lookup_catalog_name(
    catalog: Catalog,
    name: str,
    type_filter: Optional[ArtifactType],
) -> Tuple[Artifact, ...]:
    if type_filter is not None:
        artifact = catalog.artifacts.get((type_filter, name))
        return (artifact,) if artifact is not None else ()
    return tuple(
        catalog.artifacts[(artifact_type, name)]
        for artifact_type in _ARTIFACT_TYPES
        if (artifact_type, name) in catalog.artifacts
    )


def _append_explicit_key(
    key: UpstreamKey,
    catalog: Catalog,
    upstreams: UpstreamCatalog,
    selected: List[UpstreamEntry],
    errors: List[Err],
) -> None:
    if (key.type, key.name) not in catalog.artifacts:
        errors.append(Err(f"unknown artifact {format_upstream_key(key)!r}", code=_USAGE))
        return
    entry = upstreams.entries.get(key)
    if entry is None:
        errors.append(Err(f"untracked artifact {format_upstream_key(key)}", code=_USAGE))
        return
    selected.append(entry)


def _dedup_entries(entries: Iterable[UpstreamEntry]) -> Tuple[UpstreamEntry, ...]:
    seen = set()
    out = []
    for entry in entries:
        if entry.key in seen:
            continue
        seen.add(entry.key)
        out.append(entry)
    return tuple(out)
