"""WP-20 tests: the interactive selector's text/fallback flow, driven headless.

Run: ``python -m unittest discover -s tests -p "tui_test.py" -v``

These tests never touch a real terminal or ``curses``: they drive :func:`tui._run_text`
directly with a scripted ``read`` and a capturing ``write``, point ``source_factory`` at the
on-disk fixtures (``tests/fixtures``), and use a fresh temp ``--project``. They assert the
selector (a) returns the right exit code, (b) actually dispatches through the *real* command
core (filesystem effects appear), and (c) builds the expected `Request` (via a patched
``cli.DISPATCH`` recorder) — proving no command logic is duplicated in the TUI.
"""

import curses
import io
import json
import os
import pathlib
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

from agent_artifacts import tui
from agent_artifacts.model import Manifest, ManifestEntry, Ok, Request
from agent_artifacts.outcomes import ActionSummary, CommandOutcome, OutcomeItem
from agent_artifacts.profiles.loader import load_profiles
from agent_artifacts.source import open_source

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = str(REPO_ROOT / "tests" / "fixtures")


def _scripted_reader(answers):
    """Return a ``read(prompt)`` callable that yields *answers* in order, then raises EOF."""
    it = iter(answers)

    def _read(_prompt=""):
        try:
            return next(it)
        except StopIteration:
            raise EOFError from None

    return _read


def _collector():
    """Return ``(write, lines)`` where ``write(text)`` appends to the ``lines`` list."""
    lines = []
    return (lambda text="": lines.append(text)), lines


def _fixture_catalog():
    return open_source(Request(command="list", source_dir=FIXTURES)).value.catalog().value


def _fixture_profiles(project=None):
    return load_profiles(project)


