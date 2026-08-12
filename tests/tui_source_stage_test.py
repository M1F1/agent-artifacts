"""TUI01: pure source-management, health, and wizard-stage contracts."""

from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest import mock

from agent_artifacts import tui
from agent_artifacts.application.source_management import (
    finalize_source_addition,
    finalize_source_management,
)
from agent_artifacts.configuration.model import (
    CompanyReviewedSource,
    ConfiguredSource,
    OrganizationPolicy,
    ReportingMode,
    ReportingPolicy,
    ReportingSettings,
    SourceKind,
    UserConfiguration,
    default_user_configuration,
)
from agent_artifacts.configuration.paths import Platform, resolve_config_paths
from agent_artifacts.configuration.schema import parse_user_configuration, user_configuration_bytes
from agent_artifacts.domain.diagnostics import Diagnostic, DiagnosticCode, Severity
from agent_artifacts.domain.identifiers import SourceAlias, SourceId
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.io.config_store import read_configuration
from agent_artifacts.sources.model import HealthStatus, SourceHealth
from agent_artifacts.tui_sources import (
    SourceAdditionRequest,
    SourceDisplayHealth,
    SourceManagementRequest,
    SourceOperation,
    SourceOperationKind,
    SourceSelection,
    SourceStageRow,
    build_source_stage,
    plan_source_addition,
    plan_source_management,
    render_source_stage,
)
from agent_artifacts.wizard import WizardInput, advance, back, initial_session, select, stages_for
from tests.marketplace_fixtures import source_state


def _source(
    alias: str,
    kind: SourceKind,
    location: str,
    *,
    enabled: bool,
) -> ConfiguredSource:
    return ConfiguredSource(
        SourceAlias(alias),
        kind,
        location,
        None if kind is SourceKind.SOURCE_LOCAL else "main",
        enabled,
    )


def _configuration(*sources: ConfiguredSource, default: str | None = None) -> UserConfiguration:
    baseline = default_user_configuration()
    return UserConfiguration(
        baseline.schema_version,
        sources,
        None if default is None else SourceAlias(default),
        baseline.sync,
        baseline.reporting,
    )


def _degraded(code: str, *, has_current: bool = False) -> SourceHealth:
    # The projection only needs a current value to distinguish an offline last-known-good. A
    # synthetic object is intentionally unnecessary for the no-current test cases below.
    if has_current:
        raise AssertionError("tests requiring current source use marketplace fixtures")
    return SourceHealth(
        HealthStatus.DEGRADED,
        None,
        None,
        (Diagnostic(DiagnosticCode(code), Severity.ERROR, code),),
    )


class SourceStageProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.company = _source(
            "company",
            SourceKind.REGISTRY_GIT,
            "https://github.example.com/platform/agent-registry.git",
            enabled=False,
        )
        self.public = _source(
            "public",
            SourceKind.SOURCE_GIT,
            "https://github.com/example/artifacts.git",
            enabled=True,
        )
        self.local = _source(
            "local-dev",
            SourceKind.SOURCE_LOCAL,
            "/workspace/artifacts",
            enabled=True,
        )

    def test_recommended_registry_direct_source_and_no_source_are_explicit(self) -> None:
        policy = OrganizationPolicy(
            1,
            recommended_sources=(SourceAlias("company"),),
        )
        view = build_source_stage(
            _configuration(self.company, self.public),
            policy,
            {
                SourceAlias("company"): SourceHealth(HealthStatus.MISSING, None, None),
                SourceAlias("public"): SourceHealth(HealthStatus.STALE, 901, None),
            },
            first_run=True,
        )

        self.assertIsInstance(view, Ok)
        rows = {row.source.alias.value: row for row in view.value.rows}
        self.assertTrue(rows["company"].recommended)
        self.assertEqual(rows["company"].source.kind, SourceKind.REGISTRY_GIT)
        self.assertEqual(rows["public"].source.kind, SourceKind.SOURCE_GIT)
        self.assertTrue(view.value.allow_no_source)
        rendered = "\n".join(render_source_stage(view.value))
        self.assertIn("organization recommended", rendered)
        self.assertIn("direct Git source", rendered)
        self.assertIn("Continue without sources", rendered)
        self.assertNotIn("company reviewed", rendered)

    def test_required_source_and_direct_source_policy_are_fail_closed(self) -> None:
        policy = OrganizationPolicy(
            1,
            required_sources=(SourceAlias("company"),),
            allow_direct_sources=False,
        )
        view = build_source_stage(
            _configuration(self.company, self.public),
            policy,
            {},
            first_run=True,
        )

        self.assertIsInstance(view, Ok)
        rows = {row.source.alias.value: row for row in view.value.rows}
        self.assertFalse(view.value.allow_no_source)
        self.assertTrue(rows["company"].required)
        self.assertFalse(rows["public"].selectable)
        self.assertIn("organization policy", rows["public"].reason)
        denied = plan_source_management(
            view.value,
            (SourceAlias("public"),),
            no_source=False,
        )
        self.assertIsInstance(denied, Err)

    def test_unconfigured_policy_aliases_are_visible_without_inventing_origins(self) -> None:
        view = build_source_stage(
            default_user_configuration(),
            OrganizationPolicy(1, recommended_sources=(SourceAlias("company"),)),
            {},
            first_run=True,
        )

        self.assertIsInstance(view, Ok)
        self.assertEqual(view.value.unconfigured_recommended, (SourceAlias("company"),))
        rendered = "\n".join(render_source_stage(view.value))
        self.assertIn("company", rendered)
        self.assertIn("still need configuration", rendered)

    def test_health_projection_distinguishes_all_required_ui_states(self) -> None:
        sources = tuple(
            _source(
                alias,
                SourceKind.SOURCE_LOCAL,
                f"/sources/{alias}",
                enabled=alias != "disabled",
            )
            for alias in ("current", "stale", "offline", "invalid", "incompatible", "disabled")
        )
        health = {
            SourceAlias("current"): SourceHealth(HealthStatus.HEALTHY, 4, None),
            SourceAlias("stale"): SourceHealth(HealthStatus.STALE, 999, None),
            SourceAlias("offline"): _degraded("source-unavailable"),
            SourceAlias("invalid"): _degraded("source-invalid"),
            SourceAlias("incompatible"): _degraded("source-incompatible"),
        }

        view = build_source_stage(
            _configuration(*sources),
            OrganizationPolicy(1),
            health,
        )

        self.assertIsInstance(view, Ok)
        statuses = {row.source.alias.value: row.health for row in view.value.rows}
        self.assertEqual(
            statuses,
            {
                "current": SourceDisplayHealth.CURRENT,
                "disabled": SourceDisplayHealth.DISABLED,
                "incompatible": SourceDisplayHealth.INCOMPATIBLE,
                "invalid": SourceDisplayHealth.INVALID,
                "offline": SourceDisplayHealth.OFFLINE,
                "stale": SourceDisplayHealth.STALE,
            },
        )
        rendered = "\n".join(render_source_stage(view.value))
        for label in ("current", "stale", "offline", "invalid", "incompatible", "disabled"):
            self.assertIn(f"health: {label}", rendered)


