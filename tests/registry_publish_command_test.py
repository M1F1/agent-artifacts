from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from agent_artifacts import cli


def _run(*arguments: str) -> tuple[int, str]:
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = cli.main(list(arguments))
    return code, output.getvalue()


def _git(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", "-C", str(root), *arguments), text=True, capture_output=True, check=False
    )


class RegistryPublishCommandTest(unittest.TestCase):
    @contextlib.contextmanager
    def _registry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "registry"
            root.mkdir()
            self.assertEqual(_git(root, "init", "-q").returncode, 0)
            self.assertEqual(_git(root, "config", "user.name", "AART Test").returncode, 0)
            self.assertEqual(
                _git(root, "config", "user.email", "aart@example.invalid").returncode, 0
            )
            code, output = _run(
                "registry",
                "init",
                "--source",
                str(root),
                "--source-id",
                "company-registry",
                "--display-name",
                "Company Registry",
                "--yes",
            )
            self.assertEqual(code, 0, output)
            yield root

    def test_preview_projects_lock_and_build_lists_every_commit_path_and_writes_nothing(
        self,
    ) -> None:
        with self._registry() as root:
            code, output = _run("registry", "publish", "--source", str(root), "--json")

            self.assertEqual(code, 0, output)
            result = json.loads(output)
            self.assertEqual(result["phase"], "review")
            paths = {item["path"] for item in result["commit"]["paths"]}
            self.assertIn("aart.lock.json", paths)
            self.assertIn("aart.index.json", paths)
            self.assertIn("aart-registry.json", paths)
            self.assertFalse((root / "aart.lock.json").exists())
            self.assertFalse((root / "aart.index.json").exists())
            self.assertNotEqual(_git(root, "rev-parse", "HEAD").returncode, 0)

    def test_finalize_runs_all_gates_commits_once_never_pushes_and_reruns_as_noop(self) -> None:
        with self._registry() as root:
            code, output = _run(
                "registry",
                "publish",
                "--source",
                str(root),
                "--message",
                "Publish company registry",
                "--yes",
                "--json",
            )

            self.assertEqual(code, 0, output)
            result = json.loads(output)
            self.assertEqual(result["commit"]["subject"], "Publish company registry")
            self.assertFalse(result["commit"]["push"])
            self.assertTrue(all(check["passed"] for check in result["review"]["checks"]))
            committed_paths = {item["path"] for item in result["commit"]["paths"]}
            self.assertIn("aart.lock.json", committed_paths)
            self.assertIn("aart.index.json", committed_paths)
            head = _git(root, "rev-parse", "HEAD").stdout.strip()
            self.assertTrue(head)
            self.assertEqual(_git(root, "status", "--porcelain").stdout, "")

            second_code, second_output = _run(
                "registry", "publish", "--source", str(root), "--yes", "--json"
            )
            self.assertEqual(second_code, 0, second_output)
            self.assertIsNone(json.loads(second_output)["commit"])
            self.assertEqual(_git(root, "rev-parse", "HEAD").stdout.strip(), head)

    def test_malformed_collection_stops_before_writes_and_leaves_head_unmoved(self) -> None:
        with self._registry() as root:
            code, output = _run("registry", "publish", "--source", str(root), "--yes", "--json")
            self.assertEqual(code, 0, output)
            head = _git(root, "rev-parse", "HEAD").stdout.strip()
            lock_before = (root / "aart.lock.json").read_bytes()
            index_before = (root / "aart.index.json").read_bytes()
            collection = root / "collections" / "broken.json"
            collection.parent.mkdir()
            collection.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "name": "broken",
                        "summary": "Broken collection.",
                        "artifacts": [{"type": "nonsense", "name": "x"}],
                    }
                )
            )

            failed, failure_output = _run("registry", "publish", "--source", str(root), "--yes")

            self.assertEqual(failed, 1)
            self.assertIn("selector identity is invalid", failure_output)
            self.assertEqual(_git(root, "rev-parse", "HEAD").stdout.strip(), head)
            self.assertEqual((root / "aart.lock.json").read_bytes(), lock_before)
            self.assertEqual((root / "aart.index.json").read_bytes(), index_before)


if __name__ == "__main__":
    unittest.main()
