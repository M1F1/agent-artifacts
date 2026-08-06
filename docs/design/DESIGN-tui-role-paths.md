# agent-artifacts - Design: User and Maintainer TUI paths

Companion to [DESIGN.md](DESIGN.md),
[DESIGN-tui-profile-flow.md](DESIGN-tui-profile-flow.md), and GitHub issue #15.

## 1. Context

The bare `aart` TUI currently enters the consumer flow immediately. It can install, update, or
uninstall artifacts, while the maintainer-side upstream features remain available only through CLI
subcommands. The consumer manifest also records a resolved source label but not the catalog
subscription that must be reopened later. Consequently, an update without source flags can fall
back to the packaged catalog even when an artifact was installed from a local checkout or a GitHub
repository.

This change introduces an explicit User/Maintainer boundary at the start of both TUI frontends,
adds guided maintainer workflows over the existing request/command core, and makes consumer source
subscriptions durable.

## 2. Goals

- Make role selection the first interactive decision in the text and curses frontends.
- Keep User mode profile-aware and backed by the existing install/update/uninstall commands.
- Let Maintainer mode add, scan/import, check, update, validate, and inspect a local catalog.
- Preview every maintainer mutation before an explicit apply confirmation.
- Validate the catalog before and after maintainer mutations.
- Make the absolute catalog root visible and reject remote, missing, or unrecognizable mutation
  targets before dispatch.
- Persist enough per-entry source identity for consumer update to reopen the recorded catalog
  without another prompt.
- Keep domain decisions pure and immutable; keep terminal I/O and filesystem/network effects at
  the shell boundary.

## 3. Non-goals and boundaries with later issues

Issue #15 establishes role paths and maintainer operations, but it does not pre-implement the
larger wizard redesign:

- #16 will add normalized artifact descriptions. Choice rows remain constructed in one place so
  descriptions can be added without changing role or dispatch logic.
- #17 will introduce structured action outcomes. This change continues to use command exit codes
  and command rendering; the TUI does not parse stdout.
- #18 will add copy/symlink selection. User request assembly remains the single place that will
  receive `install_mode`.
- #19 will add project/user scope. Catalog subscriptions are per manifest entry and therefore can
  move unchanged into separate scope-specific manifests.
- #20 will add setup installers after consumer installation. Maintainer workflows do not execute
  artifact-owned scripts.
- #21 will add onboarding, dynamic steps, back navigation, and persistent wizard state. Role and
  maintainer action definitions are data, while rendering stays thin, so they can become stages in
  that future state machine. This issue intentionally does not create a competing partial wizard.

## 4. Domain model

### 4.1 Catalog subscription

Add an immutable `CatalogSubscription` value to each new `ManifestEntry`:

```text
CatalogSubscription
  kind: package | local | github
  location: diagnostic/install-time catalog root | local absolute root | owner/repo
  ref: optional branch, tag, or SHA expression
```

The existing `ManifestEntry.source` remains the resolved source label used as the content/version
proof (`local:/...`, `main:<sha>`, or `pin:<sha>`). `subscription` answers a different question:
which catalog should be reopened on the next update?

- `package`: the reviewed catalog beside the installed `agent_artifacts` package (the recorded
  location is diagnostic; update reopens the current installation so virtualenv moves/upgrades do
  not leave a stale path);
- `local`: an explicit local checkout;
- `github`: a repository plus its requested ref (`main` when no explicit ref was supplied).

The field is optional while reading old manifests. A missing field uses the previous source
resolution behavior, so existing manifests remain valid. Every new or refreshed entry writes the
field.

When no source override is supplied, update partitions selected entries by subscription, resolves
and plans every group before any mutation, concatenates the plans, and persists each refreshed
entry with its own source proof and subscription. An explicit `--source`, `--repo`, or `--version`
is an intentional override for all selected entries and becomes their new subscription.

### 4.2 Maintainer context and health

Add immutable domain values for the local catalog view:

```text
MaintainerContext
  root: absolute local path
  catalog: parsed Catalog
  upstreams: parsed UpstreamCatalog (empty when upstreams.json is absent)
  validation_errors: catalog and upstream metadata errors

CatalogHealth
  counts_by_type
  tracked_keys
  untracked_keys
  upstream_statuses
  validation_errors
```

Pure constructors derive counts and tracked/untracked partitions from parsed values. Remote
upstream status resolution stays in the command shell and feeds immutable `UpstreamStatus` values
into the health constructor.

A directory is a valid maintainer catalog when it exists, is local, parses as the standard catalog
shape, and contains at least one recognized catalog marker (`skills`, `guidelines`, `mcp`, `hooks`,
`memory`, `bundles`, or `upstreams.json`). Mutating a GitHub snapshot or an arbitrary empty
directory is rejected. An absent `upstreams.json` is valid and represents zero tracked artifacts.

