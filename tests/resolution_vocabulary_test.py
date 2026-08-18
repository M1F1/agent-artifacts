"""SI-3: a resolution failure names the layer that failed, not the artifact.

Design §3 records the residue: three unrelated stressors — an alias that was never configured, one
configured but never synchronized, and a cold cache read under `--offline` — all reported
`artifact-not-found`, with empty remediation, about the one part of the request that was never
wrong.  An operator sent to look for a correctly spelled name learns nothing.

Each case is driven through the real CLI, because the vocabulary is only worth anything if it
survives to the JSON an agent reads.
"""

from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

from agent_artifacts.configuration.model import (
    ConfiguredSource,
    ReportingSettings,
    SourceKind,
    SyncMode,
    SyncSettings,
    UserConfiguration,
)
from agent_artifacts.configuration.schema import user_configuration_bytes
from agent_artifacts.domain.identifiers import SourceAlias
from tests.marketplace_lifecycle_e2e_test import _COORDINATE, _FIXTURE, _environment

_COLD = "mirror/skill/code-review"


def _configure_cold_source(env) -> None:
    """Add a second subscription to the configuration without ever synchronizing it.

    This is the state a machine is in after a configuration arrives ahead of its content — a fresh
    checkout of someone's dotfiles, a restored home directory — and it is exactly the state
    `source add` cannot produce, because adding synchronizes.
    """

    mirror = env.root / "mirror-source"
    shutil.copytree(_FIXTURE, mirror)
    identity = json.loads((mirror / "aart-source.json").read_text(encoding="utf-8"))
    # A distinct identity: two subscriptions to one source ID is a different refusal entirely.
    identity["source_id"] = "mirror-native-source"
    (mirror / "aart-source.json").write_text(json.dumps(identity), encoding="utf-8")
    cold = ConfiguredSource(SourceAlias("mirror"), SourceKind.SOURCE_LOCAL, str(mirror), None, True)
    Path(env.paths.user_config_file).write_bytes(
        user_configuration_bytes(
            UserConfiguration(
                1,
                (env.source, cold),
                None,
                SyncSettings(mode=SyncMode.MANUAL),
                ReportingSettings(),
            )
        )
    )


class ResolutionFailureVocabularyTest(unittest.TestCase):
    def _diagnostic(self, payload) -> dict:
        self.assertFalse(payload["ok"], payload)
        self.assertEqual(len(payload["diagnostics"]), 1, payload)
        return payload["diagnostics"][0]

    def test_an_unconfigured_alias_reports_the_subscription_not_the_artifact(self) -> None:
        with _environment() as env:
            code, payload = env.run(
                "marketplace", "install", "ghost/skill/code-review", "--profile", "claude", "--yes"
            )

            self.assertEqual(code, 1)
            diagnostic = self._diagnostic(payload)
            self.assertEqual(diagnostic["code"], "source-unavailable")
            self.assertIn("ghost", diagnostic["message"])
            self.assertIn(
                "aart source add --alias ghost --kind registry-git --location <url>",
                diagnostic["remediation"],
            )
            # Uninstall is a valid exit here, and naming it is the whole point: an operator whose
            # source is gone still needs to remove what it installed.
            self.assertTrue(
                any("uninstall" in line for line in diagnostic["remediation"]), diagnostic
            )

    def test_a_configured_but_unsynchronized_alias_reports_the_missing_snapshot(self) -> None:
        with _environment() as env:
            _configure_cold_source(env)

            code, payload = env.run("marketplace", "install", _COLD, "--profile", "claude", "--yes")

            self.assertEqual(code, 1)
            diagnostic = self._diagnostic(payload)
            self.assertEqual(diagnostic["code"], "source-not-synchronized")
            self.assertEqual(diagnostic["remediation"], ["aart source sync --alias mirror"])

    def test_a_cold_cache_under_offline_says_so_rather_than_blaming_the_name(self) -> None:
        """Closes live-acceptance v1 `LAF-19`."""

        with _environment() as env:
            _configure_cold_source(env)

            code, payload = env.run(
                "marketplace", "install", _COLD, "--profile", "claude", "--offline", "--yes"
            )

            self.assertEqual(code, 1)
            diagnostic = self._diagnostic(payload)
            self.assertEqual(diagnostic["code"], "source-not-synchronized")
            self.assertIn("--offline", diagnostic["message"])
            self.assertIn("re-run without --offline", diagnostic["remediation"])

    def test_artifact_not_found_survives_for_the_one_case_where_it_is_true(self) -> None:
        with _environment() as env:
            code, payload = env.run(
                "marketplace", "install", "reference/skill/absent", "--profile", "claude", "--yes"
            )

            self.assertEqual(code, 1)
            diagnostic = self._diagnostic(payload)
            self.assertEqual(diagnostic["code"], "artifact-not-found")
            self.assertEqual(
                diagnostic["remediation"], ["aart marketplace list --source reference"]
            )

    def test_the_four_causes_do_not_share_one_code(self) -> None:
        """The residue was three stressors collapsing onto one code; assert they now separate."""

        with _environment() as env:
            _configure_cold_source(env)
            codes = tuple(
                self._diagnostic(
                    env.run("marketplace", "install", *argv, "--profile", "claude", "--yes")[1]
                )["code"]
                for argv in (
                    ("ghost/skill/code-review",),
                    (_COLD,),
                    (_COLD, "--offline"),
                    ("reference/skill/absent",),
                )
            )

            self.assertEqual(
                codes,
                (
                    "source-unavailable",
                    "source-not-synchronized",
                    "source-not-synchronized",
                    "artifact-not-found",
                ),
            )
            # The two synchronization cases share a code deliberately — the layer is the same — but
            # must not share remediation, or `--offline` becomes invisible.
            self.assertNotEqual(
                self._diagnostic(
                    env.run("marketplace", "install", _COLD, "--profile", "claude", "--yes")[1]
                )["remediation"],
                self._diagnostic(
                    env.run(
                        "marketplace", "install", _COLD, "--profile", "claude", "--offline", "--yes"
                    )[1]
                )["remediation"],
            )

    def test_a_healthy_install_still_resolves(self) -> None:
        """The new classification runs on every failed match; prove it changed no success path."""

        with _environment() as env:
            _configure_cold_source(env)

            code, payload = env.run(
                "marketplace", "install", _COORDINATE, "--profile", "claude", "--yes"
            )

            self.assertEqual(code, 0, payload)
            self.assertTrue(payload["finalized"])


if __name__ == "__main__":
    unittest.main()
