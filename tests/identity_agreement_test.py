"""SI-5: the consumer refuses a registry whose two identity documents disagree.

Live acceptance v2 `LAF-37`: a registry whose `aart-registry.json` and `aart-source.json` declare
different identities is refused by `registry validate --strict --frozen` — the publisher's own gate —
and accepted by every consumer path. The value the entire subscription model pins is the one no
consumer-side check looked at.

Design §2's second half applies the one-way adaptation rule: a consumer does not soften a rule the
publisher's tooling already enforces. The agreement is now checked at acquisition, whenever a
snapshot carries both documents, on the direct/local path as well as the registry path.
"""

from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

from tests.marketplace_lifecycle_e2e_test import _COORDINATE, _FIXTURE, _environment
from tests.source_project_isolation_test import _source

_DECLARED = "reference-native-source"
_DISAGREEING = "some-other-identity"


def _registry_document(registry_id: str) -> str:
    """A valid `aart-registry.json` at one chosen identity.

    It must actually parse: the agreement check has nothing to compare against a malformed registry
    marker, so a document short of the schema's required fields would make these tests pass for the
    wrong reason.
    """

    return json.dumps(
        {
            "schema_version": 1,
            "protocol_version": 1,
            "registry_id": registry_id,
            "display_name": "Reference Registry",
            "requires_aart": {"min_inclusive": "1.0.0", "max_exclusive": "3.0.0"},
            "required_capabilities": ["artifact-manifest-v1"],
            "default_channel": "main",
            "services": {},
        },
        indent=2,
    )