## 5. Application/command contract

All terminal actions produce immutable `Request` objects. `commands.upstream.run` remains the
single effectful entry point for upstream behavior.

Two read-only upstream actions complete the command core needed by the TUI:

- `upstream validate`: parse the local catalog and upstream metadata and render all validation
  failures with the absolute catalog root;
- `upstream health`: render artifact counts, tracked/untracked totals and keys, validation errors,
  and the tracked upstream statuses that need attention.

The existing `add`, `scan`, `import`, `check`, and `update` actions remain authoritative for
GitHub parsing, candidate discovery, selection, planning, execution, and output. A public
request-based scan query exposes immutable import candidates to selectors; it reuses the same
scanner called by `upstream scan/import`.

## 6. Interactive flows

### 6.1 Entry role

Both frontends first show:

```text
Choose how you want to use aart:
  User       Install, update, or remove harness artifacts from subscribed catalogs.
  Maintainer Do the same, plus import, validate, and refresh catalog upstreams.
```

Blank, `q`, Escape, or EOF exits with status 0 and does not dispatch.

### 6.2 User path

User mode retains the current sequence:

```text
profile(s) -> action -> compatible manifest/catalog choices -> Request -> dispatch
```

Update choices come from installed manifest entries. Catalog compatibility is applied whenever
the artifact is available in the loaded view; a source-specific installed artifact is not hidden
merely because it is absent from the packaged catalog. The update command, not the UI, reopens the
recorded subscriptions.

### 6.3 Maintainer path

The maintainer home always displays `Catalog: <absolute path>` and offers:

1. catalog health;
2. catalog validation;
3. add one upstream;
4. scan and import artifacts, optionally into one bundle;
5. check all or selected tracked upstreams;
6. preview and update selected tracked upstreams;
7. enter User workflows.

The text frontend loops back to the maintainer home after read-only operations and recoverable
errors. The curses frontend uses the same request builders and selections, with thin curses
rendering/input adapters.

### 6.4 Mutation protocol

Every add/import/update mutation follows one protocol:

```text
validate before -> gather/select -> dispatch dry-run preview -> confirm -> dispatch apply
                -> validate after -> print next steps
```

If pre-validation fails, no preview or mutation is dispatched. If preview fails or the user
cancels, no apply request is dispatched. Post-validation failure is returned as a failure even
when the mutation command succeeded, because the working tree needs maintainer attention.

The final guidance names the catalog root and asks the maintainer to review the working-tree diff
and rerun validation. The TUI never stages or commits changes.

## 7. Functional core / imperative shell

The implementation follows the existing functional style:

- frozen dataclasses model subscriptions, contexts, health, roles, and action choices;
- pure functions validate and transform values, partition subscriptions, compute health, and build
  requests;
- errors remain `Ok`/`Err` values at domain/application boundaries;
- command modules own filesystem/network/executor effects;
- text/curses adapters own prompts and rendering only;
- no inheritance hierarchy or mutable service locator is introduced.

The design follows DDD boundaries already present in the repository:

- consumer installation domain: manifest subscriptions and update planning;
- catalog maintenance domain: catalog/upstream validation and health;
- application layer: `Request` construction and command dispatch;
- infrastructure: source resolution, GitHub access, filesystem, and terminal adapters.

## 8. Failure and safety behavior

- The absolute active catalog root is included in context and error messages.
- Maintainer mutation requires a local catalog root; `repo` is never treated as a writable target.
- No filesystem mutation happens before the dry-run succeeds and the user confirms.
- Planning for all consumer subscription groups completes before update executes any action.
- Invalid/corrupt manifests and catalogs retain their established exit codes.
- A failed post-mutation validation is visible and non-zero; changes are not rolled back or hidden.
- Maintainer actions never commit automatically.

## 9. Verification strategy

- Pure unit tests: subscription serialization/resolution/grouping, catalog-context validation,
  health counts, request builders, role/action selection.
- Command tests: validate/health human and JSON output, missing/invalid catalog, subscription-aware
  update.
- Headless text TUI tests: both roles, clean role quit, User dispatch, invalid catalog recovery,
  add preview/apply, import candidate selection, check, update cancellation/apply, and entry into
  User mode.
- Curses integration tests: role is first and both roles route to the correct frontend flow.
- End-to-end test: a fixture-backed Maintainer import/check/update path through real command core
  with network resolution replaced by the established fake upstream adapter.
- Repository gates: Ruff lint, Ruff format check, mypy, full unit suite, shell E2E suite, catalog
  validation, and diff whitespace checks.
