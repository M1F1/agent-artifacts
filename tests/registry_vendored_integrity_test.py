"""VI-1: a vendored copy is checked against the origin it records, or the check refuses.

`LAF-41` is that `origin.input_digest` was written once and read by nothing: the lock and the index
are derived from whatever bytes are present, so they agree with a substitution by construction, and
the one document saying what the bytes were supposed to be was never consulted.

Design §3 is the claim these tests hold: the taken subtree is recoverable from the package on disk,
so the digest is recomputable with no new field, no migration, and no network. The recomputation is
exact only because two rules elsewhere hold — an authored file never collides with a taken one, and
a Git tree holds no empty directory — so both are exercised here rather than assumed.
"""

from __future__ import annotations

import json
import unittest

from agent_artifacts.domain.identifiers import ArtifactIdentity
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.protocol.native_tree import (
    SnapshotEntry,
    SnapshotEntryKind,
    SnapshotOrigin,
    SourceSnapshot,
)
from agent_artifacts.protocol.paths import parse_relative_path
from agent_artifacts.protocol.semver import SemVer
from agent_artifacts.registry_maintenance.vendoring import (
    VendoredPackage,
    VendorOptions,
    VendorOrigin,
    copy_integrity_message,
    project_vendored_package,
    read_vendor_record,
    verify_vendored_copy,
)
from agent_artifacts.sources.subtree import take_subtree

_COMMIT = "f" * 40
_URL = "https://github.com/example/atlassian-mcp.git"
_MCP_JSON = (
    json.dumps({"name": "atlassian", "server": {"command": "npx", "args": ["-y", "srv"]}}).encode()
    + b"\n"
)
_IDENTITY = ArtifactIdentity("mcp", "atlassian")


def _path(raw: str):
    parsed = parse_relative_path(raw)
    assert isinstance(parsed, Ok), parsed
    return parsed.value


def _file(raw: str, content: bytes = b"x", *, executable: bool = False) -> SnapshotEntry:
    return SnapshotEntry(_path(raw), SnapshotEntryKind.FILE, content, executable)


def _directory(raw: str) -> SnapshotEntry:
    return SnapshotEntry(_path(raw), SnapshotEntryKind.DIRECTORY)


def _foreign_repository(*extra: SnapshotEntry) -> SourceSnapshot:
    """An upstream MCP server nested inside a monorepo that has never heard of AART."""

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
            _directory("servers/atlassian/lib/inner"),
            _file("servers/atlassian/lib/inner/deep.js", b"export const deep = 2;\n"),
            *extra,
        ),
    )


def _subtree(snapshot: SourceSnapshot | None = None, raw: str = "servers/atlassian"):
    taken = take_subtree(snapshot or _foreign_repository(), _path(raw))
    assert isinstance(taken, Ok), taken
    return taken.value


def _package(subtree=None, **overrides) -> VendoredPackage:
    fields = {
        "identity": _IDENTITY,
        "version": SemVer(1, 0, 0),
        "summary": "Atlassian MCP server, vendored from upstream.",
        "profiles": ("claude",),
        "platforms": ("darwin",),
        "scopes": ("project",),
        "modes": ("copy",),
        "authored": (("payload/mcp.json", _MCP_JSON, False),),
    }
    fields.update(overrides)
    projected = project_vendored_package(
        subtree or _subtree(),
        VendorOrigin(_URL, "v1.4.0", _COMMIT),
        VendorOptions(**fields),
        artifact_root=_path("artifacts"),
        importer_version=SemVer(2, 4, 0),
    )
    assert isinstance(projected, Ok), projected
    return projected.value


def _committed(package: VendoredPackage) -> dict[str, SnapshotEntry]:
    """The package as `registry validate` finds it: files on disk, no directory entries."""

    return {
        relative: _file(relative, content, executable=executable)
        for relative, content, executable in package.files
    }


def _authored(package: VendoredPackage) -> tuple[str, ...]:
    """Read the authored list back out of the package, as every real caller does."""

    record = read_vendor_record(package.provenance)
    assert isinstance(record, Ok), record
    return record.value.authored


def _verify(package: VendoredPackage, files: dict[str, SnapshotEntry] | None = None):
    return verify_vendored_copy(
        files if files is not None else _committed(package),
        package.base,
        package.manifest.payload.root,
        _authored(package),
        package.provenance.origin.input_digest,
    )


