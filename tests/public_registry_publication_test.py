from __future__ import annotations

import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from agent_artifacts.domain.identifiers import ArtifactIdentity, ObjectDigest, SourceId
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.protocol.json import canonical_json_bytes, parse_json
from agent_artifacts.protocol.native_tree import (
    SnapshotEntry,
    SnapshotEntryKind,
    SnapshotOrigin,
    SourceSnapshot,
)
from agent_artifacts.protocol.paths import SafeRelativePath
from agent_artifacts.registry_publication import (
    PublicRegistryAudit,
    PublicRegistryPolicy,
    audit_public_registry_tree,
    read_public_registry_tree,
)

COMMIT = "0123456789abcdef0123456789abcdef01234567"
ORIGIN = "https://github.com/example/tool.git"


def _path(value: str) -> SafeRelativePath:
    return SafeRelativePath(tuple(value.split("/")))


def _entry(path: str, content: bytes, *, executable: bool = False) -> SnapshotEntry:
    return SnapshotEntry(_path(path), SnapshotEntryKind.FILE, content, executable)


def _json(path: str, value: object) -> SnapshotEntry:
    return _entry(path, canonical_json_bytes(parse_json(json.dumps(value).encode()).value))


def _policy() -> PublicRegistryPolicy:
    return PublicRegistryPolicy(
        registry_id=SourceId("reference-registry"),
        target_repository="example/reference-registry",
        source_repository=ORIGIN,
        source_commit=COMMIT,
        artifacts=(ArtifactIdentity("skill", "demo"),),
        collections=("base",),
        accepted_licenses=("MIT",),
    )


def _snapshot() -> SourceSnapshot:
    policy = _policy()
    files = [
        _entry(path, content, executable=executable)
        for path, content, executable in policy.repository_files
    ]
    files.extend(
        (
            _json(
                "aart-registry.json",
                {
                    "schema_version": 1,
                    "protocol_version": 1,
                    "registry_id": "reference-registry",
                    "display_name": "AART Reference Registry",
                    "requires_aart": {
                        "min_inclusive": "1.0.0",
                        "max_exclusive": "2.0.0",
                    },
                    "required_capabilities": [
                        "artifact-manifest-v1",
                        "lockfile-v1",
                        "registry-entry-v1",
                    ],
                    "default_channel": "main",
                    "services": {},
                },
            ),
            _json(
                "aart-source.json",
                {
                    "schema_version": 1,
                    "protocol_version": 1,
                    "source_id": "reference-registry",
                    "display_name": "AART Reference Registry",
                    "requires_aart": {
                        "min_inclusive": "1.0.0-a1",
                        "max_exclusive": "2.0.0",
                    },
                    "required_capabilities": [],
                    "artifact_roots": ["artifacts"],
                    "collection_roots": ["collections"],
                },
            ),
            _json(
                "aart.lock.json",
                {
                    "schema_version": 1,
                    "registry_inputs_digest": "sha256:"
                    "0000000000000000000000000000000000000000000000000000000000000000",
                    "entries": {},
                },
            ),
            _json(
                "aart.index.json",
                {
                    "schema_version": 1,
                    "protocol_version": 1,
                    "registry_id": "reference-registry",
                    "registry_inputs_digest": "sha256:"
                    "0000000000000000000000000000000000000000000000000000000000000000",
                    "artifacts": [],
                    "collections": [],
                    "services": {},
                },
            ),
            _json(
                "artifacts/skill/demo/artifact.json",
                {
                    "schema_version": 1,
                    "type": "skill",
                    "name": "demo",
                    "version": "1.0.0",
                    "summary": "Demonstrate a reviewed artifact.",
                    "payload": {"root": "payload", "format": "aart-skill-v1"},
                    "compatibility": {"profiles": ["codex"], "platforms": ["darwin"]},
                    "install": {
                        "scopes": ["project", "user"],
                        "modes": ["copy", "symlink"],
                        "effects": ["copy-tree"],
                    },
                    "license": "MIT",
                },
            ),
            _json(
                "artifacts/skill/demo/provenance.json",
                {
                    "schema_version": 1,
                    "origin": {
                        "kind": "git",
                        "url": ORIGIN,
                        "resolved_commit": COMMIT,
                        "path": "skills/demo",
                        "input_digest": "sha256:"
                        "1111111111111111111111111111111111111111111111111111111111111111",
                    },
                    "importer": {
                        "id": "legacy-catalog-v1",
                        "version": "1.0.0",
                        "options_digest": "sha256:"
                        "2222222222222222222222222222222222222222222222222222222222222222",
                    },
                    "warnings": [],
                },
            ),
            _entry("artifacts/skill/demo/payload/SKILL.md", b"# Demo\n"),
            _json(
                "collections/base.json",
                {
                    "schema_version": 1,
                    "name": "base",
                    "summary": "Base collection.",
                    "artifacts": [{"type": "skill", "name": "demo"}],
                    "collections": [],
                },
            ),
        )
    )
    return SourceSnapshot(SnapshotOrigin.LOCAL, tuple(files))


