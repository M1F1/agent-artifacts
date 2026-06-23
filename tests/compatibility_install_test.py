import contextlib
import io
import json
import os
import pathlib
import shutil
import tempfile
import unittest

from agent_artifacts.commands import install
from agent_artifacts.model import Request

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"


def _copy_source(tmp: str) -> str:
    source = os.path.join(tmp, "source")
    shutil.copytree(FIXTURES, source)
    restricted = {
        "name": "tabnine-postgres",
        "description": "Tabnine-only Postgres MCP.",
        "compatibility": {"profiles": ["tabnine"]},
        "server": {"command": "npx", "args": ["-y", "postgres"]},
    }
    path = os.path.join(source, "mcp", "tabnine-postgres.json")
    pathlib.Path(path).write_text(json.dumps(restricted), encoding="utf-8")
    bundle_path = os.path.join(source, "bundles", "backend.json")
    bundle = json.loads(pathlib.Path(bundle_path).read_text(encoding="utf-8"))
    mcp = bundle["includes"].setdefault("mcp", [])
    if "tabnine-postgres" not in mcp:
        mcp.append("tabnine-postgres")
    pathlib.Path(bundle_path).write_text(json.dumps(bundle), encoding="utf-8")
    return source


def _run(request: Request) -> tuple[int, str, str]:
    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = install.run(request)
    return code, out.getvalue(), err.getvalue()


class CompatibilityInstallTests(unittest.TestCase):
    def test_explicit_incompatible_install_is_usage_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = _copy_source(tmp)
            project = os.path.join(tmp, "project")
            request = Request(
                command="install",
                names=("tabnine-postgres",),
                profiles=("claude",),
                source_dir=source,
                project=project,
            )
            code, _out, err = _run(request)

            self.assertEqual(code, 2)
            self.assertIn("not compatible", err)
            self.assertIn("allowed: tabnine", err)
            self.assertFalse(os.path.exists(os.path.join(project, ".mcp.json")))

    def test_explicit_compatible_install_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = _copy_source(tmp)
            project = os.path.join(tmp, "project")
            request = Request(
                command="install",
                names=("tabnine-postgres",),
                profiles=("tabnine",),
                source_dir=source,
                project=project,
            )
            code, out, err = _run(request)

            self.assertEqual(code, 0, err)
            self.assertIn("tabnine-postgres", out)
            settings = os.path.join(project, ".tabnine", "agent", "settings.json")
            self.assertTrue(os.path.exists(settings))
            data = json.loads(pathlib.Path(settings).read_text(encoding="utf-8"))
            self.assertIn("tabnine-postgres", data["mcpServers"])

    def test_bundle_skips_incompatible_target_with_json_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = _copy_source(tmp)
            project = os.path.join(tmp, "project")
            request = Request(
                command="install",
                bundles=("backend",),
                profiles=("claude",),
                source_dir=source,
                project=project,
                json=True,
            )
            code, out, err = _run(request)

            self.assertEqual(code, 0, err)
            payload = json.loads(out)
            skipped = payload["skipped"]
            self.assertTrue(
                any(
                    item["artifact"] == "tabnine-postgres"
                    and item["profile"] == "claude"
                    and item["reason"] == "incompatible-profile"
                    and item["allowed_profiles"] == ["tabnine"]
                    for item in skipped
                ),
                skipped,
            )
            installed = {item["artifact"] for item in payload["installed"]}
            self.assertIn("postgres", installed)
            self.assertNotIn("tabnine-postgres", installed)

    def test_all_skips_incompatible_target_with_json_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = _copy_source(tmp)
            project = os.path.join(tmp, "project")
            request = Request(
                command="install",
                all=True,
                profiles=("claude",),
                source_dir=source,
                project=project,
                json=True,
            )
            code, out, err = _run(request)

            self.assertEqual(code, 0, err)
            payload = json.loads(out)
            self.assertTrue(
                any(
                    item["artifact"] == "tabnine-postgres"
                    and item["reason"] == "incompatible-profile"
                    for item in payload["skipped"]
                ),
                payload["skipped"],
            )
            installed = {item["artifact"] for item in payload["installed"]}
            self.assertNotIn("tabnine-postgres", installed)

    def test_multi_profile_installs_and_skips_per_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = _copy_source(tmp)
            project = os.path.join(tmp, "project")
            request = Request(
                command="install",
                bundles=("backend",),
                profiles=("claude", "tabnine"),
                source_dir=source,
                project=project,
                json=True,
            )
            code, out, err = _run(request)

            self.assertEqual(code, 0, err)
            payload = json.loads(out)
            installed = {
                (item["artifact"], item["profile"]) for item in payload["installed"]
            }
            self.assertIn(("tabnine-postgres", "tabnine"), installed)
            self.assertNotIn(("tabnine-postgres", "claude"), installed)
            self.assertTrue(
                any(
                    item["artifact"] == "tabnine-postgres"
                    and item["profile"] == "claude"
                    for item in payload["skipped"]
                )
            )

    def test_dry_run_json_reports_skips_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = _copy_source(tmp)
            project = os.path.join(tmp, "project")
            os.makedirs(project)
            request = Request(
                command="install",
                bundles=("backend",),
                profiles=("claude",),
                source_dir=source,
                project=project,
                dry_run=True,
                json=True,
            )
            code, out, err = _run(request)

            self.assertEqual(code, 0, err)
            payload = json.loads(out)
            self.assertIn("actions", payload)
            self.assertTrue(payload["skipped"])
            self.assertEqual(os.listdir(project), [])


if __name__ == "__main__":
    unittest.main()
