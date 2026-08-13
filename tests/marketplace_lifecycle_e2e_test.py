"""End-to-end canonical lifecycle over a real temporary home, project, and source (LIFE02).

Nothing here is mocked below the CLI entry point: a real local source is synchronized into a real
managed snapshot, and the commands write into real project/user trees.  These tests exist to prove
that the JSON contract an agent depends on matches what actually lands on disk.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_artifacts import cli
from agent_artifacts.application.sources import SourceSyncPorts, SourceSyncRequest, sync_source
from agent_artifacts.configuration.model import (
    ConfiguredSource,
    ReportingSettings,
    SourceKind,
    SyncSettings,
    UserConfiguration,
)
from agent_artifacts.configuration.paths import Platform, resolve_config_paths
from agent_artifacts.configuration.schema import user_configuration_bytes
from agent_artifacts.domain.identifiers import SourceAlias
from agent_artifacts.domain.result import Ok
from agent_artifacts.io.source_store import (
    acquire_source_lock,
    publish_source_snapshot,
    read_current_source,
    release_source_lock,
)
from agent_artifacts.protocol.capabilities import parse_capability
from agent_artifacts.runtime_contract import EXECUTABLE_VERSION
from agent_artifacts.sources.git import acquire_git_snapshot
from agent_artifacts.sources.local import read_local_snapshot
from agent_artifacts.sources.model import SyncFallback
from agent_artifacts.sources.validation import validate_source_candidate

_FIXTURE = Path(__file__).parent / "fixtures" / "protocol" / "native-source-v1"
_COORDINATE = "reference/skill/code-review"
_COLLECTION = "reference/collection/essentials"


def _unwrap(result):
    assert isinstance(result, Ok), result
    return result.value


class _Environment:
    """A real, isolated home/project/XDG environment with one synchronized local source."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.home = root / "home"
        self.project = root / "project"
        self.home.mkdir()
        self.project.mkdir()
        # ``HOME`` is what the command boundary expands; the XDG values only matter on Linux, so
        # both must point at this temporary home for the test to be hermetic on either platform.
        self.xdg = {
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "XDG_DATA_HOME": str(self.home / ".local" / "share"),
            "XDG_CACHE_HOME": str(self.home / ".cache"),
        }
        platform = Platform.DARWIN if os.sys.platform == "darwin" else Platform.LINUX
        self.paths = resolve_config_paths(
            platform,
            home=str(self.home),
            xdg_config_home=self.xdg["XDG_CONFIG_HOME"],
            xdg_data_home=self.xdg["XDG_DATA_HOME"],
            xdg_cache_home=self.xdg["XDG_CACHE_HOME"],
        )
        self.source = ConfiguredSource(
            SourceAlias("reference"),
            SourceKind.SOURCE_LOCAL,
            str(_FIXTURE.resolve()),
            None,
            True,
        )
        config_path = Path(self.paths.user_config_file)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_bytes(
            user_configuration_bytes(
                UserConfiguration(1, (self.source,), None, SyncSettings(), ReportingSettings())
            )
        )
        self._synchronize()

    def _synchronize(self) -> None:
        ports = SourceSyncPorts(
            acquire_source_lock,
            release_source_lock,
            read_current_source,
            read_local_snapshot,
            acquire_git_snapshot,
            validate_source_candidate,
            publish_source_snapshot,
        )
        synced = sync_source(
            SourceSyncRequest(
                self.source,
                self.paths.data_root,
                EXECUTABLE_VERSION,
                (_unwrap(parse_capability("artifact-manifest-v1")),),
                observed_at_epoch_seconds=100,
                fallback=SyncFallback.REQUIRE_FRESH,
                offline=False,
                timeout_seconds=30,
            ),
            ports,
        )
        assert isinstance(synced, Ok), synced

    def run(self, *argv: str):
        """Invoke the real CLI and return ``(exit_code, parsed_json)``.

        ``--project`` is omitted for user-scope runs: the CLI rejects that combination on purpose,
        because user targets are resolved from the home directory rather than a project.
        """

        scoped_to_user = "user" in argv
        arguments = [*argv, "--json"]
        if not scoped_to_user:
            arguments = [*argv, "--project", str(self.project), "--json"]
        stdout = io.StringIO()
        with (
            mock.patch.dict(os.environ, self.xdg, clear=False),
            contextlib.redirect_stdout(stdout),
            mock.patch("os.getcwd", return_value=str(self.project)),
        ):
            code = cli.main(arguments)
        raw = stdout.getvalue()
        return code, (json.loads(raw) if raw.strip() else None)


