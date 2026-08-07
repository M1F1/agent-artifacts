from __future__ import annotations

import json
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from agent_artifacts.domain.identifiers import ObjectDigest
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.importers.legacy_catalog import (
    build_import_apply_plan,
    diff_legacy_import,
    materialize_legacy_catalog,
    plan_legacy_catalog,
    scan_legacy_catalog,
    validate_legacy_import,
)
from agent_artifacts.importers.model import ImportChangeKind
from agent_artifacts.protocol.hashing import json_digest
from agent_artifacts.protocol.json import JsonObject
from agent_artifacts.protocol.native_tree import (
    SnapshotEntry,
    SnapshotEntryKind,
    SourceSnapshot,
)
from agent_artifacts.protocol.paths import SafeRelativePath
from agent_artifacts.protocol.semver import SemVer
from agent_artifacts.upstream_source import hash_upstream_path
from tests.importer_fixtures import (
    FIXTURE_ROOT,
    add_file,
    fixture_snapshot,
    importer_input,
    replace_file,
)
from tests.legacy_importer_test import options

UPSTREAMS = Path("tests/fixtures/importers/legacy_catalog/upstreams.json")


def _without(snapshot: SourceSnapshot, path: str) -> SourceSnapshot:
    return SourceSnapshot(
        snapshot.origin,
        tuple(entry for entry in snapshot.entries if str(entry.path) != path),
    )


def _upstreams() -> dict:
    return json.loads(UPSTREAMS.read_text(encoding="utf-8"))


def _with_upstreams(snapshot: SourceSnapshot, document: object) -> SourceSnapshot:
    return replace_file(snapshot, "upstreams.json", json.dumps(document).encode())


