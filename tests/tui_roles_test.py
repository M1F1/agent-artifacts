"""Role-first and Maintainer TUI behavior, exercised headlessly."""

import curses
import json
import pathlib
import shutil
import tempfile
import unittest
from unittest import mock

from agent_artifacts import tui
from agent_artifacts.import_candidates import ImportCandidate, ImportScan
from agent_artifacts.model import Err, Ok, Request
from agent_artifacts.upstreams import UpstreamKey, UpstreamSource
from agent_artifacts.wizard import WizardInput, stages_for

FIXTURES = str(pathlib.Path(__file__).resolve().parent / "fixtures")


def _scripted_reader(answers):
    iterator = iter(answers)

    def read(_prompt=""):
        try:
            return next(iterator)
        except StopIteration:
            raise EOFError from None

    return read


def _collector():
    lines = []
    return (lambda text="": lines.append(text)), lines


class RoleFirstTextTests(unittest.TestCase):
    def test_default_maintainer_reaches_actions_without_asking_for_consumer_sources(self):
        write, _lines = _collector()

        with (
            mock.patch.object(tui.os, "getcwd", return_value="/registry"),
            mock.patch.object(
                tui,
                "_prompt_source_stage_text",
                side_effect=AssertionError("Maintainer default must skip Sources"),
            ),
            mock.patch.object(tui, "_run_maintainer_text", return_value=0) as maintainer,
        ):
            code = tui._run_text(
                _scripted_reader(["", "2"]),
                write,
                source_stage_view=tui._empty_source_stage_view(),
            )

        self.assertEqual(code, 0)
        session = maintainer.call_args.args[0]
        self.assertEqual(session.current, "maintainer_action")
        self.assertNotIn("source", stages_for(session))
        self.assertEqual(maintainer.call_args.kwargs["source_dir"], "/registry")

    def test_onboarding_is_first_then_roles_have_one_line_explanations(self):
        write, lines = _collector()

        with mock.patch.object(tui, "_dispatch") as dispatch:
            code = tui._run_text(_scripted_reader(["", "q"]), write, source_dir=FIXTURES)

        self.assertEqual(code, 0)
        dispatch.assert_not_called()
        screen = "\n".join(lines)
        self.assertTrue(screen.startswith("How aart works"))
        self.assertIn("Choose how you want to use aart:", screen)
        self.assertIn("User", screen)
        self.assertIn("subscribed catalogs", screen)
        self.assertIn("Maintainer", screen)
        self.assertIn("curate the catalog", screen)

    def test_user_role_preserves_existing_request_flow(self):
        captured = []
        write, _lines = _collector()

        with mock.patch.object(
            tui, "_dispatch", side_effect=lambda request: captured.append(request) or 0
        ):
            code = tui._run_text(
                _scripted_reader(["1", "1", "install", "1", "", "1", "y"]),
                write,
                source_dir=FIXTURES,
                project="/tmp/project",
            )

        self.assertEqual(code, 0)
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].command, "install")
        self.assertEqual(captured[0].profiles, ("claude",))

    def test_eof_on_role_screen_is_clean_quit(self):
        write, _lines = _collector()
        with mock.patch.object(tui, "_dispatch") as dispatch:
            code = tui._run_text(_scripted_reader([]), write, source_dir=FIXTURES)
        self.assertEqual(code, 0)
        dispatch.assert_not_called()


