# Design: typed stage failures and actionable TUI diagnostics

Status: in delivery; ERR01–ERR06 and ERR08 completed, ERR09-A/B completed, ERR09-C/D and ERR07
pending

## 1. Context

The AART domain already has a typed diagnostic model: `DiagnosticCode`, `Diagnostic`,
`SourceLocation`, `Severity`, `Ok`, and `Err`. Several TUI paths flatten those diagnostics into a
legacy string error, while other paths allow a `ValueError` or another implementation exception to
escape into a broad curses fallback. The result is poor in two distinct ways:

- expected problems lose their code, file location, structured details, and remediation before
  they reach the user;
- unexpected errors after the wizard has started are mistaken for curses initialization failures,
  so a second text wizard starts at onboarding and appears to have forgotten the session.

Two concrete incidents define the initial acceptance boundary.

1. A project containing a 0.1 installation manifest with top-level `repo` and `installed` fields
   reaches Artifacts before the v2 parser reports `missing required field 'installations'` and
   similar schema fragments. The message does not say that legacy state was detected, name the
   affected stage, identify the file as project installation state, or explain migration.
2. An installed artifact was observed by both local status and update checking. Duplicate
   `claude:current` facts violated a marketplace-row invariant and raised `ValueError`. A broad
   `except Exception` treated that application bug as a curses failure and restarted the wizard in
   text mode.
3. A user standing in a canonical registry checkout chose Maintainer, reached Sources, and found
   that the only enabled source — a registry — cannot be used by that role. The wizard printed
   `registry <alias> is ready for source management, but artifact browsing requires the federated
   marketplace view`. Text mode then returned to Sources and allowed a clean quit; curses stored
   the flattened message as a terminal selection failure and exited with status 2. Neither
   frontend named the stage or presented role-appropriate recovery. This is the same failure class
   as incident 1 reaching a different boundary, and it is reproducible from an ordinary
   configuration with no fixture at all.

Incident 3 also exposes a scope error that no amount of better rendering would fix, addressed in
§4 below: the Sources stage asks a User question, and the wizard makes Maintainer answer it.

Validation cannot all happen at startup. Profile, scope, action, source selection, installation
mode, and artifact selection determine which state and compatibility checks are relevant. The
design therefore validates at the earliest point where sufficient context exists and makes every
stage failure explicit and actionable.

## 2. Goals and non-goals

### Goals

- Preserve typed domain diagnostics from the parser/application boundary to terminal rendering.
- Give every TUI failure a stage, operation, stable diagnostic code, concise explanation, relevant
  safe context, and concrete next action.
- Detect legacy installation state as a distinct condition rather than presenting a list of v2
  field errors.
- Keep text and curses behavior equivalent.
- Permit recovery in place when it is safe: retry the stage, go Back, choose another scope/source,
  or quit without losing earlier selections.
- Never restart a wizard because an error occurred after interactive session state exists.
- Restrict curses-to-text fallback to terminal capability/initialization failure before meaningful
  interaction begins.
- Separate expected operational failures from programming defects. Both receive a stable terminal
  presentation, but internal defects must not be mislabeled as user/configuration errors.
- Keep diagnostics safe for terminals and logs: do not expose credentials, setup input values,
  subprocess output, or secret-bearing environment variables.
- Reuse the existing `Diagnostic` and `DomainResult` algebra instead of introducing a parallel
  exception hierarchy for expected failures.

### Non-goals

- Automatically migrate, delete, replace, or repair installation state.
- Make every repository problem block the initial onboarding screen.
- Turn programming errors into successful outcomes or silently continue after invariant failure.
- Add runtime dependencies, a logging framework, or remote crash reporting.
- Change installation-state v2, registry, marketplace, reporting, or setup protocols.
- Include local paths or detailed failure context in usage analytics.
- Bump artifact `requires_aart` because of this executable UX fix.

## 3. Error taxonomy

AART uses three categories. They must remain distinguishable in code, tests, terminal output, and
JSON output where a command exposes it.

### 3.1 Expected domain failure

An expected failure is represented by `DomainErr` and one or more `Diagnostic` values. It is not
raised. Examples include invalid state, legacy state, unavailable source, incompatible artifact,
policy denial, drift conflict, and missing setup prerequisite.

Each diagnostic has:

```text
code          stable machine-readable identifier
severity      error | warning | info
message       one bounded explanation
location      optional source/path/JSON pointer/line/column
remediation   zero or more exact next actions
details       bounded non-secret structured context
```

The initial new diagnostic is:

```text
install-state-legacy
```

