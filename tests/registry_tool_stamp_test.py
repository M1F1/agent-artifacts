"""`registry init` records where the AART that ran it came from.

The three workflows `registry init` writes have to name a repository to fetch AART from, and the
literal they ship is this project's own.  A fork on a company GitHub Enterprise Server needs a
different one, and the obvious place to put it -- the template inside the fork -- is the wrong
place: that line then conflicts on every later sync from upstream.  So the tool answers the
question about itself and stamps the answer into the file it generates.

What is stamped is a *default*.  `AART_TOOL_PATH`, `AART_REPOSITORY`, `AART_TOOL_URL` and
`AART_REF` still override it, which is the difference between a stamp and a decision that cannot
be revisited.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import tempfile
import unittest

from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.io.tool_origin import discover_tool_origin, origin_from_direct_url
from agent_artifacts.protocol.native_tree import (
    SnapshotEntry,
    SnapshotEntryKind,
    SnapshotOrigin,
    SourceSnapshot,
)
from agent_artifacts.protocol.paths import parse_relative_path
from agent_artifacts.protocol.semver import SemVer
from agent_artifacts.registry_commands.model import RegistryInitOptions, ToolOrigin
from agent_artifacts.registry_commands.planning import (
    plan_registry_init,
    project_registry_workspace_plan,
)
from agent_artifacts.registry_commands.templates import (
    REGISTRY_CI_WORKFLOW,
    USAGE_REPORT_DASHBOARD_WORKFLOW,
    USAGE_REPORT_VALIDATE_WORKFLOW,
    stamp_tool_origin,
)

WORKFLOWS = (
    REGISTRY_CI_WORKFLOW,
    USAGE_REPORT_VALIDATE_WORKFLOW,
    USAGE_REPORT_DASHBOARD_WORKFLOW,
)


class ToolOriginTest(unittest.TestCase):
    def test_a_stamp_must_say_something(self) -> None:
        with self.assertRaises(ValueError):
            ToolOrigin()

    def test_a_value_that_could_leave_its_quotes_is_refused(self) -> None:
        """The stamp is pasted between single quotes in generated YAML that CI then runs."""

        for ref in ("v1' }}\ninjected: true", "main'", "${{ secrets.TOKEN }}", "a\\b"):
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                ToolOrigin(ref=ref)

    def test_a_repository_must_look_like_one(self) -> None:
        with self.assertRaises(ValueError):
            ToolOrigin(repository="not-a-repository")


class StampTest(unittest.TestCase):
    def test_no_origin_leaves_every_byte_alone(self) -> None:
        for workflow in WORKFLOWS:
            self.assertEqual(stamp_tool_origin(workflow, None), workflow)

    def test_the_repository_and_the_ref_defaults_both_move(self) -> None:
        origin = ToolOrigin(repository="platform/agent-artifacts", ref="v2.8.5")
        for workflow in WORKFLOWS:
            stamped = stamp_tool_origin(workflow, origin).decode("utf-8")
            self.assertIn("vars.AART_REPOSITORY || 'platform/agent-artifacts'", stamped)
            self.assertIn("vars.AART_REF || 'v2.8.5'", stamped)
            self.assertNotIn("M1F1/agent-artifacts", stamped)

    def test_a_stamp_never_removes_the_variable_that_overrides_it(self) -> None:
        """A stamped registry must still be retargetable from the settings page."""

        origin = ToolOrigin(repository="platform/agent-artifacts", ref="v2.8.5")
        for workflow in WORKFLOWS:
            stamped = stamp_tool_origin(workflow, origin).decode("utf-8")
            for variable in (
                "vars.AART_TOOL_PATH",
                "vars.AART_TOOL_URL",
                "vars.AART_REPOSITORY",
                "vars.AART_REF",
            ):
                self.assertIn(variable, stamped)

    def test_a_cross_host_url_replaces_the_derivation_rather_than_the_owner(self) -> None:
        """`github.server_url` is right only while the tool and the registry share an instance."""

        origin = ToolOrigin(url="https://ghe.example.test/platform/aart.git", ref="main")
        stamped = stamp_tool_origin(REGISTRY_CI_WORKFLOW, origin).decode("utf-8")
        self.assertIn(
            "TOOL_URL: ${{ vars.AART_TOOL_URL || 'https://ghe.example.test/platform/aart.git' }}",
            stamped,
        )
        self.assertNotIn("github.server_url", stamped)

    def test_a_body_with_nothing_to_stamp_is_refused_rather_than_returned(self) -> None:
        """A silent no-op would ship a workflow pointing at the wrong fork, found weeks later."""

        with self.assertRaises(ValueError):
            stamp_tool_origin(b"name: unrelated\n", ToolOrigin(ref="main"))


class DiscoveryTest(unittest.TestCase):
    def _repository(self, origin: str) -> str | None:
        root = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
        subprocess.run(("git", "init", "-q", str(root)), check=True)
        subprocess.run(("git", "-C", str(root), "remote", "add", "origin", origin), check=True)
        discovered = discover_tool_origin(str(root))
        return None if discovered is None else discovered.repository

    def test_https_and_ssh_origins_both_resolve_to_owner_and_name(self) -> None:
        self.assertEqual(
            self._repository("https://ghe.example.test/platform/agent-artifacts.git"),
            "platform/agent-artifacts",
        )
        self.assertEqual(
            self._repository("git@ghe.example.test:platform/agent-artifacts.git"),
            "platform/agent-artifacts",
        )

    def test_an_origin_with_no_host_is_not_a_place_ci_can_fetch_from(self) -> None:
        """A clone of a clone on someone's laptop would stamp a path no runner can reach."""

        self.assertIsNone(self._repository("/srv/mirrors/agent-artifacts"))
        self.assertIsNone(self._repository("../agent-artifacts"))

    def test_a_tool_that_merely_sits_inside_a_checkout_is_not_that_checkout(self) -> None:
        """AART unpacked under a home directory that is itself a repository is not that repository.

        Without this the stamp answers with someone's dotfiles, and every registry created there
        sends its CI to clone a tree that has no `agent_artifacts` package in it.
        """

        root = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
        subprocess.run(("git", "init", "-q", str(root)), check=True)
        subprocess.run(
            (
                "git",
                "-C",
                str(root),
                "remote",
                "add",
                "origin",
                "https://host.test/me/dotfiles.git",
            ),
            check=True,
        )
        nested = root / ".local" / "lib"
        nested.mkdir(parents=True)
        self.assertIsNone(discover_tool_origin(str(nested)))

    def test_a_tree_that_is_not_a_checkout_answers_nothing(self) -> None:
        """AART installed from a wheel has no origin to read, and must say so rather than guess."""

        root = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
        self.assertIsNone(discover_tool_origin(root))
        self.assertIsNone(discover_tool_origin(os.path.join(root, "absent")))


