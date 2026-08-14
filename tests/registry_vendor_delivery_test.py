"""VI-4: the review says what a consumer receives, and refuses a config that cannot run.

`LAF-46`: installing a vendored `mcp` wrote exactly one thing — the server entry merged into
`.mcp.json`. The copied payload stayed in the registry, so a descriptor whose command names a file
inside the payload names a file that will never be on the consumer's machine. The `2.3.0` tutorial
shipped exactly such an example.

`mcp` is the only type where the copied set and the delivered set differ, so it is the only type
with a finding here; the tests hold that boundary in both directions.
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
from agent_artifacts.domain.result import Ok
from agent_artifacts.registry_maintenance.model import NativeReferenceAcquisition
from agent_artifacts.registry_maintenance.vendoring import (
    delivery_reference_message,
    describe_delivery,
    mcp_descriptor_message,
)
from tests.registry_vendoring_projection_test import _COMMIT, _URL, _foreign_repository

_PACKAGE = "artifacts/mcp/atlassian"


def _descriptor(command: str, *arguments: str) -> bytes:
    return (
        json.dumps(
            {"name": "atlassian", "server": {"command": command, "args": list(arguments)}}
        ).encode()
        + b"\n"
    )


def _payload(document: bytes) -> dict[str, bytes]:
    """The copied subtree as it sits in the package, with the maintainer's descriptor beside it."""

    return {
        "payload/mcp.json": document,
        "payload/index.js": b"console.log('serve');\n",
        "payload/install.sh": b"#!/bin/sh\nexit 0\n",
        "payload/lib/client.js": b"export const client = 1;\n",
    }


def _run(*arguments: str) -> tuple[int, str]:
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = cli.main(list(arguments))
    return code, output.getvalue()


def _checks(payload: dict) -> dict[str, dict]:
    review = payload.get("review", payload)
    return {item["name"]: item for item in review["checks"]}


class DeliveryDescriptionTest(unittest.TestCase):
    def test_a_command_naming_a_copied_file_is_reported(self) -> None:
        finding = describe_delivery("mcp", _payload(_descriptor("node", "payload/index.js")))
        assert finding is not None
        self.assertEqual(finding.referenced, ("payload/index.js",))
        self.assertEqual(finding.withheld, 3)

    def test_a_payload_relative_path_counts_too(self) -> None:
        """`node index.js` names the same file as `node payload/index.js` and works no better."""

        finding = describe_delivery("mcp", _payload(_descriptor("node", "./index.js")))
        assert finding is not None
        self.assertEqual(finding.referenced, ("./index.js",))

    def test_a_command_the_consumer_resolves_is_not_a_finding(self) -> None:
        finding = describe_delivery("mcp", _payload(_descriptor("npx", "-y", "@example/srv")))
        assert finding is not None
        self.assertEqual(finding.referenced, ())
        self.assertIn("copies nothing", finding.note)

    def test_a_path_that_is_not_in_the_payload_is_not_a_finding(self) -> None:
        """Narrow by construction: refusing anything path-shaped would refuse for a guess."""

        finding = describe_delivery("mcp", _payload(_descriptor("./scripts/run.sh")))
        assert finding is not None
        self.assertEqual(finding.referenced, ())

    def test_types_that_deliver_their_whole_payload_have_no_finding(self) -> None:
        for kind in ("skill", "guideline", "memory", "hook"):
            with self.subTest(kind=kind):
                self.assertIsNone(describe_delivery(kind, _payload(_descriptor("node"))))

    def test_a_descriptor_shaped_like_the_harness_file_starts_nothing(self) -> None:
        """VI-5: `{"mcpServers": …}` parses, loads, installs, and merges an empty entry.

        It is the shape of the file the entry is merged *into*, which is why it is the mistake
        everyone makes — this repository's own vendoring fixtures made it, and so does the `2.3.0`
        tutorial.
        """

        document = json.dumps({"mcpServers": {"atlassian": {"command": "npx"}}}).encode() + b"\n"
        finding = describe_delivery("mcp", _payload(document))
        assert finding is not None
        self.assertTrue(finding.starts_nothing)
        message = mcp_descriptor_message(ArtifactIdentity("mcp", "atlassian"))
        self.assertIn('"server"', message)

    def test_a_declared_server_is_not_reported_as_starting_nothing(self) -> None:
        finding = describe_delivery("mcp", _payload(_descriptor("npx", "-y", "@example/srv")))
        assert finding is not None
        self.assertFalse(finding.starts_nothing)

    def test_an_empty_server_object_starts_nothing_too(self) -> None:
        document = json.dumps({"name": "atlassian", "server": {}}).encode() + b"\n"
        finding = describe_delivery("mcp", _payload(document))
        assert finding is not None
        self.assertTrue(finding.starts_nothing)

    def test_the_message_names_the_command_and_what_is_actually_installed(self) -> None:
        finding = describe_delivery("mcp", _payload(_descriptor("node", "payload/index.js")))
        assert finding is not None
        message = delivery_reference_message(ArtifactIdentity("mcp", "atlassian"), finding)
        self.assertIn("payload/index.js", message)
        self.assertIn("only the server entry from payload/mcp.json", message)