class SourceManagementPlanTests(unittest.TestCase):
    def test_first_use_adds_one_reviewed_registry_without_changing_existing_settings(self) -> None:
        baseline = default_user_configuration()
        view = build_source_stage(baseline, OrganizationPolicy(1), {}, first_run=True)
        self.assertIsInstance(view, Ok)
        registry = _source(
            "company",
            SourceKind.REGISTRY_GIT,
            "https://github.example.com/platform/agent-artifacts-registry.git",
            enabled=True,
        )

        planned = plan_source_addition(view.value, registry)

        self.assertIsInstance(planned, Ok)
        assert isinstance(planned, Ok)
        request = planned.value
        self.assertIsInstance(request, SourceAdditionRequest)
        self.assertEqual(request.before, baseline)
        self.assertEqual(request.after.sources, (registry,))
        self.assertEqual(request.after.default_registry, SourceAlias("company"))
        self.assertTrue(request.make_default)

    def test_source_addition_rejects_duplicate_alias_and_policy_denied_direct_source(self) -> None:
        registry = _source(
            "company",
            SourceKind.REGISTRY_GIT,
            "https://github.example.com/platform/agent-artifacts-registry.git",
            enabled=True,
        )
        populated = build_source_stage(_configuration(registry), OrganizationPolicy(1), {})
        self.assertIsInstance(populated, Ok)
        duplicate = plan_source_addition(populated.value, registry)
        self.assertIsInstance(duplicate, Err)

        empty = build_source_stage(
            default_user_configuration(),
            OrganizationPolicy(1, allow_direct_sources=False),
            {},
            first_run=True,
        )
        self.assertIsInstance(empty, Ok)
        direct = _source(
            "external",
            SourceKind.SOURCE_GIT,
            "https://github.com/example/artifacts.git",
            enabled=True,
        )
        denied = plan_source_addition(empty.value, direct)
        self.assertIsInstance(denied, Err)

        unsafe = ConfiguredSource(
            SourceAlias("unsafe"),
            SourceKind.SOURCE_GIT,
            "https://user:token@git.example/team/artifacts.git",
            "main",
            True,
        )
        neutral = build_source_stage(default_user_configuration(), OrganizationPolicy(1), {})
        self.assertIsInstance(neutral, Ok)
        self.assertIsInstance(plan_source_addition(neutral.value, unsafe), Err)

        local = _source("local", SourceKind.SOURCE_LOCAL, "/workspace/artifacts", enabled=True)
        local_view = build_source_stage(_configuration(local), OrganizationPolicy(1), {})
        self.assertIsInstance(local_view, Ok)
        duplicate_local = _source(
            "local-copy",
            SourceKind.SOURCE_LOCAL,
            "/workspace/artifacts",
            enabled=True,
        )
        self.assertIsInstance(plan_source_addition(local_view.value, duplicate_local), Err)

    def test_source_addition_rejects_the_same_git_origin_at_the_same_ref(self) -> None:
        main = _source(
            "company-main",
            SourceKind.REGISTRY_GIT,
            "https://github.example.com/platform/agent-artifacts-registry.git",
            enabled=True,
        )
        # Equivalent SCP spelling of the same origin, at the same ref: one mirror, one pointer.
        duplicate = ConfiguredSource(
            SourceAlias("company-duplicate"),
            SourceKind.REGISTRY_GIT,
            "git@GITHUB.example.com:platform/agent-artifacts-registry",
            "main",
            True,
        )
        view = build_source_stage(
            _configuration(main, default="company-main"), OrganizationPolicy(1), {}
        )
        self.assertIsInstance(view, Ok)

        duplicate_origin = plan_source_addition(view.value, duplicate, make_default=False)

        self.assertIsInstance(duplicate_origin, Err)
        assert isinstance(duplicate_origin, Err)
        self.assertIn(
            "origin and ref are already configured", duplicate_origin.diagnostics[0].message
        )

    def test_source_addition_accepts_another_ref_of_an_existing_git_origin(self) -> None:
        # SRC02: ref-aware storage makes this legitimate rather than a shared-pointer hazard.
        main = _source(
            "company-main",
            SourceKind.REGISTRY_GIT,
            "https://github.example.com/platform/agent-artifacts-registry.git",
            enabled=True,
        )
        release = ConfiguredSource(
            SourceAlias("company-release"),
            SourceKind.REGISTRY_GIT,
            "https://github.example.com/platform/agent-artifacts-registry.git",
            "release",
            True,
        )
        view = build_source_stage(
            _configuration(main, default="company-main"), OrganizationPolicy(1), {}
        )
        self.assertIsInstance(view, Ok)

        second_ref = plan_source_addition(view.value, release, make_default=False)

        self.assertIsInstance(second_ref, Ok)

    def test_registry_addition_can_preserve_an_existing_default(self) -> None:
        primary = _source(
            "primary",
            SourceKind.REGISTRY_GIT,
            "https://github.example.com/platform/primary-registry.git",
            enabled=True,
        )
        secondary = _source(
            "secondary",
            SourceKind.REGISTRY_GIT,
            "https://github.example.com/platform/secondary-registry.git",
            enabled=True,
        )
        view = build_source_stage(
            _configuration(primary, default="primary"),
            OrganizationPolicy(1),
            {},
        )
        self.assertIsInstance(view, Ok)

        planned = plan_source_addition(view.value, secondary, make_default=False)

        self.assertIsInstance(planned, Ok)
        assert isinstance(planned, Ok)
        self.assertEqual(planned.value.after.default_registry, SourceAlias("primary"))
        self.assertFalse(planned.value.make_default)

    def test_required_sources_can_be_added_one_at_a_time_but_not_selected_partially(self) -> None:
        policy = OrganizationPolicy(
            1,
            required_sources=(SourceAlias("company"), SourceAlias("team")),
        )
        company = _source(
            "company",
            SourceKind.REGISTRY_GIT,
            "https://github.example.com/platform/company-registry.git",
            enabled=True,
        )
        team = _source(
            "team",
            SourceKind.REGISTRY_GIT,
            "https://github.example.com/platform/team-registry.git",
            enabled=True,
        )
        initial = build_source_stage(default_user_configuration(), policy, {}, first_run=True)
        self.assertIsInstance(initial, Ok)

        first = plan_source_addition(initial.value, company)
        self.assertIsInstance(first, Ok)
        assert isinstance(first, Ok)
        partial_view = build_source_stage(first.value.after, policy, {})
        self.assertIsInstance(partial_view, Ok)
        self.assertIsInstance(
            plan_source_management(partial_view.value, (SourceAlias("company"),)),
            Err,
        )

        second = plan_source_addition(partial_view.value, team, make_default=False)
        self.assertIsInstance(second, Ok)
        assert isinstance(second, Ok)
        complete_view = build_source_stage(second.value.after, policy, {})
        self.assertIsInstance(complete_view, Ok)
        self.assertIsInstance(
            plan_source_management(
                complete_view.value,
                (SourceAlias("company"), SourceAlias("team")),
            ),
            Ok,
        )

    def test_enable_disable_and_default_are_one_deferred_immutable_request(self) -> None:
        company = _source(
            "company",
            SourceKind.REGISTRY_GIT,
            "https://github.com/platform/registry.git",
            enabled=False,
        )
        direct = _source(
            "direct",
            SourceKind.SOURCE_GIT,
            "https://github.com/example/artifacts.git",
            enabled=True,
        )
        view = build_source_stage(
            _configuration(company, direct),
            OrganizationPolicy(1, recommended_sources=(SourceAlias("company"),)),
            {},
        )
        self.assertIsInstance(view, Ok)

        planned = plan_source_management(
            view.value,
            (SourceAlias("company"),),
            default_registry=SourceAlias("company"),
        )

        self.assertIsInstance(planned, Ok)
        request = planned.value.request
        self.assertEqual(
            tuple(operation.kind for operation in request.operations),
            (
                SourceOperationKind.DISABLE,
                SourceOperationKind.ENABLE,
                SourceOperationKind.USE_DEFAULT,
            ),
        )
        self.assertTrue(next(s for s in request.after.sources if str(s.alias) == "company").enabled)
        self.assertFalse(next(s for s in request.after.sources if str(s.alias) == "direct").enabled)
        self.assertEqual(str(request.after.default_registry), "company")
        self.assertFalse(
            next(s for s in request.before.sources if str(s.alias) == "company").enabled
        )

        writes = []
        self.assertEqual(writes, [])
        finalized = finalize_source_management(
            request,
            lambda configuration, policy: writes.append((configuration, policy)) or Ok(object()),
        )
        self.assertIsInstance(finalized, Ok)
        self.assertTrue(finalized.value.changed)
        self.assertEqual(finalized.value.operation_count, 3)
        self.assertEqual(writes, [(request.after, request.policy)])

    def test_no_source_is_optional_unless_policy_requires_a_source(self) -> None:
        source = _source(
            "public",
            SourceKind.SOURCE_GIT,
            "https://github.com/example/artifacts.git",
            enabled=True,
        )
        optional = build_source_stage(
            _configuration(source),
            OrganizationPolicy(1),
            {},
        )
        self.assertIsInstance(optional, Ok)
        none = plan_source_management(optional.value, (), no_source=True)
        self.assertIsInstance(none, Ok)
        self.assertTrue(none.value.no_source)
        self.assertEqual(none.value.enabled_aliases, ())

        required = build_source_stage(
            _configuration(source),
            OrganizationPolicy(1, required_sources=(SourceAlias("public"),)),
            {},
        )
        self.assertIsInstance(required, Ok)
        denied = plan_source_management(required.value, (), no_source=True)
        self.assertIsInstance(denied, Err)

    def test_company_review_requires_exact_runtime_identity_not_alias_or_recommendation(
        self,
    ) -> None:
        # Missing current identity means the recommendation is visible but cannot be elevated to
        # company-reviewed merely because its alias matches organization policy.
        source = _source(
            "company",
            SourceKind.REGISTRY_GIT,
            "https://github.example.com/platform/registry.git",
            enabled=True,
        )
        policy = OrganizationPolicy(
            1,
            recommended_sources=(SourceAlias("company"),),
            company_reviewed_sources=(
                CompanyReviewedSource(
                    SourceId("company-registry"),
                    "github.example.com",
                    "platform/registry",
                ),
            ),
        )
        view = build_source_stage(_configuration(source), policy, {})

        self.assertIsInstance(view, Ok)
        self.assertTrue(view.value.rows[0].recommended)
        self.assertFalse(view.value.rows[0].company_reviewed)

        current = source_state(
            source,
            "company-registry",
            display_order=0,
        ).health
        verified = build_source_stage(
            _configuration(source),
            policy,
            {source.alias: current},
        )
        self.assertIsInstance(verified, Ok)
        self.assertTrue(verified.value.rows[0].company_reviewed)
        self.assertIn("company reviewed", "\n".join(render_source_stage(verified.value)))

    def test_selection_validation_rejects_ambiguous_unknown_and_policy_denied_choices(self) -> None:
        registry = _source(
            "registry",
            SourceKind.REGISTRY_GIT,
            "https://github.example.com/platform/registry.git",
            enabled=True,
        )
        direct = _source(
            "direct",
            SourceKind.SOURCE_GIT,
            "https://github.com/example/artifacts.git",
            enabled=False,
        )
        view = build_source_stage(
            _configuration(registry, direct, default="registry"),
            OrganizationPolicy(1, required_sources=(SourceAlias("registry"),)),
            {},
        )
        self.assertIsInstance(view, Ok)

        invalid = (
            plan_source_management(
                view.value,
                (SourceAlias("registry"), SourceAlias("registry")),
            ),
            plan_source_management(view.value, (SourceAlias("registry"),), no_source=True),
            plan_source_management(view.value, (), no_source=True),
            plan_source_management(view.value, ()),
            plan_source_management(view.value, (SourceAlias("unknown"),)),
            plan_source_management(view.value, (SourceAlias("direct"),)),
            plan_source_management(
                view.value,
                (SourceAlias("direct"),),
                default_registry=SourceAlias("direct"),
            ),
        )

        self.assertTrue(all(isinstance(result, Err) for result in invalid))

    def test_default_registry_is_preserved_or_cleared_by_selection(self) -> None:
        registry = _source(
            "registry",
            SourceKind.REGISTRY_GIT,
            "https://github.example.com/platform/registry.git",
            enabled=True,
        )
        local = _source("local", SourceKind.SOURCE_LOCAL, "/sources/local", enabled=True)
        view = build_source_stage(
            _configuration(registry, local, default="registry"),
            OrganizationPolicy(1),
            {},
        )
        self.assertIsInstance(view, Ok)

        preserved = plan_source_management(
            view.value,
            (SourceAlias("local"), SourceAlias("registry")),
        )
        cleared = plan_source_management(view.value, (SourceAlias("local"),))

        self.assertIsInstance(preserved, Ok)
        self.assertEqual(preserved.value.default_registry, SourceAlias("registry"))
        self.assertEqual(preserved.value.request.operations, ())
        self.assertIsInstance(cleared, Ok)
        self.assertEqual(
            cleared.value.request.operations,
            (
                SourceOperation(SourceOperationKind.DISABLE, SourceAlias("registry")),
                SourceOperation(SourceOperationKind.CLEAR_DEFAULT),
            ),
        )


class SourceValueInvariantTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = _source(
            "registry",
            SourceKind.REGISTRY_GIT,
            "https://github.example.com/platform/registry.git",
            enabled=True,
        )
        self.configuration = _configuration(self.registry, default="registry")
        projected = build_source_stage(self.configuration, OrganizationPolicy(1), {})
        assert isinstance(projected, Ok)
        self.view = projected.value
        planned = plan_source_management(self.view, (SourceAlias("registry"),))
        assert isinstance(planned, Ok)
        self.selection = planned.value

    def test_operation_and_row_invariants_reject_impossible_values(self) -> None:
        with self.assertRaises(ValueError):
            SourceOperation("enable", SourceAlias("registry"))  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            SourceOperation(SourceOperationKind.ENABLE)
        with self.assertRaises(ValueError):
            SourceOperation(SourceOperationKind.CLEAR_DEFAULT, SourceAlias("registry"))

        row = self.view.rows[0]
        with self.assertRaises(ValueError):
            replace(row, health="current")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            replace(row, selectable=True, reason="blocked")
        with self.assertRaises(ValueError):
            replace(row, selectable=False, reason="")

    def test_view_invariants_reject_mismatched_rows_and_policy_flags(self) -> None:
        row = self.view.rows[0]
        local = _source("local", SourceKind.SOURCE_LOCAL, "/sources/local", enabled=True)
        local_row = SourceStageRow(
            local,
            local.location,
            SourceDisplayHealth.MISSING,
            None,
            False,
            False,
            False,
            False,
            True,
        )
        with self.assertRaises(ValueError):
            replace(self.view, rows=(row, row))
        with self.assertRaises(ValueError):
            replace(self.view, rows=(local_row,))
        with self.assertRaises(ValueError):
            replace(self.view, allow_no_source=False)
        with self.assertRaises(ValueError):
            replace(self.view, allow_direct_sources=False)

    def test_request_invariants_reject_non_source_changes_and_mismatched_operations(self) -> None:
        with self.assertRaises(ValueError):
            SourceManagementRequest(  # type: ignore[arg-type]
                object(),
                self.configuration,
                OrganizationPolicy(1),
                (),
            )
        with self.assertRaises(ValueError):
            SourceManagementRequest(
                self.configuration,
                self.configuration,
                "policy",  # type: ignore[arg-type]
                (),
            )
        with self.assertRaises(ValueError):
            SourceManagementRequest(
                self.configuration,
                self.configuration,
                OrganizationPolicy(1),
                (SourceOperation(SourceOperationKind.ENABLE, SourceAlias("registry")),),
            )
        changed_reporting = replace(
            self.configuration,
            reporting=ReportingSettings(ReportingMode.PROMPT, SourceAlias("registry")),
        )
        with self.assertRaises(ValueError):
            SourceManagementRequest(
                self.configuration,
                changed_reporting,
                OrganizationPolicy(1),
                (),
            )
        changed_origin = replace(
            self.configuration,
            sources=(replace(self.registry, location="https://github.example.com/other/repo.git"),),
        )
        with self.assertRaises(ValueError):
            SourceManagementRequest(
                self.configuration,
                changed_origin,
                OrganizationPolicy(1),
                (),
            )

        # SRC02: identity is (kind, location, ref), so only an exact origin+ref repeat duplicates.
        duplicate_origin = ConfiguredSource(
            SourceAlias("another-registry"),
            self.registry.kind,
            self.registry.location,
            self.registry.ref,
            True,
        )
        with self.assertRaises(ValueError):
            SourceAdditionRequest(
                self.configuration,
                _configuration(self.registry, duplicate_origin, default="registry"),
                OrganizationPolicy(1),
                duplicate_origin,
                False,
            )

    def test_selection_invariants_reject_incoherent_review_state(self) -> None:
        request = self.selection.request
        snapshot = self.selection.health_snapshot
        cases = (
            ((SourceAlias("registry"), SourceAlias("registry")), None, False, request, snapshot),
            ((), None, False, request, snapshot),
            ((SourceAlias("registry"),), None, True, request, snapshot),
            ((SourceAlias("registry"),), SourceAlias("other"), False, request, snapshot),
            ((), None, True, request, snapshot),
            (
                (SourceAlias("registry"),),
                SourceAlias("registry"),
                False,
                request,
                snapshot + snapshot,
            ),
            ((SourceAlias("registry"),), SourceAlias("registry"), False, request, ()),
        )
        for values in cases:
            with self.subTest(values=values[:3]), self.assertRaises(ValueError):
                SourceSelection(*values)

    def test_projection_rejects_unknown_health_and_marks_invalid_git(self) -> None:
        unknown = build_source_stage(
            self.configuration,
            OrganizationPolicy(1),
            {SourceAlias("other"): SourceHealth(HealthStatus.MISSING, None, None)},
        )
        self.assertIsInstance(unknown, Err)

        invalid_git = _source(
            "invalid",
            SourceKind.SOURCE_GIT,
            "https://user:secret@github.com/example/artifacts.git",
            enabled=True,
        )
        invalid = build_source_stage(
            _configuration(invalid_git),
            OrganizationPolicy(1),
            {},
        )
        self.assertIsInstance(invalid, Ok)
        self.assertFalse(invalid.value.rows[0].selectable)
        self.assertEqual(invalid.value.rows[0].origin, "invalid Git origin")


