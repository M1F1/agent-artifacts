# Plan: issue #18 — TUI copy/symlink installation mode

Status: completed

Design: `docs/design/DESIGN-tui-install-mode.md`

## 1. Delivery strategy

Implement test-first vertical slices from pure policy to text UI, curses UI, confirmation, and
real lifecycle behavior. Each slice starts red, becomes green with the smallest complete change,
then refactors while focused tests remain green.

The command core is already the authoritative symlink implementation. TUI tests assert the built
`Request` and user-visible policy; command/E2E tests assert filesystem and manifest effects. No TUI
test should require a real terminal or developer-global path.

## 2. Work packages

### WP-1 — Pure mode and choice policy (TDD)

Red:

- Test ordered Copy/Symlink choices and the Copy default.
- Test `skill`/`hook` linkability and copy-only guideline/memory/MCP rows.
- Test Symlink rows retain disabled copy-only artifacts with a reason.
- Test mixed bundles disclose linked/copied counts, compatibility-hidden counts, multi-profile
  multiplication, and overlapping artifact/bundle de-duplication.

Green:

- Add frozen mode/confirmation values and a pure linkability predicate.
- Extend `_Choice` with enabled/reason and projected mode facts.
- Parameterize install choice construction by `InstallMode`, defaulting to copy.
- Add pure selection resolution/count and confirmation projection helpers.

Refactor gate:

- Run TUI choice/profile tests and mypy.
- Confirm pure helpers import no terminal, command, filesystem, or network adapters.

### WP-2 — Text mode selection, disabled rows, and narrow Back (TDD)

Red:

- Test blank selects Copy, explicit `1` selects Copy, and `2` selects Symlink.
- Test mode is requested for Install only and reaches `Request.install_mode`.
- Test `q` cancels and `b` returns to Action without dispatch while retaining profiles.
- Test a disabled row is rejected with its reason and a later valid selection succeeds.
- Test remote Symlink returns usage 2 before artifact selection/mutation and explains
  `--source DIR --link`.

Green:

- Add the text mode prompt and Action/Mode loop.
- Validate the resolved source label before building Symlink choices.
- Reject disabled `_prompt_indices` selections and re-prompt.
- Thread mode through choice building and `_build_request`.

Refactor gate:

- Run text TUI, input validation, source error, and request-construction tests.

### WP-3 — Shared confirmation projection and text confirmation (TDD)

Red:

- Test confirmation includes source label/root, absolute Project root, harnesses, requested mode,
  selected rows, and projected linked/copied counts.
- Test declining/EOF cancels with no changes and accepting dispatches exactly once.
- Test a mixed bundle preview matches the actual completion-summary mode counts.

Green:

- Build immutable confirmation data from source/catalog/selection/profile values.
- Render shared confirmation lines.
- Prompt only for Install and dispatch only after affirmative confirmation.
- Keep completion rendering on the existing structured result path.

Refactor gate:

- Run text TUI outcome, cancellation, mixed-bundle, and narrow-terminal tests.

### WP-4 — Curses mode, disabled rows, Back, and confirmation (TDD)

Red:

- Assert curses screen order is Harness -> Action -> Mode -> Artifacts -> Confirmation for Install.
- Assert Copy begins selected, Symlink is passed to `Request`, and mode is absent for other actions.
- Assert Backspace/127/8 from Mode returns exactly to Action without dispatch.
- Assert disabled rows cannot toggle and show a non-color reason.
- Assert declining/quit leaves no mutation; accepting dispatches only after `curses.wrapper` exits.
- Cover narrow terminal rendering for the new screens.

Green:

- Add a thin curses mode selector with the three Backspace codes.
- Add optional disabled state to the existing multi-select primitive.
- Add shared confirmation rendering/confirmation key handling.
- Retain request/result dispatch outside the curses wrapper.

Refactor gate:

- Run curses flow, selector primitive, teardown, recovery, and narrow-terminal tests.

### WP-5 — Real TUI lifecycle/E2E contract (TDD)

Red:

- Run text TUI Copy default into a temporary consumer and assert a real directory plus copy
  manifest/outcome mode.
- Run text TUI Symlink against a copied local fixture and assert a live destination link,
  requested/actual mode, and source target metadata.
- Exercise a mixed bundle and assert linked/copied completion items and warning.
- Update a linked entry and assert the link is preserved/live, not recopied.
- Uninstall and assert only the managed link disappears while its fixture source remains.

Green:

- Fix only integration seams exposed by the tests; do not duplicate command lifecycle policy.
- Preserve the existing #17 human/JSON outcome contract.

Refactor gate:

- Run symlink install/status/update/uninstall, manifest, planner, executor, and TUI E2E suites.

### WP-6 — Help, README, tracker, and execution evidence

- Align CLI and TUI terms: `Copy (recommended)` and `Symlink`, with `--link` identified as the
  flag spelling.
- Document the interactive mode and confirmation flow, local-only constraint, mixed fallback,
  and actual completion modes.
- Update `TODO.md` for #18 only after every acceptance test and gate passes.
- Change design/plan status and record final gate evidence after execution.

## 3. DDD and functional-programming constraints

- Reuse existing frozen `InstallMode`, `Request`, `Artifact`, `Bundle`, and `CommandOutcome` values.
- New mode/confirmation records are frozen; selection transformations return tuples/sets without
  mutating catalog or UI state.
- Linkability, de-duplication, mode counts, disabled policy, and confirmation rendering are pure.
- Terminal/source/filesystem work stays in adapters; TUI renderers never inspect manifests or
  planner action strings.
- The install application service remains the only mutation boundary.
- Cancellation and unavailable selections are ordinary outcomes/return values.
- Preserve deterministic catalog, bundle, profile, and user-selection ordering.

## 4. Quality gates

Run from narrowest to broadest:

1. Focused tests:

   ```sh
   python -m unittest tests.tui_install_mode_test tests.tui_test \
     tests.symlink_install_test tests.action_outcome_commands_test
   ```

2. Formatting/lint:

   ```sh
   make format
   make format-check
   make lint
   ```

3. Static types:

   ```sh
   make typecheck
   ```

4. Catalog/import validation:

   ```sh
   make validate
   ```

5. Full unit and shell E2E suite:

   ```sh
   make test
   ```

6. Temporary-project smoke:

   ```text
   text TUI Copy -> install summary -> uninstall
   text TUI Symlink -> status live link -> update no-copy -> uninstall source preserved
   text TUI mixed bundle -> linked/copied confirmation and completion counts
   remote-source Symlink -> usage 2, no consumer manifest
   ```

7. Final audit:

- Every #18 acceptance criterion maps to a focused or lifecycle test.
- Only Install asks for mode/confirmation.
- The mutating request dispatches once and only after confirmation.
- TUI performs no symlink/filesystem policy and parses no command output.
- Existing user files remain unstaged.

## 5. Stop conditions

- Do not make Symlink the default.
- Do not allow remote/cache-backed link targets.
- Do not let an enabled explicit copy-only row reach the late command usage error.
- Do not claim a bundle is all linked when it contains copied/merged targets.
- Do not dispatch a mutating request before confirmation.
- Do not implement user scope, setup installers, or the full #21 wizard in this issue.
- Do not mark #18 complete while any quality gate is red.

## 6. Execution record

Completed on 2026-08-06.

- Added immutable Copy/Symlink mode and confirmation values plus pure selection de-duplication,
  actual-mode projection, and confirmation rendering.
- Centralized linkable artifact types in the shared pure `install_modes` domain module used by the
  command core and TUI.
- Added the Install-only mode stage to text and curses, with Copy default, local-source validation,
  narrow Back-to-Action navigation, disabled copy-only rows, and disclosed mixed bundle counts.
- Added a shared confirmation view containing source, Project destination root, harnesses,
  requested mode, selected rows, and projected actual modes. Mutating dispatch happens once and
  only after confirmation and curses teardown.
- Kept the existing command core authoritative for symlink creation, manifest proof, live update,
  safe uninstall, and the #17 completion outcome.
- Aligned CLI help and README terminology and examples.

Quality-gate evidence:

- Focused matrix: 145 TUI/mode/role/CLI/symlink/outcome tests passed during the final review slice.
- `make format` and `make format-check`: 112 Python files formatted.
- Ruff: all package, test, and tracked script files passed. The literal `make lint` target also
  sees the unrelated untracked user file `scripts/demo_github_usage_report.py`; it was deliberately
  preserved and excluded from the scoped gate rather than edited or staged.
- `make typecheck`: mypy reported no issues in 46 source files.
- `make validate`: catalog validation and the stdlib-only import gate passed.
- `make test`: 705 unit tests passed, followed by the complete 11-step shell E2E flow.
- Temporary lifecycle smoke: real text-TUI Symlink install recorded requested/actual mode and link
  target, update kept it live without copying, uninstall removed only the link, and mixed bundle
  confirmation/completion both reported two linked and two copied targets.
- Remote-source tests for both text and curses returned usage 2 before artifact selection or
  mutation and showed the `--source DIR --link` recovery path.
- Final code review found no blocking correctness, security, or performance issue and removed the
  duplicated linkability rule.
