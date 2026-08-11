"""Configuring one Git origin at several refs, end to end through every gate (SRC02).

Three independent layers previously rejected this: the schema parser, the source-addition planner,
and the configuration model. All three have to agree, or a configuration becomes writable but
unreadable (or vice versa).
"""

from __future__ import annotations

import json
import unittest

from agent_artifacts.configuration.model import (
    ConfiguredSource,
    ReportingSettings,
    SourceKind,
    SyncSettings,
    UserConfiguration,
    default_organization_policy,
)
from agent_artifacts.configuration.schema import parse_user_configuration, user_configuration_bytes
from agent_artifacts.domain.identifiers import SourceAlias
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.sources.model import source_instance_id, source_store_paths
from agent_artifacts.tui_sources import build_source_stage, plan_source_addition


def _git(alias: str, location: str, ref: str) -> ConfiguredSource:
    return ConfiguredSource(SourceAlias(alias), SourceKind.SOURCE_GIT, location, ref, True)


ORIGIN = "https://git.example/team/artifacts.git"


class MultiRefSchemaTests(unittest.TestCase):
    def test_a_configuration_with_two_refs_of_one_origin_round_trips(self) -> None:
        configuration = UserConfiguration(
            1,
            (_git("main-track", ORIGIN, "main"), _git("release-track", ORIGIN, "release/1.0")),
            None,
            SyncSettings(),
            ReportingSettings(),
        )

        parsed = parse_user_configuration(user_configuration_bytes(configuration))

        self.assertIsInstance(parsed, Ok)
        assert isinstance(parsed, Ok)
        self.assertEqual(
            tuple(source.ref for source in parsed.value.sources),
            ("main", "release/1.0"),
        )

    def test_the_same_origin_at_the_same_ref_is_still_rejected_by_the_parser(self) -> None:
        # Hand-authored: two aliases, equivalent HTTPS/SSH spellings, one ref. The model refuses to
        # construct this, so the document is built directly to exercise the parser's own gate.
        document = json.dumps(
            {
                "reporting": {"mode": "disabled"},
                "schema_version": 1,
                "sources": [
                    {
                        "alias": "a",
                        "enabled": True,
                        "kind": "source-git",
                        "ref": "main",
                        "url": ORIGIN,
                    },
                    {
                        "alias": "b",
                        "enabled": True,
                        "kind": "source-git",
                        "ref": "main",
                        "url": "git@git.example:team/artifacts",
                    },
                ],
                "sync": {"max_age_seconds": 900, "mode": "auto"},
            }
        ).encode("utf-8")

        parsed = parse_user_configuration(document)

        self.assertIsInstance(parsed, Err)
        assert isinstance(parsed, Err)
        self.assertEqual(parsed.diagnostics[0].code.value, "config-invalid")
        self.assertIn("ref", parsed.diagnostics[0].message)


class MultiRefStorageTests(unittest.TestCase):
    def test_each_ref_owns_a_separate_mirror_snapshot_and_pointer(self) -> None:
        main = _git("main-track", ORIGIN, "main")
        release = _git("release-track", ORIGIN, "release/1.0")

        main_paths = source_store_paths("/data", source_instance_id(main))
        release_paths = source_store_paths("/data", source_instance_id(release))

        self.assertNotEqual(main_paths.root, release_paths.root)
        self.assertNotEqual(main_paths.mirror, release_paths.mirror)
        self.assertNotEqual(main_paths.current_file, release_paths.current_file)
        self.assertNotEqual(main_paths.lock_directory, release_paths.lock_directory)


class MultiRefAdditionTests(unittest.TestCase):
    def _stage(self, *sources: ConfiguredSource):
        view = build_source_stage(
            UserConfiguration(1, sources, None, SyncSettings(), ReportingSettings()),
            default_organization_policy(),
            {},
            first_run=False,
        )
        assert isinstance(view, Ok), view
        return view.value

    def test_adding_a_second_ref_of_a_configured_origin_is_allowed(self) -> None:
        stage = self._stage(_git("main-track", ORIGIN, "main"))

        planned = plan_source_addition(stage, _git("release-track", ORIGIN, "release/1.0"))

        self.assertIsInstance(planned, Ok)

    def test_adding_the_same_origin_at_the_same_ref_is_still_refused(self) -> None:
        stage = self._stage(_git("main-track", ORIGIN, "main"))

        planned = plan_source_addition(
            stage,
            _git("duplicate", "git@git.example:team/artifacts", "main"),
        )

        self.assertIsInstance(planned, Err)
        assert isinstance(planned, Err)
        self.assertIn("main-track", planned.diagnostics[0].message)

    def test_a_duplicate_alias_is_still_refused(self) -> None:
        stage = self._stage(_git("main-track", ORIGIN, "main"))

        planned = plan_source_addition(stage, _git("main-track", ORIGIN, "release/1.0"))

        self.assertIsInstance(planned, Err)


if __name__ == "__main__":  # pragma: no cover - unittest entry point
    unittest.main()
