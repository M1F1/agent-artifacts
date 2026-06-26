# agent-artifacts - Design: profile-first TUI flow

Companion to [DESIGN.md](DESIGN.md), [DESIGN-compatibility.md](DESIGN-compatibility.md),
and the current `agent_artifacts/tui.py` implementation.

The TUI currently asks for artifacts first, then profiles, then action. That ordering exposes
catalog rows the selected profile cannot install. For example, a user can select the `vibe`
profile only after seeing MCP and hook artifacts, even though `vibe` intentionally has no MCP
or hook target. The command core later rejects or skips the target correctly, but the
interactive view is noisy and makes the user discover compatibility by failing.

This design changes the TUI from a catalog-first picker to a profile-first, action-aware picker.
After the user chooses a profile, the artifact and bundle view is filtered to what that profile
can actually use.

## 1. Goals

- Ask for profile before showing installable catalog rows.
- Hide artifact rows that are not usable for the selected profile set.
- Keep the TUI as a thin UI layer over the existing command core.
- Share filtering rules between the text fallback and curses UI.
- Preserve the current clean-quit behavior at every prompt.
- Keep unsupported type and compatibility policy aligned with command behavior.
- Make the work easy to split across subagents after the pure filtering contract lands.

## 2. Non-goals

- Replacing the command handlers or duplicating install/update/uninstall logic in the TUI.
- Adding runtime dependencies.
- Building a full terminal UI framework.
- Changing compatibility metadata semantics.
- Solving global duplicate artifact names across types. The current command and manifest model
  still mostly treats artifact names as global within a selection.

## 3. Current flow

Current text and curses flows both gather:

```text
catalog artifacts/bundles -> profile(s) -> action -> Request -> command dispatch
```

This has three user-facing problems:

- The catalog list is unfiltered, so profile-specific artifacts appear before profile choice.
- Partial profiles, such as `vibe`, still see unsupported MCP and hook rows.
- `update` and `uninstall` use the same catalog view even though those actions are really about
  installed manifest entries.

The command core remains correct enough: explicit incompatible installs return usage errors,
and bundle/all installs skip unsupported or incompatible targets. The TUI view is the part that
needs to become smarter.

## 4. Proposed flow

The new flow is:

```text
profile(s) -> action -> action-specific choices -> Request -> command dispatch
```

The action prompt stays near the front because the choice list depends on it:

- `install` choices come from the source catalog.
- `update` choices come from installed manifest entries, with source catalog metadata available
  for compatibility checks.
- `uninstall` choices come from installed manifest entries only.

The action list should keep `install` first and selected by default in curses.

## 5. Profile selection

Profiles are loaded from `load_profiles(project)`, as today. The menu stays multi-select.

Filtering semantics for multiple selected profiles are intentionally strict:

- An artifact row is visible only when it is installable for **every** selected profile.
- This avoids selecting one row that silently installs for one profile and skips another.
- Users who want profile-specific artifact sets can run the TUI once per profile.

This rule is simple, predictable, and matches the user's mental model: if `vibe` is among the
selected profiles, MCP and hook artifacts are hidden because `vibe` cannot install them.

## 6. Install artifact filtering

An artifact is visible in the install view when all selected profiles pass both checks:

1. Type support: the profile has a target for the artifact type.
2. Artifact compatibility: `check_profile_compatibility(artifact, profile_name).ok` is true.

Examples:

| Selected profile | Visible artifact examples | Hidden artifact examples |
| --- | --- | --- |
| `claude` | skills, guidelines, memory, Claude-compatible MCP/hooks | `tabnine-postgres` |
| `tabnine` | skills, guidelines, memory, Tabnine-compatible MCP/hooks | Claude-only hooks |
| `vibe` | skills, guidelines, memory | all MCP and hook artifacts |
| `claude,vibe` | artifacts supported by both | MCP and hook artifacts |

No hidden artifact should appear as an individual selectable row.

## 7. Bundle filtering

Bundles need a slightly different rule because they can contain mixed artifacts.

Each resolved bundle gets a visibility summary:

- `visible_keys`: artifacts in the bundle that pass the selected-profile filter.
- `hidden_keys`: artifacts hidden because of unsupported type or incompatible profile.
- `is_complete`: true when `hidden_keys` is empty.

Bundle rows are shown when `visible_keys` is non-empty. The label should make partial bundles
obvious:

```text
[bundle] base - 4 artifacts
[bundle] backend - 4 installable, 2 hidden for selected profile(s)
```

Selecting a complete bundle dispatches the normal bundle request.

