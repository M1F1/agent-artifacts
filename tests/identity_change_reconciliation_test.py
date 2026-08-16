"""SI-4: an adopted identity change reconciles in the project, and `update` rebinds the record.

Live acceptance v2 `LAF-33`: `source resubscribe` adopts a new upstream identity, rebinds the
configuration and the snapshot store, and cannot touch installation records — project isolation
forbids it, and AART does not know which projects exist.  Every installation made under the old
identity therefore reported `source-unavailable` forever, `update` reported "selected canonical
installations were not found", and the resubscription review promised the opposite.

Design §2 resolves it by separating two things the record had conflated: the *subscription* (alias,
kind, origin, ref) is what resolution follows; the identity the origin declares is evidence carried
inside it.  These tests drive the whole shape through the real CLI — install under one identity,
adopt another, then reconcile in the project that owns the installation.
"""

from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

from tests.marketplace_lifecycle_e2e_test import _COORDINATE, _FIXTURE, _environment
from tests.source_project_isolation_test import _INSTALLED, _MANIFEST, _source, _stable_snapshot

_OLD_IDENTITY = "reference-native-source"
_NEW_IDENTITY = "renamed-reference-source"


class IdentityChangeReconciliationTest(unittest.TestCase):
    def _adopt_new_identity(self, env) -> None:
        """Rename the source's declared identity upstream, then adopt it with `resubscribe`."""

        document = env.source_location / "aart-source.json"
        identity = json.loads(document.read_text(encoding="utf-8"))
        self.assertEqual(identity["source_id"], _OLD_IDENTITY)
        identity["source_id"] = _NEW_IDENTITY
        document.write_text(json.dumps(identity, indent=2), encoding="utf-8")
        code, payload = _source(env, "source", "resubscribe", "--alias", "reference", "--yes")
        self.assertEqual(code, 0, payload)

    def _writable_source(self, root: Path) -> Path:
        copy = root / "writable-source"
        shutil.copytree(_FIXTURE, copy)
        return copy

    def test_status_names_the_identity_change_instead_of_reporting_it_unavailable(self) -> None:
        with _environment() as staging:
            source = self._writable_source(staging.root)
            with _environment(source) as env:
                env.run("marketplace", "install", _COORDINATE, "--profile", "claude", "--yes")
                self._adopt_new_identity(env)

                code, status = env.run("marketplace", "status", "--profile", "claude")

                self.assertEqual(code, 0, status)
                self.assertEqual([item["status"] for item in status["items"]], ["identity-changed"])
                detail = status["items"][0]["detail"]
                self.assertIn(_OLD_IDENTITY, detail)
                self.assertIn(_NEW_IDENTITY, detail)

    def test_the_resubscribe_itself_changes_nothing_beneath_the_project(self) -> None:
        """Design §2: the fix must not be `resubscribe` reaching into projects."""

        with _environment() as staging:
            source = self._writable_source(staging.root)
            with _environment(source) as env:
                env.run("marketplace", "install", _COORDINATE, "--profile", "claude", "--yes")
                before = _stable_snapshot(env.project)
                self.assertIn(str(_MANIFEST), before)

                self._adopt_new_identity(env)

                self.assertEqual(_stable_snapshot(env.project), before)

    def test_the_update_review_states_both_identities_and_writes_nothing(self) -> None:
        with _environment() as staging:
            source = self._writable_source(staging.root)
            with _environment(source) as env:
                env.run("marketplace", "install", _COORDINATE, "--profile", "claude", "--yes")
                self._adopt_new_identity(env)
                before = _stable_snapshot(env.project)

                code, review = env.run("marketplace", "update", "--profile", "claude")

                self.assertEqual(code, 0, review)
                self.assertFalse(review["finalized"])
                transitions = [item["identity_transition"] for item in review["review"]["items"]]
                self.assertEqual(transitions, [f"{_OLD_IDENTITY}:{_NEW_IDENTITY}"])
                self.assertEqual(_stable_snapshot(env.project), before)

    def test_update_rebinds_the_record_and_the_next_status_is_current(self) -> None:
        with _environment() as staging:
            source = self._writable_source(staging.root)
            with _environment(source) as env:
                env.run("marketplace", "install", _COORDINATE, "--profile", "claude", "--yes")
                self._adopt_new_identity(env)

                code, applied = env.run("marketplace", "update", "--profile", "claude", "--yes")

                self.assertEqual(code, 0, applied)
                self.assertTrue(applied["finalized"])
                manifest = json.loads((env.project / _MANIFEST).read_text(encoding="utf-8"))
                declared = {record["source"]["declared_id"] for record in manifest["installations"]}
                self.assertEqual(declared, {_NEW_IDENTITY})

                code, status = env.run("marketplace", "status", "--profile", "claude")
                self.assertEqual(code, 0, status)
                self.assertEqual([item["status"] for item in status["items"]], ["current"])
                self.assertTrue((env.project / _INSTALLED / "SKILL.md").is_file())

    def test_the_reviewed_rebinding_is_digest_bound(self) -> None:
        """A rebinding to a third identity must not be applied under consent read for the second."""

        with _environment() as staging:
            source = self._writable_source(staging.root)
            with _environment(source) as env:
                env.run("marketplace", "install", _COORDINATE, "--profile", "claude", "--yes")
                self._adopt_new_identity(env)
                _, review = env.run("marketplace", "update", "--profile", "claude")
                reviewed = review["review_digest"]

                document = env.source_location / "aart-source.json"
                identity = json.loads(document.read_text(encoding="utf-8"))
                identity["source_id"] = "third-reference-source"
                document.write_text(json.dumps(identity, indent=2), encoding="utf-8")
                _source(env, "source", "resubscribe", "--alias", "reference", "--yes")

                code, refused = env.run(
                    "marketplace",
                    "update",
                    "--profile",
                    "claude",
                    "--expect",
                    reviewed,
                    "--yes",
                )

                self.assertEqual(code, 1, refused)
                self.assertFalse(refused["finalized"])
                manifest = json.loads((env.project / _MANIFEST).read_text(encoding="utf-8"))
                declared = {record["source"]["declared_id"] for record in manifest["installations"]}
                self.assertEqual(declared, {_OLD_IDENTITY})

    def test_rs07_status_reports_the_project_when_the_only_subscription_is_removed(self) -> None:
        """`RS-07`: the project still has installations, and `status` is what reads them.

        The removal here is the one `source remove` tells an operator to take. Before this, the
        next `status` refused with `no-source-configured` — a message about the *configuration*
        when the question was about the *project*, and one an operator can do nothing with while
        their installed artifacts sit on disk.
        """

        with _environment() as staging:
            source = self._writable_source(staging.root)
            with _environment(source) as env:
                env.run("marketplace", "install", _COORDINATE, "--profile", "claude", "--yes")
                _source(env, "source", "remove", "--alias", "reference", "--yes")

                code, status = env.run("marketplace", "status", "--profile", "claude")

                self.assertEqual(code, 0, status)
                self.assertEqual(
                    [item["status"] for item in status["items"]], ["source-unavailable"]
                )
                self.assertTrue((env.project / _INSTALLED / "SKILL.md").is_file())

    def test_a_removed_subscription_is_still_source_unavailable(self) -> None:
        """The split must not turn a gone subscription into an identity question."""

        with _environment() as staging:
            source = self._writable_source(staging.root)
            with _environment(source) as env:
                env.run("marketplace", "install", _COORDINATE, "--profile", "claude", "--yes")
                # A second subscription, so this case stays what it is about: one subscription
                # gone while another survives. `RS-07` covers the empty case separately.
                mirror = self._writable_source(env.root)
                identity = json.loads((mirror / "aart-source.json").read_text(encoding="utf-8"))
                identity["source_id"] = "mirror-reference-source"
                (mirror / "aart-source.json").write_text(json.dumps(identity), encoding="utf-8")
                _source(
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
                _source(env, "source", "remove", "--alias", "reference", "--yes")

                code, status = env.run("marketplace", "status", "--profile", "claude")

                self.assertEqual(code, 0, status)
                self.assertEqual(
                    [item["status"] for item in status["items"]], ["source-unavailable"]
                )


if __name__ == "__main__":
    unittest.main()
