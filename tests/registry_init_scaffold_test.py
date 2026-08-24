from __future__ import annotations

import shlex
import unittest

from agent_artifacts import cli
from agent_artifacts.domain.identifiers import ArtifactIdentity
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.protocol.capabilities import Capability
from agent_artifacts.protocol.native_schema import parse_collection_manifest
from agent_artifacts.protocol.native_tree import (
    SnapshotEntry,
    SnapshotEntryKind,
    SnapshotOrigin,
    SourceSnapshot,
    load_native_source,
)
from agent_artifacts.protocol.paths import parse_relative_path
from agent_artifacts.protocol.registry_schema import parse_registry_manifest
from agent_artifacts.protocol.semver import SemVer
from agent_artifacts.registry_commands.model import (
    ArtifactScaffoldOptions,
    CollectionAuthorOptions,
    RegistryInitOptions,
)
from agent_artifacts.registry_commands.planning import (
    plan_artifact_scaffold,
    plan_registry_collection,
    plan_registry_init,
    project_registry_workspace_plan,
    validate_registry_workspace,
)
from agent_artifacts.registry_commands.templates import REGISTRY_CI_WORKFLOW
from tests.registry_maintenance_fixtures import replace_snapshot_file


class RegistryInitScaffoldTest(unittest.TestCase):
    def test_collection_authoring_uses_only_artifacts_the_registry_holds(self) -> None:
        initialized = plan_registry_init(
            SourceSnapshot(SnapshotOrigin.LOCAL, ()),
            RegistryInitOptions(
                "company-registry",
                "Company Agent Artifacts",
                SemVer(1, 0, 0),
                SemVer(2, 0, 0),
            ),
        )
        assert isinstance(initialized, Ok)
        registry = project_registry_workspace_plan(
            SourceSnapshot(SnapshotOrigin.LOCAL, ()), initialized.value
        )
        assert isinstance(registry, Ok)
        scaffolded = plan_artifact_scaffold(
            registry.value,
            ArtifactScaffoldOptions(
                "skill",
                "review",
                SemVer(1, 0, 0),
                "Review changes.",
                ("claude",),
                ("darwin",),
                ("project",),
                ("copy",),
            ),
        )
        assert isinstance(scaffolded, Ok)
        with_artifact = project_registry_workspace_plan(registry.value, scaffolded.value)
        assert isinstance(with_artifact, Ok)

        authored = plan_registry_collection(
            with_artifact.value,
            CollectionAuthorOptions(
                "baseline",
                "Company baseline.",
                (ArtifactIdentity("skill", "review"),),
            ),
            executable_version=SemVer(1, 0, 0),
            available_capabilities=(
                Capability("artifact-manifest-v1"),
                Capability("lockfile-v1"),
                Capability("registry-entry-v1"),
            ),
        )

        self.assertIsInstance(authored, Ok)
        assert isinstance(authored, Ok)
        complete = project_registry_workspace_plan(with_artifact.value, authored.value)
        assert isinstance(complete, Ok)
        collection = next(
            item for item in complete.value.entries if str(item.path) == "collections/baseline.json"
        )
        parsed = parse_collection_manifest(collection.content)
        assert isinstance(parsed, Ok)
        self.assertEqual(
            tuple(selector.identity for selector in parsed.value.artifacts),
            (ArtifactIdentity("skill", "review"),),
        )

        missing = plan_registry_collection(
            with_artifact.value,
            CollectionAuthorOptions(
                "missing",
                "Invalid member.",
                (ArtifactIdentity("skill", "absent"),),
            ),
            executable_version=SemVer(1, 0, 0),
            available_capabilities=(
                Capability("artifact-manifest-v1"),
                Capability("lockfile-v1"),
                Capability("registry-entry-v1"),
            ),
        )
        self.assertIsInstance(missing, Err)

    def test_init_is_deterministic_and_includes_ci_ready_minimum_latest_template(self) -> None:
        empty = SourceSnapshot(SnapshotOrigin.LOCAL, ())
        options = RegistryInitOptions(
            "company-registry",
            "Company Agent Artifacts",
            SemVer(1, 0, 0),
            SemVer(2, 0, 0),
        )
        first = plan_registry_init(empty, options)
        second = plan_registry_init(empty, options)
        assert isinstance(first, Ok), first
        self.assertEqual(first, second)
        projected = project_registry_workspace_plan(empty, first.value)
        assert isinstance(projected, Ok), projected
        files = {str(item.path): item.content for item in projected.value.entries}
        self.assertIn("aart-registry.json", files)
        self.assertIn("aart-source.json", files)
        self.assertIn(".github/workflows/aart-registry.yml", files)
        self.assertIn(".github/ISSUE_TEMPLATE/usage-report.yml", files)
        self.assertIn(".gitignore", files)
        ignored = files[".gitignore"].decode("utf-8").splitlines()
        self.assertIn(".agent-artifacts/", ignored)
        self.assertIn(".agent-artifacts-bak/", ignored)
        self.assertIn(".claude/", ignored)
        self.assertIn(".tabnine/", ignored)
        self.assertIn(".opencode/", ignored)
        self.assertIn(".vibe/", ignored)
        self.assertIn(".mcp.json", ignored)
        self.assertIn(".github/workflows/aart-usage-validate.yml", files)
        self.assertIn(".github/workflows/aart-usage-dashboard.yml", files)
        workflow = files[".github/workflows/aart-registry.yml"]
        self.assertIn(b"registry test", workflow)
        self.assertIn(b"minimum", workflow)
        self.assertIn(b"latest", workflow)
        self.assertIn(b"validate --source . --strict --frozen", workflow)
        # Unconfigured, the tool is resolved from a source tree rather than installed: AART has
        # no runtime dependencies and ships __main__.py, so the gates run on a private runner
        # that can reach no package index at all.  `pip` appears once, inside the arm that only
        # runs when somebody sets AART_PACKAGE to point at one.
        self.assertEqual(workflow.count(b"pip install"), 1)
        self.assertIn(b'if [ -n "$PACKAGE" ]', workflow)
        self.assertIn(b"PYTHONPATH=", workflow)
        self.assertIn(b"-m agent_artifacts", workflow)
        self.assertIn(b"vars.AART_REPOSITORY", workflow)
        # One checkout now — the registry's own — and it still persists no credential.  The tool
        # is cloned without one, because AART carries no credential of its own.
        self.assertEqual(workflow.count(b"persist-credentials: false"), 1)
        self.assertNotIn(b"git push", workflow)
        issue_form = files[".github/ISSUE_TEMPLATE/usage-report.yml"]
        self.assertIn(b"id: report", issue_form)
        self.assertIn(b"voluntary", issue_form.lower())
        self.assertIn(b"never add credentials", issue_form)
        self.assertNotIn(b'labels: ["usage-report"]', issue_form)
        validator = files[".github/workflows/aart-usage-validate.yml"]
        self.assertIn(b"aart reporting validate-issue usage-issue.md", validator)
        self.assertIn(b"ISSUE_NUMBER: ${{ github.event.issue.number }}", validator)
        self.assertNotIn(b"${{ github.event.issue.body }}", validator)
        self.assertNotIn(b"eval ", validator)
        dashboard = files[".github/workflows/aart-usage-dashboard.yml"]
        self.assertIn(b"--json body,createdAt", dashboard)
        self.assertIn(b"aart reporting aggregate", dashboard)
        self.assertNotIn(b"author", dashboard)
        self.assertIn(b"actions/deploy-pages@v4", dashboard)
        manifest = parse_registry_manifest(files["aart-registry.json"])
        assert isinstance(manifest, Ok)
        self.assertEqual(
            tuple(str(item) for item in manifest.value.required_capabilities),
            ("artifact-manifest-v1", "lockfile-v1", "registry-entry-v1"),
        )
        validated = validate_registry_workspace(
            projected.value,
            executable_version=SemVer(1, 0, 0),
            available_capabilities=tuple(
                Capability(value)
                for value in (
                    "artifact-manifest-v1",
                    "lockfile-v1",
                    "registry-entry-v1",
                )
            ),
        )
        assert isinstance(validated, Ok)
        self.assertTrue(validated.value.passed)

        commands = [
            line.strip().removeprefix("- run: ")
            for line in workflow.decode().splitlines()
            if line.strip().startswith("- run: aart ")
        ]
        self.assertEqual(len(commands), 6)
        for command in commands:
            argv = shlex.split(
                command.removeprefix("aart ").replace("${{ matrix.compatibility }}", "minimum")
            )
            with self.subTest(command=command):
                self.assertEqual(cli.build_parser().parse_args(argv).command, "registry")

    def test_init_can_advertise_the_scaffolded_usage_reporting_service(self) -> None:
        empty = SourceSnapshot(SnapshotOrigin.LOCAL, ())
        options = RegistryInitOptions(
            "company-registry",
            "Company Agent Artifacts",
            SemVer(1, 0, 0),
            SemVer(2, 0, 0),
            "acme/agent-artifacts-registry",
        )

        planned = plan_registry_init(empty, options)
        assert isinstance(planned, Ok), planned
        projected = project_registry_workspace_plan(empty, planned.value)
        assert isinstance(projected, Ok), projected
        files = {str(item.path): item.content for item in projected.value.entries}
        manifest = parse_registry_manifest(files["aart-registry.json"])
        assert isinstance(manifest, Ok), manifest

        self.assertEqual(len(manifest.value.services), 1)
        self.assertEqual(manifest.value.services[0].name, "usage_reporting")
        self.assertEqual(manifest.value.services[0].kind, "github-issues")
        self.assertEqual(manifest.value.services[0].repository, "acme/agent-artifacts-registry")

    def test_scaffold_produces_a_valid_native_package_and_refuses_overwrite(self) -> None:
        empty = SourceSnapshot(SnapshotOrigin.LOCAL, ())
        initialized = plan_registry_init(
            empty,
            RegistryInitOptions(
                "company-registry",
                "Company Agent Artifacts",
                SemVer(1, 0, 0),
                SemVer(2, 0, 0),
            ),
        )
        assert isinstance(initialized, Ok)
        registry = project_registry_workspace_plan(empty, initialized.value)
        assert isinstance(registry, Ok)
        options = ArtifactScaffoldOptions(
            "skill",
            "review-python",
            SemVer(1, 0, 0),
            "Review Python changes against the company checklist.",
            ("claude", "tabnine"),
            ("darwin", "linux"),
            ("project", "user"),
            ("copy", "symlink"),
        )
        planned = plan_artifact_scaffold(registry.value, options)
        assert isinstance(planned, Ok), planned
        projected = project_registry_workspace_plan(registry.value, planned.value)
        assert isinstance(projected, Ok), projected
        loaded = load_native_source(
            projected.value,
            executable_version=SemVer(1, 0, 0),
            available_capabilities=(Capability("artifact-manifest-v1"),),
        )
        assert isinstance(loaded, Ok), loaded
        self.assertEqual(str(loaded.value.artifacts[0].manifest.identity), "skill/review-python")
        self.assertIsInstance(plan_artifact_scaffold(projected.value, options), Err)

    def test_scaffolded_hook_is_actionable_and_compiles_before_publication(self) -> None:
        initialized = plan_registry_init(
            SourceSnapshot(SnapshotOrigin.LOCAL, ()),
            RegistryInitOptions(
                "company-registry",
                "Company Agent Artifacts",
                SemVer(1, 0, 0),
                SemVer(2, 0, 0),
            ),
        )
        assert isinstance(initialized, Ok)
        registry = project_registry_workspace_plan(
            SourceSnapshot(SnapshotOrigin.LOCAL, ()), initialized.value
        )
        assert isinstance(registry, Ok)
        planned = plan_artifact_scaffold(
            registry.value,
            ArtifactScaffoldOptions(
                "hook",
                "review-guard",
                SemVer(1, 0, 0),
                "Run a reviewed guard before changes are accepted.",
                ("claude",),
                ("darwin",),
                ("project",),
                ("copy",),
            ),
        )
        assert isinstance(planned, Ok), planned
        projected = project_registry_workspace_plan(registry.value, planned.value)
        assert isinstance(projected, Ok), projected
        files = {str(item.path): item for item in projected.value.entries}
        descriptor = files["artifacts/hook/review-guard/payload/hook.json"]
        self.assertIn(b'"command":"${SCRIPT_DIR}/review-guard.sh"', descriptor.content)
        script = files["artifacts/hook/review-guard/payload/review-guard.sh"]
        self.assertTrue(script.executable)
        loaded = load_native_source(
            projected.value,
            executable_version=SemVer(1, 0, 0),
            available_capabilities=(Capability("artifact-manifest-v1"),),
        )
        self.assertIsInstance(loaded, Ok)

    def test_init_never_overwrites_an_existing_registry_workflow(self) -> None:
        path = parse_relative_path(".github/workflows/aart-registry.yml")
        assert isinstance(path, Ok)
        snapshot = SourceSnapshot(
            SnapshotOrigin.LOCAL,
            (SnapshotEntry(path.value, SnapshotEntryKind.FILE, b"user-owned workflow\n"),),
        )

        planned = plan_registry_init(
            snapshot,
            RegistryInitOptions(
                "company-registry",
                "Company Registry",
                SemVer(1, 0, 0),
                SemVer(2, 0, 0),
            ),
        )

        self.assertIsInstance(planned, Err)

    def test_init_never_overwrites_an_existing_reporting_template(self) -> None:
        path = parse_relative_path(".github/ISSUE_TEMPLATE/usage-report.yml")
        assert isinstance(path, Ok)
        snapshot = SourceSnapshot(
            SnapshotOrigin.LOCAL,
            (SnapshotEntry(path.value, SnapshotEntryKind.FILE, b"user-owned form\n"),),
        )

        planned = plan_registry_init(
            snapshot,
            RegistryInitOptions(
                "company-registry",
                "Company Registry",
                SemVer(1, 0, 0),
                SemVer(2, 0, 0),
            ),
        )

        self.assertIsInstance(planned, Err)

    def test_options_reject_control_characters_and_noncanonical_compatibility_names(self) -> None:
        with self.assertRaises(ValueError):
            RegistryInitOptions(
                "company-registry",
                "Company\tRegistry",
                SemVer(1, 0, 0),
                SemVer(2, 0, 0),
            )
        with self.assertRaises(ValueError):
            ArtifactScaffoldOptions(
                "skill",
                "demo",
                SemVer(1, 0, 0),
                "A valid summary.",
                ("not a slug",),
                ("darwin",),
                ("project",),
                ("copy",),
            )

    def test_registry_commands_reject_custom_roots_the_workspace_adapter_cannot_manage(
        self,
    ) -> None:
        empty = SourceSnapshot(SnapshotOrigin.LOCAL, ())
        initialized = plan_registry_init(
            empty,
            RegistryInitOptions(
                "company-registry",
                "Company Registry",
                SemVer(1, 0, 0),
                SemVer(2, 0, 0),
            ),
        )
        assert isinstance(initialized, Ok)
        registry = project_registry_workspace_plan(empty, initialized.value)
        assert isinstance(registry, Ok)
        marker = next(
            item.content for item in registry.value.entries if str(item.path) == "aart-source.json"
        ).replace(b'"artifact_roots":["artifacts"]', b'"artifact_roots":["packages"]')
        unsupported = replace_snapshot_file(registry.value, "aart-source.json", marker)

        planned = plan_artifact_scaffold(
            unsupported,
            ArtifactScaffoldOptions(
                "skill",
                "demo",
                SemVer(1, 0, 0),
                "A canonical demo skill.",
                ("codex",),
                ("darwin",),
                ("project",),
                ("copy",),
            ),
        )

        self.assertIsInstance(planned, Err)