@contextlib.contextmanager
def _environment():
    with tempfile.TemporaryDirectory() as raw:
        yield _Environment(Path(raw).resolve())


class LifecycleCopyE2ETest(unittest.TestCase):
    def test_runtime_health_is_advisory_and_never_blocks_installation(self) -> None:
        with _environment() as env:
            inventory = env.root / "runtime-environment.json"
            inventory.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "name": "old-python-repository",
                        "capabilities": [{"id": "python", "version": "3.10.14"}],
                    }
                ),
                encoding="utf-8",
            )

            health_code, health = env.run(
                "marketplace",
                "health",
                _COLLECTION,
                "--environment",
                str(inventory),
            )

            self.assertEqual(health_code, 0, health)
            self.assertTrue(health["advisory"])
            self.assertFalse(health["installation_blocking"])
            self.assertEqual(health["summary"]["unsatisfied"], 1)
            self.assertEqual(health["items"][0]["coordinate"], f"{_COORDINATE}@1.0.0")
            self.assertEqual(health["items"][0]["status"], "unsatisfied")

            install_code, installed = env.run(
                "marketplace", "install", _COORDINATE, "--profile", "claude", "--yes"
            )

            self.assertEqual(install_code, 0, installed)
            self.assertEqual(installed["session_status"], "succeeded")

    def test_collection_install_materializes_every_expanded_member(self) -> None:
        with _environment() as env:
            code, payload = env.run(
                "marketplace", "install", _COLLECTION, "--profile", "claude", "--yes"
            )

            self.assertEqual(code, 0, payload)
            self.assertTrue(payload["finalized"])
            installed = env.project / ".claude" / "skills" / "code-review" / "SKILL.md"
            self.assertTrue(installed.is_file(), sorted(map(str, env.project.rglob("*"))))

    def test_review_only_install_writes_nothing_to_the_project(self) -> None:
        with _environment() as env:
            code, payload = env.run("marketplace", "install", _COORDINATE, "--profile", "claude")

            self.assertEqual(code, 0, payload)
            self.assertFalse(payload["finalized"])
            self.assertTrue(payload["review"]["items"])
            self.assertEqual(list(env.project.iterdir()), [])

    def test_copy_install_materializes_the_payload_and_is_idempotent(self) -> None:
        with _environment() as env:
            code, payload = env.run(
                "marketplace", "install", _COORDINATE, "--profile", "claude", "--yes"
            )

            self.assertEqual(code, 0, payload)
            self.assertTrue(payload["finalized"])
            self.assertEqual(payload["session_status"], "succeeded")
            installed = env.project / ".claude" / "skills" / "code-review" / "SKILL.md"
            self.assertTrue(installed.is_file(), sorted(map(str, env.project.rglob("*"))))
            self.assertFalse(installed.is_symlink())

            repeat_code, repeat = env.run(
                "marketplace", "install", _COORDINATE, "--profile", "claude", "--yes"
            )

            self.assertEqual(repeat_code, 0, repeat)
            self.assertEqual(repeat["session_status"], "no-op")
            self.assertEqual([item["status"] for item in repeat["items"]], ["current"])

    def test_managed_symlink_install_produces_a_link_into_the_object_store(self) -> None:
        with _environment() as env:
            code, payload = env.run(
                "marketplace",
                "install",
                _COORDINATE,
                "--profile",
                "claude",
                "--mode",
                "symlink",
                "--yes",
            )

            self.assertEqual(code, 0, payload)
            installed = env.project / ".claude" / "skills" / "code-review"
            self.assertTrue(installed.is_symlink() or installed.is_dir())
            resolved = installed.resolve()
            self.assertTrue(
                str(resolved).startswith(str(Path(env.paths.data_root).resolve())),
                f"managed symlink must target the object store, not {resolved}",
            )

    def test_user_scope_install_stays_out_of_the_project_tree(self) -> None:
        with _environment() as env:
            code, payload = env.run(
                "marketplace",
                "install",
                _COORDINATE,
                "--profile",
                "claude",
                "--scope",
                "user",
                "--yes",
            )

            self.assertEqual(code, 0, payload)
            self.assertFalse((env.project / ".claude" / "skills" / "code-review").exists())
            self.assertTrue(any(env.home.rglob("SKILL.md")), sorted(map(str, env.home.rglob("*"))))


