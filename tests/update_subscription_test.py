"""Integration coverage for updates routed by recorded catalog subscriptions."""

import io
import pathlib
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from agent_artifacts.commands import _common, install, update
from agent_artifacts.manifest import empty_manifest, upsert
from agent_artifacts.model import CatalogSubscription, ManifestEntry, Request
from agent_artifacts.source import open_source

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"


def _copy_catalog(root: pathlib.Path) -> pathlib.Path:
    shutil.copytree(FIXTURES, root)
    return root


def _run_install(project: pathlib.Path, source: pathlib.Path, name: str, profile: str) -> None:
    request = Request(
        command="install",
        names=(name,),
        profiles=(profile,),
        source_dir=str(source),
        project=str(project),
        yes=True,
    )
    with redirect_stdout(io.StringIO()):
        assert install.run(request) == 0


class RecordedSubscriptionUpdateTests(unittest.TestCase):
    def test_update_rebuilds_github_repo_and_ref_from_recorded_subscription(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = pathlib.Path(tmp) / "project"
            entry = ManifestEntry(
                artifact="code-review",
                type="skill",
                profile="claude",
                source="pin:old",
                subscription=CatalogSubscription("github", "acme/catalog", "release"),
            )
            _common.save_manifest(str(project), upsert(empty_manifest("acme/catalog"), entry))
            seen = []

            def fake_open(request):
                seen.append(request)
                return open_source(Request(command="update", source_dir=str(FIXTURES)))

            with patch.object(update, "open_source", side_effect=fake_open):
                with redirect_stdout(io.StringIO()):
                    code = update.run(Request(command="update", project=str(project)))

            self.assertEqual(code, _common.OK)
            self.assertEqual(seen[0].repo, "acme/catalog")
            self.assertEqual(seen[0].version, "release")
            refreshed = _common.load_manifest(
                Request(command="status", project=str(project))
            ).value.installed[0]
            self.assertEqual(
                refreshed.subscription,
                CatalogSubscription("github", "acme/catalog", "release"),
            )

    def test_update_without_source_reopens_recorded_local_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            source = _copy_catalog(root / "catalog")
            project = root / "project"
            _run_install(project, source, "python-style", "tabnine")
            destination = project / ".tabnine/guidelines/python-style.md"

            (source / "guidelines/python-style.md").write_text(
                "---\ndescription: Python style\n---\n\n# From recorded catalog\n",
                encoding="utf-8",
            )

            with redirect_stdout(io.StringIO()):
                code = update.run(Request(command="update", project=str(project)))

            self.assertEqual(code, _common.OK)
            self.assertEqual(destination.read_text(encoding="utf-8"), "\n# From recorded catalog")
            entry = _common.load_manifest(
                Request(command="status", project=str(project))
            ).value.installed[0]
            self.assertEqual(entry.subscription, CatalogSubscription("local", str(source)))

    def test_missing_recorded_local_catalog_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            source = _copy_catalog(root / "catalog")
            project = root / "project"
            _run_install(project, source, "python-style", "tabnine")
            shutil.rmtree(source)

            output = io.StringIO()
            with redirect_stdout(output):
                code = update.run(Request(command="update", project=str(project)))

            self.assertNotEqual(code, _common.OK)
            self.assertIn(str(source), output.getvalue())
            self.assertIn("does not exist", output.getvalue())

    def test_one_update_refreshes_entries_from_multiple_recorded_catalogs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            guideline_source = _copy_catalog(root / "guideline-catalog")
            skill_source = _copy_catalog(root / "skill-catalog")
            project = root / "project"
            _run_install(project, guideline_source, "python-style", "tabnine")
            _run_install(project, skill_source, "code-review", "claude")

            (guideline_source / "guidelines/python-style.md").write_text(
                "---\ndescription: Python style\n---\n\n# Catalog one\n", encoding="utf-8"
            )
            (skill_source / "skills/code-review/SKILL.md").write_text(
                "---\nname: code-review\n---\n# Catalog two\n", encoding="utf-8"
            )

            with redirect_stdout(io.StringIO()):
                code = update.run(Request(command="update", project=str(project)))

            self.assertEqual(code, _common.OK)
            self.assertIn(
                "Catalog one",
                (project / ".tabnine/guidelines/python-style.md").read_text(encoding="utf-8"),
            )
            self.assertIn(
                "Catalog two",
                (project / ".claude/skills/code-review/SKILL.md").read_text(encoding="utf-8"),
            )
            subscriptions = {
                entry.artifact: entry.subscription
                for entry in _common.load_manifest(
                    Request(command="status", project=str(project))
                ).value.installed
            }
            self.assertEqual(
                subscriptions,
                {
                    "python-style": CatalogSubscription("local", str(guideline_source)),
                    "code-review": CatalogSubscription("local", str(skill_source)),
                },
            )

    def test_explicit_source_override_becomes_new_subscription(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            first = _copy_catalog(root / "first")
            second = _copy_catalog(root / "second")
            project = root / "project"
            _run_install(project, first, "python-style", "tabnine")
            (second / "guidelines/python-style.md").write_text(
                "---\ndescription: Python style\n---\n\n# Migrated\n", encoding="utf-8"
            )

            with redirect_stdout(io.StringIO()):
                code = update.run(
                    Request(command="update", source_dir=str(second), project=str(project))
                )

            self.assertEqual(code, _common.OK)
            entry = _common.load_manifest(
                Request(command="status", project=str(project))
            ).value.installed[0]
            self.assertEqual(entry.subscription, CatalogSubscription("local", str(second)))

    def test_all_groups_are_planned_before_any_files_are_mutated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            valid = _copy_catalog(root / "valid")
            broken = _copy_catalog(root / "broken")
            project = root / "project"
            _run_install(project, valid, "python-style", "tabnine")
            destination = project / ".tabnine/guidelines/python-style.md"
            original = destination.read_text(encoding="utf-8")
            (valid / "guidelines/python-style.md").write_text(
                "---\ndescription: Python style\n---\n\n# Must not apply\n", encoding="utf-8"
            )
            (broken / "skills/code-review/SKILL.md").write_text("not frontmatter", encoding="utf-8")

            request = Request(command="status", project=str(project))
            current = _common.load_manifest(request).value
            injected = ManifestEntry(
                artifact="code-review",
                type="skill",
                profile="claude",
                source=f"local:{broken}",
                subscription=CatalogSubscription("local", str(broken)),
            )
            _common.save_manifest(str(project), upsert(current, injected))

            with redirect_stdout(io.StringIO()):
                code = update.run(Request(command="update", project=str(project)))

            self.assertNotEqual(code, _common.OK)
            self.assertEqual(destination.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
