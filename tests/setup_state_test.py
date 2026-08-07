"""Issue #20: redacted, scope-local setup state contracts."""

from __future__ import annotations

import unittest

from agent_artifacts.model import SetupState, SetupStateRecord
from agent_artifacts.setup import dump_setup_state, parse_setup_state, setup_state_path


class SetupStateTests(unittest.TestCase):
    def test_round_trip_is_deterministic_and_multi_profile(self):
        records = tuple(
            SetupStateRecord(
                artifact_type="mcp",
                artifact_name="atlassian",
                profile=profile,
                scope="user",
                status="configured",
                detail="Configured",
                source_label="pin:abc",
                installer_hash="a" * 64,
                plan_hash="b" * 64,
                retry_command="",
                rollback_command=f"aart setup rollback mcp/atlassian --profile {profile} --scope user",
            )
            for profile in ("tabnine", "claude")
        )
        state = SetupState(records)

        text = dump_setup_state(state)
        parsed = parse_setup_state(text)

        self.assertEqual(parsed.value, state)
        self.assertEqual(text, dump_setup_state(parsed.value))

    def test_serializer_rejects_secret_shaped_content(self):
        canary = "aart-secret-canary-123"
        state = SetupState(
            (
                SetupStateRecord(
                    "mcp",
                    "atlassian",
                    "tabnine",
                    "user",
                    "configured",
                    f"token={canary}",
                ),
            )
        )

        result = dump_setup_state(state)

        self.assertNotIn(canary, result)
        self.assertIn("[redacted]", result)

    def test_state_path_reuses_scope_root(self):
        self.assertEqual(
            setup_state_path("/fake-home"),
            "/fake-home/.agent-artifacts/setup-state.json",
        )


if __name__ == "__main__":
    unittest.main()
