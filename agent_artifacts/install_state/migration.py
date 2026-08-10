"""Pure, deterministic planning of legacy consumer-state migration."""

from __future__ import annotations

import json
import posixpath

from agent_artifacts.configuration.model import git_location_parts
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import ArtifactCoordinate
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.manifest import parse_manifest
from agent_artifacts.model import Manifest, ManifestEntry
from agent_artifacts.protocol.hashing import json_digest, sha256_bytes
from agent_artifacts.protocol.json import (
    JsonArray,
    JsonObject,
    JsonValue,
    canonical_json_bytes,
    parse_json,
)

from .model import (
    InstallationRecord,
    InstallState,
    InstallStatePaths,
    LegacyMigrationCandidate,
    StateMigrationPlan,
)
from .schema import install_state_bytes

MIGRATION_INVALID = DiagnosticCode("state-migration-invalid")
MIGRATION_SOURCE_MISSING = DiagnosticCode("state-migration-source-missing")
MIGRATION_SOURCE_AMBIGUOUS = DiagnosticCode("state-migration-source-ambiguous")
MIGRATION_PROOF_MISMATCH = DiagnosticCode("state-migration-proof-mismatch")


def _error(code: DiagnosticCode, message: str) -> Err:
    return Err((Diagnostic(code, Severity.ERROR, message),))


def _legacy_key(entry: ManifestEntry) -> tuple[str, str, str, str]:
    return (entry.type, entry.artifact, entry.profile, entry.source)


def _fields(
    value: JsonValue,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
) -> dict[str, JsonValue] | None:
    if not isinstance(value, JsonObject):
        return None
    fields = dict(value.entries)
    present = frozenset(fields)
    return fields if present >= required and present <= required | optional else None


def _valid_legacy_structure(value: JsonValue) -> bool:
    root = _fields(value, frozenset({"repo", "installed"}))
    if (
        root is None
        or not isinstance(root["repo"], str)
        or not isinstance(root["installed"], JsonArray)
    ):
        return False
    for item in root["installed"].items:
        entry = _fields(
            item,
            frozenset({"artifact", "type", "profile", "source", "files", "installed_at"}),
            frozenset({"bundle", "install", "merge", "subscription"}),
        )
        if entry is None or any(
            not isinstance(entry[name], str)
            for name in ("artifact", "type", "profile", "source", "installed_at")
        ):
            return False
        if "bundle" in entry and not isinstance(entry["bundle"], str):
            return False
        files = entry["files"]
        if not isinstance(files, JsonObject) or any(
            not isinstance(path, str) or not isinstance(digest, str)
            for path, digest in files.entries
        ):
            return False
        if "install" in entry:
            install = _fields(
                entry["install"],
                frozenset(),
                frozenset({"mode", "requested_mode", "links"}),
            )
            if (
                install is None
                or ("mode" in install and not isinstance(install["mode"], str))
                or ("requested_mode" in install and not isinstance(install["requested_mode"], str))
                or ("links" in install and not isinstance(install["links"], JsonArray))
            ):
                return False
            links = install.get("links", JsonArray(()))
            assert isinstance(links, JsonArray)
            for raw_link in links.items:
                link = _fields(
                    raw_link,
                    frozenset({"path", "target"}),
                    frozenset({"target_kind"}),
                )
                if link is None or any(not isinstance(link[name], str) for name in link):
                    return False
        if "subscription" in entry:
            subscription = _fields(
                entry["subscription"],
                frozenset({"kind", "location"}),
                frozenset({"ref"}),
            )
            if subscription is None or any(
                not isinstance(subscription[name], str) for name in subscription
            ):
                return False
        if "merge" in entry:
            merge = _fields(
                entry["merge"],
                frozenset({"file", "json_path", "mode", "value_hash"}),
                frozenset({"identity", "created_file", "overwrote"}),
            )
            if (
                merge is None
                or any(
                    not isinstance(merge[name], str)
                    for name in ("file", "json_path", "mode", "value_hash")
                )
                or ("created_file" in merge and not isinstance(merge["created_file"], bool))
                or ("overwrote" in merge and not isinstance(merge["overwrote"], bool))
                or ("identity" in merge and not isinstance(merge["identity"], JsonObject))
            ):
                return False
    return True


