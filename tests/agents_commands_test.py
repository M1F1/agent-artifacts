"""WP-29 — commands wiring for the ``agents`` artifact type (install/uninstall/status/list).

Drives the real command ``run`` functions against the repo root as a local ``--source`` (it
ships ``agents/house.md`` plus the ``base``/``backend`` bundles), into a fresh temp project,
asserting on-disk effects + manifest entries. Covers:

- install ``house`` into ``claude`` (file kind) in every mode (prepend/append/replace/skip);
- install into ``tabnine`` (dir kind) -> ``.tabnine/guidelines/house.md``;
- the unsupported-type policy (DESIGN-agents.md §5): by-name -> USAGE; by-bundle -> warn+skip;
- uninstall: prepend strips the block (foreign content preserved); replace restores the .bak;
- status / ``list --type agents`` smoke.

Run: ``python -m unittest discover -s tests -p "agents_commands_test.py" -v``.
"""

import io
import json
import os
import pathlib
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from agent_artifacts.commands import install, list as list_cmd, status, uninstall
from agent_artifacts.model import Request

REPO_ROOT = str(pathlib.Path(__file__).resolve().parents[1])

# The HTML-comment markers plan_agents wraps our block in (DESIGN-agents.md §3.3).
BEGIN = "<!-- >>> agent-artifacts agents:house >>> -->"
END = "<!-- <<< agent-artifacts agents:house <<< -->"
# A line we know is in agents/house.md (the seeded body).
BODY_MARK = "Engineering house rules"
BAK_SUFFIX = ".agent-artifacts-bak"


def _install(project, **kw) -> Request:
    return Request(command="install", source_dir=REPO_ROOT, project=project, **kw)


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def path(self, *parts) -> str:
        return os.path.join(self.project, *parts)

    def read(self, *parts) -> str:
        return pathlib.Path(self.path(*parts)).read_text()

    def run_quiet(self, req) -> int:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return install.run(req) if req.command == "install" else uninstall.run(req)

    def manifest(self) -> dict:
        return json.loads(self.read(".agent-artifacts", "manifest.json"))