class SourceManagementFinalizerTests(unittest.TestCase):
    def test_source_addition_saves_only_after_policy_revalidation(self) -> None:
        registry = _source(
            "company",
            SourceKind.REGISTRY_GIT,
            "https://github.example.com/platform/agent-artifacts-registry.git",
            enabled=True,
        )
        view = build_source_stage(default_user_configuration(), OrganizationPolicy(1), {})
        self.assertIsInstance(view, Ok)
        planned = plan_source_addition(view.value, registry)
        self.assertIsInstance(planned, Ok)
        writes = []

        finalized = finalize_source_addition(
            planned.value,
            lambda configuration, policy: writes.append((configuration, policy)) or Ok(object()),
        )

        self.assertIsInstance(finalized, Ok)
        self.assertEqual(writes, [(planned.value.after, planned.value.policy)])

        denied = SimpleNamespace(
            after=planned.value.after,
            policy=OrganizationPolicy(1, allowed_git_hosts=("internal.example",)),
        )
        rejected = finalize_source_addition(denied, mock.Mock())
        self.assertIsInstance(rejected, Err)

    def test_no_op_skips_save_and_changed_request_propagates_save_failure(self) -> None:
        registry = _source(
            "registry",
            SourceKind.REGISTRY_GIT,
            "https://github.example.com/platform/registry.git",
            enabled=True,
        )
        view = build_source_stage(
            _configuration(registry, default="registry"),
            OrganizationPolicy(1),
            {},
        )
        self.assertIsInstance(view, Ok)
        unchanged = plan_source_management(view.value, (SourceAlias("registry"),))
        self.assertIsInstance(unchanged, Ok)
        save = mock.Mock()

        finalized = finalize_source_management(unchanged.value.request, save)

        self.assertIsInstance(finalized, Ok)
        self.assertFalse(finalized.value.changed)
        save.assert_not_called()

        changed = plan_source_management(view.value, (), no_source=True)
        self.assertIsInstance(changed, Ok)
        failure = Err((Diagnostic(DiagnosticCode("save-failed"), Severity.ERROR, "save failed"),))
        saved = finalize_source_management(changed.value.request, lambda _config, _policy: failure)
        self.assertIs(saved, failure)

    def test_revalidation_rejects_policy_failure_and_saves_exact_user_value(self) -> None:
        configuration = default_user_configuration()
        denied = SimpleNamespace(
            after=configuration,
            policy=OrganizationPolicy(1, required_sources=(SourceAlias("required"),)),
            operations=(object(),),
        )
        save = mock.Mock()

        rejected = finalize_source_management(denied, save)

        self.assertIsInstance(rejected, Err)
        save.assert_not_called()

        registry = _source(
            "registry",
            SourceKind.REGISTRY_GIT,
            "https://github.example.com/platform/registry.git",
            enabled=True,
        )
        user = _configuration(registry, default="registry")
        policy_overlaid = SimpleNamespace(
            after=user,
            policy=OrganizationPolicy(
                1,
                reporting=ReportingPolicy(
                    ReportingMode.AUTOMATIC,
                    SourceAlias("registry"),
                ),
            ),
            operations=(object(),),
        )
        writes = []

        finalized = finalize_source_management(
            policy_overlaid,
            lambda configuration, policy: writes.append((configuration, policy)) or Ok(object()),
        )

        self.assertIsInstance(finalized, Ok)
        self.assertEqual(writes, [(user, policy_overlaid.policy)])


