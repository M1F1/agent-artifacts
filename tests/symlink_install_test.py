"""Tests for opt-in symlink install mode."""

from __future__ import annotations

import contextlib
import io
import json
import os
import pathlib
import shutil
import tempfile
import unittest

from agent_artifacts import planners
from agent_artifacts.commands import check, install, status, uninstall, update
from agent_artifacts.model import Artifact, CopyTree, Request, SymlinkTree

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "tests" / "fixtures"


class SymlinkInstallTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self.project = self.root / "project"
        self.source = self.root / "source"
        shutil.copytree(FIXTURES, self.source)
        self.project.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _install_req(self, **kwargs) -> Request:
        base = dict(
            command="install",
            source_dir=str(self.source),
            project=str(self.project),
            profiles=("claude",),
            install_mode="symlink",
        )
        base.update(kwargs)
        return Request(**base)

    def test_skill_symlink_install_records_metadata_and_is_live(self):
        req = self._install_req(names=("code-review",))
        with contextlib.redirect_stdout(io.StringIO()):
            code = install.run(req)
        self.assertEqual(code, 0)

        dest = self.project / ".claude" / "skills" / "code-review"
        target = self.source / "skills" / "code-review"
        self.assertTrue(dest.is_symlink())
        self.assertEqual(os.readlink(dest), str(target))

        source_skill = target / "SKILL.md"
        source_skill.write_text(source_skill.read_text(encoding="utf-8") + "\nlinked edit\n", encoding="utf-8")
        self.assertIn("linked edit", (dest / "SKILL.md").read_text(encoding="utf-8"))

        manifest = json.loads((self.project / ".agent-artifacts" / "manifest.json").read_text())
        entry = manifest["installed"][0]
        self.assertEqual(entry["install"]["mode"], "symlink")
        self.assertEqual(entry["install"]["requested_mode"], "symlink")
        self.assertEqual(entry["install"]["links"][0]["path"], ".claude/skills/code-review")
        self.assertEqual(entry["install"]["links"][0]["target"], str(target))

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = status.run(Request(command="status", project=str(self.project), json=True))
        self.assertEqual(code, 0)
        report = json.loads(buf.getvalue())
        installed = report["installed"][0]
        self.assertEqual(installed["install"]["mode"], "symlink")
        self.assertEqual(installed["files"][0]["state"], "ok (symlink)")
        self.assertTrue(installed["files"][0]["target_exists"])

    def test_uninstall_removes_symlink_not_target(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(install.run(self._install_req(names=("code-review",))), 0)
            self.assertEqual(
                uninstall.run(
                    Request(
                        command="uninstall",
                        project=str(self.project),
                        names=("code-review",),
                    )
                ),
                0,
            )

        dest = self.project / ".claude" / "skills" / "code-review"
        target = self.source / "skills" / "code-review"
        self.assertFalse(os.path.lexists(dest))
        self.assertTrue((target / "SKILL.md").exists())

    def test_update_reports_existing_symlink_as_live_linked(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(install.run(self._install_req(names=("code-review",))), 0)

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = update.run(
                Request(
                    command="update",
                    source_dir=str(self.source),
                    project=str(self.project),
                    names=("code-review",),
                    json=True,
                )
            )
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertTrue(any("live-linked" in warning for warning in payload["warnings"]))
        self.assertFalse(any(line.startswith("symlink_tree") for line in payload["performed"]))

    def test_update_prune_removes_symlink_not_target(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(install.run(self._install_req(names=("code-review",))), 0)
            self.assertEqual(
                install.run(
                    Request(
                        command="install",
                        source_dir=str(self.source),
                        project=str(self.project),
                        profiles=("claude",),
                        names=("python-style",),
                    )
                ),
                0,
            )

        with contextlib.redirect_stdout(io.StringIO()):
            code = update.run(
                Request(
                    command="update",
                    source_dir=str(self.source),
                    project=str(self.project),
                    names=("python-style",),
                    prune=True,
                    json=True,
                )
            )
        self.assertEqual(code, 0)
        self.assertFalse(os.path.lexists(self.project / ".claude" / "skills" / "code-review"))
        self.assertTrue((self.source / "skills" / "code-review" / "SKILL.md").exists())

    def test_check_reports_live_linked_entries(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(install.run(self._install_req(names=("code-review",))), 0)

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self.close()
                return False

        def opener(_request):
            return Resp(json.dumps({"sha": "f" * 40}).encode("utf-8"))

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = check._check(
                Request(
                    command="check",
                    repo="org/agent-artifacts",
                    project=str(self.project),
                    json=True,
                ),
                opener=opener,
            )
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["live_linked"], ["skill/code-review"])

    def test_status_reports_broken_retargeted_and_replaced_links(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(install.run(self._install_req(names=("code-review",))), 0)
        dest = self.project / ".claude" / "skills" / "code-review"
        target = self.source / "skills" / "code-review"

        shutil.rmtree(target)
        self.assertEqual(self._status_state(), "broken symlink")

        target.mkdir(parents=True)
        other = self.root / "other-target"
        other.mkdir()
        dest.unlink()
        os.symlink(other, dest, target_is_directory=True)
        self.assertEqual(self._status_state(), "retargeted symlink")

        dest.unlink()
        dest.mkdir()
        self.assertEqual(self._status_state(), "replaced")

    def test_explicit_non_linkable_artifact_is_usage_error(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = install.run(self._install_req(names=("python-style",)))
        self.assertEqual(code, 2)
        self.assertIn("cannot be symlink-installed", err.getvalue())
        self.assertEqual(list(self.project.iterdir()), [])

    def test_broad_link_install_warns_and_copies_non_linkable_artifacts(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = install.run(self._install_req(all=True, json=True))
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertTrue(any("--link only applies" in warning for warning in payload["warnings"]))

        by_artifact = {item["artifact"]: item for item in payload["installed"]}
        self.assertEqual(by_artifact["code-review"]["install"]["mode"], "symlink")
        self.assertEqual(by_artifact["python-style"]["install"]["mode"], "copy")
        self.assertEqual(by_artifact["python-style"]["install"]["requested_mode"], "symlink")
        self.assertTrue((self.project / ".claude" / "skills" / "code-review").is_symlink())
        self.assertTrue((self.project / ".claude" / "guidelines" / "python-style.md").is_file())

    def test_link_with_repo_is_usage_error_without_network(self):
        err = io.StringIO()
        req = Request(
            command="install",
            repo="owner/repo",
            project=str(self.project),
            profiles=("claude",),
            names=("code-review",),
            install_mode="symlink",
        )
        with contextlib.redirect_stderr(err):
            code = install.run(req)
        self.assertEqual(code, 2)
        self.assertIn("--link requires a local source", err.getvalue())

    def _status_state(self) -> str:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = status.run(Request(command="status", project=str(self.project), json=True))
        self.assertEqual(code, 0)
        report = json.loads(buf.getvalue())
        return report["installed"][0]["files"][0]["state"]


class SymlinkPlannerTests(unittest.TestCase):
    def test_skill_planner_emits_symlink_tree_for_symlink_mode(self):
        art = Artifact(type="skill", name="code-review", root="skills/code-review")
        result = planners.plan_skill(
            art,
            ".claude/skills/<name>/",
            install_mode="symlink",
        )
        self.assertEqual(
            result.value,
            (SymlinkTree(src="skills/code-review", dst=".claude/skills/code-review"),),
        )

    def test_skill_planner_keeps_copy_default(self):
        art = Artifact(type="skill", name="code-review", root="skills/code-review")
        result = planners.plan_skill(art, ".claude/skills/<name>/")
        self.assertEqual(
            result.value,
            (CopyTree(src="skills/code-review", dst=".claude/skills/code-review"),),
        )


if __name__ == "__main__":
    unittest.main()
