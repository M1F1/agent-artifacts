"""VI-2: a copy that contradicts its own record fails validate and audit.

`LAF-41` reproduced live: replace a vendored package's payload, re-run `registry lock --yes` and
`registry build --yes`, and every gate stayed green. They stayed green by construction — the lock
and the index are derived from the bytes that are there, so they agree with any substitution — which
is why the reproduction here re-locks and re-builds before asserting, rather than tampering and
checking validate alone.
"""

from __future__ import annotations

import json
import unittest

from agent_artifacts.domain.identifiers import ArtifactIdentity
from agent_artifacts.domain.result import Ok
from agent_artifacts.protocol.capabilities import Capability
from agent_artifacts.protocol.json import canonical_json_bytes
from agent_artifacts.protocol.native_schema import parse_provenance, provenance_to_json
from agent_artifacts.protocol.native_tree import (
    SnapshotEntry,
    SnapshotEntryKind,
    SnapshotOrigin,
    SourceSnapshot,
)
from agent_artifacts.protocol.paths import parse_relative_path
from agent_artifacts.protocol.semver import SemVer
from agent_artifacts.registry_commands.planning import (
    audit_registry_workspace,
    plan_registry_build,
    plan_registry_lock,
    project_registry_workspace_plan,
    validate_registry_workspace,
)
from agent_artifacts.registry_maintenance.vendoring import (
    VendorOptions,
    VendorOrigin,
    project_vendored_package,
)
from agent_artifacts.sources.subtree import take_subtree
from tests.registry_maintenance_fixtures import (
    empty_registry_snapshot,
    replace_snapshot_file,
    snapshot_file,
)

_CAPABILITIES = (Capability("artifact-manifest-v1"),)
_VERSION = SemVer(2, 4, 0)
_COMMIT = "c" * 40
_URL = "https://github.com/example/atlassian-mcp.git"
_MCP_JSON = (
    json.dumps({"name": "atlassian", "server": {"command": "npx", "args": ["-y", "srv"]}}).encode()
    + b"\n"
)
_BASE = "artifacts/mcp/atlassian"


def _path(raw: str):
    parsed = parse_relative_path(raw)
    assert isinstance(parsed, Ok), parsed
    return parsed.value


def _file(raw: str, content: bytes = b"x", *, executable: bool = False) -> SnapshotEntry:
    return SnapshotEntry(_path(raw), SnapshotEntryKind.FILE, content, executable)


def _directory(raw: str) -> SnapshotEntry:
    return SnapshotEntry(_path(raw), SnapshotEntryKind.DIRECTORY)


def _upstream() -> SourceSnapshot:
    return SourceSnapshot(
        SnapshotOrigin.IMMUTABLE_GIT,
        (
            _directory("servers"),
            _directory("servers/atlassian"),
            _file("servers/atlassian/index.js", b"console.log('serve');\n"),
            _directory("servers/atlassian/lib"),
            _file("servers/atlassian/lib/client.js", b"export const client = 1;\n"),
        ),
    )


def _vendored_registry() -> SourceSnapshot:
    """An otherwise empty registry that owns one vendored package."""

    taken = take_subtree(_upstream(), _path("servers/atlassian"))
    assert isinstance(taken, Ok), taken
    projected = project_vendored_package(
        taken.value,
        VendorOrigin(_URL, "v1.4.0", _COMMIT),
        VendorOptions(
            ArtifactIdentity("mcp", "atlassian"),
            SemVer(1, 0, 0),
            "Atlassian MCP server, vendored from upstream.",
            ("claude",),
            ("darwin",),
            ("project",),
            ("copy",),
            authored=(("payload/mcp.json", _MCP_JSON, False),),
            license="MIT",
        ),
        artifact_root=_path("artifacts"),
        importer_version=_VERSION,
    )
    assert isinstance(projected, Ok), projected
    snapshot = empty_registry_snapshot()
    return SourceSnapshot(
        snapshot.origin,
        (
            *snapshot.entries,
            *(
                _file(relative, content, executable=executable)
                for relative, content, executable in projected.value.files
            ),
        ),
    )


def _compiled(snapshot: SourceSnapshot) -> SourceSnapshot:
    """Lock and build the registry, exactly as the reproduction did after tampering."""

    locked = plan_registry_lock(
        snapshot, (), executable_version=_VERSION, available_capabilities=_CAPABILITIES
    )
    assert isinstance(locked, Ok), locked
    with_lock = project_registry_workspace_plan(snapshot, locked.value)
    assert isinstance(with_lock, Ok), with_lock
    built = plan_registry_build(
        with_lock.value, (), executable_version=_VERSION, available_capabilities=_CAPABILITIES
    )
    assert isinstance(built, Ok), built
    complete = project_registry_workspace_plan(with_lock.value, built.value)
    assert isinstance(complete, Ok), complete
    return complete.value


