"""VN-5: a vendored copy does not go stale in silence, and cannot claim it is current.

A pin cannot rot; a copy can (design §6). `revendor` re-resolves the ref the copy was taken at and
answers with one of three dispositions. The load-bearing one is `unreachable`: a maintainer who has
lost access to an upstream must be told that, and never told their copy is fine — so these tests
check the exit code and the rendered check, not only the returned value.

The other half is design §4. Upstream declares no version AART can trust, so a moved upstream is
reported with its file-level diff and planned only once the maintainer states the version that
movement deserves. Nothing here derives one.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_artifacts import cli
from agent_artifacts.curation.runtime import LocalCurationService
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.protocol.native_tree import (
    SnapshotEntry,
    SnapshotEntryKind,
    SnapshotOrigin,
    SourceSnapshot,
)
from agent_artifacts.registry_maintenance.model import NativeReferenceAcquisition
from tests.registry_vendoring_projection_test import (
    _COMMIT,
    _MCP_JSON,
    _URL,
    _file,
    _foreign_repository,
    _path,
)

_PACKAGE = "artifacts/mcp/atlassian"
_MOVED_COMMIT = "a" * 40


def _run(*arguments: str) -> tuple[int, str]:
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = cli.main(list(arguments))
    return code, output.getvalue()


def _moved_repository() -> SourceSnapshot:
    """Upstream after a release: one file rewritten, one added, one deleted."""

    return SourceSnapshot(
        SnapshotOrigin.IMMUTABLE_GIT,
        (
            _file("README.md", b"# upstream\n"),
            SnapshotEntry(_path("servers"), SnapshotEntryKind.DIRECTORY),
            SnapshotEntry(_path("servers/atlassian"), SnapshotEntryKind.DIRECTORY),
            _file("servers/atlassian/index.js", b"console.log('serve v2');\n"),
            _file("servers/atlassian/install.sh", b"#!/bin/sh\nexit 0\n", executable=True),
            _file("servers/atlassian/CHANGELOG.md", b"# 2.0\n"),
        ),
    )


def _checks(payload: dict) -> dict[str, dict]:
    review = payload.get("review", payload)
    return {item["name"]: item for item in review["checks"]}


class RevendorTest(unittest.TestCase):
    """Every test drives the real CLI over a checkout holding one vendored package."""

    @contextlib.contextmanager
    def _registry(self, upstream: SourceSnapshot | None = None, *, commit: str = _MOVED_COMMIT):
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
            original = LocalCurationService(
                str(root),
                native_acquirer=lambda _url, _ref: Ok(
                    NativeReferenceAcquisition(_URL, "v1.4.0", _COMMIT, _foreign_repository())
                ),
            )
            with patch(
                "agent_artifacts.commands.registry.load_local_curation_service",
                return_value=Ok(original),
            ):
                code, output = _run(
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
                    "servers/atlassian",
                    "--artifact-version",
                    "1.0.0",
                    "--summary",
                    "Atlassian MCP server, vendored from upstream.",
                    "--profile",
                    "claude",
                    "--platform",
                    "darwin",
                    "--yes",
                )
                self.assertEqual(code, 0, output)
            acquirer = (
                (
                    lambda _url, _ref: Err(
                        (
                            Diagnostic(
                                DiagnosticCode("source-invalid"),
                                Severity.ERROR,
                                "cannot reach origin",
                            ),
                        )
                    )
                )
                if upstream is None
                else (
                    lambda _url, _ref: Ok(
                        NativeReferenceAcquisition(_URL, "v1.4.0", commit, upstream)
                    )
                )
            )
            service = LocalCurationService(str(root), native_acquirer=acquirer)
            with patch(
                "agent_artifacts.commands.registry.load_local_curation_service",
                return_value=Ok(service),
            ):
                yield root

    def test_an_unmoved_upstream_is_up_to_date_and_writes_nothing(self) -> None:
        with self._registry(_foreign_repository(), commit=_COMMIT) as root:
            before = (root / _PACKAGE / "provenance.json").read_bytes()

            code, output = _run(
                "registry", "revendor", "--source", str(root), "mcp", "atlassian", "--yes", "--json"
            )

            self.assertEqual(code, 0, output)
            drift = _checks(json.loads(output))["vendor-drift"]
            self.assertTrue(drift["passed"])
            self.assertIn("disposition: up-to-date", drift["details"])
            self.assertEqual((root / _PACKAGE / "provenance.json").read_bytes(), before)

    def test_an_unmoved_ref_that_advanced_elsewhere_is_still_up_to_date(self) -> None:
        """The subtree is what this registry ships; the rest of the repository is not."""

        with self._registry(_foreign_repository(), commit=_MOVED_COMMIT) as root:
            code, output = _run(
                "registry", "revendor", "--source", str(root), "mcp", "atlassian", "--json"
            )

            self.assertEqual(code, 0, output)
            self.assertIn(
                "disposition: up-to-date", _checks(json.loads(output))["vendor-drift"]["details"]
            )
            recorded = json.loads((root / _PACKAGE / "provenance.json").read_text())
            self.assertEqual(recorded["origin"]["resolved_commit"], _COMMIT)

    def test_a_moved_upstream_reports_the_counts_and_refuses_without_a_version(self) -> None:
        with self._registry(_moved_repository()) as root:
            before = (root / _PACKAGE / "payload/index.js").read_bytes()

            code, output = _run(
                "registry", "revendor", "--source", str(root), "mcp", "atlassian", "--yes", "--json"
            )

            self.assertEqual(code, 1, output)
            drift = _checks(json.loads(output))["vendor-drift"]
            self.assertFalse(drift["passed"])
            self.assertIn("disposition: changed", drift["details"])
            self.assertIn("upstream files added: 1", drift["details"])
            self.assertIn("upstream files changed: 1", drift["details"])
            self.assertIn("upstream files removed: 1", drift["details"])
            self.assertEqual((root / _PACKAGE / "payload/index.js").read_bytes(), before)

    def test_a_stated_version_applies_the_movement_including_the_deletion(self) -> None:
        with self._registry(_moved_repository()) as root:
            code, output = _run(
                "registry",
                "revendor",
                "--source",
                str(root),
                "mcp",
                "atlassian",
                "--artifact-version",
                "2.0.0",
                "--yes",
                "--json",
            )

            self.assertEqual(code, 0, output)
            self.assertEqual(json.loads(output)["outcome"]["status"], "succeeded")
            self.assertEqual(
                (root / _PACKAGE / "payload/index.js").read_bytes(), b"console.log('serve v2');\n"
            )
            self.assertTrue((root / _PACKAGE / "payload/CHANGELOG.md").is_file())
            # Upstream deleted it, so the copy no longer ships it.
            self.assertFalse((root / _PACKAGE / "payload/lib/client.js").exists())
            manifest = json.loads((root / _PACKAGE / "artifact.json").read_text())
            self.assertEqual(manifest["version"], "2.0.0")
            provenance = json.loads((root / _PACKAGE / "provenance.json").read_text())
            self.assertEqual(provenance["origin"]["resolved_commit"], _MOVED_COMMIT)

    def test_the_maintainers_authored_wrapper_survives_the_re_vendor(self) -> None:
        """It is not upstream's, so an upstream deletion sweep must not take it."""

        with self._registry(_moved_repository()) as root:
            self.assertEqual(
                _run(
                    "registry",
                    "revendor",
                    "--source",
                    str(root),
                    "mcp",
                    "atlassian",
                    "--artifact-version",
                    "2.0.0",
                    "--yes",
                )[0],
                0,
            )

            self.assertEqual((root / _PACKAGE / "payload/mcp.json").read_bytes(), _MCP_JSON)

    def test_an_unreachable_origin_is_reported_as_unreachable_and_changes_nothing(self) -> None:
        with self._registry(None) as root:
            before = (root / _PACKAGE / "provenance.json").read_bytes()

            code, output = _run(
                "registry", "revendor", "--source", str(root), "mcp", "atlassian", "--yes", "--json"
            )

            self.assertEqual(code, 1, output)
            payload = json.loads(output)
            drift = _checks(payload)["vendor-drift"]
            self.assertFalse(drift["passed"])
            self.assertIn("disposition: unreachable", drift["details"])
            self.assertNotIn("disposition: up-to-date", drift["details"])
            self.assertIn(
                "An unreachable upstream is not an up-to-date copy; nothing was compared.",
                payload["review"]["warnings"],
            )
            self.assertEqual((root / _PACKAGE / "provenance.json").read_bytes(), before)

    def test_check_mode_exits_non_zero_for_an_unreachable_upstream(self) -> None:
        """`--check` is what CI runs; writing nothing must not read as being current."""

        with self._registry(None) as root:
            self.assertEqual(
                _run("registry", "revendor", "--source", str(root), "mcp", "atlassian", "--check")[
                    0
                ],
                1,
            )

    def test_re_vendoring_at_the_recorded_commit_reproduces_the_recorded_input_digest(self) -> None:
        """Design acceptance 11: the same upstream state produces the same acquisition evidence."""

        with self._registry(_foreign_repository(), commit=_COMMIT) as root:
            recorded = json.loads((root / _PACKAGE / "provenance.json").read_text())

            code, output = _run(
                "registry", "revendor", "--source", str(root), "mcp", "atlassian", "--json"
            )

            self.assertEqual(code, 0, output)
            self.assertIn(
                "disposition: up-to-date", _checks(json.loads(output))["vendor-drift"]["details"]
            )
            after = json.loads((root / _PACKAGE / "provenance.json").read_text())
            self.assertEqual(after["origin"]["input_digest"], recorded["origin"]["input_digest"])

    def test_the_review_shows_the_assessment_of_the_bytes_it_would_write(self) -> None:
        with self._registry(_moved_repository()) as root:
            _code, output = _run(
                "registry",
                "revendor",
                "--source",
                str(root),
                "mcp",
                "atlassian",
                "--artifact-version",
                "2.0.0",
                "--json",
            )

            checks = _checks(json.loads(output))
            self.assertIn("vendor-assessment", checks)
            warnings = " ".join(json.loads(output)["warnings"])
            self.assertIn("not a safety claim", warnings)
            self.assertIsNone(
                re.search(r"\b(safe|verified|trusted|secure|vetted)\b", warnings), warnings
            )

    def test_a_hand_edited_ref_is_refused_by_the_recorded_options_digest(self) -> None:
        with self._registry(_foreign_repository(), commit=_COMMIT) as root:
            document = root / _PACKAGE / "provenance.json"
            recorded = json.loads(document.read_text())
            recorded["aart.vendor"]["ref"] = "main"
            document.write_text(json.dumps(recorded) + "\n")

            code, output = _run(
                "registry", "revendor", "--source", str(root), "mcp", "atlassian", "--yes"
            )

            self.assertEqual(code, 1)
            self.assertIn("options digest", output)

    def test_a_package_that_was_never_vendored_is_refused_naming_refresh_native(self) -> None:
        with self._registry(_foreign_repository(), commit=_COMMIT) as root:
            (root / _PACKAGE / "provenance.json").unlink()

            code, output = _run("registry", "revendor", "--source", str(root), "mcp", "atlassian")

            self.assertEqual(code, 1)
            self.assertIn("refresh-native", output)


if __name__ == "__main__":
    unittest.main()
