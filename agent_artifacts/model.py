"""Frozen data model — the shared contract for the whole system (WP-0).

Everything here is immutable data: domain records, the effect/`Action` algebra, the
`Plan`, the consumer manifest, and the `Result` type. No behaviour lives in this module;
logic lives in the pure core (catalog/policy/merge/manifest/planners) and the imperative
shell (io/executor/commands). See PLAN.md §2/§5 and DESIGN.md §14.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, Literal, Mapping, Optional, Tuple, TypeVar, Union

ArtifactType = Literal["skill", "guideline", "mcp", "hook", "memory"]

# Install modes for the `memory` instruction-file type (DESIGN-memory.md §3.2). Default when
# unspecified is "prepend"; resolution precedence is CLI flag → frontmatter `mode:` → default.
MemoryMode = Literal["replace", "prepend", "append", "skip"]

# --------------------------------------------------------------------------- #
# Result — errors as values (see fp.py for combinators).                       #
# Note: Generic + dataclass(slots=True) can conflict on some runtimes, so the  #
# Result variants intentionally do not use slots.                              #
# --------------------------------------------------------------------------- #
T = TypeVar("T")


@dataclass(frozen=True)
class Ok(Generic[T]):
    value: T


@dataclass(frozen=True)
class Err:
    reason: str
    code: int = 1


Result = Union[Ok, Err]  # conceptually Result[T]


# --------------------------------------------------------------------------- #
# Catalog (source side)                                                        #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Compatibility:
    profiles: Tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CompatibilityDecision:
    ok: bool
    reason: Optional[str] = None
    allowed_profiles: Tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SkippedTarget:
    artifact: str
    type: ArtifactType
    profile: str
    reason: str
    allowed_profiles: Tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Artifact:
    type: ArtifactType
    name: str
    root: str  # path of the artifact within the source, relative (e.g. "skills/code-review")
    compatibility: Optional[Compatibility] = None


@dataclass(frozen=True, slots=True)
class Bundle:
    name: str
    description: str
    extends: Tuple[str, ...]
    includes: Mapping[ArtifactType, Tuple[str, ...]]
    pins: Mapping[str, str]  # artifact name -> ref


@dataclass(frozen=True, slots=True)
class Catalog:
    artifacts: Mapping[Tuple[ArtifactType, str], Artifact]
    bundles: Mapping[str, Bundle]


@dataclass(frozen=True, slots=True)
class ResolvedBundle:
    name: str
    artifacts: Tuple[Tuple[ArtifactType, str], ...]  # ordered, de-duplicated
    pins: Mapping[str, str]  # artifact name -> resolved ref


# --------------------------------------------------------------------------- #
# Profiles (harness mapping — data, see DESIGN.md §11)                          #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class CopyTarget:
    dir: str  # may contain the "<name>" placeholder


@dataclass(frozen=True, slots=True)
class GuidelineTarget:
    # A guideline is a standalone reference doc copied into ``dest`` (a directory) as
    # ``<name>.md``. It is never merged into a shared file — that sentinel-block behaviour
    # belongs to the ``memory`` artifact (see ``MemoryTarget`` / ``MemoryMode``).
    dest: str


@dataclass(frozen=True, slots=True)
class MergeSpec:
    file: str
    json_path: str
    mode: Literal["key", "list"]
    identity: Tuple[str, ...] = ()
    entry_template: Optional[Mapping[str, object]] = None


@dataclass(frozen=True, slots=True)
class HookTarget:
    scripts_dir: str  # may contain "<name>"
    events: Mapping[str, str]  # abstract event name -> json_path under merge.file
    merge: MergeSpec


@dataclass(frozen=True, slots=True)
class MemoryTarget:
    """Where a harness's top-level instruction file lives (DESIGN-memory.md §4).

    ``kind="file"`` — a single shared instruction file (``CLAUDE.md`` / ``AGENTS.md``); all
    four `MemoryMode` modes apply. ``kind="dir"`` — the harness has no single instruction
    file (e.g. Tabnine), so the artifact is copied into ``dest`` as ``<name>.md`` and the
    content-merge modes do not apply (``skip`` still avoids overwriting an existing file).
    """

    kind: Literal["file", "dir"]
    dest: str  # the file (kind="file") or the directory (kind="dir")


@dataclass(frozen=True, slots=True)
class Profile:
    name: str
    # Every artifact-type target is optional: ``None`` means this harness does not support
    # that type (DESIGN-memory.md §5). Installing an unsupported type errors (by-name) or is
    # skipped with a warning (bundle/--all expansion).
    skills: Optional[CopyTarget] = None
    guidelines: Optional[GuidelineTarget] = None
    mcp: Optional[MergeSpec] = None
    hooks: Optional[HookTarget] = None
    memory: Optional[MemoryTarget] = None


# --------------------------------------------------------------------------- #
# Version resolution                                                           #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Resolved:
    kind: Literal["main", "pin"]
    sha: str


def source_label(resolved: Resolved) -> str:
    """`Resolved` -> the `"main:<sha>"` / `"pin:<sha>"` string stored in the manifest."""
    return f"{resolved.kind}:{resolved.sha}"


# --------------------------------------------------------------------------- #
# Effects as data — the Action algebra and the Plan (DESIGN.md §14)            #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class CopyTree:
    src: str
    dst: str


@dataclass(frozen=True, slots=True)
class WriteFile:
    path: str
    content: bytes


@dataclass(frozen=True, slots=True)
class MergeJson:
    file: str
    json_path: str
    mode: Literal["key", "list"]
    value: object
    identity: Tuple[str, ...]
    create_if_absent: bool = True


@dataclass(frozen=True, slots=True)
class RemovePath:
    path: str


@dataclass(frozen=True, slots=True)
class Warn:
    message: str


# WriteManifest references ManifestEntry (defined below); declared after it.


# --------------------------------------------------------------------------- #
# Consumer manifest (DESIGN.md §12)                                            #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class MergeProof:
    file: str
    json_path: str
    mode: Literal["key", "list"]
    identity: Mapping[str, object]
    value_hash: str
    created_file: bool = False
    overwrote: bool = False


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    artifact: str
    type: ArtifactType
    profile: str
    source: str  # "main:<sha>" | "pin:<sha>"
    bundle: Optional[str] = None
    files: Mapping[str, str] = field(default_factory=dict)  # path -> "sha256:…"
    merge: Optional[MergeProof] = None  # hooks carry both files and merge
    installed_at: str = ""


@dataclass(frozen=True, slots=True)
class Manifest:
    repo: str
    installed: Tuple[ManifestEntry, ...] = ()


@dataclass(frozen=True, slots=True)
class WriteManifest:
    entries: Tuple[ManifestEntry, ...]


Action = Union[CopyTree, WriteFile, MergeJson, RemovePath, WriteManifest, Warn]
Plan = Tuple[Action, ...]


# --------------------------------------------------------------------------- #
# Parsed CLI request (the input to the pure core)                              #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Request:
    command: str
    names: Tuple[str, ...] = ()
    bundles: Tuple[str, ...] = ()
    profiles: Tuple[str, ...] = ()
    all: bool = False
    version: Optional[str] = None
    source_dir: Optional[str] = None
    repo: Optional[str] = None
    project: Optional[str] = None
    type_filter: Optional[ArtifactType] = None
    yes: bool = False
    force: bool = False
    dry_run: bool = False
    json: bool = False
    prune: bool = False
    memory_mode: Optional[str] = None  # DESIGN-memory.md §3.4; None → planner applies "prepend"
    upstream_action: Optional[str] = None  # "check" | "update" for maintainer-side upstreams
