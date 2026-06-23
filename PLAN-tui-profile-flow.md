# agent-artifacts - Implementation Plan: profile-first TUI flow

Companion to [DESIGN-tui-profile-flow.md](DESIGN-tui-profile-flow.md).

This plan changes the TUI behavior in slices. The first slice fixes the install UX requested by
users: choose profile first, then show only artifacts and bundle rows that make sense for that
profile selection. Later slices make update and uninstall views action-aware.

## 1. Target behavior

The TUI should gather choices in this order:

```text
profile(s) -> action -> filtered artifact/bundle choices -> dispatch
```

For `install`, the choices shown after profile selection must respect:

- profile type support, such as `vibe` not supporting MCP or hooks
- artifact compatibility metadata, such as `tabnine-postgres` only allowing `tabnine`
- strict multi-profile intersection semantics

For example, after choosing `vibe`, the user should not see MCP or hook artifact rows.
For `update`, name/bundle/profile filters narrow together so a TUI row does not refresh
unrelated installed entries.

## 2. Sequential bootstrap

Land this before parallel work starts.

### WP-TUI0 - Pure filtering contract

**Owns**

- `agent_artifacts/tui.py`
- `tests/tui_test.py`

**Purpose**

Define pure helpers for profile-aware install choices, without changing prompt order yet.

**Tests first**

- `artifact_visible_for_profiles` returns true for unrestricted skills across all built-ins.
- It returns false for MCP/hook artifacts when `vibe` is selected.
- It returns true for `tabnine-postgres` with `tabnine`.
- It returns false for `tabnine-postgres` with `claude`.
- It uses intersection semantics for multiple profiles.
- `build_install_choices` hides non-installable artifact rows.
- `build_install_choices` labels complete and partial bundles with hidden counts.

**Implementation**

- Add a pure artifact support predicate that mirrors install command support:
  - `skill -> profile.skills`
  - `guideline -> profile.guidelines`
  - `mcp -> profile.mcp`
  - `hook -> profile.hooks`
  - `memory -> profile.memory`
- Reuse `check_profile_compatibility`.
- Resolve bundles with `resolve_bundle`.
- Extend or replace the private `_Choice` object with enough metadata for partial bundle labels.

**Done when**

```sh
python -m unittest tests.tui_test -v
```

## 3. Parallel work after WP-TUI0

After WP-TUI0 lands, the implementation can be split across subagents:

| Agent | Track | Primary files | Can run in parallel with |
| --- | --- | --- | --- |
| A | Text fallback flow | `agent_artifacts/tui.py`, `tests/tui_test.py` | B, C, D |
| B | Curses flow | `agent_artifacts/tui.py`, `tests/tui_test.py` | A, C, D |
| C | Action-aware update/uninstall design slice | `agent_artifacts/tui.py`, `tests/tui_test.py` | A, B, D |
| D | Docs and integration/e2e coverage | `README.md`, `DESIGN-tui-profile-flow.md`, tests | A, B, C |

Coordination rule: subagents should not change command handlers unless the plan is amended. The
TUI remains a view/request builder over the existing command core.

## 4. Work packages

### WP-TUI1 - Text fallback profile-first install flow

**Wave:** parallel after WP-TUI0
**Suggested owner:** Agent A

**Owns**

- `agent_artifacts/tui.py`
- `tests/tui_test.py`

**Tests first**

- `_run_text` prompts for profiles before artifact choices.
- Selecting `vibe` hides `[mcp] postgres`, `[mcp] tabnine-postgres`, and hook rows.
- Selecting `tabnine` shows `[mcp] tabnine-postgres`.
- Selecting `claude` hides `[mcp] tabnine-postgres`.
- Selecting `claude,vibe` hides MCP and hook rows through intersection semantics.
- Selecting a visible artifact dispatches a request with the chosen profile(s).
- If no install choices remain, `_run_text` returns `0` and does not dispatch.

**Implementation**

- Load profiles before source resolution.
- Prompt for profile(s) first.
- Prompt for action second.
- Resolve the source only for `install` and `update`.
- For `install`, build filtered choices from `build_install_choices`.
- Prompt for artifact/bundle selection after choices are filtered.
- Keep clean quit behavior at every prompt.
- Keep source/profile/project threading action-appropriate.

**Done when**

```sh
python -m unittest tests.tui_test -v
python -m unittest discover -s tests -p "*_test.py"
```

### WP-TUI2 - Curses profile-first install flow

**Wave:** parallel after WP-TUI0
**Suggested owner:** Agent B

**Owns**

- `agent_artifacts/tui.py`
- `tests/tui_test.py`

**Tests first**

- A small fake/stub around `_curses_multiselect` and `_curses_singleselect` proves call order:
  profiles -> action -> filtered choices.
- The filtered choice labels passed to curses for `vibe` exclude MCP and hook artifacts.
- Quitting at profile, action, or choice selection returns `0`.
- Curses failure still falls back to `_run_text`.

