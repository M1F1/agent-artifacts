"""RR-5: the three receipt actions are reachable from both skins, and are the same action.

`VN-9` said a maintainer action that exists only in the CLI is half-shipped. What makes this
more than a second menu entry is that both skins call `tui.receipt_outcome`, which calls
`receipt_service` — so the tests below drive the *front-ends*, with real records on disk, and
compare what each writes against what the flag-mode renderers produce.
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

from agent_artifacts import tui
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.install_state.paths import install_state_paths
from agent_artifacts.model import SetupState, SetupStateRecord
from agent_artifacts.setup import dump_setup_state
from agent_artifacts.setup_receipt import ReceiptLocation, setup_state_file
from agent_artifacts.setup_render import (
    receipt_payload,
    render_receipt_payload,
    render_undo_payload,
)
from agent_artifacts.wizard import initial_session
from tests.tui_wizard_curses_test import Screen

SETUP_REF = "setup-" + "e" * 20
COORDINATE = "registry-a/mcp/github-docker"
MANAGED_BLOCK = (
    "# >>> aart setup: aart-github >>>\nexport AART=1\n# <<< aart setup: aart-github <<<"
)


def _installation(setup_ref: str) -> dict:
    return {
        "coordinate": COORDINATE,
        "artifact": {
            "type": "mcp",
            "name": "github-docker",
            "version": "1.0.0",
            "manifest_digest": f"sha256:{'a' * 64}",
            "object_digest": f"sha256:{'b' * 64}",
            "payload_digest": f"sha256:{'c' * 64}",
        },
        "profile": "claude",
        "profile_version": 1,
        "scope": "project",
        "requested_mode": "copy",
        "source": {
            "alias": "registry-a",
            "kind": "registry-git",
            "origin": "github.com/example/registry",
            "declared_id": "la-registry-a",
            "resolved_commit": "0" * 40,
            "subscription_ref": "main",
        },
        "effects": [
            {
                "kind": "write-file",
                "destination": ".mcp.json",
                "actual_mode": "copy",
                "created_destination": True,
                "overwrote": False,
                "installed_digest": f"sha256:{'d' * 64}",
                "source_path": "payload/x.json",
            }
        ],
        "setup_state_ref": setup_ref,
    }


def _record(block_path: str) -> SetupStateRecord:
    """One step only, and a file one — so `verify` asks the filesystem and nothing else.

    A docker or Keychain claim would make this test depend on a daemon and a login session;
    `file.managed-block@1` is verified by reading a file, which a temporary directory provides.
    """

    return SetupStateRecord(
        artifact_type="mcp",
        artifact_name="github-docker",
        profile="claude",
        scope="project",
        status="configured",
        detail="Setup completed",
        source_label="registry-a (unverified)",
        installer_path="setup/installer.json",
        installer_hash="1" * 64,
        plan_hash="2" * 64,
        started_at="2026-08-15T09:00:00Z",
        finished_at="2026-08-15T09:00:42Z",
        exit_status=0,
        retry_command=f"aart marketplace setup {COORDINATE}@1.0.0 --yes",
        rollback_command=f"aart marketplace receipt undo {COORDINATE}",
        receipt=(
            {
                "step_id": "shell-block",
                "module": "file.managed-block@1",
                "path": block_path,
                "marker": "aart-github",
                "changed": True,
                "file_existed": False,
                "mode": 0o644,
                "prior_block": None,
                "installed_block": MANAGED_BLOCK,
                "disposition": "created",
            },
        ),
        object_digest=f"sha256:{'4' * 64}",
        recipe_digest=f"sha256:{'5' * 64}",
        trust="unverified",
        trust_evidence_digest=f"sha256:{'7' * 64}",
        policy_digest=f"sha256:{'8' * 64}",
        capability_plan_digest=f"sha256:{'9' * 64}",
        canonical_review_digest=f"sha256:{'6' * 64}",
        setup_state_ref=SETUP_REF,
    )


class ReceiptFrontEndTests(unittest.TestCase):
    """One installed, setup-bearing artifact on disk, read through both front-ends."""

    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.home = str(root / "home")
        self.project = str(root / "project")
        os.makedirs(self.home)
        os.makedirs(self.project)

        self.data_root = tui._receipt_data_root(self.home)
        self.block = str(root / "project" / ".zshrc")
        self.record = _record(self.block)
        Path(self.block).write_text(MANAGED_BLOCK + "\n", encoding="utf-8")

        paths = install_state_paths(
            "project",
            project_root=self.project,
            user_home=self.home,
            data_root=self.data_root,
        )
        manifest = Path(paths.destination_path)
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            json.dumps({"schema_version": 2, "installations": [_installation(SETUP_REF)]}),
            encoding="utf-8",
        )

        self.state_path = Path(setup_state_file(self.data_root, SETUP_REF))
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            dump_setup_state(SetupState((self.record,))) + "\n", encoding="utf-8"
        )

        self.location = ReceiptLocation(
            coordinate=COORDINATE,
            profile="claude",
            scope="project",
            setup_state_ref=SETUP_REF,
            state_path=str(self.state_path),
        )

    # -- the text skin -------------------------------------------------------------------

    def _text(self, answers: list[str]) -> list[str]:
        written: list[str] = []
        supplied = iter(answers)

        def read(prompt: str) -> str:
            try:
                return next(supplied)
            except StopIteration:  # pragma: no cover - a flow that asked one question too many
                raise AssertionError(f"the flow asked an unexpected question: {prompt}") from None

        tui._run_receipt_text(
            read,
            written.append,
            project=self.project,
            user_home=self.home,
        )
        return written

    def test_show_writes_exactly_what_the_flag_mode_renderer_writes(self) -> None:
        written = self._text(["show", "1", COORDINATE])

        expected = render_receipt_payload(receipt_payload(self.record, location=self.location))
        self.assertEqual(written[-len(expected) :], list(expected))

    def test_verify_asks_the_filesystem_and_reports_the_block_as_still_true(self) -> None:
        written = self._text(["verify", "1", COORDINATE])

        joined = "\n".join(written)
        self.assertIn("Verification", joined)
        self.assertIn("true", joined)

    def test_verify_sees_an_edited_block_as_false(self) -> None:
        Path(self.block).write_text("# somebody edited this\n", encoding="utf-8")

        written = self._text(["verify", "1", COORDINATE])

        self.assertIn("false", "\n".join(written))

    def test_an_unknown_coordinate_is_refused_with_remediation_not_a_traceback(self) -> None:
        written = self._text(["show", "1", "mcp/never-installed"])

        joined = "\n".join(written)
        self.assertIn("no installation of mcp/never-installed", joined)
        self.assertIn("remediation:", joined)

    def test_undo_reviews_first_and_changes_nothing_when_the_answer_is_no(self) -> None:
        before = self.state_path.read_bytes(), Path(self.block).read_bytes()

        written = self._text(["undo", "1", COORDINATE, "n"])

        self.assertEqual((self.state_path.read_bytes(), Path(self.block).read_bytes()), before)
        self.assertIn("Undo not applied; nothing was changed.", written)
        # The review is the same one `--json` and the CLI print, not a summary of it.
        for line in render_undo_payload(tui_undo_payload(self.record, self.location)):
            self.assertIn(line, written)

    def test_undo_applied_reverses_the_effect_and_rewrites_the_record(self) -> None:
        written = self._text(["undo", "1", COORDINATE, "y"])

        self.assertFalse(Path(self.block).exists(), "the file this run created is removed")
        self.assertIn("Undo outcome: skipped", "\n".join(written))
        reread = self.state_path.read_text(encoding="utf-8")
        self.assertIn("skipped", reread)

    def test_quitting_at_any_prompt_leaves_without_touching_anything(self) -> None:
        before = self.state_path.read_bytes()

        self.assertEqual(self._text(["q"]), self._text(["q"]))
        self.assertEqual(self._text(["show", "q"]), self._text(["show", "q"]))
        self.assertEqual(self._text(["show", "1", "q"]), self._text(["show", "1", "q"]))

        self.assertEqual(self.state_path.read_bytes(), before)

    # -- the curses skin -----------------------------------------------------------------

    def _curses(self, keys: list[int]) -> Screen:
        import curses

        screen = Screen(keys, height=40, width=100)
        tui._run_receipt_curses(
            curses,
            screen,
            initial_session(),
            project=self.project,
            user_home=self.home,
        )
        return screen

    def test_the_curses_skin_shows_the_same_receipt_the_text_skin_writes(self) -> None:
        enter = 10
        typed = [ord(character) for character in COORDINATE]
        # action=show (already under the cursor), scope=project (likewise), then the coordinate,
        # then one key to dismiss the notice.
        screen = self._curses([enter, enter, *typed, enter, enter])

        painted = "\n".join(value for _row, _column, value in screen.history)
        self.assertIn("Receipt show", painted)
        self.assertIn(self.record.plan_hash[:16], painted)

    def test_both_skins_render_a_refusal_rather_than_raising(self) -> None:
        enter = 10
        typed = [ord(character) for character in "mcp/never-installed"]
        screen = self._curses([enter, enter, *typed, enter, enter])

        painted = "\n".join(value for _row, _column, value in screen.history)
        self.assertIn("failed", painted)
        self.assertIn("remediation", painted)


def tui_undo_payload(record: SetupStateRecord, location: ReceiptLocation) -> dict:
    from agent_artifacts.setup_undo import plan_undo, undo_payload

    return undo_payload(
        plan_undo(record),
        coordinate=location.coordinate,
        profile=location.profile,
        scope=location.scope,
    )


_RECEIPT_INTERNALS = (
    "render_receipt_payload",
    "render_verification_payload",
    "render_undo_payload",
    "show_view",
    "verify_view",
    "undo_view",
    "apply_undo",
    "load_receipt",
)


class ReceiptServiceParityTests(unittest.TestCase):
    """Neither front-end may grow a second copy of a receipt's decisions."""

    def test_the_front_end_owns_no_receipt_logic_beyond_asking_and_writing(self) -> None:
        """Every receipt renderer and mutation is named inside `receipt_outcome` and nowhere else.

        This is the guard that keeps `RR-5` from becoming what it was written against: a skin
        that reaches past the shared function and renders a receipt its own way drifts from the
        other skin, and the drift is invisible until an operator reads two different answers to
        the same question.
        """

        import ast

        module = ast.parse(Path(tui.__file__).read_text(encoding="utf-8"))
        seam = next(
            node
            for node in module.body
            if isinstance(node, ast.FunctionDef) and node.name == "receipt_outcome"
        )
        inside = {node.id for node in ast.walk(seam) if isinstance(node, ast.Name)} | {
            alias.name for node in ast.walk(seam) for alias in getattr(node, "names", [])
        }
        within = {id(node) for node in ast.walk(seam)}
        elsewhere = [
            node.id
            for node in ast.walk(module)
            if isinstance(node, ast.Name)
            and node.id in _RECEIPT_INTERNALS
            and id(node) not in within
        ]
        for name in _RECEIPT_INTERNALS:
            self.assertIn(name, inside, f"{name} should be used by the shared seam")
        self.assertEqual(
            elsewhere,
            [],
            f"receipt internals used outside receipt_outcome: {sorted(set(elsewhere))}",
        )

    def test_a_refusal_is_a_typed_error_not_an_exception(self) -> None:
        outcome = tui.receipt_outcome(
            "show",
            "project",
            "mcp/nothing-here",
            project=os.getcwd(),
            user_home=os.getcwd(),
            confirm=lambda _lines: False,
        )
        self.assertIsInstance(outcome, Err)
        self.assertTrue(all(item.remediation for item in outcome.diagnostics))

    def test_an_unknown_action_cannot_silently_do_nothing(self) -> None:
        # Every action the menu offers is one `receipt_outcome` handles; the menu and the
        # service must not be able to drift apart.
        from agent_artifacts.receipt_service import RECEIPT_ACTIONS

        self.assertEqual(
            tuple(name for name, _description in tui.RECEIPT_MENU_ACTIONS), RECEIPT_ACTIONS
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


__all__ = ["Ok"]