class IdentityAgreementTest(unittest.TestCase):
    def _source_copy(self, root: Path, name: str) -> Path:
        copy = root / name
        shutil.copytree(_FIXTURE, copy)
        return copy

    def test_a_source_publishing_only_aart_source_json_is_unaffected(self) -> None:
        """The check must not turn every ordinary native source into a registry."""

        with _environment() as env:
            self.assertFalse((env.source_location / "aart-registry.json").exists())

            code, payload = env.run(
                "marketplace", "install", _COORDINATE, "--profile", "claude", "--yes"
            )

            self.assertEqual(code, 0, payload)

    def test_agreeing_identity_documents_are_accepted(self) -> None:
        with _environment() as staging:
            source = self._source_copy(staging.root, "agreeing-source")
            (source / "aart-registry.json").write_text(
                _registry_document(_DECLARED), encoding="utf-8"
            )

            with _environment(source) as env:
                code, payload = env.run(
                    "marketplace", "install", _COORDINATE, "--profile", "claude", "--yes"
                )

                self.assertEqual(code, 0, payload)

    def test_source_sync_refuses_disagreeing_identity_documents(self) -> None:
        with _environment() as staging:
            source = self._source_copy(staging.root, "disagreeing-source")

            with _environment(source) as env:
                # Synchronized once while the documents agreed, so the refusal below is the sync
                # itself and not a first-acquisition failure.
                (source / "aart-registry.json").write_text(
                    _registry_document(_DISAGREEING), encoding="utf-8"
                )

                code, payload = _source(env, "source", "sync", "--alias", "reference")

                self.assertEqual(code, 1, payload)
                self.assertFalse(payload["sources"][0]["ok"], payload)
                diagnostic = self._only_diagnostic(payload["sources"][0])
                self.assertEqual(diagnostic["code"], "source-invalid")
                self.assertIn("aart-registry.json", diagnostic["message"])
                self.assertIn("aart-source.json", diagnostic["message"])
                self.assertIn(_DECLARED, diagnostic["message"])
                self.assertIn(_DISAGREEING, diagnostic["message"])
                self.assertTrue(diagnostic["remediation"], diagnostic)

    def test_source_add_refuses_disagreeing_identity_documents(self) -> None:
        with _environment() as env:
            mirror = self._source_copy(env.root, "disagreeing-mirror")
            (mirror / "aart-registry.json").write_text(
                _registry_document(_DISAGREEING), encoding="utf-8"
            )

            code, payload = _source(
                env,
                "source",
                "add",
                "--alias",
                "mirror",
                "--kind",
                "source-local",
                "--location",
                str(mirror),
            )

            self.assertEqual(code, 1, payload)
            diagnostic = self._only_diagnostic(payload)
            self.assertEqual(diagnostic["code"], "source-invalid")
            self.assertIn(_DISAGREEING, diagnostic["message"])
            # A refused subscription is not a subscription: nothing may be left configured.
            _, listed = _source(env, "source", "list")
            self.assertNotIn("mirror", [item["alias"] for item in listed["sources"]])

    def test_rs08_a_registry_marker_that_does_not_parse_is_refused(self) -> None:
        """`RS-08`: the skipped check, taken as its own decision.

        `SI-5` compared the two identities only when both documents parsed, so a source shaped like
        a registry whose `aart-registry.json` is broken was admitted in silence — the one file that
        declares the identity the whole subscription model pins went unread, and nothing said so.
        A marker that is present must parse; there is no third state where it is ignored.
        """

        with _environment() as env:
            mirror = self._source_copy(env.root, "broken-marker-mirror")
            (mirror / "aart-registry.json").write_text(
                json.dumps({"schema_version": 1, "registry_id": _DECLARED}), encoding="utf-8"
            )

            code, payload = _source(
                env,
                "source",
                "add",
                "--alias",
                "mirror",
                "--kind",
                "source-local",
                "--location",
                str(mirror),
            )

            self.assertEqual(code, 1, payload)
            diagnostic = self._only_diagnostic(payload)
            self.assertEqual(diagnostic["code"], "source-invalid")
            self.assertIn("aart-registry.json", diagnostic["message"])
            self.assertIn("does not parse", diagnostic["message"])
            self.assertTrue(diagnostic["remediation"], diagnostic)
            _, listed = _source(env, "source", "list")
            self.assertNotIn("mirror", [item["alias"] for item in listed["sources"]])

    def test_rs08_a_marker_that_is_not_json_at_all_is_refused(self) -> None:
        with _environment() as env:
            mirror = self._source_copy(env.root, "not-json-mirror")
            (mirror / "aart-registry.json").write_text("this is not a registry", encoding="utf-8")

            code, payload = _source(
                env,
                "source",
                "add",
                "--alias",
                "mirror",
                "--kind",
                "source-local",
                "--location",
                str(mirror),
            )

            self.assertEqual(code, 1, payload)
            self.assertIn("does not parse", self._only_diagnostic(payload)["message"])

    def test_rs08_a_marker_broken_after_subscription_is_refused_by_sync(self) -> None:
        """The subscription is re-validated on every sync, so the gap closes on both paths."""

        with _environment() as staging:
            source = self._source_copy(staging.root, "breaking-marker-source")

            with _environment(source) as env:
                (source / "aart-registry.json").write_text("{", encoding="utf-8")

                code, payload = _source(env, "source", "sync", "--alias", "reference")

                self.assertEqual(code, 1, payload)
                self.assertFalse(payload["sources"][0]["ok"], payload)
                diagnostic = self._only_diagnostic(payload["sources"][0])
                self.assertEqual(diagnostic["code"], "source-invalid")
                self.assertIn("does not parse", diagnostic["message"])

    def test_rs08_a_parseable_marker_that_agrees_is_still_accepted(self) -> None:
        """The new refusal must not be a second way to reject a healthy registry."""

        with _environment() as staging:
            source = self._source_copy(staging.root, "still-fine-source")
            (source / "aart-registry.json").write_text(
                _registry_document(_DECLARED), encoding="utf-8"
            )

            with _environment(source) as env:
                code, payload = env.run(
                    "marketplace", "install", _COORDINATE, "--profile", "claude", "--yes"
                )

                self.assertEqual(code, 0, payload)

    def _only_diagnostic(self, payload) -> dict:
        diagnostics = payload["diagnostics"]
        self.assertEqual(len(diagnostics), 1, payload)
        return diagnostics[0]


if __name__ == "__main__":
    unittest.main()