**Implementation**

- In `_run_curses`, load `profile_names` before building choices.
- Ask profiles first.
- Ask action second.
- Build filtered choices based on selected profiles and action.
- Ask artifacts/bundles last.
- Continue using `_build_request` and `_dispatch`.

**Done when**

```sh
python -m unittest tests.tui_test -v
```

### WP-TUI3 - Bundle behavior and labels

**Wave:** parallel after WP-TUI0, may be paired with WP-TUI1
**Suggested owner:** Agent A or D

**Owns**

- `agent_artifacts/tui.py`
- `tests/tui_test.py`

**Tests first**

- Complete bundle labels show the normal bundle name/description.
- Partial bundle labels include installable and hidden counts.
- Bundles with zero installable artifacts are hidden.
- Selecting a complete bundle dispatches `Request.bundles`.
- Selecting a partial bundle dispatches `Request.bundles` in the first implementation and relies
  on command-core skip warnings.

**Implementation**

- Use `resolve_bundle` to compute bundle contents.
- Count visible and hidden artifact keys for selected profiles.
- Preserve sorted bundle ordering.
- Keep individual hidden artifact rows out of the choice list.

**Done when**

```sh
python -m unittest tests.tui_test -v
```

### WP-TUI4 - Action-aware update and uninstall views

**Wave:** can start after WP-TUI0, final integration after WP-TUI1
**Suggested owner:** Agent C

**Owns**

- `agent_artifacts/tui.py`
- `tests/tui_test.py`

**Tests first**

- `uninstall` choices are installed manifest entries for selected profile(s), not the whole
  source catalog.
- Uninstalling through the TUI removes only the selected profile's installed entries.
- `update` choices are installed manifest entries for selected profile(s).
- `uninstall` works from the manifest even when source resolution would fail.
- If there is no manifest or no matching installed entry, the TUI returns `0` and does not
  dispatch.
- `update NAME --profile PROFILE` selects the intersection of those filters, not a broad OR.

**Implementation**

- Add a helper to load the manifest through `_common.load_manifest` or a small injected manifest
  loader for tests.
- Build uninstall choices from manifest entries filtered by selected profile(s).
- Build update choices from manifest entries filtered by selected profile(s), with source catalog
  lookups used for labels and compatibility where available.
- Keep install choices catalog-based.
- Adjust update command selection if needed so combined filters narrow together.

**Done when**

```sh
python -m unittest tests.tui_test -v
python -m unittest tests.uninstall_test -v
python -m unittest tests.update_test -v
```

### WP-TUI5 - Docs and end-to-end coverage

**Wave:** parallel after WP-TUI1 shape stabilizes
**Suggested owner:** Agent D

**Owns**

- `README.md` if the TUI behavior is documented there
- `DESIGN-tui-profile-flow.md`
- `PLAN-tui-profile-flow.md`
- optional e2e coverage

**Tests/checks first**

- Confirm the text fallback can run headlessly with `vibe` and does not print hidden artifact
  rows.
- Confirm the existing shell e2e remains green.

**Implementation**

- Document profile-first TUI behavior where users see TUI instructions.
- Note that partial bundles may still produce command-layer skip warnings.
- Keep docs aligned with the final implemented prompt order.

**Done when**

```sh
make test
make validate
```

## 5. Integration order

Recommended merge order:

1. WP-TUI0: pure filtering contract.
2. WP-TUI1 and WP-TUI3 together or back-to-back.
3. WP-TUI2 once the text flow behavior is accepted.
4. WP-TUI4 for update/uninstall action-aware views.
5. WP-TUI5 after behavior is stable.

WP-TUI1 can ship without WP-TUI4 if we want the requested install UX sooner.

## 6. Risks and decisions

### Partial bundles

Decision for first implementation: show partial bundle rows when at least one artifact is
installable for the selected profile set. Dispatch the normal bundle request and let command-core
skip warnings explain hidden targets after the action.

Risk: the user may see warnings for artifacts that were hidden in the TUI. This is acceptable for
the first implementation because bundle attribution and command behavior remain unchanged.

Future option: add a TUI-specific "visible bundle subset" request shape if partial-bundle warnings
become confusing.

### Multi-profile filtering

Decision: use intersection semantics. A row is visible only if every selected profile can install
it.

Risk: selecting many profiles may hide more rows than expected. This is preferable to selecting an
artifact that only applies to some profiles and surprises the user with skips.

### Duplicate artifact names

Decision: do not solve in this TUI change. The current command request and manifest model are
name-centric. A future model change should address typed artifact selection globally.

## 7. Verification gate

Before calling the implementation complete:

```sh
python -m unittest tests.tui_test -v
python -m unittest discover -s tests -p "*_test.py"
make test
make validate
make lint
make typecheck
git diff --check
```

`make lint` and `make typecheck` require the optional dev dependencies. If they are not installed
in the active interpreter, run them from a temporary venv.
