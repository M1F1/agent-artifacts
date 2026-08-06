# Design: TUI copy/symlink installation mode

Status: implemented for issue #18

## 1. Context

The consumer command core already models `InstallMode = copy | symlink`, accepts `--link`, emits
`SymlinkTree` for linkable directory artifacts, records requested and actual modes in the manifest,
preserves those modes during update, and removes only managed link paths during uninstall. The TUI
currently always builds the default copy request and gives an interactive user no mode choice.

Issue #18 adds the missing interaction layer. It must reuse `Request.install_mode` and the existing
install application service; the TUI must not create symlinks, infer completion from stdout, or
reimplement lifecycle policy.

The interaction is also an input to the next issues:

- #19 will replace the fixed Project destination with an explicit project/user scope;
- #20 will add post-install setup entries to the confirmation/review data;
- #21 will move the mode, confirmation, and selection values into a persistent wizard state with
  general Back navigation.

This slice therefore represents mode and confirmation facts as immutable values and keeps rendering
separate from selection policy.

## 2. Goals and non-goals

### Goals

- Offer Copy and Symlink in both text and curses flows for Install only.
- Keep Copy first, recommended, and selected by an empty/default response.
- Pass the choice through `Request.install_mode` to the existing command core.
- Reject a remote-only Symlink choice before artifact selection or mutation, with an actionable
  local-catalog instruction.
- Prevent individual file/merge-only artifacts from reaching the late explicit-symlink usage error.
- Keep bundle selection available and disclose its existing mixed-mode fallback before confirmation.
- Show source, current Project scope/root, harnesses, requested mode, selected rows, and projected
  linked/copied target counts before dispatch.
- Use the #17 result contract for actual per-artifact completion modes.
- Retain the established manifest/update/uninstall safety behavior and cover it end to end.

### Non-goals

