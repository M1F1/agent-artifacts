from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from tests.packaging_test import _load_script

ROOT = Path(__file__).resolve().parents[1]


def _tree(root: Path) -> tuple[tuple[str, bytes], ...]:
    return tuple(
        (path.relative_to(root).as_posix(), path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file() and ".git" not in path.relative_to(root).parts
    )


class ReferenceRegistryExportE2ETest(unittest.TestCase):
    def test_export_rejects_a_checkout_that_claims_an_unapproved_origin(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            subprocess.run(("git", "clone", "-q", "--no-local", str(ROOT), str(source)), check=True)
            subprocess.run(
                (
                    "git",
                    "-C",
                    str(source),
                    "remote",
                    "set-url",
                    "origin",
                    "https://github.com/example/spoof.git",
                ),
                check=True,
            )
            commit = subprocess.run(
                ("git", "-C", str(source), "rev-parse", "HEAD"),
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            destination = Path(temporary) / "destination"
            result = subprocess.run(
                (
                    sys.executable,
                    str(ROOT / "scripts/prepare_reference_registry.py"),
                    "--source-checkout",
                    str(source),
                    "--source-commit",
                    commit,
                    "--destination",
                    str(destination),
                ),
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("approved public AART repository", result.stderr)
            self.assertFalse(destination.exists())

    def test_exact_committed_source_exports_deterministically_and_works_outside_checkout(
        self,
    ) -> None:
        commit = subprocess.run(
            ("git", "rev-parse", "HEAD"),
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "first"
            second = Path(temporary) / "second"
            for destination in (first, second):
                result = subprocess.run(
                    (
                        sys.executable,
                        str(ROOT / "scripts/prepare_reference_registry.py"),
                        "--source-checkout",
                        str(ROOT),
                        "--source-commit",
                        commit,
                        "--destination",
                        str(destination),
                        "--json",
                    ),
                    cwd=temporary,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                receipt = json.loads(result.stdout)
                self.assertEqual(receipt["source_commit"], commit)
                self.assertEqual(receipt["artifact_count"], 10)
                self.assertEqual(receipt["collection_count"], 2)
            self.assertEqual(_tree(first), _tree(second))

            build_root = Path(temporary) / "wheel-source"
            shutil.copytree(
                ROOT / "agent_artifacts",
                build_root / "agent_artifacts",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            shutil.copy2(ROOT / "pyproject.toml", build_root / "pyproject.toml")
            shutil.copy2(ROOT / "README.md", build_root / "README.md")
            build = _load_script("build_wheel")
            build.ROOT = build_root
            self.assertEqual(build.main(), 0)
            wheel = next((build_root / "dist").glob("agent_artifacts-*-py3-none-any.whl"))
            with zipfile.ZipFile(wheel) as archive:
                names = archive.namelist()
            for operational_root in (
                "artifacts/",
                "bundles/",
                "guidelines/",
                "hooks/",
                "mcp/",
                "memory/",
                "skills/",
            ):
                self.assertFalse(any(name.startswith(operational_root) for name in names))

            outside = Path(temporary) / "outside"
            outside.mkdir()
            site = Path(temporary) / "site"
            installed = subprocess.run(
                (
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--no-index",
                    "--no-deps",
                    "--target",
                    str(site),
                    str(wheel),
                ),
                cwd=outside,
                capture_output=True,
                text=True,
            )
            self.assertEqual(installed.returncode, 0, installed.stderr + installed.stdout)
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(site)
            for arguments in (
                ("registry", "validate", "--source", str(first), "--strict", "--frozen"),
                ("registry", "test", "--source", str(first)),
                ("list", "--source", str(first), "--json"),
            ):
                result = subprocess.run(
                    (sys.executable, "-m", "agent_artifacts", *arguments),
                    cwd=outside,
                    env=environment,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)


if __name__ == "__main__":
    unittest.main()
