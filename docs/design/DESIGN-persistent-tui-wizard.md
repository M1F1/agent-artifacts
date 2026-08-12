# Design: persistent TUI onboarding and review wizard

Status: implemented for issue #21

## 1. Context

The current text and curses frontends gather values in local variables and immediately move to the
next prompt. They have accumulated narrow navigation exceptions, such as Install mode returning to
Action, but they do not share a session model. Returning from Review to Artifacts cannot preserve a
basket, most screens do not expose the current stage, and mutating maintainer flows leave curses
before their inputs and preview confirmation are collected.

Issues #15 through #20 deliberately left immutable seams for this redesign:

- role and maintainer action choices are data;
- artifact descriptions and compatibility reasons survive choice projection;
- commands return structured outcomes;
- install mode and scope are explicit request values;
- `InstallConfirmation` contains resolved destinations, projected modes, and the setup queue.

Issue #21 turns those values into one explicit wizard/session state shared by text and curses. The
command core remains authoritative. Navigation, rendering, and catalog reads cannot mutate the
consumer project, user configuration, or maintainer catalog.

## 2. Goals and non-goals

### Goals

- Start every interactive session with a short controls/onboarding stage.
- Show an accessible, non-color-only progress stepper on every wizard screen.
- Support one-stage Back navigation in both frontends while preserving valid selections.
- Persist the selected role, action, profiles, scope, mode, source facts, basket, cursor, and scroll
  position in an immutable session value.
- Derive only the stages applicable to the selected role/action.
- Reconcile an edited earlier choice by retaining valid downstream values, removing only invalid
  values, explaining every removal, and requiring affected stages to be reconfirmed.
- Treat selected artifacts and bundles as a persistent basket with count, descriptions, projected
  modes, compatibility warnings, destinations, and setup queue.
- Make Review a separate stage and Finalize the sole transition that may dispatch an install,
  update, uninstall, or upstream mutation.
- Ask for confirmation before quitting a non-empty basket and explicitly state that no changes
  were made.
- Keep text/curses behavior equivalent and usable in narrow terminals without depending on color.

### Non-goals

- Change command, planner, executor, manifest, setup, or upstream mutation semantics.
- Persist an unfinished wizard across process restarts.
- Introduce a GUI framework, async terminal runtime, external dependency, or mutable service
  container.
- Make navigation itself perform filesystem, Keychain, Docker, network, or upstream mutations.
- Hide command failures or parse command prose to infer results.
- Guarantee cursor restoration when the available choice set no longer contains the prior row;
  the nearest valid row is used in that case.

## 3. Ubiquitous language and state model

The wizard domain uses these terms consistently:

- **Stage**: one applicable decision or information screen.
- **Session**: the complete immutable wizard state.
- **Selection**: the value confirmed for one stage.
- **Basket**: ordered artifact/bundle choice identities selected for the pending action.
- **Visited**: a stage displayed at least once.
- **Confirmed**: a stage whose current value has been accepted since the latest relevant edit.
- **Notice**: a visible explanation of a downstream value removed or invalidated by an edit.
- **Finalize**: the only navigation event that yields a dispatchable request.

The pure model lives in a small `agent_artifacts/wizard.py` module:

```text
WizardStage =
  onboarding | role | maintainer_action | profiles | action | scope |
  source | mode | artifacts | upstream_details | review

WizardPosition
  stage
  cursor
  scroll

BasketItem
  kind: artifact | bundle | upstream
  key
  label
  description

WizardNotice
  stage
  value
  reason

WizardSession
  current
  visited
  confirmed
  role
  maintainer_action
  profiles
  action
  scope
  install_mode
  source_label/source_root
  basket
  positions
  notices
  revision
```

All records are frozen and use tuples/frozen sets or read-only mappings. No terminal object,
catalog adapter, manifest, subprocess handle, or secret is stored in the session. URLs and other
maintainer form values may be held only as non-secret selections needed to build the reviewed
request.

## 4. Dynamic stage graph

`stages_for(session)` is a total pure function. It returns only applicable stages, in order.

Common entry:

```text
Onboarding -> Role
```

User path:

```text
Profiles -> Action -> Scope
  Install   -> Mode -> Artifacts -> Review
  Update   ----------> Artifacts -> Review
  Uninstall ---------> Artifacts -> Review
  Status   ---------------------> Review
```

Source resolution is a read-model concern at Artifacts rather than an extra confirmation stage.
The shell stores only its stable local/GitHub/default label and root in the session, then Review
shows those facts (or recorded subscriptions used by Update). Cursor movement never resolves a
source, fetches content, or mutates state.

Maintainer path:

```text
Maintainer action
  Health/Validate -> Review
  Add             -> Upstream details -> Review
  Import          -> Upstream details -> Artifacts -> Review
  Check           ----------------------> Artifacts -> Review
  Update          ----------------------> Artifacts -> Review
  User workflows  -> Profiles -> Action -> ... -> Review
```

The active local catalog root is always shown on maintainer stages. Import candidate discovery is
a read-only query when entering Artifacts. Add/import form details remain editable before Review.
Mutation preview remains part of Review: validation and dry-run may run there, but apply cannot.

If an earlier edit changes the dynamic graph, hidden values remain available only when they are
safe branch-specific defaults (for example the last Install mode). They are not considered
confirmed and cannot leak into a request for another action.

## 5. Pure navigation and invalidation

The model accepts explicit events and returns a new session plus an optional decision:

```text
visit(session, stage)
set_selection(session, stage, value)
advance(session)
back(session)
remember_position(session, stage, cursor, scroll)
reconcile_basket(session, available choices)
request_quit(session)
finalize(session)
```

Invariants:

- `current` always belongs to `stages_for(session)`.
- `back` moves to exactly the previous applicable stage and never dispatches.
- Values are not discarded merely by Back/Next.
- Editing a stage removes confirmation from that stage and every later applicable stage.
- `visited` remains historical, but the stepper renders `[x]` only for currently confirmed stages.
- Finalize is rejected unless every required applicable stage is confirmed and Review is current.
- Repeated Back/Next is deterministic and never duplicates basket items.
- Quit is immediate when the basket is empty; otherwise it yields `confirm_quit`.

Choice reconciliation receives immutable available choices from the application layer. It keeps
selected keys that remain enabled, removes only absent/disabled keys, and emits one stable notice
per removal with the exact compatibility/source/scope reason. It clamps remembered cursor/scroll
positions to the new list. The affected Artifacts and Review stages become unconfirmed.

Changing Action does not erase profiles or scope. Changing Scope reprojects profiles and choices,
then reconciles the basket. Changing Mode keeps bundles whose mixed fallback remains valid and
removes only disabled explicit rows. Changing Role retains the inactive branch's values in memory,
but only the active branch participates in Review or request construction.

## 6. Rendering contract

Every screen begins with a shared pure header projection:

```text
[x] How it works -> [x] Role -> [●] Harness -> [ ] Action
[ ] Scope -> [ ] Mode -> [ ] Artifacts -> [ ] Review

Basket: 3 selected
```

The renderer wraps whole step tokens across lines for narrow terminals and never relies on color:

- `[x]` confirmed;
- `[●]` current;
- `[ ]` future, visited-but-invalidated, or not yet confirmed.

The current stage title and correct interaction hint follow the header. Single-select screens say
`Enter = choose`; multi-select screens say `Space = toggle · Enter = continue`; both include
`Backspace = back · q = quit` where Back is applicable. Text mode uses `b`/`back` because line
editing consumes Backspace.

Onboarding is frontend-specific only in its key labels:

```text
How aart TUI works

  Up / Down    Move between options
  Space        Toggle an item on multi-select screens
  Enter        Confirm this stage and continue
  Backspace    Return one stage without losing choices
  q            Quit

Press Enter to start.
```

The text fallback substitutes numbered/name input and `b`/`back` while explaining that comma-
separated values are multi-select. Onboarding is the first screen even when the frontend falls
back from curses initialization.

Notices render immediately below the header and remain until the affected stage is reconfirmed.
Basket summaries show selected count at every later stage and list labels/descriptions on Review.

## 7. Selector and position behavior

Both adapters consume and return a small navigation result instead of conflating quit, back, empty
selection, and confirmation:

```text
WizardInput
  kind: confirm | back | quit
  selected values
  cursor
  scroll
```

Curses recognizes `KEY_BACKSPACE`, byte `127`, and byte `8` on every wizard screen except
Onboarding. Multi-select receives the session's checked keys and remembered cursor/scroll, so
returning from Review restores the same basket and viewport. Space has no selection effect on a
single-select screen. Disabled rows remain visible with `[-]` and a textual reason.

Text prompts accept `b`/`back` and `q`/`quit` everywhere. Artifact input supports additive/removal
editing over the existing basket rather than rebuilding it from an empty tuple. The prompt always
prints the selected count and full descriptions remain available through `?N`.

## 8. Review and finalization boundary

Review is a pure projection over the session plus current read models. For a User action it shows:

- role and action;
- selected profiles;
- project/user scope and resolved root/destinations;
- catalog source or recorded subscriptions;
- requested Copy/Symlink mode and projected mixed fallback;
- ordered artifact/bundle basket with count and descriptions;
- compatibility removals, disabled/skipped warnings, and expected mutations;
- setup-capable artifact/profile queue from issue #20.

