"""Project a canonical package from foreign bytes (VN-2).

`VN-1` takes a subtree out of a repository that knows nothing about AART. This turns that subtree
into an ordinary owned registry package: the taken bytes become `payload/`, the maintainer's authored
`artifact.json` gives it an identity, and `provenance.json` records verifiably where the bytes came
from and with what options.

The result is deliberately not a new kind of thing (design §2). It is an owned package that happens
to carry `provenance.json`, so the index projection, the security baseline's cross-check, and the
installer's credential-free-origin check all already apply to it, and a `2.0.0` consumer reads it.

What this module refuses is the package that would not load. A projection whose payload does not
satisfy its declared kind is refused here, naming the document the kind requires, rather than
emitted for `registry validate` to reject later against a manifest the maintainer did not write by
hand.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast

from agent_artifacts.domain.diagnostics import Diagnostic, Severity, SourceLocation
from agent_artifacts.domain.identifiers import ArtifactIdentity, ObjectDigest, SourceId
from agent_artifacts.domain.result import Err, Ok, Result
from agent_artifacts.protocol.codes import ARTIFACT_INVALID
from agent_artifacts.protocol.hashing import json_digest
from agent_artifacts.protocol.json import (
    JsonArray,
    JsonObject,
    canonical_json_bytes,
    parse_json,
)
from agent_artifacts.protocol.native_models import (
    INSTALL_EFFECTS_BY_TYPE,
    PAYLOAD_FORMAT_BY_TYPE,
    ArtifactManifest,
    CanonicalArtifactType,
    CompatibilitySpec,
    ImporterProvenance,
    InstallMode,
    InstallScope,
    InstallSpec,
    OriginProvenance,
    PayloadSpec,
    Provenance,
    SetupReference,
)
from agent_artifacts.protocol.native_schema import (
    artifact_manifest_to_json,
    provenance_to_json,
)
from agent_artifacts.protocol.native_tree import (
    SnapshotEntry,
    SnapshotEntryKind,
    SnapshotOrigin,
    SourceSnapshot,
    compile_native_package,
)
from agent_artifacts.protocol.paths import SafeRelativePath, parse_relative_path
from agent_artifacts.protocol.registry_index import index_artifact_from_package
from agent_artifacts.protocol.semver import SemVer
from agent_artifacts.security.attestation_schema import attestation_bytes
from agent_artifacts.security.attestations import (
    EMPTY_CACHE_INPUT_DIGEST,
    AssessmentCacheKey,
    AttestationOrigin,
    AttestationOriginKind,
    SecurityAttestation,
    attestation_digest,
)
from agent_artifacts.security.baseline import (
    BASELINE_PROVIDER_ID,
    BASELINE_PROVIDER_VERSION,
    BASELINE_RULES_DIGEST,
    BaselineScanRequest,
    assess_installation_risk,
)
from agent_artifacts.security.model import SecurityAssessment
from agent_artifacts.sources.model import source_snapshot_digest
from agent_artifacts.sources.subtree import TakenSubtree
from agent_artifacts.store.model import ObjectCandidate, make_object_candidate

VENDOR_IMPORTER_ID = "registry-vendor-v1"
# A namespaced extension rather than a new provenance field: the release adds no schema revision,
# and every AART from `2.0.0` already preserves unknown namespaced keys unchanged.  `origin` could
# not hold it — that object rejects unknown fields, and widening it would be the format revision
# this design promised not to make.
VENDOR_RECORD_KEY = "aart.vendor"
_PAYLOAD_ROOT = "payload"
# The one document each kind's payload cannot load without.  A vendored subtree rarely contains it,
# because the upstream repository was never shaped for AART — supplying it is the maintainer's
# wrapper, and it is authored, reviewed, and assessed like any other file they add.
_REQUIRED_PAYLOAD_DOCUMENT = {
    "skill": "payload/SKILL.md",
    "mcp": "payload/mcp.json",
    "hook": "payload/hook.json",
}
_ALLOWED_AUTHORED_ROOTS = frozenset({"README.md", "SETUP.md", "payload", "setup"})
# File names that carry a licence grant rather than mention one.  `NOTICE` and `COPYRIGHT` are
# deliberately absent: they accompany a licence, and treating them as one would report a finding
# where there is no grant to record.
_LICENSE_NAMES = frozenset(
    {"license", "licence", "copying", "license-mit", "license-apache", "unlicense"}
)
_LICENSE_SUFFIXES = ("", ".md", ".txt", ".rst")
# SPDX identifiers a licence file determines by itself.  Ordered, first match wins, because the
# markers are not disjoint: every BSD-3-Clause text contains the whole BSD-2-Clause text.
_LICENSE_TEXTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Apache-2.0", ("apache license", "version 2.0")),
    ("MPL-2.0", ("mozilla public license", "version 2.0")),
    ("ISC", ("permission to use, copy, modify, and/or distribute this software",)),
    ("MIT", ("permission is hereby granted, free of charge",)),
    (
        "BSD-3-Clause",
        ("redistribution and use in source and binary forms", "endorse or promote products"),
    ),
    ("BSD-2-Clause", ("redistribution and use in source and binary forms",)),
    ("Unlicense", ("this is free and unencumbered software released into the public domain",)),
)
# The GPL family names its version in the text but not its grant: `-only` and `-or-later` are chosen
# by the work that applies the licence, not by the licence document.  Recognising the family and
# refusing to complete the identifier is the honest answer; the maintainer states the rest.
_LICENSE_FAMILIES: tuple[tuple[str, str], ...] = (
    ("gnu affero general public license", "GNU Affero General Public License"),
    ("gnu lesser general public license", "GNU Lesser General Public License"),
    ("gnu general public license", "GNU General Public License"),
)
_LICENSE_PREFIX_BYTES = 4096
# Canonical package content the projection writes itself.  Refusing these by name rather than as
# "not canonical content" matters: they are canonical, and the maintainer who passes one is trying
# to override the two documents whose whole purpose is to be derived from the vendoring inputs.
_PROJECTED_ROOTS = frozenset({"artifact.json", "provenance.json"})


def _error(message: str, path: str | None = None) -> Err:
    return Err((Diagnostic(ARTIFACT_INVALID, Severity.ERROR, message, SourceLocation(path=path)),))


@dataclass(frozen=True, slots=True)
class VendorOrigin:
    """Where the bytes came from, exactly as the acquisition resolved it."""

    url: str
    ref: str
    resolved_commit: str


@dataclass(frozen=True, slots=True)
class VendorOptions:
    """What the maintainer authors, because the upstream repository declares none of it."""

    identity: ArtifactIdentity
    version: SemVer
    summary: str
    profiles: tuple[str, ...]
    platforms: tuple[str, ...]
    scopes: tuple[str, ...]
    modes: tuple[str, ...]
    setup_recipe: SafeRelativePath | None = None
    setup_platforms: tuple[str, ...] = ()
    authored: tuple[tuple[str, bytes, bool], ...] = ()
    warnings: tuple[str, ...] = field(default=())
    # What the maintainer states, which always wins: a licence read out of a file is a reading of
    # somebody else's document, and the registry publishes what it is prepared to stand behind.
    license: str | None = None


@dataclass(frozen=True, slots=True)
class LicenseFinding:
    """What the taken subtree says about its own licence, and what it leaves unsettled.

    Vendoring redistributes somebody else's work, so the omission has to be visible (design §7).
    `identifier` is filled only where the licence file settles the SPDX identifier on its own;
    everything else is reported in `note` for a human to resolve, and refuses nothing.
    """

    paths: tuple[str, ...]
    identifier: str | None
    note: str


@dataclass(frozen=True, slots=True)
class VendoredPackage:
    """One owned package, ready to be written as ordinary registry content."""

    base: str
    files: tuple[tuple[str, bytes, bool], ...]
    manifest: ArtifactManifest
    provenance: Provenance
    license: LicenseFinding


def vendor_options_digest(url: str, ref: str, path: SafeRelativePath) -> ObjectDigest:
    """Digest every input that decides which bytes were taken.

    Two vendorings of one upstream state must be comparable, so this covers the origin URL, the
    requested ref, and the taken path. The ref is included even though it moves: a tag and a branch
    that happen to resolve to one commit are two different standing instructions, and `VN-5`'s drift
    check compares instructions, not only outcomes.
    """

    return json_digest(
        JsonObject(
            (
                ("path", str(path)),
                ("ref", ref),
                ("url", url),
            )
        )
    )


def acquisition_options_digest(origin: VendorOrigin, subtree: TakenSubtree) -> ObjectDigest:
    return vendor_options_digest(origin.url, origin.ref, subtree.path)


@dataclass(frozen=True, slots=True)
class VendorRecord:
    """How this copy was made: the standing instruction, and which files are not upstream's.

    `provenance.json` records the resolved commit, which cannot move, but re-vendoring needs the
    instruction that produced it — a branch and a tag resolving to one commit ask for different
    things next time. It also needs to know which files the maintainer wrote, because a file in the
    package that upstream no longer has is either their wrapper or an upstream deletion, and nothing
    else in the package distinguishes the two.
    """

    ref: str
    authored: tuple[str, ...]


def _record_json(record: VendorRecord) -> JsonObject:
    return JsonObject(
        (
            ("authored", JsonArray(record.authored)),
            ("ref", record.ref),
        )
    )


def read_vendor_record(provenance: Provenance) -> Result[VendorRecord]:
    """Recover the vendoring instruction, refusing a record its own digest does not confirm.

    The extension is ordinary JSON in a file a maintainer can edit, so a ref read back out of it is
    checked against `importer.options_digest` — the value written when the copy was made. A hand-
    edited ref would otherwise silently re-vendor from somewhere the recorded copy never came from.
    """

    if provenance.importer.id != VENDOR_IMPORTER_ID:
        return _error(
            f"this artifact was not produced by {VENDOR_IMPORTER_ID}; "
            "only a vendored artifact can be re-vendored"
        )
    raw = dict(provenance.extensions).get(VENDOR_RECORD_KEY)
    if not isinstance(raw, JsonObject):
        return _error(f"provenance does not record {VENDOR_RECORD_KEY}")
    ref = raw.get("ref")
    authored = raw.get("authored")
    if not isinstance(ref, str) or not ref or not isinstance(authored, JsonArray):
        return _error(f"{VENDOR_RECORD_KEY} must record a ref and the authored file list")
    if any(not isinstance(item, str) or not item for item in authored.items):
        return _error(f"{VENDOR_RECORD_KEY}.authored must be package-relative paths")
    paths = tuple(cast(tuple[str, ...], authored.items))
    if vendor_options_digest(provenance.origin.url, ref, provenance.origin.path) != (
        provenance.importer.options_digest
    ):
        return _error(
            "the recorded vendoring instruction does not match its options digest; "
            "provenance.json has been edited by hand"
        )
    return Ok(VendorRecord(ref, paths))


@dataclass(frozen=True, slots=True)
class CopyIntegrity:
    """What the copy's own record says, and what the copy says (VI-1).

    Both digests are carried rather than a boolean, because every caller renders them: a maintainer
    told only that something mismatched has no way to record which copy of which package it was.
    """

    recorded: ObjectDigest
    recomputed: ObjectDigest
    files: int

    @property
    def matches(self) -> bool:
        return self.recorded == self.recomputed


def verify_vendored_copy(
    files: Mapping[str, SnapshotEntry],
    base: str,
    payload_root: SafeRelativePath,
    authored: tuple[str, ...],
    recorded: ObjectDigest,
) -> Result[CopyIntegrity]:
    """Recompute `origin.input_digest` from the package on disk (design §3).

    The taken subtree is recoverable from the copy, so the claim vendoring makes has a gate that
    needs no network and no new field. Two properties make the inverse of `project_vendored_package`
    exact: `_authored_files` refuses an authored path that collides with a taken one, so subtracting
    the recorded list leaves precisely the taken files; and `take_subtree` carries only files and
    directories out of a Git tree, which holds no empty directory, so the taken directories are
    exactly the ancestors of the taken files.

    A package that cannot be reconstructed at all is refused rather than reported as a mismatch. A
    payload with nothing in it but the maintainer's own wrapper is a malformed package, and calling
    that drift would name the wrong defect.
    """

    prefix = f"{base}/{payload_root}/"
    excluded = {f"{base}/{relative}" for relative in authored}
    entries: list[SnapshotEntry] = []
    directories: set[str] = set()
    for raw in sorted(files):
        entry = files[raw]
        if (
            not raw.startswith(prefix)
            or raw in excluded
            or entry.kind is not SnapshotEntryKind.FILE
        ):
            continue
        parsed = parse_relative_path(raw.removeprefix(prefix))
        if isinstance(parsed, Err):
            return _error(f"the vendored payload holds an unsafe path: {raw}", path=raw)
        parts = parsed.value.parts
        directories.update("/".join(parts[:index]) for index in range(1, len(parts)))
        entries.append(
            SnapshotEntry(parsed.value, SnapshotEntryKind.FILE, entry.content, entry.executable)
        )
    if not entries:
        return _error(
            f"the vendored package holds no copied payload file under {prefix}; "
            "it cannot be checked against the origin it records",
            path=base,
        )
    taken = len(entries)
    entries.extend(
        SnapshotEntry(_path(relative), SnapshotEntryKind.DIRECTORY) for relative in directories
    )
    entries.sort(key=lambda item: str(item.path))
    digest = source_snapshot_digest(SourceSnapshot(SnapshotOrigin.IMMUTABLE_GIT, tuple(entries)))
    if isinstance(digest, Err):
        return digest
    return Ok(CopyIntegrity(recorded, digest.value, taken))


@dataclass(frozen=True, slots=True)
class DeliveryFinding:
    """What installing this artifact actually delivers, for a type where that is not all of it.

    Vendoring copies a subtree into the registry; installing applies the effects the type declares.
    For `mcp` those effects touch one file of the payload, so the copied bytes and the delivered
    bytes are different sets — and a descriptor naming a file inside the payload names one that will
    not be on the consumer's machine (`LAF-46`, design §7).
    """

    withheld: int
    referenced: tuple[str, ...]
    note: str
    # True when the descriptor declares no `server` object at all: the merge still runs and writes
    # an empty entry, so the artifact installs successfully and starts nothing.
    starts_nothing: bool = False


def _names_payload_file(raw: str, payload: Mapping[str, bytes]) -> bool:
    """Does this descriptor string name a file inside the copied payload?

    Deliberately narrow: only a string that resolves to a file actually present under `payload/`
    counts. Refusing anything that merely looks like a path would be refusing for a guess, and an
    MCP server legitimately launched from an absolute path outside the package is none of AART's
    business.
    """

    candidate = raw.removeprefix("./")
    return candidate in payload or f"{_PAYLOAD_ROOT}/{candidate}" in payload


def describe_delivery(kind: str, payload: Mapping[str, bytes]) -> DeliveryFinding | None:
    """What a consumer receives from this payload, or `None` where they receive all of it.

    `skill` and `hook` copy the payload tree; `guideline` and `memory` write the one document that
    is the whole payload. `mcp` merges the `server` object out of `payload/mcp.json` and copies
    nothing, which is the case worth reporting.
    """

    if kind != "mcp":
        return None
    document = payload.get(f"{_PAYLOAD_ROOT}/mcp.json")
    withheld = sum(1 for path in payload if path != f"{_PAYLOAD_ROOT}/mcp.json")
    note = (
        "installing this artifact merges the server entry from payload/mcp.json into the "
        f"profile's MCP file and copies nothing; {withheld} copied payload "
        f"{'file is' if withheld == 1 else 'files are'} not delivered to consumers"
    )
    if document is None:
        return DeliveryFinding(withheld, (), note)
    parsed = parse_json(document)
    if isinstance(parsed, Err) or not isinstance(parsed.value, JsonObject):
        # An unparsable descriptor is refused by the loader that reads it; saying so twice, in
        # different words, would send the maintainer looking for two faults.
        return DeliveryFinding(withheld, (), note)
    server = parsed.value.get("server")
    values: list[str] = []
    if isinstance(server, JsonObject):
        command = server.get("command")
        if isinstance(command, str):
            values.append(command)
        arguments = server.get("args")
        if isinstance(arguments, JsonArray):
            values.extend(item for item in arguments.items if isinstance(item, str))
    return DeliveryFinding(
        withheld,
        tuple(sorted({item for item in values if _names_payload_file(item, payload)})),
        note,
        # An `aart-mcp-v1` descriptor is `{"name": …, "server": {…}}`.  A document shaped like the
        # harness file it ends up in — `{"mcpServers": {…}}` — parses, loads, installs, and merges
        # an empty object: the artifact is delivered and starts nothing (VI-5).
        starts_nothing=not isinstance(server, JsonObject) or not server.entries,
    )


def mcp_descriptor_message(identity: ArtifactIdentity) -> str:
    """The one sentence for a descriptor that installs successfully and starts nothing."""

    return (
        f"vendored mcp descriptor declares no server, so installing it writes an empty entry: "
        f'{identity} needs payload/mcp.json shaped {{"name": …, "server": {{"command": …}}}}; '
        "a document shaped like the harness file it merges into installs and starts nothing"
    )


def delivery_reference_message(identity: ArtifactIdentity, finding: DeliveryFinding) -> str:
    """The one sentence for a configuration that cannot work on any consumer machine."""

    named = ", ".join(finding.referenced)
    return (
        f"vendored mcp descriptor names a copied payload file consumers never receive: "
        f"{identity} launches {named}, and installing this artifact writes only the server entry "
        "from payload/mcp.json. State a command the consumer's machine already resolves"
    )


def copy_integrity_message(identity: ArtifactIdentity, integrity: CopyIntegrity) -> str:
    """One sentence, said the same way by validate, audit, and re-vendor.

    It states what is wrong and stops: the copy is not the copy its provenance describes. Who changed
    it is not knowable from here — a local patch, a checkout that translated line endings, and a
    substitution are indistinguishable in the bytes — so the message names all three and the one
    route AART supports, rather than diagnosing.
    """

    return (
        f"vendored artifact no longer matches the origin it records: {identity} "
        f"({integrity.files} copied payload files digest to {integrity.recomputed}, "
        f"provenance records {integrity.recorded}). The copy was edited after vendoring, "
        "translated on checkout, or replaced; AART has no patched-copy record, so a copy that "
        "must differ from upstream is vendored from a fork that contains the difference"
    )


def _is_license_name(relative: str) -> bool:
    name = relative.rsplit("/", 1)[-1].lower()
    return any(
        name.endswith(suffix) and name.removesuffix(suffix) in _LICENSE_NAMES
        for suffix in _LICENSE_SUFFIXES
    )


def _identify(content: bytes) -> tuple[str | None, str | None]:
    """Read one licence file as (SPDX identifier, recognised family); either may be absent.

    Only the opening of the file is read, and only for phrases that appear in the licence's own
    preamble. This identifies a text; it does not adjudicate a grant, and an unrecognised file is
    reported as unrecognised rather than guessed at.
    """

    text = " ".join(content[:_LICENSE_PREFIX_BYTES].decode("utf-8", "replace").lower().split())
    for marker, family in _LICENSE_FAMILIES:
        if marker in text:
            return None, family
    for identifier, markers in _LICENSE_TEXTS:
        if all(marker in text for marker in markers):
            return identifier, None
    return None, None


def discover_license(subtree: TakenSubtree) -> LicenseFinding:
    """Look for the licence covering the taken work, and say what was and was not settled.

    Only a file at the subtree root can be pre-filled from. A `LICENSE` further down covers whatever
    sits beside it — a bundled dependency, a sample — and adopting it as the artifact's licence would
    record a claim nobody made. Those are reported, never used.
    """

    files = {
        str(entry.path): entry
        for entry in subtree.snapshot.entries
        if entry.kind is SnapshotEntryKind.FILE
    }
    found = tuple(sorted(path for path in files if _is_license_name(path)))
    root = tuple(path for path in found if "/" not in path)
    if not found:
        return LicenseFinding((), None, "no license file in the taken subtree")
    listed = ", ".join(found)
    if not root:
        return LicenseFinding(
            found,
            None,
            "license files were found only below the subtree root, where they cover what sits "
            f"beside them rather than the taken work: {listed}",
        )
    if len(root) > 1:
        return LicenseFinding(
            found,
            None,
            f"several license files at the subtree root, so none was adopted: {listed}",
        )
    identifier, family = _identify(files[root[0]].content)
    if identifier is not None:
        return LicenseFinding(found, identifier, f"{root[0]}: {identifier}")
    if family is not None:
        return LicenseFinding(
            found,
            None,
            f"{root[0]}: {family}, whose text does not say whether the grant is -only or "
            "-or-later; state the identifier with --license",
        )
    return LicenseFinding(
        found, None, f"{root[0]}: text not recognised; state the identifier with --license"
    )


def _authored_files(
    options: VendorOptions, taken: frozenset[str]
) -> Result[tuple[tuple[str, bytes, bool], ...]]:
    files: list[tuple[str, bytes, bool]] = []
    seen: set[str] = set()
    for raw, content, executable in options.authored:
        parsed = parse_relative_path(raw)
        if isinstance(parsed, Err):
            return _error(f"authored package path is unsafe: {raw!r}")
        relative = str(parsed.value)
        root = relative.split("/", 1)[0]
        if root in _PROJECTED_ROOTS:
            return _error(f"the vendoring writes {root}; it is not authored alongside the payload")
        if root not in _ALLOWED_AUTHORED_ROOTS:
            return _error(f"authored file is not canonical package content: {relative}")
        if relative in seen:
            return _error(f"authored file is given twice: {relative}")
        # Never silently over-write a taken byte: the maintainer would be reviewing upstream content
        # that is not the content their registry ships.
        if relative in taken:
            return _error(f"authored file collides with the taken subtree: {relative}")
        seen.add(relative)
        files.append((relative, content, executable))
    return Ok(tuple(files))


def project_vendored_package(
    subtree: TakenSubtree,
    origin: VendorOrigin,
    options: VendorOptions,
    *,
    artifact_root: SafeRelativePath,
    importer_version: SemVer,
) -> Result[VendoredPackage]:
    """Build the package a `registry vendor` would write, without writing anything.

    `importer_version` is the AART that did the vendoring: the importer is this executable, so the
    provenance records which one produced the copy. It is passed rather than read, so the projection
    stays a pure function of its inputs.
    """

    kind = options.identity.kind
    if kind not in PAYLOAD_FORMAT_BY_TYPE:
        return _error(f"unsupported artifact type for vendoring: {kind}")
    taken_files = {
        f"{_PAYLOAD_ROOT}/{entry.path}": entry
        for entry in subtree.snapshot.entries
        if entry.kind is SnapshotEntryKind.FILE
    }
    authored = _authored_files(options, frozenset(taken_files))
    if isinstance(authored, Err):
        return authored
    payload_paths = set(taken_files) | {
        path for path, _content, _executable in authored.value if path.startswith("payload/")
    }
    required = _REQUIRED_PAYLOAD_DOCUMENT.get(kind)
    if required is not None and required not in payload_paths:
        return _error(
            f"a vendored {kind} needs {required}; the taken subtree does not contain it, "
            "so the maintainer supplies it"
        )
    if kind in {"guideline", "memory"} and (
        len(payload_paths) != 1 or not next(iter(payload_paths)).endswith(".md")
    ):
        return _error(
            f"a vendored {kind} carries exactly one Markdown document; "
            f"the taken subtree contributes {len(payload_paths)} payload files"
        )
    canonical_kind = cast(CanonicalArtifactType, kind)
    license_finding = discover_license(subtree)
    setup = None
    if options.setup_recipe is not None:
        setup = SetupReference(options.setup_recipe, options.setup_platforms or options.platforms)
    manifest = ArtifactManifest(
        1,
        options.identity,
        options.version,
        options.summary,
        PayloadSpec(_path(_PAYLOAD_ROOT), PAYLOAD_FORMAT_BY_TYPE[canonical_kind]),
        CompatibilitySpec(options.profiles, options.platforms),
        InstallSpec(
            cast(tuple[InstallScope, ...], options.scopes),
            cast(tuple[InstallMode, ...], options.modes),
            tuple(sorted(INSTALL_EFFECTS_BY_TYPE[canonical_kind])),
        ),
        setup,
        (),
        # Stated wins over discovered; discovered fills the silence rather than leaving a copy of
        # somebody else's work in this registry with no licence recorded at all.
        options.license or license_finding.identifier,
    )
    provenance = Provenance(
        1,
        OriginProvenance(
            "git",
            origin.url,
            origin.resolved_commit,
            subtree.path,
            subtree.input_digest,
        ),
        ImporterProvenance(
            VENDOR_IMPORTER_ID,
            importer_version,
            acquisition_options_digest(origin, subtree),
        ),
        # Acquisition warnings travel with the artifact rather than with the run that produced it:
        # the baseline surfaces them as `importer-warning`, so a second reviewer sees what the first
        # was told.
        tuple(sorted(set(options.warnings))),
        (
            (
                VENDOR_RECORD_KEY,
                _record_json(
                    VendorRecord(
                        origin.ref,
                        tuple(sorted(relative for relative, _c, _e in authored.value)),
                    )
                ),
            ),
        ),
    )
    base = f"{artifact_root}/{kind}/{options.identity.name}"
    files: list[tuple[str, bytes, bool]] = [
        (f"{base}/artifact.json", canonical_json_bytes(artifact_manifest_to_json(manifest)), False),
        (f"{base}/provenance.json", canonical_json_bytes(provenance_to_json(provenance)), False),
    ]
    files.extend(
        (f"{base}/{relative}", entry.content, entry.executable)
        for relative, entry in taken_files.items()
    )
    files.extend(
        (f"{base}/{relative}", content, executable)
        for relative, content, executable in authored.value
    )
    return Ok(VendoredPackage(base, tuple(sorted(files)), manifest, provenance, license_finding))


@dataclass(frozen=True, slots=True)
class VendorAssessment:
    """What the baseline found in the exact bytes this vendoring would write."""

    candidate: ObjectCandidate
    assessment: SecurityAssessment
    attestation: SecurityAttestation
    document_path: str
    document: bytes


def _package_entries(package: VendoredPackage) -> tuple[SnapshotEntry, ...]:
    prefix = f"{package.base}/"
    return tuple(
        SnapshotEntry(
            _path(relative.removeprefix(prefix)), SnapshotEntryKind.FILE, content, executable
        )
        for relative, content, executable in package.files
    )


def assess_vendored_package(
    package: VendoredPackage,
    *,
    source_id: SourceId,
) -> Result[VendorAssessment]:
    """Assess the projected package before a byte of it is written.

    The object assessed is the whole package, so the maintainer's own wrapper — the `mcp.json` they
    authored, the `install.sh` they added — is scanned with the copied payload rather than exempted
    from it (design §3). The result is canonical local attestation evidence: it names the exact
    object digest it describes, so a reader can tell whether it still applies.
    """

    entries = _package_entries(package)
    candidate = make_object_candidate(entries)
    if isinstance(candidate, Err):
        return candidate
    compiled = compile_native_package(entries, expected_identity=package.manifest.identity)
    if isinstance(compiled, Err):
        return compiled
    indexed = index_artifact_from_package(
        compiled.value,
        source_id=source_id,
        object_digest=candidate.value.digest,
    )
    assessment = assess_installation_risk(BaselineScanRequest(candidate.value, indexed))
    try:
        attestation = SecurityAttestation(
            1,
            AssessmentCacheKey(
                1,
                candidate.value.digest,
                BASELINE_PROVIDER_ID,
                BASELINE_PROVIDER_VERSION,
                BASELINE_RULES_DIGEST,
                EMPTY_CACHE_INPUT_DIGEST,
                EMPTY_CACHE_INPUT_DIGEST,
            ),
            # Local, not `registry-ci`: this ran on the maintainer's machine, and a registry-CI
            # origin would have to name a resolved registry revision that does not exist until the
            # vendoring is committed.
            AttestationOrigin(AttestationOriginKind.LOCAL),
            assessment,
        )
    except ValueError as error:
        return _error(str(error))
    digest = attestation_digest(attestation)
    return Ok(
        VendorAssessment(
            candidate.value,
            assessment,
            attestation,
            f"security/attestations/{digest.value}.json",
            attestation_bytes(attestation),
        )
    )


def _path(raw: str) -> SafeRelativePath:
    parsed = parse_relative_path(raw)
    assert isinstance(parsed, Ok), raw
    return parsed.value
