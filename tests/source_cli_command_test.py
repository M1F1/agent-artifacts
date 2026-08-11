"""Agent CLI coverage for configured source onboarding and marketplace browse."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent_artifacts import cli
from agent_artifacts.application.configuration import (
    ConfigRecoveryPlan,
    ConfigurationPorts,
    ConfigWriteReceipt,
    LoadedConfiguration,
)
from agent_artifacts.commands._configured_runtime import ConfiguredRuntime
from agent_artifacts.configuration.model import (
    ConfiguredSource,
    SourceKind,
    default_organization_policy,
    default_user_configuration,
)
from agent_artifacts.configuration.paths import ConfigPaths
from agent_artifacts.configuration.policy import RuntimeOverrides, apply_configuration
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import ObjectDigest, SourceAlias, SourceId
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.protocol.hashing import sha256_bytes
from agent_artifacts.sources.model import HealthStatus, SourceHealth, SyncDisposition


def _runtime(
    configuration=None,
    *,
    recovery: ConfigRecoveryPlan | None = None,
    writes: list[str] | None = None,
) -> ConfiguredRuntime:
    user = default_user_configuration() if configuration is None else configuration
    policy = default_organization_policy()
    effective = apply_configuration(user, RuntimeOverrides(), policy)
    assert isinstance(effective, Ok)
    paths = ConfigPaths(
        "/tmp/aart-cli/config.json",
        "/tmp/aart-cli/data",
        "/tmp/aart-cli/cache",
        "/tmp/aart-cli/policy.json",
    )

    def read(_request):
        return Ok(None)

    def write(document):
        if writes is not None:
            writes.append("save")
        return Ok(ConfigWriteReceipt(document.path, sha256_bytes(document.content)))

    def recover(_plan):
        raise AssertionError("recovery is not part of source onboarding")

    def write_checked(document):
        # CFG02: the reviewed source-management write goes through the compare-and-swap port.
        # This fake records the same marker and asserts the expected state was actually named.
        if writes is not None:
            writes.append("save")
        return Ok(ConfigWriteReceipt(document.path, sha256_bytes(document.content)))

    return ConfiguredRuntime(
        paths,
        ConfigurationPorts(read, write, recover, write_checked),
        LoadedConfiguration(user, effective.value, None, recovery, ()),
    )


def _sync_outcome():
    return SimpleNamespace(
        disposition=SyncDisposition.PUBLISHED,
        current=SimpleNamespace(
            declared_source_id=SourceId("team-registry"),
            candidate=SimpleNamespace(
                resolved_revision="a" * 40,
                snapshot_digest=ObjectDigest("sha256", "b" * 64),
            ),
        ),
        diagnostics=(),
    )


class SourceCliParserAndDispatchTests(unittest.TestCase):
    def test_source_add_flags_map_to_a_distinct_request_contract(self) -> None:
        request = cli._to_request(
            cli.build_parser().parse_args(
                [
                    "source",
                    "add",
                    "--alias",
                    "company",
                    "--kind",
                    "registry-git",
                    "--location",
                    "https://git.example.test/company/registry.git",
                    "--ref",
                    "stable",
                    "--no-default",
                    "--json",
                ]
            )
        )
        self.assertEqual(request.command, "source")
        self.assertEqual(request.source_action, "add")
        self.assertEqual(request.source_alias, "company")
        self.assertEqual(request.source_kind, "registry-git")
        self.assertEqual(request.source_location, "https://git.example.test/company/registry.git")
        self.assertEqual(request.ref, "stable")
        self.assertFalse(request.source_make_default)
        self.assertTrue(request.json)

    def test_source_and_marketplace_dispatch_to_their_own_boundaries(self) -> None:
        calls = []

        def source_handler(request):
            calls.append((request.command, request.source_action))
            return 17

        def marketplace_handler(request):
            calls.append((request.command, request.marketplace_action))
            return 19

        with patch.dict(
            cli.DISPATCH,
            {"source": source_handler, "marketplace": marketplace_handler},
        ):
            self.assertEqual(cli.main(["source", "list"]), 17)
            self.assertEqual(cli.main(["marketplace", "list", "--json"]), 19)
        self.assertEqual(calls, [("source", "list"), ("marketplace", "list")])


class SourceCliCommandTests(unittest.TestCase):
    def test_local_source_add_then_agent_browse_uses_durable_state_without_objects(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            paths = ConfigPaths(
                str(root / "config" / "config.json"),
                str(root / "data"),
                str(root / "cache"),
                str(root / "policy.json"),
            )
            fixture = str(
                (Path(__file__).parent / "fixtures" / "protocol" / "native-source-v1").resolve()
            )
            add_stdout = io.StringIO()
            list_stdout = io.StringIO()
            marketplace_stdout = io.StringIO()
            with patch(
                "agent_artifacts.commands._configured_runtime.resolve_config_paths",
                return_value=paths,
            ):
                with contextlib.redirect_stdout(add_stdout):
                    added = cli.main(
                        [
                            "source",
                            "add",
                            "--alias",
                            "fixture",
                            "--kind",
                            "source-local",
                            "--location",
                            fixture,
                            "--json",
                        ]
                    )
                with contextlib.redirect_stdout(list_stdout):
                    listed = cli.main(["source", "list", "--json"])
                with contextlib.redirect_stdout(marketplace_stdout):
                    browsed = cli.main(["marketplace", "list", "--json"])

            self.assertEqual(added, 0)
            self.assertEqual(listed, 0)
            self.assertEqual(browsed, 0)
            self.assertEqual(json.loads(add_stdout.getvalue())["source"]["alias"], "fixture")
            self.assertEqual(json.loads(list_stdout.getvalue())["sources"][0]["health"], "healthy")
            marketplace = json.loads(marketplace_stdout.getvalue())
            self.assertTrue(marketplace["ok"])
            self.assertEqual(len(marketplace["artifacts"]), 1)
            self.assertFalse((root / "data" / "objects").exists())

    def test_add_synchronizes_before_saving_and_emits_json(self) -> None:
        events: list[str] = []
        runtime = _runtime(writes=events)

        def synchronize(*_args, **_kwargs):
            events.append("sync")
            return Ok(_sync_outcome())

        stdout = io.StringIO()
        with (
            patch(
                "agent_artifacts.commands.source.load_runtime_configuration",
                side_effect=(Ok(runtime), Ok(runtime)),
            ),
            patch(
                "agent_artifacts.commands.source.sync_configured_source",
                side_effect=synchronize,
            ),
            contextlib.redirect_stdout(stdout),
        ):
            result = cli.main(
                [
                    "source",
                    "add",
                    "--alias",
                    "company",
                    "--kind",
                    "registry-git",
                    "--location",
                    "https://git.example.test/company/registry.git",
                    "--json",
                ]
            )

        self.assertEqual(result, 0)
        self.assertEqual(events, ["sync", "save"])
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["operation"], "source.add")
        self.assertEqual(payload["source"]["alias"], "company")
        self.assertTrue(payload["source"]["default"])
        self.assertEqual(payload["sync"]["source_id"], "team-registry")

    def test_add_sync_failure_never_saves_and_is_json_safe(self) -> None:
        events: list[str] = []
        runtime = _runtime(writes=events)
        failed = Err(
            (
                Diagnostic(
                    DiagnosticCode("source-unavailable"),
                    Severity.ERROR,
                    "remote is unavailable",
                ),
            )
        )
        stdout = io.StringIO()
        with (
            patch(
                "agent_artifacts.commands.source.load_runtime_configuration",
                return_value=Ok(runtime),
            ),
            patch(
                "agent_artifacts.commands.source.sync_configured_source",
                return_value=failed,
            ),
            contextlib.redirect_stdout(stdout),
        ):
            result = cli.main(
                [
                    "source",
                    "add",
                    "--alias",
                    "company",
                    "--kind",
                    "registry-git",
                    "--location",
                    "https://git.example.test/company/registry.git",
                    "--json",
                ]
            )

        self.assertEqual(result, 1)
        self.assertEqual(events, [])
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["operation"], "source.add")
        self.assertEqual(payload["diagnostics"][0]["code"], "source-unavailable")

    def test_add_second_registry_preserves_existing_default_without_an_explicit_flag(self) -> None:
        existing = ConfiguredSource(
            SourceAlias("company"),
            SourceKind.REGISTRY_GIT,
            "https://git.example.test/company/registry.git",
            "main",
            True,
        )
        baseline = default_user_configuration()
        configuration = type(baseline)(
            baseline.schema_version,
            (existing,),
            existing.alias,
            baseline.sync,
            baseline.reporting,
        )
        runtime = _runtime(configuration)
        stdout = io.StringIO()
        with (
            patch(
                "agent_artifacts.commands.source.load_runtime_configuration",
                side_effect=(Ok(runtime), Ok(runtime)),
            ),
            patch(
                "agent_artifacts.commands.source.sync_configured_source",
                return_value=Ok(_sync_outcome()),
            ),
            contextlib.redirect_stdout(stdout),
        ):
            result = cli.main(
                [
                    "source",
                    "add",
                    "--alias",
                    "team",
                    "--kind",
                    "registry-git",
                    "--location",
                    "https://git.example.test/team/registry.git",
                    "--json",
                ]
            )

        self.assertEqual(result, 0)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["source"]["default"])

    def test_add_refuses_to_overwrite_a_corrupt_configuration(self) -> None:
        events: list[str] = []
        recovery = ConfigRecoveryPlan(
            "/tmp/aart-cli/config.json",
            "/tmp/aart-cli/config.json.corrupt-a",
            ObjectDigest("sha256", "c" * 64),
            b"{}\n",
        )
        runtime = _runtime(recovery=recovery, writes=events)
        stdout = io.StringIO()
        with (
            patch(
                "agent_artifacts.commands.source.load_runtime_configuration",
                return_value=Ok(runtime),
            ),
            patch("agent_artifacts.commands.source.sync_configured_source") as synchronize,
            contextlib.redirect_stdout(stdout),
        ):
            result = cli.main(
                [
                    "source",
                    "add",
                    "--alias",
                    "company",
                    "--kind",
                    "registry-git",
                    "--location",
                    "https://git.example.test/company/registry.git",
                    "--json",
                ]
            )

        self.assertEqual(result, 1)
        self.assertEqual(events, [])
        synchronize.assert_not_called()
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["diagnostics"][0]["code"], "config-invalid")

    def test_add_refuses_a_configuration_that_becomes_corrupt_during_sync(self) -> None:
        events: list[str] = []
        recovery = ConfigRecoveryPlan(
            "/tmp/aart-cli/config.json",
            "/tmp/aart-cli/config.json.corrupt-a",
            ObjectDigest("sha256", "c" * 64),
            b"{}\n",
        )
        before = _runtime(writes=events)
        after = _runtime(recovery=recovery, writes=events)
        stdout = io.StringIO()
        with (
            patch(
                "agent_artifacts.commands.source.load_runtime_configuration",
                side_effect=(Ok(before), Ok(after)),
            ),
            patch(
                "agent_artifacts.commands.source.sync_configured_source",
                side_effect=lambda *_args, **_kwargs: (events.append("sync"), Ok(_sync_outcome()))[
                    1
                ],
            ),
            contextlib.redirect_stdout(stdout),
        ):
            result = cli.main(
                [
                    "source",
                    "add",
                    "--alias",
                    "company",
                    "--kind",
                    "registry-git",
                    "--location",
                    "https://git.example.test/company/registry.git",
                    "--json",
                ]
            )

        self.assertEqual(result, 1)
        self.assertEqual(events, ["sync"])
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["diagnostics"][0]["code"], "config-invalid")

    def test_list_reports_managed_health_without_mutating_configuration(self) -> None:
        source = ConfiguredSource(
            SourceAlias("company"),
            SourceKind.REGISTRY_GIT,
            "https://git.example.test/company/registry.git",
            "main",
            True,
        )
        configuration = default_user_configuration()
        configuration = type(configuration)(
            configuration.schema_version,
            (source,),
            source.alias,
            configuration.sync,
            configuration.reporting,
        )
        runtime = _runtime(configuration)
        stdout = io.StringIO()
        with (
            patch(
                "agent_artifacts.commands.source.load_runtime_configuration",
                return_value=Ok(runtime),
            ),
            patch(
                "agent_artifacts.commands.source._source_health",
                return_value=SourceHealth(HealthStatus.HEALTHY, 12, None),
            ),
            contextlib.redirect_stdout(stdout),
        ):
            result = cli.main(["source", "list", "--json"])

        self.assertEqual(result, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["sources"][0]["health"], "healthy")
        self.assertTrue(payload["sources"][0]["default"])

    def test_list_refuses_to_treat_a_corrupt_config_as_empty(self) -> None:
        recovery = ConfigRecoveryPlan(
            "/tmp/aart-cli/config.json",
            "/tmp/aart-cli/config.json.corrupt-a",
            ObjectDigest("sha256", "c" * 64),
            b"{}\n",
        )
        stdout = io.StringIO()
        with (
            patch(
                "agent_artifacts.commands.source.load_runtime_configuration",
                return_value=Ok(_runtime(recovery=recovery)),
            ),
            contextlib.redirect_stdout(stdout),
        ):
            result = cli.main(["source", "list", "--json"])

        self.assertEqual(result, 1)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["diagnostics"][0]["code"], "config-invalid")


class MarketplaceCliCommandTests(unittest.TestCase):
    def test_list_emits_the_configured_canonical_snapshot_as_json(self) -> None:
        source = ConfiguredSource(
            SourceAlias("company"),
            SourceKind.REGISTRY_GIT,
            "https://git.example.test/company/registry.git",
            "main",
            True,
        )
        configuration = default_user_configuration()
        configuration = type(configuration)(
            configuration.schema_version,
            (source,),
            source.alias,
            configuration.sync,
            configuration.reporting,
        )
        runtime = _runtime(configuration)
        snapshot = {
            "schema_version": 1,
            "sources": [{"alias": "company"}],
            "artifacts": [{"coordinate": "company/skill/example@1.0.0"}],
            "collections": [],
            "diagnostics": [],
        }
        stdout = io.StringIO()
        with (
            patch(
                "agent_artifacts.commands.marketplace.load_runtime_configuration",
                return_value=Ok(runtime),
            ),
            patch(
                "agent_artifacts.commands.marketplace.load_read_only_marketplace",
                return_value=Ok(object()),
            ),
            patch(
                "agent_artifacts.commands.marketplace.marketplace_catalog_bytes",
                return_value=json.dumps(snapshot).encode("utf-8"),
            ),
            contextlib.redirect_stdout(stdout),
        ):
            result = cli.main(["marketplace", "list", "--json"])

        self.assertEqual(result, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["operation"], "marketplace.list")
        self.assertEqual(payload["aart_version"], "1.3.0")
        self.assertEqual(payload["artifacts"], snapshot["artifacts"])

    def test_list_without_a_source_returns_the_canonical_json_diagnostic(self) -> None:
        no_source = Err(
            (
                Diagnostic(
                    DiagnosticCode("no-source-configured"),
                    Severity.ERROR,
                    "this content operation requires at least one enabled source",
                ),
            )
        )
        stdout = io.StringIO()
        with (
            patch(
                "agent_artifacts.commands.marketplace.load_runtime_configuration",
                return_value=no_source,
            ),
            contextlib.redirect_stdout(stdout),
        ):
            result = cli.main(["marketplace", "list", "--json"])

        self.assertEqual(result, 1)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["operation"], "marketplace.list")
        self.assertEqual(payload["diagnostics"][0]["code"], "no-source-configured")


if __name__ == "__main__":
    unittest.main()
