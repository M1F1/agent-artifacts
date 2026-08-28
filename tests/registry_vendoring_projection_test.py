"""VN-2: foreign bytes become an ordinary owned package, or the projection refuses.

Design §2 is the point of this package: a vendored artifact is not a new kind of thing. It is an
owned package that happens to carry `provenance.json`, so every rule that already applies to owned
content — the loader, the index projection, the security baseline's cross-check, `validate --strict
--frozen` — applies to it without being taught anything. These tests hold that claim, because the
cheap way to ship vendoring would have been a parallel path that none of those gates look at.

The other half is what the projection refuses. A projection that emits a package the loader will
reject has only moved the failure later, to a manifest the maintainer never wrote by hand and cannot
usefully debug.
"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from agent_artifacts import cli
from agent_artifacts.domain.identifiers import ArtifactIdentity, SourceId
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.protocol.native_tree import (
    SnapshotEntry,
    SnapshotEntryKind,
    SnapshotOrigin,
    SourceSnapshot,
    load_native_source,
)
from agent_artifacts.protocol.paths import parse_relative_path
from agent_artifacts.protocol.registry_index import index_artifact_from_package
from agent_artifacts.protocol.semver import SemVer
from agent_artifacts.registry_maintenance.vendoring import (
    VENDOR_IMPORTER_ID,
    VendoredPackage,
    VendorOptions,
    VendorOrigin,
    acquisition_options_digest,
    project_vendored_package,
)
from agent_artifacts.runtime_contract import EXECUTABLE_CAPABILITIES, EXECUTABLE_VERSION
from agent_artifacts.security.baseline import BaselineScanRequest, assess_installation_risk
from agent_artifacts.sources.subtree import take_subtree
from agent_artifacts.store.model import make_object_candidate

_CAPABILITIES = EXECUTABLE_CAPABILITIES
_COMMIT = "f" * 40
_URL = "https://github.com/example/atlassian-mcp.git"
# An `aart-mcp-v1` descriptor: `name` and a `server` object.  It was written here as
# `{"mcpServers": …}` — the shape of the harness file the entry is merged *into* — which parses,
# loads, installs, and starts nothing, because `server` is absent and the merge writes `{}` (VI-5).
_MCP_JSON = (
    json.dumps(
        {"name": "atlassian", "server": {"command": "npx", "args": ["-y", "@example/atlassian"]}}
    ).encode()
    + b"\n"
)


def _path(raw: str):
    parsed = parse_relative_path(raw)
    assert isinstance(parsed, Ok), parsed
    return parsed.value


def _file(raw: str, content: bytes = b"x", *, executable: bool = False) -> SnapshotEntry:
    return SnapshotEntry(_path(raw), SnapshotEntryKind.FILE, content, executable)


def _directory(raw: str) -> SnapshotEntry:
    return SnapshotEntry(_path(raw), SnapshotEntryKind.DIRECTORY)


def _foreign_repository(*extra: SnapshotEntry) -> SourceSnapshot:
    """An upstream MCP server in a monorepo that has never heard of AART."""

    return SourceSnapshot(
        SnapshotOrigin.IMMUTABLE_GIT,
        (
            _file("README.md", b"# upstream\n"),
            _directory("servers"),
            _directory("servers/atlassian"),
            _file("servers/atlassian/index.js", b"console.log('serve');\n"),
            _file("servers/atlassian/install.sh", b"#!/bin/sh\nexit 0\n", executable=True),
            _directory("servers/atlassian/lib"),
            _file("servers/atlassian/lib/client.js", b"export const client = 1;\n"),
            *extra,
        ),
    )


def _subtree(snapshot: SourceSnapshot | None = None, raw: str = "servers/atlassian"):
    taken = take_subtree(snapshot or _foreign_repository(), _path(raw))
    assert isinstance(taken, Ok), taken
    return taken.value


def _origin(ref: str = "v1.4.0") -> VendorOrigin:
    return VendorOrigin(_URL, ref, _COMMIT)


def _options(**overrides) -> VendorOptions:
    """What the maintainer authors: the upstream repository declares none of it."""

    fields = {
        "identity": ArtifactIdentity("mcp", "atlassian"),
        "version": SemVer(1, 0, 0),
        "summary": "Atlassian MCP server, vendored from upstream.",
        "profiles": ("claude",),
        "platforms": ("darwin", "linux"),
        "scopes": ("project",),
        "modes": ("copy",),
        "authored": (("payload/mcp.json", _MCP_JSON, False),),
    }
    fields.update(overrides)
    return VendorOptions(**fields)


def _projected(subtree=None, origin: VendorOrigin | None = None, **overrides):
    return project_vendored_package(
        subtree or _subtree(),
        origin or _origin(),
        _options(**overrides),
        artifact_root=_path("artifacts"),
        importer_version=SemVer(2, 3, 0),
    )


def _package(**overrides) -> VendoredPackage:
    result = _projected(**overrides)
    assert isinstance(result, Ok), result
    return result.value


def _message(result) -> str:
    assert isinstance(result, Err), f"expected a refusal, got {result}"
    return "; ".join(diagnostic.message for diagnostic in result.diagnostics)


_REGISTRY_MARKER = {
    "schema_version": 1,
    "protocol_version": 1,
    "registry_id": "vendor-registry",
    "display_name": "Vendor Registry",
    "requires_aart": {"min_inclusive": "0.0.1", "max_exclusive": "3.0.0"},
    "required_capabilities": ["artifact-manifest-v1"],
    "default_channel": "main",
    "services": {},
}
_SOURCE_MARKER = {
    "schema_version": 1,
    "protocol_version": 1,
    "source_id": "vendor-registry",
    "display_name": "Vendor Registry",
    "requires_aart": {"min_inclusive": "0.0.1", "max_exclusive": "3.0.0"},
    "required_capabilities": ["artifact-manifest-v1"],
    "artifact_roots": ["artifacts"],
    "collection_roots": [],
}


def _registry_snapshot(package: VendoredPackage) -> SourceSnapshot:
    """The emitted package as ordinary registry content, with nothing else in the registry."""

    entries = [
        _file("aart-source.json", json.dumps(_SOURCE_MARKER).encode()),
        *(
            _file(relative, content, executable=executable)
            for relative, content, executable in package.files
        ),
    ]
    return SourceSnapshot(SnapshotOrigin.LOCAL, tuple(entries))


def _loaded(package: VendoredPackage):
    source = load_native_source(
        _registry_snapshot(package),
        executable_version=EXECUTABLE_VERSION,
        available_capabilities=_CAPABILITIES,
    )
    assert isinstance(source, Ok), source
    self_artifacts = source.value.artifacts
    assert len(self_artifacts) == 1, self_artifacts
    return self_artifacts[0]


def _package_relative(package: VendoredPackage) -> tuple[SnapshotEntry, ...]:
    return tuple(
        _file(relative.removeprefix(f"{package.base}/"), content, executable=executable)
        for relative, content, executable in package.files
    )


def _findings(package: VendoredPackage) -> frozenset[str]:
    """Run the consumer-side baseline over the emitted package, as an installer would."""

    candidate = make_object_candidate(_package_relative(package))
    assert isinstance(candidate, Ok), candidate
    indexed = index_artifact_from_package(
        _loaded(package),
        source_id=SourceId("vendor-registry"),
        object_digest=candidate.value.digest,
    )
    assessment = assess_installation_risk(BaselineScanRequest(candidate.value, indexed))
    return frozenset(finding.rule_id for finding in assessment.findings)


class VendoredPackageIsOwnedContentTest(unittest.TestCase):
    def test_the_projected_package_loads_through_the_ordinary_loader(self) -> None:
        """No vendoring-aware loader exists, and this is why none is needed."""

        loaded = _loaded(_package())

        self.assertEqual(str(loaded.manifest.identity), "mcp/atlassian")

    def test_the_loaded_manifest_and_provenance_are_the_projected_ones_unchanged(self) -> None:
        package = _package()

        loaded = _loaded(package)

        self.assertEqual(loaded.manifest, package.manifest)
        self.assertEqual(loaded.provenance, package.provenance)

    def test_the_payload_keeps_the_upstream_layout_and_its_executable_bits(self) -> None:
        """An install script arriving non-executable is debugged at the wrong layer."""

        package = _package()

        modes = {relative: executable for relative, _content, executable in package.files}
        base = package.base
        self.assertTrue(modes[f"{base}/payload/install.sh"])
        self.assertFalse(modes[f"{base}/payload/index.js"])
        self.assertIn(f"{base}/payload/lib/client.js", modes)

    def test_the_provenance_names_the_commit_the_path_and_this_importer(self) -> None:
        provenance = _package().provenance

        self.assertEqual(provenance.origin.kind, "git")
        self.assertEqual(provenance.origin.url, _URL)
        self.assertEqual(provenance.origin.resolved_commit, _COMMIT)
        self.assertEqual(str(provenance.origin.path), "servers/atlassian")
        self.assertEqual(provenance.origin.input_digest, _subtree().input_digest)
        self.assertEqual(provenance.importer.id, VENDOR_IMPORTER_ID)

    def test_the_index_record_carries_the_provenance_the_file_states(self) -> None:
        """The index is what a consumer reads; a divergence here is invisible upstream."""

        package = _package()

        indexed = index_artifact_from_package(
            _loaded(package),
            source_id=SourceId("vendor-registry"),
            object_digest=_subtree().input_digest,
        )

        assert indexed.provenance is not None
        self.assertEqual(indexed.provenance.origin_url, package.provenance.origin.url)
        self.assertEqual(
            indexed.provenance.resolved_commit, package.provenance.origin.resolved_commit
        )
        self.assertEqual(indexed.provenance.path, package.provenance.origin.path)

    def test_the_baseline_raises_no_provenance_mismatch_for_a_vendored_package(self) -> None:
        self.assertNotIn("provenance-index-mismatch", _findings(_package()))
        self.assertNotIn("provenance-missing", _findings(_package()))
        self.assertNotIn("provenance-unexpected", _findings(_package()))

    def test_an_acquisition_warning_reaches_the_second_reviewer(self) -> None:
        """Warnings travel with the artifact, not with the run that produced it."""

        warned = _package(warnings=("upstream declares no license",))

        self.assertEqual(warned.provenance.warnings, ("upstream declares no license",))
        self.assertIn("importer-warning", _findings(warned))
        self.assertNotIn("importer-warning", _findings(_package()))


class AcquisitionOptionsDigestTest(unittest.TestCase):
    def test_one_upstream_state_vendored_twice_digests_the_same_options(self) -> None:
        first = acquisition_options_digest(_origin(), _subtree())
        second = acquisition_options_digest(_origin(), _subtree())

        self.assertEqual(first, second)

    def test_two_refs_resolving_to_one_commit_are_two_standing_instructions(self) -> None:
        """`VN-5`'s drift check compares instructions, not only outcomes."""

        tagged = acquisition_options_digest(_origin("v1.4.0"), _subtree())
        tracking = acquisition_options_digest(_origin("main"), _subtree())

        self.assertNotEqual(tagged, tracking)

    def test_a_different_taken_path_digests_differently(self) -> None:
        other = _foreign_repository(
            _directory("servers/other"), _file("servers/other/index.js", b"other\n")
        )

        self.assertNotEqual(
            acquisition_options_digest(_origin(), _subtree()),
            acquisition_options_digest(_origin(), _subtree(other, "servers/other")),
        )