- Add user-global scope or model user destinations (#19).
- Add setup installers or a setup queue (#20).
- Implement the complete multi-stage wizard, persistent basket, or general Back navigation (#21).
- Change core eligibility: only skills and hook payload directories are linkable in this version.
- Link remote snapshots, guidelines, memory files, MCP merge entries, or hook registrations.
- Change `--link` compatibility, exit codes, manifest shape, or copy-default behavior.

## 3. Domain and pure application values

The TUI gains frozen presentation/application values:

```text
InstallModeChoice
  mode: copy | symlink
  label: Copy (recommended) | Symlink
  description: user-facing behavior and constraints

InstallConfirmation
  source_label/source_root
  scope: project
  destination_root
  profiles
  requested_mode
  selected_labels
  linked_targets/copied_targets
```

The canonical linkability predicate is a pure artifact-type rule shared by choice decoration and
confirmation counting: `skill` and `hook` are linkable; `guideline`, `memory`, and `mcp` are
copy/merge-only. It mirrors the existing install command policy but never performs an install.

Confirmation target counts are computed from the de-duplicated resolved artifact selection and the
selected profile intersection. Overlapping explicit artifacts and bundles therefore do not inflate
the preview. Counts describe artifact/profile targets, matching completion-summary items.

## 4. Interaction sequence

For the User path:

```text
Role -> Harness(es) -> Action
                       |
                       +-- Install -> resolve source/catalog -> Mode -> Artifacts -> Confirm -> apply
                       `-- Update/Uninstall --------------------> Artifacts -----------> apply
```

### 4.1 Mode screen

Text mode displays:

```text
Installation mode:
  1. Copy (recommended)  Install an independent snapshot into the target harness.
  2. Symlink             Live-link supported skills/hooks to a local catalog;
                         file and merged artifacts use copy semantics in bundles.
Installation mode [1]:
```

Blank input selects Copy. `q` cancels with the shared no-change outcome. `b`/`back` returns to the
Action choice while retaining the selected harnesses. This is a deliberately narrow transition;
#21 will provide general stateful Back navigation.

Curses uses the same ordered labels and descriptions. Copy starts under the cursor. Backspace from
this screen returns to Action, and quit cancels without dispatch.

### 4.2 Local-source validation

The already-resolved `Source` is local only when its structured label is `local:<absolute-root>`.
If Symlink is selected for `main:<sha>` or `pin:<sha>`, the TUI returns usage code 2 before building
artifact choices or dispatching a mutation. The message explains that Symlink needs a durable local
catalog and gives the equivalent flag-mode command shape:

```text
aart install ... --source /path/to/catalog --link
```

Copy remains available for the same remote source. The install command retains its own validation
as defense in depth for non-TUI callers.

## 5. Artifact and bundle choices

Copy mode preserves current rows exactly.

In Symlink mode:

- linkable individual skill/hook rows remain selectable and say they will be symlinked;
- non-linkable individual rows remain visible but disabled, with a concise reason such as
  `copy-only; choose Copy or select a mixed bundle`;
- text input that includes a disabled row is rejected and re-prompted with its reason;
- curses cannot toggle a disabled row and renders the same reason without relying only on color;
- bundle rows remain selectable because the command core intentionally supports mixed fallback;
- each bundle row shows de-duplicated projected counts such as `2 linked, 3 copied`, plus any
  existing profile-compatibility hidden count.

This prevents an explicit non-linkable row from producing a late opaque error without changing the
established broad bundle semantics.

## 6. Confirmation contract

Install receives a confirmation step after artifact selection and before the only mutating
dispatch. Both frontends project the same immutable `InstallConfirmation`:

```text
Confirm installation
  Source: local:/catalog (/catalog)
  Destination: Project — /consumer/project
  Harnesses: claude
  Requested mode: Symlink
  Projected modes: 2 linked, 3 copied
  Selected: backend
```

The destination is the absolute current project root. #19 will replace the fixed scope field with
the selected scope and scope-specific resolved destinations. The selected rows are user choices;
projected counts come from resolved catalog artifacts.

Declining or EOF emits the shared cancellation/no-change outcome. Accepting builds one immutable
`Request` with `install_mode` and dispatches exactly one mutating command. Curses confirmation
happens before the wrapper exits; command execution and the #17 completion summary happen only
after terminal teardown.

## 7. Command and lifecycle boundary

`_build_request` accepts an explicit `install_mode`, defaulting to copy for update/uninstall and
legacy callers. It does not interpret the mode. Install execution remains:

```text
TUI selection -> Request.install_mode -> install.execute -> planner -> executor -> manifest
```

The completion summary uses the actual `ManifestEntry.install.mode` already exposed by #17. Mixed
bundle fallback therefore reports which items were copied and which were linked, independent of
the requested mode.

No update or uninstall changes are expected. Regression/E2E tests prove:

- update retains each entry's recorded requested/actual mode and treats a correct link as live;
- uninstall removes the destination link and leaves the source tree intact;
- manifest metadata continues to record requested mode, actual mode, and link target.

## 8. DDD and functional boundaries

- Domain: existing `InstallMode`, catalog artifacts/bundles, manifest install proof, action outcome.
- Pure application/presentation core: linkability, mode choices, disabled-row policy, selection
  de-duplication, projected counts, and confirmation-line projection.
- Imperative shell: source resolution, terminal reads/keys, curses drawing, filesystem mutation.
- Anti-corruption boundary: the TUI produces `Request`; only the install service understands plans
  and effects. Completion rendering consumes `CommandOutcome`, not command prose.
- Expected cancellation, unavailable source, and disabled selection are explicit values/exit paths,
  not exceptions.

## 9. Compatibility and risks

- Existing TUI tests assume profile -> action -> artifacts. Update them to include the Install-only
  mode and confirmation stages; update/uninstall sequences remain unchanged.
- A bundle can overlap an explicitly selected artifact. Resolve and de-duplicate keys before counts.
- Multiple profiles multiply targets. Report artifact/profile counts, not only catalog members.
- Custom profiles can change destinations, but this issue confirms the absolute project root rather
  than duplicating planner path logic. #19 will add first-class scope destination resolution.
- A curses failure must still fall back to text without performing the queued request.
- A remote source may already have been fetched to display the catalog, but choosing Symlink still
  fails before consumer mutation.

## 10. Acceptance mapping

- Both modes/frontends and Copy default: section 4.1.
- `Request.install_mode` reuse: sections 6-7.
- Remote rejection/local instruction: section 4.2.
- Disabled non-linkable rows and mixed bundles: section 5.
- Source/destination/harness/mode confirmation: section 6.
- Actual completion modes: section 7 and the #17 result contract.
- Update/uninstall safety: section 7.
- CLI/TUI terminology and documentation: mode labels in section 4.1.
- Default, Symlink, cancellation/back, validation, mixed bundle, metadata, update and uninstall
  tests: implementation plan.
