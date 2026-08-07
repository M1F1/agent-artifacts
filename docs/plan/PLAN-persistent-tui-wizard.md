# Plan: issue #21 — persistent TUI onboarding and review wizard

Status: complete

Design: `docs/design/DESIGN-persistent-tui-wizard.md`

## 1. Delivery strategy

Implement vertical, test-first slices from the pure wizard domain outward. Every work package starts
with failing tests, adds the smallest coherent behavior, and refactors only while its focused suite
is green. The immutable wizard/session model is shared; text and curses remain thin adapters over
the same transitions and existing request/command core.

Baseline on `main` before issue #21: 772 unit tests, all 11 shell E2E steps, Ruff, mypy across 50
source files, catalog validation, and the stdlib-only gate passed after issue #20.

## 2. Work packages

### WP-1 — Pure stage graph and immutable session (TDD)

Red:

- Test the initial stage is Onboarding and all records are frozen.
- Test User dynamic stages for Install, Update, Uninstall, and Status.
- Test Maintainer dynamic stages for health/validate/add/import/check/update/User workflows.
- Test forward, one-stage Back, repeated Back/Next, visited/confirmed markers, and boundary no-ops.
- Test profiles, action, scope, mode, source facts, branch-specific values, and basket survive
  navigation.
- Test position memory stores/clamps cursor and scroll per stage.
- Test only Review can produce Finalize and stale revisions cannot finalize.
- Test empty-basket quit versus `confirm_quit` for a non-empty basket.

Green:

- Add `agent_artifacts/wizard.py` with frozen `WizardSession`, `WizardPosition`, `BasketItem`,
  `WizardNotice`, navigation input/decision values, stage constants, and total transition functions.
- Keep stage derivation and transition validation independent of TUI, catalog, commands, and I/O.

Refactor gate:

- `python -m unittest tests.wizard_state_test`
- Ruff and mypy on `wizard.py` and its tests.
- Source inspection confirms no terminal/filesystem/network/command imports.

DDD boundary: the Wizard aggregate owns navigation and confirmation, not artifact eligibility or
mutation.

Functional approach: each event is `WizardSession -> WizardSession/Decision`; no in-place lists,
hidden globals, mutable dictionaries, or exception-based expected control flow.

### WP-2 — Selective invalidation, basket, and render projections (TDD)

Red:

- Reconcile an edited profile/scope/mode/action against immutable available choices.
- Preserve compatible basket keys in stable order and remove only invalid/disabled keys.
- Emit one visible reason per removed key, de-duplicated and stable.
- Mark affected downstream stages unconfirmed without erasing unrelated selections.
- Test selected count, descriptions, disabled reasons, setup queue, destinations, projected mixed
  modes, and source facts in Review.
- Test `[x]`/`[●]`/`[ ]` stepper semantics and whole-token wrapping in narrow widths.
- Test onboarding text for curses and fallback controls plus single/multi-select hints.

Green:

- Add pure choice reconciliation, basket projection, stepper/header/onboarding rendering, and
  Review projection helpers.
- Reuse `_Choice`, `InstallConfirmation`, compatibility reasons, and setup queue values instead of
  reproducing policy.

Refactor gate:

- `python -m unittest tests.wizard_state_test tests.wizard_render_test`
- Confirm no color-only state and no line exceeds supplied width.

DDD boundary: compatibility/catalog inputs are read models; the Wizard keeps only stable selection
identity and notices.

Functional approach: filter/fold immutable tuples; renderers are deterministic string projections.

### WP-3 — Explicit adapter input results and text wizard (TDD)

Red:

- Text session starts with Onboarding before Role.
- Every stage prints the shared header, current stage, relevant hint, and basket count.
- `b`/`back` returns one stage; `q`/`quit` is distinct from empty confirmation.
- Single-select never accepts a multi-toggle operation; multi-select edits the existing basket.
- Back/forward preserves profile/action/scope/mode/artifact selections.
- Review Back returns to Artifacts with the basket intact.
- Editing an earlier choice retains compatible selections and prints removals/reasons.
- Quit with a basket asks for abandonment confirmation; No returns to the same stage.
- Install/Update/Uninstall dispatch exactly once only after Finalize; cancellation never dispatches.
- Status uses the dynamic short path and keeps structured result rendering.

Green:

- Introduce an explicit `WizardInput` result for text prompts.
- Refactor `_run_text`/User flow into a stage loop over `WizardSession`.
- Load source/manifest/catalog read models only on applicable stages and reconcile the basket before
  Review.
- Build the existing `Request` and `InstallConfirmation` only from a valid Finalize decision.
- Keep issue #20 setup execution after core success.

Refactor gate:

- `python -m unittest tests.tui_wizard_text_test tests.tui_test tests.tui_roles_test \
  tests.tui_scope_test tests.tui_install_mode_test tests.tui_setup_test`
