# Plan: issue #17 — explicit action outcomes and summaries

Status: completed

Design: `docs/design/DESIGN-action-outcomes.md`

## 1. Delivery strategy

Deliver test-first vertical slices. Each slice begins with a failing contract test, implements the
smallest complete domain behavior, and refactors only while focused tests remain green. Preserve
legacy JSON fields and process exit codes throughout so failures identify the new slice rather than
an unrelated compatibility break.

The implementation sequence deliberately starts at the pure result algebra, then instruments the
effect boundary, then migrates consumer and maintainer commands, and finally changes the TUI. No UI
code may parse stdout or executor description strings.

## 2. Work packages

### WP-1 — Immutable outcome algebra and pure projections (TDD)

Red:

- Add table-driven tests for every outcome status, deterministic count aggregation, changed/no-op
  calculation, and stable item ordering.
- Add headline tests for install/reinstall, changed/already-current update, empty update filters,
  uninstall with missing effects, cancellation, conflict, failure, and maintainer zero-change.
- Assert `summary_to_dict` and `render_summary` expose equivalent counts and item identities.

Green:

- Add frozen `OutcomeItem`, `ActionSummary`, and `CommandOutcome` values.
- Add pure counts, JSON projection, and human renderer functions in `outcomes.py`.
- Keep warnings and recovery as separate ordered values.

Refactor gate:

- Run the outcome unit tests and mypy on the new module.
- Ensure no filesystem, network, terminal, or command imports enter the pure projection module.

### WP-2 — Structured executor observations and no-op detection (TDD)

Red:

- Extend executor tests for changed and unchanged `CopyTree`, `SymlinkTree`, `WriteFile`,
  `MergeJson`, and `RemovePath` actions.
- Cover recursively equal/different trees, already-equal merge values, absent removals, and an
  injected per-effect failure.
- Assert compatibility `performed` strings remain available.

Green:

- Add immutable effect observations to `executor.Report`.
- Add deterministic tree/file/link/merge comparisons before mutation.
- Skip proven no-op writes/copies/merges while recording `unchanged`.
- Convert shell effect failures into structured failed observations without losing earlier items.

Refactor gate:

- Run executor, filesystem, merge, and planner unit tests.
- Verify comparison helpers are read-only and mutation remains confined to performers.

### WP-3 — Install outcome contract (TDD)

Red:

- Test fresh install, reinstall, copy, symlink, mixed bundle fallback, skipped compatibility,
  conflict, execution failure, and empty broad selection.
- Assert human and JSON summaries have identical selected/changed/count/item data.
- Assert legacy install JSON fields remain.

Green:

- Split install into `execute(request) -> CommandOutcome` plus rendering `run(request) -> int`.
- Map manifest-before/after entries and executor observations to installed/reinstalled/skipped/
  conflicted/failed items with actual `InstallProof.mode`.
- Persist only entries whose required effects completed safely.

Refactor gate:

- Run install, compatibility-install, symlink-install, manifest, and executor tests.

### WP-4 — Update classification and zero-change contract (TDD)

Red:

- Test five selected/current entries produce selected=5, changed=0 and five `up_to_date` items.
- Test real file/tree/merge changes, empty filters, missing upstream artifact, skipped compatibility,
  drift conflict, forced conflict resolution, partial execution failure, and prune.
- Verify linked entries that already point to the correct source are current.

Green:

- Preserve entry-to-effect ownership while assembling each source-group plan.
- Map structured observations by managed path/merge identity to each selected manifest entry.
- Return explicit changed/up-to-date/skipped/conflict/failed items and canonical no-op text.
- Preserve multi-subscription all-planning-before-execution safety.

Refactor gate:

- Run update, update-subscription, compatibility-update, policy, status, and symlink tests.

### WP-5 — Uninstall effect accounting and preservation (TDD)

Red:

- Test removed manifest entries with existing files, already-missing files/config entries,
  sentinel-preserved user content, restored backups, changed symlink conflicts, no match, dry-run,
  and partial failures.
- Assert selected entry count, removed entry list, per-effect absent/removed/preserved facts, and
  human/JSON parity.

Green:

- Return structured observations from file, sentinel, backup, link, and merge reversal helpers.
- Split uninstall into outcome execution and rendering wrapper.
- Remove a manifest entry only when its required reversal is complete; retain recoverable entries
  on failure and include recovery instructions.

Refactor gate:

- Run uninstall, memory, manifest, and symlink uninstall tests.

### WP-6 — Maintainer result mapping (TDD)

Red:

- Cover validate/health, zero/nonzero scan, add, import with skipped/conflicts, upstream check,
  zero-change update, changed update, preview, cancellation, and failure.
- Assert scanned/imported/checked/updated counts and item lists match in human and JSON output.

Green:

- Add outcome-producing execution paths for every upstream action.
- Translate existing `UpstreamStatus`, import selection, catalog health, and executor observations
  directly into outcome items.
- Retain command-specific preview/status detail in `CommandOutcome.payload`.

Refactor gate:

- Run all upstream command, planner, JSON, import, validation, and maintainer tests.

### WP-7 — Shared CLI/TUI result dispatch and explicit early exits (TDD)

Red:

- Assert flag-mode dispatch renders one final summary and returns the outcome exit code.
- Assert text TUI writes the same summary through its injected writer.
- Assert curses dispatch occurs after wrapper teardown and leaves the summary visible.
- Cover cancelled role/profile/action/selection, empty selection, no matching choices, positive,
  no-op, conflict, partial failure, and recovery output in both frontends.

Green:

- Add result dispatch alongside the existing CLI compatibility dispatch.
- Make TUI consume `CommandOutcome`, never captured/parsing stdout.
- Return/render explicit non-mutating outcomes for every early quit/empty path.
- Ensure warnings and recovery follow the headline and are not cleared by curses.

Refactor gate:

- Run TUI, role, maintainer-TUI, CLI, and smoke tests.

### WP-8 — Documentation and tracker

- Document final summary examples and JSON `summary` schema in README.
- Explain exit-code/no-op behavior and actual install-mode reporting.
- Update `TODO.md` for #17 only after all acceptance tests and gates pass.
- Record the final quality-gate evidence in this plan.

## 3. DDD and functional-programming constraints

- Outcome records, effect observations, manifest entries, plans, and requests remain immutable.
- Counts and headlines are derived by pure folds/projections; do not store duplicate mutable
  counters.
- Commands are application services translating domain/planner/executor records into outcomes.
- Filesystem/network/terminal operations stay at shell adapters; no renderer reads disk.
- Expected errors, conflicts, cancellation, and partial results are values with exit codes.
- Preserve input ordering and return new tuples/mappings instead of mutating selections.
- Frontends depend on `CommandOutcome`; they never know planner action classes or parse prose.

## 4. Quality gates

Run from narrowest to broadest:

1. Focused outcome/executor/command tests:

   ```sh
   python -m unittest tests.outcomes_test tests.executor_test tests.install_test \
     tests.update_test tests.uninstall_test tests.upstream_command_test \
     tests.upstream_json_test tests.upstream_maintainer_command_test tests.tui_test \
     tests.tui_maintainer_e2e_test
   ```

2. Formatting and lint:

   ```sh
   make format
   make format-check
   make lint
   ```

3. Static types:

   ```sh
   make typecheck
   ```

4. Catalog and dependency validation:

   ```sh
   make validate
   ```

5. Full unit and end-to-end suite:

   ```sh
   make test
   ```

6. CLI/TUI smoke matrix in a temporary project:

   ```sh
   python -m agent_artifacts install code-review --profile claude --source . --project "$TMPDIR/aart-outcome-smoke" --json
   python -m agent_artifacts update code-review --profile claude --source . --project "$TMPDIR/aart-outcome-smoke" --json
   python -m agent_artifacts uninstall code-review --profile claude --project "$TMPDIR/aart-outcome-smoke" --json
   python -m agent_artifacts upstream validate --source . --json
   python -m agent_artifacts upstream check --source . --all --json
   ```

7. Final audit:

- Every #17 acceptance criterion maps to a focused test and full-suite evidence.
- Human/JSON summaries originate from the same value.
- No frontend parses stdout or executor description text.
- Legacy JSON fields and exit codes remain covered.
- No unrelated user files are staged.

## 5. Stop conditions

- Do not label an update current merely because the command exited zero; prove effect equivalence.
- Do not erase warnings/recovery under a concise headline.
- Do not save a manifest entry as successful when its required effect failed.
- Do not broaden into #18-#21 UI/features beyond the structured extension points required here.
- Do not mark #17 complete while any focused or full quality gate is red.

## 6. Execution record

Completed on 2026-08-06.

- Added the immutable `OutcomeItem`, `ActionSummary`, and `CommandOutcome` domain contract plus
  pure human/JSON projections.
- Added structured executor observations, proven no-op detection, and failure capture without
  discarding earlier effects.
- Migrated install, update, uninstall, maintainer actions, CLI dispatch, and both TUI frontends to
  explicit results. Update pruning, manifest write failures, drift, missing uninstall effects,
  cancellation, conflicts, partial install success, and recovery guidance have focused tests.
- Preserved existing exit codes and command-specific JSON fields while adding the canonical
  `summary` object.
- Updated README examples and marked the issue tracker only after all gates passed.

Quality-gate evidence:

- `make format` and `make format-check`: 109 Python files formatted.
- `make lint`: Ruff reported no violations.
- `make typecheck`: mypy reported no issues in 45 source files.
- `make validate`: catalog validation and the stdlib-only import gate passed.
- `make test`: 682 unit tests passed, followed by the complete 11-step shell E2E flow.
- CLI smoke: install, already-current update, uninstall, maintainer validate, missing-tracking
  failure/recovery output, and a successful zero-selection upstream check all emitted canonical
  JSON summaries. The temporary consumer project was moved to the system Trash.
- Final diff and code-review audit: no whitespace errors, no stdout parsing in the TUI, and no
  unrelated user files selected for commit.
