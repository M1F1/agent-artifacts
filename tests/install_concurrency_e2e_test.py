from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from agent_artifacts.domain.result import Ok
from agent_artifacts.install_state.schema import parse_install_state
from agent_artifacts.installation.application import finalize_install, prepare_install
from agent_artifacts.installation.io import LocalInstallAdapter
from agent_artifacts.installation.model import InstallStatus
from agent_artifacts.profiles.builtin import builtin
from tests.canonical_install_application_test import _fixture


class InstallConcurrencyE2ETest(unittest.TestCase):
    def test_two_reviewed_installs_converge_without_lost_state_or_partial_payload(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project, paths, location, request, catalog, effective = _fixture(Path(raw), "skill")
            first = prepare_install(
                request,
                catalog,
                effective,
                builtin()["claude"],
                location,
                paths,
                LocalInstallAdapter(),
            )
            second = prepare_install(
                request,
                catalog,
                effective,
                builtin()["claude"],
                location,
                paths,
                LocalInstallAdapter(),
            )
            assert isinstance(first, Ok)
            assert isinstance(second, Ok)
            barrier = threading.Barrier(2)
            outcomes = []

            def finalize(plan) -> None:
                barrier.wait()
                outcomes.append(
                    finalize_install(
                        plan,
                        plan.review_digest,
                        catalog,
                        effective,
                        LocalInstallAdapter(),
                    )
                )

            threads = (
                threading.Thread(target=finalize, args=(first.value,)),
                threading.Thread(target=finalize, args=(second.value,)),
            )
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)

            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual(len(outcomes), 2)
            self.assertTrue(all(isinstance(outcome, Ok) for outcome in outcomes))
            statuses = tuple(
                outcome.value.status for outcome in outcomes if isinstance(outcome, Ok)
            )
            self.assertEqual(statuses.count(InstallStatus.APPLIED), 1)
            self.assertTrue(
                set(statuses).issubset(
                    {InstallStatus.APPLIED, InstallStatus.CONFLICTED, InstallStatus.FAILED}
                )
            )
            destination = project / ".claude/skills/review/SKILL.md"
            state_path = project / ".agent-artifacts/manifest.json"
            self.assertEqual(destination.read_text(encoding="utf-8"), "# Installed\n")
            state = parse_install_state(state_path.read_bytes(), path=str(state_path))
            assert isinstance(state, Ok)
            self.assertEqual(len(state.value.installations), 1)


if __name__ == "__main__":
    unittest.main()
