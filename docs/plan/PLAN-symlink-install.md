# agent-artifacts - Implementation Plan: opt-in symlink install mode

Companion to [../design/DESIGN-symlink-install.md](../design/DESIGN-symlink-install.md).

**Status (2026-06-29):** implemented. The shipped slice covers local `--link` installs for
skills and hook payload directories, manifest/status metadata, update/uninstall/check handling,
agent instructions, and verification.

This is a medium-sized feature because the user-facing flag is small, but the correctness
contract spans the model, executor, manifest, status, update, uninstall, and agent instructions.
The default remains copy installs. Symlink mode is explicit, local-only, and visible in metadata.

## 1. Target behavior

Copy remains the default:

```sh
aart install code-review --profile tabnine
```

Symlink mode is opt-in and links installed directory artifacts to the local catalog checkout:

```sh
aart install code-review --profile tabnine --link --source /Users/mifi/code/agent-artifacts
```

Example filesystem result:

```text
<project>/.tabnine/agent/skills/code-review
  -> /Users/mifi/code/agent-artifacts/skills/code-review
```

Changes propagate only when the local catalog checkout changes: local edits, `git pull`, branch
switches, or `aart upstream update` rewriting the local catalog artifact. Remote upstream changes
do not propagate until the local checkout is updated.

`aart status --json` becomes the canonical agent-facing installed-state view:

```json
{
  "artifact": "code-review",
  "type": "skill",
  "profile": "claude",
  "install": {
    "mode": "symlink",
    "requested_mode": "symlink",
    "links": [
      {
        "path": ".claude/skills/code-review",
        "target": "/Users/mifi/code/agent-artifacts/skills/code-review",
        "target_exists": true
      }
    ]
  }
}
```

## 2. Workstream shape

Sequential spine: **WP-0 contract → WP-1 executor/fs → WP-2 planner/install → WP-3 manifest/status
→ WP-4 update/uninstall/check → WP-5 docs/agent instructions → WP-6 verification**.

Some work can run in parallel after WP-0:

- WP-1 executor/fs and WP-3 manifest parsing can start together.
- WP-5 docs can draft early, but final examples depend on WP-3 JSON shape.
- WP-4 should wait for WP-2 and WP-3 so it can rely on real symlink entries.

## 3. Work packages

### WP-0 - Contract and CLI surface

**Owns:** `agent_artifacts/model.py`, `agent_artifacts/cli.py`, `tests/cli_test.py`.

**Tests first**

- `install --link` parses into `Request.install_mode == "symlink"`.
- Existing `install` parses into `Request.install_mode == "copy"` or `None` with copy resolved
  by command code.
- Optional long form, if accepted: `--install-mode copy|symlink`.
- Invalid combinations still fail through existing argparse/`validate_flags` paths.

**Implementation**

- Add `InstallMode = Literal["copy", "symlink"]`.
- Add `Request.install_mode: Optional[str] = None` or a default `"copy"`.
- Add the `install --link` flag. If both spellings are implemented, make `--link` shorthand for
  `--install-mode symlink`.
- Keep default behavior unchanged for every caller that constructs `Request` directly in tests.

**Done when:** CLI parser tests pass and existing install tests still construct `Request`
without modification or with minimal explicit defaults.

### WP-1 - Filesystem and executor action

**Owns:** `agent_artifacts/model.py`, `agent_artifacts/io/fs.py`, `agent_artifacts/executor.py`,
`tests/fs_test.py`, `tests/executor_test.py`.

**Tests first**

- `SymlinkTree(src, dst)` renders in human dry-run output.
- `plan_to_json` emits `{"action": "symlink-tree", "src": ..., "dst": ...}`.
- Executor creates a symlink and parent directory.
- Re-running against the same symlink is idempotent.
- Existing non-symlink destination fails clearly.
- Broken existing symlink is handled deliberately: either replaced only with force support later,
  or treated as a conflict.

**Implementation**

- Add:

  ```python
  @dataclass(frozen=True, slots=True)
  class SymlinkTree:
      src: str
      dst: str
  ```