class LifecycleUpdateStatusUninstallE2ETest(unittest.TestCase):
    def test_update_on_a_current_installation_is_a_no_op(self) -> None:
        with _environment() as env:
            env.run("marketplace", "install", _COORDINATE, "--profile", "claude", "--yes")

            code, payload = env.run(
                "marketplace", "update", _COORDINATE, "--profile", "claude", "--yes"
            )

            self.assertEqual(code, 0, payload)
            self.assertEqual(payload["session_status"], "no-op")

    def test_status_reports_the_installed_artifact_without_changing_it(self) -> None:
        with _environment() as env:
            env.run("marketplace", "install", _COORDINATE, "--profile", "claude", "--yes")
            installed = env.project / ".claude" / "skills" / "code-review" / "SKILL.md"
            before = installed.read_bytes()

            code, payload = env.run("marketplace", "status", "--profile", "claude")

            self.assertEqual(code, 0, payload)
            self.assertEqual(payload["operation"], "marketplace.status")
            self.assertEqual(installed.read_bytes(), before)

    def test_forced_reinstall_upserts_the_record_instead_of_duplicating_it(self) -> None:
        # ``--force`` authorizes overwriting an already-installed artifact.  The record it leaves
        # must still be one record: a duplicate would make later status and uninstall ambiguous.
        with _environment() as env:
            env.run("marketplace", "install", _COORDINATE, "--profile", "claude", "--yes")

            code, payload = env.run(
                "marketplace", "install", _COORDINATE, "--profile", "claude", "--force", "--yes"
            )

            self.assertEqual(code, 0, payload)
            state = json.loads((env.project / ".agent-artifacts" / "manifest.json").read_text())
            self.assertEqual(len(state["installations"]), 1, state)

    def test_a_bare_update_selects_every_installation_in_the_scope(self) -> None:
        # ``update`` without coordinates is the routine operator action.  It must reconcile the
        # whole recorded scope, not silently do nothing because no coordinate was named.
        with _environment() as env:
            env.run("marketplace", "install", _COORDINATE, "--profile", "claude", "--yes")

            code, payload = env.run("marketplace", "update", "--profile", "claude", "--yes")

            self.assertEqual(code, 0, payload)
            self.assertEqual(len(payload["items"]), 1, payload)
            self.assertEqual(payload["items"][0]["status"], "current")

    def test_review_and_json_are_observations_that_change_no_effect(self) -> None:
        # ``--json`` selects a rendering.  An agent reading the plan must be able to trust that
        # asking for it never installs anything the human-readable path would not have.
        with _environment() as env:
            code, payload = env.run("marketplace", "install", _COORDINATE, "--profile", "claude")

            self.assertEqual(code, 0, payload)
            self.assertFalse(payload["finalized"])
            self.assertEqual(list(env.project.iterdir()), [], "review must not touch the project")

    def test_uninstall_removes_the_installed_payload(self) -> None:
        with _environment() as env:
            env.run("marketplace", "install", _COORDINATE, "--profile", "claude", "--yes")
            installed = env.project / ".claude" / "skills" / "code-review"
            self.assertTrue(installed.exists())

            code, payload = env.run(
                "marketplace", "uninstall", _COORDINATE, "--profile", "claude", "--yes"
            )

            self.assertEqual(code, 0, payload)
            self.assertFalse(installed.exists(), sorted(map(str, env.project.rglob("*"))))


