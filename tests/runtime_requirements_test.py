from __future__ import annotations

import json
import unittest

from agent_artifacts.consumer.runtime_requirements import (
    RuntimeRequirementStatus,
    evaluate_runtime_requirements,
    parse_runtime_environment,
    parse_runtime_requirements,
)
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.protocol.native_schema import parse_artifact_manifest


def _manifest(extension: object | None = None, *, key: str = "aart.runtime-requirements"):
    document = {
        "schema_version": 1,
        "type": "skill",
        "name": "example",
        "version": "1.0.0",
        "summary": "Example skill.",
        "payload": {"root": "payload", "format": "aart-skill-v1"},
        "compatibility": {"profiles": ["claude"], "platforms": ["darwin"]},
        "install": {
            "scopes": ["project"],
            "modes": ["copy"],
            "effects": ["copy-tree"],
        },
    }
    if extension is not None:
        document[key] = extension
    parsed = parse_artifact_manifest(json.dumps(document))
    assert isinstance(parsed, Ok), parsed
    return parsed.value


def _requirements():
    parsed = parse_runtime_requirements(
        _manifest(
            {
                "schema_version": 1,
                "requirements": [
                    {
                        "id": "python",
                        "version": {"min_inclusive": "3.11.0"},
                        "reason": "The artifact uses Python 3.11 stdlib features.",
                    },
                    {"id": "command.git"},
                ],
            }
        )
    )
    assert isinstance(parsed, Ok), parsed
    return parsed.value


class RuntimeRequirementParsingTests(unittest.TestCase):
    def test_absent_extension_means_no_declared_runtime_requirements(self) -> None:
        parsed = parse_runtime_requirements(_manifest())

        self.assertEqual(parsed, Ok(()))

    def test_namespaced_extension_preserves_presence_and_version_requirements(self) -> None:
        requirements = _requirements()

        self.assertEqual([item.id for item in requirements], ["command.git", "python"])
        python = requirements[1]
        self.assertEqual(str(python.version.min_inclusive), "3.11.0")
        self.assertEqual(python.reason, "The artifact uses Python 3.11 stdlib features.")

    def test_personal_namespace_is_rejected_with_one_key_migration(self) -> None:
        parsed = parse_runtime_requirements(
            _manifest(
                {"schema_version": 1, "requirements": [{"id": "python"}]},
                key="com.m1f1.runtime-requirements",
            )
        )

        self.assertIsInstance(parsed, Err)
        assert isinstance(parsed, Err)
        diagnostic = parsed.diagnostics[0]
        self.assertEqual(diagnostic.code.value, "runtime-requirements-migration-required")
        self.assertIn("aart.runtime-requirements", " ".join(diagnostic.remediation))

    def test_malformed_advisory_extension_is_reportable_without_invalidating_manifest(self) -> None:
        manifest = _manifest(
            {
                "schema_version": 1,
                "requirements": [{"id": "python", "version": {}}],
            }
        )

        parsed = parse_runtime_requirements(manifest)

        self.assertIsInstance(parsed, Err)
        assert isinstance(parsed, Err)
        self.assertEqual(parsed.diagnostics[0].code.value, "runtime-requirements-invalid")


class RuntimeEnvironmentHealthTests(unittest.TestCase):
    def test_environment_is_explicit_data_not_a_process_probe(self) -> None:
        parsed = parse_runtime_environment(
            json.dumps(
                {
                    "schema_version": 1,
                    "name": "repository-ci",
                    "capabilities": [
                        {"id": "python", "version": "3.12.2"},
                        {"id": "command.git"},
                    ],
                }
            )
        )

        self.assertIsInstance(parsed, Ok)
        assert isinstance(parsed, Ok)
        self.assertEqual(parsed.value.name, "repository-ci")
        self.assertEqual([item.id for item in parsed.value.capabilities], ["command.git", "python"])

    def test_satisfied_unsatisfied_and_unknown_are_advisory_observations(self) -> None:
        requirements = _requirements()
        environments = {
            "satisfied": {
                "schema_version": 1,
                "capabilities": [
                    {"id": "python", "version": "3.11.8"},
                    {"id": "command.git"},
                ],
            },
            "unsatisfied": {
                "schema_version": 1,
                "capabilities": [
                    {"id": "python", "version": "3.10.14"},
                    {"id": "command.git"},
                ],
            },
            "unknown": {
                "schema_version": 1,
                "capabilities": [{"id": "python"}],
            },
        }

        observed = {}
        for name, document in environments.items():
            parsed = parse_runtime_environment(json.dumps(document))
            assert isinstance(parsed, Ok), parsed
            observed[name] = {
                item.requirement.id: item.status
                for item in evaluate_runtime_requirements(requirements, parsed.value)
            }

        self.assertEqual(
            observed["satisfied"],
            {
                "command.git": RuntimeRequirementStatus.SATISFIED,
                "python": RuntimeRequirementStatus.SATISFIED,
            },
        )
        self.assertEqual(observed["unsatisfied"]["python"], RuntimeRequirementStatus.UNSATISFIED)
        self.assertEqual(observed["unknown"]["python"], RuntimeRequirementStatus.UNKNOWN)
        self.assertEqual(observed["unknown"]["command.git"], RuntimeRequirementStatus.UNKNOWN)

    def test_duplicate_environment_capabilities_are_rejected(self) -> None:
        parsed = parse_runtime_environment(
            '{"schema_version":1,"capabilities":[{"id":"python"},{"id":"python"}]}'
        )

        self.assertIsInstance(parsed, Err)
        assert isinstance(parsed, Err)
        self.assertEqual(parsed.diagnostics[0].code.value, "runtime-environment-invalid")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