- Existing text lifecycle and structured outcome tests remain green.

DDD boundary: the application shell supplies read models and maps finalized state to `Request`;
commands remain the only mutation services.

Functional approach: the loop folds explicit input events into new sessions; prompt functions do
not mutate shared selections.

### WP-4 — Curses wizard, Backspace, viewport restoration, and teardown (TDD)

Red:

- Curses first displays Onboarding, then the dynamic stepper on every stage.
- `KEY_BACKSPACE`, `127`, and `8` return one stage from single-select, multi-select, and Review.
- Space toggles only multi-select rows; disabled rows remain non-selectable with `[-]` and reasons.
- Initial checked keys, cursor, and scroll restore after Back/forward.
- Review Back preserves the basket; Finalize is visually distinct and dispatches exactly once.
- Quit with a basket confirms abandonment and reports no mutation.
- Narrow heights/widths retain current stage, stepper state, basket count, and controls without
  throwing.
- Dispatch and interactive setup run only after `curses.wrapper` tears down.

Green:

- Add thin curses stage/select/review adapters returning `WizardInput` plus position.
- Extend list drawing with header rows, viewport offset, initial checked/cursor values, and shared
  accessible markers.
- Drive the same `WizardSession` transition loop inside the wrapper and retain only the finalized
  decision for post-wrapper dispatch.

Refactor gate:

- `python -m unittest tests.tui_wizard_curses_test tests.tui_test \
  tests.tui_install_mode_test tests.tui_scope_test tests.tui_setup_test`
- Exactly-once and post-teardown assertions pass with patched curses boundaries.

DDD boundary: curses owns key codes and dimensions only.

Functional approach: drawing consumes immutable view state; input returns events, never performs a
command.

### WP-5 — Maintainer dynamic stages and preview/finalize protocol (TDD)

Red:

- Maintainer health/validate use the short Review path.
- Add/import collect non-secret upstream details as editable state before Review.
- Import candidates and tracked check/update keys behave as persistent basket items.
- Back moves through applicable maintainer stages without rerunning apply or losing inputs.
- Changing URL/source invalidates only dependent candidates and explains removals.
- Mutation Review performs validation and dry-run preview, but apply occurs only on Finalize.
- Preview failure, Back, quit, or decline never applies.
- Curses leaves full-screen mode before line-oriented upstream detail entry/output while preserving
  the shared session, or presents equivalent curses fields where implemented.
- Existing validation -> preview -> apply -> validation order and exit codes remain unchanged.

Green:

- Project maintainer actions/forms/selections into the shared stage graph.
- Split the existing mutation protocol into explicit non-mutating preview and finalized apply
  phases without changing command requests.
- Reuse upstream candidate/context queries and Request builders.

Refactor gate:

- `python -m unittest tests.tui_wizard_maintainer_test tests.tui_roles_test \
  tests.tui_maintainer_e2e_test tests.upstream_command_test`
- No maintainer write before Finalize in dispatch-spy traces.

DDD boundary: the maintainer/upstream domain still owns catalog rules; the wizard owns only staged
input and finalization.

Functional approach: immutable non-secret form values and request transformations; effectful
validation/query/dispatch stay injected.

### WP-6 — Real lifecycle, documentation, tracker, and compatibility (TDD)

Red:

- Temporary project text E2E: onboarding -> basket -> Review/Edit -> Finalize -> one install.
- Temporary user-home path: scope edit shows exact retained/removed selections and never touches the
  real home.
- Symlink and mixed bundle review match actual completion modes.
- Setup-capable selection appears in Review and setup runs only after successful Finalize/install.
- Update/uninstall Review lists recorded source/destination and preserves command lifecycle.
- Text and curses quit paths state that no changes were made.

Green:

- Update README with compact onboarding, stepper, basket, and full Review examples.
- Add issue #21 to `TODO.md`; check items only after final gates.
- Update existing headless scripts and fixtures without weakening prior acceptance assertions.

Refactor gate:

- New wizard E2E plus issue #15–#20 TUI/lifecycle suites.
- No tests read/write real user-global paths or invoke real setup adapters.

## 3. Cross-cutting DDD and functional constraints

- `WizardSession` is the aggregate root; transitions preserve its invariants.
- Stage, position, basket, notice, input, and decision are immutable value objects.
- Catalog, manifest, profile, compatibility, setup, and upstream domains remain separate bounded
  contexts exposed as read models or existing services.
- The anti-corruption boundary maps only a finalized session into an existing `Request`.
- Stage derivation, transition, invalidation, clamping, basket reconciliation, stepper rendering,
  Review rendering, and request selection ordering are pure and deterministic.
- Terminal, source, manifest, query, clock, filesystem, network, setup, and command dispatch effects
  stay at injected shell boundaries.