class LifecycleDiagnosticsE2ETest(unittest.TestCase):
    def test_an_unknown_coordinate_reports_a_structured_not_found_diagnostic(self) -> None:
        with _environment() as env:
            code, payload = env.run(
                "marketplace", "install", "reference/skill/absent", "--profile", "claude", "--yes"
            )

            self.assertEqual(code, 1)
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["diagnostics"][0]["code"], "artifact-not-found")

    def test_an_unknown_profile_is_rejected_before_anything_is_written(self) -> None:
        with _environment() as env:
            code, payload = env.run(
                "marketplace", "install", _COORDINATE, "--profile", "nope", "--yes"
            )

            self.assertEqual(code, 1)
            self.assertFalse(payload["ok"])
            self.assertEqual(list(env.project.iterdir()), [])

    def test_a_profile_outside_the_declared_compatibility_is_refused(self) -> None:
        # The fixture declares ``claude``/``tabnine``.  A known-but-undeclared profile must be
        # refused with the allowed set named, so the operator can pick a profile that works
        # instead of guessing why an install produced nothing.
        with _environment() as env:
            code, payload = env.run(
                "marketplace", "install", _COORDINATE, "--profile", "opencode", "--yes"
            )

            self.assertEqual(code, 1)
            diagnostic = payload["diagnostics"][0]
            self.assertEqual(diagnostic["code"], "artifact-incompatible")
            self.assertIn("claude", diagnostic["message"])
            self.assertEqual(list(env.project.iterdir()), [])

    def test_an_unreadable_install_state_is_a_typed_refusal_not_a_crash(self) -> None:
        # Reading damaged state must fail closed with a diagnostic rather than tracebacking or,
        # worse, treating the project as if nothing were installed and reinstalling over it.
        with _environment() as env:
            env.run("marketplace", "install", _COORDINATE, "--profile", "claude", "--yes")
            state = env.project / ".agent-artifacts" / "manifest.json"
            self.assertTrue(state.exists(), sorted(map(str, env.project.rglob("*"))))
            state.write_text("{ this is not valid json ]", encoding="utf-8")

            code, payload = env.run("marketplace", "status", "--profile", "claude")

            self.assertNotEqual(code, 0)
            self.assertFalse(payload["ok"])
            self.assertTrue(payload["diagnostics"])

    def test_a_malformed_coordinate_reports_the_accepted_grammar(self) -> None:
        with _environment() as env:
            code, payload = env.run(
                "marketplace", "install", "code-review", "--profile", "claude", "--yes"
            )

            self.assertEqual(code, 1)
            self.assertIn("<source>/<kind>/<name>", payload["diagnostics"][0]["message"])

    def test_setup_on_an_artifact_that_declares_none_completes_with_an_empty_queue(self) -> None:
        with _environment() as env:
            env.run("marketplace", "install", _COORDINATE, "--profile", "claude", "--yes")

            code, payload = env.run(
                "marketplace", "setup", _COORDINATE, "--profile", "claude", "--yes"
            )

            self.assertEqual(code, 0, payload)
            self.assertEqual(payload["setup"]["planned"], [])
            self.assertEqual(payload["setup"]["planning_failures"], [])

    def test_setup_review_never_executes_and_never_authorizes_implicitly(self) -> None:
        with _environment() as env:
            env.run("marketplace", "install", _COORDINATE, "--profile", "claude", "--yes")

            code, payload = env.run("marketplace", "setup", _COORDINATE, "--profile", "claude")

            self.assertEqual(code, 0, payload)
            self.assertFalse(payload["finalized"])
            self.assertIn("setup", payload)

    def test_offline_install_from_the_published_snapshot_succeeds(self) -> None:
        with _environment() as env:
            code, payload = env.run(
                "marketplace", "install", _COORDINATE, "--profile", "claude", "--offline", "--yes"
            )

            self.assertEqual(code, 0, payload)
            self.assertTrue(payload["offline_last_known_good"])


if __name__ == "__main__":  # pragma: no cover - unittest entry point
    unittest.main()