class RoleFirstCursesTests(unittest.TestCase):
    def test_default_maintainer_reaches_actions_without_entering_sources(self):
        calls = []
        events = iter((WizardInput("confirm", (1,)), WizardInput("quit")))

        def wrapper(ui):
            ui(object())

        def single(*args):
            calls.append(args[2])
            return next(events)

        with (
            mock.patch.object(curses, "wrapper", side_effect=wrapper),
            mock.patch.object(curses, "curs_set", return_value=None),
            mock.patch.object(tui, "_curses_onboarding", return_value=WizardInput("confirm")),
            mock.patch.object(tui, "_curses_single_event", side_effect=single),
            mock.patch.object(tui.os, "getcwd", return_value="/registry"),
            mock.patch.object(tui, "_is_canonical_maintainer_workspace", return_value=True),
            mock.patch.object(
                tui,
                "_curses_source_event",
                side_effect=AssertionError("Maintainer default must skip Sources"),
            ),
        ):
            code = tui._run_curses(source_stage_view=tui._empty_source_stage_view())

        self.assertEqual(code, 0)
        self.assertTrue(calls[0].startswith("Choose how"))
        self.assertTrue(calls[1].startswith("Maintainer - /registry"))

    def test_role_is_first_curses_screen_and_quit_is_clean(self):
        calls = []

        def wrapper(ui):
            ui(object())

        def single(_curses, _stdscr, title, labels):
            calls.append((title, tuple(labels)))
            return None

        with (
            mock.patch.object(curses, "wrapper", side_effect=wrapper),
            mock.patch.object(curses, "curs_set", return_value=None),
            mock.patch.object(tui, "_curses_singleselect", side_effect=single),
            mock.patch.object(tui, "_curses_multiselect") as multi,
            mock.patch.object(tui, "_dispatch") as dispatch,
        ):
            code = tui._run_curses(source_dir=FIXTURES)

        self.assertEqual(code, 0)
        self.assertTrue(calls[0][0].startswith("Choose how"))
        self.assertIn("User", calls[0][1][0])
        self.assertIn("Maintainer", calls[0][1][1])
        multi.assert_not_called()
        dispatch.assert_not_called()

    def test_maintainer_health_routes_after_role_and_action_screens(self):
        calls = []
        selections = iter((1, 0))  # Maintainer, Health

        def wrapper(ui):
            ui(object())

        def single(_curses, _stdscr, title, labels):
            calls.append((title, tuple(labels)))
            return next(selections)

        captured = []
        with (
            mock.patch.object(curses, "wrapper", side_effect=wrapper),
            mock.patch.object(curses, "curs_set", return_value=None),
            mock.patch("builtins.input", side_effect=["y"]),
            mock.patch.object(tui, "_curses_singleselect", side_effect=single),
            mock.patch.object(
                tui, "_dispatch", side_effect=lambda request: captured.append(request) or 0
            ),
        ):
            code = tui._run_curses(source_dir=FIXTURES)

        self.assertEqual(code, 0)
        self.assertTrue(calls[0][0].startswith("Choose how"))
        self.assertTrue(calls[1][0].startswith("Maintainer"))
        self.assertEqual(captured[0].upstream_action, "health")


class MaintainerMutationProtocolTests(unittest.TestCase):
    def test_validation_preview_apply_validation_order(self):
        calls = []
        write, lines = _collector()
        mutation = Request(
            command="upstream",
            upstream_action="update",
            names=("skill/demo",),
            source_dir="/catalog",
        )

        code = tui._run_maintainer_mutation(
            mutation,
            _scripted_reader(["y"]),
            write,
            dispatch=lambda request: calls.append(request) or 0,
        )

        self.assertEqual(code, 0)
        self.assertEqual(
            [(request.upstream_action, request.dry_run) for request in calls],
            [("validate", False), ("update", True), ("update", False), ("validate", False)],
        )
        self.assertTrue(any("review the working-tree diff" in line for line in lines))

    def test_cancel_after_preview_never_applies(self):
        calls = []
        mutation = Request(
            command="upstream",
            upstream_action="add",
            names=("skill/demo",),
            url="https://github.com/acme/demo/tree/main/skills/demo",
            source_dir="/catalog",
        )

        code = tui._run_maintainer_mutation(
            mutation,
            _scripted_reader(["n"]),
            lambda _text="": None,
            dispatch=lambda request: calls.append(request) or 0,
        )

        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].upstream_action, "validate")
        self.assertTrue(calls[1].dry_run)

    def test_failed_preview_never_prompts_or_applies(self):
        calls = []
        mutation = Request(
            command="upstream",
            upstream_action="update",
            all=True,
            source_dir="/catalog",
        )

        def dispatch(request):
            calls.append(request)
            return 4 if request.dry_run else 0

        code = tui._run_maintainer_mutation(
            mutation,
            _scripted_reader([]),
            lambda _text="": None,
            dispatch=dispatch,
        )

        self.assertEqual(code, 4)
        self.assertEqual(len(calls), 2)