class InstalledDistributionTest(unittest.TestCase):
    """`pipx install git+https://.../agent-artifacts.git@main` has to stamp too.

    An ordinary install has no checkout to read, but PEP 610 requires the installer to record
    where it fetched from.  `pip`, `pipx` and `uv` all write the same `direct_url.json`, walked on
    2026-08-21 against real `uv tool install` and `pipx install` runs.
    """

    def test_a_git_install_stamps_what_was_asked_for(self) -> None:
        origin = origin_from_direct_url(
            '{"url": "https://ghe.example.test/platform/agent-artifacts.git",'
            ' "vcs_info": {"vcs": "git", "requested_revision": "main", "commit_id": "abc123"}}'
        )
        self.assertEqual(origin, ToolOrigin(repository="platform/agent-artifacts", ref="main"))

    def test_without_a_requested_revision_the_commit_is_the_honest_answer(self) -> None:
        """`pip install git+https://host/o/n.git` records no revision, only what it resolved to."""

        origin = origin_from_direct_url(
            '{"url": "git+ssh://git@ghe.example.test:2222/platform/aart.git",'
            ' "vcs_info": {"vcs": "git", "commit_id": "deadbeef"}}'
        )
        self.assertEqual(origin, ToolOrigin(repository="platform/aart", ref="deadbeef"))

    def test_a_wheel_from_an_index_is_not_stamped(self) -> None:
        """An index states a version, not a place to clone; inventing one is `LAF-122`."""

        self.assertIsNone(
            origin_from_direct_url(
                '{"url": "https://nexus.test/agent_artifacts-2.8.5-py3-none-any.whl",'
                ' "archive_info": {"hash": "sha256=abc"}}'
            )
        )

    def test_an_install_from_a_local_directory_names_no_host(self) -> None:
        self.assertIsNone(
            origin_from_direct_url(
                '{"url": "file:///Users/someone/code/agent-artifacts",'
                ' "vcs_info": {"vcs": "git", "requested_revision": "main"}}'
            )
        )

    def test_a_record_that_is_absent_or_unreadable_answers_nothing(self) -> None:
        for text in (None, "", "not json", "[]", '{"url": 7, "vcs_info": {"vcs": "git"}}'):
            with self.subTest(text=text):
                self.assertIsNone(origin_from_direct_url(text))


