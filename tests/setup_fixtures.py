"""Shared setup-recipe fixtures for the canonical (protocol 2) setup tests."""

from __future__ import annotations

import json


def recipe(**changes: object) -> bytes:
    """A valid current-revision setup recipe, with per-test field overrides."""
    value: dict[str, object] = {
        "schema_version": 2,
        "protocol_version": 2,
        "artifact": "mcp/atlassian",
        "purpose": "Configure optional Atlassian token access.",
        "platforms": ["darwin"],
        "help_urls": [{"label": "Atlassian auth", "url": "https://example.test/auth"}],
        "required_tools": ["/usr/bin/security"],
        "capabilities": ["keychain", "filesystem"],
        "inputs": [
            {
                "id": "api_token",
                "type": "secret",
                "prompt": "Paste the Atlassian API token",
                "help_url": "https://example.test/token",
            }
        ],
        "steps": [
            {
                "id": "token",
                "use": "macos-keychain.store@1",
                "with": {
                    "input": "api_token",
                    "service": "aart/mcp/atlassian",
                    "account": "default",
                },
            },
            {
                "id": "shell",
                "use": "shell.env-from-keychain@1",
                "with": {
                    "file": "~/.zshrc",
                    "variables": {
                        "ATLASSIAN_API_TOKEN": {
                            "service": "aart/mcp/atlassian",
                            "account": "default",
                        }
                    },
                },
            },
        ],
    }
    value.update(changes)
    return json.dumps(value).encode()
