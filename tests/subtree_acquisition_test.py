"""VN-1: one subtree is taken from a repository that knows nothing about AART, or nothing is.

`promote-native` refuses any upstream that is not already a native source, which is most of them
(design §1). Vendoring's first step is therefore taking a *part* of a foreign repository — no
markers, no `artifact_roots`, no manifest — and every way that can go quietly wrong has to go loudly
wrong instead: a typo in `--path` must not produce a valid empty package, and a link out of the
taken subtree must be neither dropped nor followed (design §5).
"""

from __future__ import annotations

import unittest

from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.protocol.native_tree import (
    SnapshotEntry,
    SnapshotEntryKind,
    SnapshotOrigin,
    SourceSnapshot,
)
from agent_artifacts.protocol.paths import parse_relative_path
from agent_artifacts.sources.model import SnapshotLimits
from agent_artifacts.sources.subtree import take_subtree


def _path(raw: str):
    parsed = parse_relative_path(raw)
    assert isinstance(parsed, Ok), parsed
    return parsed.value


def _file(raw: str, content: bytes = b"x", *, executable: bool = False) -> SnapshotEntry:
    return SnapshotEntry(_path(raw), SnapshotEntryKind.FILE, content, executable)


def _directory(raw: str) -> SnapshotEntry:
    return SnapshotEntry(_path(raw), SnapshotEntryKind.DIRECTORY)


def _link(raw: str, target: str) -> SnapshotEntry:
    return SnapshotEntry(_path(raw), SnapshotEntryKind.SYMLINK, target.encode())


def _foreign_repository(*extra: SnapshotEntry) -> SourceSnapshot:
    """A monorepo with no AART markers anywhere — the case vendoring exists for."""

    return SourceSnapshot(
        SnapshotOrigin.IMMUTABLE_GIT,
        (
            _file("README.md", b"# a repository that never heard of AART\n"),
            _file("package.json", b"{}\n"),
            _directory("servers"),
            _directory("servers/atlassian"),
            _file("servers/atlassian/index.js", b"console.log('serve');\n"),
            _file("servers/atlassian/install.sh", b"#!/bin/sh\n", executable=True),
            _directory("servers/atlassian/lib"),
            _file("servers/atlassian/lib/client.js", b"export const client = 1;\n"),
            _directory("servers/other"),
            _file("servers/other/index.js", b"console.log('other');\n"),
            *extra,
        ),
    )


def _taken(snapshot: SourceSnapshot, raw: str = "servers/atlassian", **kwargs):
    return take_subtree(snapshot, _path(raw), **kwargs)


def _message(result) -> str:
    assert isinstance(result, Err), f"expected a refusal, got {result}"
    return "; ".join(diagnostic.message for diagnostic in result.diagnostics)


class SubtreeExtractionTest(unittest.TestCase):
    def test_a_repository_with_no_aart_markers_yields_a_re_rooted_subtree(self) -> None:
        taken = _taken(_foreign_repository())

        self.assertIsInstance(taken, Ok)
        self.assertEqual(
            tuple(str(entry.path) for entry in taken.value.snapshot.entries),
            ("index.js", "install.sh", "lib", "lib/client.js"),
        )
        self.assertEqual(taken.value.files, 3)

    def test_the_neighbouring_subtree_is_not_taken(self) -> None:
        """`--path` is a subset, not a filter: nothing outside it may ride along."""

        taken = _taken(_foreign_repository())

        assert isinstance(taken, Ok)
        self.assertNotIn(
            "other", {str(entry.path).split("/")[0] for entry in taken.value.snapshot.entries}
        )

    def test_executable_bits_survive_the_taking(self) -> None:
        """An install script arriving non-executable is debugged at the wrong layer (design §5)."""

        taken = _taken(_foreign_repository())

        assert isinstance(taken, Ok)
        modes = {str(entry.path): entry.executable for entry in taken.value.snapshot.entries}
        self.assertTrue(modes["install.sh"])
        self.assertFalse(modes["index.js"])

    def test_the_same_commit_and_path_yield_the_same_input_digest(self) -> None:
        """The value that becomes `OriginProvenance.input_digest`, so two vendorings compare."""

        first = _taken(_foreign_repository())
        second = _taken(_foreign_repository())

        assert isinstance(first, Ok) and isinstance(second, Ok)
        self.assertEqual(first.value.input_digest, second.value.input_digest)

    def test_a_different_subtree_of_one_repository_digests_differently(self) -> None:
        first = _taken(_foreign_repository())
        second = _taken(_foreign_repository(), "servers/other")

        assert isinstance(first, Ok) and isinstance(second, Ok)
        self.assertNotEqual(first.value.input_digest, second.value.input_digest)