class SourceWizardStateTests(unittest.TestCase):
    def test_source_stage_precedes_harness_and_backspace_preserves_selection(self) -> None:
        source = _source(
            "public",
            SourceKind.SOURCE_GIT,
            "https://github.com/example/artifacts.git",
            enabled=True,
        )
        view = build_source_stage(_configuration(source), OrganizationPolicy(1), {})
        self.assertIsInstance(view, Ok)
        planned = plan_source_management(view.value, (SourceAlias("public"),))
        self.assertIsInstance(planned, Ok)

        session = advance(initial_session())
        session = select(session, "role", "user")
        session = advance(session)
        self.assertEqual(session.current, "source")
        session = select(session, "source", planned.value)
        session = advance(session)
        self.assertEqual(session.current, "profiles")
        self.assertEqual(stages_for(session)[2], "source")

        returned = back(session)
        self.assertEqual(returned.current, "source")
        self.assertEqual(returned.source_selection, planned.value)


class SourceFrontendTests(unittest.TestCase):
    def _view(self):
        company = _source(
            "company",
            SourceKind.SOURCE_GIT,
            "https://github.com/platform/registry.git",
            enabled=False,
        )
        direct = _source(
            "direct",
            SourceKind.SOURCE_GIT,
            "https://github.com/example/artifacts.git",
            enabled=True,
        )
        view = build_source_stage(
            _configuration(company, direct),
            OrganizationPolicy(1, recommended_sources=(SourceAlias("company"),)),
            {},
            first_run=True,
        )
        assert isinstance(view, Ok)
        return view.value

    def test_text_back_preserves_source_toggle_and_finalize_is_the_first_write(self) -> None:
        answers = iter(
            (
                "",
                "1",
                "1",
                "1",
                "status",
                "1",
                "back",
                "back",
                "back",
                "back",
                "",
                "",
                "status",
                "1",
                "y",
            )
        )
        events = []
        writes = []

        def read(_prompt=""):
            return next(answers)

        with mock.patch.object(
            tui,
            "_dispatch_result",
            side_effect=lambda request: (
                events.append(("dispatch", request.command))
                or tui.CommandOutcome(0, tui.ActionSummary(action=request.command))
            ),
        ):
            code = tui._run_text(
                read,
                writes.append,
                source_stage_view=self._view(),
                source_finalizer=lambda request: (
                    events.append(("save", tuple(item.kind.value for item in request.operations)))
                    or Ok(object())
                ),
            )

        self.assertEqual(code, 0)
        self.assertEqual(events[0][0], "save")
        self.assertEqual(events[1], ("dispatch", "status"))
        self.assertEqual(len(events), 2)
        rendered = "\n".join(writes)
        self.assertGreaterEqual(rendered.count("Stage: Sources"), 2)
        self.assertIn("organization recommended", rendered)
        self.assertIn("Sources: applied 2 reviewed configuration change", rendered)

    def test_text_can_exit_without_forcing_a_registry(self) -> None:
        baseline = default_user_configuration()
        empty = build_source_stage(baseline, OrganizationPolicy(1), {}, first_run=True)
        self.assertIsInstance(empty, Ok)
        answers = iter(("", "1", "1"))
        writes = []

        code = tui._run_text(
            lambda _prompt="": next(answers),
            writes.append,
            source_stage_view=empty.value,
        )

        self.assertEqual(code, 0)
        rendered = "\n".join(writes)
        self.assertIn("Enter 'a' to add a registry or compatible source", rendered)
        self.assertIn("no registry was forced", rendered)

    def test_text_first_use_can_add_sync_and_refresh_a_registry_source(self) -> None:
        empty = build_source_stage(default_user_configuration(), OrganizationPolicy(1), {})
        self.assertIsInstance(empty, Ok)
        registry = _source(
            "registry",
            SourceKind.REGISTRY_GIT,
            "https://github.example.com/platform/agent-artifacts-registry.git",
            enabled=True,
        )
        refreshed = build_source_stage(
            _configuration(registry, default="registry"), OrganizationPolicy(1), {}
        )
        self.assertIsInstance(refreshed, Ok)
        answers = iter(
            (
                "",  # how it works
                "1",  # user role
                "a",  # add source
                "1",  # registry kind
                "",  # default alias
                "https://github.example.com/platform/agent-artifacts-registry.git",
                "",  # default ref
                "y",  # explicit source setup review
                "q",  # quit from refreshed Sources stage
            )
        )
        writes = []
        additions = []

        code = tui._run_text(
            lambda _prompt="": next(answers),
            writes.append,
            source_stage_view=empty.value,
            source_addition_finalizer=lambda request: additions.append(request) or Ok(object()),
            source_stage_loader=lambda: Ok(
                tui._RuntimeSourceStage(refreshed.value, lambda _request: Ok(object()), None)
            ),
        )

        self.assertEqual(code, 0)
        self.assertEqual(len(additions), 1)
        self.assertEqual(additions[0].source, registry)
        rendered = "\n".join(writes)
        self.assertIn("Source setup review:", rendered)
        self.assertIn("Sources: synchronized and saved registry", rendered)
        self.assertNotIn("bundled-legacy", rendered)

    def test_curses_unavailable_fallback_keeps_source_onboarding_runtime(self) -> None:
        empty = build_source_stage(default_user_configuration(), OrganizationPolicy(1), {})
        self.assertIsInstance(empty, Ok)

        def finalize_selection(_request):
            return Ok(object())

        def finalize_addition(_request):
            return Ok(object())

        runtime = tui._RuntimeSourceStage(
            empty.value,
            finalize_selection,
            finalize_addition,
        )
        with (
            mock.patch.object(tui, "_runtime_source_stage_context", return_value=Ok(runtime)),
            mock.patch.object(tui.sys.stdin, "isatty", return_value=True),
            mock.patch.object(tui.sys.stdout, "isatty", return_value=True),
            mock.patch.object(
                tui, "_run_curses", side_effect=tui.CursesUnavailable("curses unavailable")
            ),
            mock.patch.object(tui, "_run_text", return_value=0) as fallback,
        ):
            code = tui.run(user_home="/tmp/aart-home")

        self.assertEqual(code, 0)
        self.assertIs(fallback.call_args.kwargs["source_addition_finalizer"], finalize_addition)
        self.assertTrue(callable(fallback.call_args.kwargs["source_stage_loader"]))

    def test_failure_after_source_addition_propagates_with_the_refreshed_view(self) -> None:
        empty = build_source_stage(default_user_configuration(), OrganizationPolicy(1), {})
        self.assertIsInstance(empty, Ok)
        assert isinstance(empty, Ok)
        source = _source(
            "registry",
            SourceKind.REGISTRY_GIT,
            "https://github.example.com/platform/agent-artifacts-registry.git",
            enabled=True,
        )
        added = plan_source_addition(empty.value, source)
        self.assertIsInstance(added, Ok)
        assert isinstance(added, Ok)
        refreshed = build_source_stage(
            _configuration(source, default="registry"), OrganizationPolicy(1), {}
        )
        self.assertIsInstance(refreshed, Ok)
        assert isinstance(refreshed, Ok)

        class _Screen:
            def clear(self) -> None:
                return None

            def addstr(self, _row: int, _column: int, _line: str) -> None:
                return None

            def refresh(self) -> None:
                return None

        def wrapper(callback) -> None:
            callback(_Screen())

        fake_curses = SimpleNamespace(curs_set=lambda _value: None, wrapper=wrapper)
        refreshed_runtime = tui._RuntimeSourceStage(
            refreshed.value,
            lambda _request: Ok(object()),
            lambda _request: Ok(object()),
        )
        with (
            mock.patch.dict(sys.modules, {"curses": fake_curses}),
            mock.patch.object(tui, "load_profiles", return_value=(object(),)),
            mock.patch.object(tui, "_curses_onboarding", return_value=WizardInput("confirm")),
            mock.patch.object(
                tui,
                "_curses_single_event",
                return_value=WizardInput("confirm", (0,)),
            ),
            mock.patch.object(
                tui,
                "_curses_source_event",
                side_effect=(
                    (WizardInput("add"), None, None),
                    RuntimeError("terminal failed after source refresh"),
                ),
            ) as source_event,
            mock.patch.object(tui, "_curses_source_addition", return_value=added.value),
            mock.patch.object(tui, "_curses_notice"),
            mock.patch.object(tui, "_run_text", return_value=0) as fallback,
        ):
            with self.assertRaises(RuntimeError):
                tui._run_curses(
                    source_stage_view=empty.value,
                    source_finalizer=lambda _request: Ok(object()),
                    source_addition_finalizer=lambda _request: Ok(object()),
                    source_stage_loader=lambda: Ok(refreshed_runtime),
                )

        # The addition still refreshes the view the wizard keeps working with, but a failure this
        # late is a defect: it propagates instead of silently restarting the wizard in text mode.
        self.assertIs(source_event.call_args_list[1].args[3], refreshed.value)
        fallback.assert_not_called()

    def test_curses_back_event_keeps_the_same_source_selection(self) -> None:
        view = self._view()
        planned = plan_source_management(view, (SourceAlias("company"),))
        self.assertIsInstance(planned, Ok)
        session = advance(initial_session())
        session = select(session, "role", "user")
        session = advance(session)
        session = select(session, "source", planned.value)

        with mock.patch.object(
            tui,
            "_curses_multi_event",
            return_value=WizardInput("back", cursor=1, scroll=1),
        ) as multi:
            event, selected, error = tui._curses_source_event(
                object(),
                object(),
                session,
                view,
            )

        self.assertEqual(event.kind, "back")
        self.assertIsNone(selected)
        self.assertIsNone(error)
        self.assertEqual(session.source_selection, planned.value)
        self.assertEqual(multi.call_args.kwargs["selected"], (0,))

    def test_curses_sources_exposes_add_action_without_mutating_selection(self) -> None:
        view = self._view()
        session = advance(initial_session())
        session = select(session, "role", "user")
        session = advance(session)

        with mock.patch.object(
            tui,
            "_curses_multi_event",
            return_value=WizardInput("add", cursor=0, scroll=0),
        ) as multi:
            event, selected, error = tui._curses_source_event(
                object(),
                object(),
                session,
                view,
            )

        self.assertEqual(event.kind, "add")
        self.assertIsNone(selected)
        self.assertIsNone(error)
        self.assertTrue(multi.call_args.kwargs["allow_add"])

    def test_curses_empty_required_sources_keeps_add_navigation_available(self) -> None:
        view = build_source_stage(
            default_user_configuration(),
            OrganizationPolicy(1, required_sources=(SourceAlias("company"),)),
            {},
            first_run=True,
        )
        self.assertIsInstance(view, Ok)
        assert isinstance(view, Ok)
        self.assertEqual(view.value.rows, ())
        self.assertFalse(view.value.allow_no_source)
        session = advance(initial_session())
        session = select(session, "role", "user")
        session = advance(session)

        class _Screen:
            def __init__(self) -> None:
                self.lines: list[str] = []

            def clear(self) -> None:
                return None

            def addstr(self, _row: int, _column: int, line: str) -> None:
                self.lines.append(line)

            def refresh(self) -> None:
                return None

            def getch(self) -> int:
                return ord("a")

            def getmaxyx(self) -> tuple[int, int]:
                return (24, 100)

        curses = SimpleNamespace(KEY_BACKSPACE=263)
        screen = _Screen()
        event, selected, error = tui._curses_source_event(curses, screen, session, view.value)

        self.assertEqual(event.kind, "add")
        self.assertIsNone(selected)
        self.assertIsNone(error)
        self.assertIn("No sources are configured.", screen.lines)
        self.assertIn("Press a to add a source", " ".join(screen.lines))

    def test_curses_source_addition_shows_parser_diagnostic_before_returning(self) -> None:
        view = build_source_stage(default_user_configuration(), OrganizationPolicy(1), {})
        self.assertIsInstance(view, Ok)
        session = advance(initial_session())
        session = select(session, "role", "user")
        session = advance(session)
        with (
            mock.patch.object(
                tui,
                "_curses_single_event",
                return_value=WizardInput("confirm", (0,)),
            ),
            mock.patch.object(
                tui,
                "_curses_text_input",
                side_effect=(
                    "Not a slug",
                    "https://github.example.com/platform/registry.git",
                    "main",
                ),
            ),
            mock.patch.object(tui, "_curses_notice") as notice,
        ):
            result = tui._curses_source_addition(object(), object(), session, view.value)

        self.assertIsInstance(result, WizardInput)
        assert isinstance(result, WizardInput)
        self.assertEqual(result.kind, "back")
        self.assertEqual(notice.call_args.args[2], "Source setup error")
        self.assertIn("lowercase slug", " ".join(notice.call_args.args[3]))


