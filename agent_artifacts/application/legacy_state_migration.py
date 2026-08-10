"""Resolve 0.1 installation facts into explicit canonical migration evidence.

The functional core consumes immutable marketplace data plus already-inspected filesystem
snapshots. The small application function below performs only bounded reads through the install
port; it never writes, syncs a source, or guesses between equal artifact identities.
"""

from __future__ import annotations

import json
import posixpath
import re
from dataclasses import dataclass
from typing import Mapping, Protocol

from agent_artifacts.configuration.model import ConfiguredSource, SourceKind, git_location_parts
from agent_artifacts.consumer.model import ConsumerContext
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import ArtifactIdentity, SourceAlias
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.install_state.migration import parse_legacy_manifest
from agent_artifacts.install_state.model import (
    ArtifactEvidence,
    EffectProof,
    InstallScope,
    LegacyMigrationCandidate,
    SourceEvidence,
)
from agent_artifacts.installation.model import InstallLocation, PathSnapshot
from agent_artifacts.marketplace.model import MarketplaceItem
from agent_artifacts.model import ManifestEntry
from agent_artifacts.protocol.hashing import json_digest, sha256_bytes
from agent_artifacts.protocol.json import JsonArray, JsonObject, JsonValue, parse_json
from agent_artifacts.protocol.semver import SemVer

MIGRATION_RESOLUTION_INVALID = DiagnosticCode("state-migration-resolution-invalid")
MIGRATION_SOURCE_MISSING = DiagnosticCode("state-migration-source-missing")
MIGRATION_SOURCE_AMBIGUOUS = DiagnosticCode("state-migration-source-ambiguous")
MIGRATION_EFFECT_MISSING = DiagnosticCode("state-migration-effect-missing")
_SLUG_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_ARTIFACT_KINDS = frozenset({"skill", "guideline", "mcp", "hook", "memory"})
_MAPPING_RE = re.compile(
    r"^(?P<kind>skill|guideline|mcp|hook|memory)/"
    r"(?P<name>[a-z][a-z0-9]*(?:-[a-z0-9]+)*)@"
    r"(?P<profile>[a-z][a-z0-9]*(?:-[a-z0-9]+)*)="
    r"(?P<alias>[a-z][a-z0-9]*(?:-[a-z0-9]+)*)$"
)


def _error(code: DiagnosticCode, message: str, *remediation: str) -> Err:
    return Err((Diagnostic(code, Severity.ERROR, message, remediation=remediation),))


@dataclass(frozen=True, slots=True)
class LegacySourceMapping:
    identity: ArtifactIdentity
    profile: str
    alias: SourceAlias

    @property
    def key(self) -> tuple[ArtifactIdentity, str]:
        return (self.identity, self.profile)


@dataclass(frozen=True, slots=True)
class LegacyStateMigrationRequest:
    legacy_content: bytes
    scope: InstallScope
    source_mappings: tuple[LegacySourceMapping, ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.legacy_content, bytes)
            or self.scope not in {"project", "user"}
            or len({item.key for item in self.source_mappings}) != len(self.source_mappings)
        ):
            raise ValueError("legacy state migration request is invalid")


class LegacyInspectionPort(Protocol):
    def inspect_path(self, path: str) -> Result[PathSnapshot]: ...


def parse_source_mappings(values: tuple[str, ...]) -> Result[tuple[LegacySourceMapping, ...]]:
    """Parse repeatable ``TYPE/NAME@PROFILE=ALIAS`` resolutions without shorthand guessing."""

    mappings: list[LegacySourceMapping] = []
    for raw in values:
        match = _MAPPING_RE.fullmatch(raw)
        if match is None:
            return _error(
                MIGRATION_RESOLUTION_INVALID,
                f"invalid source mapping {raw!r}; expected TYPE/NAME@PROFILE=ALIAS",
            )
        mappings.append(
            LegacySourceMapping(
                ArtifactIdentity(match.group("kind"), match.group("name")),  # type: ignore[arg-type]
                match.group("profile"),
                SourceAlias(match.group("alias")),
            )
        )
    ordered = tuple(sorted(mappings, key=lambda item: (str(item.identity), item.profile)))
    if len({item.key for item in ordered}) != len(ordered):
        return _error(
            MIGRATION_RESOLUTION_INVALID,
            "each legacy artifact/profile may have only one explicit source mapping",
        )
    return Ok(ordered)


