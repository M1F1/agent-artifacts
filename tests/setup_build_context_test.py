"""SBC-1: a recipe can name the package it ships in, and AART hands it a copy.

The setup model has two address spaces — the consumer's home and their project — and every path a
recipe may write resolves into one of them.  Nothing could name a *source*, so a step could not read
the payload shipped beside it; the one escape hatch, `custom_entrypoint`, runs from a temporary copy
whose environment carries no path to the package either.

These tests cover the primitive that closes it: one validated package-relative name, resolved at
plan time, and a working copy of the named subtree inside the run directory.  The store itself stays
readable-only — proven here by digesting the source before and after a run that materialized the
context, wrote into it, and removed it.
"""

from __future__ import annotations

import os
import shutil
import stat
import unittest

from agent_artifacts.model import SetupInstaller, SetupPlan, SetupQueueItem
from agent_artifacts.setup import _Invalid, _package_relative_source, resolve_package_source
from agent_artifacts.setup_runtime import (
    CONTEXT_DIRECTORY,
    context_digest,
    materialize_build_context,
    new_run_directory,
)


def _installer(descriptor_path: str = "mcp/atlassian/setup/installer.json") -> SetupInstaller:
    return SetupInstaller(
        schema_version=2,
        protocol_version=2,
        artifact="mcp/atlassian",
        purpose="Build a local image from the package payload",
        platforms=("darwin",),
        help_urls=(),
        required_tools=("docker",),
        capabilities=("docker",),
        inputs=(),
        steps=(),
        descriptor_path=descriptor_path,
        descriptor_hash="a" * 64,
        manual_path="mcp/atlassian/SETUP.md",
    )


def _item(source_root: str, descriptor_path: str = "mcp/atlassian/setup/installer.json"):
    return SetupQueueItem(
        artifact_type="mcp",
        artifact_name="atlassian",
        profile="default",
        scope="user",
        source_label="registry",
        source_root=source_root,
        installer=_installer(descriptor_path),
    )


def _plan(item: SetupQueueItem, run_root: str) -> SetupPlan:
    return SetupPlan(
        item=item,
        effects=(),
        plan_hash="b" * 64,
        target_root=run_root,
        home_root=run_root,
        run_root=run_root,
    )


class PackageRelativeNameTest(unittest.TestCase):
    """A name pointing at the package is validated apart from a name pointing at a destination."""

    def test_a_plain_name_is_accepted(self) -> None:
        self.assertEqual(_package_relative_source("payload", "step build.context"), "payload")

    def test_traversal_is_refused_and_the_field_is_named(self) -> None:
        for candidate in ("..", "../payload", "payload/..", "./payload"):
            with self.subTest(candidate=candidate):
                with self.assertRaises(_Invalid) as raised:
                    _package_relative_source(candidate, "step build.context")
                self.assertIn("step build.context", str(raised.exception))

    def test_an_absolute_path_is_refused(self) -> None:
        with self.assertRaises(_Invalid) as raised:
            _package_relative_source("/etc", "step build.context")
        self.assertIn("step build.context", str(raised.exception))

    def test_a_nested_path_is_refused(self) -> None:
        """One name directly below the package root, as `custom_entrypoint` already requires."""

        with self.assertRaises(_Invalid) as raised:
            _package_relative_source("payload/docker", "step build.context")
        self.assertIn("directly below the package root", str(raised.exception))

    def test_a_non_string_is_refused(self) -> None:
        with self.assertRaises(_Invalid):
            _package_relative_source(["payload"], "step build.context")


class ResolvePackageSourceTest(unittest.TestCase):
    def test_a_name_resolves_against_the_package_not_the_registry(self) -> None:
        item = _item("/registry")
        self.assertEqual(
            resolve_package_source(item, "payload"),
            os.path.join("/registry", "mcp", "atlassian", "payload"),
        )

    def test_a_root_level_recipe_resolves_against_the_source_root(self) -> None:
        item = _item("/package", descriptor_path=os.path.join("setup", "installer.json"))
        self.assertEqual(
            resolve_package_source(item, "payload"), os.path.join("/package", "payload")
        )

    def test_a_name_that_escapes_the_package_is_refused(self) -> None:
        """Redundant against the validator, and kept: it is where containment is actually decided."""

        item = _item("/registry")
        with self.assertRaises(_Invalid):
            resolve_package_source(item, os.path.join("..", "other"))


class MaterializeBuildContextTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = os.path.realpath(
            os.environ.get("TMPDIR", "/tmp")
        )  # resolved so comparisons hold on macOS
        self.workspace = os.path.join(self.root, f"aart-sbc1-{os.getpid()}-{id(self)}")
        self.package = os.path.join(self.workspace, "mcp", "atlassian")
        self.payload = os.path.join(self.package, "payload")
        os.makedirs(os.path.join(self.payload, "lib"))
        with open(os.path.join(self.payload, "server.py"), "w", encoding="utf-8") as stream:
            stream.write("print('serve')\n")
        with open(os.path.join(self.payload, "requirements.txt"), "w", encoding="utf-8") as stream:
            stream.write("requests==2.32.3\n")
        with open(os.path.join(self.payload, "entry.sh"), "w", encoding="utf-8") as stream:
            stream.write("#!/bin/sh\nexec python server.py\n")
        os.chmod(os.path.join(self.payload, "entry.sh"), 0o755)
        with open(os.path.join(self.payload, "lib", "client.py"), "w", encoding="utf-8") as stream:
            stream.write("client = 1\n")
        self.run_root = os.path.join(self.workspace, "home")
        os.makedirs(self.run_root)
        self.addCleanup(shutil.rmtree, self.workspace, ignore_errors=True)

    def _relative_files(self, root: str) -> set[str]:
        found = set()
        for directory, _subdirectories, names in os.walk(root):
            for name in names:
                found.add(os.path.relpath(os.path.join(directory, name), root))
        return found

    def test_the_copy_holds_exactly_the_declared_subtree(self) -> None:
        run_dir = new_run_directory(_plan(_item(self.workspace), self.run_root))
        context = materialize_build_context(self.payload, run_dir)
        self.assertEqual(context, os.path.join(run_dir, CONTEXT_DIRECTORY))
        self.assertEqual(self._relative_files(context), self._relative_files(self.payload))
        with open(os.path.join(context, "server.py"), encoding="utf-8") as stream:
            self.assertEqual(stream.read(), "print('serve')\n")

    def test_the_copy_is_private_and_keeps_the_executable_bit(self) -> None:
        run_dir = new_run_directory(_plan(_item(self.workspace), self.run_root))
        context = materialize_build_context(self.payload, run_dir)
        self.assertEqual(stat.S_IMODE(os.stat(run_dir).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(context).st_mode), 0o700)
        self.assertTrue(os.stat(os.path.join(context, "entry.sh")).st_mode & 0o111)
        self.assertFalse(os.stat(os.path.join(context, "server.py")).st_mode & 0o111)

    def test_the_copy_lives_under_the_run_root_and_nowhere_else(self) -> None:
        run_dir = new_run_directory(_plan(_item(self.workspace), self.run_root))
        context = materialize_build_context(self.payload, run_dir)
        expected = os.path.join(self.run_root, ".agent-artifacts", "setup-runs")
        self.assertEqual(os.path.commonpath((expected, context)), expected)

    def test_a_symlink_in_the_subtree_is_refused_and_leaves_nothing_behind(self) -> None:
        os.symlink("/etc/passwd", os.path.join(self.payload, "leak"))
        run_dir = new_run_directory(_plan(_item(self.workspace), self.run_root))
        with self.assertRaises(RuntimeError) as raised:
            materialize_build_context(self.payload, run_dir)
        self.assertIn("symlink", str(raised.exception))
        self.assertFalse(os.path.exists(os.path.join(run_dir, CONTEXT_DIRECTORY)))

    def test_a_symlinked_source_is_refused(self) -> None:
        linked = os.path.join(self.package, "linked-payload")
        os.symlink(self.payload, linked)
        run_dir = new_run_directory(_plan(_item(self.workspace), self.run_root))
        with self.assertRaises(RuntimeError):
            materialize_build_context(linked, run_dir)

    def test_a_missing_source_is_refused_by_name(self) -> None:
        run_dir = new_run_directory(_plan(_item(self.workspace), self.run_root))
        with self.assertRaises(RuntimeError) as raised:
            materialize_build_context(os.path.join(self.package, "absent"), run_dir)
        self.assertIn("absent", str(raised.exception))

    def test_a_second_materialization_in_one_run_is_refused(self) -> None:
        run_dir = new_run_directory(_plan(_item(self.workspace), self.run_root))
        materialize_build_context(self.payload, run_dir)
        with self.assertRaises(RuntimeError):
            materialize_build_context(self.payload, run_dir)

    def test_a_non_regular_entry_is_refused(self) -> None:
        os.mkfifo(os.path.join(self.payload, "pipe"))
        run_dir = new_run_directory(_plan(_item(self.workspace), self.run_root))
        with self.assertRaises(RuntimeError) as raised:
            materialize_build_context(self.payload, run_dir)
        self.assertIn("regular files and directories", str(raised.exception))


class TheSourceIsNeverWrittenToTest(unittest.TestCase):
    """The claim the whole design rests on, stated as a digest that must not move."""

    def setUp(self) -> None:
        self.workspace = os.path.join(
            os.path.realpath(os.environ.get("TMPDIR", "/tmp")),
            f"aart-sbc1-store-{os.getpid()}-{id(self)}",
        )
        self.payload = os.path.join(self.workspace, "mcp", "atlassian", "payload")
        os.makedirs(self.payload)
        with open(os.path.join(self.payload, "server.py"), "w", encoding="utf-8") as stream:
            stream.write("print('serve')\n")
        with open(os.path.join(self.payload, "Dockerfile"), "w", encoding="utf-8") as stream:
            stream.write("FROM python:3.11-slim\nCOPY . /app\n")
        self.run_root = os.path.join(self.workspace, "home")
        os.makedirs(self.run_root)
        self.addCleanup(shutil.rmtree, self.workspace, ignore_errors=True)

    def test_a_run_that_wrote_into_its_context_left_the_package_untouched(self) -> None:
        before = context_digest(self.payload)
        run_dir = new_run_directory(_plan(_item(self.workspace), self.run_root))
        context = materialize_build_context(self.payload, run_dir)
        with open(os.path.join(context, "company-ca.pem"), "w", encoding="utf-8") as stream:
            stream.write("-----BEGIN CERTIFICATE-----\n")
        self.assertNotEqual(context_digest(context), before)
        shutil.rmtree(run_dir)
        self.assertFalse(os.path.exists(run_dir))
        self.assertEqual(context_digest(self.payload), before)

    def test_a_faithful_copy_digests_the_same_as_its_source(self) -> None:
        run_dir = new_run_directory(_plan(_item(self.workspace), self.run_root))
        context = materialize_build_context(self.payload, run_dir)
        self.assertEqual(context_digest(context), context_digest(self.payload))

    def test_the_digest_notices_a_changed_mode_not_only_changed_bytes(self) -> None:
        before = context_digest(self.payload)
        os.chmod(os.path.join(self.payload, "server.py"), 0o755)
        self.assertNotEqual(context_digest(self.payload), before)


if __name__ == "__main__":
    unittest.main()