class VendorProjectionRefusesTest(unittest.TestCase):
    def test_a_payload_missing_its_kinds_document_names_the_document(self) -> None:
        """The upstream repository was never shaped for AART, so this is the common case.

        Supplying the missing document is the maintainer's wrapper. Refusing here names it; letting
        the package through would fail later against a manifest nobody wrote by hand.
        """

        refused = _projected(authored=())

        message = _message(refused)
        self.assertIn("payload/mcp.json", message)
        self.assertIn("artifacts/mcp/atlassian/payload/mcp.json", message)
        assert isinstance(refused, Err)
        self.assertIn(
            "author artifacts/mcp/atlassian/payload/mcp.json",
            refused.diagnostics[0].remediation[0],
        )

    def test_an_authored_file_may_not_overwrite_a_taken_byte(self) -> None:
        """Otherwise the maintainer reviews upstream content their registry does not ship."""

        refused = _projected(
            authored=(
                ("payload/mcp.json", _MCP_JSON, False),
                ("payload/index.js", b"console.log('mine');\n", False),
            )
        )

        self.assertIn("collides with the taken subtree", _message(refused))
        assert isinstance(refused, Err)
        self.assertIn("upstream already provides", refused.diagnostics[0].message)
        self.assertIn(
            "remove the authored copy at artifacts/mcp/atlassian/payload/index.js",
            refused.diagnostics[0].remediation[0],
        )

    def test_the_two_derived_documents_are_not_authored(self) -> None:
        for reserved in ("artifact.json", "provenance.json"):
            with self.subTest(reserved=reserved):
                refused = _projected(
                    authored=(("payload/mcp.json", _MCP_JSON, False), (reserved, b"{}\n", False))
                )

                self.assertIn(f"the vendoring writes {reserved}", _message(refused))

    def test_an_authored_file_outside_the_canonical_roots_is_refused(self) -> None:
        refused = _projected(
            authored=(("payload/mcp.json", _MCP_JSON, False), ("Makefile", b"all:\n", False))
        )

        self.assertIn("not canonical package content", _message(refused))

    def test_an_unsafe_authored_path_is_refused(self) -> None:
        refused = _projected(authored=(("../escape.json", b"{}\n", False),))

        self.assertIn("unsafe", _message(refused))

    def test_the_same_authored_path_given_twice_is_refused(self) -> None:
        refused = _projected(
            authored=(("payload/mcp.json", _MCP_JSON, False), ("payload/mcp.json", b"{}\n", False))
        )

        self.assertIn("given twice", _message(refused))

    def test_a_guideline_vendored_from_a_directory_of_files_is_refused(self) -> None:
        """A guideline is one Markdown document; a directory cannot become one silently."""

        refused = _projected(identity=ArtifactIdentity("guideline", "style"), authored=())

        self.assertIn("exactly one Markdown document", _message(refused))

    def test_a_guideline_vendored_from_one_markdown_file_is_projected(self) -> None:
        upstream = SourceSnapshot(
            SnapshotOrigin.IMMUTABLE_GIT,
            (_directory("docs"), _file("docs/style.md", b"# Style\n")),
        )

        projected = _projected(
            subtree=_subtree(upstream, "docs"),
            identity=ArtifactIdentity("guideline", "style"),
            authored=(),
        )

        self.assertIsInstance(projected, Ok)


