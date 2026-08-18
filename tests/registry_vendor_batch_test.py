from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_artifacts import cli
from agent_artifacts.curation.runtime import LocalCurationService
from agent_artifacts.domain.result import Ok
from agent_artifacts.protocol.native_tree import (
    SnapshotEntry,
    SnapshotEntryKind,
    SnapshotOrigin,
    SourceSnapshot,
)
from agent_artifacts.protocol.paths import parse_relative_path
from agent_artifacts.registry_maintenance.model import NativeReferenceAcquisition

_URL = "https://example.com/foreign.git"
_COMMIT = "b" * 40


def _path(raw: str):
    parsed = parse_relative_path(raw)
    assert isinstance(parsed, Ok)
    return parsed.value


def _run(*arguments: str) -> tuple[int, str]:
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = cli.main(list(arguments))
    return code, output.getvalue()


def _init_registry(root: Path) -> None:
    subprocess.run(("git", "-C", str(root), "init", "-q"), check=True)
    code, output = _run(
        "registry",
        "init",
        "--source",
        str(root),
        "--source-id",
        "company-registry",
        "--display-name",
        "Company Registry",
        "--yes",
    )
    assert code == 0, output


class RegistryDiscoveryTest(unittest.TestCase):
    def test_discovery_emits_rejected_reviewable_candidates_for_conventional_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            checkout = Path(temporary) / "foreign"
            (checkout / "skills" / "review").mkdir(parents=True)
            (checkout / "skills" / "review" / "SKILL.md").write_text("# Review\n")
            (checkout / "guidelines").mkdir()
            (checkout / "guidelines" / "testing.md").write_text("# Test\n")
            (checkout / "CLAUDE.md").write_text("# Memory\n")
            (checkout / "README.md").write_text("not a candidate\n")

            code, output = _run(
                "registry",
                "discover",
                "--checkout",
                str(checkout),
                "--url",
                _URL,
                "--profile",
                "claude",
                "--platform",
                "darwin",
            )

            self.assertEqual(code, 0, output)
            manifest = json.loads(output)
            self.assertEqual(manifest["origin"], {"ref": "main", "url": _URL})
            self.assertEqual(len(manifest["artifacts"]), 3)
            self.assertTrue(all(item["accept"] is False for item in manifest["artifacts"]))
            self.assertEqual(
                {(item["kind"], item["path"]) for item in manifest["artifacts"]},
                {
                    ("skill", "skills/review"),
                    ("guideline", "guidelines/testing.md"),
                    ("memory", "CLAUDE.md"),
                },
            )


class RegistryVendorBatchTest(unittest.TestCase):
    def test_two_accepted_artifacts_use_one_acquisition_and_one_atomic_plan(self) -> None:
        upstream = SourceSnapshot(
            SnapshotOrigin.IMMUTABLE_GIT,
            (
                SnapshotEntry(_path("docs/one.md"), SnapshotEntryKind.FILE, b"# One\n"),
                SnapshotEntry(_path("docs/two.md"), SnapshotEntryKind.FILE, b"# Two\n"),
            ),
        )
        acquisition = NativeReferenceAcquisition(_URL, "main", _COMMIT, upstream)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "registry"
            root.mkdir()
            _init_registry(root)
            manifest = Path(temporary) / "vendors.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "origin": {"url": _URL, "ref": "main"},
                        "defaults": {
                            "artifact_version": "1.0.0",
                            "profiles": ["tabnine"],
                            "platforms": ["darwin"],
                            "scopes": ["project"],
                            "modes": ["copy"],
                        },
                        "artifacts": [
                            {
                                "accept": True,
                                "kind": "memory",
                                "name": "one",
                                "path": "docs/one.md",
                                "summary": "First shared memory.",
                            },
                            {
                                "accept": True,
                                "kind": "memory",
                                "name": "two",
                                "path": "docs/two.md",
                                "summary": "Second shared memory.",
                            },
                            {
                                "accept": False,
                                "kind": "memory",
                                "name": "ignored",
                                "path": "does-not-exist.md",
                                "summary": "Rejected candidate.",
                            },
                        ],
                    }
                )
            )
            calls: list[tuple[str, str]] = []

            def acquire(url: str, ref: str):
                calls.append((url, ref))
                return Ok(acquisition)

            service = LocalCurationService(str(root), native_acquirer=acquire)
            with patch(
                "agent_artifacts.commands.registry.load_local_curation_service",
                return_value=Ok(service),
            ):
                code, output = _run(
                    "registry",
                    "vendor-batch",
                    "--source",
                    str(root),
                    "--manifest",
                    str(manifest),
                    "--yes",
                    "--json",
                )

            self.assertEqual(code, 0, output)
            self.assertEqual(calls, [(_URL, "main")])
            result = json.loads(output)
            self.assertEqual(result["review"]["operation"], "registry.vendor-batch")
            self.assertIn("plans 2 owned copies", " ".join(result["review"]["warnings"]))
            self.assertEqual((root / "artifacts/memory/one/payload/one.md").read_text(), "# One\n")
            self.assertEqual((root / "artifacts/memory/two/payload/two.md").read_text(), "# Two\n")
            self.assertFalse((root / "artifacts/memory/ignored").exists())

    def test_a_manifest_with_no_accepted_candidates_refuses_without_acquiring(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "registry"
            root.mkdir()
            _init_registry(root)
            manifest = Path(temporary) / "vendors.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "origin": {"url": _URL, "ref": "main"},
                        "artifacts": [
                            {
                                "accept": False,
                                "kind": "memory",
                                "name": "one",
                                "path": "docs/one.md",
                                "summary": "First shared memory.",
                            }
                        ],
                    }
                )
            )
            calls = 0

            def acquire(_url: str, _ref: str):
                nonlocal calls
                calls += 1
                raise AssertionError("rejected manifests must not acquire upstream")

            service = LocalCurationService(str(root), native_acquirer=acquire)
            with patch(
                "agent_artifacts.commands.registry.load_local_curation_service",
                return_value=Ok(service),
            ):
                code, output = _run(
                    "registry",
                    "vendor-batch",
                    "--source",
                    str(root),
                    "--manifest",
                    str(manifest),
                    "--yes",
                )

            self.assertEqual(code, 1)
            self.assertIn("no accepted artifacts", output)
            self.assertEqual(calls, 0)


if __name__ == "__main__":
    unittest.main()
