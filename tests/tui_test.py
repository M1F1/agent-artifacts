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
        self.assertFalse(
            tui.artifact_visible_for_profiles(mcp, ("claude", "vibe"), self.profiles)
        )
        self.assertTrue(
            tui.artifact_visible_for_profiles(skill, ("claude", "vibe"), self.profiles)
        )

    def test_build_install_choices_filters_artifacts_for_vibe(self):
        choices = tui.build_install_choices(self.catalog, ("vibe",), self.profiles)
        labels = [choice.label for choice in choices]
        self.assertIn("[skill] code-review", labels)
        self.assertIn("[guideline] python-style", labels)
        self.assertIn("[memory] house", labels)
        self.assertFalse(any("[mcp]" in label for label in labels))
        self.assertFalse(any("[hook]" in label for label in labels))

    def test_build_install_choices_shows_tabnine_only_mcp_for_tabnine(self):
        choices = tui.build_install_choices(self.catalog, ("tabnine",), self.profiles)
        self.assertIn("[mcp] tabnine-postgres", [choice.label for choice in choices])

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
        read = _scripted_reader(["1", "install", "1"])
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
        read = _scripted_reader(["1", "1", "1"])
        write, _ = _collector()
        with redirect_stdout(io.StringIO()):
            rc = tui._run_text(read, write, source_dir=FIXTURES, project=self.project)
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isfile(self._path(".claude", "skills", "code-review", "SKILL.md")))

    def test_vibe_flow_hides_incompatible_artifacts_before_selection(self):
        read = _scripted_reader(["4", "install", "q"])  # vibe, install, quit at choices
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

    def test_tabnine_flow_shows_tabnine_only_mcp(self):
        read = _scripted_reader(["3", "install", "q"])  # tabnine, install, quit at choices
        write, lines = _collector()
        with mock.patch.object(tui, "_dispatch") as disp:
            rc = tui._run_text(read, write, source_dir=FIXTURES, project=self.project)
        self.assertEqual(rc, 0)
        disp.assert_not_called()
        self.assertIn("[mcp] tabnine-postgres", "\n".join(lines))

    def test_claude_flow_hides_tabnine_only_mcp(self):
        read = _scripted_reader(["1", "install", "q"])  # claude, install, quit at choices
        write, lines = _collector()
        with mock.patch.object(tui, "_dispatch") as disp:
            rc = tui._run_text(read, write, source_dir=FIXTURES, project=self.project)
        self.assertEqual(rc, 0)
        disp.assert_not_called()
        self.assertNotIn("[mcp] tabnine-postgres", "\n".join(lines))

    def test_multi_profile_flow_uses_intersection_filtering(self):
        read = _scripted_reader(["1,4", "install", "q"])  # claude+vibe
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
        read = _scripted_reader(["4", "install", "4"])
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
        read = _scripted_reader(["4", "uninstall", "q"])  # vibe
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
        read = _scripted_reader(["1", "update", "q"])  # claude
        write, lines = _collector()
        with mock.patch.object(tui, "_dispatch") as disp:
            rc = tui._run_text(read, write, source_dir=FIXTURES, project=self.project)
        self.assertEqual(rc, 0)
        disp.assert_not_called()
        self.assertIn("[skill] code-review", "\n".join(lines))

    def test_no_matching_installed_entries_returns_without_dispatch(self):
        read = _scripted_reader(["1", "uninstall"])  # no manifest entries
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
        read = _scripted_reader(["q"])
        write, _ = _collector()
        with mock.patch.object(tui, "_dispatch") as disp:
            rc = tui._run_text(read, write, source_dir=FIXTURES, project=None)
        self.assertEqual(rc, 0)
        disp.assert_not_called()

    def test_quit_at_action_prompt(self):
        read = _scripted_reader(["1", "q"])  # pick profile, quit at action
        write, _ = _collector()
        with mock.patch.object(tui, "_dispatch") as disp:
            rc = tui._run_text(read, write, source_dir=FIXTURES, project=None)
        self.assertEqual(rc, 0)
        disp.assert_not_called()

    def test_quit_at_selection_prompt(self):
        read = _scripted_reader(["1", "1", "q"])  # profile + action, quit at choices
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

        read = _scripted_reader(["1", "install", "1"])
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

        read = _scripted_reader(["1", "install", "6"])
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

        read = _scripted_reader(["1", "install", "1,3"])  # code-review + postgres
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
            read = _scripted_reader(["1", "uninstall", "1"])
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


