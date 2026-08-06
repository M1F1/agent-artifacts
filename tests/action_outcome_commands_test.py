"""Cross-command structured outcome contracts for issue #17."""

from __future__ import annotations

import contextlib
import io
import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock

from agent_artifacts import executor
from agent_artifacts.commands import install, uninstall, update
from agent_artifacts.model import Request

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"


def _capture(command, request: Request) -> tuple[int, dict]:
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = command.run(request)
    return code, json.loads(output.getvalue())


class ConsumerOutcomeContractTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = pathlib.Path(self.temp.name) / "project"
        self.project.mkdir()

    def _request(self, command: str, **changes) -> Request:
        values = {
            "command": command,
            "names": ("code-review",),
            "profiles": ("claude",),
            "source_dir": str(FIXTURES),
            "project": str(self.project),
            "json": True,
        }
        values.update(changes)
        return Request(**values)

    def test_install_reinstall_and_actual_mode_share_the_json_contract(self):
        first_code, first = _capture(install, self._request("install"))
        second_code, second = _capture(install, self._request("install"))

        self.assertEqual((first_code, second_code), (0, 0))
        self.assertEqual(first["summary"]["selected"], 1)
        self.assertEqual(first["summary"]["items"][0]["status"], "installed")
        self.assertEqual(first["summary"]["items"][0]["mode"], "copy")
        self.assertEqual(second["summary"]["items"][0]["status"], "reinstalled")
        self.assertEqual(second["summary"]["items"][0]["mode"], "copy")

    def test_noop_update_is_not_an_empty_selection(self):
        _capture(install, self._request("install"))

        current_code, current = _capture(update, self._request("update"))
        empty_code, empty = _capture(
            update,
            self._request("update", names=("does-not-exist",)),
        )

        self.assertEqual((current_code, empty_code), (0, 0))
        self.assertEqual(current["summary"]["selected"], 1)
        self.assertEqual(current["summary"]["changed"], 0)
        self.assertEqual(current["summary"]["items"][0]["status"], "up_to_date")
        self.assertEqual(empty["summary"]["selected"], 0)
        self.assertEqual(empty["summary"]["items"], [])

    def test_update_with_local_drift_is_skipped_not_reported_current(self):
        _capture(
            install,
            self._request("install", names=("python-style",), profiles=("tabnine",)),
        )
        managed = self.project / ".tabnine" / "guidelines" / "python-style.md"
        managed.write_text("local edit", encoding="utf-8")

        code, payload = _capture(
            update,
            self._request("update", names=("python-style",), profiles=("tabnine",)),
        )

        self.assertEqual(code, 0)
        self.assertEqual(payload["summary"]["changed"], 0)
        self.assertEqual(payload["summary"]["items"][0]["status"], "skipped")
        self.assertIn("kept local changes", payload["summary"]["items"][0]["detail"])

    def test_update_prune_reports_the_removed_manifest_entry(self):
        _capture(install, self._request("install"))
        _capture(
            install,
            self._request("install", names=("python-style",), profiles=("tabnine",)),
        )

        code, payload = _capture(
            update,
            self._request("update", names=("code-review",), prune=True),
        )

        self.assertEqual(code, 0)
        self.assertEqual(payload["summary"]["selected"], 2)
        self.assertEqual(
            {item["key"]: item["status"] for item in payload["summary"]["items"]},
            {
                "skill/code-review@claude": "up_to_date",
                "guideline/python-style@tabnine": "removed",
            },
        )
        manifest = json.loads(
            (self.project / ".agent-artifacts" / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual([entry["artifact"] for entry in manifest["installed"]], ["code-review"])

    def test_uninstall_reports_removed_entry_and_already_missing_managed_path(self):
        _capture(install, self._request("install"))
        managed = self.project / ".claude" / "skills" / "code-review"
        for path in sorted(managed.rglob("*"), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()
        managed.rmdir()

        code, payload = _capture(
            uninstall,
            self._request("uninstall", source_dir=None),
        )

        self.assertEqual(code, 0)
        self.assertEqual(payload["summary"]["selected"], 1)
        self.assertEqual(payload["summary"]["counts"]["removed"], 1)
        self.assertEqual(payload["summary"]["counts"]["already_absent"], 1)
        self.assertEqual(len(payload["removed_entries"]), 1)

    def test_install_effect_failure_is_nonzero_and_does_not_claim_manifest_success(self):
        destination = os.path.join(str(self.project), ".claude", "skills", "code-review")
        failed_report = executor.Report(
            performed=(),
            warnings=("copy failed",),
            manifest_written=False,
            observations=(
                executor.EffectObservation(
                    operation="copy-tree",
                    target=destination,
                    state="failed",
                    detail="permission denied",
                ),
            ),
        )

        with mock.patch.object(install.executor, "execute", return_value=failed_report):
            outcome = install.execute(self._request("install", json=False))

        self.assertEqual(outcome.exit_code, 1)
        self.assertEqual(outcome.summary.items[0].status, "failed")
        manifest_path = self.project / ".agent-artifacts" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["installed"], [])

    def test_partial_install_separates_success_and_failure_and_persists_only_success(self):
        skill_destination = os.path.join(str(self.project), ".claude", "skills", "code-review")
        guideline_destination = os.path.join(
            str(self.project), ".claude", "guidelines", "python-style.md"
        )
        partial_report = executor.Report(
            performed=(f"write_file {guideline_destination}",),
            warnings=("copy failed",),
            manifest_written=False,
            observations=(
                executor.EffectObservation(
                    "copy-tree",
                    skill_destination,
                    "failed",
                    "permission denied",
                ),
                executor.EffectObservation(
                    "write-file",
                    guideline_destination,
                    "changed",
                ),
            ),
        )

        request = self._request(
            "install",
            names=("code-review", "python-style"),
            json=False,
        )
        with mock.patch.object(install.executor, "execute", return_value=partial_report):
            outcome = install.execute(request)

        self.assertEqual(outcome.exit_code, 1)
        self.assertEqual(
            {item.artifact: item.status for item in outcome.summary.items},
            {"code-review": "failed", "python-style": "installed"},
        )
        manifest_path = self.project / ".agent-artifacts" / "manifest.json"
        installed = json.loads(manifest_path.read_text(encoding="utf-8"))["installed"]
        self.assertEqual([entry["artifact"] for entry in installed], ["python-style"])

    def test_manifest_write_failure_is_reported_as_failure(self):
        with mock.patch.object(
            install._common,
            "save_manifest",
            side_effect=PermissionError("manifest denied"),
        ):
            outcome = install.execute(self._request("install", json=False))

        self.assertEqual(outcome.exit_code, 1)
        self.assertEqual(outcome.summary.items[0].status, "failed")
        self.assertTrue(any("manifest denied" in warning for warning in outcome.summary.warnings))

    def test_unreadable_merge_config_is_failure_and_keeps_manifest_entry(self):
        _capture(
            install,
            self._request("install", names=("postgres",), profiles=("claude",)),
        )
        (self.project / ".mcp.json").write_text("{broken", encoding="utf-8")

        code, payload = _capture(
            uninstall,
            self._request(
                "uninstall",
                names=("postgres",),
                profiles=("claude",),
                source_dir=None,
            ),
        )

        self.assertEqual(code, 1)
        self.assertEqual(payload["summary"]["items"][0]["status"], "failed")
        manifest = json.loads(
            (self.project / ".agent-artifacts" / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual([entry["artifact"] for entry in manifest["installed"]], ["postgres"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
