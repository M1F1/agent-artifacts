"""SBC-9: the index and the consumer must be talking about the same thing.

`LAF-51`, found by walking the guided route on a real machine: the compiled index published the
recipe's *declared* capabilities while the consumer recomputed the *policy* capabilities, and
`_prepare_setup_plan` required the two to be equal. They cannot be — `filesystem` is not
`managed-file`, `docker` is not `docker-build` — so setup planning refused every recipe beyond a
keychain-only one, in `2.4.0` and on this branch alike, and no test noticed because each side was
tested against itself.

The two vocabularies still exist and should: an author declares that a recipe touches files, an
organization decides whether it allows a managed-file write. What may not exist again is a gate that
compares one to the other.
"""

from __future__ import annotations

import unittest

from agent_artifacts.model import SetupInstaller
from agent_artifacts.setup import _CAPABILITIES, _MODULES, _PLANNED_CAPABILITIES, parse_installer
from agent_artifacts.setup_engine.application import _planned_capabilities
from tests.setup_fixtures import recipe

_EVERY_MODULE = [
    {
        "id": "certificates",
        "use": "trust-store.export-certificates@1",
        "with": {"subject_contains": "Example Corp Root", "output": "company-ca.pem"},
    },
    {"id": "image", "use": "docker.build@1", "with": {"context": "payload"}},
    {
        "id": "pull",
        "use": "docker.pull@1",
        "with": {"image": f"example.test/tool@sha256:{'a' * 64}"},
    },
    {
        "id": "token",
        "use": "macos-keychain.store@1",
        "with": {"input": "api_token", "service": "aart/mcp/atlassian", "account": "default"},
    },
    {
        "id": "shell",
        "use": "shell.env-from-keychain@1",
        "with": {
            "file": "~/.zshrc",
            "variables": {"T": {"service": "aart/mcp/atlassian", "account": "default"}},
        },
    },
    {"id": "block", "use": "file.managed-block@1", "with": {"file": "~/.config/x", "content": "y"}},
    {
        "id": "merge",
        "use": "json.managed-merge@1",
        "with": {"file": "~/.config/y.json", "path": ["a"], "value": 1},
    },
    {"id": "dir", "use": "directory.create@1", "with": {"path": "~/.config/z"}},
    {"id": "verify", "use": "command.verify@1", "with": {"argv": ["/bin/echo", "ok"]}},
    {"id": "restart", "use": "restart.notice@1", "with": {"message": "Restart the harness."}},
]


def _installer(steps: list[dict[str, object]]) -> SetupInstaller:
    outcome = parse_installer(
        recipe(
            required_tools=["docker", "/usr/bin/security"],
            capabilities=[
                "docker",
                "network",
                "process",
                "trust-store",
                "keychain",
                "filesystem",
            ],
            steps=steps,
        ),
        artifact_key="mcp/atlassian",
        descriptor_path="mcp/atlassian/setup/installer.json",
    )
    assert hasattr(outcome, "value"), getattr(outcome, "reason", "")
    return outcome.value


class OneTableDecidesWhatARecipeNeedsTest(unittest.TestCase):
    def test_every_module_says_what_it_needs(self) -> None:
        """A module added without a capability entry would silently need nothing."""

        self.assertEqual(set(_PLANNED_CAPABILITIES), set(_MODULES))

    def test_the_index_publishes_what_the_consumer_recomputes(self) -> None:
        """The gate in `_prepare_setup_plan` is only meaningful if both sides can agree."""

        from agent_artifacts.protocol.registry_index import index_artifact_from_package

        installer = _installer(_EVERY_MODULE)
        published = tuple(
            str(item) for item in _published_capabilities(index_artifact_from_package, installer)
        )
        recomputed = tuple(str(item) for item in _planned_capabilities(installer))
        self.assertEqual(published, recomputed)

    def test_the_two_vocabularies_are_different_on_purpose(self) -> None:
        """If these ever coincide, the bridge looks redundant. It is not: this is why it exists."""

        planned = {value for values in _PLANNED_CAPABILITIES.values() for value in values}
        self.assertNotEqual(planned, set(_CAPABILITIES))
        self.assertIn("filesystem", _CAPABILITIES)
        self.assertNotIn("filesystem", planned)
        self.assertIn("managed-file", planned)
        self.assertNotIn("managed-file", _CAPABILITIES)

    def test_a_build_still_declares_network_and_process(self) -> None:
        installer = _installer(
            [{"id": "image", "use": "docker.build@1", "with": {"context": "payload"}}]
        )
        self.assertEqual(
            tuple(str(item) for item in _planned_capabilities(installer)),
            ("docker-build", "network", "process"),
        )


def _published_capabilities(project, installer: SetupInstaller):
    """Project one package through the real index compiler and return its setup capabilities."""

    from dataclasses import replace

    from agent_artifacts.domain.identifiers import ObjectDigest, SourceId
    from agent_artifacts.protocol.native_schema import parse_artifact_manifest
    from agent_artifacts.protocol.native_tree import NativeArtifactPackage

    manifest = parse_artifact_manifest(
        """{
          "schema_version": 1,
          "type": "mcp",
          "name": "atlassian",
          "version": "2.1.0",
          "summary": "Connect reviewed Atlassian tools.",
          "payload": {"root": "payload", "format": "aart-mcp-v1"},
          "compatibility": {"profiles": ["claude"], "platforms": ["darwin"]},
          "install": {"scopes": ["user"], "modes": ["copy"], "effects": ["merge-json"]},
          "setup": {"recipe": "setup/installer.json", "platforms": ["darwin"]}
        }"""
    )
    assert hasattr(manifest, "value")
    digest = ObjectDigest("sha256", "1" * 64)
    package = replace(
        NativeArtifactPackage(manifest.value, None, digest, digest),
        setup_installer=installer,
    )
    record = project(package, source_id=SourceId("company-registry"), object_digest=digest)
    assert record.setup is not None
    return record.setup.capabilities


if __name__ == "__main__":
    unittest.main()
