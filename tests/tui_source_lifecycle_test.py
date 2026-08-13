"""SL-1/SL-6: synchronizing and removing a source from both human front-ends.

The dead end this covers is concrete: a subscribed origin whose managed snapshot no longer
matches what the origin declares refuses every read path, and before these operations existed the
only way out was hand-editing configuration and deleting cache directories.  The interface now
owns both halves — refresh the snapshot, or end the subscription — and both front-ends dispatch
exactly the requests the CLI does.
"""

from __future__ import annotations

import curses
import unittest

from agent_artifacts import tui
from agent_artifacts.configuration.model import (
    ConfiguredSource,
    OrganizationPolicy,
    SourceKind,
    UserConfiguration,
    default_user_configuration,
)
from agent_artifacts.domain.identifiers import SourceAlias, SourceId
from agent_artifacts.domain.result import Err, Ok
from agent_artifacts.protocol.native_tree import (
    SnapshotEntry,
    SnapshotEntryKind,
    SnapshotOrigin,
    SourceSnapshot,
)
from agent_artifacts.protocol.paths import parse_relative_path
from agent_artifacts.sources.model import (
    CurrentSource,
    SourceSyncOutcome,
    SyncDisposition,
    make_source_candidate,
    source_instance_id,
)
from agent_artifacts.tui_layout import CONTENT_MEASURE
from agent_artifacts.tui_sources import (
    build_source_stage,
    plan_source_removal,
    render_source_removal_review,
    render_source_sync_outcome,
    render_source_sync_review,
)
from tests.tui_wizard_curses_test import Screen


def _unwrap(result):
    assert isinstance(result, Ok), result
    return result.value