def _write_manifest(project, entries):
    path = pathlib.Path(project) / ".agent-artifacts" / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "repo": "M1F1/agent-artifacts",
        "installed": [
            {
                "artifact": entry.artifact,
                "type": entry.type,
                "profile": entry.profile,
                "source": entry.source,
                **({"bundle": entry.bundle} if entry.bundle else {}),
                "files": dict(entry.files),
                "installed_at": entry.installed_at,
            }
            for entry in entries
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


class ChoiceModelTests(unittest.TestCase):
    """Pure profile-aware choice filtering, independent of prompt I/O."""

    def setUp(self):
        self.catalog = _fixture_catalog()
        self.profiles = _fixture_profiles()

    def _artifact(self, type_, name):
        return self.catalog.artifacts[(type_, name)]

    def test_unrestricted_skill_visible_for_all_builtin_profiles(self):
        art = self._artifact("skill", "code-review")
        for profile in ("claude", "opencode", "tabnine", "vibe"):
            with self.subTest(profile=profile):
                self.assertTrue(tui.artifact_visible_for_profiles(art, (profile,), self.profiles))

    def test_vibe_hides_mcp_and_hook_artifacts(self):
        for type_, name in (("mcp", "postgres"), ("hook", "block-secrets")):
            with self.subTest(artifact=name):
                self.assertFalse(
                    tui.artifact_visible_for_profiles(
                        self._artifact(type_, name), ("vibe",), self.profiles
                    )
                )

    def test_tabnine_only_mcp_visibility_respects_compatibility(self):
        art = self._artifact("mcp", "tabnine-postgres")
        self.assertTrue(tui.artifact_visible_for_profiles(art, ("tabnine",), self.profiles))
        self.assertFalse(tui.artifact_visible_for_profiles(art, ("claude",), self.profiles))

    def test_multiple_profiles_use_intersection_semantics(self):
        mcp = self._artifact("mcp", "postgres")
        skill = self._artifact("skill", "code-review")
        self.assertFalse(tui.artifact_visible_for_profiles(mcp, ("claude", "vibe"), self.profiles))
        self.assertTrue(tui.artifact_visible_for_profiles(skill, ("claude", "vibe"), self.profiles))

    def test_build_install_choices_filters_artifacts_for_vibe(self):
        choices = tui.build_install_choices(self.catalog, ("vibe",), self.profiles)
        labels = [choice.label for choice in choices]
        self.assertTrue(any(label.startswith("[skill] code-review") for label in labels))
        self.assertTrue(any(label.startswith("[guideline] python-style") for label in labels))
        self.assertTrue(any(label.startswith("[memory] house") for label in labels))
        self.assertFalse(any("[mcp]" in label for label in labels))
        self.assertFalse(any("[hook]" in label for label in labels))

    def test_build_install_choices_shows_tabnine_only_mcp_for_tabnine(self):
        choices = tui.build_install_choices(self.catalog, ("tabnine",), self.profiles)
        self.assertTrue(
            any(choice.label.startswith("[mcp] tabnine-postgres") for choice in choices)
        )

    def test_install_choices_keep_description_as_structured_data(self):
        choices = tui.build_install_choices(self.catalog, ("claude",), self.profiles)
        code_review = next(choice for choice in choices if choice.name == "code-review")
        backend = next(choice for choice in choices if choice.name == "backend")

        self.assertEqual(
            code_review.description,
            "Review changes for bugs, risks, and maintainability problems.",
        )
        self.assertEqual(
            code_review.label,
            "[skill] code-review — Review changes for bugs, risks, and maintainability problems.",
        )
        self.assertEqual(
            backend.description,
            "Add database access to the team's essential agent setup.",
        )

    def test_compatibility_filtering_preserves_description(self):
        choices = tui.build_install_choices(self.catalog, ("tabnine",), self.profiles)
        postgres = next(choice for choice in choices if choice.name == "tabnine-postgres")

        self.assertEqual(
            postgres.description,
            "Let Tabnine inspect and query PostgreSQL databases.",
        )

    def test_build_install_choices_marks_partial_bundles(self):
        choices = tui.build_install_choices(self.catalog, ("vibe",), self.profiles)
        bundles = {choice.name: choice for choice in choices if choice.kind == "bundle"}
        self.assertIn("backend", bundles)
        self.assertFalse(bundles["backend"].complete)
        self.assertGreater(bundles["backend"].hidden_count, 0)
        self.assertIn("hidden for selected profile", bundles["backend"].label)

    def test_manifest_choices_are_profile_scoped(self):
        manifest = Manifest(
            repo="r",
            installed=(
                ManifestEntry("code-review", "skill", "claude", "main:1"),
                ManifestEntry("python-style", "guideline", "vibe", "main:1"),
            ),
        )
        choices = tui.build_action_choices(
            "uninstall", self.catalog, manifest, ("vibe",), self.profiles
        )
        self.assertEqual([choice.name for choice in choices], ["python-style"])

    def test_update_keeps_source_specific_manifest_entry_absent_from_loaded_catalog(self):
        manifest = Manifest(
            repo="remote/catalog",
            installed=(ManifestEntry("remote-only", "skill", "claude", "main:1"),),
        )
        empty = type(self.catalog)(artifacts={}, bundles={})

        choices = tui.build_action_choices("update", empty, manifest, ("claude",), self.profiles)

        self.assertEqual([choice.name for choice in choices], ["remote-only"])
        self.assertEqual(choices[0].description, "")

    def test_update_and_uninstall_use_catalog_description_when_available(self):
        manifest = Manifest(
            repo="r",
            installed=(ManifestEntry("code-review", "skill", "claude", "main:1"),),
        )

        for action in ("update", "uninstall"):
            with self.subTest(action=action):
                choices = tui.build_action_choices(
                    action, self.catalog, manifest, ("claude",), self.profiles
                )
                self.assertEqual(
                    choices[0].description,
                    "Review changes for bugs, risks, and maintainability problems.",
                )
                self.assertIn(" — Review changes", choices[0].label)


class TextFlowInstallTests(unittest.TestCase):
    """The happy path: pick an artifact + profile + install, dispatched for real."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def _path(self, *parts):
        return os.path.join(self.project, *parts)

    def test_install_code_review_to_claude(self):
        # Profile 1 = claude ; action install ; row 1 = [skill] code-review.
        read = _scripted_reader(["1", "1", "install", "1", "", "1", "y"])
        write, _ = _collector()
        with redirect_stdout(io.StringIO()):
            rc = tui._run_text(
                read,
                write,
                source_factory=open_source,
                source_dir=FIXTURES,
                project=self.project,
            )
        self.assertEqual(rc, 0)
        # The REAL install command ran: the skill tree + manifest are on disk.
        self.assertTrue(
            os.path.isfile(self._path(".claude", "skills", "code-review", "SKILL.md")),
            "selector did not dispatch through the real install command",
        )
        manifest_file = self._path(".agent-artifacts", "manifest.json")
        self.assertTrue(os.path.isfile(manifest_file))
        manifest = json.loads(pathlib.Path(manifest_file).read_text())
        installed = {e["artifact"] for e in manifest["installed"]}
        self.assertIn("code-review", installed)

    def test_action_by_name_or_number_equivalent(self):
        # Selecting the action by its number works like the name.
        read = _scripted_reader(["1", "1", "1", "1", "", "1", "y"])
        write, _ = _collector()
        with redirect_stdout(io.StringIO()):
            rc = tui._run_text(read, write, source_dir=FIXTURES, project=self.project)
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isfile(self._path(".claude", "skills", "code-review", "SKILL.md")))

    def test_vibe_flow_hides_incompatible_artifacts_before_selection(self):
        read = _scripted_reader(["1", "4", "install", "1", "", "q"])  # project, Copy, quit
        write, lines = _collector()
        with mock.patch.object(tui, "_dispatch") as disp:
            rc = tui._run_text(read, write, source_dir=FIXTURES, project=self.project)
        self.assertEqual(rc, 0)
        disp.assert_not_called()
        menu = "\n".join(lines)
        self.assertIn("[skill] code-review", menu)
        self.assertIn("[memory] house", menu)
        self.assertNotIn("[mcp] postgres", menu)
        self.assertNotIn("[mcp] tabnine-postgres", menu)
        self.assertNotIn("[hook] block-secrets", menu)

    def test_text_selector_prints_full_descriptions(self):
        read = _scripted_reader(["1", "1", "install", "1", "", "q"])
        write, lines = _collector()
        with mock.patch.object(tui, "_dispatch") as disp:
            rc = tui._run_text(read, write, source_dir=FIXTURES, project=self.project)

        self.assertEqual(rc, 0)
        disp.assert_not_called()
        self.assertIn(
            "[skill] code-review — Review changes for bugs, risks, and maintainability problems.",
            "\n".join(lines),
        )

    def test_tabnine_flow_shows_tabnine_only_mcp(self):
        read = _scripted_reader(["1", "3", "install", "1", "", "q"])  # project, Copy, quit
        write, lines = _collector()
        with mock.patch.object(tui, "_dispatch") as disp:
            rc = tui._run_text(read, write, source_dir=FIXTURES, project=self.project)
        self.assertEqual(rc, 0)
        disp.assert_not_called()
        self.assertIn("[mcp] tabnine-postgres", "\n".join(lines))

    def test_claude_flow_hides_tabnine_only_mcp(self):
        read = _scripted_reader(["1", "1", "install", "1", "", "q"])  # project, Copy, quit
        write, lines = _collector()
        with mock.patch.object(tui, "_dispatch") as disp:
            rc = tui._run_text(read, write, source_dir=FIXTURES, project=self.project)
        self.assertEqual(rc, 0)
        disp.assert_not_called()
        self.assertNotIn("[mcp] tabnine-postgres", "\n".join(lines))

    def test_multi_profile_flow_uses_intersection_filtering(self):
        read = _scripted_reader(["1", "1,4", "install", "1", "", "q"])  # project, Copy, quit
        write, lines = _collector()
        with mock.patch.object(tui, "_dispatch") as disp:
            rc = tui._run_text(read, write, source_dir=FIXTURES, project=self.project)
        self.assertEqual(rc, 0)
        disp.assert_not_called()
        menu = "\n".join(lines)
        self.assertIn("[skill] code-review", menu)
        self.assertNotIn("[mcp] postgres", menu)
        self.assertNotIn("[hook] block-secrets", menu)

    def test_partial_bundle_can_be_selected_via_tui(self):
        # For vibe, choices are skill, guideline, memory, backend bundle, base bundle.
        read = _scripted_reader(["1", "4", "install", "1", "", "4", "y"])
        captured = {}

        def _recorder(request):
            captured["req"] = request
            return 0

        write, lines = _collector()
        with mock.patch.object(tui, "_dispatch", side_effect=_recorder):
            rc = tui._run_text(read, write, source_dir=FIXTURES, project=self.project)
        self.assertEqual(rc, 0)
        self.assertEqual(captured["req"].bundles, ("backend",))
        self.assertIn("hidden for selected profile", "\n".join(lines))

    def test_uninstall_choices_are_installed_entries_for_selected_profile(self):
        _write_manifest(
            self.project,
            (
                ManifestEntry(
                    artifact="code-review",
                    type="skill",
                    profile="claude",
                    source="main:1",
                    files={".claude/skills/code-review/SKILL.md": "sha256:1"},
                ),
                ManifestEntry(
                    artifact="python-style",
                    type="guideline",
                    profile="vibe",
                    source="main:1",
                    files={".vibe/guidelines/python-style.md": "sha256:2"},
                ),
            ),
        )
        read = _scripted_reader(["1", "4", "uninstall", "1", "q"])  # User, vibe, project
        write, lines = _collector()
        with mock.patch.object(tui, "_dispatch") as disp:
            rc = tui._run_text(read, write, source_dir=FIXTURES, project=self.project)
        self.assertEqual(rc, 0)
        disp.assert_not_called()
        menu = "\n".join(lines)
        self.assertIn("[guideline] python-style", menu)
        self.assertNotIn("[skill] code-review", menu)

    def test_update_choices_are_installed_entries_for_selected_profile(self):
        _write_manifest(
            self.project,
            (
                ManifestEntry(
                    artifact="code-review",
                    type="skill",
                    profile="claude",
                    source="main:1",
                    files={".claude/skills/code-review/SKILL.md": "sha256:1"},
                ),
            ),
        )
        read = _scripted_reader(["1", "1", "update", "1", "q"])  # User, claude, project
        write, lines = _collector()
        with mock.patch.object(tui, "_dispatch") as disp:
            rc = tui._run_text(read, write, source_dir=FIXTURES, project=self.project)
        self.assertEqual(rc, 0)
        disp.assert_not_called()
        self.assertIn("[skill] code-review", "\n".join(lines))

    def test_no_matching_installed_entries_returns_without_dispatch(self):
        read = _scripted_reader(["1", "1", "uninstall", "1"])  # User, project, no entries
        write, lines = _collector()
        with mock.patch.object(tui, "_dispatch") as disp:
            rc = tui._run_text(read, write, source_dir=FIXTURES, project=self.project)
        self.assertEqual(rc, 0)
        disp.assert_not_called()
        self.assertTrue(any("No installed artifacts to uninstall" in line for line in lines))


class TextFlowQuitTests(unittest.TestCase):
    """Quitting at any prompt returns 0 and dispatches nothing."""

    def test_quit_immediately_blank(self):
        read = _scripted_reader([""])  # blank at the first prompt
        write, _ = _collector()
        with mock.patch.object(tui, "_dispatch") as disp:
            rc = tui._run_text(read, write, source_dir=FIXTURES, project=None)
        self.assertEqual(rc, 0)
        disp.assert_not_called()

    def test_quit_with_q(self):
        read = _scripted_reader(["q"])
        write, _ = _collector()
        with mock.patch.object(tui, "_dispatch") as disp:
            rc = tui._run_text(read, write, source_dir=FIXTURES, project=None)
        self.assertEqual(rc, 0)
        disp.assert_not_called()

    def test_quit_at_profile_prompt(self):
        read = _scripted_reader(["1", "q"])
        write, _ = _collector()
        with mock.patch.object(tui, "_dispatch") as disp:
            rc = tui._run_text(read, write, source_dir=FIXTURES, project=None)
        self.assertEqual(rc, 0)
        disp.assert_not_called()

    def test_quit_at_action_prompt(self):
        read = _scripted_reader(["1", "1", "q"])  # User, pick profile, quit at action
        write, _ = _collector()
        with mock.patch.object(tui, "_dispatch") as disp:
            rc = tui._run_text(read, write, source_dir=FIXTURES, project=None)
        self.assertEqual(rc, 0)
        disp.assert_not_called()

    def test_quit_at_selection_prompt(self):
        read = _scripted_reader(["1", "1", "1", "1", "", "q"])  # project, Copy, quit
        write, _ = _collector()
        with mock.patch.object(tui, "_dispatch") as disp:
            rc = tui._run_text(read, write, source_dir=FIXTURES, project=None)
        self.assertEqual(rc, 0)
        disp.assert_not_called()

    def test_eof_is_clean_quit(self):
        read = _scripted_reader([])  # EOF immediately
        write, _ = _collector()
        with mock.patch.object(tui, "_dispatch") as disp:
            rc = tui._run_text(read, write, source_dir=FIXTURES, project=None)
        self.assertEqual(rc, 0)
        disp.assert_not_called()


class RequestAssemblyTests(unittest.TestCase):
    """The built Request carries the expected fields (no command logic duplicated)."""

    def test_dispatch_receives_expected_request(self):
        captured = {}

        def _recorder(request):
            captured["req"] = request
            return 0

        read = _scripted_reader(["1", "1", "install", "1", "", "1", "y"])
        write, _ = _collector()
        with mock.patch.object(tui, "_dispatch", side_effect=_recorder):
            rc = tui._run_text(read, write, source_dir=FIXTURES, project="/tmp/example-proj")
        self.assertEqual(rc, 0)
        req = captured["req"]
        self.assertIsInstance(req, Request)
        self.assertEqual(req.command, "install")
        self.assertEqual(req.names, ("code-review",))
        self.assertEqual(req.bundles, ())
        self.assertEqual(req.profiles, ("claude",))
        self.assertEqual(req.source_dir, FIXTURES)
        self.assertEqual(req.project, "/tmp/example-proj")
        self.assertTrue(req.yes)
        # Selection is left untyped so bare names resolve across types in the core.
        self.assertIsNone(req.type_filter)

    def test_bundle_selection_populates_bundles(self):
        # Profile 1 = claude; row 6 = [bundle] backend after filtering.
        captured = {}

        def _recorder(request):
            captured["req"] = request
            return 0

        read = _scripted_reader(["1", "1", "install", "1", "", "6", "y"])
        write, _ = _collector()
        with mock.patch.object(tui, "_dispatch", side_effect=_recorder):
            rc = tui._run_text(read, write, source_dir=FIXTURES, project=None)
        self.assertEqual(rc, 0)
        req = captured["req"]
        self.assertEqual(req.bundles, ("backend",))
        self.assertEqual(req.names, ())

    def test_multi_select_artifacts(self):
        captured = {}

        def _recorder(request):
            captured["req"] = request
            return 0

        read = _scripted_reader(["1", "1", "install", "1", "", "1,3", "y"])
        write, _ = _collector()
        with mock.patch.object(tui, "_dispatch", side_effect=_recorder):
            rc = tui._run_text(read, write, source_dir=FIXTURES, project=None)
        self.assertEqual(rc, 0)
        req = captured["req"]
        self.assertEqual(set(req.names), {"code-review", "postgres"})

    def test_uninstall_action_routes_through(self):
        captured = {}

        def _recorder(request):
            captured["req"] = request
            return 0

        with tempfile.TemporaryDirectory() as project:
            _write_manifest(
                project,
                (
                    ManifestEntry(
                        artifact="code-review",
                        type="skill",
                        profile="claude",
                        source="main:1",
                    ),
                ),
            )
            read = _scripted_reader(["1", "1", "uninstall", "1", "1", "y"])
            write, _ = _collector()
            with mock.patch.object(tui, "_dispatch", side_effect=_recorder):
                rc = tui._run_text(read, write, source_dir=FIXTURES, project=project)
        self.assertEqual(rc, 0)
        self.assertEqual(captured["req"].command, "uninstall")
        self.assertEqual(captured["req"].profiles, ("claude",))


class DispatchRoutingTests(unittest.TestCase):
    """``_dispatch`` reuses the same command handlers (cli.DISPATCH or the module)."""

    def test_dispatch_prefers_cli_dispatch_when_present(self):
        calls = {}

        def _fake_run(request):
            calls["request"] = request
            return 7

        fake_dispatch = {"install": _fake_run}
        import agent_artifacts.cli as cli

        with mock.patch.object(cli, "DISPATCH", fake_dispatch, create=True):
            rc = tui._dispatch(Request(command="install", names=("code-review",)))
        self.assertEqual(rc, 7)
        self.assertEqual(calls["request"].command, "install")

    def test_dispatch_falls_back_to_command_module(self):
        # With no cli.DISPATCH attribute, _dispatch imports commands.<cmd>.run directly.
        import agent_artifacts.cli as cli

        recorded = {}

        def _fake_run(request):
            recorded["req"] = request
            return 0

        # Remove DISPATCH (if present) and stub the install module's run.
        with mock.patch.object(cli, "DISPATCH", None, create=True):
            import agent_artifacts.commands.install as install_mod

            with mock.patch.object(install_mod, "run", side_effect=_fake_run):
                rc = tui._dispatch(Request(command="install", names=("code-review",)))
        self.assertEqual(rc, 0)
        self.assertEqual(recorded["req"].names, ("code-review",))


class StructuredOutcomeFrontendTests(unittest.TestCase):
    def make_command_outcome(self):
        return CommandOutcome(
            0,
            ActionSummary(
                action="install",
                selected=1,
                items=(
                    OutcomeItem(
                        "skill/code-review@claude",
                        "installed",
                        artifact="code-review",
                        artifact_type="skill",
                        profile="claude",
                        mode="copy",
                    ),
                ),
            ),
        )

    def test_text_frontend_writes_structured_summary_through_injected_writer(self):
        write, lines = _collector()
        with mock.patch.object(
            tui,
            "_dispatch_result",
            return_value=self.make_command_outcome(),
        ) as dispatch:
            code = tui._run_text(
                _scripted_reader(["1", "1", "install", "1", "", "1", "y"]),
                write,
                source_dir=FIXTURES,
            )

        self.assertEqual(code, 0)
        dispatch.assert_called_once()
        self.assertIn("Installed 1 artifact; 1 selected.", lines)
        self.assertTrue(any("mode=copy" in line for line in lines))

    def test_text_frontend_keeps_conflict_warning_and_recovery(self):
        result = CommandOutcome(
            4,
            ActionSummary(
                action="update",
                selected=1,
                items=(
                    OutcomeItem(
                        "skill/code-review@claude",
                        "conflict",
                        detail="local and upstream changes differ",
                    ),
                ),
                warnings=("candidate written beside the managed file",),
                recovery=("Review the candidate and rerun with --force.",),
            ),
        )
        write, lines = _collector()
        with mock.patch.object(tui, "_dispatch_result", return_value=result):
            code = tui._run_text(
                _scripted_reader(["1", "1", "install", "1", "", "1", "y"]),
                write,
                source_dir=FIXTURES,
            )

        self.assertEqual(code, 4)
        self.assertIn("warning: candidate written beside the managed file", lines)
        self.assertIn("next: Review the candidate and rerun with --force.", lines)

    def test_curses_dispatches_after_teardown_and_leaves_summary_visible(self):
        inside_wrapper = {"value": False}

        def wrapper(callback):
            inside_wrapper["value"] = True
            callback(object())
            inside_wrapper["value"] = False

        singles = iter((0, 0))  # User, Install

        def dispatch(_request):
            self.assertFalse(inside_wrapper["value"])
            return self.make_command_outcome()

        output = io.StringIO()
        with (
            redirect_stdout(output),
            mock.patch.object(curses, "wrapper", side_effect=wrapper),
            mock.patch.object(curses, "curs_set", return_value=None),
            mock.patch.object(
                tui,
                "_curses_singleselect",
                side_effect=lambda *_args, **_kwargs: next(singles),
            ),
            mock.patch.object(tui, "_curses_multiselect", side_effect=((0,), (0,))),
            mock.patch.object(tui, "_curses_install_scope", return_value="project"),
            mock.patch.object(tui, "_curses_install_mode", return_value="copy"),
            mock.patch.object(tui, "_curses_confirm_install", return_value=True),
            mock.patch.object(tui, "_dispatch_result", side_effect=dispatch),
        ):
            code = tui._run_curses(source_dir=FIXTURES)

        self.assertEqual(code, 0)
        self.assertIn("Installed 1 artifact; 1 selected.", output.getvalue())

    def test_curses_failure_summary_and_recovery_remain_after_teardown(self):
        inside_wrapper = {"value": False}

        def wrapper(callback):
            inside_wrapper["value"] = True
            callback(object())
            inside_wrapper["value"] = False

        singles = iter((0, 0))
        result = CommandOutcome(
            1,
            ActionSummary(
                action="install",
                selected=1,
                items=(
                    OutcomeItem(
                        "skill/code-review@claude",
                        "failed",
                        detail="permission denied",
                    ),
                ),
                recovery=("Fix permissions and retry.",),
            ),
        )

        def dispatch(_request):
            self.assertFalse(inside_wrapper["value"])
            return result

        output = io.StringIO()
        with (
            redirect_stdout(output),
            mock.patch.object(curses, "wrapper", side_effect=wrapper),
            mock.patch.object(curses, "curs_set", return_value=None),
            mock.patch.object(
                tui,
                "_curses_singleselect",
                side_effect=lambda *_args, **_kwargs: next(singles),
            ),
            mock.patch.object(tui, "_curses_multiselect", side_effect=((0,), (0,))),
            mock.patch.object(tui, "_curses_install_scope", return_value="project"),
            mock.patch.object(tui, "_curses_install_mode", return_value="copy"),
            mock.patch.object(tui, "_curses_confirm_install", return_value=True),
            mock.patch.object(tui, "_dispatch_result", side_effect=dispatch),
        ):
            code = tui._run_curses(source_dir=FIXTURES)

        self.assertEqual(code, 1)
        self.assertIn("failed: skill/code-review@claude", output.getvalue())
        self.assertIn("next: Fix permissions and retry.", output.getvalue())


class CursesFlowTests(unittest.TestCase):
    """The curses wrapper uses the same profile -> action -> filtered choices order."""

    def test_curses_profiles_then_action_then_filtered_choices(self):
        calls = []

        def _fake_wrapper(ui):
            ui(object())

        def _fake_multiselect(_curses, _stdscr, title, labels, details=None, disabled=None):
            calls.append((title, tuple(labels)))
            if title.startswith("Select profile"):
                return (3,)  # vibe
            if title.startswith("Select artifact"):
                joined = "\n".join(labels)
                self.assertIn("[skill] code-review", joined)
                self.assertIn("Review changes for bugs", joined)
                self.assertIsNotNone(details)
                self.assertNotIn("[mcp] postgres", joined)
                self.assertNotIn("[hook] block-secrets", joined)
                return None  # quit at choices
            raise AssertionError(f"unexpected multiselect: {title}")

        def _fake_singleselect(_curses, _stdscr, title, labels):
            calls.append((title, tuple(labels)))
            if title.startswith("Choose how"):
                self.assertIn("User", labels[0])
                self.assertIn("Maintainer", labels[1])
                return 0  # User
            self.assertEqual(tuple(labels), tui.ACTIONS)
            return 0  # install

        with (
            mock.patch.object(curses, "wrapper", side_effect=_fake_wrapper),
            mock.patch.object(curses, "curs_set", return_value=None),
            mock.patch.object(tui, "_curses_multiselect", side_effect=_fake_multiselect),
            mock.patch.object(tui, "_curses_singleselect", side_effect=_fake_singleselect),
            mock.patch.object(tui, "_curses_install_scope", return_value="project"),
            mock.patch.object(tui, "_curses_install_mode", return_value="copy"),
            mock.patch.object(tui, "_dispatch") as disp,
        ):
            rc = tui._run_curses(source_dir=FIXTURES, project=None)

        self.assertEqual(rc, 0)
        disp.assert_not_called()
        self.assertTrue(calls[0][0].startswith("Choose how"))
        self.assertTrue(calls[1][0].startswith("Select profile"))
        self.assertTrue(calls[2][0].startswith("Action"))
        self.assertTrue(calls[3][0].startswith("Select artifact"))


class InputValidationTests(unittest.TestCase):
    """Bad numeric input re-prompts instead of crashing; selection then proceeds."""

    def test_bad_then_good_selection_reprompts(self):
        captured = {}

        def _recorder(request):
            captured["req"] = request
            return 0

        # Profile + action are valid; "99" and "abc" are bad choice inputs before "1".
        read = _scripted_reader(["1", "1", "1", "1", "", "99", "abc", "1", "y"])
        write, lines = _collector()
        with mock.patch.object(tui, "_dispatch", side_effect=_recorder):
            rc = tui._run_text(read, write, source_dir=FIXTURES, project=None)
        self.assertEqual(rc, 0)
        self.assertEqual(captured["req"].names, ("code-review",))
        # A re-prompt message was emitted.
        self.assertTrue(any("between 1 and" in ln for ln in lines))

    def test_text_question_mark_number_shows_full_description_without_selecting(self):
        choices = (
            tui._Choice(
                "artifact",
                "code-review",
                "skill",
                "[skill] code-review — Review changes safely.",
                description="Review changes safely.",
            ),
        )
        write, lines = _collector()

        picked = tui._prompt_indices(_scripted_reader(["?1", "1"]), write, "Selection: ", choices)

        self.assertEqual(picked, (0,))
        self.assertIn("Review changes safely.", "\n".join(lines))


class TextSelectionParityTests(unittest.TestCase):
    """WP-3 step 7: the silent exit on an empty confirm is gone from the text menu too."""

    def choices(self):
        return (
            tui._Choice("artifact", "review", "skill", "[skill] review — Review a diff."),
            tui._Choice("artifact", "style", "guideline", "[guideline] style — House style."),
        )

    def test_a_blank_answer_re_prompts_and_names_the_way_out(self):
        write, lines = _collector()

        picked = tui._prompt_indices(
            _scripted_reader(["", "2"]), write, "Selection: ", self.choices()
        )

        self.assertEqual(picked, (1,))
        rendered = "\n".join(lines)
        self.assertIn("q", rendered)
        self.assertIn("1 and 2", rendered)

    def test_q_still_leaves_without_a_selection(self):
        write, _lines = _collector()

        self.assertEqual(
            tui._prompt_indices(_scripted_reader(["q"]), write, "Selection: ", self.choices()),
            (),
        )


class NarrowTerminalTests(unittest.TestCase):
    class _Screen:
        def __init__(self, keys=()):
            self.keys = iter(keys)
            self.lines = []
            self.history = []

        def clear(self):
            self.lines.clear()

        def addstr(self, row, column, value):
            self.lines.append((row, column, value))
            self.history.append((row, column, value))

        def refresh(self):
            pass

        def getmaxyx(self):
            return (8, 18)

        def getch(self):
            return next(self.keys)

    def test_ellipsize_never_exceeds_width_and_marks_truncation(self):
        self.assertEqual(tui._ellipsize("abc", 0), "")
        self.assertEqual(tui._ellipsize("abc", 1), "…")
        self.assertEqual(tui._ellipsize("abc", 3), "abc")
        self.assertEqual(tui._ellipsize("abcdef", 4), "abc…")

    def test_draw_list_keeps_each_row_to_one_visual_line(self):
        screen = self._Screen()

        tui._draw_list(
            curses,
            screen,
            "A very long selector title",
            ["[skill] code-review — A deliberately long description"],
            0,
            [False],
        )

        self.assertTrue(screen.lines)
        self.assertTrue(all("\n" not in value for _row, _column, value in screen.lines))
        self.assertTrue(all(len(value) <= 17 for _row, _column, value in screen.lines))
        self.assertTrue(any(value.endswith("…") for _row, _column, value in screen.lines))

    def test_text_choice_row_respects_terminal_width(self):
        choice = tui._Choice(
            "artifact",
            "review",
            "skill",
            "[skill] review — A deliberately long description",
            description="A deliberately long description",
        )

        line = tui._text_choice_line(1, choice, 24)

        self.assertLessEqual(len(line), 24)
        self.assertTrue(line.endswith("…"))
        self.assertLessEqual(len(tui._text_choice_line(1, choice, 4)), 4)

    def test_question_mark_opens_full_curses_detail_then_preserves_selection(self):
        screen = self._Screen((ord("?"), curses.KEY_NPAGE, ord("x"), ord(" "), 10))
        description = (
            "Complete description shown in the detail view, including a final scroll target."
        )

        picked = tui._curses_multiselect(
            curses,
            screen,
            "Artifacts",
            ["[skill] review — Short"],
            details=(description,),
        )

        self.assertEqual(picked, (0,))
        rendered = "\n".join(value for _row, _column, value in screen.history)
        self.assertIn("Complete", rendered)
        self.assertIn("target.", rendered)


class SourceErrorTests(unittest.TestCase):
    """A source/catalog failure is surfaced as a nonzero exit, not an exception."""

    def test_source_factory_error_returns_code(self):
        from agent_artifacts.model import Err

        def _bad_source(_request):
            return Err("boom", code=3)

        read = _scripted_reader(["1", "1", "install", "1", ""])
        write, lines = _collector()
        rc = tui._run_text(read, write, source_factory=_bad_source, source_dir=FIXTURES)
        self.assertEqual(rc, 3)
        self.assertTrue(any("boom" in ln for ln in lines))

    def test_uninstall_does_not_require_source_catalog(self):
        from agent_artifacts.model import Err

        with tempfile.TemporaryDirectory() as project:
            _write_manifest(
                project,
                (
                    ManifestEntry(
                        artifact="code-review",
                        type="skill",
                        profile="claude",
                        source="main:1",
                    ),
                ),
            )

            def _bad_source(_request):
                return Err("boom", code=3)

            captured = {}

            def _recorder(request):
                captured["req"] = request
                return 0

            read = _scripted_reader(["1", "1", "uninstall", "1", "1", "y"])
            write, _ = _collector()
            with mock.patch.object(tui, "_dispatch", side_effect=_recorder):
                rc = tui._run_text(
                    read,
                    write,
                    source_factory=_bad_source,
                    source_dir=FIXTURES,
                    project=project,
                )

        self.assertEqual(rc, 0)
        self.assertEqual(captured["req"].command, "uninstall")

    def test_empty_catalog_returns_zero(self):
        # A source whose catalog has no artifacts/bundles -> clean 0, no dispatch.
        class _EmptySource:
            def label(self):
                return "local:empty"

            def catalog(self):
                from agent_artifacts.model import Catalog

                return Ok(Catalog(artifacts={}, bundles={}))

        read = _scripted_reader(["1", "1", "install", "1", ""])
        write, lines = _collector()
        with mock.patch.object(tui, "_dispatch") as disp:
            rc = tui._run_text(
                read,
                write,
                source_factory=lambda _r: Ok(_EmptySource()),
                source_dir=FIXTURES,
            )
        self.assertEqual(rc, 0)
        disp.assert_not_called()
        self.assertTrue(any("No installable artifacts" in ln for ln in lines))


if __name__ == "__main__":
    unittest.main()