# --------------------------------------------------------------------------- #
# install — file kind (claude), all four modes                                 #
# --------------------------------------------------------------------------- #
class InstallFileModes(_Base):
    def test_prepend_creates_sentinel_block_in_claude_md(self):
        code = self.run_quiet(_install(self.project, names=("house",), profiles=("claude",)))
        self.assertEqual(code, 0)
        text = self.read("CLAUDE.md")
        self.assertIn(BEGIN, text)
        self.assertIn(END, text)
        self.assertIn(BODY_MARK, text)
        # Manifest carries an agents entry for the claude profile.
        entries = self.manifest()["installed"]
        agents = [e for e in entries if e["type"] == "agents"]
        self.assertEqual(len(agents), 1)
        self.assertEqual(agents[0]["artifact"], "house")
        self.assertEqual(agents[0]["profile"], "claude")

    def test_prepend_puts_our_block_above_foreign_content(self):
        # Pre-seed CLAUDE.md with foreign content; prepend must land ABOVE it, foreign kept.
        os.makedirs(self.project, exist_ok=True)
        pathlib.Path(self.path("CLAUDE.md")).write_text("# Pre-existing\n- keep me\n")
        import agent_artifacts.commands.install as install
        code = install.run(
            _install(self.project, names=("house",), profiles=("claude",), agents_mode="prepend")
        )
        self.assertEqual(code, 0)
        text = self.read("CLAUDE.md")
        self.assertIn("keep me", text)  # foreign content preserved
        self.assertLess(text.index(BEGIN), text.index("Pre-existing"))  # our block first

    def test_append_puts_our_block_below_foreign_content(self):
        pathlib.Path(self.path("CLAUDE.md")).write_text("# Pre-existing\n- keep me\n")
        code = self.run_quiet(
            _install(self.project, names=("house",), profiles=("claude",), agents_mode="append")
        )
        self.assertEqual(code, 0)
        text = self.read("CLAUDE.md")
        self.assertIn("keep me", text)
        self.assertGreater(text.index(BEGIN), text.index("Pre-existing"))  # our block last

    def test_replace_into_empty_file_writes_whole_body_no_sentinel(self):
        code = self.run_quiet(
            _install(self.project, names=("house",), profiles=("claude",), agents_mode="replace")
        )
        self.assertEqual(code, 0)
        text = self.read("CLAUDE.md")
        self.assertIn(BODY_MARK, text)
        self.assertNotIn(BEGIN, text)  # replace writes the raw body, no markers

    def test_replace_over_foreign_requires_force_then_backs_up(self):
        pathlib.Path(self.path("CLAUDE.md")).write_text("# Foreign rules\n")
        # Without --force: CONFLICT (4), nothing written.
        code = self.run_quiet(
            _install(self.project, names=("house",), profiles=("claude",), agents_mode="replace")
        )
        self.assertEqual(code, 4)
        self.assertEqual(self.read("CLAUDE.md"), "# Foreign rules\n")  # untouched
        # With --force: body replaces the file and the prior content is backed up.
        code = self.run_quiet(
            _install(
                self.project, names=("house",), profiles=("claude",),
                agents_mode="replace", force=True,
            )
        )
        self.assertEqual(code, 0)
        self.assertIn(BODY_MARK, self.read("CLAUDE.md"))
        self.assertEqual(self.read("CLAUDE.md" + BAK_SUFFIX), "# Foreign rules\n")

    def test_skip_with_existing_file_leaves_it_untouched(self):
        pathlib.Path(self.path("CLAUDE.md")).write_text("# Hand-authored\n")
        code = self.run_quiet(
            _install(self.project, names=("house",), profiles=("claude",), agents_mode="skip")
        )
        self.assertEqual(code, 0)
        self.assertEqual(self.read("CLAUDE.md"), "# Hand-authored\n")  # seed-if-missing: skipped

    def test_skip_when_absent_creates_the_file(self):
        code = self.run_quiet(
            _install(self.project, names=("house",), profiles=("claude",), agents_mode="skip")
        )
        self.assertEqual(code, 0)
        self.assertIn(BODY_MARK, self.read("CLAUDE.md"))

    def test_prepend_reinstall_is_idempotent(self):
        req = _install(self.project, names=("house",), profiles=("claude",), agents_mode="prepend")
        self.run_quiet(req)
        first = self.read("CLAUDE.md")
        self.run_quiet(req)
        self.assertEqual(self.read("CLAUDE.md"), first)  # byte-identical re-install


# --------------------------------------------------------------------------- #
# install — dir kind (tabnine)                                                  #
# --------------------------------------------------------------------------- #
class InstallDirKind(_Base):
    def setUp(self):
        super().setUp()
        os.makedirs(self.path(".agent-artifacts"), exist_ok=True)
        pathlib.Path(self.path(".agent-artifacts", "profiles.json")).write_text(json.dumps({
            "dirprof": {
                "name": "dirprof",
                "agents": {"kind": "dir", "dest": "somedir/"}
            }
        }))

    def test_dir_kind_writes_named_file_in_dest_dir(self):
        code = self.run_quiet(_install(self.project, names=("house",), profiles=("dirprof",)))
        self.assertEqual(code, 0)
        dest = self.path("somedir", "house.md")
        self.assertTrue(os.path.isfile(dest))
        self.assertIn(BODY_MARK, pathlib.Path(dest).read_text())
        # manifest proof points at the dir-copy destination
        entry = [e for e in self.manifest()["installed"] if e["type"] == "agents"][0]
        self.assertIn("somedir/house.md", entry["files"])


# --------------------------------------------------------------------------- #
# unsupported-type policy (DESIGN-agents.md §5)                                 #
# --------------------------------------------------------------------------- #
class UnsupportedTypePolicy(_Base):
    def test_by_name_unsupported_type_errors_usage(self):
        # postgres is an mcp; vibe.mcp is None -> explicit by-name request must fail USAGE.
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            code = install.run(_install(self.project, names=("postgres",), profiles=("vibe",)))
        self.assertEqual(code, 2)  # _common.USAGE
        self.assertIn("vibe", err.getvalue())
        # Nothing installed: no manifest written.
        self.assertFalse(os.path.exists(self.path(".agent-artifacts", "manifest.json")))

    def test_by_bundle_warns_and_skips_unsupported_but_installs_supported(self):
        # backend = base (skill/guideline/agents) + mcp:postgres. Into vibe (mcp=None) the
        # mcp must warn+skip while the supported types install and the run exits OK.
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            code = install.run(_install(self.project, bundles=("backend",), profiles=("vibe",)))
        self.assertEqual(code, 0)
        # agents (house) installed into AGENTS.md via prepend (vibe agents kind=file).
        self.assertIn(BEGIN, self.read("AGENTS.md"))
        # supported types present in the manifest; the unsupported mcp is absent.
        types = {e["type"] for e in self.manifest()["installed"]}
        self.assertIn("agents", types)
        self.assertIn("skill", types)
        self.assertNotIn("mcp", types)
        # a warning mentioning the skipped postgres mcp was surfaced.
        self.assertIn("postgres", out.getvalue())