- Expected Back/quit/invalid/empty states are values, not raised exceptions.
- No secret enters wizard state, Review, notices, logs, or test snapshots.
- Runtime dependencies remain Python standard library only.

## 4. Quality gates

Run narrowest to broadest after every relevant slice, then repeat the complete matrix on the final
tree.

1. Pure wizard domain/rendering:

   ```sh
   python -m unittest tests.wizard_state_test tests.wizard_render_test
   ```

2. Text/curses/maintainer wizard integration:

   ```sh
   python -m unittest tests.tui_wizard_text_test tests.tui_wizard_curses_test \
     tests.tui_wizard_maintainer_test
   ```

3. Adjacent #15–#20 regressions:

   ```sh
   python -m unittest tests.tui_test tests.tui_roles_test tests.tui_scope_test \
     tests.tui_install_mode_test tests.tui_setup_test tests.tui_maintainer_e2e_test
   ```

4. Formatting and lint on repository-owned files:

   ```sh
   python -m ruff format agent_artifacts tests scripts/build_wheel.py \
     scripts/inject_commit.py scripts/bump_version.py skills/author-aart-installer/scripts
   python -m ruff format --check agent_artifacts tests scripts/build_wheel.py \
     scripts/inject_commit.py scripts/bump_version.py skills/author-aart-installer/scripts
   python -m ruff check agent_artifacts tests scripts/build_wheel.py \
     scripts/inject_commit.py scripts/bump_version.py skills/author-aart-installer/scripts
   ```

5. Static/catalog/import gates:

   ```sh
   python -m mypy
   make validate
   ```

6. Full unit and shell E2E:

   ```sh
   python -m unittest discover -s tests -p '*_test.py'
   bash tests/e2e_test.sh
   ```

7. Final audit:

- `git diff --check` and intended-file staging review.
- Code-review skill audit for correctness, security, style, performance, and test gaps.
- Map every issue criterion and #15–#20 seam to a test/doc/code reference.
- Confirm no mutating dispatch is reachable before Finalize.
- Confirm unrelated untracked user files remain untouched and unstaged.

The literal broad `make lint`/`make format` targets include the unrelated untracked
`scripts/demo_github_usage_report.py`; use the equivalent explicit repository-owned path list above
unless that user file is independently removed or adopted.

## 5. Stop conditions

- Do not add production behavior before the corresponding failing test.
- Do not let text and curses maintain separate navigation truth.
- Do not reset all downstream state when only some values become invalid.
- Do not dispatch install/update/uninstall/upstream apply before a current Review Finalize.
- Do not treat Back, quit, cursor movement, detail view, source query, or dry-run preview as apply.
- Do not lose a non-empty basket without explicit quit confirmation.
- Do not use color as the sole state indicator.
- Do not touch real home, Keychain, Docker, harness config, or remote upstreams in tests.
- Do not mark #21 complete while any acceptance or quality gate is red.

## 6. Execution record

Completed on 2026-08-06 in the planned TDD slices:

- WP-1/2 introduced the frozen wizard aggregate, dynamic stage graph, confirmation/revision rules,
  selective basket reconciliation, position clamping, onboarding, stepper, and narrow render
  projections. The focused pure suite contains state and rendering tests only; the module has no
  command, terminal, filesystem, subprocess, or network imports.
- WP-3 moved the production text entry path to a session fold with explicit Back/quit/confirm
  results, persistent basket, complete Review facts, stale-revision protection, and Finalize-only
  dispatch. A temporary-project lifecycle test exercises a real install after Review/Edit.
- WP-4 moved curses to the same session, added the three Backspace variants, restored checked rows,
  cursor and scroll, compacted selector headers for narrow terminals, made long Review screens
  scrollable, and retained the finalized request until after `curses.wrapper` teardown.
- WP-5 added Maintainer dynamic stages and split the mutation protocol into non-mutating
  validation/dry-run preview and Finalize-only apply/post-validation halves. Dispatch-spy and real
  upstream E2E tests prove preview cancellation cannot apply.
- WP-6 added the README walkthrough, issue tracker checklist, source/subscription and absolute
  destination facts for Update/Uninstall Review, setup-queue coverage, and cancellation E2E.

Final evidence:

- focused wizard suites: state, rendering, text, curses, Maintainer, and real lifecycle green;
- adjacent #15–#20 and upstream regressions green;
- full unittest discovery: 804 tests green;
- shell E2E: 11/11 steps green;
- Ruff format/check and lint green on repository-owned paths;
- mypy green across 51 source files;
- catalog validation and stdlib-only import gate green;
- `git diff --check` clean;
- code-review audit found no unresolved correctness, security, performance, style, or test-gap
  findings;
- unrelated `.agent-artifacts/`, `.tabnine/`, `TABNINE.md`, and
  `scripts/demo_github_usage_report.py` remained untouched and unstaged.