- Include `SymlinkTree` in the `Action` union.
- Add `fs.symlink_tree(src, dst)`.
- Add executor dispatch, render, and JSON serialization.
- Use absolute normalized targets at execution time. Parent directories are created like
  `copy_tree`.

**Done when:** executor and fs tests pass, and all existing action render/JSON tests are updated
for the new action without changing existing action behavior.

### WP-2 - Planner and install command wiring

**Owns:** `agent_artifacts/planners.py`, `agent_artifacts/commands/install.py`,
`tests/planners_test.py`, `tests/install_test.py`, new `tests/symlink_install_test.py`.

**Tests first**

- Skill copy mode emits `CopyTree`.
- Skill symlink mode emits `SymlinkTree`.
- Hook symlink mode emits `SymlinkTree` plus the existing `MergeJson` registration.
- Explicit `--link` for `guideline`, `memory`, or `mcp` returns `USAGE (2)`.
- Bundle/`--all --link` links skills/hooks, copies or merges non-linkable artifacts normally,
  and emits structured warnings.
- `--link --repo OWNER/NAME` is rejected with `USAGE (2)`.
- `--link --source DIR` succeeds.

**Implementation**

- Thread install mode from `Request` into `plan_install` through the existing `files` mapping or
  a small explicit argument.
- Teach `plan_skill` and `plan_hook` to emit `SymlinkTree` when mode is `symlink`.
- Add command-level validation that symlink mode is allowed only for durable local sources:
  `--source DIR` and editable default local source are allowed; remote/cache sources are rejected.
- Implement linkable-target partitioning:
  - explicit non-linkable target + `--link` → usage error;
  - broad non-linkable target + `--link` → warning and normal copy/merge.
- Include install mode in install summaries and `install --json`.

**Done when:** symlink install creates the expected links in a temp project, broad bundle behavior
is visible in warnings, and default copy install remains byte-for-byte compatible where practical.

### WP-3 - Manifest metadata and status visibility

**Owns:** `agent_artifacts/model.py`, `agent_artifacts/manifest.py`,
`agent_artifacts/commands/status.py`, `tests/manifest_test.py`, `tests/status_test.py`,
`tests/symlink_status_test.py`.

**Tests first**

- A manifest entry with no `install` field parses as copy mode.
- A symlink install entry round-trips with `install.mode`, `requested_mode`, and `links`.
- `dump_manifest` field order is stable.
- `status --json` includes the `install` object.
- `status` distinguishes:
  - `ok (symlink)`
  - `missing`
  - `broken symlink`
  - `retargeted symlink`
  - `replaced`
- Human `status` prints `install=copy` or `install=symlink`.

**Implementation**

- Add immutable manifest metadata records, for example:

  ```python
  @dataclass(frozen=True, slots=True)
  class InstallLink:
      path: str
      target: str
      target_kind: Literal["dir"]

  @dataclass(frozen=True, slots=True)
  class InstallProof:
      mode: InstallMode
      requested_mode: InstallMode
      links: Tuple[InstallLink, ...] = ()
  ```

- Add `install: InstallProof` or optional install proof to `ManifestEntry`.
- Serialize `install` after `source` and before `bundle`/`files`.
- Parse missing install metadata as copy for backward compatibility.
- Extend `_entry_json` and `_print_human` in `status.py`.
- Add symlink-aware local state checks using `os.path.islink`, `os.readlink`, and target existence.

**Done when:** old manifests still parse, new symlink manifests round-trip, and status JSON gives
agents enough data to explain the live link.

### WP-4 - Update, uninstall, prune, and check behavior

**Owns:** `agent_artifacts/commands/update.py`, `agent_artifacts/commands/uninstall.py`,
`agent_artifacts/commands/check.py`, `agent_artifacts/manifest.py`, tests for each command.

**Tests first**

