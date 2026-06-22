"""Contract tests for maintainer-side upstream tracking.

TDD note: these tests intentionally land before the upstream modules/fields exist. The first
run should fail on the missing contract, then implementation makes it green.
"""

import unittest

from agent_artifacts.model import Request


class UpstreamContractTests(unittest.TestCase):
    def test_request_carries_nested_upstream_action(self):
        req = Request(command="upstream", upstream_action="check")
        self.assertEqual(req.upstream_action, "check")

    def test_upstream_modules_export_contract_stubs(self):
        from agent_artifacts import upstream_planner, upstream_source, upstreams

        for name in (
            "UpstreamKey",
            "UpstreamSource",
            "UpstreamSync",
            "UpstreamEntry",
            "UpstreamCatalog",
            "parse_upstreams",
            "dump_upstreams",
            "select_upstreams",
        ):
            self.assertTrue(hasattr(upstreams, name), name)

        for name in ("ResolvedUpstream", "resolve_upstream_source", "hash_upstream_path"):
            self.assertTrue(hasattr(upstream_source, name), name)

        for name in ("UpstreamStatus", "plan_upstream_check", "plan_upstream_update"):
            self.assertTrue(hasattr(upstream_planner, name), name)


if __name__ == "__main__":
    unittest.main()