class VendorDeliveryReviewTest(unittest.TestCase):
    """The real CLI, vendoring one MCP server with the descriptor the maintainer authored."""

    @contextlib.contextmanager
    def _vendored(self, document: bytes):
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
            descriptor = root / _PACKAGE / "payload/mcp.json"
            descriptor.parent.mkdir(parents=True)
            descriptor.write_bytes(document)
            service = LocalCurationService(
                str(root),
                native_acquirer=lambda _url, _ref: Ok(
                    NativeReferenceAcquisition(_URL, "v1.4.0", _COMMIT, _foreign_repository())
                ),
            )
            with patch(
                "agent_artifacts.commands.registry.load_local_curation_service",
                return_value=Ok(service),
            ):
                yield root

    def _vendor(self, root: Path) -> tuple[int, str]:
        return _run(
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
            "--license",
            "MIT",
            "--yes",
            "--json",
        )

    def test_a_descriptor_launching_a_copied_file_fails_the_delivery_check(self) -> None:
        with self._vendored(_descriptor("node", "payload/index.js")) as root:
            _code, output = self._vendor(root)

            delivery = _checks(json.loads(output))["vendor-delivery"]
            self.assertFalse(delivery["passed"])
            self.assertIn(
                "descriptor names a withheld payload file: payload/index.js", delivery["details"]
            )

    def test_the_check_states_what_is_installed_and_what_the_assessment_covered(self) -> None:
        with self._vendored(_descriptor("npx", "-y", "@example/srv")) as root:
            _code, output = self._vendor(root)

            delivery = _checks(json.loads(output))["vendor-delivery"]
            self.assertTrue(delivery["passed"], delivery)
            rendered = " ".join(delivery["details"])
            self.assertIn("merges the server entry from payload/mcp.json", rendered)
            self.assertIn("3 copied payload files are not delivered", rendered)
            self.assertIn("no consumer of this artifact receives", rendered)

    def test_audit_reports_the_same_condition_and_fails(self) -> None:
        with self._vendored(_descriptor("node", "payload/index.js")) as root:
            self.assertEqual(self._vendor(root)[0], 0)

            code, output = _run("registry", "audit", "--source", str(root))

            self.assertEqual(code, 1, output)
            self.assertIn("names a copied payload file consumers never receive", output)

    def test_a_harness_shaped_descriptor_fails_the_review_and_the_audit(self) -> None:
        document = json.dumps({"mcpServers": {"atlassian": {"command": "npx"}}}).encode() + b"\n"
        with self._vendored(document) as root:
            _code, output = self._vendor(root)

            delivery = _checks(json.loads(output))["vendor-delivery"]
            self.assertFalse(delivery["passed"])
            self.assertIn("declares no server", " ".join(delivery["details"]))
            code, audited = _run("registry", "audit", "--source", str(root))
            self.assertEqual(code, 1, audited)
            self.assertIn("installing it writes an empty entry", audited)

    def test_audit_passes_for_a_command_the_consumer_resolves(self) -> None:
        with self._vendored(_descriptor("npx", "-y", "@example/srv")) as root:
            self.assertEqual(self._vendor(root)[0], 0)

            code, output = _run("registry", "audit", "--source", str(root))

            self.assertEqual(code, 0, output)


if __name__ == "__main__":
    unittest.main()
