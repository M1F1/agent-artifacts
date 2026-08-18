"""End-to-end proof that `--memory-mode` reaches the file the harness actually reads.

The memory install modes were always implemented in the installation engine, but the flag that
selected them lived on the removed legacy install command (LAF-21).  Wiring alone is not the
contract: these tests drive the real CLI over a real project and assert the bytes on disk, so a
mode that stops reaching the planner fails here rather than in a unit-level mock.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.marketplace_lifecycle_e2e_test import _environment

_MEMORY = "reference/memory/house@1.0.0"
_SENTINEL_OPEN = "<!-- >>> agent-artifacts memory:house >>> -->"
_BACKUP_SUFFIX = ".agent-artifacts-bak"


def _instruction_file(environment) -> Path:
    return environment.project / "CLAUDE.md"


class MemoryModeE2ETest(unittest.TestCase):
    def test_two_named_memories_share_one_tabnine_file_and_uninstall_independently(self) -> None:
        fixture = Path(__file__).parent / "fixtures/protocol/native-source-v1"
        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw) / "source"
            shutil.copytree(fixture, source)
            house = source / "artifacts/memory/house"
            rules = source / "artifacts/memory/rules"
            shutil.copytree(house, rules)
            manifest_path = rules / "artifact.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["name"] = "rules"
            manifest["summary"] = "Shared testing rules."
            manifest_path.write_text(json.dumps(manifest))
            (rules / "payload/HOUSE.md").write_text("# Testing rules\n\nRun tests twice.\n")
            (rules / "provenance.json").unlink()

            with _environment(source) as environment:
                first, first_payload = environment.run(
                    "marketplace",
                    "install",
                    "reference/memory/house@1.0.0",
                    "--profile",
                    "tabnine",
                    "--yes",
                )
                second, second_payload = environment.run(
                    "marketplace",
                    "install",
                    "reference/memory/rules@1.0.0",
                    "--profile",
                    "tabnine",
                    "--yes",
                )

                self.assertEqual(first, 0, first_payload)
                self.assertEqual(second, 0, second_payload)
                destination = environment.project / "TABNINE.md"
                rendered = destination.read_text()
                self.assertIn("memory:house", rendered)
                self.assertIn("memory:rules", rendered)
                status, status_payload = environment.run(
                    "marketplace", "status", "--profile", "tabnine"
                )
                self.assertEqual(status, 0, status_payload)
                self.assertEqual({item["status"] for item in status_payload["items"]}, {"current"})

                removed, removed_payload = environment.run(
                    "marketplace",
                    "uninstall",
                    "reference/memory/house",
                    "--profile",
                    "tabnine",
                    "--yes",
                )
                self.assertEqual(removed, 0, removed_payload)
                rendered = destination.read_text()
                self.assertNotIn("memory:house", rendered)
                self.assertIn("memory:rules", rendered)

                last, last_payload = environment.run(
                    "marketplace",
                    "uninstall",
                    "reference/memory/rules",
                    "--profile",
                    "tabnine",
                    "--yes",
                )
                self.assertEqual(last, 0, last_payload)
                self.assertFalse(destination.exists())

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

    def test_a_forced_replace_parks_the_displaced_content_in_a_sidecar(self) -> None:
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
                "--force",
                "--yes",
            )

            self.assertEqual(code, 0, payload)
            sidecar = destination.parent / (destination.name + _BACKUP_SUFFIX)
            self.assertEqual(
                sidecar.read_text(encoding="utf-8"),
                original,
                "forcing a replace says 'put yours here', not 'lose mine forever'",
            )

    def test_uninstalling_a_forced_replace_puts_the_displaced_content_back(self) -> None:
        with _environment() as environment:
            destination = _instruction_file(environment)
            original = "# Existing\n\nHand-written guidance.\n"
            destination.write_text(original, encoding="utf-8")
            environment.run(
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
            self.assertNotIn("Hand-written guidance.", destination.read_text(encoding="utf-8"))

            code, payload = environment.run(
                "marketplace", "uninstall", _MEMORY, "--profile", "claude", "--yes"
            )

            self.assertEqual(code, 0, payload)
            self.assertEqual(
                destination.read_text(encoding="utf-8"),
                original,
                "uninstall restores what the replace displaced rather than deleting the file",
            )
            sidecar = destination.parent / (destination.name + _BACKUP_SUFFIX)
            self.assertFalse(sidecar.exists(), "a consumed sidecar is not left behind as litter")

    def test_a_replace_over_a_blank_file_needs_no_sidecar(self) -> None:
        # The destination guard still wants force over any pre-existing file, but blank content is
        # nothing to preserve, so no sidecar is left behind for uninstall to restore.
        with _environment() as environment:
            destination = _instruction_file(environment)
            destination.write_text("   \n", encoding="utf-8")

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
            sidecar = destination.parent / (destination.name + _BACKUP_SUFFIX)
            self.assertFalse(sidecar.exists(), "whitespace is not content worth preserving")

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