# --------------------------------------------------------------------------- #
# uninstall reversal                                                            #
# --------------------------------------------------------------------------- #
class UninstallReversal(_Base):
    def test_prepend_uninstall_strips_block_keeps_foreign(self):
        pathlib.Path(self.path("CLAUDE.md")).write_text("# Pre-existing\n- keep me\n")
        self.run_quiet(
            _install(self.project, names=("house",), profiles=("claude",), agents_mode="prepend")
        )
        self.assertIn(BEGIN, self.read("CLAUDE.md"))
        # uninstall by name from the claude profile.
        code = self.run_quiet(
            Request(command="uninstall", names=("house",), profiles=("claude",), project=self.project)
        )
        self.assertEqual(code, 0)
        text = self.read("CLAUDE.md")
        self.assertNotIn(BEGIN, text)  # our block gone
        self.assertNotIn(BODY_MARK, text)
        self.assertIn("keep me", text)  # foreign content preserved
        # manifest entry dropped
        self.assertEqual(self.manifest()["installed"], [])

    def test_replace_uninstall_restores_backup(self):
        pathlib.Path(self.path("CLAUDE.md")).write_text("# Foreign rules\n- precious\n")
        self.run_quiet(
            _install(
                self.project, names=("house",), profiles=("claude",),
                agents_mode="replace", force=True,
            )
        )
        # after replace: our body in CLAUDE.md, foreign in the .bak
        self.assertIn(BODY_MARK, self.read("CLAUDE.md"))
        self.assertTrue(os.path.exists(self.path("CLAUDE.md" + BAK_SUFFIX)))
        # uninstall removes our file and restores the backup over it.
        code = self.run_quiet(
            Request(command="uninstall", names=("house",), profiles=("claude",), project=self.project)
        )
        self.assertEqual(code, 0)
        self.assertEqual(self.read("CLAUDE.md"), "# Foreign rules\n- precious\n")  # restored
        self.assertFalse(os.path.exists(self.path("CLAUDE.md" + BAK_SUFFIX)))  # bak consumed


# --------------------------------------------------------------------------- #
# status / list smoke                                                          #
# --------------------------------------------------------------------------- #
class StatusAndList(_Base):
    def test_status_reports_installed_agents_entry(self):
        self.run_quiet(_install(self.project, names=("house",), profiles=("claude",)))
        out = io.StringIO()
        with redirect_stdout(out):
            code = status.run(Request(command="status", project=self.project, json=True))
        self.assertEqual(code, 0)
        report = json.loads(out.getvalue())
        agents = [e for e in report["installed"] if e["type"] == "agents"]
        self.assertEqual(len(agents), 1)
        self.assertEqual(agents[0]["artifact"], "house")
        # the CLAUDE.md file is tracked and reports a non-missing state.
        states = {f["path"]: f["state"] for f in agents[0]["files"]}
        self.assertTrue(any("CLAUDE.md" in p for p in states))
        self.assertNotIn("missing", states.values())

    def test_list_type_agents_shows_house(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = list_cmd.run(
                Request(command="list", source_dir=REPO_ROOT, type_filter="agents", json=True)
            )
        self.assertEqual(code, 0)
        obj = json.loads(out.getvalue())
        names = {a["name"] for a in obj["artifacts"] if a["type"] == "agents"}
        self.assertIn("house", names)
        # --type filter restricts to agents only.
        self.assertEqual({a["type"] for a in obj["artifacts"]}, {"agents"})


if __name__ == "__main__":
    unittest.main()