class CursesFlowTests(unittest.TestCase):
    """The curses wrapper uses the same profile -> action -> filtered choices order."""

    def test_curses_profiles_then_action_then_filtered_choices(self):
        calls = []

        def _fake_wrapper(ui):
            ui(object())

        def _fake_multiselect(_curses, _stdscr, title, labels):
            calls.append((title, tuple(labels)))
            if title.startswith("Select profile"):
                return (3,)  # vibe
            if title.startswith("Select artifact"):
                joined = "\n".join(labels)
                self.assertIn("[skill] code-review", joined)
                self.assertNotIn("[mcp] postgres", joined)
                self.assertNotIn("[hook] block-secrets", joined)
                return None  # quit at choices
            raise AssertionError(f"unexpected multiselect: {title}")

        def _fake_singleselect(_curses, _stdscr, title, labels):
            calls.append((title, tuple(labels)))
            self.assertEqual(tuple(labels), tui.ACTIONS)
            return 0  # install

        with (
            mock.patch.object(curses, "wrapper", side_effect=_fake_wrapper),
            mock.patch.object(curses, "curs_set", return_value=None),
            mock.patch.object(tui, "_curses_multiselect", side_effect=_fake_multiselect),
            mock.patch.object(tui, "_curses_singleselect", side_effect=_fake_singleselect),
            mock.patch.object(tui, "_dispatch") as disp,
        ):
            rc = tui._run_curses(source_dir=FIXTURES, project=None)

        self.assertEqual(rc, 0)
        disp.assert_not_called()
        self.assertTrue(calls[0][0].startswith("Select profile"))
        self.assertTrue(calls[1][0].startswith("Action"))
        self.assertTrue(calls[2][0].startswith("Select artifact"))


class InputValidationTests(unittest.TestCase):
    """Bad numeric input re-prompts instead of crashing; selection then proceeds."""

    def test_bad_then_good_selection_reprompts(self):
        captured = {}

        def _recorder(request):
            captured["req"] = request
            return 0

        # Profile + action are valid; "99" and "abc" are bad choice inputs before "1".
        read = _scripted_reader(["1", "1", "99", "abc", "1"])
        write, lines = _collector()
        with mock.patch.object(tui, "_dispatch", side_effect=_recorder):
            rc = tui._run_text(read, write, source_dir=FIXTURES, project=None)
        self.assertEqual(rc, 0)
        self.assertEqual(captured["req"].names, ("code-review",))
        # A re-prompt message was emitted.
        self.assertTrue(any("between 1 and" in ln for ln in lines))


class SourceErrorTests(unittest.TestCase):
    """A source/catalog failure is surfaced as a nonzero exit, not an exception."""

    def test_source_factory_error_returns_code(self):
        from agent_artifacts.model import Err

        def _bad_source(_request):
            return Err("boom", code=3)

        read = _scripted_reader(["1", "install"])
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

            read = _scripted_reader(["1", "uninstall", "1"])
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

        read = _scripted_reader(["1", "install"])
        write, lines = _collector()
        with mock.patch.object(tui, "_dispatch") as disp:
            rc = tui._run_text(read, write, source_factory=lambda _r: Ok(_EmptySource()))
        self.assertEqual(rc, 0)
        disp.assert_not_called()
        self.assertTrue(any("No installable artifacts" in ln for ln in lines))


if __name__ == "__main__":
    unittest.main()
