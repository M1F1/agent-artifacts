"""WP-2 update-policy tests: one case per docs/design/DESIGN.md §9 decision-table row + the --force path."""

import unittest

from agent_artifacts import policy
from agent_artifacts.model import RemovePath, Warn, WriteFile

A = "h_disk"  # an on-disk hash
B = "h_base"  # the hash recorded at install
N = "h_new"  # the incoming hash


class ClassifyTests(unittest.TestCase):
    # --- new is present -------------------------------------------------- #
    def test_missing_locally_creates(self):
        self.assertEqual(policy.classify(None, B, N), "create")
        self.assertEqual(policy.classify(None, None, N), "create")

    def test_clean_and_current_is_noop(self):
        self.assertEqual(policy.classify(B, B, B), "noop")

    def test_clean_with_new_upstream_overwrites(self):
        self.assertEqual(policy.classify(B, B, N), "overwrite")

    def test_local_drift_unchanged_upstream_keeps_drift(self):
        self.assertEqual(policy.classify(A, B, B), "keep-drift")

    def test_local_drift_and_new_upstream_conflicts(self):
        self.assertEqual(policy.classify(A, B, N), "conflict")

    def test_unmanaged_file_matching_new_is_noop(self):
        # base is None (never installed by us) but disk already equals new
        self.assertEqual(policy.classify(N, None, N), "noop")

    def test_unmanaged_file_differing_from_new_conflicts(self):
        self.assertEqual(policy.classify(A, None, N), "conflict")

    # --- new is gone upstream ------------------------------------------- #
    def test_removed_upstream_clean_removes(self):
        self.assertEqual(policy.classify(B, B, None), "remove")

    def test_removed_upstream_with_drift_keeps_local(self):
        self.assertEqual(policy.classify(A, B, None), "keep-drift")

    def test_removed_upstream_already_absent_is_noop(self):
        self.assertEqual(policy.classify(None, B, None), "noop")


class DecisionActionTests(unittest.TestCase):
    def test_create_and_overwrite_write(self):
        self.assertEqual(
            policy.decision_action("create", "f.txt", b"data"),
            (WriteFile(path="f.txt", content=b"data"),),
        )
        self.assertEqual(
            policy.decision_action("overwrite", "f.txt", b"data"),
            (WriteFile(path="f.txt", content=b"data"),),
        )

    def test_noop_emits_nothing(self):
        self.assertEqual(policy.decision_action("noop", "f.txt", b"x"), ())

    def test_remove_emits_removepath(self):
        self.assertEqual(
            policy.decision_action("remove", "f.txt", None),
            (RemovePath(path="f.txt"),),
        )

    def test_keep_drift_warns_only(self):
        actions = policy.decision_action("keep-drift", "f.txt", b"x")
        self.assertEqual(len(actions), 1)
        self.assertIsInstance(actions[0], Warn)

    def test_conflict_without_force_writes_sidecar_and_warns(self):
        actions = policy.decision_action("conflict", "f.txt", b"new")
        self.assertEqual(
            actions[0],
            WriteFile(path="f.txt" + policy.NEW_SUFFIX, content=b"new"),
        )
        self.assertIsInstance(actions[1], Warn)
        self.assertNotIn(WriteFile(path="f.txt", content=b"new"), actions)  # original untouched

    def test_conflict_with_force_overwrites_original_and_warns(self):
        actions = policy.decision_action("conflict", "f.txt", b"new", force=True)
        self.assertEqual(actions[0], WriteFile(path="f.txt", content=b"new"))
        self.assertIsInstance(actions[1], Warn)

    def test_none_content_becomes_empty_bytes(self):
        self.assertEqual(
            policy.decision_action("create", "f.txt", None),
            (WriteFile(path="f.txt", content=b""),),
        )


if __name__ == "__main__":
    unittest.main()
