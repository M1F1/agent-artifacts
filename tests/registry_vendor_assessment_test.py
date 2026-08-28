"""VN-4: the assessment is part of the review, and is committed with the copy.

Vendoring is the moment somebody else's bytes become this registry's responsibility, so the review
that authorises it has to say what is in them. The baseline runs over the *projected package* — the
copied payload and the maintainer's own wrapper in one object — because a scan that exempts the
wrapper would miss the file most likely to run something (design §3).

Nothing here is a verdict. A completed assessment that reports three findings has done its job; the
maintainer decides. These tests hold the rendering to that: the findings are legible, the framing is
the `security` command's own, and no surface calls the result safe.
"""

from __future__ import annotations

import contextlib
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_artifacts.domain.result import Ok
from agent_artifacts.protocol.native_tree import SnapshotEntry, SnapshotEntryKind, SourceSnapshot
from agent_artifacts.registry_maintenance.model import NativeReferenceAcquisition
from agent_artifacts.security.attestation_schema import parse_attestation
from agent_artifacts.security.attestations import AttestationOriginKind, attestation_digest
from tests.credential_fixtures import access_token
from tests.registry_vendor_command_test import (
    _ACQUISITION,
    _MCP_JSON,
    _PACKAGE,
    _run,
    _vendor_command,
)
from tests.registry_vendoring_projection_test import (
    _COMMIT,
    _URL,
    _foreign_repository,
    _path,
)
from tests.setup_fixtures import recipe

# A leaked personal-access-token literal, committed upstream exactly as they are in the wild.
_LEAKED = ("export const token" + ' = "' + access_token() + '";\n').encode("utf-8")
_PIPED = (
    b"#!/bin/sh\n# AART manual setup: see ../SETUP.md\ncurl https://example.com/setup.sh | sh\n"
)
_RECIPE = recipe(
    capabilities=["keychain", "filesystem", "custom-code", "process"],
    custom_entrypoint="install.sh",
)
_UNPINNED = b"#!/bin/sh\npip install requests\nexit 0\n"


def _file(raw: str, content: bytes, *, executable: bool = False) -> SnapshotEntry:
    return SnapshotEntry(_path(raw), SnapshotEntryKind.FILE, content, executable)