def _configured(context: ConsumerContext, alias: SourceAlias) -> ConfiguredSource | None:
    return next(
        (
            source
            for source in context.effective.configuration.sources
            if source.enabled and source.alias == alias
        ),
        None,
    )


def _same_git(left: str, right: str) -> bool:
    left_parts = git_location_parts(left)
    right_parts = git_location_parts(right)
    return left_parts is not None and left_parts == right_parts


def _subscription_matches(entry: ManifestEntry, source: ConfiguredSource) -> bool:
    subscription = entry.subscription
    if subscription is None or subscription.kind == "package":
        return True
    if subscription.kind == "local":
        return (
            source.kind is SourceKind.SOURCE_LOCAL
            and posixpath.abspath(subscription.location) == source.location
        )
    return (
        source.is_git
        and _same_git(subscription.location, source.location)
        and subscription.ref == source.ref
    )


def _select_item(
    entry: ManifestEntry,
    context: ConsumerContext,
    mappings: Mapping[tuple[ArtifactIdentity, str], SourceAlias],
) -> Result[MarketplaceItem]:
    if (
        entry.type not in _ARTIFACT_KINDS
        or not isinstance(entry.artifact, str)
        or _SLUG_RE.fullmatch(entry.artifact) is None
        or not isinstance(entry.profile, str)
        or _SLUG_RE.fullmatch(entry.profile) is None
    ):
        return _error(
            MIGRATION_RESOLUTION_INVALID,
            "legacy artifact type, name, and profile must use canonical identifiers",
        )
    identity = ArtifactIdentity(entry.type, entry.artifact)
    items = tuple(item for item in context.catalog.items if item.coordinate.artifact == identity)
    requested = mappings.get((identity, entry.profile))
    if requested is not None:
        selected = tuple(item for item in items if item.source.alias == requested)
        if len(selected) == 1:
            return Ok(selected[0])
        return _error(
            MIGRATION_SOURCE_MISSING,
            f"explicit source {requested.value!r} does not provide {identity}",
            "sync or enable the selected source, then retry the migration",
        )
    compatible = tuple(
        item
        for item in items
        if (configured := _configured(context, item.source.alias)) is not None
        and _subscription_matches(entry, configured)
    )
    # Package-era and subscription-less manifests have no durable alias. A single qualified
    # artifact is unambiguous; two are never resolved by display order/default registry.
    candidates = compatible if entry.subscription is not None else items
    if len(candidates) == 1:
        return Ok(candidates[0])
    mapping = f"{identity}@{entry.profile}=ALIAS"
    if not candidates:
        return _error(
            MIGRATION_SOURCE_MISSING,
            f"no configured current source can resolve legacy {identity}@{entry.profile}",
            "enable and sync a compatible source in the TUI",
            f"or pass --source-map {mapping}",
        )
    aliases = ", ".join(item.source.alias.value for item in candidates)
    return _error(
        MIGRATION_SOURCE_AMBIGUOUS,
        f"legacy {identity}@{entry.profile} exists in multiple sources: {aliases}",
        f"pass --source-map {mapping}",
    )


