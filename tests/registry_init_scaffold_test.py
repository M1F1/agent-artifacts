from __future__ import annotations

import shlex
import unittest

from agent_artifacts import cli
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.protocol.capabilities import Capability
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
from agent_artifacts.registry_commands.model import ArtifactScaffoldOptions, RegistryInitOptions
from agent_artifacts.registry_commands.planning import (
    plan_artifact_scaffold,
    plan_registry_init,
    project_registry_workspace_plan,
    validate_registry_workspace,
)
from tests.registry_maintenance_fixtures import replace_snapshot_file


class RegistryInitScaffoldTest(unittest.TestCase):
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
        self.assertIn(".github/workflows/aart-usage-validate.yml", files)
        self.assertIn(".github/workflows/aart-usage-dashboard.yml", files)
        workflow = files[".github/workflows/aart-registry.yml"]
        self.assertIn(b"registry test", workflow)
        self.assertIn(b"minimum", workflow)
        self.assertIn(b"latest", workflow)
        self.assertIn(b"validate --source . --strict --frozen", workflow)
        self.assertIn(b"pip install --no-deps ./.aart-tool", workflow)
        self.assertIn(b"vars.AART_REPOSITORY", workflow)
        self.assertEqual(workflow.count(b"persist-credentials: false"), 2)
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
        registry = project_registry_workspace_plan(SourceSnapshot(SnapshotOrigin.LOCAL, ()), initialized.value)
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