class VendorAssessmentTest(unittest.TestCase):
    @contextlib.contextmanager
    def _registry(
        self,
        snapshot: SourceSnapshot | None = None,
        *,
        authored: tuple[tuple[str, bytes], ...] = (),
    ):
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
            for relative, content in ((f"{_PACKAGE}/payload/mcp.json", _MCP_JSON), *authored):
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
                if relative.endswith(".sh"):
                    target.chmod(0o755)
            acquisition = (
                _ACQUISITION
                if snapshot is None
                else NativeReferenceAcquisition(_URL, "v1.4.0", _COMMIT, snapshot)
            )
            from agent_artifacts.curation.runtime import LocalCurationService

            service = LocalCurationService(
                str(root), native_acquirer=lambda _url, _ref: Ok(acquisition)
            )
            with patch(
                "agent_artifacts.commands.registry.load_local_curation_service",
                return_value=Ok(service),
            ):
                yield root

    def _assessment_details(self, output: str) -> list[str]:
        checks = json.loads(output)["checks"]
        return next(item["details"] for item in checks if item["name"] == "vendor-assessment")

    def test_the_maintainers_own_wrapper_is_assessed_not_only_the_copied_payload(self) -> None:
        """The wrapper is the half AART's own users run first; exempting it would be the bug."""

        authored = (
            (f"{_PACKAGE}/setup/installer.json", _RECIPE),
            (f"{_PACKAGE}/setup/install.sh", _PIPED),
            (f"{_PACKAGE}/SETUP.md", b"# Setup\n\nRun the reviewed installer.\n"),
        )
        with self._registry(authored=authored) as root:
            code, output = _run(
                *_vendor_command(root, "--setup-recipe", "setup/installer.json", "--json")
            )

            self.assertEqual(code, 0, output)
            details = self._assessment_details(output)
            piped = [item for item in details if item.startswith("shell-pipe-to-interpreter")]
            self.assertEqual(len(piped), 1, details)
            self.assertIn("setup/install.sh", piped[0])

    def test_a_credential_committed_upstream_is_reported_before_it_is_copied(self) -> None:
        planted = _foreign_repository(_file("servers/atlassian/lib/token.js", _LEAKED))

        with self._registry(planted) as root:
            code, output = _run(*_vendor_command(root, "--json"))

            self.assertEqual(code, 0, output)
            details = self._assessment_details(output)
            leaked = [item for item in details if item.startswith("embedded-credential")]
            self.assertEqual(len(leaked), 1, details)
            self.assertIn("payload/lib/token.js", leaked[0])
            self.assertIn("installation risk: critical", details)

    def test_an_unpinned_install_in_the_copied_payload_is_reported(self) -> None:
        planted = _foreign_repository(
            _file("servers/atlassian/bootstrap.sh", _UNPINNED, executable=True)
        )

        with self._registry(planted) as root:
            code, output = _run(*_vendor_command(root, "--json"))

            self.assertEqual(code, 0, output)
            details = self._assessment_details(output)
            unpinned = [item for item in details if item.startswith("unpinned-package-install")]
            self.assertEqual(len(unpinned), 1, details)
            self.assertIn("payload/bootstrap.sh", unpinned[0])

    def test_findings_do_not_refuse_the_vendor_they_inform_the_maintainer(self) -> None:
        """A finding is evidence, not a veto: the reviewer decides, and the check still passed."""

        planted = _foreign_repository(_file("servers/atlassian/lib/token.js", _LEAKED))

        with self._registry(planted) as root:
            code, output = _run(*_vendor_command(root, "--yes", "--json"))

            self.assertEqual(code, 0, output)
            finalized = json.loads(output)
            self.assertEqual(finalized["outcome"]["status"], "succeeded")
            check = next(
                item
                for item in finalized["review"]["checks"]
                if item["name"] == "vendor-assessment"
            )
            self.assertTrue(check["passed"])
            self.assertTrue((root / _PACKAGE / "payload/lib/token.js").is_file())

    def test_the_rendered_review_claims_nothing_about_safety(self) -> None:
        """Plan VN-4: no surface says verified, trusted, or safe — in text or in JSON."""

        planted = _foreign_repository(_file("servers/atlassian/lib/token.js", _LEAKED))

        with self._registry(planted) as root:
            code, text = _run(*_vendor_command(root))
            self.assertEqual(code, 0, text)
            _code, data = _run(*_vendor_command(root, "--json"))

            claim = re.compile(r"(?i)\b(safe|verified|trusted|secure|vetted)\b")
            self.assertIsNone(claim.search(text), text)
            self.assertIsNone(claim.search(data), data)
            self.assertIn("Assessments reduce uncertainty; they are not safety guarantees.", text)

    def test_the_evidence_the_reviewer_read_is_committed_with_the_package(self) -> None:
        """A second reviewer sees what the first saw, bound to the digest it describes."""

        planted = _foreign_repository(_file("servers/atlassian/lib/token.js", _LEAKED))

        with self._registry(planted) as root:
            code, output = _run(*_vendor_command(root, "--yes", "--json"))
            self.assertEqual(code, 0, output)

            documents = sorted((root / "security/attestations").glob("*.json"))
            self.assertEqual(len(documents), 1)
            parsed = parse_attestation(documents[0].read_bytes())
            self.assertIsInstance(parsed, Ok)
            attestation = parsed.value
            # The name is the digest of the evidence, so a rewritten document stops resolving.
            self.assertEqual(f"{attestation_digest(attestation).value}.json", documents[0].name)
            self.assertIs(attestation.origin.kind, AttestationOriginKind.LOCAL)
            self.assertEqual(
                {item.rule_id for item in attestation.assessment.findings}
                & {"embedded-credential"},
                {"embedded-credential"},
            )
            rendered = self._assessment_details(json.dumps(json.loads(output)["review"]))
            self.assertIn(f"findings: {len(attestation.assessment.findings)}", rendered)

    def test_the_committed_evidence_leaves_the_registry_inputs_alone(self) -> None:
        """`security/` is not a registry input, so evidence cannot make the lock read as stale."""

        with self._registry() as root:
            self.assertEqual(_run(*_vendor_command(root, "--yes"))[0], 0)
            for arguments in (("lock", "--yes"), ("build", "--yes")):
                code, output = _run("registry", *arguments, "--source", str(root))
                self.assertEqual(code, 0, output)

            before = (root / "aart.lock.json").read_bytes()
            (root / "security/attestations/deadbeef.json").write_bytes(b"{}\n")
            code, output = _run("registry", "lock", "--source", str(root), "--yes")

            self.assertEqual(code, 0, output)
            self.assertEqual((root / "aart.lock.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
