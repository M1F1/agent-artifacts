"""WP-30 tests: CLI/TUI surface for the `memory` artifact type.

Pure wiring (mirrors cli_test.py): the install/list handler is stubbed via ``cli.DISPATCH`` so
we assert only that argv maps onto the right :class:`Request` fields — ``--memory-mode`` ->
``Request.memory_mode``, ``--type memory`` accepted -> ``type_filter`` — and that the TUI's
display order knows the new type. No command logic runs.

Run: ``python -m unittest discover -s tests -p "memory_cli_test.py" -v``
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


class TestMemoryModeFlag(unittest.TestCase):
    def test_memory_mode_maps_to_request(self):
        for mode in ("replace", "prepend", "append", "skip"):
            with self.subTest(mode=mode):
                _, req = _dispatch(
                    ["install", "house", "--profile", "claude", "--source", ".",
                     "--memory-mode", mode],
                    command="install",
                )
                self.assertEqual(req.memory_mode, mode)

    def test_memory_mode_defaults_to_none(self):
        # Absent flag -> None, so the planner applies the "prepend" default (DESIGN-memory §3.4).
        _, req = _dispatch(
            ["install", "house", "--profile", "claude", "--source", "."],
            command="install",
        )
        self.assertIsNone(req.memory_mode)

    def test_invalid_memory_mode_is_usage_error(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                cli.build_parser().parse_args(["install", "x", "--memory-mode", "bogus"])
        self.assertEqual(ctx.exception.code, 2)


class TestTypeFilterMemory(unittest.TestCase):
    def test_list_accepts_type_memory(self):
        _, req = _dispatch(["list", "--type", "memory", "--source", "."], command="list")
        self.assertEqual(req.type_filter, "memory")

    def test_memory_in_cli_type_choices(self):
        self.assertIn("memory", cli._ARTIFACT_TYPES)


class TestTuiKnowsMemory(unittest.TestCase):
    def test_type_order_includes_memory(self):
        self.assertIn("memory", tui._TYPE_ORDER)

    def test_memory_rank_is_stable(self):
        # A defined rank, not the fall-through len() default reserved for unknown types.
        self.assertEqual(tui._type_rank("memory"), tui._TYPE_ORDER.index("memory"))


if __name__ == "__main__":
    unittest.main()
