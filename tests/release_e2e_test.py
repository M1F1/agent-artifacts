from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.reference_registry_export_e2e_test import APPROVED_ORIGIN, _committed_source
from tests.versioning_test import ROOT, _load_script

REFERENCE_ORIGIN = "https://github.com/M1F1/agent-artifacts-registry.git"


class ReleaseE2ETest(unittest.TestCase):
    def test_fresh_reference_export_passes_the_complete_stable_release_checklist(self) -> None:
        release = _load_script("release")
        exporter = _load_script("prepare_reference_registry")
        with tempfile.TemporaryDirectory() as raw:
            temporary = Path(raw)
            source, commit = _committed_source(temporary)
            registry = temporary / "reference-registry"
            self.assertEqual(
                exporter.main(
                    (
                        "--source-checkout",
                        str(source),
                        "--source-commit",
                        commit,
                        "--destination",
                        str(registry),
                    )
                ),
                0,
            )
            subprocess.run(
                ("git", "-C", str(registry), "add", "."),
                check=True,
            )
            subprocess.run(
                (
                    "git",
                    "-C",
                    str(registry),
                    "-c",
                    "user.name=AART Release Test",
                    "-c",
                    "user.email=release-test@example.invalid",
                    "commit",
                    "-qm",
                    "Export reference registry",
                ),
                check=True,
            )
            subprocess.run(
                ("git", "-C", str(registry), "remote", "add", "origin", REFERENCE_ORIGIN),
                check=True,
            )
            subprocess.run(
                ("git", "-C", str(registry), "update-ref", "refs/remotes/origin/HEAD", "HEAD"),
                check=True,
            )

            def exported_remote_head(command, cwd, environment, timeout_seconds):
                if cwd == registry and command == (
                    "git",
                    "ls-remote",
                    "--symref",
                    "origin",
                    "HEAD",
                ):
                    commit = subprocess.check_output(
                        ("git", "-C", str(registry), "rev-parse", "HEAD"),
                        text=True,
                    ).strip()
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        f"ref: refs/heads/main\tHEAD\n{commit}\tHEAD\n",
                        "",
                    )
                return release._run_process(command, cwd, environment, timeout_seconds)

            receipt = release.check_release(
                ROOT,
                registry,
                process_runner=exported_remote_head,
                require_clean=False,
                require_main=False,
            )

        self.assertEqual(receipt["status"], "passed", receipt)
        self.assertEqual(receipt["version"], "1.0.0")
        self.assertTrue(all(item["passed"] for item in receipt["checks"]))
        self.assertNotEqual(commit, "0" * 40)
        self.assertEqual(APPROVED_ORIGIN, "https://github.com/M1F1/agent-artifacts.git")


if __name__ == "__main__":
    unittest.main()
