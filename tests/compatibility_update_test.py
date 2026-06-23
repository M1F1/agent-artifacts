import contextlib
import io
import json
import os
import pathlib
import shutil
import tempfile
import unittest

from agent_artifacts.commands import _common, install, update
from agent_artifacts.model import Request

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
PROFILE = "claude"
DEST = os.path.join(".claude", "guidelines", "python-style.md")


def _copy_source(tmp: str, name: str) -> str:
    source = os.path.join(tmp, name)
    shutil.copytree(FIXTURES, source)
    return source


def _install_guideline(source: str, project: str) -> None:
    request = Request(
        command="install",
        names=("python-style",),
        profiles=(PROFILE,),
        source_dir=source,
        project=project,
    )
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        code = install.run(request)
    if code != 0:
        raise AssertionError(f"install failed with code {code}")


def _restrict_guideline(source: str, body: str = "# Restricted upstream\n") -> None:
    path = os.path.join(source, "guidelines", "python-style.md")
    pathlib.Path(path).write_text(
        f"---\ndescription: Python style\ncompatibility.profiles: tabnine\n---\n{body}",
        encoding="utf-8",
    )


def _run(request: Request) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = update.run(request)
    return code, out.getvalue()


class CompatibilityUpdateTests(unittest.TestCase):
    def test_explicit_incompatible_update_is_usage_error_even_with_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = os.path.join(tmp, "project")
            source = _copy_source(tmp, "source")
            _install_guideline(source, project)
            restricted = _copy_source(tmp, "restricted")
            _restrict_guideline(restricted)

            before_manifest = pathlib.Path(
                os.path.join(project, ".agent-artifacts", "manifest.json")
            ).read_text(encoding="utf-8")
            request = Request(
                command="update",
                names=("python-style",),
                source_dir=restricted,
                project=project,
                force=True,
            )
            code, out = _run(request)

            self.assertEqual(code, _common.USAGE)
            self.assertIn("not compatible", out)
            after_manifest = pathlib.Path(
                os.path.join(project, ".agent-artifacts", "manifest.json")
            ).read_text(encoding="utf-8")
            self.assertEqual(after_manifest, before_manifest)

    def test_broad_update_skips_incompatible_entry_and_leaves_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = os.path.join(tmp, "project")
            source = _copy_source(tmp, "source")
            _install_guideline(source, project)
            dest = os.path.join(project, DEST)
            before_text = pathlib.Path(dest).read_text(encoding="utf-8")
            restricted = _copy_source(tmp, "restricted")
            _restrict_guideline(restricted, body="# Should not land\n")

            request = Request(
                command="update",
                source_dir=restricted,
                project=project,
                json=True,
            )
            code, out = _run(request)

            self.assertEqual(code, _common.OK)
            payload = json.loads(out)
            self.assertEqual(payload["performed"], [])
            self.assertEqual(payload["conflict"], False)
            self.assertEqual(
                payload["skipped"],
                [
                    {
                        "artifact": "python-style",
                        "type": "guideline",
                        "profile": PROFILE,
                        "reason": "incompatible-profile",
                        "allowed_profiles": ["tabnine"],
                    }
                ],
            )
            self.assertEqual(pathlib.Path(dest).read_text(encoding="utf-8"), before_text)

    def test_dry_run_json_reports_skip_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = os.path.join(tmp, "project")
            source = _copy_source(tmp, "source")
            _install_guideline(source, project)
            dest = os.path.join(project, DEST)
            before_text = pathlib.Path(dest).read_text(encoding="utf-8")
            restricted = _copy_source(tmp, "restricted")
            _restrict_guideline(restricted)

            request = Request(
                command="update",
                source_dir=restricted,
                project=project,
                dry_run=True,
                json=True,
            )
            code, out = _run(request)

            self.assertEqual(code, _common.OK)
            payload = json.loads(out)
            self.assertEqual(payload["actions"], [])
            self.assertEqual(payload["skipped"][0]["reason"], "incompatible-profile")
            self.assertEqual(pathlib.Path(dest).read_text(encoding="utf-8"), before_text)

    def test_prune_does_not_remove_incompatible_selected_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = os.path.join(tmp, "project")
            source = _copy_source(tmp, "source")
            _install_guideline(source, project)
            restricted = _copy_source(tmp, "restricted")
            _restrict_guideline(restricted)

            request = Request(
                command="update",
                source_dir=restricted,
                project=project,
                prune=True,
                json=True,
            )
            code, _out = _run(request)

            self.assertEqual(code, _common.OK)
            manifest = _common.load_manifest(Request(command="status", project=project)).value
            self.assertEqual(len(manifest.installed), 1)
            self.assertEqual(manifest.installed[0].artifact, "python-style")
            self.assertTrue(os.path.exists(os.path.join(project, DEST)))


if __name__ == "__main__":
    unittest.main()
