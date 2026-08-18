"""VN-3: `registry vendor` copies a foreign subtree in, review first.

`promote-native` refuses any upstream that is not already a native AART source, which is most of
them. The same fixture proves both halves here: one repository with no markers anywhere, refused by
`promote-native` and vendored successfully — that is the whole point of the command (design §1).

The review/finalize contract is the one every other registry mutation already uses, and vendoring
adds a gate rather than relaxing one: without `--yes` nothing is written, and the plan refuses
outright without an approved review record, exactly as `plan_native_promotion` does.
"""

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
from agent_artifacts.domain.identifiers import ArtifactIdentity
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.protocol.native_tree import (
    SnapshotEntry,
    SnapshotEntryKind,
    SnapshotOrigin,
    SourceSnapshot,
)
from agent_artifacts.protocol.paths import parse_relative_path
from agent_artifacts.protocol.registry_models import ReviewRecord
from agent_artifacts.protocol.semver import SemVer
from agent_artifacts.registry_commands.planning import plan_artifact_vendor
from agent_artifacts.registry_maintenance.model import NativeReferenceAcquisition
from agent_artifacts.registry_maintenance.vendoring import VendorOptions
from tests.registry_vendoring_projection_test import (
    _COMMIT,
    _MCP_JSON,
    _URL,
    _foreign_repository,
    _path,
)

_ACQUISITION = NativeReferenceAcquisition(_URL, "v1.4.0", _COMMIT, _foreign_repository())
_PACKAGE = "artifacts/mcp/atlassian"


def _run(*arguments: str) -> tuple[int, str]:
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = cli.main(list(arguments))
    return code, output.getvalue()


