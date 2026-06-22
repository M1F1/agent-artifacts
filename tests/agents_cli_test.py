"""WP-30 tests: CLI/TUI surface for the `agents` artifact type.

Pure wiring (mirrors cli_test.py): the install/list handler is stubbed via ``cli.DISPATCH`` so
we assert only that argv maps onto the right :class:`Request` fields — ``--agents-mode`` ->
``Request.agents_mode``, ``--type agents`` accepted -> ``type_filter`` — and that the TUI's
display order knows the new type. No command logic runs.

Run: ``python -m unittest discover -s tests -p "agents_cli_test.py" -v``
"""

import contextlib
import io
import unittest
from unittest.mock import patch

from agent_artifacts import cli, tui


def _dispatch(argv, *, command, code=0):
    """Run ``cli.main(argv)`` with ``command``'s handler stubbed; return (rc, captured Request)."""
    calls = []

    def run(request):
        calls.append(request)
        return code

    with patch.dict(cli.DISPATCH, {command: run}):
        rc = cli.main(argv)
    return rc, (calls[0] if calls else None)


class TestAgentsModeFlag(unittest.TestCase):
    def test_agents_mode_maps_to_request(self):
        for mode in ("replace", "prepend", "append", "skip"):
            with self.subTest(mode=mode):
                _, req = _dispatch(
                    ["install", "house", "--profile", "claude", "--source", ".",
                     "--agents-mode", mode],
                    command="install",
                )
                self.assertEqual(req.agents_mode, mode)

    def test_agents_mode_defaults_to_none(self):
        # Absent flag -> None, so the planner applies the "prepend" default (DESIGN-agents §3.4).
        _, req = _dispatch(
            ["install", "house", "--profile", "claude", "--source", "."],
            command="install",
        )
        self.assertIsNone(req.agents_mode)

    def test_invalid_agents_mode_is_usage_error(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                cli.build_parser().parse_args(["install", "x", "--agents-mode", "bogus"])
        self.assertEqual(ctx.exception.code, 2)


class TestTypeFilterAgents(unittest.TestCase):
    def test_list_accepts_type_agents(self):
        _, req = _dispatch(["list", "--type", "agents", "--source", "."], command="list")
        self.assertEqual(req.type_filter, "agents")

    def test_agents_in_cli_type_choices(self):
        self.assertIn("agents", cli._ARTIFACT_TYPES)


class TestTuiKnowsAgents(unittest.TestCase):
    def test_type_order_includes_agents(self):
        self.assertIn("agents", tui._TYPE_ORDER)

    def test_agents_rank_is_stable(self):
        # A defined rank, not the fall-through len() default reserved for unknown types.
        self.assertEqual(tui._type_rank("agents"), tui._TYPE_ORDER.index("agents"))


if __name__ == "__main__":
    unittest.main()
