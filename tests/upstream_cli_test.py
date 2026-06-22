"""CLI wiring tests for the nested ``upstream`` maintainer command."""

import unittest
from unittest.mock import patch

from agent_artifacts import cli
from agent_artifacts.model import Request


def _recorder(code: int = 0):
    calls = []

    def run(request: Request) -> int:
        calls.append(request)
        return code

    run.calls = calls  # type: ignore[attr-defined]
    return run


def _dispatch(argv, code=0):
    rec = _recorder(code)
    with patch.dict(cli.DISPATCH, {"upstream": rec}):
        rc = cli.main(argv)
    return rc, rec.calls[0] if rec.calls else None  # type: ignore[attr-defined]


class UpstreamCliTests(unittest.TestCase):
    def test_upstream_check_maps_request(self):
        rc, req = _dispatch([
            "upstream", "check",
            "--all",
            "--type", "skill",
            "--bundle", "base",
            "--source", "/catalog",
            "--json",
        ])

        self.assertEqual(rc, 0)
        self.assertEqual(req.command, "upstream")
        self.assertEqual(req.upstream_action, "check")
        self.assertTrue(req.all)
        self.assertEqual(req.type_filter, "skill")
        self.assertEqual(req.bundles, ("base",))
        self.assertEqual(req.source_dir, "/catalog")
        self.assertTrue(req.json)

    def test_upstream_update_maps_request(self):
        rc, req = _dispatch([
            "upstream", "update",
            "skill/code-review",
            "--bundle", "backend",
            "--dry-run",
            "--force",
            "--json",
        ])

        self.assertEqual(rc, 0)
        self.assertEqual(req.command, "upstream")
        self.assertEqual(req.upstream_action, "update")
        self.assertEqual(req.names, ("skill/code-review",))
        self.assertEqual(req.bundles, ("backend",))
        self.assertTrue(req.dry_run)
        self.assertTrue(req.force)
        self.assertTrue(req.json)


if __name__ == "__main__":
    unittest.main()