def _run(*arguments: str) -> tuple[int, str]:
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = cli.main(list(arguments))
    return code, output.getvalue()


class VendoredRegistryPassesItsPublisherGatesTest(unittest.TestCase):
    """The emitted registry is validated by the commands a publisher already runs."""

    def test_a_registry_holding_a_vendored_artifact_locks_builds_and_validates_frozen(self) -> None:
        package = _package()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "registry"
            root.mkdir()
            subprocess.run(
                ("git", "-C", str(root), "init", "-q"),
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            (root / "aart-registry.json").write_text(json.dumps(_REGISTRY_MARKER), encoding="utf-8")
            (root / "aart-source.json").write_text(json.dumps(_SOURCE_MARKER), encoding="utf-8")
            for relative, content, executable in package.files:
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
                if executable:
                    target.chmod(0o755)

            # `format` first because the two markers are written as plain JSON here, exactly as a
            # maintainer's editor would leave them; nothing about the vendored package needs it.
            for arguments in (
                ("format", "--yes"),
                ("lock", "--yes"),
                ("build", "--yes"),
                ("validate", "--strict", "--frozen", "--json"),
                ("audit", "--json"),
            ):
                code, output = _run("registry", *arguments, "--source", str(root))
                self.assertEqual(code, 0, f"registry {arguments[0]}: {output}")

            index = json.loads((root / "aart.index.json").read_text(encoding="utf-8"))
            artifact = next(item for item in index["artifacts"] if item["name"] == "atlassian")
            self.assertEqual(artifact["provenance"]["resolved_commit"], _COMMIT)


if __name__ == "__main__":
    unittest.main()
