"""The wheel carries where it was built from, so delivery stops mattering.

`_build_origin.py` is generated at build time the way `_commit.py` is: the committed source holds
empty strings, and a release job stamps its own `github.server_url`, `github.repository` and tag.
That is what lets `registry init` point a registry's CI at a company fork whether the wheel arrived
from a release URL, an internal index, `pipx`, `uv`, or a file on a laptop.

A wheel that lies about its origin is worse than one that says nothing, so the injector refuses
rather than guesses, and these tests are mostly about the refusals.
"""

from __future__ import annotations

import importlib.util
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

from agent_artifacts.io.tool_origin import origin_from_build

ROOT = pathlib.Path(__file__).resolve().parents[1]
COMPANY = "https://ghe.example.test/platform/agent-artifacts.git"


def _load(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_t_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class CommittedSourceTest(unittest.TestCase):
    def test_the_tracked_file_names_no_release(self) -> None:
        """A real value here would churn on every commit, exactly as `_commit.py` says."""

        text = (ROOT / "agent_artifacts" / "_build_origin.py").read_text(encoding="utf-8")
        for line in ('REPOSITORY_URL = ""', 'REF = ""', 'COMMIT = ""', 'VERSION = ""'):
            self.assertIn(line, text)

    def test_a_development_build_therefore_stamps_nothing(self) -> None:
        self.assertIsNone(origin_from_build())


class InjectorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.inject = _load("inject_build_origin")
        self.root = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))
        subprocess.run(("git", "init", "-q", str(self.root)), check=True)
        for name in ("scripts", "agent_artifacts"):
            shutil.copytree(ROOT / name, self.root / name)
        shutil.copy(ROOT / "pyproject.toml", self.root / "pyproject.toml")
        subprocess.run(("git", "-C", str(self.root), "add", "-A"), check=True)
        subprocess.run(
            (
                "git",
                "-C",
                str(self.root),
                "-c",
                "user.email=t@t",
                "-c",
                "user.name=t",
                "commit",
                "-q",
                "-m",
                "t",
            ),
            check=True,
        )
        self.version = self.inject._source_version(self.root)
        subprocess.run(("git", "-C", str(self.root), "tag", f"v{self.version}"), check=True)

    def _resolve(self, **env: str):
        return self.inject.resolve(env, root=self.root)

    def test_a_matching_tag_resolves_to_all_four_values(self) -> None:
        url, ref, commit, version = self._resolve(
            AART_BUILD_REPOSITORY_URL=COMPANY, AART_BUILD_REF=f"v{self.version}"
        )
        self.assertEqual(url, COMPANY)
        self.assertEqual(ref, f"v{self.version}")
        self.assertEqual(version, self.version)
        self.assertEqual(len(commit), 40)

    def test_a_tag_that_is_not_the_source_version_is_refused(self) -> None:
        """The same rule `version.py check-tag` enforces, applied to what gets baked in."""

        with self.assertRaises(self.inject.OriginError):
            self._resolve(AART_BUILD_REPOSITORY_URL=COMPANY, AART_BUILD_REF="v99.0.0")

    def test_a_ref_pointing_at_another_commit_is_refused(self) -> None:
        (self.root / "extra.txt").write_text("moved on\n", encoding="utf-8")
        subprocess.run(("git", "-C", str(self.root), "add", "-A"), check=True)
        subprocess.run(
            (
                "git",
                "-C",
                str(self.root),
                "-c",
                "user.email=t@t",
                "-c",
                "user.name=t",
                "commit",
                "-q",
                "-m",
                "later",
            ),
            check=True,
        )
        with self.assertRaises(self.inject.OriginError):
            self._resolve(AART_BUILD_REPOSITORY_URL=COMPANY, AART_BUILD_REF=f"v{self.version}")

    def test_a_url_with_no_host_is_refused(self) -> None:
        """`/srv/mirrors/aart` is not somewhere a runner can fetch from."""

        for url in ("/srv/mirrors/agent-artifacts", "../aart", "file:///home/me/aart"):
            with self.subTest(url=url), self.assertRaises(self.inject.OriginError):
                self._resolve(AART_BUILD_REPOSITORY_URL=url, AART_BUILD_REF=f"v{self.version}")

    def test_half_an_origin_is_refused(self) -> None:
        with self.assertRaises(self.inject.OriginError):
            self._resolve(AART_BUILD_REPOSITORY_URL=COMPANY)
        with self.assertRaises(self.inject.OriginError):
            self._resolve(AART_BUILD_REF=f"v{self.version}")

    def test_no_origin_at_all_is_a_development_build_rather_than_a_failure(self) -> None:
        self.assertEqual(self._resolve(), ("", "", "", ""))

    def test_what_it_renders_is_importable_and_says_what_was_asked(self) -> None:
        rendered = self.inject.render(COMPANY, "v2.8.5", "a" * 40, "2.8.5")
        namespace: dict[str, object] = {}
        exec(compile(rendered, "_build_origin.py", "exec"), namespace)
        self.assertEqual(namespace["REPOSITORY_URL"], COMPANY)
        self.assertEqual(namespace["REF"], "v2.8.5")
        self.assertEqual(namespace["VERSION"], "2.8.5")


class ReleaseWorkflowTest(unittest.TestCase):
    def test_the_release_job_stamps_from_its_own_context(self) -> None:
        """A fork must stamp its own instance and repository with no edit to the workflow."""

        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn(
            "AART_BUILD_REPOSITORY_URL: ${{ github.server_url }}/${{ github.repository }}.git",
            workflow,
        )
        self.assertIn(
            "AART_BUILD_REF: ${{ github.event.release.tag_name || github.ref_name }}", workflow
        )
        self.assertIn("scripts/inject_build_origin.py", workflow)
        # It must run before the wheel is built, or the wheel carries the tracked empty values.
        self.assertLess(
            workflow.index("inject_build_origin.py"), workflow.index("scripts/build_wheel.py")
        )


if __name__ == "__main__":
    unittest.main()
