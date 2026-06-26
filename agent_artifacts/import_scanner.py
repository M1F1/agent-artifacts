"""Batch upstream import scanners for manifest and heuristic modes."""

from __future__ import annotations

import json
import os
from typing import List, Literal, Optional, Tuple

from . import catalog as catalog_mod
from .import_candidates import (
    ImportCandidate,
    ImportScan,
    destination_for,
)
from .import_manifest import find_manifest, parse_import_manifest
from .model import ArtifactType, Err, Ok, Result
from .upstreams import UpstreamKey, UpstreamSource

ImportMode = Literal["auto", "manifest", "heuristic"]

_IGNORE_DIRS = {
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    "target",
}


def scan_import_root(
    root: str,
    *,
    source: UpstreamSource,
    sha: str,
    mode: ImportMode = "auto",
) -> Result:
    manifest_path = find_manifest(root)
    if mode in ("auto", "manifest") and manifest_path is not None:
        try:
            with open(manifest_path, encoding="utf-8") as fh:
                manifest_text = fh.read()
        except OSError as exc:
            return Err(f"cannot read import manifest: {exc}", code=1)
        manifest_res = parse_import_manifest(manifest_text)
        if isinstance(manifest_res, Err):
            return manifest_res
        candidates_res = _manifest_candidates(root, source, manifest_res.value.artifacts)
        if isinstance(candidates_res, Err):
            return candidates_res
        return Ok(
            ImportScan(
                mode="manifest",
                repo=source.repo,
                ref=source.ref,
                scan_root=source.path,
                sha=sha,
                root=os.path.abspath(root),
                candidates=candidates_res.value,
            )
        )

    if mode == "manifest":
        return Err("import manifest not found", code=2)

    candidates = _heuristic_candidates(root, source)
    return Ok(
        ImportScan(
            mode="heuristic",
            repo=source.repo,
            ref=source.ref,
            scan_root=source.path,
            sha=sha,
            root=os.path.abspath(root),
            candidates=candidates,
        )
    )


def _manifest_candidates(root: str, source: UpstreamSource, artifacts) -> Result:
    out = []
    errors = []
    for item in artifacts:
        abs_path = _safe_join(root, item.path)
        if abs_path is None:
            errors.append(f"{item.type}/{item.name}: path escapes scan root")
            continue
        problem = _validate_artifact_path(item.type, item.name, abs_path)
        if problem is not None:
            errors.append(f"{item.type}/{item.name}: {problem}")
            continue
        tree = os.path.isdir(abs_path)
        descriptor = _descriptor_source_path(root, item.type, item.name, abs_path, source, item.path)
        out.append(
            ImportCandidate(
                key=UpstreamKey(item.type, item.name),
                source=_candidate_source(source, item.path),
                detected_by="manifest",
                confidence="explicit",
                upstream_kind="tree" if tree else "file",
                local_destination=destination_for(item.type, item.name, tree=tree),
                absolute_path=abs_path,
                descriptor_path=descriptor,
                description=item.description or None,
                selected_by_default=True,
            )
        )
    if errors:
        return Err("; ".join(errors), code=2)
    return Ok(tuple(out))


def _heuristic_candidates(root: str, source: UpstreamSource) -> Tuple[ImportCandidate, ...]:
    out: List[ImportCandidate] = []
    candidate_dirs: List[str] = []

    for current, dirs, _files in os.walk(root, topdown=True):
        dirs[:] = [d for d in sorted(dirs) if d not in _IGNORE_DIRS and not _ignored_hidden(d)]
        if _under_any(current, candidate_dirs):
            dirs[:] = []
            continue

        skill = os.path.join(current, "SKILL.md")
        if os.path.isfile(skill):
            candidate = _skill_candidate(root, source, current, skill)
            if candidate is not None:
                out.append(candidate)
                candidate_dirs.append(current)
                dirs[:] = []
                continue

        hook = os.path.join(current, "hook.json")
        if os.path.isfile(hook):
            candidate = _hook_candidate(root, source, current, hook)
            if candidate is not None:
                out.append(candidate)
                candidate_dirs.append(current)
                dirs[:] = []
                continue

        mcp_descriptor = _mcp_dir_descriptor(current)
        if mcp_descriptor is not None:
            candidate = _mcp_candidate(root, source, current, mcp_descriptor, tree=True)
            if candidate is not None:
                out.append(candidate)
                candidate_dirs.append(current)
                dirs[:] = []

    for current, dirs, files in os.walk(root, topdown=True):
        dirs[:] = [d for d in sorted(dirs) if d not in _IGNORE_DIRS and not _ignored_hidden(d)]
        if _under_any(current, candidate_dirs):
            dirs[:] = []
            continue
        for filename in sorted(files):
            path = os.path.join(current, filename)
            if filename.endswith(".json"):
                candidate = _mcp_candidate(root, source, path, path, tree=False)
                if candidate is not None:
                    out.append(candidate)
            elif filename.endswith(".md") and filename not in {"README.md", "SKILL.md"}:
                candidate = _markdown_candidate(root, source, path)
                if candidate is not None:
                    out.append(candidate)

    return tuple(_dedup_candidates(out))


