"""P02 contracts for deterministic native package loading from acquired tree snapshots."""

from __future__ import annotations

import json
import pathlib
import unittest
from typing import cast

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _unwrap(result):
    from agent_artifacts.domain.result import Ok

    if not isinstance(result, Ok):
        raise AssertionError(f"expected Ok, got {result!r}")
    return result.value


def _codes(result) -> tuple[str, ...]:
    from agent_artifacts.domain.result import Err

    if not isinstance(result, Err):
        raise AssertionError(f"expected Err, got {result!r}")
    return tuple(diagnostic.code.value for diagnostic in result.diagnostics)


def _entry(raw_path: str, content: bytes, *, kind=None, executable: bool = False):
    from agent_artifacts.protocol.native_tree import SnapshotEntry, SnapshotEntryKind
    from agent_artifacts.protocol.paths import parse_relative_path

    return SnapshotEntry(
        _unwrap(parse_relative_path(raw_path)),
        SnapshotEntryKind.FILE if kind is None else kind,
        content,
        executable,
    )


def _json_entry(raw_path: str, value):
    return _entry(raw_path, json.dumps(value, sort_keys=True).encode("utf-8"))


def _source_document(artifact_roots=None):
    return {
        "schema_version": 1,
        "protocol_version": 1,
        "source_id": "fixture-source",
        "display_name": "Fixture Source",
        "requires_aart": {"min_inclusive": "1.0.0", "max_exclusive": "2.0.0"},
        "required_capabilities": ["artifact-manifest-v1"],
        "artifact_roots": artifact_roots or ["artifacts"],
        "collection_roots": ["collections"],
    }


def _artifact_document(artifact_type: str, name: str, payload_format: str, **overrides):
    effects = {
        "skill": ["copy-tree"],
        "guideline": ["write-file"],
        "mcp": ["merge-json"],
        "hook": ["copy-tree", "merge-json"],
        "memory": ["managed-block"],
    }
    document = {
        "schema_version": 1,
        "type": artifact_type,
        "name": name,
        "version": "1.0.0",
        "summary": f"Use the fixture {artifact_type}.",
        "payload": {"root": "payload", "format": payload_format},
        "compatibility": {"profiles": ["claude"], "platforms": ["darwin", "linux"]},
        "install": {"scopes": ["project"], "modes": ["copy"], "effects": effects[artifact_type]},
    }
    document.update(overrides)
    return document


def _provenance_document():
    return {
        "schema_version": 1,
        "origin": {
            "kind": "git",
            "url": "https://github.com/example/upstream.git",
            "resolved_commit": "a" * 40,
            "path": "skills/review",
            "input_digest": f"sha256:{'b' * 64}",
        },
        "importer": {
            "id": "skill-v1",
            "version": "1.0.0",
            "options_digest": f"sha256:{'c' * 64}",
        },
        "warnings": [],
    }


def _setup_recipe(artifact: str):
    return {
        "schema_version": 2,
        "protocol_version": 2,
        "artifact": artifact,
        "purpose": "Configure the fixture without credentials.",
        "platforms": ["darwin"],
        "help_urls": [],
        "required_tools": [],
        "capabilities": [],
        "inputs": [],
        "steps": [
            {
                "id": "restart",
                "use": "restart.notice@1",
                "with": {"message": "Restart the harness."},
            }
        ],
    }


def _five_package_entries():
    packages = (
        ("skill", "review", "aart-skill-v1", "SKILL.md", b"---\nname: review\n---\n"),
        ("guideline", "python", "aart-guideline-v1", "python.md", b"Use Ruff.\n"),
        ("memory", "house", "aart-memory-v1", "house.md", b"Remember tests.\n"),
        ("mcp", "postgres", "aart-mcp-v1", "mcp.json", b'{"servers":{}}'),
        (
            "hook",
            "guard",
            "aart-hook-v1",
            "hook.json",
            b'{"command":"./guard.sh","name":"guard"}',
        ),
    )
    entries = [_json_entry("aart-source.json", _source_document())]
    for artifact_type, name, payload_format, payload_name, payload in packages:
        base = f"artifacts/{artifact_type}/{name}"
        entries.append(
            _json_entry(
                f"{base}/artifact.json",
                _artifact_document(artifact_type, name, payload_format),
            )
        )
        entries.append(_entry(f"{base}/payload/{payload_name}", payload))
    return entries