def parse_legacy_manifest(legacy_content: bytes) -> Result[Manifest]:
    """Parse the bounded 0.1 manifest dialect as strict JSON before effect inspection."""

    try:
        legacy_text = legacy_content.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return _error(MIGRATION_INVALID, "legacy manifest is not valid UTF-8")
    strict_legacy = parse_json(legacy_content)
    if isinstance(strict_legacy, Err):
        return _error(
            MIGRATION_INVALID,
            "legacy manifest must be strict JSON without duplicate keys, floats, or invalid Unicode",
        )
    if not _valid_legacy_structure(strict_legacy.value):
        return _error(
            MIGRATION_INVALID,
            "legacy manifest shape contains missing, unknown, or incorrectly typed fields",
        )
    parsed = parse_manifest(legacy_text)
    if not hasattr(parsed, "value"):
        return _error(MIGRATION_INVALID, f"legacy manifest is invalid: {parsed.reason}")
    return Ok(parsed.value)


def _expected_destinations(entry: ManifestEntry) -> frozenset[str]:
    destinations = set(entry.files)
    if entry.merge is not None:
        destinations.add(entry.merge.file)
    return frozenset(destinations)


def _proof_matches(entry: ManifestEntry, candidate: LegacyMigrationCandidate) -> bool:
    by_destination = {effect.destination: effect for effect in candidate.effects}
    if frozenset(by_destination) != _expected_destinations(entry):
        return False
    linked_paths = {link.path for link in entry.install.links}
    if len(linked_paths) != len(entry.install.links) or not linked_paths <= set(entry.files):
        return False
    legacy_digests = dict(candidate.legacy_file_digests)
    if not frozenset(legacy_digests) <= frozenset(entry.files):
        return False
    for destination, digest in entry.files.items():
        effect = by_destination[destination]
        candidate_digest = legacy_digests.get(destination, str(effect.installed_digest))
        if digest and candidate_digest != digest:
            return False
        if destination in linked_paths and (
            effect.kind != "symlink-tree" or effect.actual_mode != "symlink"
        ):
            return False
        if destination not in linked_paths and effect.actual_mode != "copy":
            return False
    if entry.merge is not None:
        effect = by_destination[entry.merge.file]
        try:
            identity_content = json.dumps(
                dict(entry.merge.identity),
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        except (TypeError, ValueError):
            return False
        identity = parse_json(identity_content)
        if isinstance(identity, Err):
            return False
        if candidate.legacy_merge_value_hash is None:
            expected_path = entry.merge.json_path
            expected_identity = identity.value
            legacy_value_hash = str(effect.installed_digest)
        elif entry.merge.mode == "key":
            parts = entry.merge.json_path.split(".")
            if len(parts) < 2:
                return False
            expected_path = ".".join(parts[:-1])
            expected_identity = JsonArray((parts[-1],))
            legacy_value_hash = candidate.legacy_merge_value_hash
        else:
            expected_path = entry.merge.json_path
            expected_identity = identity.value
            legacy_value_hash = candidate.legacy_merge_value_hash
        if (
            effect.kind != "merge-json"
            or effect.json_path != expected_path
            or effect.merge_mode != entry.merge.mode
            or effect.identity_digest != json_digest(expected_identity)
            or (
                effect.identity_evidence != expected_identity
                if candidate.legacy_merge_value_hash is not None
                else effect.identity_evidence not in {None, expected_identity}
            )
            or legacy_value_hash != entry.merge.value_hash
            or effect.created_destination != entry.merge.created_file
            or effect.overwrote != entry.merge.overwrote
        ):
            return False
    return True


def _record(
    entry: ManifestEntry,
    candidate: LegacyMigrationCandidate,
    scope: str,
) -> Result[InstallationRecord]:
    if not _proof_matches(entry, candidate):
        return _error(
            MIGRATION_PROOF_MISMATCH,
            f"migration evidence does not prove the exact legacy effects for "
            f"{entry.type}/{entry.artifact}@{entry.profile}",
        )
    try:
        return Ok(
            InstallationRecord(
                coordinate=ArtifactCoordinate(candidate.source.alias, candidate.artifact.identity),
                source=candidate.source,
                artifact=candidate.artifact,
                profile=entry.profile,
                profile_version=candidate.profile_version,
                scope=scope,  # type: ignore[arg-type]
                requested_mode=entry.install.requested_mode,
                effects=candidate.effects,
                setup_state_ref=candidate.setup_state_ref,
            )
        )
    except ValueError as error:
        return _error(MIGRATION_INVALID, str(error))


def plan_legacy_migration(
    legacy_content: bytes,
    candidates: tuple[LegacyMigrationCandidate, ...],
    paths: InstallStatePaths,
    *,
    collision_index: int = 0,
) -> Result[StateMigrationPlan]:
    """Create an immutable dry-run plan; this function performs no IO."""

    parsed = parse_legacy_manifest(legacy_content)
    if isinstance(parsed, Err):
        return parsed

    records: list[InstallationRecord] = []
    for entry in parsed.value.installed:
        if (
            entry.subscription is not None
            and entry.subscription.kind == "github"
            and git_location_parts(entry.subscription.location) is None
        ):
            return _error(
                MIGRATION_INVALID,
                f"legacy subscription for {entry.type}/{entry.artifact}@{entry.profile} "
                "contains a credential-bearing or unsafe Git origin",
            )
        matches = tuple(
            candidate for candidate in candidates if candidate.legacy_key == _legacy_key(entry)
        )
        if not matches:
            return _error(
                MIGRATION_SOURCE_MISSING,
                f"no explicit canonical source evidence for legacy "
                f"{entry.type}/{entry.artifact}@{entry.profile} ({entry.source})",
            )
        if len(matches) != 1:
            return _error(
                MIGRATION_SOURCE_AMBIGUOUS,
                f"multiple canonical source candidates match legacy "
                f"{entry.type}/{entry.artifact}@{entry.profile} ({entry.source})",
            )
        converted = _record(entry, matches[0], paths.scope)
        if isinstance(converted, Err):
            return converted
        records.append(converted.value)
    try:
        state = InstallState(2, tuple(records))
    except ValueError as error:
        return _error(MIGRATION_INVALID, str(error))

    replacement = install_state_bytes(state)
    legacy_digest = sha256_bytes(legacy_content)
    replacement_digest = sha256_bytes(replacement)
    if (
        not isinstance(collision_index, int)
        or isinstance(collision_index, bool)
        or collision_index < 0
        or collision_index > 10_000
    ):
        return _error(MIGRATION_INVALID, "migration collision index is invalid")
    suffix = legacy_digest.value + ("" if collision_index == 0 else f"-{collision_index}")
    backup_path = posixpath.join(paths.backup_directory, f"manifest-v1-{suffix}.json")
    journal_path = posixpath.join(paths.journal_directory, f"manifest-v1-{suffix}.json")
    review_value = JsonObject(
        (
            ("schema_version", 1),
            ("scope", paths.scope),
            ("legacy_path", paths.legacy_path),
            ("destination_path", paths.destination_path),
            ("backup_path", backup_path),
            ("journal_path", journal_path),
            ("legacy_digest", str(legacy_digest)),
            ("replacement_digest", str(replacement_digest)),
        )
    )
    review_digest = json_digest(review_value)
    journal_content = canonical_json_bytes(
        JsonObject(
            (
                ("schema_version", 1),
                ("review_digest", str(review_digest)),
                ("scope", paths.scope),
                ("legacy_path", paths.legacy_path),
                ("destination_path", paths.destination_path),
                ("backup_path", backup_path),
                ("legacy_digest", str(legacy_digest)),
                ("replacement_digest", str(replacement_digest)),
            )
        )
    )
    try:
        return Ok(
            StateMigrationPlan(
                paths.scope,
                paths.legacy_path,
                paths.destination_path,
                backup_path,
                journal_path,
                paths.lock_path,
                legacy_digest,
                replacement_digest,
                legacy_content,
                replacement,
                journal_content,
                review_digest,
            )
        )
    except ValueError as error:
        return _error(MIGRATION_INVALID, str(error))