def _skill_candidate(
    root: str, source: UpstreamSource, directory: str, skill_path: str
) -> Optional[ImportCandidate]:
    text = _read_text(skill_path)
    name = _frontmatter_name(text) or os.path.basename(directory)
    res = catalog_mod.parse_skill(text, name)
    if isinstance(res, Err):
        return None
    rel = _rel(root, directory)
    return ImportCandidate(
        key=UpstreamKey("skill", name),
        source=_candidate_source(source, rel),
        detected_by="heuristic",
        confidence="high",
        upstream_kind="tree",
        local_destination=destination_for("skill", name, tree=True),
        absolute_path=directory,
        selected_by_default=True,
    )


def _hook_candidate(
    root: str, source: UpstreamSource, directory: str, hook_path: str
) -> Optional[ImportCandidate]:
    data = _read_json(hook_path)
    name = data.get("name") if isinstance(data, dict) else None
    name = name if isinstance(name, str) and name else os.path.basename(directory)
    res = catalog_mod.parse_hook(_read_text(hook_path), name)
    if isinstance(res, Err):
        return None
    rel = _rel(root, directory)
    return ImportCandidate(
        key=UpstreamKey("hook", name),
        source=_candidate_source(source, rel),
        detected_by="heuristic",
        confidence="high",
        upstream_kind="tree",
        local_destination=destination_for("hook", name, tree=True),
        absolute_path=directory,
        descriptor_path=_source_join(source.path, rel, "hook.json"),
        selected_by_default=True,
    )


def _mcp_candidate(
    root: str,
    source: UpstreamSource,
    path: str,
    descriptor_path: str,
    *,
    tree: bool,
) -> Optional[ImportCandidate]:
    data = _read_json(descriptor_path)
    name = data.get("name") if isinstance(data, dict) else None
    default_name = os.path.basename(path)
    if default_name.endswith(".json"):
        default_name = default_name[: -len(".json")]
    name = name if isinstance(name, str) and name else default_name
    res = catalog_mod.parse_mcp(_read_text(descriptor_path), name)
    if isinstance(res, Err):
        return None
    rel = _rel(root, path)
    descriptor_rel = _rel(root, descriptor_path)
    warnings: Tuple[str, ...] = ()
    if tree and os.path.basename(path) != name:
        warnings = (f"descriptor name {name!r} differs from directory {os.path.basename(path)!r}",)
    return ImportCandidate(
        key=UpstreamKey("mcp", name),
        source=_candidate_source(source, rel),
        detected_by="heuristic",
        confidence="high" if tree or path.endswith(".json") else "medium",
        upstream_kind="tree" if tree else "file",
        local_destination=destination_for("mcp", name, tree=tree),
        absolute_path=path,
        descriptor_path=_source_join(source.path, descriptor_rel),
        warnings=warnings,
        selected_by_default=True,
    )


def _markdown_candidate(
    root: str, source: UpstreamSource, path: str
) -> Optional[ImportCandidate]:
    rel = _rel(root, path)
    parts = rel.split("/")
    stem = os.path.splitext(os.path.basename(path))[0]
    text = _read_text(path)
    name = _frontmatter_name(text) or stem

    artifact_type: ArtifactType
    confidence = "ambiguous"
    selected = False
    if parts[0] in {"memory", "memories", "context"}:
        artifact_type = "memory"
        confidence = "medium"
        selected = True
    elif parts[0] in {"guidelines", "guideline", "rules"} or rel.startswith("docs/guidelines/"):
        artifact_type = "guideline"
        confidence = "medium"
        selected = True
    else:
        artifact_type = "guideline"

    parser = catalog_mod.parse_memory if artifact_type == "memory" else catalog_mod.parse_guideline
    res = parser(text, name)
    if isinstance(res, Err):
        return None

    warnings: Tuple[str, ...] = ()
    if confidence == "ambiguous":
        warnings = ("ambiguous markdown; pass --select with the intended type/name to import",)
    return ImportCandidate(
        key=UpstreamKey(artifact_type, name),
        source=_candidate_source(source, rel),
        detected_by="heuristic",
        confidence=confidence,  # type: ignore[arg-type]
        upstream_kind="file",
        local_destination=destination_for(artifact_type, name, tree=False),
        absolute_path=path,
        warnings=warnings,
        selected_by_default=selected,
    )