It is emitted when installation-state input is valid JSON and has the recognized 0.1 top-level
shape (`repo` and `installed`) instead of v2 (`schema_version` and `installations`). It names the
state path and offers a dry-run migration command. It does not imply that migration will succeed;
source mapping may still require a later, separately typed diagnostic.

Malformed JSON and malformed v2 state remain `install-state-invalid`. Unsupported explicit schema
versions must not be confused with recognized 0.1 state.

### 3.2 Stage failure envelope

The wizard does not invent new domain errors. It attaches presentation context to a `DomainErr` in
an immutable frontend value:

```text
WizardStageFailure
  stage: WizardStage
  operation: load | review | finalize | setup | reporting
  diagnostics: tuple[Diagnostic, ...]
  action: optional user action
  scope: optional project | user
  project: optional absolute local path
  recoverable: bool
  choices: retry | back | quit (subset selected by the adapter)
```

This value is never raised. It is a frontend envelope used by both text and curses renderers. The
domain diagnostics remain authoritative. `project` and other local presentation context are never
copied into analytics events.

The envelope's recovery choices are conservative:

- `retry` only when repeating the read can produce a different result without mutation, for
  example after the user repairs a file or source in another terminal;
- `back` when an earlier stage can select a different applicable scope, source, profile, action, or
  mode;
- `quit` always, with an explicit statement that no pending action was finalized.

### 3.3 Unexpected internal failure

An invariant violation, `TypeError`, unexpected `ValueError`, or adapter bug is not converted into
an expected domain diagnostic deep in the core. The outer frontend boundary catches it only to:

1. restore the terminal;
2. render a stable `tui-stage-internal` diagnostic with the current stage and operation;
3. state that no pending action was finalized (or, if failure occurred after finalize, report the
   already-known artifact outcome separately);
4. exit non-zero without starting another wizard.

Normal output does not include a traceback or exception message because either can contain local
or secret-bearing data. Development diagnostics may expose a traceback only through an explicit
local debug mechanism designed and tested in the implementation task; debug output is never sent
to reporting.

## 4. Validation placement

Validation runs at the earliest boundary with enough information to be correct.

### Startup boundary

Startup continues to validate inputs required for every path:

- user configuration can be parsed and policy applied;
- configured-source metadata required to render Sources is readable;
- terminal capability determines curses versus text before the session begins.

Startup may identify obvious project-state shape for an informational notice, but it must not block
user-scope or maintainer actions merely because project-scope state is legacy. It must not perform
network fetches, migrations, repairs, or artifact compatibility checks.

### Stage-entry boundary

Stage loaders validate inputs that become relevant after choices are known:

- Sources: selected configuration, policy, snapshot health, and availability;
- Harness/Scope/Mode: profile and target compatibility inputs;
- Artifacts: selected scope installation state, marketplace projection, lifecycle join, and
  compatibility;
- Review: exact selected coordinates, current plan inputs, and review binding;
- Finalize: unchanged preconditions, mutation result, setup result, and optional reporting result.

The Artifacts loader is the initial implementation target because it currently flattens
`DomainErr` into the legacy `Err(reason, code)` value.

### Role-scoped stage inputs

A stage must ask the question its role actually has. Sources asks "which catalogs do I consume
from" — a User question about subscriptions. Maintainer's question is different in kind: "which
local checkout am I curating". The wizard currently routes both through one stage and translates
the answer for Maintainer through the 0.1 compatibility bridge
([tui.py:1949](../../agent_artifacts/tui.py)), which accepts only a local directory or a
`github.com/…@main` reference. A registry subscription — the normal thing for a consumer to have
enabled — has no valid translation, so the role dead-ends on its own configuration.

**Decision.** Maintainer curates a checkout and does not consume a subscription. The role
therefore defaults to the current working directory and skips Sources entirely, exactly as it
already behaves when `--source` is passed explicitly; an explicit `--source` continues to win.
The evidence that this is right is that the working path already exists and is strictly shorter:

```text
aart --source .            role -> Maintainer -> Maintainer action   (works today)
aart                       role -> Maintainer -> Sources -> dead end (works today, wrongly)
```

Sources remains untouched for User, which genuinely subscribes. What Maintainer loses is a
question it was never able to answer.

This is deliberately the smaller of two options. Giving Maintainer its own checkout-selection
screen — a picker over known checkouts, recent roots, or a typed path — is a real design with its
own state and validation, and it is **out of scope here**; the default-plus-flag covers the actual
workflow, which is running the tool inside the checkout being curated.

## 5. Functional core and adapter contract

Expected failures use one path end to end:

```text
parser / domain / application
        |
        | Result[T] = Ok[T] | DomainErr
        v
stage loader
        |
        | preserve diagnostics; add WizardStageFailure context
        v
text renderer or curses renderer
        |
        | recovery event: retry | back | quit
        v
same WizardSession (unless user explicitly goes Back or quits)
```

