"""SL-5: every refusal in the source area names a command the shipped executable accepts.

The 2026-08-13 dead end was as much a diagnostics failure as a missing-operation failure: `sync`
advised the operator to "review the configured origin before replacing this source", and there was
no replace.  Rewriting that sentence fixes it once; this file is what keeps it fixed.

Each refusal is produced by the real production path, never by a literal written here, and every
``aart …`` command found in its remediation is handed to the actual CLI parser.  A remediation that
drifts away from the shipped surface — a renamed subcommand, a dropped flag, a command that was
only ever planned — fails here.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import re
import unittest
from unittest.mock import patch

from agent_artifacts import cli
from agent_artifacts.application.configuration import ConfigurationRequest, load_configuration
from agent_artifacts.application.sources import sync_source
from agent_artifacts.configuration.model import (
    ConfiguredSource,
    OrganizationPolicy,
    SourceKind,
    UserConfiguration,
    default_user_configuration,
)
from agent_artifacts.configuration.policy import RuntimeOverrides
from agent_artifacts.domain.identifiers import SourceAlias
from agent_artifacts.domain.result import Err
from agent_artifacts.tui_sources import (
    build_source_stage,
    plan_source_addition,
    plan_source_removal,
)
from tests.configuration_application_test import _FakePorts as _ConfigurationPorts
from tests.configuration_application_test import _paths
from tests.source_sync_application_test import _candidate, _current, _FakePorts, _request

_COMMAND = re.compile(r"`(aart [^`]+)`")


def _refusal(result) -> tuple[str, ...]:
    """Every remediation line of a refusal, with the refusal itself asserted to be one."""

    assert isinstance(result, Err), f"expected a refusal, got {result}"
    return tuple(line for diagnostic in result.diagnostics for line in diagnostic.remediation)


def _registry(alias: str, location: str) -> ConfiguredSource:
    return ConfiguredSource(SourceAlias(alias), SourceKind.REGISTRY_GIT, location, "main", True)


def _view(*sources: ConfiguredSource):
    baseline = default_user_configuration()
    configuration = UserConfiguration(
        baseline.schema_version, sources, None, baseline.sync, baseline.reporting
    )
    stage = build_source_stage(configuration, OrganizationPolicy(1), {}, first_run=False)
    assert not isinstance(stage, Err), stage
    return stage.value


class SourceRemediationNamesRealCommandsTest(unittest.TestCase):
    def assert_runnable(self, remediation: tuple[str, ...]) -> tuple[str, ...]:
        """Assert the remediation offers at least one command, and that all of them parse.

        ``parse_args`` is the shipped surface itself, so this cannot pass against a command the
        parser does not define.  ``error`` is patched because argparse writes to stderr and exits
        rather than raising anything a test can attribute back to a specific command.  A
        remediation ending in ``--help`` is advice to go read the help, so it succeeds by exiting
        zero instead of returning; that still proves the subcommand exists, which is the claim.
        """

        found = tuple(match for line in remediation for match in _COMMAND.findall(line))
        self.assertTrue(found, f"remediation names no command: {remediation}")
        for command in found:
            arguments = command.split()[1:]
            with (
                patch.object(
                    argparse.ArgumentParser,
                    "error",
                    side_effect=lambda message, named=command: self.fail(
                        f"`{named}` is not accepted: {message}"
                    ),
                ),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                if arguments[-1] == "--help":
                    with self.assertRaises(SystemExit) as exited:
                        cli.build_parser().parse_args(arguments)
                    self.assertEqual(exited.exception.code, 0, f"`{command}` did not exit zero")
                else:
                    cli.build_parser().parse_args(arguments)
        return found

    def test_a_changed_declared_identity_points_at_a_command_that_exists(self) -> None:
        source = _registry("registry", "https://git.example.test/team/registry.git")
        ports = _FakePorts(
            _candidate(source, b"new"),
            _current(_candidate(source, b"old"), source_id="old-id"),
        )

        refused = sync_source(_request(source), ports.ports())

        commands = self.assert_runnable(_refusal(refused))
        self.assertIn("aart source resubscribe --alias registry", commands)

    def test_an_already_configured_alias_points_at_commands_that_exist(self) -> None:
        held = _registry("registry", "https://git.example.test/team/registry.git")
        duplicate = _registry("registry", "https://git.example.test/other/registry.git")

        refused = plan_source_addition(_view(held), duplicate)

        commands = self.assert_runnable(_refusal(refused))
        self.assertTrue(any("--alias registry" in command for command in commands), commands)

    def test_an_already_configured_origin_and_ref_point_at_commands_that_exist(self) -> None:
        held = _registry("registry", "https://git.example.test/team/registry.git")
        same_origin = _registry("second", "https://git.example.test/team/registry.git")

        refused = plan_source_addition(_view(held), same_origin)

        commands = self.assert_runnable(_refusal(refused))
        self.assertTrue(
            any("--alias registry" in command for command in commands),
            f"remediation must name the alias that holds the origin: {commands}",
        )

    def test_removing_an_unconfigured_alias_points_at_the_listing_command(self) -> None:
        held = _registry("registry", "https://git.example.test/team/registry.git")

        refused = plan_source_removal(_view(held), SourceAlias("typo"))

        commands = self.assert_runnable(_refusal(refused))
        self.assertTrue(any(command.startswith("aart source list") for command in commands))

    def test_a_content_operation_without_any_source_points_at_the_command_that_adds_one(
        self,
    ) -> None:
        """The first refusal a new operator meets, and the one that must not be a dead end."""

        refused = load_configuration(
            ConfigurationRequest(_paths(), RuntimeOverrides(), content_required=True),
            _ConfigurationPorts({}).ports(),
        )

        commands = self.assert_runnable(_refusal(refused))
        self.assertIn("aart source add --help", commands)

    def test_the_guard_rejects_a_remediation_naming_a_command_that_does_not_exist(self) -> None:
        """The guard is only worth having if it fails on the thing it claims to catch."""

        with self.assertRaises(AssertionError):
            self.assert_runnable(("run `aart source disavow --alias registry`",))


if __name__ == "__main__":
    unittest.main()