def _validate_artifact_path(artifact_type: ArtifactType, name: str, path: str) -> Optional[str]:
    try:
        if artifact_type == "skill":
            return _parser_problem(catalog_mod.parse_skill(_read_text(os.path.join(path, "SKILL.md")), name))
        if artifact_type == "hook":
            return _parser_problem(catalog_mod.parse_hook(_read_text(os.path.join(path, "hook.json")), name))
        if artifact_type == "guideline":
            return _parser_problem(catalog_mod.parse_guideline(_read_text(path), name))
        if artifact_type == "memory":
            return _parser_problem(catalog_mod.parse_memory(_read_text(path), name))
        if artifact_type == "mcp":
            descriptor = _mcp_descriptor_file(path, name)
            if descriptor is None:
                return f"missing MCP descriptor mcp.json or {name}.json"
            return _parser_problem(catalog_mod.parse_mcp(_read_text(descriptor), name))
    except OSError as exc:
        return str(exc)
    return f"unknown artifact type {artifact_type!r}"


def _parser_problem(result: Result) -> Optional[str]:
    return result.reason if isinstance(result, Err) else None


def _mcp_dir_descriptor(directory: str) -> Optional[str]:
    if not os.path.isdir(directory):
        return None
    return _mcp_descriptor_file(directory, os.path.basename(directory))


def _mcp_descriptor_file(path: str, name: str) -> Optional[str]:
    if not os.path.isdir(path):
        return path if path.endswith(".json") and os.path.isfile(path) else None
    for filename in ("mcp.json", f"{name}.json"):
        candidate = os.path.join(path, filename)
        if os.path.isfile(candidate):
            return candidate
    return None


def _descriptor_source_path(
    root: str,
    artifact_type: ArtifactType,
    name: str,
    abs_path: str,
    source: UpstreamSource,
    rel_path: str,
) -> Optional[str]:
    if artifact_type == "hook":
        return _source_join(source.path, rel_path, "hook.json")
    if artifact_type != "mcp":
        return None
    descriptor = _mcp_descriptor_file(abs_path, name)
    if descriptor is None:
        return None
    if os.path.isdir(abs_path):
        return _source_join(source.path, _rel(root, descriptor))
    return _source_join(source.path, rel_path)


def _candidate_source(source: UpstreamSource, rel: str) -> UpstreamSource:
    return UpstreamSource(
        kind=source.kind,
        repo=source.repo,
        ref=source.ref,
        path=_source_join(source.path, rel),
        api_url=source.api_url,
        web_url=source.web_url,
    )


def _source_join(*parts: str) -> str:
    clean: List[str] = []
    for part in parts:
        if not part:
            continue
        clean.extend(seg for seg in part.split("/") if seg)
    return "/".join(clean)


def _safe_join(root: str, rel: str) -> Optional[str]:
    path = os.path.abspath(os.path.join(root, *rel.split("/"))) if rel else os.path.abspath(root)
    root_abs = os.path.abspath(root)
    if path != root_abs and not path.startswith(root_abs + os.sep):
        return None
    return path


def _frontmatter_name(text: str) -> Optional[str]:
    _found, fields, _body = catalog_mod._split_frontmatter(text)
    value = fields.get("name")
    return value if value else None


def _read_text(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _read_json(path: str):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def _rel(root: str, path: str) -> str:
    return os.path.relpath(path, root).replace(os.sep, "/")


def _under_any(path: str, roots: List[str]) -> bool:
    path_abs = os.path.abspath(path)
    for root in roots:
        root_abs = os.path.abspath(root)
        if path_abs == root_abs or path_abs.startswith(root_abs + os.sep):
            return True
    return False


def _ignored_hidden(dirname: str) -> bool:
    return dirname.startswith(".") and dirname != ".agent-artifacts"


def _dedup_candidates(candidates: List[ImportCandidate]) -> List[ImportCandidate]:
    seen = set()
    out = []
    for candidate in candidates:
        key = (candidate.key.type, candidate.key.name)
        if key in seen:
            continue
        seen.add(key)
        out.append(candidate)
    return out
