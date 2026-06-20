"""Frozen data model — the shared contract for the whole system (WP-0).

Everything here is immutable data: domain records, the effect/`Action` algebra, the
`Plan`, the consumer manifest, and the `Result` type. No behaviour lives in this module;
logic lives in the pure core (catalog/policy/merge/manifest/planners) and the imperative
shell (io/executor/commands). See PLAN.md §2/§5 and DESIGN.md §14.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, Literal, Mapping, Optional, Tuple, TypeVar, Union

ArtifactType = Literal["skill", "guideline", "mcp", "hook"]

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
class Artifact:
    type: ArtifactType
    name: str
    root: str  # path of the artifact within the source, relative (e.g. "skills/code-review")


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
    mode: Literal["copy", "append-sentinel"]
    dest: str  # directory (copy) or file (append-sentinel)


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
class Profile:
    name: str
    skills: CopyTarget
    guidelines: GuidelineTarget
    mcp: MergeSpec
    hooks: HookTarget


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
