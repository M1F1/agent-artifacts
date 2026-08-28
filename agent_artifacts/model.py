"""Frozen data model — the shared contract for the whole system (WP-0).

Everything here is immutable data: domain records, the effect/`Action` algebra, the
`Plan`, the consumer manifest, and the `Result` type. No behaviour lives in this module;
logic lives in the pure core (catalog/policy/merge/manifest/planners) and the imperative
shell (io/executor/commands). See docs/plan/PLAN.md §2/§5 and docs/design/DESIGN.md §14.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, Literal, Mapping, Optional, Tuple, TypeVar, Union

ArtifactType = Literal["skill", "guideline", "mcp", "hook", "memory"]

# Consumer destination/state boundary. Project remains the backward-compatible default;
# user scope resolves explicit harness targets under the current user's home directory.
InstallScope = Literal["project", "user"]

# Install mode for directory tree artifacts. Copy is the stable default; symlink is an
# explicit local/live-linked mode.
InstallMode = Literal["copy", "symlink"]

# Install modes for the `memory` instruction-file type (docs/design/DESIGN-memory.md §3.2). Default when
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
SetupCapability = Literal[
    "keychain",
    "filesystem",
    "docker",
    "network",
    "process",
    "custom-code",
    # Reading the machine's public certificate list is a materially smaller claim than reaching
    # into its credential store, and a review that called both "keychain" would teach the reader
    # to discount the word.
    "trust-store",
]
SetupTerminalStatus = Literal[
    "configured",
    "already_configured",
    "cancelled",
    "skipped",
    "unsupported",
    "prerequisite_missing",
    "apply_failed_rolled_back",
    "rollback_incomplete",
    "verification_failed",
]


@dataclass(frozen=True, slots=True)
class SetupHelpUrl:
    label: str
    url: str


@dataclass(frozen=True, slots=True)
class SetupInput:
    id: str
    type: Literal["secret", "text"]
    prompt: str
    help_url: Optional[str] = None


@dataclass(frozen=True, slots=True)
class SetupStep:
    id: str
    use: str
    config: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class SetupInstaller:
    schema_version: int
    protocol_version: int
    artifact: str
    purpose: str
    platforms: Tuple[str, ...]
    help_urls: Tuple[SetupHelpUrl, ...]
    required_tools: Tuple[str, ...]
    capabilities: Tuple[SetupCapability, ...]
    inputs: Tuple[SetupInput, ...]
    steps: Tuple[SetupStep, ...]
    descriptor_path: str
    descriptor_hash: str
    # The fixed package-relative manual route, derived from the recipe path rather than declared
    # by the author, so every validated installer carries exactly one.
    manual_path: str
    custom_entrypoint: Optional[str] = None
    custom_hash: Optional[str] = None


@dataclass(frozen=True, slots=True)
class SetupManualReference:
    """One immutable manual-setup route: every validated recipe carries exactly one."""

    relative_path: str
    source: str


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
    # Catalog parsers always populate a normalized, non-empty, single-line description.
    # The default preserves lightweight hand-built domain fixtures outside the parser boundary.
    description: str = ""
    setup: Optional[SetupInstaller] = None


@dataclass(frozen=True, slots=True)
class SetupQueueItem:
    artifact_type: ArtifactType
    artifact_name: str
    profile: str
    scope: InstallScope
    source_label: str
    source_root: str
    installer: SetupInstaller
    # Either a verified commit-pinned web root or empty. Rendering falls back to the contained
    # absolute local path; a moving branch URL is never emitted as setup provenance.
    source_url: str = ""
    # The installed artifact's own version, carried because a locally built image is tagged from
    # identity and version rather than from anything the recipe may author. Empty only where a
    # queue item is built outside an installation record, which no build step may plan against.
    artifact_version: str = ""


@dataclass(frozen=True, slots=True)
class SetupEffect:
    step_id: str
    module: str
    capability: Optional[SetupCapability]
    summary: str
    target: str = ""
    argv: Tuple[str, ...] = ()
    reversible: bool = False
    config: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SetupPlan:
    item: SetupQueueItem
    effects: Tuple[SetupEffect, ...]
    plan_hash: str
    target_root: str = ""
    home_root: str = ""
    run_root: str = ""
    preflight_status: Optional[SetupTerminalStatus] = None
    preflight_detail: str = ""


@dataclass(frozen=True, slots=True)
class SetupStateRecord:
    artifact_type: ArtifactType
    artifact_name: str
    profile: str
    scope: InstallScope
    status: SetupTerminalStatus
    detail: str
    source_label: str = ""
    installer_path: str = ""
    installer_hash: str = ""
    custom_hash: str = ""
    schema_version: int = 1
    protocol_version: int = 1
    plan_hash: str = ""
    started_at: str = ""
    finished_at: str = ""
    exit_status: Optional[int] = None
    retry_command: str = ""
    rollback_command: str = ""
    receipt_path: str = ""
    receipt: Tuple[Mapping[str, object], ...] = ()
    # Canonical SET01 evidence. Empty values preserve the 0.1.x setup-state reader while new
    # executions bind their receipt to one installed object, trust/policy decision, and Review.
    object_digest: str = ""
    recipe_digest: str = ""
    trust: str = ""
    trust_evidence_digest: str = ""
    policy_digest: str = ""
    capability_plan_digest: str = ""
    canonical_review_digest: str = ""
    setup_state_ref: str = ""


@dataclass(frozen=True, slots=True)
class SetupState:
    records: Tuple[SetupStateRecord, ...] = ()


# Profile/harness mapping types live in ``agent_artifacts.profiles.model``; that module is
# the single definition of the canonical profile data. Nothing may re-declare them here.


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
# Effects as data — the Action algebra and the Plan (docs/design/DESIGN.md §14)            #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class CopyTree:
    src: str
    dst: str


@dataclass(frozen=True, slots=True)
class SymlinkTree:
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
# Consumer manifest (docs/design/DESIGN.md §12)                                            #
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
class InstallLink:
    path: str
    target: str
    target_kind: Literal["dir"] = "dir"


@dataclass(frozen=True, slots=True)
class InstallProof:
    mode: InstallMode = "copy"
    requested_mode: InstallMode = "copy"
    links: Tuple[InstallLink, ...] = ()


@dataclass(frozen=True, slots=True)
class CatalogSubscription:
    """Stable identity of the catalog to reopen for a consumer update.

    ``ManifestEntry.source`` records the resolved content version.  This value records the
    unresolved subscription: packaged/local catalog root, or GitHub repository and ref.
    """

    kind: Literal["package", "local", "github"]
    location: str
    ref: Optional[str] = None


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    artifact: str
    type: ArtifactType
    profile: str
    source: str  # "main:<sha>" | "pin:<sha>"
    collection: Optional[str] = None
    files: Mapping[str, str] = field(default_factory=dict)  # path -> "sha256:…"
    merge: Optional[MergeProof] = None  # hooks carry both files and merge
    installed_at: str = ""
    install: InstallProof = field(default_factory=InstallProof)
    subscription: Optional[CatalogSubscription] = None


@dataclass(frozen=True, slots=True)
class Manifest:
    repo: str
    installed: Tuple[ManifestEntry, ...] = ()


@dataclass(frozen=True, slots=True)
class WriteManifest:
    entries: Tuple[ManifestEntry, ...]


Action = Union[CopyTree, SymlinkTree, WriteFile, MergeJson, RemovePath, WriteManifest, Warn]
Plan = Tuple[Action, ...]


# --------------------------------------------------------------------------- #
# Parsed CLI request (the input to the pure core)                              #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Request:
    command: str
    names: Tuple[str, ...] = ()
    profiles: Tuple[str, ...] = ()
    # A registry workspace path for registry authoring commands.  Consumer operations only read
    # configured canonical sources and never accept an arbitrary catalog directory.
    source_dir: Optional[str] = None
    project: Optional[str] = None
    scope: InstallScope = "project"
    # Adapter/test injection only; not exposed as a public CLI flag. ``None`` resolves via
    # ``expanduser('~')`` at the command boundary.
    user_home: Optional[str] = None
    artifact_kind: Optional[ArtifactType] = None
    yes: bool = False
    force: bool = False
    dry_run: bool = False
    json: bool = False
    prune: bool = False
    install_mode: InstallMode = "copy"
    # How a ``memory`` artifact meets an existing harness instruction file.  ``None`` lets the
    # canonical default (``prepend``) apply; an installed record keeps its own recorded mode
    # across later updates.
    memory_mode: Optional[MemoryMode] = None
    # Git reference supplied only while adding a configured canonical source.
    ref: Optional[str] = None
    # Exact native package reference used by registry promotion.  These fields are deliberately
    # distinct from configured consumer sources: a maintainer reviews an explicit Git package
    # before its registry entry is allowed to name it.
    native_url: Optional[str] = None
    native_path: Optional[str] = None
    # A package-relative setup recipe declared while vendoring, when the maintainer has authored
    # one beside the copied payload.
    setup_recipe: Optional[str] = None
    review_policy: Optional[str] = None
    registry_action: Optional[str] = None
    check: bool = False
    # Resolve vendored origins during an audit.  Off by default: an audit that reached the network
    # unasked would fail offline and depend on somebody else's uptime in CI.
    check_upstream: bool = False
    strict: bool = False
    frozen: bool = False
    source_id: Optional[str] = None
    display_name: Optional[str] = None
    # Optional registry-owned GitHub Issues destination advertised by ``registry init``.
    usage_reporting_repository: Optional[str] = None
    summary: Optional[str] = None
    collection_members: Tuple[str, ...] = ()
    # Discovery emits, and batch vendoring consumes, one reviewable JSON manifest.  The checkout
    # is deliberately distinct from the registry source: it is inert foreign input, never a
    # configured consumer source.
    discovery_checkout: Optional[str] = None
    discovery_output: Optional[str] = None
    discovery_accept_all: bool = False
    vendor_manifest: Optional[str] = None
    publish_message: Optional[str] = None
    artifact_version: Optional[str] = None
    # The licence the registry records for a vendored copy.  Stated by the maintainer, because a
    # licence read out of an upstream file is a reading of somebody else's document.
    artifact_license: Optional[str] = None
    minimum_version: Optional[str] = None
    maximum_version: Optional[str] = None
    latest_version: Optional[str] = None
    compatibility: Optional[str] = None
    registry_scopes: Tuple[str, ...] = ()
    registry_modes: Tuple[str, ...] = ()
    registry_platforms: Tuple[str, ...] = ()
    security_action: Optional[str] = None
    # Which `marketplace receipt` action was asked for.  Kept beside the other per-family
    # action fields rather than reusing one, so an unrelated command cannot select a receipt.
    receipt_action: Optional[str] = None
    security_input: Optional[str] = None
    security_artifact: Optional[str] = None
    registry_index: Optional[str] = None
    registry_lock: Optional[str] = None
    security_cache: Optional[str] = None
    security_object_digest: Optional[str] = None
    security_rules_digest: Optional[str] = None
    security_options_digest: Optional[str] = None
    security_policy_digest: Optional[str] = None
    security_provider_version: Optional[str] = None
    publisher_source_id: Optional[str] = None
    security_registry_inputs_digest: Optional[str] = None
    publisher_trust: Optional[str] = None
    reporting_action: Optional[str] = None
    reporting_input: Optional[str] = None
    reporting_output: Optional[str] = None
    # Canonical configured-source command surface.
    source_action: Optional[str] = None
    source_alias: Optional[str] = None
    source_kind: Optional[str] = None
    source_location: Optional[str] = None
    source_make_default: Optional[bool] = None
    marketplace_action: Optional[str] = None
    # The words `marketplace search` was given, kept apart from `names`.  `names` holds
    # coordinates, which are parsed and must resolve; these are free text, which matches or does
    # not.  One field for both would make a typo in a coordinate look like a search that found
    # nothing.
    query: Tuple[str, ...] = ()
    # How many rows a search prints.  ``None`` prints every match: a catalog is finite and the
    # person asked.
    search_limit: Optional[int] = None
    runtime_environment: Optional[str] = None
    # Canonical lifecycle gates.  Each defaults to the denying value so that neither an agent nor a
    # script can acquire an authorization by omitting a flag.
    offline: bool = False
    # The digest a human actually reviewed, carried from the reviewing command to the finalizing
    # one.  ``--yes`` alone still means "finalize what this process just computed"; supplying this
    # additionally requires that what was reviewed is still what would happen.
    expect: Optional[str] = None
    authorize_untrusted_source: bool = False
    authorize_custom_entrypoint: bool = False
    approve_setup_effects: bool = False
    upgrade_wheel: Optional[str] = None
    upgrade_source_checkout: Optional[str] = None
