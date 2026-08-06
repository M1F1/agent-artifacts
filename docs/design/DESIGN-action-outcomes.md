# Design: explicit action outcomes and summaries

Status: implemented for issue #17

## 1. Context

The command core currently exposes only an integer exit code. Individual commands print unrelated
payload shapes, and update can succeed without printing anything. The TUI therefore has no stable
domain value describing what happened after dispatch. A zero exit code cannot distinguish an empty
selection, an already-current selection, a real mutation, or an intentional cancellation.

Issue #17 introduces one result contract shared by flag-mode commands, the text TUI, and curses.
The contract must also remain useful to the following issues:

- #18 needs actual copy/symlink mode and mixed-mode fallback per installed artifact;
- #19 needs scope and resolved destinations without changing outcome semantics;
- #20 needs configured/incomplete setup results and retry instructions;
- #21 needs to render the final result after Finalize without parsing command output.

The outcome is therefore immutable application-domain data. Human text and JSON are projections of
that data, not alternate sources of truth.

## 2. Goals and non-goals

### Goals

- Return an explicit structured result for every mutating user and maintainer action.
- Distinguish changed, already-current, empty/not-matched, skipped, conflicted, failed, preserved,
  and cancelled results while retaining the established process exit codes.
- Record the actual install mode for every artifact/profile target.
- Make selected and changed counts independent so an update no-op is unambiguous.
- Keep warnings and recovery instructions adjacent to, but structurally separate from, the final
  summary.
- Render the same counts and item lists in human and JSON output.
- Leave the final summary visible after curses exits and emit it through the text fallback writer.
- Provide pure aggregation and rendering inputs suitable for #18-#21.

### Non-goals

- Add install-mode selection, user-global scope, setup scripts, or wizard navigation from #18-#21.
- Change the meaning of existing exit codes or turn informational drift into a failure.
- Persist transient command outcomes in the consumer manifest.
- Infer success from stdout, executor description strings, or filesystem state after the fact.
- Hide existing warnings, conflicts, action previews, or recovery guidance.

## 3. Domain contract

The model gains frozen values with a closed status vocabulary:

```text
OutcomeItem
  identity: artifact/profile key or maintainer key
  status: installed | reinstalled | changed | up_to_date | removed |
          already_absent | skipped | conflict | failed | preserved |
          scanned | imported | checked | updated | cancelled
  artifact_type/profile/mode/detail: optional structured facts

ActionSummary
  action: install | update | uninstall | upstream.<action> | cancelled
  selected: number of requested/selected domain targets
  items: ordered OutcomeItem values
  warnings: ordered warning strings
  recovery: ordered safe next-step strings
  dry_run: whether effects were only previewed

CommandOutcome
  exit_code: established CLI code
  summary: ActionSummary
  payload: command-specific structured detail retained for compatibility
```

`ActionSummary.counts` and `changed` are derived by pure folds over `items`; callers do not provide
redundant counters that could disagree. An item identity is stable and machine-readable: consumer
artifacts use type/name/profile, while maintainer artifacts use type/name. Detail strings explain a
reason but are never parsed to recover status, mode, or identity.

`selected` means the number of domain targets after explicit request filtering and before outcome
classification. Empty input/cancellation therefore has `selected=0`, while five selected current
artifacts have `selected=5`, `changed=0`, and five `up_to_date` items.

## 4. Execution-result boundary

The executor gains structured per-effect observations in addition to its compatibility
`performed` strings. Before applying an action it determines whether that action will change its
managed target:

- `CopyTree`: recursively compare source and destination trees; equal trees are a no-op;
- `SymlinkTree`: compare link existence and resolved target;
- `WriteFile`: compare desired bytes to the existing file;
- `MergeJson`: compare the managed key/list element to the desired value;
- `RemovePath`: distinguish an existing managed path from an already-absent path;
- `Warn`: record a skipped/conflicted observation without treating the warning itself as a change.

The observation stores operation, target, state (`changed`, `unchanged`, `skipped`, or `failed`),
and an optional error. Commands map observations back to immutable manifest/planner entries by
managed paths and merge proofs. They never inspect a rendered executor string.

No-op actions may be skipped by the shell once equivalence is proven. This avoids rewriting files
or directories merely to report them as current. Unexpected effect failures are returned in the
execution report rather than erasing earlier observations; command policy decides the existing
non-zero exit and whether manifest persistence is safe.

## 5. Command contracts

Each mutating command exposes `execute(request) -> CommandOutcome`. Its existing
`run(request) -> int` remains the CLI compatibility wrapper: execute once, render the outcome once,
and return `outcome.exit_code`. The TUI dispatches the same `execute` function and renders the same
outcome only after the full-screen frontend has closed.

### 5.1 Install

One outcome item is emitted per artifact/profile manifest entry.

- no previous manifest key: `installed`;
- previous key present: `reinstalled`;
- skipped compatibility/support target: `skipped` with its reason;
- planning/execution failure: `failed` or `conflict`.