def _registry(alias: str = "registry") -> ConfiguredSource:
    return ConfiguredSource(
        SourceAlias(alias),
        SourceKind.REGISTRY_GIT,
        f"https://git.example.test/team/{alias}.git",
        "main",
        True,
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


def _view(configuration: UserConfiguration, policy: OrganizationPolicy | None = None):
    return _unwrap(
        build_source_stage(
            configuration,
            policy or OrganizationPolicy(1),
            {},
            first_run=False,
        )
    )


def _outcome(
    source: ConfiguredSource,
    disposition: SyncDisposition = SyncDisposition.PUBLISHED,
) -> SourceSyncOutcome:
    snapshot = SourceSnapshot(
        SnapshotOrigin.IMMUTABLE_GIT,
        (
            SnapshotEntry(
                _unwrap(parse_relative_path("file.txt")),
                SnapshotEntryKind.FILE,
                b"content",
            ),
        ),
    )
    candidate = _unwrap(
        make_source_candidate(
            source_instance_id(source),
            source.alias,
            "a" * 40,
            snapshot,
        )
    )
    return SourceSyncOutcome(
        disposition,
        CurrentSource(candidate, SourceId("team-registry"), 100, "/managed/snapshot"),
    )


def _scripted(answers):
    values = iter(answers)

    def read(_prompt=""):
        try:
            return next(values)
        except StopIteration:
            raise EOFError from None

    return read


class SourceLifecyclePlanningTests(unittest.TestCase):
    """The planner and its review text are pure, and the CLI and TUI share both."""

    def test_removal_clears_a_default_registry_it_owned_and_keeps_the_others(self) -> None:
        keep = _registry("keep")
        drop = _registry("drop")
        view = _view(_configuration(keep, drop, default="drop"))

        planned = _unwrap(plan_source_removal(view, SourceAlias("drop")))

        self.assertTrue(planned.cleared_default)
        self.assertEqual(planned.after.sources, (keep,))
        self.assertIsNone(planned.after.default_registry)

    def test_removal_keeps_a_default_registry_owned_by_another_source(self) -> None:
        keep = _registry("keep")
        drop = _registry("drop")
        view = _view(_configuration(keep, drop, default="keep"))

        planned = _unwrap(plan_source_removal(view, SourceAlias("drop")))

        self.assertFalse(planned.cleared_default)
        self.assertEqual(planned.after.default_registry, SourceAlias("keep"))

    def test_an_organization_required_alias_cannot_be_unsubscribed(self) -> None:
        required = _registry("company")
        policy = OrganizationPolicy(1, required_sources=(SourceAlias("company"),))
        view = _view(_configuration(required, default="company"), policy)

        refused = plan_source_removal(view, SourceAlias("company"))

        self.assertIsInstance(refused, Err)
        assert isinstance(refused, Err)
        self.assertIn("policy owner", refused.diagnostics[0].remediation[0])

    def test_an_unconfigured_alias_is_refused_by_naming_the_listing_command(self) -> None:
        view = _view(_configuration(_registry()))

        refused = plan_source_removal(view, SourceAlias("absent"))

        self.assertIsInstance(refused, Err)
        assert isinstance(refused, Err)
        self.assertIn("aart source list", refused.diagnostics[0].remediation[0])

    def test_the_removal_review_promises_installed_artifacts_are_kept(self) -> None:
        view = _view(_configuration(_registry(), default="registry"))
        planned = _unwrap(plan_source_removal(view, SourceAlias("registry")))

        review = "\n".join(render_source_removal_review(planned))

        self.assertIn("delete its managed snapshot", review)
        self.assertIn("keeps: every installed artifact", review)
        self.assertIn("clear the default registry", review)

    def test_the_sync_review_separates_availability_from_installed_files(self) -> None:
        view = _view(_configuration(_registry()))

        review = "\n".join(render_source_sync_review(view.rows[0]))

        self.assertIn("registry", review)
        self.assertIn("become installable", review)
        self.assertIn("keeps: every installed artifact", review)

    def test_the_three_sync_results_are_distinguishable_in_words(self) -> None:
        source = _registry()
        published = render_source_sync_outcome(source.alias, _outcome(source))
        unchanged = render_source_sync_outcome(
            source.alias, _outcome(source, SyncDisposition.UNCHANGED)
        )
        retained = render_source_sync_outcome(
            source.alias, _outcome(source, SyncDisposition.RETAINED)
        )

        self.assertIn("snapshot updated", published[0])
        self.assertIn("already current", unchanged[0])
        self.assertIn("keeping the last good snapshot", retained[0])


class _Runtime:
    """The imperative source boundary, recorded so both front-ends can be held to it."""

    def __init__(self, view, *, sync=None, removal=None):
        self.view = view
        self.sync_result = sync
        self.removal_result = removal if removal is not None else Ok(object())
        self.synced: list[SourceAlias] = []
        self.removed: list[str] = []
        self.reloads = 0

    def run_sync(self, alias):
        self.synced.append(alias)
        return self.sync_result

    def finalize_removal(self, request):
        self.removed.append(request.source.alias.value)
        if isinstance(self.removal_result, Ok):
            self.view = _view(request.after)
        return self.removal_result

    def load(self):
        self.reloads += 1
        return Ok(
            tui._RuntimeSourceStage(
                self.view,
                lambda _request: Ok(object()),
                lambda _request: Ok(object()),
                self.finalize_removal,
                self.run_sync,
            )
        )


class SourceLifecycleTextTests(unittest.TestCase):
    """The text front-end reaches both operations from the Sources stage."""

    def _run(self, runtime, answers) -> tuple[int, str]:
        writes: list[str] = []
        code = tui._run_text(
            _scripted(answers),
            writes.append,
            source_stage_view=runtime.view,
            source_removal_finalizer=runtime.finalize_removal,
            source_sync_runner=runtime.run_sync,
            source_stage_loader=runtime.load,
        )
        return code, "\n".join(writes)

    def test_the_sources_prompt_offers_sync_and_remove_when_a_source_exists(self) -> None:
        runtime = _Runtime(_view(_configuration(_registry())))

        _code, rendered = self._run(runtime, ["", "1", "q"])

        self.assertIn(
            "Enter 's' to synchronize a configured source, or 'r' to remove one", rendered
        )

    def test_an_empty_sources_stage_offers_only_add(self) -> None:
        runtime = _Runtime(_view(_configuration()))

        _code, rendered = self._run(runtime, ["", "1", "q"])

        self.assertNotIn("s=sync", rendered)
        self.assertIn("Enter 'a' to add a registry", rendered)

    def test_sync_reviews_then_dispatches_and_reports_the_new_snapshot(self) -> None:
        source = _registry()
        runtime = _Runtime(_view(_configuration(source)), sync=Ok(_outcome(source)))

        code, rendered = self._run(runtime, ["", "1", "s", "1", "y", "q"])

        self.assertEqual(code, 0)
        self.assertEqual(runtime.synced, [source.alias])
        self.assertIn("Source sync review:", rendered)
        self.assertIn("snapshot updated", rendered)
        self.assertEqual(runtime.reloads, 1)

    def test_declining_the_sync_review_dispatches_nothing(self) -> None:
        source = _registry()
        runtime = _Runtime(_view(_configuration(source)), sync=Ok(_outcome(source)))

        _code, rendered = self._run(runtime, ["", "1", "s", "1", "n", "q"])

        self.assertEqual(runtime.synced, [])
        self.assertIn("Source was not synchronized", rendered)

    def test_a_failed_sync_says_the_snapshot_is_unchanged_and_keeps_the_stage(self) -> None:
        source = _registry()
        failure = Err(
            (
                tui.Diagnostic(
                    tui.DiagnosticCode("source-unavailable"),
                    tui.Severity.ERROR,
                    "origin is unreachable",
                ),
            )
        )
        runtime = _Runtime(_view(_configuration(source)), sync=failure)

        _code, rendered = self._run(runtime, ["", "1", "s", "registry", "y", "q"])

        self.assertEqual(runtime.synced, [source.alias])
        self.assertIn("source-unavailable", rendered)
        self.assertIn("its snapshot is unchanged", rendered)
        self.assertIn("r removes this source", rendered)
        self.assertEqual(runtime.reloads, 0)

    def test_remove_reviews_then_finalizes_and_the_row_is_gone_afterwards(self) -> None:
        source = _registry()
        runtime = _Runtime(_view(_configuration(source, default="registry")))

        code, rendered = self._run(runtime, ["", "1", "r", "1", "y", "q"])

        self.assertEqual(code, 0)
        self.assertEqual(runtime.removed, ["registry"])
        self.assertIn("Source removal review:", rendered)
        self.assertIn("removed registry and deleted its snapshot", rendered)
        self.assertIn("the default registry was cleared", rendered)
        self.assertEqual(runtime.view.rows, ())

    def test_declining_the_removal_review_finalizes_nothing(self) -> None:
        runtime = _Runtime(_view(_configuration(_registry())))

        _code, rendered = self._run(runtime, ["", "1", "r", "1", "n", "q"])

        self.assertEqual(runtime.removed, [])
        self.assertIn("Source was not removed; nothing was deleted.", rendered)

    def test_a_refused_removal_reports_the_diagnostic_and_keeps_the_source(self) -> None:
        failure = Err(
            (
                tui.Diagnostic(
                    tui.DiagnosticCode("source-locked"),
                    tui.Severity.ERROR,
                    "another aart process holds the source lock",
                ),
            )
        )
        runtime = _Runtime(_view(_configuration(_registry())), removal=failure)

        _code, rendered = self._run(runtime, ["", "1", "r", "1", "y", "q"])

        self.assertEqual(runtime.removed, ["registry"])
        self.assertIn("source-locked", rendered)
        self.assertIn("registry was not removed.", rendered)
        self.assertEqual(len(runtime.view.rows), 1)

    def test_maintenance_without_a_wired_runtime_refuses_instead_of_pretending(self) -> None:
        view = _view(_configuration(_registry()))
        writes: list[str] = []

        tui._run_text(
            _scripted(["", "1", "s", "r", "q"]),
            writes.append,
            source_stage_view=view,
        )

        rendered = "\n".join(writes)
        self.assertIn("source synchronization is unavailable in this TUI runtime", rendered)
        self.assertIn("source removal is unavailable in this TUI runtime", rendered)


class SourceRefusalWayOutTests(unittest.TestCase):
    """A refused source operation must state its way out on the screen that refused it.

    This is the failure the whole stage exists to end: an origin that re-declared its identity
    refuses every sync, and a notice that shows only the refusal leaves the user exactly where
    they were before these operations existed.
    """

    IDENTITY_CHANGE = Err(
        (
            tui.Diagnostic(
                tui.DiagnosticCode("source-invalid"),
                tui.Severity.ERROR,
                "resolved source changed its declared source identity",
                remediation=(
                    "review the origin, then run `aart source remove --alias registry` and add "
                    "it again to subscribe to the new identity",
                ),
            ),
        )
    )

    def test_the_curses_notice_keeps_remediation_and_wraps_instead_of_truncating(self) -> None:
        lines = tui._source_flow_diagnostics(self.IDENTITY_CHANGE)

        joined = " ".join(line.strip() for line in lines)
        self.assertIn("changed its declared source identity", joined)
        self.assertIn("aart source remove --alias registry", joined)
        self.assertNotIn("…", joined)
        for line in lines:
            self.assertLessEqual(len(line), CONTENT_MEASURE)

    def test_the_text_front_end_states_the_keys_that_lead_out_of_a_failed_sync(self) -> None:
        source = _registry()
        runtime = _Runtime(_view(_configuration(source)), sync=self.IDENTITY_CHANGE)
        writes: list[str] = []

        tui._run_text(
            _scripted(["", "1", "s", "1", "y", "q"]),
            writes.append,
            source_stage_view=runtime.view,
            source_removal_finalizer=runtime.finalize_removal,
            source_sync_runner=runtime.run_sync,
            source_stage_loader=runtime.load,
        )

        rendered = "\n".join(writes)
        self.assertIn("changed its declared source identity", rendered)
        self.assertIn("remediation: review the origin", rendered)
        self.assertIn("In Sources: s retries, r removes this source, a adds one.", rendered)


class SourceLifecycleCursesTests(unittest.TestCase):
    """The curses front-end binds the same two operations to s and r on the Sources list."""

    def test_the_sources_list_advertises_and_returns_sync_and_remove(self) -> None:
        for key, kind in ((ord("s"), "sync"), (ord("r"), "remove")):
            with self.subTest(kind=kind):
                screen = Screen((key,), height=16, width=110)

                event = tui._curses_multiselect(
                    curses,
                    screen,
                    "Sources",
                    ("registry — health: current",),
                    wizard=True,
                    allow_add=True,
                    allow_source_maintenance=True,
                )

                assert not isinstance(event, tuple)
                self.assertEqual(event.kind, kind)
                self.assertEqual(event.selected, (0,))
                bar = [value for row, _column, value in screen.lines if row == screen.height - 1][0]
                self.assertIn("s=sync", bar)
                self.assertIn("r=remove", bar)

    def test_a_list_without_source_maintenance_never_binds_those_keys(self) -> None:
        screen = Screen((ord("s"), ord("r"), 10), height=16, width=110)

        picked = tui._curses_multiselect(curses, screen, "Artifacts", ("one",), wizard=True)

        self.assertEqual(picked.kind, "confirm")
        bar = [value for row, _column, value in screen.lines if row == screen.height - 1][0]
        self.assertNotIn("s=sync", bar)

    def test_the_curses_sources_stage_reports_the_cursor_row_for_maintenance(self) -> None:
        view = _view(_configuration(_registry("first"), _registry("second")))
        screen = Screen((curses.KEY_DOWN, ord("r")), height=20, width=110)

        event, selection, error = tui._curses_source_event(
            curses,
            screen,
            tui.WizardSession(current="source"),
            view,
        )

        self.assertEqual(event.kind, "remove")
        self.assertIsNone(selection)
        self.assertIsNone(error)
        row = tui._selected_source_row(view, event.selected)
        assert row is not None
        self.assertEqual(row.source.alias, SourceAlias("second"))

    def test_the_no_source_row_is_not_a_maintenance_target(self) -> None:
        view = _view(_configuration(_registry()))

        self.assertIsNone(tui._selected_source_row(view, (len(view.rows),)))

    def test_the_curses_removal_screen_plans_and_reviews_before_returning(self) -> None:
        view = _view(_configuration(_registry(), default="registry"))
        session = tui.WizardSession(current="source")
        screen = Screen((10,), height=24, width=110)

        request = tui._curses_source_removal(curses, screen, session, view, view.rows[0])

        assert not isinstance(request, tui.WizardInput)
        self.assertEqual(request.source.alias, SourceAlias("registry"))
        self.assertTrue(request.cleared_default)
        rendered = "\n".join(value for _row, _column, value in screen.history)
        self.assertIn("Source removal review:", rendered)
        self.assertIn("enter=remove", rendered)

    def test_the_curses_removal_screen_can_be_declined(self) -> None:
        view = _view(_configuration(_registry()))
        screen = Screen((ord("n"),), height=24, width=110)

        request = tui._curses_source_removal(
            curses,
            screen,
            tui.WizardSession(current="source"),
            view,
            view.rows[0],
        )

        self.assertIsInstance(request, tui.WizardInput)
        assert isinstance(request, tui.WizardInput)
        self.assertEqual(request.kind, "back")

    def test_the_curses_sync_screen_reviews_before_returning_the_row(self) -> None:
        view = _view(_configuration(_registry()))
        screen = Screen((10,), height=24, width=110)

        reviewed = tui._curses_source_sync(
            curses,
            screen,
            tui.WizardSession(current="source"),
            view.rows[0],
        )

        self.assertIs(reviewed, view.rows[0])
        rendered = "\n".join(value for _row, _column, value in screen.history)
        self.assertIn("Source sync review:", rendered)
        self.assertIn("enter=sync", rendered)


if __name__ == "__main__":
    unittest.main()
