from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from tests.packaging_test import _load_script

ROOT = Path(__file__).resolve().parents[1]
APPROVED_ORIGIN = "https://github.com/M1F1/agent-artifacts.git"


def _tree(root: Path) -> tuple[tuple[str, bytes], ...]:
    return tuple(
        (path.relative_to(root).as_posix(), path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file() and ".git" not in path.relative_to(root).parts
    )


def _committed_source(root: Path) -> tuple[Path, str]:
    """Expose checkout HEAD under a ref, including shallow detached CI commits."""

    source = root / "committed-source"
    source.mkdir()
    subprocess.run(("git", "-C", str(source), "init", "-q"), check=True)
    subprocess.run(
        (
            "git",
            "-C",
            str(source),
            "fetch",
            "-q",
            "--update-shallow",
            str(ROOT),
            "HEAD:refs/heads/export",
        ),
        check=True,
    )
    commit = subprocess.run(
        ("git", "-C", str(source), "rev-parse", "refs/heads/export"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ("git", "-C", str(source), "remote", "add", "origin", APPROVED_ORIGIN), check=True
    )
    return source, commit


class ReferenceRegistryExportE2ETest(unittest.TestCase):
    def test_export_rejects_a_checkout_that_claims_an_unapproved_origin(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source, commit = _committed_source(Path(temporary))
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
        with tempfile.TemporaryDirectory() as temporary:
            source, commit = _committed_source(Path(temporary))
            first = Path(temporary) / "first"
            second = Path(temporary) / "second"
            for destination in (first, second):
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
            build_root.mkdir()
            wheel_root = Path(temporary) / "wheel"
            wheel_root.mkdir()
            packaging = _load_script("packaging_check")
            packaging._copy_project(ROOT, build_root)
            packaging._build_wheel(build_root, wheel_root)
            wheel = next(wheel_root.glob("agent_artifacts-*-py3-none-any.whl"))
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
