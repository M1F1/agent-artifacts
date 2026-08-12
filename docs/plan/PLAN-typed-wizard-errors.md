# Plan: typed stage failures and actionable TUI diagnostics

- **Status:** proposed; documentation only, implementation not started
- **Design:** [`DESIGN-typed-wizard-errors.md`](../design/DESIGN-typed-wizard-errors.md)
- **Primary outcome:** expected failures retain typed diagnostics through the wizard, and an
  internal exception can never silently restart an active session.
- **Initial user-visible case:** legacy project installation state detected while loading
  Artifacts.

## Handoff state

The change set that introduced this plan also contains two prerequisite bug fixes that must remain
independently understandable in history:

- `agent_artifacts/tui.py` and `tests/tui_consumer_text_test.py` contain the local setup-reporting
  identity fix;
- `agent_artifacts/tui_marketplace.py` and `tests/tui_marketplace_test.py` contain the local
  lifecycle-status deduplication fix that prevents the observed Artifacts restart;
No typed-error implementation was made while writing this plan. A new agent should verify that the
preceding fixes are present in history, then implement ERR01 onward as a separate reviewable change.

The reproducer for the first expected failure is:

```text
/Users/mifi/code/agent-artifacts/.agent-artifacts/manifest.json
  top-level keys: repo, installed

cd /Users/mifi/code/agent-artifacts
aart
  User -> configured registry -> Claude -> Install -> Project -> Copy -> Artifacts
```

Current unhelpful output:

```text
error: missing required field 'installations'; missing required field 'schema_version';
unknown field 'installed'; unknown field 'repo'
```

The supported explicit migration preview currently continues with a separate, legitimate source
resolution error for `memory/superpowers@tabnine`. Do not hide or bypass that error:

```sh
aart migrate state --from 0.1 --scope project --dry-run
```

## Guardrails

- Write a failing characterization test before each functional change.
- Expected errors use `DomainErr`; do not add ordinary exception subclasses as control flow.
- Preserve `Diagnostic.code`, `location`, `remediation`, and `details`; never flatten them to one
  semicolon-separated string inside canonical TUI flows.
- Do not automatically migrate or modify legacy/invalid state.
- Do not broaden startup validation so project state blocks unrelated user-scope or maintainer
  paths.
- Do not catch programming errors inside domain code merely to make tests pass.
- Do not restart the wizard after session initialization.
- Do not expose raw exceptions, tracebacks, file contents, credentials, setup inputs, or environment
  values in normal terminal output or analytics.
- Keep text and curses behavior equivalent; a feature is incomplete if only one frontend handles it.
- Do not change registry schemas, artifact versions, or `requires_aart` in this task.
- Keep release/version bump and publication as separate explicitly authorized work.

## Delivery sequence

### ERR01 — characterize the two failure classes

**Status:** pending

1. Add a parser/application fixture for recognized 0.1 state (`repo` plus `installed`) and a
   separate malformed-v2 fixture.
2. Add a text-wizard test that reaches Artifacts with legacy project state and captures the current
   flattened diagnostic.
3. Add a curses flow test where an exception occurs after the session starts and prove the current
   behavior invokes text fallback/onboarding again.
4. Keep the already-added lifecycle duplicate test as regression coverage for the concrete bug,
   but do not treat deduplication as sufficient error handling.
5. Record mutation snapshots around each failing flow so later fixes prove that diagnostics are
   read-only.

Acceptance:

- tests fail for the intended behavioral reasons, not fixture/setup errors;
- the legacy-state and unexpected-internal-error cases are independently reproducible;
- test output contains no secrets or machine-dependent source content.

### ERR02 — discriminate legacy installation state in the parser

**Status:** pending; depends on ERR01

1. Add `INSTALL_STATE_LEGACY = DiagnosticCode("install-state-legacy")` beside
   `STATE_INVALID` in `agent_artifacts/install_state/schema.py`.
2. After JSON parsing and before strict v2 field validation, recognize only the bounded 0.1
   top-level shape. Return a typed diagnostic with:
   - the exact input path in `SourceLocation`;
   - a message that this is AART 0.1 installation state;
   - preview-first project/user migration remediation without `--apply`;
   - a detail identifying detected and required schema families, without serializing file content.
3. Keep malformed JSON, arbitrary unknown objects, malformed v2, and unsupported explicit schema
   versions under `install-state-invalid`.
4. Test project and user paths, canonical diagnostic ordering, and serialization through
   `diagnostic_to_data`.

Acceptance:

- legacy shape produces exactly `install-state-legacy`;
- malformed v2 never produces `install-state-legacy`;
- parsing performs no writes and does not infer source mappings.

### ERR03 — preserve DomainErr through the Artifacts loader

**Status:** pending; depends on ERR02

1. Change `_load_user_wizard_read_model` to return
   `DomainResult[_UserWizardReadModel]` for the canonical configured-marketplace path.
2. Remove conversion of `ConsumerApplicationService.browse` failures into legacy
   `Err("; ".join(...), code=2)`.
3. Audit the function's legacy-source branch. Adapt legacy command errors at one named compatibility
   boundary rather than weakening the canonical return type.
4. Introduce the immutable `WizardStageFailure` presentation envelope in a small wizard/TUI model
   module. It contains stage/operation/recovery context and the original diagnostics.
5. Add a pure adapter from `(session, operation, DomainErr)` to `WizardStageFailure`.

Acceptance:

- diagnostic identity, location, remediation, and details survive from parser to stage envelope;
- no canonical path concatenates diagnostic messages;
- mypy proves every loader outcome is handled.

### ERR04 — shared deterministic rendering and recovery

