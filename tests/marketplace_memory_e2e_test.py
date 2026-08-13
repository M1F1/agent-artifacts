"""End-to-end proof that `--memory-mode` reaches the file the harness actually reads.

The memory install modes were always implemented in the installation engine, but the flag that
selected them lived on the removed legacy install command (LAF-21).  Wiring alone is not the
contract: these tests drive the real CLI over a real project and assert the bytes on disk, so a
mode that stops reaching the planner fails here rather than in a unit-level mock.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from tests.marketplace_lifecycle_e2e_test import _environment

_MEMORY = "reference/memory/house@1.0.0"
_SENTINEL_OPEN = "<!-- >>> agent-artifacts memory:house >>> -->"


def _instruction_file(environment) -> Path:
    return environment.project / "CLAUDE.md"


class MemoryModeE2ETest(unittest.TestCase):
    def test_default_prepend_writes_the_managed_block_into_a_fresh_file(self) -> None:
        with _environment() as environment:
            destination = _instruction_file(environment)

            code, payload = environment.run(
                "marketplace", "install", _MEMORY, "--profile", "claude", "--yes"
            )

            self.assertEqual(code, 0, payload)
            self.assertIn(_SENTINEL_OPEN, destination.read_text(encoding="utf-8"))

    def test_prepend_over_foreign_content_needs_force_and_then_leads_the_file(self) -> None:
        with _environment() as environment:
            destination = _instruction_file(environment)
            original = "# Existing\n\nHand-written guidance.\n"
            destination.write_text(original, encoding="utf-8")

            refused, diagnostics = environment.run(
                "marketplace", "install", _MEMORY, "--profile", "claude", "--yes"
            )
            self.assertNotEqual(refused, 0, diagnostics)
            self.assertEqual(destination.read_text(encoding="utf-8"), original)

            code, payload = environment.run(
                "marketplace", "install", _MEMORY, "--profile", "claude", "--force", "--yes"
            )

            self.assertEqual(code, 0, payload)
            rendered = destination.read_text(encoding="utf-8")
            self.assertIn(_SENTINEL_OPEN, rendered)
            self.assertIn("Hand-written guidance.", rendered)
            self.assertLess(
                rendered.index(_SENTINEL_OPEN),
                rendered.index("Hand-written guidance."),
                "the default mode is prepend, so the managed block leads the file",
            )

    def test_append_puts_the_managed_block_below_existing_content(self) -> None:
        with _environment() as environment:
            destination = _instruction_file(environment)
            destination.write_text("# Existing\n\nHand-written guidance.\n", encoding="utf-8")

            code, payload = environment.run(
                "marketplace",
                "install",
                _MEMORY,
                "--profile",
                "claude",
                "--memory-mode",
                "append",
                "--force",
                "--yes",
            )

            self.assertEqual(code, 0, payload)
            rendered = destination.read_text(encoding="utf-8")
            self.assertGreater(rendered.index(_SENTINEL_OPEN), rendered.index("Hand-written"))

    def test_replace_refuses_to_discard_foreign_content_without_force(self) -> None:
        with _environment() as environment:
            destination = _instruction_file(environment)
            original = "# Existing\n\nHand-written guidance.\n"
            destination.write_text(original, encoding="utf-8")

            code, payload = environment.run(
                "marketplace",
                "install",
                _MEMORY,
                "--profile",
                "claude",
                "--memory-mode",
                "replace",
                "--yes",
            )

            self.assertNotEqual(code, 0)
            self.assertEqual(
                destination.read_text(encoding="utf-8"),
                original,
                "a refused replace must not have touched the file",
            )
            self.assertIsNotNone(payload)

    def test_replace_with_force_overwrites_the_instruction_file(self) -> None:
        with _environment() as environment:
            destination = _instruction_file(environment)
            destination.write_text("# Existing\n\nHand-written guidance.\n", encoding="utf-8")

            code, payload = environment.run(
                "marketplace",
                "install",
                _MEMORY,
                "--profile",
                "claude",
                "--memory-mode",
                "replace",
                "--force",
                "--yes",
            )

            self.assertEqual(code, 0, payload)
            rendered = destination.read_text(encoding="utf-8")
            self.assertIn("House conventions", rendered)
            self.assertNotIn("Hand-written guidance.", rendered)

    def test_skip_leaves_an_existing_instruction_file_untouched(self) -> None:
        with _environment() as environment:
            destination = _instruction_file(environment)
            original = "# Existing\n\nHand-written guidance.\n"
            destination.write_text(original, encoding="utf-8")

            code, payload = environment.run(
                "marketplace",
                "install",
                _MEMORY,
                "--profile",
                "claude",
                "--memory-mode",
                "skip",
                "--yes",
            )

            self.assertNotEqual(code, 0, "skip over existing content has no managed effect")
            self.assertEqual(
                [diagnostic["message"] for diagnostic in payload["diagnostics"]],
                ["memory install was skipped and has no managed effect"],
                "the refusal must name the empty outcome rather than report a false success",
            )
            self.assertEqual(destination.read_text(encoding="utf-8"), original)

    def test_review_without_yes_writes_no_instruction_file(self) -> None:
        with _environment() as environment:
            destination = _instruction_file(environment)

            code, payload = environment.run(
                "marketplace",
                "install",
                _MEMORY,
                "--profile",
                "claude",
                "--memory-mode",
                "append",
            )

            self.assertEqual(code, 0, payload)
            self.assertFalse(destination.exists(), "review must not create the destination")


if __name__ == "__main__":
    unittest.main()