class LegacyImporterEdgesTest(unittest.TestCase):
    def test_recognized_descriptors_and_setup_fail_closed_when_malformed(self) -> None:
        base = fixture_snapshot()
        cases = (
            add_file(
                _without(base, "skills/demo/SKILL.md"),
                "skills/demo/README.md",
                b"descriptor is missing\n",
            ),
            add_file(base, "guidelines/unexpected.txt", b"not a guideline\n"),
            add_file(base, "mcp/missing/README.md", b"no descriptor\n"),
            add_file(base, "mcp/database/database.json", b'{"name":"database"}'),
            replace_file(base, "mcp/database/mcp.json", b"[]"),
            replace_file(base, "hooks/lint/hook.json", b'{"name":"lint","name":"other"}'),
            replace_file(base, "skills/demo/SKILL.md", b"\xff"),
            add_file(
                _without(base, "mcp/database/setup/installer.json"),
                "mcp/database/setup/notes.txt",
                b"recipe is missing\n",
            ),
            replace_file(
                base,
                "mcp/database/setup/installer.json",
                b'{"platforms":[]}',
            ),
        )
        for index, snapshot in enumerate(cases):
            with self.subTest(case=index):
                self.assertIsInstance(scan_legacy_catalog(importer_input(snapshot)), Err)

    def test_bundle_shape_and_references_fail_closed(self) -> None:
        base = fixture_snapshot()
        cases = (
            add_file(base, "bundles/nested/base.json", b"{}"),
            replace_file(base, "bundles/base.json", b'{"name":"other"}'),
            replace_file(base, "bundles/base.json", b"[]"),
            replace_file(
                base,
                "bundles/base.json",
                b'{"name":"base","description":"x","includes":{"skills":["absent"]}}',
            ),
            add_file(base, "bundles/Bad_Name.json", b'{"name":"Bad_Name"}'),
        )
        for index, snapshot in enumerate(cases):
            with self.subTest(case=index):
                self.assertIsInstance(scan_legacy_catalog(importer_input(snapshot)), Err)

    def test_upstream_schema_pin_and_origin_fail_closed(self) -> None:
        base = fixture_snapshot()
        malformed_root = {"version": 1, "artifacts": [], "extra": True}
        scalar_entry = {"version": 1, "artifacts": {"guideline/style": "bad"}}
        missing_entry_field = _upstreams()
        del missing_entry_field["artifacts"]["guideline/style"]["last_synced"]
        scalar_source = _upstreams()
        scalar_source["artifacts"]["guideline/style"]["source"] = "bad"
        unknown_nested = _upstreams()
        unknown_nested["artifacts"]["guideline/style"]["source"]["token"] = "secret"
        absent = _upstreams()
        absent["artifacts"]["guideline/absent"] = absent["artifacts"].pop("guideline/style")
        invalid_sha = _upstreams()
        invalid_sha["artifacts"]["guideline/style"]["last_synced"]["sha"] = "main"
        invalid_hash = _upstreams()
        invalid_hash["artifacts"]["guideline/style"]["last_synced"]["content_hash"] = "sha256:bad"
        unsafe_path = _upstreams()
        unsafe_path["artifacts"]["guideline/style"]["source"]["path"] = "../escape.md"
        unsafe_web = _upstreams()
        unsafe_web["artifacts"]["guideline/style"]["source"]["web_url"] = (
            "https://example.test/repo/"
        )
        cases = (
            malformed_root,
            scalar_entry,
            missing_entry_field,
            scalar_source,
            unknown_nested,
            absent,
            invalid_sha,
            invalid_hash,
            unsafe_path,
            unsafe_web,
        )
        for index, document in enumerate(cases):
            with self.subTest(case=index):
                result = scan_legacy_catalog(importer_input(_with_upstreams(base, document)))
                self.assertIsInstance(result, Err)

    def test_input_bounds_are_checked_before_parsing(self) -> None:
        base = fixture_snapshot()
        with patch("agent_artifacts.importers.legacy_catalog._MAX_ENTRIES", 0):
            self.assertIsInstance(scan_legacy_catalog(importer_input(base)), Err)
        with patch("agent_artifacts.importers.legacy_catalog._MAX_FILE_BYTES", 1):
            self.assertIsInstance(scan_legacy_catalog(importer_input(base)), Err)
        with patch("agent_artifacts.importers.legacy_catalog._MAX_TOTAL_BYTES", 1):
            self.assertIsInstance(scan_legacy_catalog(importer_input(base)), Err)

    def test_flat_mcp_untracked_source_and_tracked_directory_are_supported(self) -> None:
        base = fixture_snapshot()
        without_upstreams = _without(base, "upstreams.json")
        untracked = scan_legacy_catalog(importer_input(without_upstreams))
        self.assertIsInstance(untracked, Ok)

        directory_paths = (
            "mcp/database/SETUP.md",
            "mcp/database/setup/installer.json",
            "mcp/database/mcp.json",
        )
        flat = base
        for path in directory_paths:
            flat = _without(flat, path)
        flat = add_file(
            flat,
            "mcp/database.json",
            b'{"name":"database","description":"Flat database MCP.","server":{}}',
        )
        self.assertIsInstance(scan_legacy_catalog(importer_input(flat)), Ok)

        document = _upstreams()
        document["artifacts"]["skill/demo"] = {
            "source": {
                "kind": "github",
                "repo": "team/demo-skill",
                "ref": "main",
                "path": "skills/demo",
                "api_url": "https://ghe.example.test/api/v3",
            },
            "last_synced": {
                "sha": "1" * 40,
                "content_hash": hash_upstream_path(str(FIXTURE_ROOT / "skills" / "demo")),
                "synced_at": "ignored",
            },
        }
        tracked = scan_legacy_catalog(importer_input(_with_upstreams(base, document)))
        self.assertIsInstance(tracked, Ok)

    def test_tampered_options_input_output_and_diff_are_rejected(self) -> None:
        request = importer_input()
        scanned = scan_legacy_catalog(request)
        assert isinstance(scanned, Ok)
        planned = plan_legacy_catalog(scanned.value, options())
        assert isinstance(planned, Ok)

        malformed_options = JsonObject((("schema_version", 1),))
        malformed_plan = replace(
            planned.value,
            options=malformed_options,
            options_digest=json_digest(malformed_options),
        )
        self.assertIsInstance(materialize_legacy_catalog(request, malformed_plan), Err)
        for key, value in (
            ("profiles", "not-an-array"),
            ("artifact_version", "not-semver"),
            ("display_name", " invalid "),
        ):
            option_document = JsonObject(
                tuple(
                    (name, value if name == key else item)
                    for name, item in planned.value.options.entries
                )
            )
            tampered = replace(
                planned.value,
                options=option_document,
                options_digest=json_digest(option_document),
            )
            with self.subTest(option=key):
                self.assertIsInstance(materialize_legacy_catalog(request, tampered), Err)
        changed_input = importer_input(
            replace_file(request.snapshot, "skills/demo/SKILL.md", b"# Changed\n")
        )
        self.assertIsInstance(materialize_legacy_catalog(changed_input, planned.value), Err)

        materialized = materialize_legacy_catalog(request, planned.value)
        assert isinstance(materialized, Ok)
        forged = replace(
            materialized.value,
            output_digest=ObjectDigest("sha256", "f" * 64),
        )
        self.assertIsInstance(
            validate_legacy_import(forged, executable_version=SemVer(1, 0, 0)),
            Err,
        )
        validated = validate_legacy_import(
            materialized.value,
            executable_version=SemVer(1, 0, 0),
        )
        assert isinstance(validated, Ok)
        extra = SnapshotEntry(
            SafeRelativePath(("removed-after-import.txt",)),
            SnapshotEntryKind.FILE,
            b"old\n",
        )
        destination = SourceSnapshot(
            materialized.value.snapshot.origin,
            (*materialized.value.snapshot.entries, extra),
        )
        diff = diff_legacy_import(validated.value, destination)
        assert isinstance(diff, Ok)
        self.assertIn(ImportChangeKind.REMOVED, {item.kind for item in diff.value.changes})
        mismatched = replace(diff.value, after_digest=ObjectDigest("sha256", "0" * 64))
        with self.assertRaises(ValueError):
            build_import_apply_plan(validated.value, mismatched)


if __name__ == "__main__":
    unittest.main()
