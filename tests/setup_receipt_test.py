"""RR-1: the persisted setup record can be read from outside a run.

Three absences get three sentences, because an operator holding a refusal needs to know which
of them they are in: never installed, installed without setup, or a pointer whose target is
gone.
"""

from __future__ import annotations

import json

from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.install_state.schema import parse_install_state
from agent_artifacts.setup_receipt import (
    RECEIPT_INVALID,
    RECEIPT_MISSING,
    RECEIPT_NO_SETUP,
    RECEIPT_NOT_INSTALLED,
    locate_setup_record,
    missing_record,
    read_setup_record,
    setup_state_file,
)

DATA_ROOT = "/data"


def _installation(*, name: str, setup_ref: str | None) -> dict:
    record = {
        "coordinate": f"registry-a/mcp/{name}",
        "artifact": {
            "type": "mcp",
            "name": name,
            "version": "1.0.0",
            "manifest_digest": f"sha256:{'a' * 64}",
            "object_digest": f"sha256:{'b' * 64}",
            "payload_digest": f"sha256:{'c' * 64}",
        },
        "profile": "claude",
        "profile_version": 1,
        "scope": "project",
        "requested_mode": "copy",
        "source": {
            "alias": "registry-a",
            "kind": "registry-git",
            "origin": "github.com/example/registry",
            "declared_id": "la-registry-a",
            "resolved_commit": "0" * 40,
            "subscription_ref": "main",
        },
        "effects": [
            {
                "kind": "write-file",
                "destination": ".mcp.json",
                "actual_mode": "copy",
                "created_destination": True,
                "overwrote": False,
                "installed_digest": f"sha256:{'d' * 64}",
                "source_path": "payload/x.json",
            }
        ],
    }
    if setup_ref is not None:
        record["setup_state_ref"] = setup_ref
    return record


def _state(records: list[dict]):
    parsed = parse_install_state(
        json.dumps({"schema_version": 2, "installations": records}).encode("utf-8")
    )
    assert isinstance(parsed, Ok), parsed
    return parsed.value


def _codes(error: Err) -> set[str]:
    return {diagnostic.code.value for diagnostic in error.diagnostics}


def _remediation(error: Err) -> tuple[str, ...]:
    return tuple(line for diagnostic in error.diagnostics for line in diagnostic.remediation)


def test_locates_the_record_a_setup_bearing_installation_points_at() -> None:
    state = _state([_installation(name="github-docker", setup_ref="setup-" + "e" * 20)])

    located = locate_setup_record(
        state,
        coordinate="registry-a/mcp/github-docker",
        profile="claude",
        scope="project",
        data_root=DATA_ROOT,
    )

    assert isinstance(located, Ok), located
    assert located.value.setup_state_ref == "setup-" + "e" * 20
    assert located.value.state_path == setup_state_file(DATA_ROOT, "setup-" + "e" * 20)


def test_an_uninstalled_coordinate_is_not_an_installation_without_setup() -> None:
    state = _state([_installation(name="github-docker", setup_ref="setup-" + "e" * 20)])

    located = locate_setup_record(
        state,
        coordinate="registry-a/mcp/never-installed",
        profile="claude",
        scope="project",
        data_root=DATA_ROOT,
    )

    assert isinstance(located, Err)
    assert _codes(located) == {RECEIPT_NOT_INSTALLED.value}
    assert _remediation(located), "a refusal with no remediation is the residue RS-09 records"


def test_an_installation_with_no_recorded_run_claims_only_what_the_state_proves() -> None:
    # Measured live on 2026-08-15: the artifact *did* declare setup and planning was refused,
    # while this refusal said it "declares no setup". InstallationRecord carries no such field,
    # so the reader must not assert it.
    state = _state([_installation(name="plain", setup_ref=None)])

    located = locate_setup_record(
        state,
        coordinate="registry-a/mcp/plain",
        profile="claude",
        scope="project",
        data_root=DATA_ROOT,
    )

    assert isinstance(located, Err)
    message = " ".join(d.message for d in located.diagnostics)
    assert "no setup run has been recorded" in message
    assert "declares no setup" not in message
    assert any("--authorize-untrusted-source" in line for line in _remediation(located))


def test_an_installation_declaring_no_setup_says_so_in_its_own_words() -> None:
    state = _state([_installation(name="plain", setup_ref=None)])

    located = locate_setup_record(
        state,
        coordinate="registry-a/mcp/plain",
        profile="claude",
        scope="project",
        data_root=DATA_ROOT,
    )

    assert isinstance(located, Err)
    assert _codes(located) == {RECEIPT_NO_SETUP.value}
    assert _remediation(located)


def test_a_pointer_whose_target_is_gone_is_its_own_refusal() -> None:
    state = _state([_installation(name="github-docker", setup_ref="setup-" + "e" * 20)])
    located = locate_setup_record(
        state,
        coordinate="registry-a/mcp/github-docker",
        profile="claude",
        scope="project",
        data_root=DATA_ROOT,
    )
    assert isinstance(located, Ok)

    absent = missing_record(located.value)

    assert _codes(absent) == {RECEIPT_MISSING.value}
    assert _remediation(absent)


def test_reads_the_one_record_a_located_file_holds() -> None:
    state = _state([_installation(name="github-docker", setup_ref="setup-" + "e" * 20)])
    located = locate_setup_record(
        state,
        coordinate="registry-a/mcp/github-docker",
        profile="claude",
        scope="project",
        data_root=DATA_ROOT,
    )
    assert isinstance(located, Ok)
    text = json.dumps(
        {
            "version": 1,
            "records": [
                {
                    "artifact_type": "mcp",
                    "artifact_name": "github-docker",
                    "profile": "claude",
                    "scope": "project",
                    "status": "configured",
                    "detail": "Setup completed",
                    "plan_hash": "f" * 64,
                    "receipt": [{"step_id": "build", "module": "docker.build@1"}],
                }
            ],
        }
    )

    record = read_setup_record(text, location=located.value)

    assert isinstance(record, Ok), record
    assert record.value.artifact_name == "github-docker"
    assert record.value.receipt[0]["module"] == "docker.build@1"


def test_a_file_holding_no_single_bound_record_is_refused() -> None:
    state = _state([_installation(name="github-docker", setup_ref="setup-" + "e" * 20)])
    located = locate_setup_record(
        state,
        coordinate="registry-a/mcp/github-docker",
        profile="claude",
        scope="project",
        data_root=DATA_ROOT,
    )
    assert isinstance(located, Ok)

    empty = read_setup_record(json.dumps({"version": 1, "records": []}), location=located.value)
    malformed = read_setup_record("{not json", location=located.value)

    assert _codes(empty) == {RECEIPT_INVALID.value}
    assert _codes(malformed) == {RECEIPT_INVALID.value}