Required changes to the current boundary:

- `_load_user_wizard_read_model` returns `DomainResult[_UserWizardReadModel]`, not the legacy
  `model.Err` with a semicolon-joined reason.
- `ConsumerApplicationService.browse` diagnostics pass through unchanged.
- TUI stage handlers convert a `DomainErr` to `WizardStageFailure`; they do not concatenate it and
  terminate immediately.
- one shared pure renderer projects a stage failure into terminal lines; curses and text only own
  interaction mechanics.
- expected IO adapters return typed diagnostics with a path/location rather than raising ordinary
  exceptions.

Legacy `agent_artifacts.model.Err` remains only where the pre-1.0 compatibility command surface
still requires it. New canonical TUI/application plumbing must not convert `DomainErr` into it.

## 6. Rendering contract

An expected failure is concise first and detailed enough to act on:

```text
Artifacts could not be loaded

error [install-state-legacy]: AART 0.1 installation state was detected.
  project: /Users/mifi/code/agent-artifacts
  path: /Users/mifi/code/agent-artifacts/.agent-artifacts/manifest.json

Next steps:
  Preview migration:
    aart migrate state --from 0.1 --scope project --dry-run
  Or go Back and select User scope.

Retry = r, Back = b, Quit = q
```

If migration preview later cannot resolve an artifact, its own typed diagnostic is rendered:

```text
error [state-migration-source-missing]: No configured source resolves
memory/superpowers@tabnine.
  Enable and sync a compatible source, or provide:
    --source-map memory/superpowers@tabnine=SOURCE_ALIAS
```

Rendering rules:

- show the stage and the failed operation once;
- show every diagnostic code;
- show location path and pointer when present;
- render remediation as commands/instructions, never as an unlabelled paragraph;
- preserve deterministic diagnostic ordering;
- wrap safely for narrow terminals and do not rely on color;
- do not display raw exception text for internal failures;
- never claim “no changes were made” after a finalize boundary unless the known outcome proves it;
  artifact/setup/reporting outcomes remain independently reported.

### Diagnostic placement

The lower pane introduced by the legibility work is the right place for a **list-local** problem,
not for every failure. The two presentations have different jobs:

- When the list remains usable — for example Enter lands on a disabled artifact, a selected
  installation mode becomes unavailable, or an effect row cannot be approved — the fixed-height
  pane below the list temporarily renders a `Feedback` record. It contains the diagnostic code,
  bounded explanation, and the next available action. It replaces the cursor-detail record rather
  than being appended below it, so the list geometry and pinned status bar do not move.
- When a stage cannot produce its list or review at all — for example Artifacts cannot load, a
  source cannot be read, or a pre-finalize review fails — there is no useful list to leave behind.
  Curses opens the same scrollable record view used by `?`, headed by the failed stage and
  operation; text prints that record immediately before the Retry/Back/Quit prompt. This is the
  authoritative presentation for `WizardStageFailure`.
- Setup happens after the payload outcome is known and curses has already yielded the terminal.
  Its failure is a bounded terminal record that first states the payload outcome, then the setup
  status and manual `SETUP.md` route. It must never be squeezed into a stale artifact pane or say
  that the payload was rolled back.

The status bar is never the sole error surface: it is intentionally terse and may degrade under
width pressure. The pane/record carries the code and recovery; the bar only advertises the keys
that act on it. This gives a selection error the low, stable placement suggested by the artifact
view without hiding a stage-blocking diagnostic under a list that does not exist.

## 7. Curses fallback boundary

There are currently broad exception handlers in both `run` and `_run_curses`. They may invoke
`_run_text` after arbitrary code has already executed. The replacement contract is:

```text
before wizard interaction:
  curses import/setup/terminal capability failure -> start text wizard once

after wizard interaction starts:
  expected DomainErr -> render stage failure in the current frontend
  unexpected exception -> restore terminal, render tui-stage-internal, exit non-zero
  never start a second wizard
```

The implementation records whether the curses callback reached session initialization. Fallback
is allowed only while that boundary has not been crossed. Prefer catching the narrow curses
initialization error type where possible. Broad catching remains only at the outermost crash
boundary for terminal restoration and typed internal-error rendering, never for fallback.

## 8. State and mutation safety

- Stage loading and error rendering are read-only.
- Retry repeats only the failed read/review preparation; it never replays Finalize.
- Back uses the existing immutable `WizardSession` navigation and basket invalidation rules.
- A legacy or invalid state file is never overwritten, renamed, or migrated automatically.
- Migration remains preview-first and requires explicit `--apply`.
- Source synchronization remains an explicit reviewed operation; an error message cannot perform it.
- Reporting failure remains warning-only after an artifact outcome and cannot change that outcome.
- An internal failure after a partial/finalized operation must render the known outcome before the
  internal diagnostic and must not state that the operation was rolled back unless rollback is a
  typed result.

