"""VI-6: the documented MCP descriptor is one the checks would pass.

`LAF-46` was a tutorial teaching an example that cannot run: a command naming a file inside
`payload/`, which installation never delivers, written in the shape of the harness file rather than
the artifact (`VI-5`). Prose can be corrected once and drift back, so the example itself is fed to
`describe_delivery` here — the same function the vendor review and `registry audit` use. A tutorial
descriptor that would fail the review fails this test instead.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from agent_artifacts.registry_maintenance.vendoring import describe_delivery

_ROOT = Path(__file__).resolve().parent.parent
_TUTORIAL = _ROOT / "docs/tutorials/vendoring-v1.md"
_PROTOCOL = _ROOT / "docs/protocol/native-source-v1.md"
_FENCE = re.compile(r"^```json\n(.*?)^```", re.MULTILINE | re.DOTALL)

# The payload the tutorial's upstream produces, so a documented command naming a copied file is
# recognised as naming one.
_PAYLOAD = {
    "payload/LICENSE": b"MIT\n",
    "payload/index.js": b"console.log('serve');\n",
    "payload/install.sh": b"#!/bin/sh\nexit 0\n",
    "payload/lib/client.js": b"export const client = 1;\n",
}


def _descriptors(text: str) -> list[dict]:
    """Every JSON fence that is an `mcp` payload, by either the right shape or the wrong one."""

    found = []
    for block in _FENCE.findall(text):
        try:
            document = json.loads(block)
        except json.JSONDecodeError:
            continue  # A fence showing a fragment or an elided digest is not a descriptor.
        if isinstance(document, dict) and ("server" in document or "mcpServers" in document):
            found.append(document)
    return found


class VendoringTutorialExampleTest(unittest.TestCase):
    def test_the_tutorial_shows_at_least_one_descriptor(self) -> None:
        """Otherwise the checks below would pass by having nothing to check."""

        self.assertTrue(_descriptors(_TUTORIAL.read_text()))

    def test_every_documented_descriptor_passes_the_delivery_check(self) -> None:
        for document in _descriptors(_TUTORIAL.read_text()):
            with self.subTest(document=document):
                payload = dict(_PAYLOAD)
                payload["payload/mcp.json"] = json.dumps(document).encode() + b"\n"
                finding = describe_delivery("mcp", payload)
                assert finding is not None
                self.assertEqual(finding.referenced, ())
                self.assertFalse(finding.starts_nothing)


class DeliveryIsWrittenDownTest(unittest.TestCase):
    def test_the_protocol_tabulates_what_each_type_delivers(self) -> None:
        text = _PROTOCOL.read_text()
        self.assertIn("What installation delivers", text)
        for kind in ("skill", "guideline", "memory", "hook", "mcp"):
            with self.subTest(kind=kind):
                self.assertIn(f"| `{kind}` | ", text.split("What installation delivers", 1)[1])


if __name__ == "__main__":
    unittest.main()
