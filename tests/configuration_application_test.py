from __future__ import annotations

import unittest

from agent_artifacts.application.configuration import (
    ConfigDocument,
    ConfigReadRequest,
    ConfigRecoveryReceipt,
    ConfigurationPorts,
    ConfigurationRequest,
    ConfigWriteReceipt,
    load_configuration,
    recover_user_configuration,
    save_user_configuration,
)
from agent_artifacts.configuration.paths import PathOverrides, Platform, resolve_config_paths
from agent_artifacts.configuration.policy import RuntimeOverrides
from agent_artifacts.configuration.schema import parse_organization_policy, parse_user_configuration
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import ObjectDigest
from agent_artifacts.domain.result import Err, Ok


def _digest(character: str) -> ObjectDigest:
    return ObjectDigest("sha256", character * 64)


class _FakePorts:
    def __init__(self, documents: dict[str, bytes | None]):
        self.documents = documents
        self.reads: list[str] = []
        self.writes: list[ConfigDocument] = []
        self.recoveries = []

    def read(self, request: ConfigReadRequest):
        self.reads.append(request.path)
        return Ok(self.documents.get(request.path))

    def write(self, command: ConfigDocument):
        self.writes.append(command)
        return Ok(ConfigWriteReceipt(command.path, _digest("a")))

    def recover(self, command):
        self.recoveries.append(command)
        return Ok(
            ConfigRecoveryReceipt(
                command.path,
                command.backup_path,
                command.expected_digest,
                _digest("b"),
            )
        )

    def ports(self) -> ConfigurationPorts:
        return ConfigurationPorts(self.read, self.write, self.recover)


def _paths():
    return resolve_config_paths(
        Platform.LINUX,
        home="/never/real/home",
        overrides=PathOverrides(
            config_root="/test/config",
            data_root="/test/data",
            cache_root="/test/cache",
            policy_file="/test/policy.json",
        ),
    )


