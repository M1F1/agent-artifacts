"""Public migrate-state CLI and bounded legacy command-window contracts."""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_artifacts import cli
from agent_artifacts.consumer.application import ConsumerApplicationService
from agent_artifacts.consumer.io import LocalConsumerAdapter
from agent_artifacts.consumer.model import ConsumerContext
from agent_artifacts.domain.result import Ok
from agent_artifacts.manifest import dump_manifest
from agent_artifacts.model import Manifest, ManifestEntry, Request
from agent_artifacts.profiles.builtin import builtin
from agent_artifacts.source import open_source
from tests.canonical_symlink_test import _fixture


class MigrateCliTest(unittest.TestCase):
    def test_state_parser_maps_dry_run_apply_rollback_and_explicit_source_resolution(self) -> None:
        parser = cli.build_parser()
        dry = cli._to_request(
            parser.parse_args(
                [
                    "migrate",
                    "state",
                    "--from",
                    "0.1",
                    "--scope",
                    "user",
                    "--source-map",
                    "skill/review@claude=company",
                    "--dry-run",
                    "--json",
                ]
            )
        )
        apply = cli._to_request(parser.parse_args(["migrate", "state", "--from", "0.1", "--apply"]))
        rollback = cli._to_request(
            parser.parse_args(["migrate", "state", "--from", "0.1", "--rollback"])
        )

        self.assertEqual(dry.migration_action, "state")
        self.assertEqual(dry.migration_from, "0.1")
        self.assertEqual(dry.scope, "user")
        self.assertEqual(dry.source_mappings, ("skill/review@claude=company",))
        self.assertTrue(dry.dry_run and dry.json)
        self.assertTrue(apply.apply)
        self.assertTrue(rollback.rollback)

    def test_migrate_dispatches_as_a_first_class_command(self) -> None:
        calls: list[Request] = []

        def handler(request: Request) -> int:
            calls.append(request)
            return 7

        with patch.dict(cli.DISPATCH, {"migrate": handler}):
            result = cli.main(["migrate", "state", "--from", "0.1", "--dry-run"])

        self.assertEqual(result, 7)
        self.assertEqual(calls[0].migration_action, "state")

    def test_legacy_package_catalog_default_is_removed_with_actionable_message(self) -> None:
        result = open_source(Request(command="list"))

        self.assertTrue(hasattr(result, "reason"))
        self.assertIn("configured marketplace", result.reason)
        self.assertIn("--source", result.reason)

    def test_legacy_source_and_repo_flags_emit_explicit_compatibility_warning(self) -> None:
        stderr = io.StringIO()
        with (
            patch.dict(cli.DISPATCH, {"list": lambda _request: 0}),
            contextlib.redirect_stderr(stderr),
        ):
            self.assertEqual(cli.main(["list", "--source", "/tmp/catalog"]), 0)

        self.assertIn("legacy 0.1 compatibility path", stderr.getvalue())
        # The warning must name the canonical replacement for both audiences, not just the TUI.
        self.assertIn("aart marketplace", stderr.getvalue())
        self.assertIn("TUI", stderr.getvalue())

    def test_command_dry_run_apply_and_later_process_rollback_are_end_to_end(self) -> None:
        from agent_artifacts.commands import migrate

        with tempfile.TemporaryDirectory() as raw:
            fixture = _fixture(Path(raw), "skill")
            project, _checkout, store_paths, location, _request, catalog, effective = fixture
            context = ConsumerContext(catalog, effective, builtin(), location, store_paths)
            consumer = ConsumerApplicationService(context, LocalConsumerAdapter())
            destination = ".claude/skills/review"
            installed = project / destination
            installed.mkdir(parents=True)
            (installed / "SKILL.md").write_text("# legacy\n", encoding="utf-8")
            legacy = dump_manifest(
                Manifest(
                    "M1F1/agent-artifacts",
                    (
                        ManifestEntry(
                            "review",
                            "skill",
                            "claude",
                            "main:" + "7" * 40,
                            files={destination: ""},
                        ),
                    ),
                )
            ).encode()
            state = project / ".agent-artifacts/manifest.json"
            state.parent.mkdir(parents=True)
            state.write_bytes(legacy)
            base = dict(
                command="migrate",
                migration_action="state",
                migration_from="0.1",
                project=str(project),
                user_home=str(Path(raw, "home")),
            )

            with patch.object(migrate, "load_local_consumer_service", return_value=Ok(consumer)):
                self.assertEqual(migrate.run(Request(**base, dry_run=True)), 0)
                self.assertEqual(state.read_bytes(), legacy)
                self.assertEqual(migrate.run(Request(**base, apply=True)), 0)
                self.assertIn(b'"schema_version":2', state.read_bytes())

            # Recovery is state-local: a later process can roll back even when its source
            # configuration/catalog cannot be loaded anymore.
            with patch.object(
                migrate,
                "load_local_consumer_service",
                side_effect=AssertionError("rollback must not load marketplace sources"),
            ):
                self.assertEqual(migrate.run(Request(**base, rollback=True)), 0)

            self.assertEqual(state.read_bytes(), legacy)


if __name__ == "__main__":
    unittest.main()