Selecting a partial bundle may use the existing bundle request in the first implementation. The
command core will skip hidden targets and report warnings, preserving bundle attribution in the
manifest. This means the user will not see hidden artifacts in the selection view, but may still
see a post-action warning explaining what the command skipped.

A later enhancement can add a precise "install visible subset" request shape if we decide partial
bundle warnings are too noisy.

## 8. Update and uninstall views

The current TUI shows catalog rows for all actions. The profile-first redesign should make
`update` and `uninstall` action-aware:

- `uninstall` should show installed manifest entries for the selected profile set.
- `update` should show installed manifest entries for the selected profile set and hide entries
  whose current source artifact is no longer compatible, unless we add an explicit "blocked"
  section.
- Bundle rows for installed entries should be derived from manifest `entry.bundle`.

Update and uninstall requests still dispatch through the command core. Update command filters
must narrow together when names, bundles, and profiles are all present; otherwise a precise TUI
row could update extra entries. Uninstall already uses profile-scoped name selection.

## 9. Pure UI model

Add a small pure model inside `tui.py` or a new `agent_artifacts/tui_model.py` if the helper grows:

```python
@dataclass(frozen=True, slots=True)
class Choice:
    kind: Literal["artifact", "bundle"]
    name: str
    type: Optional[ArtifactType]
    label: str
    hidden_count: int = 0
    complete: bool = True
```

Core helpers:

```python
def artifact_visible_for_profiles(artifact, profile_names, profiles) -> bool:
    ...

def build_install_choices(catalog, profile_names, profiles) -> Tuple[Choice, ...]:
    ...

def build_action_choices(action, catalog, manifest, profile_names, profiles) -> Tuple[Choice, ...]:
    ...
```

The text and curses front-ends should both call these helpers. Tests should target the helpers
directly before testing the prompt flows.

## 10. Request assembly

The TUI should continue to dispatch `Request` objects through `_dispatch`.

For artifact rows:

- `Request.names` contains the selected artifact names.
- `Request.profiles` contains the profile selection.

For complete bundle rows:

- `Request.bundles` contains the selected bundle names.

For partial bundle rows in the first implementation:

- `Request.bundles` may still contain the selected bundle names.
- The command layer remains responsible for skipping hidden targets and printing warnings.

The TUI filters what it shows, then relies on command policy as the safety net. The one command
semantic this design requires is update-filter intersection: when update receives names,
bundles, and profiles together, all present filters narrow the selected manifest entries.

For `update` and `uninstall`, manifest-backed rows dispatch the same name/bundle/profile request
shape. This is safe because update filters narrow together and uninstall filters names within
the selected profile set.

## 11. Text UI changes

The fallback prompt order becomes:

```text
Select profile(s):
  1. claude
  2. opencode
  3. tabnine
  4. vibe
Profile (e.g. 1):

Action:
  1. install
  2. update
  3. uninstall
Action (e.g. 1):

Source: local:/...
Select artifact(s)/bundle(s) for vibe:
  1. [skill] code-review
  2. [guideline] python-style
  3. [memory] house
Selection (e.g. 1,3):
```

If no choices remain after filtering:

```text
No installable artifacts or bundles for profile(s): vibe.
```

The prompt should return `0` without dispatching in that case.

`uninstall` does not need a source catalog and can show manifest entries even when source
resolution would fail. `install` and `update` still resolve the source after the action is chosen.

## 12. Curses UI changes

The curses UI follows the same order and uses the same choice builder:

```text
profiles -> action -> filtered choices
```

The existing `_curses_multiselect` and `_curses_singleselect` helpers can stay. The main change is
the ordering and rebuilding the choice labels after profile/action selection.

If the terminal fails at any point, fallback remains `_run_text`.

## 13. Testing strategy

Test the pure filtering helpers first:

- `vibe` hides MCP and hook artifacts.
- `tabnine` shows `tabnine-postgres`.
- `claude` hides `tabnine-postgres`.
- Multiple profiles use intersection semantics.
- Complete and partial bundles get the expected labels and hidden counts.

Then test text flow:

- The first prompt is profile selection.
- Selecting `vibe` never displays MCP/hook artifact rows.
- Selecting `tabnine` displays the Tabnine-only MCP row.
- Selecting a visible artifact dispatches the expected request.
- Empty filtered choice sets return `0` and do not dispatch.

Finally test curses enough to prove it uses the same ordering and shared choice builder. Deep
terminal rendering remains best-effort because curses is hard to exercise headlessly.

## 14. Rollout

Ship in two behavioral slices:

1. Install flow: profile-first, compatibility-filtered artifact and bundle choices.
2. Action-aware update/uninstall views based on installed manifest entries.

Both slices continue to dispatch through the command core and can be reviewed independently.