- `update` does not recopy a symlinked skill tree.
- `update --json` reports symlinked tree entries as live-linked or skipped, not copied.
- Hook update still refreshes merge registration for symlinked hook payloads.
- `uninstall` removes the destination symlink and does not delete the target directory.
- `uninstall` refuses to remove a retargeted symlink without `--force`.
- `prune` removes symlink paths, not targets.
- `check --json` reports symlink installs as local/live-linked where remote freshness is not
  authoritative.

**Implementation**

- In update desired-plan reconstruction, preserve each selected entry's install mode.
- Do not execute `CopyTree`/`SymlinkTree` updates for symlink entries whose destination already
  points at the recorded target.
- Keep merge refresh behavior for hybrid artifacts such as hooks.
- In uninstall/prune removal, use manifest link metadata to remove only `path`.
- Add safety checks before removing retargeted links.
- Extend check output with a clear state, for example `live_linked`, for symlink entries.

**Done when:** update/uninstall/check behavior is safe and explicit for linked entries, while copy
entries continue through the existing policy path.

### WP-5 - Agent instructions and user documentation

**Owns:** `skills/agent-artifacts/SKILL.md`, `README.md`,
`docs/design/DESIGN-symlink-install.md`, this plan.

**Tests first**

- Existing content/doc tests pass after updates.
- Any command examples in README use supported flags.

**Implementation**

- Update the agent skill to instruct agents:
  - use `aart status --json` for installed state;
  - treat missing `install` metadata as copy;
  - understand `install.mode == "symlink"` as live-linked to local `install.links[].target`;
  - report broken/retargeted links instead of silently reinstalling;
  - use `--link` only when the user asks for local/shared/live behavior.
- README: add a short "linked local installs" section with the local-checkout propagation model.
- Update the design doc with any decisions closed during implementation, especially flag spelling
  and bundle fallback behavior.

**Done when:** docs match implemented behavior and agents have a clear metadata contract.

### WP-6 - Integration and verification

**Owns:** end-to-end verification across the repo.

**Tests first**

- Add e2e coverage for local `--source` symlink install:
  - install skill with `--link`;
  - edit local source skill;
  - assert consumer path sees the edit through the symlink;
  - status reports `ok (symlink)`;
  - uninstall removes only the symlink.
- Add bundle e2e for mixed linkable/non-linkable artifacts and warnings.

**Required verification**

```sh
PATH=venv/bin:$PATH PYTHONPATH=$(pwd) make test
PATH=venv/bin:$PATH PYTHONPATH=$(pwd) make validate
PATH=venv/bin:$PATH PYTHONPATH=$(pwd) make lint
PATH=venv/bin:$PATH PYTHONPATH=$(pwd) make typecheck
```

**Done when:** full suite and quality gates pass; no non-stdlib runtime dependency is introduced;
copy-mode behavior remains the default in all docs and tests.

## 4. Critical path

`WP-0 → WP-1 → WP-2 → WP-3 → WP-4 → WP-6`.

WP-5 can draft after WP-0 but should finalize after WP-3 and WP-4 settle JSON/status wording.

## 5. Risks and decisions

- **Flag spelling.** Decide whether to ship only `--link` or both `--link` and
  `--install-mode copy|symlink`. Proposal: ship `--link` first; keep enum internally.
- **Bundle fallback.** Proposed behavior is warn-and-copy for non-linkable broad selections. A
  stricter fail-fast mode would be safer but less ergonomic.
- **Durable local source detection.** The implementation must distinguish editable/local source
  roots from remote cache materializations without relying on path names alone.
- **Force semantics.** Replacing existing destinations and removing retargeted symlinks need clear
  `--force` gates.
- **Status vocabulary.** Keep states stable once exposed in JSON because agents will branch on
  them.
- **Relative symlinks.** Absolute targets are simpler and inspectable. Relative links can be a
  later enhancement.

## 6. Definition of done

- Default install path is still copy.
- Symlink install works only for local durable sources.
- Manifest metadata records mode and targets.
- `status --json` exposes mode, target, and link health for agents.
- Update, uninstall, prune, and check handle linked entries explicitly.
- Docs explain that propagation happens only when the local `agent-artifacts` checkout changes.
- Full test, validation, lint, and typecheck gates pass.