def _absolute_destination(
    destination: str,
    scope: InstallScope,
    location: InstallLocation,
) -> Result[str]:
    normalized = posixpath.normpath(destination)
    if scope == "user":
        if posixpath.isabs(normalized) and normalized != "/":
            return Ok(normalized)
        return _error(
            MIGRATION_RESOLUTION_INVALID,
            f"legacy user destination is not an absolute path: {destination}",
        )
    if posixpath.isabs(normalized):
        return _error(
            MIGRATION_RESOLUTION_INVALID,
            f"legacy project destination is not relative: {destination}",
        )
    absolute = posixpath.normpath(posixpath.join(location.project_root, normalized))
    try:
        contained = posixpath.commonpath((location.project_root, absolute)) == location.project_root
    except ValueError:
        contained = False
    if not contained or absolute == location.project_root:
        return _error(
            MIGRATION_RESOLUTION_INVALID,
            f"legacy project destination escapes its project: {destination}",
        )
    return Ok(absolute)


def _source_path(entry: ManifestEntry, snapshot: PathSnapshot) -> str | None:
    if snapshot.kind == "tree" or entry.type in {"skill", "hook"}:
        return "payload"
    if entry.type in {"guideline", "memory"}:
        return f"payload/{entry.artifact}.md"
    return "payload/content"


def _memory_is_managed(entry: ManifestEntry, snapshot: PathSnapshot) -> bool:
    if entry.type != "memory" or snapshot.kind != "file":
        return False
    try:
        text = snapshot.content.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return False
    begin = f"<!-- >>> agent-artifacts memory:{entry.artifact} >>> -->"
    end = f"<!-- <<< agent-artifacts memory:{entry.artifact} <<< -->"
    return text.count(begin) == text.count(end) == 1 and text.index(begin) < text.index(end)


def _file_effect(
    entry: ManifestEntry,
    destination: str,
    snapshot: PathSnapshot,
    link_target: str | None,
    ports: LegacyInspectionPort,
) -> Result[EffectProof]:
    if link_target is not None:
        if (
            snapshot.kind != "symlink"
            or snapshot.link_target is None
            or posixpath.normpath(snapshot.link_target) != posixpath.normpath(link_target)
            or not posixpath.isabs(link_target)
        ):
            return _error(
                MIGRATION_EFFECT_MISSING,
                f"legacy symlink proof no longer matches {destination}",
            )
        target = ports.inspect_path(link_target)
        if isinstance(target, Err):
            return target
        if target.value.kind != "tree" or target.value.digest is None:
            return _error(
                MIGRATION_EFFECT_MISSING,
                f"legacy symlink target is not a readable directory tree: {link_target}",
            )
        return Ok(
            EffectProof(
                "symlink-tree",
                destination,
                "symlink",
                target.value.digest,
                source_path="payload",
                link_target=link_target,
                link_semantics="mutable-local",
            )
        )
    if snapshot.kind not in {"file", "tree"} or snapshot.digest is None:
        return _error(
            MIGRATION_EFFECT_MISSING,
            f"legacy installed destination is missing or unsafe: {destination}",
        )
    if snapshot.kind == "tree":
        kind = "copy-tree"
    elif _memory_is_managed(entry, snapshot):
        kind = "managed-block"
    else:
        kind = "write-file"
    return Ok(
        EffectProof(
            kind,  # type: ignore[arg-type]
            destination,
            "copy",
            snapshot.digest,
            source_path=(None if kind == "managed-block" else _source_path(entry, snapshot)),
        )
    )


def _navigate(value: object, path: str) -> tuple[bool, object]:
    node = value
    for part in path.split(".") if path else ():
        if not isinstance(node, dict) or part not in node:
            return False, None
        node = node[part]
    return True, node


def _identity_value(value: object, field: str) -> tuple[bool, object]:
    if isinstance(value, dict):
        if field in value:
            return True, value[field]
        for child in value.values():
            found, item = _identity_value(child, field)
            if found:
                return True, item
    elif isinstance(value, list):
        for child in value:
            found, item = _identity_value(child, field)
            if found:
                return True, item
    return False, None


