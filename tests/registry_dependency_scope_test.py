"""SI-9: `requires` is intra-registry, and the refusal says so.

`LAF-38` was filed as a question, not a defect: `registry build` refuses
`skill/la-probe requires missing skill/using-residues` when the dependency lives in another
configured registry.  The restriction is deliberate (design §7.2) — a cross-registry dependency
breaks whenever a maintainer who does not own the artifact changes their own registry — and the
defect was that nothing said so.  "requires missing" reads as "not published yet", so a maintainer
waits for a publication that will never make the build pass.

These tests hold the wording to the rule: every refusal is produced by the real planning path, never
by a literal written here, and the two shapes a maintainer can actually be in are distinguished —
an identity this registry does not publish at all, and one it references from another origin.
"""

from __future__ import annotations

import json
import unittest

from agent_artifacts.domain.identifiers import SourceId
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.protocol.native_tree import SnapshotEntry, SourceSnapshot
from agent_artifacts.protocol.registry_index import (
    index_artifact_from_package,
    validate_registry_graph,
)
from agent_artifacts.protocol.registry_schema import parse_registry_manifest
from agent_artifacts.protocol.semver import parse_semver
from agent_artifacts.registry_maintenance.planning import registry_native_content
from tests.registry_index_test import _digest, _package
from tests.registry_maintenance_fixtures import (
    append_snapshot_file,
    registry_with_owned_package,
    replace_snapshot_file,
    snapshot_file,
)
from tests.source_remediation_test import _COMMAND, _parse_failure

_OWNED_MANIFEST = "artifacts/skill/code-review/artifact.json"
_ELSEWHERE = "https://github.com/example/other-registry.git"


def _requiring(name: str) -> SourceSnapshot:
    """A registry that owns one package, which requires ``skill/<name>``."""

    snapshot = registry_with_owned_package()
    document = json.loads(snapshot_file(snapshot, _OWNED_MANIFEST))
    document["requires"] = [{"type": "skill", "name": name}]
    return replace_snapshot_file(snapshot, _OWNED_MANIFEST, json.dumps(document).encode())


def _referencing(snapshot: SourceSnapshot, name: str) -> SourceSnapshot:
    """The same registry, now referencing ``skill/<name>`` from another repository."""

    entry = {
        "schema_version": 1,
        "type": "skill",
        "name": name,
        "source": {
            "kind": "git",
            "url": _ELSEWHERE,
            "ref": "main",
            "path": f"artifacts/skill/{name}",
        },
        "review": {"status": "approved", "policy": "company-review-v1"},
    }
    return append_snapshot_file(snapshot, f"entries/skill/{name}.json", json.dumps(entry).encode())


def _compiled(snapshot: SourceSnapshot):
    """Compile the workspace's owned content exactly as every maintainer command does."""

    files: dict[str, SnapshotEntry] = {str(entry.path): entry for entry in snapshot.entries}
    registry = parse_registry_manifest(files["aart-registry.json"].content)
    assert isinstance(registry, Ok), registry
    version = parse_semver("2.1.0")
    assert isinstance(version, Ok), version
    return registry_native_content(
        snapshot,
        files,
        registry.value,
        executable_version=version.value,
        available_capabilities=(),
    )


def _refusal(result) -> tuple[str, tuple[str, ...]]:
    assert isinstance(result, Err), f"expected a refusal, got {result}"
    assert len(result.diagnostics) == 1, result.diagnostics
    diagnostic = result.diagnostics[0]
    return diagnostic.message, diagnostic.remediation


class DependencyScopeRefusalTest(unittest.TestCase):
    def test_a_dependency_the_registry_does_not_publish_states_the_rule(self) -> None:
        message, remediation = _refusal(_compiled(_requiring("helper")))

        self.assertIn("skill/code-review requires skill/helper", message)
        self.assertIn("this registry does not publish", message)
        self.assertIn("requires resolves inside one registry", message)
        self.assertNotIn("missing", message)
        self.assertTrue(remediation)

    def test_a_referenced_dependency_is_not_reported_as_an_absent_one(self) -> None:
        """The two cases have different fixes, so they are not allowed to read alike.

        A promoted reference is published by this registry — a consumer can install it — and is
        still not something this registry's own dependency graph can resolve.  Told "does not
        publish", a maintainer looking at their own `entries/` directory would have every reason to
        think AART was simply wrong.
        """

        message, _remediation = _refusal(_compiled(_referencing(_requiring("helper"), "helper")))

        self.assertIn(_ELSEWHERE, message)
        self.assertIn("rather than owning", message)
        self.assertNotIn("does not publish", message)

    def test_a_referenced_dependency_is_still_refused(self) -> None:
        """SI-9 documents the restriction; it does not lift it (design §7.2, guardrail 1)."""

        self.assertIsInstance(_compiled(_referencing(_requiring("helper"), "helper")), Err)

    def test_the_registry_builds_when_the_dependency_is_owned(self) -> None:
        """The rule refuses one thing only: the workspace it is meant to accept still compiles."""

        self.assertIsInstance(_compiled(registry_with_owned_package()), Ok)

    def test_the_index_graph_refuses_with_the_same_words(self) -> None:
        """The second site of the same rule, reached when an index is generated or parsed."""

        artifact = index_artifact_from_package(
            _package("review", requires=[{"type": "skill", "name": "helper"}]),
            source_id=SourceId("company-registry"),
            object_digest=_digest("3"),
        )

        indexed = validate_registry_graph((artifact,), ())

        message, remediation = _refusal(indexed)
        self.assertIn("skill/review requires skill/helper", message)
        self.assertIn("this registry does not publish", message)
        self.assertTrue(remediation)


class DependencyScopeRemediationTest(unittest.TestCase):
    """SI-6's rule, applied to the remediation SI-9 adds: every command named must exist."""

    def test_every_command_the_remediation_names_is_one_the_parser_accepts(self) -> None:
        _message, remediation = _refusal(_compiled(_requiring("helper")))

        commands = tuple(match for line in remediation for match in _COMMAND.findall(line))
        self.assertTrue(commands, f"remediation names no command: {remediation}")
        for command in commands:
            failure = _parse_failure(command)
            self.assertIsNone(failure, f"`{command}` is not accepted: {failure}")

    def test_the_remediation_names_the_route_that_works_in_this_release(self) -> None:
        """Publishing it here is the route; promoting it is named for what it actually does.

        `registry promote-native` puts a foreign package in this registry for consumers to install,
        and a promoted identity is *not* a `requires` target — proved by
        `test_a_referenced_dependency_is_still_refused`.  Offering it as the fix for this refusal
        would send the maintainer to a command that cannot resolve their build.
        """

        _message, remediation = _refusal(_compiled(_requiring("helper")))
        joined = " ".join(remediation)

        self.assertIn("aart registry scaffold", joined)
        self.assertIn("does not", joined)


if __name__ == "__main__":
    unittest.main()
