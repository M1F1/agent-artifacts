"""Executor — imperative shell (WP-9). The only place a Plan touches disk (docs/design/DESIGN.md §14).

`execute` dispatches each `Action` to a performer (using io.fs); `render_plan`/`plan_to_json`
present a Plan for ``--dry-run`` / ``--json`` without performing any effect.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Tuple, Type

from .model import (
    Action,
    CopyTree,
    ManifestEntry,
    MergeJson,
    Plan,
    RemovePath,
    SymlinkTree,
    Warn,
    WriteFile,
    WriteManifest,
)

MANIFEST_PATH = ".agent-artifacts/manifest.json"


# --------------------------------------------------------------------------- #
# Report — what ran (returned by execute).                                     #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Report:
    performed: Tuple[str, ...]
    warnings: Tuple[str, ...]
    manifest_written: bool


# --------------------------------------------------------------------------- #
# Internal mutable execution context (collects results as performers run).      #
# --------------------------------------------------------------------------- #
class _Ctx:
    __slots__ = ("fs", "performed", "warnings", "manifest_written")

    def __init__(self, fs):
        self.fs = fs
        self.performed: List[str] = []
        self.warnings: List[str] = []
        self.manifest_written = False


# --------------------------------------------------------------------------- #
# JSON helpers.                                                                 #
# --------------------------------------------------------------------------- #
def _descend(root: dict, json_path: str) -> dict:
    """Descend (creating missing mappings) into ``root`` along a dotted path.

    An empty ``json_path`` returns ``root`` itself.
    """
    node = root
    if not json_path:
        return node
    for part in json_path.split("."):
        child = node.get(part)
        if not isinstance(child, dict):
            child = {}
            node[part] = child
        node = child
    return node


def _manifest_entry_to_dict(entry: ManifestEntry) -> dict:
    """Serialize a `ManifestEntry` to a plain JSON-able dict (local; no WP-4)."""
    out: Dict[str, Any] = {
        "artifact": entry.artifact,
        "type": entry.type,
        "profile": entry.profile,
        "source": entry.source,
        "install": {
            "mode": entry.install.mode,
            "requested_mode": entry.install.requested_mode,
            "links": [
                {
                    "path": link.path,
                    "target": link.target,
                    "target_kind": link.target_kind,
                }
                for link in entry.install.links
            ],
        },
        "bundle": entry.bundle,
        "files": dict(entry.files),
        "installed_at": entry.installed_at,
    }
    if entry.merge is not None:
        m = entry.merge
        out["merge"] = {
            "file": m.file,
            "json_path": m.json_path,
            "mode": m.mode,
            "identity": dict(m.identity),
            "value_hash": m.value_hash,
            "created_file": m.created_file,
            "overwrote": m.overwrote,
        }
    else:
        out["merge"] = None
    return out


# --------------------------------------------------------------------------- #
# Performers — one per Action kind. Each mutates the context / fs.              #
# --------------------------------------------------------------------------- #
def _do_copy_tree(a: CopyTree, ctx: _Ctx) -> None:
    ctx.fs.copy_tree(a.src, a.dst)
    ctx.performed.append(f"copy_tree {a.src} -> {a.dst}")


def _do_symlink_tree(a: SymlinkTree, ctx: _Ctx) -> None:
    ctx.fs.symlink_tree(a.src, a.dst)
    ctx.performed.append(f"symlink_tree {a.src} -> {a.dst}")


def _do_write_file(a: WriteFile, ctx: _Ctx) -> None:
    ctx.fs.write_atomic(a.path, a.content)
    ctx.performed.append(f"write_file {a.path}")


def _do_merge_json(a: MergeJson, ctx: _Ctx) -> None:
    if ctx.fs.exists(a.file):
        root = ctx.fs.read_json(a.file)
        if not isinstance(root, dict):
            root = {}
    else:
        root = {}

    if a.mode == "key":
        # json_path addresses the mapping that holds the keyed entry.
        leaf = _descend(root, a.json_path)
        key = a.identity[0]
        leaf[key] = a.value
    elif a.mode == "list":
        # json_path addresses the list itself; descend to its parent and take the
        # last segment as the list key (do NOT materialize the leaf as a mapping).
        parts = a.json_path.split(".") if a.json_path else [""]
        parent = _descend(root, ".".join(parts[:-1]))
        list_key = parts[-1]
        current = parent.get(list_key)
        if not isinstance(current, list):
            current = []
            parent[list_key] = current
        if not any(_deep_equal(existing, a.value) for existing in current):
            current.append(a.value)
    else:  # pragma: no cover - guarded by the model's Literal type
        raise ValueError(f"unknown merge mode: {a.mode!r}")

    ctx.fs.write_atomic(a.file, json.dumps(root, indent=2).encode())
    ctx.performed.append(f"merge_json {a.file} [{a.mode}] {a.json_path}")


def _do_remove_path(a: RemovePath, ctx: _Ctx) -> None:
    ctx.fs.remove_path(a.path)
    ctx.performed.append(f"remove_path {a.path}")


def _do_write_manifest(a: WriteManifest, ctx: _Ctx) -> None:
    payload = {"installed": [_manifest_entry_to_dict(e) for e in a.entries]}
    ctx.fs.write_atomic(MANIFEST_PATH, json.dumps(payload, indent=2).encode())
    ctx.manifest_written = True
    ctx.performed.append(f"write_manifest {MANIFEST_PATH} ({len(a.entries)} entries)")


def _do_warn(a: Warn, ctx: _Ctx) -> None:
    ctx.warnings.append(a.message)
    ctx.performed.append(f"warn {a.message}")


def _deep_equal(x: Any, y: Any) -> bool:
    """Structural equality over JSON-shaped values (dict/list/scalars)."""
    if isinstance(x, dict) and isinstance(y, dict):
        if x.keys() != y.keys():
            return False
        return all(_deep_equal(x[k], y[k]) for k in x)
    if isinstance(x, list) and isinstance(y, list):
        return len(x) == len(y) and all(_deep_equal(a, b) for a, b in zip(x, y, strict=True))
    return x == y


# Dispatch table: Action type -> performer. No if/elif chain.
_DISPATCH: Dict[Type[Action], Callable[[Any, _Ctx], None]] = {
    CopyTree: _do_copy_tree,
    SymlinkTree: _do_symlink_tree,
    WriteFile: _do_write_file,
    MergeJson: _do_merge_json,
    RemovePath: _do_remove_path,
    WriteManifest: _do_write_manifest,
    Warn: _do_warn,
}


def execute(plan: Plan, fs=None) -> Report:
    """Execute every Action in order; return a Report. `fs` is injectable for testing."""
    if fs is None:
        import agent_artifacts.io.fs as fs  # noqa: PLC0415

    ctx = _Ctx(fs)
    for action in plan:
        performer = _DISPATCH.get(type(action))
        if performer is None:
            raise TypeError(f"no performer for action: {type(action).__name__}")
        performer(action, ctx)

    return Report(
        performed=tuple(ctx.performed),
        warnings=tuple(ctx.warnings),
        manifest_written=ctx.manifest_written,
    )


# --------------------------------------------------------------------------- #
# Renderers — present a Plan without touching disk.                            #
# --------------------------------------------------------------------------- #
def _render_action(a: Action) -> str:
    if isinstance(a, CopyTree):
        return f"copy-tree   {a.src} -> {a.dst}"
    if isinstance(a, SymlinkTree):
        return f"symlink-tree {a.src} -> {a.dst}"
    if isinstance(a, WriteFile):
        return f"write-file  {a.path} ({len(a.content)} bytes)"
    if isinstance(a, MergeJson):
        return f"merge-json  {a.file} [{a.mode}] at '{a.json_path}'"
    if isinstance(a, RemovePath):
        return f"remove-path {a.path}"
    if isinstance(a, WriteManifest):
        return f"manifest    {MANIFEST_PATH} ({len(a.entries)} entries)"
    if isinstance(a, Warn):
        return f"warn        {a.message}"
    raise TypeError(f"cannot render action: {type(a).__name__}")  # pragma: no cover


def render_plan(plan: Plan) -> str:
    """Human-readable ``--dry-run`` rendering."""
    return "\n".join(_render_action(a) for a in plan)


def _action_to_obj(a: Action) -> dict:
    if isinstance(a, CopyTree):
        return {"action": "copy-tree", "src": a.src, "dst": a.dst}
    if isinstance(a, SymlinkTree):
        return {"action": "symlink-tree", "src": a.src, "dst": a.dst}
    if isinstance(a, WriteFile):
        return {"action": "write-file", "path": a.path, "size": len(a.content)}
    if isinstance(a, MergeJson):
        return {
            "action": "merge-json",
            "file": a.file,
            "json_path": a.json_path,
            "mode": a.mode,
            "value": a.value,
            "identity": list(a.identity),
            "create_if_absent": a.create_if_absent,
        }
    if isinstance(a, RemovePath):
        return {"action": "remove-path", "path": a.path}
    if isinstance(a, WriteManifest):
        return {
            "action": "write-manifest",
            "path": MANIFEST_PATH,
            "entries": [_manifest_entry_to_dict(e) for e in a.entries],
        }
    if isinstance(a, Warn):
        return {"action": "warn", "message": a.message}
    raise TypeError(f"cannot serialize action: {type(a).__name__}")  # pragma: no cover


def plan_to_json(plan: Plan) -> str:
    """Machine-readable ``--json`` rendering."""
    return json.dumps([_action_to_obj(a) for a in plan], indent=2)