class ConfigurationApplicationTest(unittest.TestCase):
    def test_first_run_with_zero_sources_succeeds_for_local_operations(self) -> None:
        paths = _paths()
        fake = _FakePorts({})

        result = load_configuration(
            ConfigurationRequest(paths, RuntimeOverrides(), content_required=False),
            fake.ports(),
        )

        self.assertIsInstance(result, Ok)
        assert isinstance(result, Ok)
        self.assertEqual(result.value.effective.configuration.sources, ())
        self.assertIsNotNone(result.value.first_run)
        assert result.value.first_run is not None
        self.assertTrue(result.value.first_run.allow_no_source)
        self.assertTrue(result.value.first_run.allow_direct_sources)
        self.assertEqual(
            fake.reads,
            [paths.policy_file, paths.user_config_file],
        )
        self.assertEqual(fake.writes, [])

    def test_content_operation_without_source_has_stable_guidance(self) -> None:
        paths = _paths()
        result = load_configuration(
            ConfigurationRequest(paths, RuntimeOverrides(), content_required=True),
            _FakePorts({}).ports(),
        )

        self.assertIsInstance(result, Err)
        assert isinstance(result, Err)
        self.assertEqual(result.diagnostics[0].code.value, "no-source-configured")
        self.assertIn("aart source add", result.diagnostics[0].remediation)

    def test_policy_recommendations_shape_first_run_without_forcing_registry(self) -> None:
        paths = _paths()
        fake = _FakePorts(
            {
                paths.policy_file: b'{"schema_version":1,"recommended_sources":["company"],"allow_direct_sources":false}',
            }
        )

        result = load_configuration(
            ConfigurationRequest(paths, RuntimeOverrides(), content_required=False),
            fake.ports(),
        )

        self.assertIsInstance(result, Ok)
        assert isinstance(result, Ok)
        assert result.value.first_run is not None
        self.assertEqual(tuple(map(str, result.value.first_run.recommended_sources)), ("company",))
        self.assertFalse(result.value.first_run.allow_direct_sources)
        self.assertTrue(result.value.first_run.allow_no_source)

    def test_required_source_is_presented_on_first_run_but_blocks_content(self) -> None:
        paths = _paths()
        fake = _FakePorts(
            {paths.policy_file: b'{"schema_version":1,"required_sources":["company"]}'}
        )

        local = load_configuration(
            ConfigurationRequest(paths, RuntimeOverrides(), content_required=False),
            fake.ports(),
        )
        content = load_configuration(
            ConfigurationRequest(paths, RuntimeOverrides(), content_required=True),
            fake.ports(),
        )

        self.assertIsInstance(local, Ok)
        assert isinstance(local, Ok)
        assert local.value.first_run is not None
        self.assertEqual(tuple(map(str, local.value.first_run.required_sources)), ("company",))
        self.assertFalse(local.value.first_run.allow_no_source)
        self.assertIsInstance(content, Err)
        assert isinstance(content, Err)
        self.assertEqual(content.diagnostics[0].code.value, "source-policy-denied")

    def test_corrupt_user_config_is_recoverable_but_cannot_drive_content(self) -> None:
        paths = _paths()
        corrupt = b'{"token":"secret-value", broken'
        fake = _FakePorts({paths.user_config_file: corrupt})

        local = load_configuration(
            ConfigurationRequest(paths, RuntimeOverrides(), content_required=False),
            fake.ports(),
        )
        content = load_configuration(
            ConfigurationRequest(paths, RuntimeOverrides(), content_required=True),
            fake.ports(),
        )

        self.assertIsInstance(local, Ok)
        assert isinstance(local, Ok)
        self.assertIsNotNone(local.value.recovery)
        self.assertNotIn("secret-value", repr(local.value.diagnostics))
        self.assertIsInstance(content, Err)
        assert local.value.recovery is not None
        recovered = recover_user_configuration(local.value.recovery, fake.ports())
        self.assertIsInstance(recovered, Ok)
        self.assertEqual(len(fake.recoveries), 1)

    def test_corrupt_policy_fails_closed_and_denied_save_does_not_write(self) -> None:
        paths = _paths()
        corrupt_policy = _FakePorts({paths.policy_file: b"{"})
        loaded = load_configuration(
            ConfigurationRequest(paths, RuntimeOverrides(), content_required=False),
            corrupt_policy.ports(),
        )
        self.assertIsInstance(loaded, Err)

        configuration = parse_user_configuration('{"schema_version":1}')
        policy = parse_organization_policy('{"schema_version":1,"required_sources":["company"]}')
        assert isinstance(configuration, Ok)
        assert isinstance(policy, Ok)
        fake = _FakePorts({})
        saved = save_user_configuration(
            configuration.value,
            policy.value,
            paths,
            fake.ports(),
        )

        self.assertIsInstance(saved, Err)
        self.assertEqual(fake.writes, [])

    def test_port_failures_short_circuit_in_read_order(self) -> None:
        paths = _paths()
        failure = Err(
            (Diagnostic(DiagnosticCode("config-io-failed"), Severity.ERROR, "read failed"),)
        )

        policy_failure = ConfigurationPorts(
            lambda _request: failure,
            lambda _value: failure,
            lambda _value: failure,
        )
        policy_result = load_configuration(
            ConfigurationRequest(paths, RuntimeOverrides(), content_required=False),
            policy_failure,
        )
        self.assertEqual(policy_result, failure)

        reads: list[str] = []

        def fail_user(request):
            reads.append(request.path)
            return Ok(None) if request.path == paths.policy_file else failure

        user_failure = ConfigurationPorts(
            fail_user,
            lambda _value: failure,
            lambda _value: failure,
        )
        user_result = load_configuration(
            ConfigurationRequest(paths, RuntimeOverrides(), content_required=False),
            user_failure,
        )
        self.assertEqual(user_result, failure)
        self.assertEqual(reads, [paths.policy_file, paths.user_config_file])

    def test_existing_configuration_loads_and_policy_denial_is_propagated(self) -> None:
        paths = _paths()
        direct = b'{"schema_version":1,"sources":[{"alias":"team","kind":"source-git","url":"https://example.test/team/repo.git","ref":"main","enabled":true}]}'
        loaded = load_configuration(
            ConfigurationRequest(paths, RuntimeOverrides(), content_required=True),
            _FakePorts({paths.user_config_file: direct}).ports(),
        )
        denied = load_configuration(
            ConfigurationRequest(paths, RuntimeOverrides(), content_required=False),
            _FakePorts(
                {
                    paths.user_config_file: direct,
                    paths.policy_file: b'{"schema_version":1,"allow_direct_sources":false}',
                }
            ).ports(),
        )

        self.assertIsInstance(loaded, Ok)
        assert isinstance(loaded, Ok)
        self.assertIsNone(loaded.value.first_run)
        self.assertIsInstance(denied, Err)

    def test_allowed_configuration_is_serialized_through_write_port(self) -> None:
        paths = _paths()
        configuration = parse_user_configuration('{"schema_version":1}')
        policy = parse_organization_policy('{"schema_version":1}')
        assert isinstance(configuration, Ok)
        assert isinstance(policy, Ok)
        fake = _FakePorts({})

        result = save_user_configuration(configuration.value, policy.value, paths, fake.ports())

        self.assertIsInstance(result, Ok)
        self.assertEqual(len(fake.writes), 1)
        self.assertEqual(fake.writes[0].path, paths.user_config_file)
        self.assertEqual(fake.writes[0].content[-1:], b"\n")


if __name__ == "__main__":
    unittest.main()