def _integrity(package: VendoredPackage, files: dict[str, SnapshotEntry] | None = None):
    result = _verify(package, files)
    assert isinstance(result, Ok), result
    return result.value


class VendoredCopyIntegrityTest(unittest.TestCase):
    def test_projected_package_verifies_against_its_own_record(self) -> None:
        """The digest written at vendoring time is recomputable from the bytes it describes."""

        integrity = _integrity(_package())
        self.assertTrue(integrity.matches, integrity)
        self.assertEqual(integrity.recorded, integrity.recomputed)
        # Four copied files; the maintainer's `payload/mcp.json` is theirs, not upstream's.
        self.assertEqual(integrity.files, 4)

    def test_nested_payload_reproduces_the_taken_subtree_digest(self) -> None:
        """The directories are derived, not stored, so a nested payload is the case that proves it.

        A Git tree holds no empty directory and `take_subtree` carries nothing but files and
        directories, so every directory of the taken snapshot is an ancestor of a taken file. The
        fixture is two levels deep for exactly this reason.
        """

        subtree = _subtree()
        package = _package(subtree)
        self.assertEqual(_integrity(package).recomputed, subtree.input_digest)

    def test_executable_bit_is_part_of_the_copy(self) -> None:
        files = _committed(package := _package())
        target = f"{package.base}/payload/install.sh"
        files[target] = _file(target, files[target].content, executable=False)
        self.assertFalse(_integrity(package, files).matches)

    def test_one_changed_byte_is_a_mismatch(self) -> None:
        """The `LAF-41` reproduction, at the smallest scale that produces it."""

        files = _committed(package := _package())
        target = f"{package.base}/payload/index.js"
        files[target] = _file(target, b"console.log('serve!');\n")
        integrity = _integrity(package, files)
        self.assertFalse(integrity.matches)
        self.assertNotEqual(integrity.recorded, integrity.recomputed)

    def test_added_and_removed_payload_files_are_mismatches(self) -> None:
        files = _committed(package := _package())
        added = dict(files)
        added[f"{package.base}/payload/extra.js"] = _file(f"{package.base}/payload/extra.js")
        self.assertFalse(_integrity(package, added).matches)
        removed = dict(files)
        del removed[f"{package.base}/payload/lib/client.js"]
        self.assertFalse(_integrity(package, removed).matches)

    def test_authored_payload_file_is_excluded_from_the_copy(self) -> None:
        """The maintainer's wrapper is not upstream's, and upstream's digest does not cover it."""

        package = _package()
        files = _committed(package)
        self.assertIn(f"{package.base}/payload/mcp.json", files)
        target = f"{package.base}/payload/mcp.json"
        files[target] = _file(target, b'{"name": "atlassian", "server": {"command": "uvx"}}\n')
        self.assertTrue(_integrity(package, files).matches)

    def test_declaring_a_copied_file_authored_does_not_hide_it(self) -> None:
        """Editing `aart.vendor.authored` to cover a tampered file removes it from the digest.

        The record is not covered by `options_digest` — that digest covers URL, ref, and path — so
        the evasion is worth stating: excluding a file upstream supplied changes the recomputation,
        which is a mismatch, not a match.
        """

        package = _package()
        result = verify_vendored_copy(
            _committed(package),
            package.base,
            package.manifest.payload.root,
            ("payload/mcp.json", "payload/index.js"),
            package.provenance.origin.input_digest,
        )
        assert isinstance(result, Ok), result
        self.assertFalse(result.value.matches)

    def test_a_payload_of_nothing_but_the_wrapper_refuses(self) -> None:
        """A package with no copied file is malformed; calling that drift names the wrong defect."""

        package = _package()
        files = {
            relative: entry
            for relative, entry in _committed(package).items()
            if not relative.startswith(f"{package.base}/payload/") or relative.endswith("/mcp.json")
        }
        result = _verify(package, files)
        assert isinstance(result, Err), result
        self.assertIn("no copied payload file", result.diagnostics[0].message)

    def test_the_message_names_the_package_both_digests_and_the_route_back(self) -> None:
        files = _committed(package := _package())
        target = f"{package.base}/payload/index.js"
        files[target] = _file(target, b"tampered\n")
        message = copy_integrity_message(_IDENTITY, _integrity(package, files))
        self.assertIn("mcp/atlassian", message)
        self.assertIn(str(package.provenance.origin.input_digest), message)
        self.assertIn("fork", message)


if __name__ == "__main__":
    unittest.main()