def _validate(snapshot: SourceSnapshot, *, require_compiled: bool = False):
    report = validate_registry_workspace(
        snapshot,
        executable_version=_VERSION,
        available_capabilities=_CAPABILITIES,
        require_compiled=require_compiled,
    )
    assert isinstance(report, Ok), report
    return report.value


def _audit(snapshot: SourceSnapshot):
    report = audit_registry_workspace(
        snapshot, executable_version=_VERSION, available_capabilities=_CAPABILITIES
    )
    assert isinstance(report, Ok), report
    return report.value


def _messages(report) -> str:
    return "; ".join(
        diagnostic.message for check in report.checks for diagnostic in check.diagnostics
    )


def _tampered(snapshot: SourceSnapshot) -> SourceSnapshot:
    return replace_snapshot_file(
        snapshot, f"{_BASE}/payload/index.js", b"console.log('exfiltrate');\n"
    )


class VendoredCopyGateTest(unittest.TestCase):
    def test_an_untouched_vendored_registry_passes_both_gates(self) -> None:
        registry = _compiled(_vendored_registry())
        self.assertTrue(
            _validate(registry, require_compiled=True).passed, _messages(_validate(registry))
        )
        self.assertTrue(_audit(registry).passed, _messages(_audit(registry)))

    def test_a_substituted_payload_fails_validate_and_audit_after_relocking(self) -> None:
        """The `LAF-41` reproduction, end to end and offline."""

        registry = _compiled(_tampered(_vendored_registry()))
        validated = _validate(registry, require_compiled=True)
        audited = _audit(registry)
        self.assertFalse(validated.passed)
        self.assertFalse(audited.passed)
        for report in (validated, audited):
            self.assertIn("no longer matches the origin it records", _messages(report))
            self.assertIn("mcp/atlassian", _messages(report))

    def test_the_finding_names_both_digests(self) -> None:
        recorded = parse_provenance(
            snapshot_file(_vendored_registry(), f"{_BASE}/provenance.json"),
            path=f"{_BASE}/provenance.json",
        )
        assert isinstance(recorded, Ok), recorded
        message = _messages(_audit(_tampered(_vendored_registry())))
        self.assertIn(str(recorded.value.origin.input_digest), message)
        self.assertIn("copied payload files digest to sha256:", message)

    def test_a_hand_edited_authored_list_does_not_hide_the_substitution(self) -> None:
        """Declaring the edited file authored removes it from the copy, which is still a mismatch."""

        registry = _tampered(_vendored_registry())
        document = parse_provenance(
            snapshot_file(registry, f"{_BASE}/provenance.json"), path=f"{_BASE}/provenance.json"
        )
        assert isinstance(document, Ok), document
        raw = json.loads(canonical_json_bytes(provenance_to_json(document.value)))
        raw["aart.vendor"]["authored"] = ["payload/index.js", "payload/mcp.json"]
        edited = replace_snapshot_file(
            registry, f"{_BASE}/provenance.json", json.dumps(raw).encode() + b"\n"
        )
        self.assertFalse(_audit(edited).passed)
        self.assertFalse(_validate(edited).passed)

    def test_an_owned_package_without_provenance_is_unaffected(self) -> None:
        """Only a package carrying `registry-vendor-v1` provenance ships bytes to check."""

        registry = _vendored_registry()
        without = SourceSnapshot(
            registry.origin,
            tuple(
                entry for entry in registry.entries if str(entry.path) != f"{_BASE}/provenance.json"
            ),
        )
        self.assertTrue(_validate(without).passed, _messages(_validate(without)))
        self.assertNotIn("no longer matches", _messages(_audit(without)))

    def test_a_provenance_written_by_another_importer_is_not_verified(self) -> None:
        registry = _vendored_registry()
        raw = json.loads(snapshot_file(registry, f"{_BASE}/provenance.json"))
        raw["importer"]["id"] = "native-promote-v1"
        del raw["aart.vendor"]
        foreign = replace_snapshot_file(
            _tampered(registry), f"{_BASE}/provenance.json", json.dumps(raw).encode() + b"\n"
        )
        self.assertNotIn("no longer matches", _messages(_validate(foreign)))
        self.assertNotIn("no longer matches", _messages(_audit(foreign)))


if __name__ == "__main__":
    unittest.main()