Every installed/reinstalled item carries `mode=copy|symlink`, taken from the actual `InstallProof`,
not only the requested flag. Human output groups copy and symlink targets; JSON exposes the same
items and derived counts. An empty broad selection succeeds with an explicit zero-change summary.

### 5.2 Update

Selection and mutation are classified independently. Each selected manifest entry becomes:

- `changed` when at least one managed effect changed;
- `up_to_date` when all desired effects were already equivalent;
- `skipped` when the artifact disappeared or compatibility excluded it;
- `conflict` or `failed` when policy/execution prevented completion.

The final line follows the canonical form:

```text
Updated 0 artifacts; all 5 selected artifacts are already up to date.
```

No matching manifest entries is a different result: selected zero, an empty/not-matched detail,
and `No installed artifacts matched the selected harness and filters.`

### 5.3 Uninstall

One item is emitted per selected manifest entry. It is `removed` when the manifest entry is
removed, even if one or more managed filesystem/config targets were already absent. Managed target
observations additionally count removed vs already-absent paths/config entries. Sentinel rewrites
and restored backups are `preserved` details when they retain user content.

No match succeeds explicitly:

```text
Removed 0 artifacts; no files were changed.
```

Changed symlinks/merges that require `--force` remain conflicts and retain the existing conflict
exit code.

### 5.4 Maintainer actions

- validate/health: checked counts plus validation/attention items;
- scan: scanned candidates and a zero-candidate result;
- import/add: imported, skipped, and conflicted item lists;
- upstream check: checked statuses, including up-to-date and update-available;
- upstream update: selected, updated, up-to-date, skipped, conflicted, and failed items.

Preview and validation output used by the maintainer flow remains visible. After an apply sequence,
the applied action summary is the final outcome; cancellation emits a `cancelled` result with
`selected` preserved where known and states that no changes were made.

## 6. Rendering and JSON compatibility

`outcomes.py` contains pure projections:

- `summary_to_dict(summary)` returns action, selected, changed, no_changes, counts, ordered items,
  warnings, recovery, and dry-run;
- `render_summary(summary)` returns lines with the canonical headline followed by grouped items,
  warnings, and recovery instructions.

Existing JSON fields remain during migration. Every mutating JSON response also receives a
required `summary` object produced from the same `ActionSummary` used for human output. Existing
human details/previews may precede the summary, but the final non-empty block is always the shared
summary so it remains visible after TUI completion.

Warnings and recovery instructions are rendered after the headline and are never replaced by it.
Secrets are not outcome fields; later setup results may contain only redacted, non-secret status.

## 7. TUI behavior

The curses frontend still gathers choices inside `curses.wrapper`, then returns to the normal
terminal before dispatch. It receives a `CommandOutcome` through result dispatch and renders the
summary after curses teardown. The text fallback uses its injected `write` function for the same
rendered lines, which makes behavior testable without capturing global stdout.

All pre-dispatch exits become explicit outcomes:

- quitting/cancelling: `Cancelled; no changes were made.`;
- empty artifact selection: `No artifacts selected; no changes were made.`;
- no choices for the selected filters: action-specific no-match summary.

These outcomes return zero and do not dispatch a mutating request.

## 8. Functional core and DDD boundaries

- Domain: frozen outcome values and their status vocabulary.
- Pure application core: item aggregation, counts, headline selection, JSON projection, and mapping
  structured executor observations to artifact entries.
- Imperative shell: filesystem comparison/mutation, network access, terminal input, and printing.
- Anti-corruption boundary: commands translate executor/upstream planner records into outcome
  items; UI code never understands planner action strings.
- Expected conflicts and failures remain values with exit codes; exceptions are reserved for
  programmer errors or are converted at the shell boundary.

The dependency direction is:

```text
planner entries + executor observations -> pure outcome mapping -> CommandOutcome
                                                            |-> CLI renderer
                                                            `-> TUI renderer
```

## 9. Compatibility and risks

- **Legacy tests/consumers expect top-level JSON fields.** Preserve them and add `summary`.
- **Tree equality can be expensive.** Compare deterministic relative file sets and stream SHA-256;
  catalog artifacts are small and comparison avoids unnecessary copies.
- **Actions can share a config file.** Map merge results by merge proof identity, not file alone.
- **A partial executor failure can leave effects.** Report every successful and failed observation,
  do not claim atomicity, and do not persist entries whose required effects failed.
- **Duplicate summaries in TUI.** Result dispatch owns final rendering; command `run` owns rendering
  only in flag mode.
- **Future statuses expand.** Add vocabulary deliberately and keep unknown statuses renderable via
  their detail instead of silently counting them as changed.

## 10. Acceptance mapping

- Final text/curses summaries and explicit cancellation: sections 5 and 7.
- Selected vs actually changed update counts and no-op distinction: sections 3 and 5.2.
- Partial success, conflicts, failures, warnings, recovery: sections 3-6.
- Actual copy/symlink modes: section 5.1.
- Manifest entries and already-missing uninstall effects: section 5.3.
- Human/JSON parity: section 6.
- Maintainer counts/no-change: section 5.4.
- Unit/E2E matrix: specified in the implementation plan.
