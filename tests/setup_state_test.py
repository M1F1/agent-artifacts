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

    def test_canonical_evidence_is_all_or_nothing_and_strictly_typed(self):
        incomplete = SetupState(
            (
                SetupStateRecord(
                    "mcp",
                    "atlassian",
                    "tabnine",
                    "user",
                    "configured",
                    "Configured",
                    object_digest="sha256:" + "a" * 64,
                ),
            )
        )
        with self.assertRaisesRegex(ValueError, "evidence"):
            dump_setup_state(incomplete)

        malformed = (
            '{"version":1,"records":[{"artifact_type":"mcp",'
            '"artifact_name":"atlassian","profile":"tabnine","scope":"user",'
            '"status":"configured","object_digest":"token=synthetic-canary"}]}'
        )
        parsed = parse_setup_state(malformed)
        self.assertEqual(parsed.code, 5)
        self.assertIn("evidence", parsed.reason)
        self.assertNotIn("synthetic-canary", parsed.reason)


if __name__ == "__main__":
    unittest.main()