def _json_value(value: object) -> Result[JsonValue]:
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError, UnicodeError):
        return _error(MIGRATION_EFFECT_MISSING, "legacy merge value is not strict JSON")
    return parse_json(encoded)


def _merge_effect(
    entry: ManifestEntry,
    destination: str,
    snapshot: PathSnapshot,
) -> Result[tuple[EffectProof, str]]:
    assert entry.merge is not None
    if snapshot.kind != "file":
        return _error(
            MIGRATION_EFFECT_MISSING,
            f"legacy merge destination is not a regular file: {destination}",
        )
    strict = parse_json(snapshot.content)
    if isinstance(strict, Err) or not isinstance(strict.value, JsonObject):
        return _error(
            MIGRATION_EFFECT_MISSING,
            f"legacy merge destination is not strict JSON: {destination}",
        )
    try:
        root = json.loads(snapshot.content.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error(MIGRATION_EFFECT_MISSING, f"cannot inspect legacy merge at {destination}")
    proof = entry.merge
    if proof.mode == "key":
        parts = proof.json_path.split(".")
        if len(parts) < 2:
            return _error(
                MIGRATION_EFFECT_MISSING,
                f"legacy keyed merge path has no managed key: {proof.json_path}",
            )
        found, value = _navigate(root, proof.json_path)
        json_path = ".".join(parts[:-1])
        identity_evidence: JsonValue = JsonArray((parts[-1],))
    else:
        if not proof.identity:
            return _error(
                MIGRATION_EFFECT_MISSING,
                f"legacy list merge has no identity evidence: {proof.file}#{proof.json_path}",
            )
        found, container = _navigate(root, proof.json_path)
        matches: list[object] = []
        if found and isinstance(container, list):
            for value in container:
                if all(
                    _identity_value(value, field) == (True, expected)
                    for field, expected in proof.identity.items()
                ):
                    matches.append(value)
        found = len(matches) == 1
        value = matches[0] if found else None
        json_path = proof.json_path
        identity = _json_value(dict(proof.identity))
        if isinstance(identity, Err):
            return identity
        identity_evidence = identity.value
    if not found:
        return _error(
            MIGRATION_EFFECT_MISSING,
            f"legacy merge value is absent or ambiguous at {proof.file}#{proof.json_path}",
        )
    legacy_hash = "sha256:" + sha256_bytes(repr(value).encode("utf-8")).value
    if legacy_hash != proof.value_hash:
        return _error(
            MIGRATION_EFFECT_MISSING,
            f"legacy merge value drifted at {proof.file}#{proof.json_path}",
        )
    canonical = _json_value(value)
    if isinstance(canonical, Err):
        return canonical
    return Ok(
        (
            EffectProof(
                "merge-json",
                destination,
                "copy",
                json_digest(canonical.value),
                json_path=json_path,
                merge_mode=proof.mode,
                identity_digest=json_digest(identity_evidence),
                identity_evidence=identity_evidence,
                created_destination=proof.created_file,
                overwrote=proof.overwrote,
            ),
            legacy_hash,
        )
    )


def _artifact_evidence(entry: ManifestEntry, effects: tuple[EffectProof, ...]) -> ArtifactEvidence:
    identity = ArtifactIdentity(entry.type, entry.artifact)
    seed = (
        f"{entry.type}/{entry.artifact}@{entry.profile}\0{entry.source}\0"
        + "\0".join(
            f"{effect.kind}:{effect.destination}:{effect.installed_digest}" for effect in effects
        )
    ).encode("utf-8")
    return ArtifactEvidence(
        identity,
        SemVer(0, 1, 0, ("legacy",)),
        sha256_bytes(b"legacy-manifest\0" + seed),
        sha256_bytes(b"legacy-payload\0" + seed),
        sha256_bytes(b"legacy-object\0" + seed),
    )


def _candidate(
    entry: ManifestEntry,
    item: MarketplaceItem,
    context: ConsumerContext,
    scope: InstallScope,
    ports: LegacyInspectionPort,
) -> Result[LegacyMigrationCandidate]:
    configured = _configured(context, item.source.alias)
    if configured is None or item.source.source_id is None or item.source.resolved_revision is None:
        return _error(MIGRATION_SOURCE_MISSING, "selected migration source is not current")
    links = {link.path: link.target for link in entry.install.links}
    effects: list[EffectProof] = []
    legacy_digests: list[tuple[str, str]] = []
    for destination, legacy_digest in entry.files.items():
        absolute = _absolute_destination(destination, scope, context.location)
        if isinstance(absolute, Err):
            return absolute
        observed = ports.inspect_path(absolute.value)
        if isinstance(observed, Err):
            return observed
        effect = _file_effect(
            entry,
            destination,
            observed.value,
            links.get(destination),
            ports,
        )
        if isinstance(effect, Err):
            return effect
        if legacy_digest:
            if observed.value.kind != "file":
                return _error(
                    MIGRATION_EFFECT_MISSING,
                    f"legacy raw digest cannot prove a non-file destination: {destination}",
                )
            actual = "sha256:" + sha256_bytes(observed.value.content).value
            if actual != legacy_digest:
                return _error(
                    MIGRATION_EFFECT_MISSING,
                    f"legacy installed file drifted: {destination}",
                )
            legacy_digests.append((destination, actual))
        effects.append(effect.value)
    merge_hash: str | None = None
    if entry.merge is not None:
        absolute = _absolute_destination(entry.merge.file, scope, context.location)
        if isinstance(absolute, Err):
            return absolute
        observed = ports.inspect_path(absolute.value)
        if isinstance(observed, Err):
            return observed
        merge = _merge_effect(entry, entry.merge.file, observed.value)
        if isinstance(merge, Err):
            return merge
        effects.append(merge.value[0])
        merge_hash = merge.value[1]
    if not effects:
        return _error(
            MIGRATION_EFFECT_MISSING,
            f"legacy {entry.type}/{entry.artifact}@{entry.profile} has no installed effects",
        )
    try:
        source = SourceEvidence(
            item.source.alias,
            item.source.source_id,
            item.source.kind,
            item.source.origin,
            item.source.resolved_revision,
            configured.ref,
        )
        return Ok(
            LegacyMigrationCandidate(
                entry.artifact,
                entry.type,
                entry.profile,
                entry.source,
                source,
                _artifact_evidence(entry, tuple(effects)),
                1,
                tuple(effects),
                legacy_file_digests=tuple(legacy_digests),
                legacy_merge_value_hash=merge_hash,
            )
        )
    except ValueError as error:
        return _error(MIGRATION_RESOLUTION_INVALID, str(error))


def build_legacy_migration_candidates(
    request: LegacyStateMigrationRequest,
    context: ConsumerContext,
    ports: LegacyInspectionPort,
) -> Result[tuple[LegacyMigrationCandidate, ...]]:
    """Inspect only destinations named by validated legacy state and resolve every source."""

    parsed = parse_legacy_manifest(request.legacy_content)
    if isinstance(parsed, Err):
        return parsed
    mappings = {item.key: item.alias for item in request.source_mappings}
    candidates: list[LegacyMigrationCandidate] = []
    for entry in parsed.value.installed:
        if entry.profile not in context.profiles:
            return _error(
                MIGRATION_RESOLUTION_INVALID,
                f"legacy profile is not supported by this AART build: {entry.profile}",
            )
        item = _select_item(entry, context, mappings)
        if isinstance(item, Err):
            return item
        built = _candidate(entry, item.value, context, request.scope, ports)
        if isinstance(built, Err):
            return built
        candidates.append(built.value)
    return Ok(tuple(candidates))


__all__ = [
    "LegacySourceMapping",
    "LegacyStateMigrationRequest",
    "build_legacy_migration_candidates",
    "parse_source_mappings",
]
