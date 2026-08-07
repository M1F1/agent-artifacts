from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.io.store_lock import acquire_store_lock, release_store_lock
from agent_artifacts.store.model import StoreLockLease, StoreLockRequest


class StoreLockAdapterTest(unittest.TestCase):
    def test_store_lock_serializes_and_preserves_nominal_lease_type(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            lock = str(Path(root) / "store.lock")
            request = StoreLockRequest(lock, timeout_seconds=0.01, stale_after_seconds=60)
            first = acquire_store_lock(request)
            self.assertIsInstance(first, Ok)
            assert isinstance(first, Ok)
            self.assertIsInstance(first.value, StoreLockLease)

            busy = acquire_store_lock(request)
            self.assertIsInstance(busy, Err)
            self.assertIsInstance(release_store_lock(StoreLockLease(lock, "wrong")), Err)
            self.assertEqual(release_store_lock(first.value), Ok(None))


if __name__ == "__main__":
    unittest.main()