def _tree_bytes(root: Path) -> tuple[tuple[str, bytes], ...]:
    return tuple(
        (path.relative_to(root).as_posix(), path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file() and ".git" not in path.relative_to(root).parts
    )


def _vendor_command(root: Path, *extra: str, path: str = "servers/atlassian") -> tuple[str, ...]:
    return (
        "registry",
        "vendor",
        "--source",
        str(root),
        "mcp",
        "atlassian",
        "--url",
        _URL,
        "--ref",
        "v1.4.0",
        "--path",
        path,
        "--artifact-version",
        "1.0.0",
        "--summary",
        "Atlassian MCP server, vendored from upstream.",
        "--profile",
        "claude",
        "--platform",
        "darwin",
        *extra,
    )


class VendorCommandTest(unittest.TestCase):
    """Every test drives the real CLI over a temporary checkout with a stubbed acquisition."""

    @contextlib.contextmanager
    def _registry(self, snapshot: SourceSnapshot | None = None, *, wrapper: bool = True):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "registry"
            root.mkdir()
            subprocess.run(
                ("git", "-C", str(root), "init", "-q"),
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
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
            self.assertEqual(code, 0, output)
            if wrapper:
                # The document the kind's payload cannot load without.  Upstream was never shaped
                # for AART, so the maintainer authors it and `vendor` adopts what it finds.
                document = root / _PACKAGE / "payload/mcp.json"
                document.parent.mkdir(parents=True)
                document.write_bytes(_MCP_JSON)
            acquisition = NativeReferenceAcquisition(
                _URL, "v1.4.0", _COMMIT, snapshot or _foreign_repository()
            )
            service = LocalCurationService(
                str(root), native_acquirer=lambda _url, _ref: Ok(acquisition)
            )
            with patch(
                "agent_artifacts.commands.registry.load_local_curation_service",
                return_value=Ok(service),
            ):
                yield root

    def test_a_review_writes_nothing_and_states_what_is_being_copied(self) -> None:
        with self._registry() as root:
            before = _tree_bytes(root)

            code, output = _run(*_vendor_command(root, "--json"))

            self.assertEqual(code, 0, output)
            review = json.loads(output)
            self.assertEqual(review["phase"], "review")
            self.assertFalse(review["applied"])
            self.assertEqual(_tree_bytes(root), before)
            self.assertFalse((root / _PACKAGE / "artifact.json").exists())
            details = next(
                item["details"] for item in review["checks"] if item["name"] == "vendor-origin"
            )
            self.assertIn(f"origin: {_URL}", details)
            self.assertIn(f"resolved commit: {_COMMIT}", details)
            self.assertIn("subtree: servers/atlassian", details)
            self.assertIn(f"target: {_PACKAGE}", details)
            self.assertIn("declared version: 1.0.0", details)

    def test_the_review_says_the_copy_is_not_a_safety_claim(self) -> None:
        """Design §3: a successful vendor means the bytes were copied and pinned, nothing more."""

        with self._registry() as root:
            _code, output = _run(*_vendor_command(root, "--json"))

            warnings = " ".join(json.loads(output)["warnings"])
            self.assertIn("not a safety claim", warnings)
            self.assertNotIn("verified", warnings)
            self.assertNotIn("trusted", warnings)

    def test_finalizing_writes_an_owned_package_that_passes_the_publisher_gates(self) -> None:
        with self._registry() as root:
            code, output = _run(*_vendor_command(root, "--yes", "--json"))
            self.assertEqual(code, 0, output)
            finalized = json.loads(output)
            self.assertEqual(finalized["outcome"]["status"], "succeeded")
            self.assertEqual(finalized["review"]["operation"], "registry.vendor")

            self.assertTrue((root / _PACKAGE / "artifact.json").is_file())
            self.assertTrue((root / _PACKAGE / "provenance.json").is_file())
            self.assertTrue((root / _PACKAGE / "payload/index.js").is_file())
            self.assertTrue((root / _PACKAGE / "payload/lib/client.js").is_file())

            for arguments in (
                ("lock", "--yes"),
                ("build", "--yes"),
                ("validate", "--strict", "--frozen", "--json"),
                ("audit", "--json"),
            ):
                code, output = _run("registry", *arguments, "--source", str(root))
                self.assertEqual(code, 0, f"registry {arguments[0]}: {output}")

    def test_the_copied_payload_keeps_its_executable_bit(self) -> None:
        with self._registry() as root:
            self.assertEqual(_run(*_vendor_command(root, "--yes"))[0], 0)

            mode = (root / _PACKAGE / "payload/install.sh").stat().st_mode
            self.assertTrue(mode & 0o111)

    def test_the_provenance_pins_the_resolved_commit_and_the_taken_path(self) -> None:
        with self._registry() as root:
            self.assertEqual(_run(*_vendor_command(root, "--yes"))[0], 0)

            provenance = json.loads((root / _PACKAGE / "provenance.json").read_text())
            self.assertEqual(provenance["origin"]["resolved_commit"], _COMMIT)
            self.assertEqual(provenance["origin"]["path"], "servers/atlassian")
            self.assertEqual(provenance["importer"]["id"], "registry-vendor-v1")

    def test_a_single_markdown_file_can_be_vendored_as_memory_with_provenance(self) -> None:
        upstream = SourceSnapshot(
            SnapshotOrigin.IMMUTABLE_GIT,
            (
                SnapshotEntry(
                    _path("CLAUDE.md"),
                    SnapshotEntryKind.FILE,
                    b"# Shared house rules\n",
                ),
            ),
        )
        with self._registry(upstream, wrapper=False) as root:
            code, output = _run(
                "registry",
                "vendor",
                "--source",
                str(root),
                "memory",
                "shared-house-rules",
                "--url",
                _URL,
                "--ref",
                "v1.4.0",
                "--path",
                "CLAUDE.md",
                "--artifact-version",
                "1.0.0",
                "--summary",
                "Shared upstream house rules.",
                "--profile",
                "tabnine",
                "--platform",
                "darwin",
                "--yes",
                "--json",
            )

            self.assertEqual(code, 0, output)
            package = root / "artifacts" / "memory" / "shared-house-rules"
            self.assertEqual(
                (package / "payload" / "CLAUDE.md").read_text(),
                "# Shared house rules\n",
            )
            provenance = json.loads((package / "provenance.json").read_text())
            self.assertEqual(provenance["origin"]["path"], "CLAUDE.md")

    def test_the_maintainers_authored_wrapper_is_adopted_rather_than_overwritten(self) -> None:
        with self._registry() as root:
            code, output = _run(*_vendor_command(root, "--yes", "--json"))

            self.assertEqual(code, 0, output)
            self.assertEqual((root / _PACKAGE / "payload/mcp.json").read_bytes(), _MCP_JSON)
            statuses = {
                item["path"]: item["status"] for item in json.loads(output)["review"]["changes"]
            }
            self.assertEqual(statuses[f"{_PACKAGE}/payload/mcp.json"], "unchanged")
            self.assertEqual(statuses[f"{_PACKAGE}/artifact.json"], "added")

    def test_without_the_kinds_document_the_vendor_refuses_naming_it(self) -> None:
        with self._registry(wrapper=False) as root:
            code, output = _run(*_vendor_command(root, "--yes"))

            self.assertEqual(code, 1)
            self.assertIn("payload/mcp.json", output)
            self.assertFalse((root / _PACKAGE / "artifact.json").exists())

    def test_a_symlink_inside_the_subtree_refuses_the_vendor(self) -> None:
        """VN-1's refusal has to reach the maintainer through the command (acceptance 7)."""

        linked = _foreign_repository(
            SnapshotEntry(
                _path("servers/atlassian/shared.js"),
                SnapshotEntryKind.SYMLINK,
                b"../other/index.js",
            )
        )

        with self._registry(linked) as root:
            code, output = _run(*_vendor_command(root, "--yes"))

            self.assertEqual(code, 1)
            self.assertIn("shared.js", output)
            self.assertFalse((root / _PACKAGE / "artifact.json").exists())

    def test_an_empty_subtree_refuses_naming_the_path(self) -> None:
        with self._registry() as root:
            code, output = _run(*_vendor_command(root, "--yes", path="servers/atlassain"))

            self.assertEqual(code, 1)
            self.assertIn("servers/atlassain", output)

    def test_vendoring_over_an_existing_package_refuses(self) -> None:
        with self._registry() as root:
            self.assertEqual(_run(*_vendor_command(root, "--yes"))[0], 0)
            before = _tree_bytes(root)

            code, output = _run(*_vendor_command(root, "--yes"))

            self.assertEqual(code, 1)
            self.assertIn("artifact package already exists: mcp/atlassian", output)
            self.assertEqual(_tree_bytes(root), before)

    def test_rs04_the_refusal_names_revendor_when_the_package_is_a_vendored_copy(self) -> None:
        """`RS-04`: `vendor` is create-only, so the maintainer who ran it wanted the other command.

        Movement is the ordinary reason to run `vendor` twice, and `revendor` is the command that
        adopts it. A refusal that stops at *already exists* leaves the operator to find that out.
        """

        with self._registry() as root:
            self.assertEqual(_run(*_vendor_command(root, "--yes"))[0], 0)

            code, output = _run(*_vendor_command(root, "--yes"))

            self.assertEqual(code, 1)
            self.assertIn("remediation:", output)
            self.assertIn("aart registry revendor mcp atlassian", output)
            # `revendor` plans nothing without the version this registry will publish, so the
            # sentence that names it has to name that too.
            self.assertIn("--artifact-version", output)

    def test_rs04_an_owned_package_is_not_sent_to_revendor(self) -> None:
        """`revendor` re-resolves a recorded upstream. An authored package has none to re-resolve."""

        # `wrapper=False`: the scaffold authors the whole package, including the descriptor the
        # other tests write by hand for `vendor` to adopt.
        with self._registry(wrapper=False) as root:
            self.assertEqual(
                _run(
                    "registry",
                    "scaffold",
                    "--source",
                    str(root),
                    "mcp",
                    "atlassian",
                    "--summary",
                    "Atlassian MCP server.",
                    "--profile",
                    "claude",
                    "--platform",
                    "darwin",
                    "--yes",
                )[0],
                0,
            )

            code, output = _run(*_vendor_command(root, "--yes"))

            self.assertEqual(code, 1)
            self.assertIn("artifact package already exists: mcp/atlassian", output)
            self.assertNotIn("revendor", output)
            self.assertIn("remediation:", output)

    def test_a_declared_setup_recipe_with_no_recipe_authored_refuses(self) -> None:
        with self._registry() as root:
            code, output = _run(
                *_vendor_command(root, "--setup-recipe", "setup/installer.json", "--yes")
            )

            self.assertEqual(code, 1)
            self.assertIn("setup/installer.json", output)

    def test_the_review_points_at_lock_and_build_before_strict_validation(self) -> None:
        """A vendored package makes the lock and index stale; `validate --strict` alone would fail."""

        with self._registry() as root:
            _code, output = _run(*_vendor_command(root, "--json"))

            follow_up = " ".join(json.loads(output)["follow_up_commands"])
            self.assertIn("registry lock", follow_up)
            self.assertIn("registry build", follow_up)


class VendorSucceedsWherePromoteNativeRefusesTest(unittest.TestCase):
    """One fixture, both halves: the upstream `promote-native` cannot use is the vendoring case."""

    def test_the_same_markerless_upstream_is_refused_by_promotion_and_vendored(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "registry"
            root.mkdir()
            subprocess.run(
                ("git", "-C", str(root), "init", "-q"),
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.assertEqual(
                _run(
                    "registry",
                    "init",
                    "--source",
                    str(root),
                    "--source-id",
                    "company-registry",
                    "--display-name",
                    "Company Registry",
                    "--yes",
                )[0],
                0,
            )
            document = root / _PACKAGE / "payload/mcp.json"
            document.parent.mkdir(parents=True)
            document.write_bytes(_MCP_JSON)
            service = LocalCurationService(
                str(root), native_acquirer=lambda _url, _ref: Ok(_ACQUISITION)
            )
            with patch(
                "agent_artifacts.commands.registry.load_local_curation_service",
                return_value=Ok(service),
            ):
                promoted, promotion_output = _run(
                    "registry",
                    "promote-native",
                    "--source",
                    str(root),
                    "mcp",
                    "atlassian",
                    "--url",
                    _URL,
                    "--path",
                    "servers/atlassian",
                    "--yes",
                )
                vendored, vendor_output = _run(*_vendor_command(root, "--yes"))

            self.assertEqual(promoted, 1, promotion_output)
            self.assertEqual(vendored, 0, vendor_output)
            self.assertTrue((root / _PACKAGE / "provenance.json").is_file())
            self.assertFalse((root / "entries/mcp/atlassian.json").exists())


class VendorRequiresAnApprovedReviewTest(unittest.TestCase):
    """The gate `plan_native_promotion` already applies, applied at the same layer."""

    def _options(self) -> VendorOptions:
        return VendorOptions(
            ArtifactIdentity("mcp", "atlassian"),
            SemVer(1, 0, 0),
            "Atlassian MCP server, vendored from upstream.",
            ("claude",),
            ("darwin",),
            ("project",),
            ("copy",),
        )

    def _snapshot(self) -> SourceSnapshot:
        source = {
            "schema_version": 1,
            "protocol_version": 1,
            "source_id": "company-registry",
            "display_name": "Company Registry",
            "requires_aart": {"min_inclusive": "1.0.0", "max_exclusive": "3.0.0"},
            "required_capabilities": ["artifact-manifest-v1"],
            "artifact_roots": ["artifacts"],
            "collection_roots": [],
        }
        parsed = parse_relative_path("aart-source.json")
        assert isinstance(parsed, Ok)
        return SourceSnapshot(
            SnapshotOrigin.LOCAL,
            (
                SnapshotEntry(
                    parsed.value, SnapshotEntryKind.FILE, json.dumps(source).encode(), False
                ),
            ),
        )

    def test_an_unapproved_review_record_refuses_before_anything_is_planned(self) -> None:
        refused = plan_artifact_vendor(
            self._snapshot(),
            _ACQUISITION,
            self._options(),
            path=_path("servers/atlassian"),
            review=ReviewRecord("pending", "manual-review-v1"),
            importer_version=SemVer(2, 3, 0),
        )

        assert isinstance(refused, Err), refused
        self.assertIn(
            "approved review record",
            "; ".join(item.message for item in refused.diagnostics),
        )


if __name__ == "__main__":
    unittest.main()