class RuntimeSourceContextTests(unittest.TestCase):
    def _context(self, home: pathlib.Path, paths, *, policy: bytes | None = None):
        xdg_defaults = {
            "XDG_CONFIG_HOME": str(home / ".config"),
            "XDG_DATA_HOME": str(home / ".local" / "share"),
            "XDG_CACHE_HOME": str(home / ".cache"),
        }
        with (
            mock.patch.dict(os.environ, xdg_defaults),
            mock.patch(
                "agent_artifacts.io.config_store.read_configuration",
                side_effect=lambda request: (
                    Ok(policy) if request.path == paths.policy_file else read_configuration(request)
                ),
            ),
        ):
            return tui._runtime_source_stage_context(
                source_dir=None,
                repo=None,
                user_home=str(home),
            )

    def test_fresh_runtime_requires_explicit_source_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = pathlib.Path(temporary).resolve()
            platform = Platform.DARWIN if sys.platform == "darwin" else Platform.LINUX
            paths = resolve_config_paths(platform, home=str(home))

            context = self._context(home, paths)

        self.assertIsInstance(context, Ok)
        runtime = context.value
        view, finalizer = runtime.view, runtime.source_finalizer
        self.assertEqual(view.rows, ())
        self.assertTrue(view.allow_no_source)
        self.assertIsNotNone(finalizer)
        self.assertIsNotNone(runtime.source_addition_finalizer)
        self.assertFalse(pathlib.Path(paths.user_config_file).exists())

    def test_first_use_source_addition_syncs_before_persisting_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = pathlib.Path(temporary).resolve()
            platform = Platform.DARWIN if sys.platform == "darwin" else Platform.LINUX
            paths = resolve_config_paths(platform, home=str(home))
            context = self._context(home, paths)
            self.assertIsInstance(context, Ok)
            runtime = context.value
            source = _source(
                "local-fixture",
                SourceKind.SOURCE_LOCAL,
                str(
                    (
                        pathlib.Path(__file__).parent / "fixtures" / "protocol" / "native-source-v1"
                    ).resolve()
                ),
                enabled=True,
            )
            planned = plan_source_addition(runtime.view, source)
            self.assertIsInstance(planned, Ok)
            assert runtime.source_addition_finalizer is not None
            with mock.patch(
                "agent_artifacts.sources.runtime.sync_configured_source",
                return_value=Ok(object()),
            ) as synchronized:
                finalized = runtime.source_addition_finalizer(planned.value)

            self.assertIsInstance(finalized, Ok)
            synchronized.assert_called_once_with(source, data_root=paths.data_root)
            persisted = parse_user_configuration(pathlib.Path(paths.user_config_file).read_bytes())
            self.assertIsInstance(persisted, Ok)
            assert isinstance(persisted, Ok)
            self.assertEqual(persisted.value.sources, (source,))

    def test_failed_first_use_sync_does_not_create_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = pathlib.Path(temporary).resolve()
            platform = Platform.DARWIN if sys.platform == "darwin" else Platform.LINUX
            paths = resolve_config_paths(platform, home=str(home))
            context = self._context(home, paths)
            self.assertIsInstance(context, Ok)
            runtime = context.value
            source = _source(
                "local-fixture",
                SourceKind.SOURCE_LOCAL,
                str(
                    (
                        pathlib.Path(__file__).parent / "fixtures" / "protocol" / "native-source-v1"
                    ).resolve()
                ),
                enabled=True,
            )
            planned = plan_source_addition(runtime.view, source)
            self.assertIsInstance(planned, Ok)
            failure = Err(
                (
                    Diagnostic(
                        DiagnosticCode("source-unavailable"), Severity.ERROR, "source unavailable"
                    ),
                )
            )
            assert runtime.source_addition_finalizer is not None
            with mock.patch(
                "agent_artifacts.sources.runtime.sync_configured_source",
                return_value=failure,
            ):
                finalized = runtime.source_addition_finalizer(planned.value)

            self.assertIs(finalized, failure)
            self.assertFalse(pathlib.Path(paths.user_config_file).exists())

    def test_source_addition_never_overwrites_a_corrupt_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = pathlib.Path(temporary).resolve()
            platform = Platform.DARWIN if sys.platform == "darwin" else Platform.LINUX
            paths = resolve_config_paths(platform, home=str(home))
            config_path = pathlib.Path(paths.user_config_file)
            config_path.parent.mkdir(parents=True)
            corrupt = b'{"schema_version":"not-an-integer"}'
            config_path.write_bytes(corrupt)
            context = self._context(home, paths)
            self.assertIsInstance(context, Ok)
            runtime = context.value
            source = _source(
                "local-fixture",
                SourceKind.SOURCE_LOCAL,
                str(
                    (
                        pathlib.Path(__file__).parent / "fixtures" / "protocol" / "native-source-v1"
                    ).resolve()
                ),
                enabled=True,
            )
            planned = plan_source_addition(runtime.view, source)
            self.assertIsInstance(planned, Ok)
            assert runtime.source_addition_finalizer is not None
            with mock.patch(
                "agent_artifacts.sources.runtime.sync_configured_source"
            ) as synchronized:
                finalized = runtime.source_addition_finalizer(planned.value)

            self.assertIsInstance(finalized, Err)
            synchronized.assert_not_called()
            self.assertIn("recover it", finalized.diagnostics[0].message)
            self.assertEqual(config_path.read_bytes(), corrupt)

    def test_configured_sources_and_health_are_loaded_without_mutation_then_saved_on_finalize(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = pathlib.Path(temporary).resolve()
            platform = Platform.DARWIN if sys.platform == "darwin" else Platform.LINUX
            paths = resolve_config_paths(platform, home=str(home))
            first = _source(
                "first",
                SourceKind.SOURCE_LOCAL,
                str(home / "first"),
                enabled=True,
            )
            second = _source(
                "second",
                SourceKind.SOURCE_LOCAL,
                str(home / "second"),
                enabled=False,
            )
            original = user_configuration_bytes(_configuration(first, second))
            config_path = pathlib.Path(paths.user_config_file)
            config_path.parent.mkdir(parents=True)
            config_path.write_bytes(original)

            context = self._context(home, paths)

            self.assertIsInstance(context, Ok)
            runtime = context.value
            view, finalizer = runtime.view, runtime.source_finalizer
            self.assertIsNotNone(finalizer)
            self.assertEqual(config_path.read_bytes(), original)
            self.assertEqual(
                {row.source.alias.value: row.health for row in view.rows},
                {
                    "first": SourceDisplayHealth.MISSING,
                    "second": SourceDisplayHealth.DISABLED,
                },
            )
            planned = plan_source_management(view, (SourceAlias("second"),))
            self.assertIsInstance(planned, Ok)
            self.assertEqual(config_path.read_bytes(), original)
            assert finalizer is not None
            finalized = finalizer(planned.value.request)
            self.assertIsInstance(finalized, Ok)
            parsed = parse_user_configuration(config_path.read_bytes())
            self.assertIsInstance(parsed, Ok)
            enabled = {source.alias.value: source.enabled for source in parsed.value.sources}
            self.assertEqual(enabled, {"first": False, "second": True})

    def test_policy_overlay_is_validated_but_not_persisted_as_user_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = pathlib.Path(temporary).resolve()
            platform = Platform.DARWIN if sys.platform == "darwin" else Platform.LINUX
            paths = resolve_config_paths(platform, home=str(home))
            registry = _source(
                "registry",
                SourceKind.REGISTRY_GIT,
                "https://github.example.com/platform/registry.git",
                enabled=True,
            )
            local = _source(
                "local",
                SourceKind.SOURCE_LOCAL,
                str(home / "local"),
                enabled=False,
            )
            raw_user = _configuration(registry, local, default="registry")
            config_path = pathlib.Path(paths.user_config_file)
            config_path.parent.mkdir(parents=True)
            config_path.write_bytes(user_configuration_bytes(raw_user))
            policy = (
                b'{"schema_version":1,"reporting":{"mode":"automatic","destination":"registry"}}'
            )

            context = self._context(home, paths, policy=policy)

            self.assertIsInstance(context, Ok)
            runtime = context.value
            view, finalizer = runtime.view, runtime.source_finalizer
            self.assertEqual(view.configuration.reporting.mode, ReportingMode.PROMPT)
            planned = plan_source_management(
                view,
                (SourceAlias("local"), SourceAlias("registry")),
            )
            self.assertIsInstance(planned, Ok)
            self.assertEqual(planned.value.request.after.reporting.mode, ReportingMode.PROMPT)
            assert finalizer is not None
            finalized = finalizer(planned.value.request)
            self.assertIsInstance(finalized, Ok)
            persisted = parse_user_configuration(config_path.read_bytes())
            self.assertIsInstance(persisted, Ok)
            self.assertEqual(persisted.value.reporting.mode, ReportingMode.PROMPT)
            self.assertIsNone(persisted.value.reporting.destination)

    def test_finalize_rejects_configuration_changed_after_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = pathlib.Path(temporary).resolve()
            platform = Platform.DARWIN if sys.platform == "darwin" else Platform.LINUX
            paths = resolve_config_paths(platform, home=str(home))
            first = _source(
                "first",
                SourceKind.SOURCE_LOCAL,
                str(home / "first"),
                enabled=True,
            )
            second = _source(
                "second",
                SourceKind.SOURCE_LOCAL,
                str(home / "second"),
                enabled=False,
            )
            config_path = pathlib.Path(paths.user_config_file)
            config_path.parent.mkdir(parents=True)
            config_path.write_bytes(user_configuration_bytes(_configuration(first, second)))
            context = self._context(home, paths)
            self.assertIsInstance(context, Ok)
            runtime = context.value
            view, finalizer = runtime.view, runtime.source_finalizer
            planned = plan_source_management(view, (SourceAlias("second"),))
            self.assertIsInstance(planned, Ok)
            drifted = _configuration(
                replace(first, enabled=False),
                replace(second, enabled=True),
            )
            drifted_bytes = user_configuration_bytes(drifted)
            config_path.write_bytes(drifted_bytes)
            assert finalizer is not None

            finalized = finalizer(planned.value.request)

            self.assertIsInstance(finalized, Err)
            self.assertIn("changed after Review", finalized.diagnostics[0].message)
            self.assertEqual(config_path.read_bytes(), drifted_bytes)


if __name__ == "__main__":
    unittest.main()
