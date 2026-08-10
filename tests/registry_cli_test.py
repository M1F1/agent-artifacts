from __future__ import annotations

import unittest
from unittest.mock import patch

from agent_artifacts import cli
from agent_artifacts.model import Request


class RegistryCliTest(unittest.TestCase):
    def test_all_registry_actions_map_to_one_command_boundary(self) -> None:
        parser = cli.build_parser()
        actions = {
            "init",
            "scaffold",
            "format",
            "validate",
            "lock",
            "build",
            "audit",
            "test",
            "diff",
            "migrate",
        }
        registry = next(
            action for action in parser._actions if action.__class__.__name__ == "_SubParsersAction"
        ).choices["registry"]
        sub = next(
            action
            for action in registry._actions
            if action.__class__.__name__ == "_SubParsersAction"
        )
        self.assertEqual(set(sub.choices), actions)
        self.assertIn("registry", cli.DISPATCH)

    def test_format_check_and_json_are_preserved_in_request(self) -> None:
        captured: list[Request] = []

        def run(request: Request) -> int:
            captured.append(request)
            return 0

        with patch.dict(cli.DISPATCH, {"registry": run}):
            result = cli.main(
                ["registry", "format", "--source", "/tmp/registry", "--check", "--json"]
            )
        self.assertEqual(result, 0)
        self.assertEqual(captured[0].registry_action, "format")
        self.assertEqual(captured[0].source_dir, "/tmp/registry")
        self.assertTrue(captured[0].check)
        self.assertTrue(captured[0].json)

    def test_migrate_defaults_to_dry_run_and_requires_explicit_apply(self) -> None:
        request = cli._to_request(
            cli.build_parser().parse_args(
                [
                    "registry",
                    "migrate",
                    "--legacy-source",
                    "/tmp/legacy",
                    "--source",
                    "/tmp/registry",
                    "--source-id",
                    "company-registry",
                    "--display-name",
                    "Company Registry",
                    "--profile",
                    "generic",
                    "--license",
                    "MIT",
                ]
            )
        )
        self.assertEqual(request.registry_action, "migrate")
        self.assertEqual(request.legacy_source, "/tmp/legacy")
        self.assertFalse(request.apply)
        self.assertEqual(request.artifact_license, "MIT")

    def test_scaffold_install_scope_and_mode_do_not_silently_include_defaults(self) -> None:
        request = cli._to_request(
            cli.build_parser().parse_args(
                [
                    "registry",
                    "scaffold",
                    "--source",
                    "/tmp/registry",
                    "skill",
                    "demo",
                    "--summary",
                    "Demonstrate one canonical skill.",
                    "--profile",
                    "codex",
                    "--platform",
                    "darwin",
                    "--install-scope",
                    "user",
                    "--install-mode",
                    "symlink",
                ]
            )
        )
        self.assertEqual(request.registry_scopes, ("user",))
        self.assertEqual(request.registry_modes, ("symlink",))


if __name__ == "__main__":
    unittest.main()
