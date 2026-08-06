"""Executor — imperative shell (WP-9). The only place a Plan touches disk (docs/design/DESIGN.md §14).

`execute` dispatches each `Action` to a performer (using io.fs); `render_plan`/`plan_to_json`
present a Plan for ``--dry-run`` / ``--json`` without performing any effect.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple, Type

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
EffectState = Literal["changed", "unchanged", "skipped", "failed"]


@dataclass(frozen=True, slots=True)
class EffectObservation:
    """Structured fact about one attempted effect."""

    operation: str
    target: str
    state: EffectState
    detail: Optional[str] = None


@dataclass(frozen=True, slots=True)
class Report:
    performed: Tuple[str, ...]
    warnings: Tuple[str, ...]
    manifest_written: bool
    observations: Tuple[EffectObservation, ...] = ()

    @property
    def failed(self) -> bool:
        return any(item.state == "failed" for item in self.observations)


# --------------------------------------------------------------------------- #
# Internal mutable execution context (collects results as performers run).      #
# --------------------------------------------------------------------------- #
class _Ctx:
    __slots__ = ("fs", "performed", "warnings", "manifest_written", "observations")

    def __init__(self, fs):
        self.fs = fs
        self.performed: List[str] = []
        self.warnings: List[str] = []
        self.manifest_written = False
        self.observations: List[EffectObservation] = []


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


def _tree_files(root: str) -> Optional[Tuple[str, ...]]:
    """Return the deterministic relative file set for a real directory tree."""

    if not os.path.isdir(root) or os.path.islink(root):
        return None
    files = []
    for directory, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for filename in sorted(filenames):
            absolute = os.path.join(directory, filename)
            files.append(os.path.relpath(absolute, root))
    return tuple(files)


def _trees_equal(src: str, dst: str) -> bool:
    """Return whether copying ``src`` over ``dst`` would change managed bytes.

    ``copytree(..., dirs_exist_ok=True)`` preserves destination-only content, so extra files in
    the destination do not make the copy effect non-idempotent.
    """

    src_files = _tree_files(src)
    dst_files = _tree_files(dst)
    if src_files is None or dst_files is None or not set(src_files).issubset(dst_files):
        return False
    for relative in src_files:
        with open(os.path.join(src, relative), "rb") as src_file:
            with open(os.path.join(dst, relative), "rb") as dst_file:
                if src_file.read() != dst_file.read():
                    return False
    return True


def _symlink_matches(src: str, dst: str) -> bool:
    if not os.path.islink(dst):
        return False
    raw_target = os.readlink(dst)
    actual = (
        raw_target
        if os.path.isabs(raw_target)
        else os.path.abspath(os.path.join(os.path.dirname(dst), raw_target))
    )
    return os.path.normpath(actual) == os.path.normpath(os.path.abspath(src))


def _lookup(root: object, json_path: str) -> object:
    node = root
    if not json_path:
        return node
    for part in json_path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _merge_is_current(action: MergeJson, fs) -> bool:
    if not fs.exists(action.file):
        return False
    root = fs.read_json(action.file)
    if action.mode == "key":
        if not action.identity:
            return False
        parent = _lookup(root, action.json_path)
        return (
            isinstance(parent, dict)
            and action.identity[0] in parent
            and _deep_equal(parent[action.identity[0]], action.value)
        )
    current = _lookup(root, action.json_path)
    return isinstance(current, list) and any(
        _deep_equal(existing, action.value) for existing in current
    )


def _manifest_bytes(action: WriteManifest) -> bytes:
    payload = {"installed": [_manifest_entry_to_dict(entry) for entry in action.entries]}
    return json.dumps(payload, indent=2).encode()


def _path_exists(path: str, fs) -> bool:
    lexists = getattr(fs, "lexists", None)
    if callable(lexists):
        return bool(lexists(path))
    if getattr(fs, "__name__", "") == "agent_artifacts.io.fs":
        return os.path.lexists(path)
    return bool(fs.exists(path))


def _would_change(action: Action, fs) -> bool:
    """Read-only equivalence check for a supported action."""

    if isinstance(action, CopyTree):
        return not _trees_equal(action.src, action.dst)
    if isinstance(action, SymlinkTree):
        return not _symlink_matches(action.src, action.dst)
    if isinstance(action, WriteFile):
        return not fs.exists(action.path) or fs.read_bytes(action.path) != action.content
    if isinstance(action, MergeJson):
        return not _merge_is_current(action, fs)
    if isinstance(action, RemovePath):
        return _path_exists(action.path, fs)
    if isinstance(action, WriteManifest):
        desired = _manifest_bytes(action)
        return not fs.exists(MANIFEST_PATH) or fs.read_bytes(MANIFEST_PATH) != desired
    if isinstance(action, Warn):
        return False
    raise TypeError(f"cannot classify action: {type(action).__name__}")


def _operation_target(action: Action) -> Tuple[str, str]:
    if isinstance(action, CopyTree):
        return "copy-tree", action.dst
    if isinstance(action, SymlinkTree):
        return "symlink-tree", action.dst
    if isinstance(action, WriteFile):
        return "write-file", action.path
    if isinstance(action, MergeJson):
        identity = action.identity[0] if action.mode == "key" and action.identity else ""
        suffix = f".{identity}" if identity else ""
        return "merge-json", f"{action.file}#{action.json_path}{suffix}"
    if isinstance(action, RemovePath):
        return "remove-path", action.path
    if isinstance(action, WriteManifest):
        return "write-manifest", MANIFEST_PATH
    if isinstance(action, Warn):
        return "warn", action.message
    raise TypeError(f"cannot describe action: {type(action).__name__}")


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
        operation, target = _operation_target(action)
        if isinstance(action, Warn):
            performer(action, ctx)
            ctx.observations.append(
                EffectObservation(operation=operation, target=target, state="skipped")
            )
            continue
        try:
            if not _would_change(action, fs):
                ctx.observations.append(
                    EffectObservation(operation=operation, target=target, state="unchanged")
                )
                continue
            performer(action, ctx)
            ctx.observations.append(
                EffectObservation(operation=operation, target=target, state="changed")
            )
        except Exception as exc:
            detail = str(exc) or type(exc).__name__
            ctx.warnings.append(f"{operation} {target} failed: {detail}")
            ctx.observations.append(
                EffectObservation(
                    operation=operation,
                    target=target,
                    state="failed",
                    detail=detail,
                )
            )

    return Report(
        performed=tuple(ctx.performed),
        warnings=tuple(ctx.warnings),
        manifest_written=ctx.manifest_written,
        observations=tuple(ctx.observations),
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