def _replace_file(snapshot: SourceSnapshot, path: str, content: bytes) -> SourceSnapshot:
    entries = tuple(
        replace(entry, content=content) if str(entry.path) == path else entry
        for entry in snapshot.entries
    )
    return SourceSnapshot(snapshot.origin, entries)


def _remove(snapshot: SourceSnapshot, path: str) -> SourceSnapshot:
    return SourceSnapshot(
        snapshot.origin, tuple(entry for entry in snapshot.entries if str(entry.path) != path)
    )


def _json_value(snapshot: SourceSnapshot, path: str) -> dict:
    return json.loads(next(entry.content for entry in snapshot.entries if str(entry.path) == path))


def _replace_json(snapshot: SourceSnapshot, path: str, update) -> SourceSnapshot:
    value = _json_value(snapshot, path)
    update(value)
    return _replace_file(snapshot, path, json.dumps(value).encode())


class PublicRegistryPublicationTest(unittest.TestCase):
    def test_policy_and_receipt_values_reject_invalid_boundaries(self) -> None:
        invalid_policies = (
            {"target_repository": "missing-owner"},
            {"source_repository": "https://private.example/repo.git"},
            {"source_commit": "abc"},
            {"artifacts": ()},
            {"artifacts": (ArtifactIdentity("skill", "demo"),) * 2},
            {"collections": ("base", "base")},
            {"collections": ("../private",)},
            {"accepted_licenses": ()},
            {"accepted_licenses": ("bad\nlicense",)},
        )
        for changes in invalid_policies:
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    replace(_policy(), **changes)
        with self.assertRaises(ValueError):
            PublicRegistryAudit(ObjectDigest("sha256", "0" * 64), 0, 1, 0, COMMIT)

    def test_reviewed_exact_tree_passes_and_receipt_is_deterministic(self) -> None:
        first = audit_public_registry_tree(_snapshot(), _policy())
        second = audit_public_registry_tree(_snapshot(), _policy())
        assert isinstance(first, Ok), first
        self.assertEqual(first, second)
        self.assertEqual(first.value.artifact_count, 1)
        self.assertEqual(first.value.collection_count, 1)
        self.assertGreater(first.value.file_count, 8)

    def test_license_and_provenance_are_mandatory_and_exact(self) -> None:
        snapshot = _snapshot()
        manifest_path = "artifacts/skill/demo/artifact.json"
        manifest = json.loads(
            next(e.content for e in snapshot.entries if str(e.path) == manifest_path)
        )
        manifest.pop("license")
        missing_license = audit_public_registry_tree(
            _replace_file(snapshot, manifest_path, json.dumps(manifest).encode()), _policy()
        )
        self.assertIsInstance(missing_license, Err)
        self.assertIn("license", missing_license.diagnostics[0].message)

        provenance_path = "artifacts/skill/demo/provenance.json"
        provenance = json.loads(
            next(e.content for e in snapshot.entries if str(e.path) == provenance_path)
        )
        provenance["origin"]["resolved_commit"] = "f" * 40
        wrong_commit = audit_public_registry_tree(
            _replace_file(snapshot, provenance_path, json.dumps(provenance).encode()), _policy()
        )
        self.assertIsInstance(wrong_commit, Err)
        self.assertIn("source commit", wrong_commit.diagnostics[0].message)

    def test_credentials_private_paths_links_and_generated_files_fail_closed(self) -> None:
        cases = (
            _entry("artifacts/skill/demo/payload/token.txt", b"ghp_" + b"a" * 36),
            _entry("artifacts/skill/demo/payload/path.txt", b"/Users/alice/private/repo\n"),
            SnapshotEntry(_path("artifacts/skill/demo/payload/link"), SnapshotEntryKind.SYMLINK),
            _entry("dist/reference-registry.zip", b"generated"),
        )
        for unsafe in cases:
            with self.subTest(path=str(unsafe.path)):
                result = audit_public_registry_tree(
                    SourceSnapshot(SnapshotOrigin.LOCAL, (*_snapshot().entries, unsafe)),
                    _policy(),
                )
                self.assertIsInstance(result, Err)

    def test_unexpected_identity_collection_or_workflow_bytes_fail_closed(self) -> None:
        for policy in (
            replace(
                _policy(),
                artifacts=(ArtifactIdentity("skill", "other"),),
            ),
            replace(_policy(), collections=("other",)),
        ):
            with self.subTest(policy=policy):
                self.assertIsInstance(audit_public_registry_tree(_snapshot(), policy), Err)
        changed_ci = _replace_file(
            _snapshot(), ".github/workflows/aart-registry.yml", b"name: disabled\n"
        )
        self.assertIsInstance(audit_public_registry_tree(changed_ci, _policy()), Err)

    def test_root_and_content_failures_are_rejected_before_publication(self) -> None:
        cases = (
            SourceSnapshot(SnapshotOrigin.LOCAL, ()),
            _remove(_snapshot(), "aart-registry.json"),
            _remove(_snapshot(), "aart-source.json"),
            _remove(_snapshot(), "aart.lock.json"),
            _remove(_snapshot(), "aart.index.json"),
            _replace_file(_snapshot(), "aart-registry.json", b"{}"),
            _replace_file(_snapshot(), "artifacts/skill/demo/payload/SKILL.md", b"bad\0content"),
            _replace_file(_snapshot(), "artifacts/skill/demo/payload/SKILL.md", b"\xff\xfe"),
            SourceSnapshot(
                SnapshotOrigin.LOCAL,
                (*_snapshot().entries, _entry("artifacts/skill/demo/README.md", b"unexpected")),
            ),
        )
        for candidate in cases:
            with self.subTest(entries=len(candidate.entries)):
                self.assertIsInstance(audit_public_registry_tree(candidate, _policy()), Err)

    def test_every_artifact_and_collection_boundary_is_enforced(self) -> None:
        manifest_path = "artifacts/skill/demo/artifact.json"
        provenance_path = "artifacts/skill/demo/provenance.json"
        collection_path = "collections/base.json"
        cases = (
            _replace_file(_snapshot(), manifest_path, b"{}"),
            _remove(_snapshot(), provenance_path),
            _replace_file(_snapshot(), provenance_path, b"{}"),
            _replace_json(
                _snapshot(),
                provenance_path,
                lambda value: value["origin"].update(url="https://github.com/example/other.git"),
            ),
            _replace_json(
                _snapshot(),
                provenance_path,
                lambda value: value["origin"].update(path="skills/other"),
            ),
            _remove(_snapshot(), "artifacts/skill/demo/payload/SKILL.md"),
            _replace_file(_snapshot(), collection_path, b"{}"),
            _replace_json(_snapshot(), collection_path, lambda value: value.update(name="other")),
            _replace_json(
                _snapshot(),
                collection_path,
                lambda value: value.update(artifacts=[{"type": "skill", "name": "other"}]),
            ),
            _remove(_snapshot(), collection_path),
        )
        for candidate in cases:
            with self.subTest(candidate=candidate):
                self.assertIsInstance(audit_public_registry_tree(candidate, _policy()), Err)

    def test_complete_tree_reader_is_non_following_and_omits_only_git_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "registry"
            root.mkdir()
            for entry in _snapshot().entries:
                target = root.joinpath(*entry.path.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(entry.content)
                target.chmod(0o700 if entry.executable else 0o600)
            git = root / ".git"
            git.mkdir()
            (git / "private-token").write_bytes(b"ghp_" + b"a" * 36)

            read = read_public_registry_tree(str(root))
            assert isinstance(read, Ok), read
            self.assertFalse(
                any(
                    str(entry.path) == ".git" or str(entry.path).startswith(".git/")
                    for entry in read.value.entries
                )
            )
            audited = audit_public_registry_tree(read.value, _policy())
            self.assertIsInstance(audited, Ok)

            link = root / "artifacts/skill/demo/payload/link"
            link.symlink_to("SKILL.md")
            linked = read_public_registry_tree(str(root))
            assert isinstance(linked, Ok), linked
            self.assertTrue(
                any(entry.kind is SnapshotEntryKind.SYMLINK for entry in linked.value.entries)
            )
            self.assertIsInstance(audit_public_registry_tree(linked.value, _policy()), Err)

    def test_tree_reader_rejects_invalid_roots_and_bounded_io_failures(self) -> None:
        self.assertIsInstance(read_public_registry_tree("relative"), Err)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            missing = root / "missing"
            self.assertIsInstance(read_public_registry_tree(str(missing)), Err)
            regular = root / "file"
            regular.write_text("file", encoding="utf-8")
            self.assertIsInstance(read_public_registry_tree(str(regular)), Err)
            linked = root / "link"
            linked.symlink_to(regular)
            self.assertIsInstance(read_public_registry_tree(str(linked)), Err)

            directory = root / "tree"
            directory.mkdir()
            (directory / "large").write_bytes(b"12")
            with patch("agent_artifacts.registry_publication._MAX_FILE_BYTES", 1):
                self.assertIsInstance(read_public_registry_tree(str(directory)), Err)

            fifo = directory / "fifo"
            os.mkfifo(fifo)
            special = read_public_registry_tree(str(directory))
            assert isinstance(special, Ok), special
            self.assertTrue(
                any(entry.kind is SnapshotEntryKind.SPECIAL for entry in special.value.entries)
            )
            self.assertIsInstance(audit_public_registry_tree(special.value, _policy()), Err)


if __name__ == "__main__":
    unittest.main()
