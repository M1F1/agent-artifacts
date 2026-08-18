"""The text front-end vendors exactly what the flags vendor (VN-9)."""

from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest import mock

from agent_artifacts import cli, tui
from agent_artifacts.curation.model import (
    CurationAction,
    CurationChange,
    CurationCheck,
    CurationReview,
)
from agent_artifacts.curation.runtime import PreparedCuration
from agent_artifacts.domain.identifiers import ObjectDigest
from agent_artifacts.domain.result import Ok
from agent_artifacts.protocol.native_tree import SnapshotOrigin, SourceSnapshot

URL = "https://github.com/example/atlassian-mcp.git"
ASSESSMENT = CurationCheck(
    "vendor-assessment",
    True,
    (
        "installation risk: critical",
        "findings: 1",
        "shell-pipe-to-interpreter (critical): Shell content pipes downloaded bytes directly "
        "to an interpreter. [payload/install.sh]",
    ),
)


def _action_number(name: str) -> str:
    return str([action for action, _label in tui.CANONICAL_MAINTAINER_ACTIONS].index(name) + 1)


def _scripted(values):
    answers = iter(values)

    def read(_prompt: str = "") -> str:
        return next(answers)

    return read


class _Service:
    """Capture the request each front-end builds; render one review with an assessment."""

    def __init__(self) -> None:
        self.prepared = []

    def prepare(self, request):
        self.prepared.append(request)
        review = CurationReview(
            request.action,
            request.workspace,
            True,
            ObjectDigest("sha256", "a" * 64),
            ObjectDigest("sha256", "b" * 64),
            (CurationChange("artifacts/mcp/atlassian/artifact.json", "added"),),
            checks=(ASSESSMENT,),
            warnings=("Assessments reduce uncertainty; they are not safety guarantees.",),
        )
        return Ok(PreparedCuration(review, SourceSnapshot(SnapshotOrigin.LOCAL, ())))

    def finalize(self, prepared, reviewed_digest):  # pragma: no cover - not reached here
        raise AssertionError("this test never finalizes")


def _wizard(root: Path, answers, service):
    writes: list[str] = []
    with mock.patch.object(tui, "_is_canonical_maintainer_workspace", return_value=True):
        code = tui._run_text(
            _scripted(answers),
            writes.append,
            source_dir=str(root),
            curation_service_factory=lambda _root: Ok(service),
        )
    return code, writes


def _flags(root: Path, arguments, service):
    output = io.StringIO()
    with (
        redirect_stdout(output),
        mock.patch(
            "agent_artifacts.commands.registry.load_local_curation_service",
            return_value=Ok(service),
        ),
    ):
        cli.main([*arguments, "--source", str(root)])
    return output.getvalue()


class VendorFrontEndParityTest(unittest.TestCase):
    def test_collection_wizard_and_flags_build_the_same_request(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "registry"
            root.mkdir()
            wizard_service = _Service()
            _wizard(
                root,
                [
                    "",
                    "2",
                    _action_number("collection"),
                    "platform-baseline",
                    "What every project receives.",
                    "skill/review,guideline/branching",
                    "quit",
                    "y",
                ],
                wizard_service,
            )
            flag_service = _Service()
            _flags(
                root,
                [
                    "registry",
                    "collection",
                    "platform-baseline",
                    "--summary",
                    "What every project receives.",
                    "--include",
                    "skill/review",
                    "--include",
                    "guideline/branching",
                ],
                flag_service,
            )

            self.assertEqual(len(wizard_service.prepared), 1)
            self.assertEqual(len(flag_service.prepared), 1)
            self.assertEqual(wizard_service.prepared[0], flag_service.prepared[0])
            self.assertIs(wizard_service.prepared[0].action, CurationAction.COLLECTION)

    def test_the_wizard_builds_the_request_the_flags_build(self) -> None:
        # One fixture, two front-ends. The wizard is a way of stating the same action, not a
        # second definition of what vendoring means.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "registry"
            root.mkdir()
            wizard_service = _Service()
            _wizard(
                root,
                [
                    "",
                    "2",
                    _action_number("vendor"),
                    "mcp",
                    "atlassian",
                    URL,
                    "v1.4.0",
                    "packages/atlassian-mcp",
                    "Atlassian MCP server, vendored from upstream.",
                    "1.0.0",
                    "MIT",
                    "setup/installer.json",
                    "claude",
                    "darwin",
                    "",
                    "",
                    "quit",
                    "y",
                ],
                wizard_service,
            )
            flag_service = _Service()
            _flags(
                root,
                [
                    "registry",
                    "vendor",
                    "mcp",
                    "atlassian",
                    "--url",
                    URL,
                    "--ref",
                    "v1.4.0",
                    "--path",
                    "packages/atlassian-mcp",
                    "--artifact-version",
                    "1.0.0",
                    "--summary",
                    "Atlassian MCP server, vendored from upstream.",
                    "--profile",
                    "claude",
                    "--platform",
                    "darwin",
                    "--license",
                    "MIT",
                    "--setup-recipe",
                    "setup/installer.json",
                ],
                flag_service,
            )

            self.assertEqual(len(wizard_service.prepared), 1)
            self.assertEqual(len(flag_service.prepared), 1)
            # `minimum_version`/`maximum_version` are `registry init`'s source-compatibility
            # bounds. No other action reads them, and flag mode stamps its own fallback on every
            # request; comparing them would compare a value neither front-end is stating.
            self.assertEqual(
                replace(wizard_service.prepared[0], minimum_version="", maximum_version=""),
                replace(flag_service.prepared[0], minimum_version="", maximum_version=""),
            )
            self.assertEqual(wizard_service.prepared[0].action, CurationAction.VENDOR)
            self.assertEqual(wizard_service.prepared[0].workspace, os.path.abspath(str(root)))

    def test_the_wizard_review_shows_the_assessment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "registry"
            root.mkdir()
            service = _Service()
            _code, writes = _wizard(
                root,
                [
                    "",
                    "2",
                    _action_number("vendor"),
                    "mcp",
                    "atlassian",
                    URL,
                    "v1.4.0",
                    "packages/atlassian-mcp",
                    "Atlassian MCP server, vendored from upstream.",
                    "1.0.0",
                    "",
                    "",
                    "claude",
                    "darwin",
                    "",
                    "",
                    "quit",
                    "y",
                ],
                service,
            )
            rendered = "\n".join(writes)

            self.assertIn("check vendor-assessment", rendered)
            self.assertIn("installation risk: critical", rendered)
            self.assertIn("shell-pipe-to-interpreter (critical)", rendered)
            self.assertIn("not safety guarantees", rendered)

    def test_an_unstated_revendor_version_stays_unstated_in_the_wizard(self) -> None:
        # Blank is an answer here, not a gap: it is how the wizard says what omitting
        # `--artifact-version` says, and a default would answer the question the command asks.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "registry"
            root.mkdir()
            service = _Service()
            _wizard(
                root,
                [
                    "",
                    "2",
                    _action_number("revendor"),
                    "mcp",
                    "atlassian",
                    "",
                    "quit",
                    "y",
                ],
                service,
            )

            self.assertEqual(len(service.prepared), 1)
            self.assertEqual(service.prepared[0].action, CurationAction.REVENDOR)
            self.assertIsNone(service.prepared[0].artifact_version)


if __name__ == "__main__":
    unittest.main()