Maintainer Review shows the catalog root, action, non-secret upstream form values, selected tracked
keys/import candidates, validation result, dry-run preview outcome, and expected catalog changes.
Preview is non-mutating and must succeed before Finalize becomes enabled.

Review supports:

- Back/Edit: return one applicable stage with all values intact;
- Finalize: produce one immutable `Request` (or the existing maintainer mutation protocol input);
- Quit: confirm basket abandonment when non-empty.

The application shell asserts a `finalize` decision before calling `_dispatch_result`, `_dispatch`,
or the apply half of `_run_maintainer_mutation`. Curses always tears down before dispatch and before
issue #20's foreground setup runner. Each mutating request dispatches exactly once.

## 9. DDD and functional boundaries

- **Wizard domain:** stages, session, transitions, confirmation, invalidation, basket identity,
  cursor/scroll positions, quit/finalize decisions.
- **Catalog/compatibility read model:** existing artifact, bundle, profile, manifest, source, and
  setup projections supplied to the domain as immutable choices.
- **Application layer:** maps a finalized session to the existing immutable `Request` and
  `InstallConfirmation` values.
- **Adapters:** text/curses keys, terminal dimensions, source/manifest queries, and printing.
- **Mutation boundary:** existing consumer/upstream command services only.

Pure functions never call `input`, curses, `open_source`, manifest loaders, dispatch, filesystem,
network, Keychain, Docker, or subprocess APIs. Expected navigation and validation outcomes are
values, not exceptions. Stage order, basket order, notices, and request selections remain stable.

## 10. Compatibility and migration

- Flag-mode CLI behavior is unchanged.
- Existing `_Choice`, `InstallConfirmation`, request builders, structured outcomes, and setup
  queue projections are reused.
- Existing selector helpers may keep compatibility wrappers for focused tests, but the wizard
  paths use the explicit `WizardInput` result.
- Text test scripts gain the onboarding response and explicit Review/Finalize response. Legacy
  narrow Install-mode Back behavior becomes the general Back transition.
- Maintainer preview/apply/validate sequencing stays authoritative; only input collection and the
  point of apply confirmation move into the wizard.
- A curses initialization failure starts a new text session at Onboarding; it does not attempt to
  serialize terminal-local partial state across frontend failure.

## 11. Failure and safety behavior

How a failure is *presented* is not decided here. This design owns the stage graph and its safety
properties; [`DESIGN-typed-wizard-errors.md`](DESIGN-typed-wizard-errors.md) owns the typed error
contract that every stage in this graph reports through — the diagnostic algebra, the
`WizardStageFailure` record, the placement rule that separates a list-local `Feedback` record from
a stage-blocking record, and the curses fallback boundary. The bullets below state only what this
wizard guarantees; where they touch presentation they defer to that document.

- Back, forward navigation, cursor movement, detail viewing, and basket editing are non-mutating.
- Source/catalog/manifest query errors remain visible and keep their established exit codes. They
  are carried as typed diagnostics, not flattened into a string, and reach the user as the record
  defined by the error contract rather than as a loose line.
- A source or scope edit reconciles choices before Review; stale keys cannot reach a request.
- Empty required selections cannot advance.
- Quit with a basket requires affirmative abandonment; EOF defaults to no mutation.
- Curses errors fall back safely only before dispatch. After dispatch, an unexpected exception is
  reported as an internal defect and the wizard is not restarted.
- Finalize decisions are single-use: a revision identifier prevents a stale Review result from
  dispatching after state changes.
- No secret is stored in wizard state or rendered in Review. A failure discloses no traceback, no
  raw subprocess output, and no value typed during setup.
- A stage that cannot read installation state reports it and stops. The wizard never migrates,
  rewrites, or discards state to make a stage advance.

## 12. Verification and acceptance mapping

- Onboarding and exact controls: shared rendering plus text/curses integration tests.
- Dynamic stepper, accessible markers, narrow wrapping: pure render tests.
- Backspace `KEY_BACKSPACE`/127/8 and text `b`/`back`: selector and flow tests.
- Persistent values, basket, cursor/scroll: pure transition and frontend round-trip tests.
- Selective invalidation and visible reasons: reconciliation tests using profile/scope/mode changes.
- Full Review including source, destinations, descriptions, setup queue, and warnings: projection
  tests over the seams from #16–#20.
- Finalize-only mutation and exactly-once dispatch: text/curses integration tests with spies plus
  real temporary-project lifecycle tests.
- Confirmed quit with non-empty basket: pure decision and frontend tests.
- Maintainer dynamic stages and preview-before-apply: maintainer text/curses tests and existing
  real command-core E2E.
- Repository gates: Ruff format/lint, mypy, catalog/stdlib validation, full unit suite, shell E2E,
  diff whitespace check, and final code-review audit.
