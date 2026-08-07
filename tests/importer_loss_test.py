from __future__ import annotations

import json
import unittest
from pathlib import Path

from agent_artifacts.domain.result import Err
from agent_artifacts.importers.legacy_catalog import scan_legacy_catalog
from agent_artifacts.protocol.native_tree import SnapshotEntry, SnapshotEntryKind, SourceSnapshot
from agent_artifacts.protocol.paths import SafeRelativePath
from tests.importer_fixtures import add_file, fixture_snapshot, importer_input, replace_file


class ImporterLossTest(unittest.TestCase):
    def test_ambiguous_stale_unsafe_and_unknown_legacy_inputs_fail_closed(self) -> None:
        base = fixture_snapshot()
        duplicate_mcp = add_file(
            base,
            "mcp/database.json",
            b'{"name":"database","description":"duplicate","server":{}}',
        )
        stale = replace_file(
            base,
            "guidelines/style.md",
            b"---\ndescription: Changed after sync.\n---\nchanged\n",
        )
        unsafe = SourceSnapshot(
            base.origin,
            (
                *base.entries,
                SnapshotEntry(
                    SafeRelativePath(("skills", "escape")),
                    SnapshotEntryKind.SYMLINK,
                ),
            ),
        )
        unknown_bundle_field = replace_file(
            base,
            "bundles/base.json",
            b'{"name":"base","description":"base","includes":{"skills":["demo"]},"magic":true}',
        )
        invalid_name = add_file(
            base,
            "guidelines/Bad_Name.md",
            b"---\ndescription: Invalid canonical name.\n---\nbody\n",
        )

        cases = (
            (duplicate_mcp, "import-ambiguous"),
            (stale, "import-stale"),
            (unsafe, "import-lossy"),
            (unknown_bundle_field, "import-lossy"),
            (invalid_name, "import-lossy"),
        )
        for snapshot, code in cases:
            with self.subTest(code=code):
                result = scan_legacy_catalog(importer_input(snapshot))
                self.assertIsInstance(result, Err)
                assert isinstance(result, Err)
                self.assertIn(code, {item.code.value for item in result.diagnostics})

    def test_credential_bearing_enterprise_origin_is_rejected_without_echoing_it(self) -> None:
        document = json.loads(
            Path("tests/fixtures/importers/legacy_catalog/upstreams.json").read_text(
                encoding="utf-8"
            )
        )
        source = document["artifacts"]["guideline/style"]["source"]
        source["api_url"] = "https://user:top-secret@ghe.example.test/api/v3"
        snapshot = replace_file(
            fixture_snapshot(),
            "upstreams.json",
            json.dumps(document).encode("utf-8"),
        )

        result = scan_legacy_catalog(importer_input(snapshot))

        self.assertIsInstance(result, Err)
        assert isinstance(result, Err)
        messages = " ".join(item.message for item in result.diagnostics)
        self.assertNotIn("top-secret", messages)


if __name__ == "__main__":
    unittest.main()