class PlannedWorkspaceTest(unittest.TestCase):
    def _files(self, origin: ToolOrigin | None) -> dict[str, bytes]:
        empty = SourceSnapshot(SnapshotOrigin.LOCAL, ())
        planned = plan_registry_init(
            empty,
            RegistryInitOptions(
                "company-registry",
                "Company Registry",
                SemVer(2, 0, 0),
                SemVer(3, 0, 0),
                tool_origin=origin,
            ),
        )
        assert isinstance(planned, Ok), planned
        projected = project_registry_workspace_plan(empty, planned.value)
        assert isinstance(projected, Ok), projected
        return {str(entry.path): entry.content for entry in projected.value.entries}

    def test_every_emitted_workflow_carries_the_stamp(self) -> None:
        files = self._files(ToolOrigin(repository="platform/agent-artifacts", ref="v2.8.5"))
        for name in (
            ".github/workflows/aart-registry.yml",
            ".github/workflows/aart-usage-validate.yml",
            ".github/workflows/aart-usage-dashboard.yml",
        ):
            self.assertIn(b"vars.AART_REPOSITORY || 'platform/agent-artifacts'", files[name], name)
            self.assertIn(b"vars.AART_REF || 'v2.8.5'", files[name], name)

    def test_files_that_never_fetch_the_tool_are_left_alone(self) -> None:
        stamped = self._files(ToolOrigin(repository="platform/agent-artifacts", ref="v2.8.5"))
        plain = self._files(None)
        for name in (".gitignore", ".github/ISSUE_TEMPLATE/usage-report.yml"):
            self.assertEqual(stamped[name], plain[name], name)

    def test_without_a_stamp_the_shipped_defaults_survive(self) -> None:
        files = self._files(None)
        workflow = files[".github/workflows/aart-registry.yml"]
        self.assertEqual(workflow, REGISTRY_CI_WORKFLOW)

    def test_the_refusal_to_overwrite_compares_against_the_stamped_bytes(self) -> None:
        """A stamped registry re-run on its own files must recognize them as its own."""

        origin = ToolOrigin(repository="platform/agent-artifacts", ref="v2.8.5")
        path = parse_relative_path(".github/workflows/aart-registry.yml")
        assert isinstance(path, Ok)
        snapshot = SourceSnapshot(
            SnapshotOrigin.LOCAL,
            (
                SnapshotEntry(
                    path.value,
                    SnapshotEntryKind.FILE,
                    stamp_tool_origin(REGISTRY_CI_WORKFLOW, origin),
                ),
            ),
        )
        options = RegistryInitOptions(
            "company-registry",
            "Company Registry",
            SemVer(2, 0, 0),
            SemVer(3, 0, 0),
            tool_origin=origin,
        )
        self.assertIsInstance(plan_registry_init(snapshot, options), Ok)
        # The same file is foreign to an init carrying a different stamp, which is the existing
        # refusal doing its job rather than a new rule.
        other = RegistryInitOptions(
            "company-registry",
            "Company Registry",
            SemVer(2, 0, 0),
            SemVer(3, 0, 0),
            tool_origin=ToolOrigin(repository="other/agent-artifacts", ref="v2.8.5"),
        )
        self.assertIsInstance(plan_registry_init(snapshot, other), Err)


if __name__ == "__main__":
    unittest.main()