def _replaced(entries, raw_path: str, replacement):
    return [replacement if str(entry.path) == raw_path else entry for entry in entries]


def _load(entries, *, origin=None, executable_version: str = "1.5.0"):
    from agent_artifacts.protocol.capabilities import parse_capability
    from agent_artifacts.protocol.native_tree import (
        SnapshotOrigin,
        SourceSnapshot,
        load_native_source,
    )
    from agent_artifacts.protocol.semver import parse_semver

    snapshot = SourceSnapshot(
        SnapshotOrigin.LOCAL if origin is None else origin,
        tuple(entries),
    )
    return load_native_source(
        snapshot,
        executable_version=_unwrap(parse_semver(executable_version)),
        available_capabilities=(_unwrap(parse_capability("artifact-manifest-v1")),),
    )


class NativeSourceLoaderTest(unittest.TestCase):
    def test_artifact_version_bounds_do_not_make_the_whole_source_incompatible(self):
        entries = _five_package_entries()
        manifest_path = "artifacts/skill/review/artifact.json"
        manifest = _artifact_document(
            "skill",
            "review",
            "aart-skill-v1",
            requires_aart={"min_inclusive": "1.1.0"},
        )
        entries = _replaced(entries, manifest_path, _json_entry(manifest_path, manifest))

        loaded = _load(entries, executable_version="1.0.0")

        self.assertEqual(len(_unwrap(loaded).artifacts), 5)

    def test_documented_reference_fixture_is_executable_protocol_evidence(self):
        from agent_artifacts.protocol.native_tree import SnapshotEntry, SnapshotEntryKind
        from agent_artifacts.protocol.paths import parse_relative_path

        fixture = ROOT / "tests" / "fixtures" / "protocol" / "native-source-v1"
        entries = []
        for fixture_path in sorted(fixture.rglob("*")):
            relative = fixture_path.relative_to(fixture).as_posix()
            parsed_path = _unwrap(parse_relative_path(relative))
            if fixture_path.is_dir():
                entries.append(SnapshotEntry(parsed_path, SnapshotEntryKind.DIRECTORY))
            else:
                entries.append(
                    SnapshotEntry(
                        parsed_path,
                        SnapshotEntryKind.FILE,
                        fixture_path.read_bytes(),
                        bool(fixture_path.stat().st_mode & 0o111),
                    )
                )

        source = _unwrap(_load(entries))

        self.assertEqual(str(source.manifest.source_id), "reference-native-source")
        self.assertEqual(tuple(item.name for item in source.collections), ("essentials",))
        self.assertIsNotNone(source.artifacts[0].provenance)

    def test_local_and_immutable_git_snapshots_compile_identically_for_all_types(self):
        from agent_artifacts.protocol.native_tree import SnapshotOrigin

        entries = _five_package_entries()
        local = _unwrap(_load(entries, origin=SnapshotOrigin.LOCAL))
        git = _unwrap(_load(reversed(entries), origin=SnapshotOrigin.IMMUTABLE_GIT))

        self.assertEqual(local, git)
        self.assertEqual(
            tuple(str(package.manifest.identity) for package in local.artifacts),
            ("guideline/python", "hook/guard", "mcp/postgres", "memory/house", "skill/review"),
        )
        self.assertTrue(
            all(str(package.payload_digest).startswith("sha256:") for package in local.artifacts)
        )

        from agent_artifacts.protocol.native_tree import SnapshotEntryKind

        with_directories = entries + [
            _entry("artifacts", b"", kind=SnapshotEntryKind.DIRECTORY),
            _entry("artifacts/skill", b"", kind=SnapshotEntryKind.DIRECTORY),
            _entry("artifacts/skill/review", b"", kind=SnapshotEntryKind.DIRECTORY),
            _entry("artifacts/skill/review/payload", b"", kind=SnapshotEntryKind.DIRECTORY),
        ]
        self.assertEqual(_unwrap(_load(with_directories)), local)

    def test_declared_dependencies_are_resolved_before_the_source_crosses_its_boundary(self):
        entries = _five_package_entries()
        review_path = "artifacts/skill/review/artifact.json"
        review = _artifact_document(
            "skill",
            "review",
            "aart-skill-v1",
            requires=[{"type": "guideline", "name": "python"}],
        )
        entries = _replaced(entries, review_path, _json_entry(review_path, review))
        source = _unwrap(_load(entries))
        review_package = next(
            item for item in source.artifacts if item.manifest.identity.name == "review"
        )
        self.assertEqual(str(review_package.manifest.requires[0].identity), "guideline/python")

        missing = _artifact_document(
            "skill",
            "review",
            "aart-skill-v1",
            requires=[{"type": "skill", "name": "absent"}],
        )
        self.assertEqual(
            _codes(_load(_replaced(entries, review_path, _json_entry(review_path, missing)))),
            ("artifact-invalid",),
        )
        python_path = "artifacts/guideline/python/artifact.json"
        cyclic_python = _artifact_document(
            "guideline",
            "python",
            "aart-guideline-v1",
            requires=[{"type": "skill", "name": "review"}],
        )
        self.assertEqual(
            _codes(
                _load(
                    _replaced(
                        entries,
                        python_path,
                        _json_entry(python_path, cyclic_python),
                    )
                )
            ),
            ("artifact-invalid",),
        )

    def test_discovery_requires_the_root_marker_and_uses_only_explicit_artifact_roots(self):
        from agent_artifacts.protocol.native_tree import SnapshotEntryKind

        nested = _five_package_entries()
        nested[0] = _json_entry("nested/aart-source.json", _source_document())
        self.assertEqual(_codes(_load(nested)), ("source-marker-missing",))

        entries = _five_package_entries()
        entries.extend(
            (
                _json_entry(
                    "elsewhere/skill/ignored/artifact.json",
                    _artifact_document("skill", "ignored", "aart-skill-v1"),
                ),
                _entry("elsewhere/skill/ignored/payload/SKILL.md", b"ignored"),
            )
        )
        loaded = _unwrap(_load(entries))
        self.assertNotIn(
            "skill/ignored", tuple(str(item.manifest.identity) for item in loaded.artifacts)
        )

        with_unrelated_symlink = entries + [
            _entry("docs/latest", b"guide.md", kind=SnapshotEntryKind.SYMLINK)
        ]
        self.assertEqual(_unwrap(_load(with_unrelated_symlink)), loaded)

    def test_rejects_symlinks_special_files_duplicates_and_identity_mismatches(self):
        from agent_artifacts.protocol.native_tree import (
            SnapshotEntry,
            SnapshotEntryKind,
            SnapshotOrigin,
            SourceSnapshot,
            load_native_source,
        )
        from agent_artifacts.protocol.paths import SafeRelativePath, parse_relative_path
        from agent_artifacts.protocol.semver import parse_semver

        base = _five_package_entries()
        cases = (
            (
                base
                + [
                    _entry("artifacts/skill/review/link", b"target", kind=SnapshotEntryKind.SYMLINK)
                ],
                "source-tree-invalid",
            ),
            (
                base
                + [_entry("artifacts/skill/review/device", b"", kind=SnapshotEntryKind.SPECIAL)],
                "source-tree-invalid",
            ),
            (base + [base[-1]], "source-tree-invalid"),
        )
        for entries, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(_codes(_load(entries)), (expected,))

        mismatched = _five_package_entries()
        mismatched[1] = _json_entry(
            "artifacts/skill/review/artifact.json",
            _artifact_document("skill", "other", "aart-skill-v1"),
        )
        self.assertEqual(_codes(_load(mismatched)), ("artifact-invalid",))

        invalid_path = SnapshotEntry(SafeRelativePath(("..", "escape")), SnapshotEntryKind.FILE)
        self.assertEqual(_codes(_load(base + [invalid_path])), ("source-tree-invalid",))
        bad_directory = _entry(
            "artifacts/empty",
            b"content",
            kind=SnapshotEntryKind.DIRECTORY,
        )
        self.assertEqual(_codes(_load(base + [bad_directory])), ("source-tree-invalid",))
        invalid_kind = SnapshotEntry(
            _unwrap(parse_relative_path("bad-kind")),
            cast(SnapshotEntryKind, "socket"),
        )
        self.assertEqual(_codes(_load(base + [invalid_kind])), ("source-tree-invalid",))
        invalid_content = SnapshotEntry(
            _unwrap(parse_relative_path("bad-content")),
            SnapshotEntryKind.FILE,
            cast(bytes, "text"),
        )
        self.assertEqual(_codes(_load(base + [invalid_content])), ("source-tree-invalid",))
        invalid_origin = SourceSnapshot(cast(SnapshotOrigin, "mutable-git"), tuple(base))
        self.assertEqual(
            _codes(
                load_native_source(
                    invalid_origin,
                    executable_version=_unwrap(parse_semver("1.5.0")),
                    available_capabilities=(),
                )
            ),
            ("source-tree-invalid",),
        )

    def test_enforces_payload_conventions_and_declared_setup_recipe_presence(self):
        entries = _five_package_entries()
        without_skill_payload = [
            entry
            for entry in entries
            if str(entry.path) != "artifacts/skill/review/payload/SKILL.md"
        ]
        self.assertEqual(_codes(_load(without_skill_payload)), ("artifact-invalid",))

        setup_entries = _five_package_entries()
        setup_entries[7] = _json_entry(
            "artifacts/mcp/postgres/artifact.json",
            _artifact_document(
                "mcp",
                "postgres",
                "aart-mcp-v1",
                setup={"recipe": "setup/installer.json", "platforms": ["darwin"]},
            ),
        )
        self.assertEqual(_codes(_load(setup_entries)), ("artifact-invalid",))
        setup_entries.append(
            _json_entry("artifacts/mcp/postgres/setup/installer.json", {"schema_version": 1})
        )
        self.assertEqual(_codes(_load(setup_entries)), ("artifact-invalid",))
        setup_entries = _replaced(
            setup_entries,
            "artifacts/mcp/postgres/setup/installer.json",
            _json_entry(
                "artifacts/mcp/postgres/setup/installer.json",
                _setup_recipe("mcp/postgres"),
            ),
        )
        setup_entries.append(_entry("artifacts/mcp/postgres/SETUP.md", b"Manual fixture setup.\n"))
        self.assertEqual(len(_unwrap(_load(setup_entries)).artifacts), 5)

        root_manual_without_setup = _five_package_entries() + [
            _entry("artifacts/mcp/postgres/SETUP.md", b"Orphaned manual.\n")
        ]
        self.assertEqual(_codes(_load(root_manual_without_setup)), ("artifact-invalid",))

    def test_rejects_malformed_payloads_undeclared_setup_and_bad_provenance(self):
        base = _five_package_entries()
        cases = (
            (
                _replaced(
                    base,
                    "artifacts/skill/review/payload/SKILL.md",
                    _entry("artifacts/skill/review/payload/SKILL.md", b"\xff"),
                ),
                ("artifact-invalid",),
            ),
            (
                _replaced(
                    base,
                    "artifacts/mcp/postgres/payload/mcp.json",
                    _entry("artifacts/mcp/postgres/payload/mcp.json", b"not-json"),
                ),
                ("artifact-invalid",),
            ),
            (
                base + [_entry("artifacts/guideline/python/payload/extra.md", b"extra")],
                ("artifact-invalid",),
            ),
            (
                _replaced(
                    base,
                    "artifacts/mcp/postgres/payload/mcp.json",
                    _entry("artifacts/mcp/postgres/payload/other.json", b"{}"),
                ),
                ("artifact-invalid",),
            ),
            (
                base + [_json_entry("artifacts/skill/review/setup/installer.json", {})],
                ("artifact-invalid",),
            ),
            (
                base + [_json_entry("artifacts/skill/review/provenance.json", [])],
                ("provenance-invalid",),
            ),
            (
                base + [_entry("artifacts/skill/review/unexpected.txt", b"unexpected")],
                ("artifact-invalid",),
            ),
            (
                [
                    entry
                    for entry in base
                    if str(entry.path) != "artifacts/hook/guard/artifact.json"
                ],
                ("artifact-invalid",),
            ),
        )
        for entries, expected in cases:
            with self.subTest(paths=tuple(str(entry.path) for entry in entries)):
                self.assertEqual(_codes(_load(entries)), expected)

        valid_provenance = base + [
            _json_entry("artifacts/skill/review/provenance.json", _provenance_document())
        ]
        source = _unwrap(_load(valid_provenance))
        skill = next(
            item for item in source.artifacts if str(item.manifest.identity) == "skill/review"
        )
        self.assertIsNotNone(skill.provenance)

    def test_loads_declared_collections_and_rejects_path_identity_or_depth_mismatch(self):
        collection = {
            "schema_version": 1,
            "name": "base",
            "summary": "Base tools.",
            "artifacts": [{"type": "skill", "name": "review"}],
            "collections": [],
        }
        loaded = _unwrap(
            _load(_five_package_entries() + [_json_entry("collections/base.json", collection)])
        )
        self.assertEqual(tuple(item.name for item in loaded.collections), ("base",))

        mismatch = {**collection, "name": "other"}
        self.assertEqual(
            _codes(
                _load(_five_package_entries() + [_json_entry("collections/base.json", mismatch)])
            ),
            ("collection-invalid",),
        )
        self.assertEqual(
            _codes(
                _load(
                    _five_package_entries()
                    + [_json_entry("collections/nested/base.json", collection)]
                )
            ),
            ("collection-invalid",),
        )

    def test_rejects_unknown_layout_empty_sources_and_duplicate_identities_across_roots(self):
        unknown = _five_package_entries() + [_entry("artifacts/widget/example/file.txt", b"data")]
        self.assertEqual(_codes(_load(unknown)), ("source-tree-invalid",))

        empty = [_json_entry("aart-source.json", _source_document())]
        self.assertEqual(_codes(_load(empty)), ("source-tree-invalid",))

        duplicated = _five_package_entries()
        duplicated[0] = _json_entry(
            "aart-source.json",
            _source_document(["artifacts", "vendor"]),
        )
        duplicated.extend(
            (
                _json_entry(
                    "vendor/skill/review/artifact.json",
                    _artifact_document("skill", "review", "aart-skill-v1"),
                ),
                _entry("vendor/skill/review/payload/SKILL.md", b"review"),
            )
        )
        self.assertEqual(_codes(_load(duplicated)), ("artifact-invalid",))

        direct_file = _five_package_entries() + [_entry("artifacts/orphan.txt", b"data")]
        self.assertEqual(_codes(_load(direct_file)), ("source-tree-invalid",))

    def test_invalid_root_marker_and_duplicate_collection_identities_fail(self):
        from agent_artifacts.protocol.native_tree import SnapshotEntryKind

        marker_directory = _five_package_entries()
        marker_directory[0] = _entry(
            "aart-source.json",
            b"",
            kind=SnapshotEntryKind.DIRECTORY,
        )
        self.assertEqual(_codes(_load(marker_directory)), ("source-marker-missing",))

        invalid_marker = _five_package_entries()
        invalid_marker[0] = _entry("aart-source.json", b"not-json")
        self.assertEqual(_codes(_load(invalid_marker)), ("protocol-json-invalid",))

        source = _source_document()
        source["collection_roots"] = ["collections", "more-collections"]
        collection = {
            "schema_version": 1,
            "name": "base",
            "summary": "Base tools.",
            "artifacts": [{"type": "skill", "name": "review"}],
        }
        entries = _five_package_entries()
        entries[0] = _json_entry("aart-source.json", source)
        entries.extend(
            (
                _json_entry("collections/base.json", collection),
                _json_entry("more-collections/base.json", collection),
            )
        )
        self.assertEqual(_codes(_load(entries)), ("collection-invalid",))

    def test_required_version_and_capability_handshake_fail_before_package_loading(self):
        from agent_artifacts.protocol.native_tree import (
            SnapshotOrigin,
            SourceSnapshot,
            load_native_source,
        )
        from agent_artifacts.protocol.semver import parse_semver

        entries = _five_package_entries()
        entries[0] = _json_entry(
            "aart-source.json",
            _source_document(),
        )
        snapshot = SourceSnapshot(SnapshotOrigin.LOCAL, tuple(entries))
        result = load_native_source(
            snapshot,
            executable_version=_unwrap(parse_semver("2.0.0")),
            available_capabilities=(),
        )
        self.assertEqual(_codes(result), ("source-incompatible", "source-incompatible"))


if __name__ == "__main__":
    unittest.main()