## 9. Diagnostic safety and compatibility

Diagnostic details are allowlisted. They may contain artifact coordinates, profile, scope, stage,
diagnostic code, schema version, and the local state path shown to the local user. They may not
contain credentials, environment values, setup input contents, raw stdout/stderr, arbitrary file
contents, or raw exception messages.

This is an executable UX and error-contract correction:

- it does not change registry schemas or generated registry evidence;
- it does not require an artifact version bump;
- it does not add or raise per-artifact `requires_aart`;
- release/version selection is a separate release task and should follow normal SemVer policy;
- CLI JSON diagnostics should retain existing fields and may add stage context only through an
  explicitly versioned/compatible output contract.

## 10. Acceptance criteria

1. Recognized 0.1 project state produces `install-state-legacy`, the exact state path, and migration
   preview remediation when entering project-scope Artifacts.
2. Malformed state produces `install-state-invalid` and its parser location without being
   mislabeled legacy.
3. The same typed domain diagnostic reaches text and curses renderers without message flattening.
4. A recoverable Artifacts failure offers Retry, Back, and Quit and preserves prior selections.
5. Going Back permits User scope to proceed even when project state is legacy.
6. An unexpected failure after session initialization renders `tui-stage-internal`, exits
   non-zero, and does not display onboarding a second time.
7. A genuine curses initialization failure starts the text wizard exactly once.
8. No failure path mutates the manifest, configuration, source store, object store, project files,
   setup state, or analytics.
9. Terminal output contains no raw secret, setup input, environment value, or traceback by default.
10. Existing canonical project/user workflows, lifecycle JSON commands, setup, and reporting tests
    remain green.

## 11. Open implementation decisions

The implementer must resolve this narrowly and record the choice in the plan/task notes:

- whether startup shows a non-blocking legacy-state notice before Role or relies exclusively on the
  first affected stage. The stage diagnostic is mandatory either way.

## 12. Delivery record

ERR01–ERR04 are implemented. The renderer is a pure `WizardStageFailure` projection shared by
text and curses; it uses the layout kernel's bounded wrapping and an explicit non-secret detail
allowlist. Retry is available in both frontends and repeats only the read-model load. Back uses
the immutable wizard transition, and Quit preserves the existing basket-discard confirmation.
Stage-blocking failures use the full scrollable record; the fixed lower pane remains for
list-local feedback only.

The retained 0.1 command bridge carries an adapter-only nonzero exit status for the existing
command surface. It is not rendered and never removes canonical recovery choices. This preserves
the narrow compatibility boundary without extending the legacy protocol or changing v1 artifact
validity.

ERR05 is also implemented. `InternalFailureContext` is a mutable imperative-shell value containing
only the last safe stage and operation; it never enters the persistent session, reporting, or
analytics. Default internal records are redacted and nonzero. `AART_DEBUG=1` is the explicit
local-developer mechanism for a traceback on stderr; it never changes normal terminal stdout or a
reporting payload. The capability probe falls back to text only for a missing curses import or a
TTY `OSError`; all other errors use the redacted internal record.

ERR06 is implemented. The audit distinguishes a usable Sources list from a blocked stage: a source
selection validation error becomes a bounded, code-bearing fixed lower-pane feedback record in
curses (and the equivalent compact text feedback), while post-selection source loading and the
narrow legacy bridge use the full `Sources` stage record with conservative Back/Quit recovery.
Review preparation and finalization preserve canonical `DomainErr` in both consumer and curation
flows. If expected finalization fails after curses has restored the terminal, the shell prints the
same safe, typed terminal record and exits rather than restarting the wizard or presenting a raw
diagnostic line. Source-add/sync/refresh failures remain local to source setup, and
setup/reporting remain post-outcome warning paths until ERR09 introduces their dedicated bounded
effect record and manual `SETUP.md` route. No error context is copied into reporting or analytics.

ERR08 is implemented. The default Maintainer route carries the pure
`WizardSession.maintainer_checkout` fact, set only when no `--source` or `--repo` was supplied.
Its stage graph omits Sources, uses the absolute current working directory as the curation root,
and therefore makes Back from Maintainer action return directly to Role. User still asks the
subscription question. An explicit source/repo continues through Sources and its typed ERR06
compatibility bridge. This changes only navigation and read-only context selection; it does not
select, synchronize or write a source, and it does not change registry protocols or analytics.
