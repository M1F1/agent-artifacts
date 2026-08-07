from __future__ import annotations

import json
import unittest

from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.protocol.registry_schema import (
    parse_registry_entry,
    parse_registry_index,
    parse_registry_lock,
    parse_registry_manifest,
)


def _document(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _digest(character: str) -> str:
    return f"sha256:{character * 64}"


def _registry_manifest() -> dict[str, object]:
    return {
        "schema_version": 1,
        "protocol_version": 1,
        "registry_id": "company-agent-artifacts",
        "display_name": "Company Agent Artifacts",
        "requires_aart": {"min_inclusive": "1.0.0", "max_exclusive": "2.0.0"},
        "required_capabilities": ["lockfile-v1", "registry-entry-v1"],
        "default_channel": "main",
        "services": {
            "usage_reporting": {
                "kind": "github-issues",
                "repository": "agents/company-agent-artifacts-registry",
            }
        },
    }


def _entry() -> dict[str, object]:
    return {
        "schema_version": 1,
        "type": "mcp",
        "name": "atlassian",
        "source": {
            "kind": "git",
            "url": "git@github.company.example:platform/atlassian-agent-tools.git",
            "ref": "main",
            "path": "artifacts/mcp/atlassian",
        },
        "review": {"status": "approved", "policy": "company-artifact-review-v1"},
    }


def _locked_entry() -> dict[str, object]:
    return {
        "origin_url": "git@github.company.example:platform/atlassian-agent-tools.git",
        "requested_ref": "main",
        "resolved_commit": "a" * 40,
        "path": "artifacts/mcp/atlassian",
        "manifest_digest": _digest("1"),
        "payload_digest": _digest("2"),
        "object_digest": _digest("3"),
        "artifact_version": "2.1.0",
        "review": {"status": "approved", "policy": "company-artifact-review-v1"},
        "provenance_digest": _digest("4"),
    }


class RegistryProtocolSchemaTest(unittest.TestCase):
    def test_registry_manifest_parses_advertised_service_without_enabling_it(self) -> None:
        result = parse_registry_manifest(_document(_registry_manifest()))

        self.assertIsInstance(result, Ok)
        assert isinstance(result, Ok)
        self.assertEqual(str(result.value.registry_id), "company-agent-artifacts")
        self.assertEqual(result.value.default_channel, "main")
        self.assertEqual(result.value.services[0].name, "usage_reporting")
        self.assertEqual(result.value.services[0].kind, "github-issues")
        self.assertEqual(
            result.value.services[0].repository,
            "agents/company-agent-artifacts-registry",
        )

    def test_registry_manifest_rejects_trust_reporting_enablement_and_credentials(self) -> None:
        cases = []
        trust = _registry_manifest()
        trust["trust"] = "trusted"
        cases.append(trust)
        enabled = _registry_manifest()
        assert isinstance(enabled["services"], dict)
        enabled["services"]["usage_reporting"]["enabled"] = True  # type: ignore[index]
        cases.append(enabled)
        credential = _registry_manifest()
        assert isinstance(credential["services"], dict)
        credential["services"]["usage_reporting"]["repository"] = (  # type: ignore[index]
            "https://token@example.test/org/repo"
        )
        cases.append(credential)

        for value in cases:
            with self.subTest(value=value):
                result = parse_registry_manifest(_document(value))
                self.assertIsInstance(result, Err)

    def test_native_git_entry_is_structured_and_identity_bound_to_path(self) -> None:
        result = parse_registry_entry(_document(_entry()))

        self.assertIsInstance(result, Ok)
        assert isinstance(result, Ok)
        self.assertEqual(str(result.value.identity), "mcp/atlassian")
        self.assertEqual(result.value.source.ref, "main")
        self.assertEqual(result.value.review.status, "approved")

        mismatch = _entry()
        assert isinstance(mismatch["source"], dict)
        mismatch["source"]["path"] = "artifacts/mcp/jira"
        self.assertIsInstance(parse_registry_entry(_document(mismatch)), Err)

    def test_entry_rejects_unsafe_refs_credentials_and_self_authored_trust(self) -> None:
        cases: list[dict[str, object]] = []
        unsafe_ref = _entry()
        assert isinstance(unsafe_ref["source"], dict)
        unsafe_ref["source"]["ref"] = "--upload-pack=evil"
        cases.append(unsafe_ref)
        credential = _entry()
        assert isinstance(credential["source"], dict)
        credential["source"]["url"] = "https://token@example.test/org/repo.git"
        cases.append(credential)
        trust = _entry()
        trust["trust"] = "trusted"
        cases.append(trust)

        for value in cases:
            with self.subTest(value=value):
                self.assertIsInstance(parse_registry_entry(_document(value)), Err)

    def test_lockfile_requires_pinned_commits_digests_and_sorted_identities(self) -> None:
        lock = {
            "schema_version": 1,
            "registry_inputs_digest": _digest("0"),
            "entries": {
                "mcp/atlassian": _locked_entry(),
                "skill/code-review": {
                    **_locked_entry(),
                    "path": "artifacts/skill/code-review",
                    "artifact_version": "1.0.0",
                },
            },
        }

        result = parse_registry_lock(_document(lock))

        self.assertIsInstance(result, Ok)
        assert isinstance(result, Ok)
        self.assertEqual(
            tuple(str(identity) for identity, _locked in result.value.entries),
            ("mcp/atlassian", "skill/code-review"),
        )

        lock["entries"]["mcp/atlassian"]["resolved_commit"] = "main"  # type: ignore[index]
        self.assertIsInstance(parse_registry_lock(_document(lock)), Err)

    def test_compiled_index_is_strict_and_contains_no_trust_or_payload_bytes(self) -> None:
        index = {
            "schema_version": 1,
            "protocol_version": 1,
            "registry_id": "company-agent-artifacts",
            "registry_inputs_digest": _digest("0"),
            "artifacts": [
                {
                    "source_id": "company-agent-artifacts",
                    "type": "mcp",
                    "name": "atlassian",
                    "version": "2.1.0",
                    "summary": "Connect reviewed Atlassian tools.",
                    "manifest_digest": _digest("1"),
                    "payload_digest": _digest("2"),
                    "object_digest": _digest("3"),
                    "compatibility": {
                        "profiles": ["claude", "tabnine"],
                        "platforms": ["darwin", "linux"],
                    },
                    "install": {
                        "scopes": ["project", "user"],
                        "modes": ["copy"],
                        "effects": ["merge-json"],
                    },
                    "setup": None,
                    "review": {
                        "status": "approved",
                        "policy": "company-artifact-review-v1",
                    },
                    "provenance": {
                        "origin_url": "git@github.company.example:platform/tools.git",
                        "resolved_commit": "a" * 40,
                        "path": "artifacts/mcp/atlassian",
                    },
                    "collections": ["essentials"],
                }
            ],
            "collections": [
                {
                    "name": "essentials",
                    "summary": "Reviewed essentials.",
                    "artifacts": [{"type": "mcp", "name": "atlassian"}],
                    "collections": [],
                }
            ],
            "services": {},
        }

        result = parse_registry_index(_document(index))
        self.assertIsInstance(result, Ok)

        index["artifacts"][0]["trust"] = "trusted"  # type: ignore[index]
        self.assertIsInstance(parse_registry_index(_document(index)), Err)


if __name__ == "__main__":
    unittest.main()