if __name__ == "__main__":
    unittest.main()


class GeneratedRegistryReadmeTest(unittest.TestCase):
    """The one generated file a maintainer owns: written when absent, never taken back.

    Every other template is managed — `init` refuses a copy whose bytes differ. A README is the
    file people are meant to edit, and a repository created on GitHub with "Add a README" already
    has one, so managing it would turn both of those into a refusal.
    """

    def _init(self, *entries: SnapshotEntry) -> dict[str, bytes]:
        planned = plan_registry_init(
            SourceSnapshot(SnapshotOrigin.LOCAL, entries),
            RegistryInitOptions("company", "Company Registry", SemVer(2, 0, 0), SemVer(3, 0, 0)),
        )
        self.assertIsInstance(planned, Ok)
        return {str(change.path): change.content for change in planned.value.changes}

    @staticmethod
    def _existing_readme() -> SnapshotEntry:
        path = parse_relative_path("README.md")
        assert isinstance(path, Ok)
        return SnapshotEntry(path.value, SnapshotEntryKind.FILE, b"# mine\n")

    def test_a_registry_without_one_gets_a_readme_naming_itself(self):
        changes = self._init()
        self.assertIn("README.md", changes)
        readme = changes["README.md"].decode("utf-8")
        self.assertTrue(readme.startswith("# Company Registry\n"))
        self.assertIn("`company`", readme)

    def test_a_registry_that_already_has_one_keeps_it_untouched(self):
        self.assertNotIn("README.md", self._init(self._existing_readme()))

    def test_the_readme_teaches_the_fetch_order_the_workflow_actually_uses(self):
        """A registry is configured from settings, so the file has to say which settings."""

        readme = self._init()["README.md"].decode("utf-8")
        workflow = REGISTRY_CI_WORKFLOW.decode("utf-8")
        for name in ("AART_PACKAGE", "AART_WHEEL_URL", "AART_TOOL_PATH", "AART_TOOL_URL"):
            self.assertIn(name, readme, name)
            self.assertIn(name, workflow, name)
        self.assertLess(readme.index("AART_PACKAGE"), readme.index("AART_WHEEL_URL"))
        self.assertLess(readme.index("AART_WHEEL_URL"), readme.index("AART_TOOL_PATH"))
        self.assertLess(readme.index("AART_TOOL_PATH"), readme.index("AART_TOOL_URL"))

    def test_an_existing_readme_survives_a_real_init_on_disk(self):
        """The unit tests above build a snapshot by hand, so they cannot see this failure.

        `registry init` only leaves a README alone if the *workspace reader* reports it, and that
        reader has its own allowlist. With `README.md` missing from it an existing file is
        invisible, `init` plans a write, and a maintainer's README is replaced by a generated one.
        Only a run against a real directory reaches that code.
        """

        import subprocess
        import sys
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            subprocess.run(("git", "init", "-q", str(root)), check=True)
            (root / "README.md").write_text("# hands off\n", encoding="utf-8")
            finished = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "agent_artifacts",
                    "registry",
                    "init",
                    "--source",
                    str(root),
                    "--source-id",
                    "company",
                    "--display-name",
                    "Company Registry",
                    "--yes",
                ],
                capture_output=True,
                text=True,
                cwd=str(Path(__file__).resolve().parents[1]),
            )
            self.assertEqual(finished.returncode, 0, finished.stderr)
            self.assertEqual((root / "README.md").read_text(encoding="utf-8"), "# hands off\n")
            self.assertTrue((root / "aart-registry.json").is_file())

    def test_a_real_init_on_an_empty_directory_writes_the_readme(self):
        import subprocess
        import sys
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            subprocess.run(("git", "init", "-q", str(root)), check=True)
            finished = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "agent_artifacts",
                    "registry",
                    "init",
                    "--source",
                    str(root),
                    "--source-id",
                    "company",
                    "--display-name",
                    "Company Registry",
                    "--yes",
                ],
                capture_output=True,
                text=True,
                cwd=str(Path(__file__).resolve().parents[1]),
            )
            self.assertEqual(finished.returncode, 0, finished.stderr)
            written = (root / "README.md").read_text(encoding="utf-8")
            self.assertTrue(written.startswith("# Company Registry\n"))
            self.assertIn("AART_PACKAGE", written)