**Status:** pending; depends on ERR03

1. Add one pure renderer for `WizardStageFailure` used by text and curses.
2. Render stage, operation, codes, locations, details, remediation, and only the allowed recovery
   choices.
3. Add a shared wizard event for Retry if both frontends can support it in this slice. Otherwise
   ship Back/Quit equivalently and leave Retry explicitly pending; do not implement it in one
   frontend only.
4. Text Artifacts behavior:
   - render the failure in place;
   - Back returns to Mode/Scope through existing navigation;
   - Quit exits cleanly;
   - Retry repeats only the read-model load and preserves the session/basket.
5. Curses Artifacts behavior mirrors text and returns to the same screen after dismiss/retry.
6. Add narrow-terminal rendering tests and verify no color dependency.

Acceptance:

- legacy state output names Artifacts, project, path, code, and migration preview;
- choosing Back preserves valid earlier selections and permits User scope;
- no error path finalizes a plan or mutates state.

### ERR05 — constrain curses fallback and type internal failures

**Status:** pending; may proceed after ERR01, should integrate after ERR04

1. Replace broad fallback semantics in `_run_curses` and `run` with an explicit initialization
   boundary.
2. Allow text fallback exactly once only for import/TTY/curses setup failure before wizard session
   initialization.
3. After initialization:
   - expected stage failures use `WizardStageFailure`;
   - unexpected exceptions restore the terminal and produce `tui-stage-internal`;
   - the process exits non-zero and never invokes `_run_text`.
4. Ensure the outer crash boundary knows the last stage and operation without storing terminal or
   service objects in `WizardSession`.
5. Decide and implement the explicit local debug traceback mechanism from the design's open
   decisions. Default output must remain redacted.

Acceptance:

- initialization failure starts onboarding once in text mode;
- post-initialization exception never restarts onboarding;
- normal output contains a stable code and no raw exception/traceback;
- debug output is opt-in, local-only, tested, and excluded from reporting.

### ERR06 — audit remaining stage boundaries

**Status:** pending; depends on ERR03–ERR05

Audit every stage/operation boundary and classify failures rather than mechanically wrapping all
exceptions:

1. Sources load/add/sync/finalize.
2. Profile/scope/mode compatibility projection.
3. Artifacts marketplace and lifecycle joins.
4. Review preparation for consumer and maintainer paths.
5. Finalize, setup queue, and reporting.
6. Legacy compatibility paths still using `agent_artifacts.model.Err`.

For each boundary:

- expected adapter/domain failure returns `DomainErr`;
- frontend adds stage context and recovery choices;
- internal invariant failures reach the typed outer crash boundary;
- post-finalize warnings cannot overwrite or obscure known artifact outcomes;
- JSON CLI retains structured diagnostics and exit status.

Acceptance:

- no new canonical TUI code flattens diagnostics;
- no broad exception handler triggers a frontend restart;
- every caught exception has a documented narrow reason or is the outer crash boundary.

### ERR07 — documentation, quality, and release handoff

**Status:** pending; depends on ERR01–ERR06

1. Update user documentation with the rendered legacy-state example, migration preview, source-map
   follow-up, and distinction between project and user scope.
2. Update persistent-wizard design documentation to link this error contract.
3. Add a release note describing the UX correction without claiming automatic migration.
4. Decide the executable patch version only in the release task. Do not edit registry compatibility
   or per-artifact requirements.
5. Verify a built wheel reproduces the same typed behavior as the checkout.

Acceptance:

- docs never instruct users to delete or hand-edit installation state;
- release notes distinguish legacy state, invalid state, and internal failure;
- wheel and checkout pass the same end-to-end scenarios.

## Test matrix

Minimum focused coverage:

| Layer | Scenario | Required assertion |
|---|---|---|
| parser | recognized 0.1 project/user state | `install-state-legacy`, path, remediation |
| parser | malformed JSON/v2 | `install-state-invalid`, precise location |
| consumer | browse reads legacy selected scope | original diagnostic preserved |
| wizard core | stage failure envelope | immutable, deterministic recovery choices |
| text TUI | Artifacts legacy state | actionable output; Back/Quit/Retry contract |
| curses TUI | Artifacts legacy state | same diagnostic and recovery semantics |
| curses startup | terminal init failure | text onboarding exactly once |
| curses active | unexpected exception | `tui-stage-internal`; no restart |
| safety | every failure above | no tracked project/config/state/store mutation |
| privacy | internal/setup failures | no secret, raw output, or traceback by default |
| regression | installed MCP lifecycle join | Artifacts renders; unique statuses retained |
| regression | setup/reporting | artifact outcome preserved independently |

Before implementation handoff or PR, run:

```sh
git diff --check
make format-check
make lint
make typecheck
make unit
make integration
make e2e
make validate
make coverage
make packaging-check
make docs-check
```

The repository-wide lint gate must include all tracked implementation and test files. Preserve
untracked workspace artifacts unless their ownership and inclusion are explicitly agreed before
claiming the complete gate passes.

## Completion checklist

- [ ] ERR01 characterization tests exist and fail before implementation.
- [ ] ERR02 distinguishes legacy and invalid installation state.
- [ ] ERR03 preserves typed diagnostics through stage loading.
- [ ] ERR04 renders and recovers equivalently in text and curses.
- [ ] ERR05 prevents post-start fallback/restart and types internal failures.
- [ ] ERR06 audits all stage boundaries without exception laundering.
- [ ] ERR07 documents, packages, and hands off release decisions.
- [ ] No automatic migration or state overwrite was introduced.
- [ ] No analytics payload gained local diagnostic context.
- [ ] No registry/artifact compatibility requirement changed.