class SubtreeFailsClosedTest(unittest.TestCase):
    def test_a_typo_in_the_path_refuses_instead_of_producing_an_empty_package(self) -> None:
        refused = _taken(_foreign_repository(), "servers/atlassain")

        self.assertIn("servers/atlassain", _message(refused))

    def test_a_path_naming_a_file_takes_that_file_under_its_basename(self) -> None:
        taken = _taken(_foreign_repository(), "servers/atlassian/index.js")

        self.assertIsInstance(taken, Ok)
        assert isinstance(taken, Ok)
        self.assertEqual(taken.value.path, _path("servers/atlassian/index.js"))
        self.assertEqual(
            tuple(str(entry.path) for entry in taken.value.snapshot.entries),
            ("index.js",),
        )
        self.assertEqual(taken.value.files, 1)

    def test_a_subtree_holding_only_directories_is_refused(self) -> None:
        empty = SourceSnapshot(
            SnapshotOrigin.IMMUTABLE_GIT,
            (_directory("servers"), _directory("servers/atlassian"), _file("README.md")),
        )

        refused = _taken(empty)

        self.assertIn("no files", _message(refused))

    def test_a_link_whose_target_leaves_the_subtree_is_refused_naming_both(self) -> None:
        """Neither dropped nor followed: one produces a silently incomplete package, the other
        copies content the maintainer never reviewed."""

        refused = _taken(
            _foreign_repository(_link("servers/atlassian/shared.js", "../other/index.js"))
        )

        message = _message(refused)
        self.assertIn("shared.js", message)
        self.assertIn("../other/index.js", message)
        self.assertIn("leaves it", message)

    def test_an_absolute_link_target_is_refused(self) -> None:
        refused = _taken(_foreign_repository(_link("servers/atlassian/etc", "/etc/passwd")))

        message = _message(refused)
        self.assertIn("/etc/passwd", message)
        self.assertIn("leaves it", message)

    def test_a_link_escaping_from_a_nested_directory_is_refused(self) -> None:
        """The check is relative to the link, not to the subtree root."""

        refused = _taken(
            _foreign_repository(_link("servers/atlassian/lib/up.js", "../../other/index.js"))
        )

        self.assertIn("leaves it", _message(refused))

    def test_a_contained_link_is_refused_for_the_reason_that_actually_applies(self) -> None:
        """It does not escape — and a canonical package still cannot carry it.

        `tree_digest` knows files and directories, so there is no representation for a symlink in
        the package tree or in the digest that binds it. Carrying one is a format change, which
        `2.3.0` does not make; refusing it says so rather than reporting an escape that did not
        happen.
        """

        refused = _taken(_foreign_repository(_link("servers/atlassian/alias.js", "index.js")))

        message = _message(refused)
        self.assertIn("cannot carry", message)
        self.assertNotIn("leaves it", message)

    def test_a_special_file_in_the_subtree_is_refused(self) -> None:
        special = _foreign_repository(
            SnapshotEntry(_path("servers/atlassian/socket"), SnapshotEntryKind.SPECIAL)
        )

        self.assertIn("special file", _message(_taken(special)))

    def test_a_local_snapshot_cannot_be_vendored(self) -> None:
        """Provenance binds a resolved commit; a local tree has none to bind."""

        local = SourceSnapshot(SnapshotOrigin.LOCAL, _foreign_repository().entries)

        self.assertIn("immutable Git", _message(_taken(local)))


class SubtreeLimitsTest(unittest.TestCase):
    """Limits bound what was taken, not the repository it was taken from."""

    def test_a_repository_larger_than_the_limit_still_yields_a_small_subtree(self) -> None:
        oversized = _foreign_repository(_file("vendor/blob.bin", b"0" * 4096))

        taken = _taken(oversized, limits=SnapshotLimits(max_total_bytes=2048))

        self.assertIsInstance(taken, Ok)

    def test_a_subtree_past_the_total_limit_is_refused(self) -> None:
        refused = _taken(_foreign_repository(), limits=SnapshotLimits(max_total_bytes=8))

        self.assertIn("total-size limit", _message(refused))

    def test_a_subtree_past_the_file_count_limit_is_refused(self) -> None:
        refused = _taken(_foreign_repository(), limits=SnapshotLimits(max_files=2))

        self.assertIn("file-count limit", _message(refused))

    def test_a_single_file_past_the_per_file_limit_is_refused(self) -> None:
        refused = _taken(_foreign_repository(), limits=SnapshotLimits(max_file_bytes=4))

        self.assertIn("size limit", _message(refused))

    def test_depth_is_measured_after_re_rooting(self) -> None:
        """A subtree taken from deep inside a monorepo is shallow once it is a package."""

        deep = SourceSnapshot(
            SnapshotOrigin.IMMUTABLE_GIT,
            (
                _directory("a"),
                _directory("a/b"),
                _directory("a/b/c"),
                _directory("a/b/c/d"),
                _file("a/b/c/d/index.js"),
            ),
        )

        taken = take_subtree(deep, _path("a/b/c"), limits=SnapshotLimits(max_depth=2))

        self.assertIsInstance(taken, Ok)


if __name__ == "__main__":
    unittest.main()
