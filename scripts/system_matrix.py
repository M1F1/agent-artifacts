#!/usr/bin/env python3
"""Run the named AART 1.0 system and fault-injection scenarios hermetically."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable
SCHEMA_VERSION = 1

# (stable scenario name, per-process runtime budget, exact unittest IDs)
SCENARIOS: tuple[tuple[str, int, tuple[str, ...]], ...] = (
    (
        "direct-only",
        30,
        (
            "tests.source_acquisition_e2e_test.SourceAcquisitionE2ETest."
            "test_local_source_sync_validates_publishes_rereads_and_becomes_unchanged",
            "tests.canonical_install_application_test.CanonicalInstallApplicationTest."
            "test_finalize_applies_reviewed_copy_and_pins_manifest_v2_evidence",
        ),
    ),
    (
        "public-company-team",
        30,
        (
            "tests.marketplace_e2e_test.MarketplaceE2ETest."
            "test_public_company_and_team_sources_compile_without_shadowing",
        ),
    ),
    (
        "native-reference",
        30,
        (
            "tests.native_promotion_test.NativePromotionTest."
            "test_native_promotion_writes_only_entry_lock_and_index",
        ),
    ),
    (
        "foreign-import",
        45,
        (
            "tests.legacy_importer_e2e_test.LegacyImporterE2ETest."
            "test_fixture_runs_through_stage_review_atomic_apply_and_noop",
        ),
    ),
    (
        "collision",
        30,
        (
            "tests.marketplace_e2e_test.MarketplaceE2ETest."
            "test_two_real_runtime_sources_preserve_collision_and_resolve_qualified_company_item",
        ),
    ),
    (
        "trust-downgrade",
        30,
        (
            "tests.canonical_setup_application_test.CanonicalSetupApplicationTest."
            "test_trust_downgrade_after_review_is_terminal_and_non_mutating",
        ),
    ),
    (
        "offline",
        30,
        (
            "tests.consumer_application_test.ConsumerApplicationTest."
            "test_offline_cached_install_and_lifecycle_actions_have_typed_feedback",
            "tests.source_sync_application_test.SourceSyncApplicationTest."
            "test_offline_mode_never_calls_git_and_requires_a_cached_snapshot",
        ),
    ),
    (
        "concurrent-sync-install",
        30,
        (
            "tests.install_concurrency_e2e_test.InstallConcurrencyE2ETest."
            "test_two_reviewed_installs_converge_without_lost_state_or_partial_payload",
            "tests.source_store_adapter_test.SourceStoreAdapterTest."
            "test_concurrent_identical_publications_converge_on_one_snapshot",
        ),
    ),
    (
        "corrupt-lock-object",
        30,
        (
            "tests.object_store_adapter_test.ObjectStoreAdapterTest."
            "test_concurrent_identical_publication_converges_and_corruption_repairs",
            "tests.registry_lock_test.RegistryLockTest."
            "test_stale_mismatched_or_self_referential_lock_never_resolves",
        ),
    ),
    (
        "setup-partial",
        30,
        (
            "tests.canonical_setup_application_test.CanonicalSetupApplicationTest."
            "test_queue_stop_retry_and_rollback_preserve_per_item_terminal_outcomes",
        ),
    ),
    (
        "security-provider-failure",
        30,
        (
            "tests.security_analyzer_protocol_test.SecurityAnalyzerProtocolTest."
            "test_timeout_crash_and_malformed_output_become_failed_attempts",
        ),
    ),
    (
        "reporting-absent",
        30,
        (
            "tests.reporting_application_test.ReportingApplicationTest."
            "test_disabled_without_destination_has_no_plan_or_provider_call",
            "tests.reporting_runtime_test.ReportingRuntimeTest."
            "test_missing_or_incoherent_registry_snapshot_fails_closed",
        ),
    ),
    (
        "migration-rollback",
        45,
        (
            "tests.migrate_cli_test.MigrateCliTest."
            "test_command_dry_run_apply_and_later_process_rollback_are_end_to_end",
        ),
    ),
)

ProcessRunner = Callable[
    [tuple[str, ...], Path, Mapping[str, str], int], subprocess.CompletedProcess[str]
]


def scenario_names() -> tuple[str, ...]:
    return tuple(name for name, _budget, _tests in SCENARIOS)


def validate_manifest() -> tuple[str, ...]:
    """Return stable configuration diagnostics without performing IO."""

    diagnostics: list[str] = []
    names = scenario_names()
    if len(set(names)) != len(names):
        diagnostics.append("system-matrix scenario names must be unique")
    for name, budget_seconds, test_ids in SCENARIOS:
        if not name or not isinstance(budget_seconds, int) or budget_seconds < 1:
            diagnostics.append(f"system-matrix scenario {name!r} has an invalid runtime budget")
        if not test_ids or len(set(test_ids)) != len(test_ids):
            diagnostics.append(f"system-matrix scenario {name!r} has invalid test IDs")
        if any(
            not test_id.startswith("tests.") or any(c.isspace() for c in test_id)
            for test_id in test_ids
        ):
            diagnostics.append(f"system-matrix scenario {name!r} has an unsafe test ID")
    return tuple(sorted(diagnostics))


def select_scenarios(
    selected: Sequence[str] = (),
) -> tuple[tuple[str, int, tuple[str, ...]], ...]:
    requested = tuple(selected)
    if len(set(requested)) != len(requested):
        raise ValueError("duplicate system-matrix scenario")
    known = {scenario[0]: scenario for scenario in SCENARIOS}
    unknown = tuple(name for name in requested if name not in known)
    if unknown:
        raise ValueError(f"unknown system-matrix scenario: {', '.join(unknown)}")
    if not requested:
        return SCENARIOS
    requested_set = set(requested)
    return tuple(scenario for scenario in SCENARIOS if scenario[0] in requested_set)


def _environment(scenario_root: Path) -> dict[str, str]:
    home = scenario_root / "home"
    temporary = scenario_root / "tmp"
    config = scenario_root / "xdg-config"
    data = scenario_root / "xdg-data"
    cache = scenario_root / "xdg-cache"
    for path in (home, temporary, config, data, cache):
        path.mkdir(parents=True)
    environment = {
        "PATH": os.environ.get("PATH", os.defpath),
        "HOME": str(home),
        "TMPDIR": str(temporary),
        "XDG_CONFIG_HOME": str(config),
        "XDG_DATA_HOME": str(data),
        "XDG_CACHE_HOME": str(cache),
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "GCM_INTERACTIVE": "never",
        "LC_ALL": "C",
        "LANG": "C",
        "TZ": "UTC",
        "HTTP_PROXY": "http://127.0.0.1:9",
        "HTTPS_PROXY": "http://127.0.0.1:9",
        "ALL_PROXY": "http://127.0.0.1:9",
        "NO_PROXY": "127.0.0.1,localhost",
    }
    for name in ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT"):
        if name in os.environ:
            environment[name] = os.environ[name]
    return environment


def _run_process(
    command: tuple[str, ...],
    cwd: Path,
    environment: Mapping[str, str],
    timeout_seconds: int,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=dict(environment),
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )


def _recovery_command(name: str) -> str:
    return f"python scripts/system_matrix.py --scenario {name} --json"


def _scenario_receipt(
    name: str,
    test_count: int,
    diagnostic_code: str | None,
) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "name": name,
        "status": "passed" if diagnostic_code is None else "failed",
        "test_count": test_count,
    }
    if diagnostic_code is not None:
        receipt["diagnostic_code"] = diagnostic_code
        receipt["recovery_command"] = _recovery_command(name)
    return receipt


def run_matrix(
    repository_root: Path = ROOT,
    *,
    selected: Sequence[str] = (),
    process_runner: ProcessRunner = _run_process,
    temporary_parent: Path | None = None,
) -> dict[str, Any]:
    """Execute isolated scenarios and return path/time/output-independent evidence."""

    diagnostics = validate_manifest()
    if diagnostics:
        raise ValueError("; ".join(diagnostics))
    scenarios = select_scenarios(selected)
    root = repository_root.resolve()
    receipts: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(
        prefix="aart-system-matrix-",
        dir=None if temporary_parent is None else str(temporary_parent),
    ) as raw:
        run_root = Path(raw)
        for name, budget_seconds, test_ids in scenarios:
            scenario_root = run_root / name
            environment = _environment(scenario_root)
            command = (PYTHON, "-m", "unittest", "-v", *test_ids)
            diagnostic_code: str | None = None
            try:
                completed = process_runner(command, root, environment, budget_seconds)
                if completed.returncode != 0:
                    diagnostic_code = "scenario-exit-nonzero"
            except subprocess.TimeoutExpired:
                diagnostic_code = "scenario-timeout"
            except OSError:
                diagnostic_code = "scenario-runner-failed"
            receipts.append(_scenario_receipt(name, len(test_ids), diagnostic_code))
    failed = sum(item["status"] == "failed" for item in receipts)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "passed" if failed == 0 else "failed",
        "scenario_count": len(receipts),
        "passed": len(receipts) - failed,
        "failed": failed,
        "scenarios": receipts,
        "recovery_commands": [
            item["recovery_command"] for item in receipts if item["status"] == "failed"
        ],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        action="append",
        choices=scenario_names(),
        default=[],
        help="run one named scenario; repeat to select more than one",
    )
    parser.add_argument("--json", action="store_true", help="print the canonical JSON receipt")
    parser.add_argument("--list", action="store_true", help="list scenario names without running")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.list:
        for name in scenario_names():
            print(name)
        return 0
    try:
        receipt = run_matrix(ROOT, selected=tuple(args.scenario))
    except ValueError as error:
        print(f"system matrix configuration error: {error}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    else:
        for scenario in receipt["scenarios"]:
            print(f"{scenario['name']}: {scenario['status']}")
            if scenario["status"] == "failed":
                print(f"  recovery: {scenario['recovery_command']}")
        print(
            f"system matrix {receipt['status']}: "
            f"{receipt['passed']}/{receipt['scenario_count']} scenarios passed"
        )
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