class MaintainerTextTests(unittest.TestCase):
    def test_health_dispatches_against_explicit_absolute_catalog(self):
        captured = []
        write, lines = _collector()

        with mock.patch.object(
            tui, "_dispatch", side_effect=lambda request: captured.append(request) or 0
        ):
            code = tui._run_text(
                _scripted_reader(["2", "1", "y"]),
                write,
                source_dir=FIXTURES,
            )

        self.assertEqual(code, 0)
        self.assertEqual(captured[0].upstream_action, "health")
        self.assertEqual(captured[0].source_dir, str(pathlib.Path(FIXTURES).resolve()))
        self.assertIn(f"Catalog: {pathlib.Path(FIXTURES).resolve()}", "\n".join(lines))

    def test_invalid_maintainer_catalog_is_rejected_before_action_dispatch(self):
        write, lines = _collector()
        with mock.patch.object(tui, "_dispatch") as dispatch:
            code = tui._run_text(
                _scripted_reader(["2"]),
                write,
                source_dir="/definitely/not/a/catalog",
            )

        self.assertNotEqual(code, 0)
        dispatch.assert_not_called()
        self.assertIn("/definitely/not/a/catalog", "\n".join(lines))

    def test_add_builds_requests_and_uses_mutation_protocol(self):
        captured = []
        write, _lines = _collector()

        with mock.patch.object(
            tui, "_dispatch", side_effect=lambda request: captured.append(request) or 0
        ):
            code = tui._run_text(
                _scripted_reader(
                    [
                        "2",
                        "3",
                        "skill/demo",
                        "https://github.com/acme/demo/tree/main/skills/demo",
                        "",
                        "",
                        "y",
                    ]
                ),
                write,
                source_dir=FIXTURES,
            )

        self.assertEqual(code, 0)
        self.assertEqual(
            [(request.upstream_action, request.dry_run) for request in captured],
            [("validate", False), ("add", True), ("add", False), ("validate", False)],
        )
        self.assertEqual(captured[1].names, ("skill/demo",))
        self.assertEqual(captured[1].url, "https://github.com/acme/demo/tree/main/skills/demo")

    def test_maintainer_can_enter_user_workflow(self):
        captured = []
        write, _lines = _collector()

        with mock.patch.object(
            tui, "_dispatch", side_effect=lambda request: captured.append(request) or 0
        ):
            code = tui._run_text(
                _scripted_reader(["2", "7", "1", "install", "1", "", "1", "y"]),
                write,
                source_dir=FIXTURES,
            )

        self.assertEqual(code, 0)
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].command, "install")

    def test_import_scans_selects_candidates_and_optional_bundle_before_preview(self):
        candidate = ImportCandidate(
            key=UpstreamKey("skill", "demo"),
            source=UpstreamSource("github", "acme/demo", "main", "skills/demo"),
            detected_by="manifest",
            confidence="explicit",
            upstream_kind="tree",
            local_destination="skills/demo",
            absolute_path="/staged/skills/demo",
        )
        scan = ImportScan(
            mode="manifest",
            repo="acme/demo",
            ref="main",
            scan_root="",
            sha="abc",
            root="/staged",
            candidates=(candidate,),
        )
        captured = []
        write, _lines = _collector()
        from agent_artifacts.commands import upstream

        with (
            mock.patch.object(upstream, "scan_import_candidates", return_value=Ok(scan)),
            mock.patch.object(
                tui, "_dispatch", side_effect=lambda request: captured.append(request) or 0
            ),
        ):
            code = tui._run_text(
                _scripted_reader(
                    [
                        "2",
                        "4",
                        "https://github.com/acme/demo",
                        "1",
                        "starter",
                        "Imported starter artifacts",
                        "y",
                    ]
                ),
                write,
                source_dir=FIXTURES,
            )

        self.assertEqual(code, 0)
        self.assertEqual(
            [(request.upstream_action, request.dry_run) for request in captured],
            [("validate", False), ("import", True), ("import", False), ("validate", False)],
        )
        self.assertEqual(captured[1].names, ("skill/demo",))
        self.assertEqual(captured[1].bundles, ("starter",))
        self.assertEqual(captured[1].bundle_description, "Imported starter artifacts")

    def test_import_scan_failure_returns_its_error_code_without_dispatch(self):
        write, lines = _collector()
        from agent_artifacts.commands import upstream

        with (
            mock.patch.object(
                upstream, "scan_import_candidates", return_value=Err("scan failed", code=3)
            ),
            mock.patch.object(tui, "_dispatch") as dispatch,
        ):
            code = tui._run_text(
                _scripted_reader(["2", "4", "https://github.com/acme/demo"]),
                write,
                source_dir=FIXTURES,
            )

        self.assertEqual(code, 3)
        dispatch.assert_not_called()
        self.assertIn("scan failed", "\n".join(lines))

    def test_check_selected_and_update_selected_build_core_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / "catalog"
            shutil.copytree(FIXTURES, root)
            (root / "upstreams.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "artifacts": {
                            "skill/code-review": {
                                "source": {
                                    "kind": "github",
                                    "repo": "acme/catalog",
                                    "ref": "main",
                                    "path": "skills/code-review",
                                },
                                "last_synced": {
                                    "sha": "abc",
                                    "content_hash": "sha256:abc",
                                    "synced_at": "2026-08-06T00:00:00Z",
                                },
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            for action_number, answer, expected_action in (
                ("5", "1", "check"),
                ("5", "a", "check"),
                ("6", "1", "update"),
            ):
                with self.subTest(action=expected_action, selection=answer):
                    captured = []
                    answers = ["2", action_number, answer, "y"]
                    with mock.patch.object(
                        tui,
                        "_dispatch",
                        side_effect=lambda request, captured=captured: (
                            captured.append(request) or 0
                        ),
                    ):
                        code = tui._run_text(
                            _scripted_reader(answers),
                            lambda _text="": None,
                            source_dir=str(root),
                        )
                    self.assertEqual(code, 0)
                    action_requests = [
                        request
                        for request in captured
                        if request.upstream_action == expected_action
                    ]
                    self.assertTrue(action_requests)
                    if answer == "a":
                        self.assertTrue(action_requests[0].all)
                    else:
                        self.assertEqual(action_requests[0].names, ("skill/code-review",))


if __name__ == "__main__":
    unittest.main()
