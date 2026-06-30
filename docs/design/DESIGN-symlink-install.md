# agent-artifacts - Design: opt-in symlink install mode

Companion to [DESIGN.md](DESIGN.md), focused on consumer-side installs that should stay
live-linked to a local catalog checkout instead of being copied into every project.

**Status (2026-06-29):** implemented for local directory artifacts. Copy remains the default;
`--link` is opt-in and records visible install metadata in the consumer manifest/status output.

## 1. Goal and scope

The current install model is intentionally snapshot-like: artifacts are copied or merged into
the consumer project, and the manifest records enough proof to check drift and uninstall. That
must remain the default because it is stable and reproducible.

There is also a real local-development and shared-catalog use case: the same skill is installed
into many repositories, and when the local source-of-truth checkout changes, every installed
copy should see the change immediately. Symlink install mode solves that for artifacts that are
physically installed as directories.

**In scope**

- Add an explicit opt-in symlink mode, with copy mode still the default.
- Support symlink mode only for stable local sources, primarily `--source DIR` and the editable
  default source checkout.
- Record install mode and link targets in the consumer manifest.
- Make the mode visible to humans and agents through install output, `status`, and JSON.
- Keep catalog listing and installed-state reporting distinct.

**Out of scope**

- Making symlink installs the default.
- Symlinking from remote/cache snapshots.
- Symlinking merge-only artifacts such as MCP config entries.
- Solving version pinning for live-linked installs. Symlink mode is deliberately "live", not
  reproducible.
- Windows-specific junction behavior in v1.

## 2. Current code findings

The relevant current paths are:

- [`agent_artifacts/cli.py`](../../agent_artifacts/cli.py) parses install flags into
  `Request`.
- [`agent_artifacts/commands/install.py`](../../agent_artifacts/commands/install.py) resolves
  source, catalog, profiles, and manifest, then calls `planners.plan_install`.
- [`agent_artifacts/planners.py`](../../agent_artifacts/planners.py) emits `CopyTree` for
  skills and hook payloads, `WriteFile` for guidelines and memory, and `MergeJson` for MCP and
  hook registrations.
- [`agent_artifacts/executor.py`](../../agent_artifacts/executor.py) executes `CopyTree`,
  `WriteFile`, `MergeJson`, `RemovePath`, `Warn`, and manifest writes.
- [`agent_artifacts/manifest.py`](../../agent_artifacts/manifest.py) serializes
  `ManifestEntry`. Existing entries do not have an install-mode field.
- [`agent_artifacts/commands/status.py`](../../agent_artifacts/commands/status.py) is the
  local installed-artifact listing. It reads only `.agent-artifacts/manifest.json` and local
  disk, which makes it the right agent-facing surface for "what is installed here?"
- [`agent_artifacts/commands/list.py`](../../agent_artifacts/commands/list.py) is a catalog
  browser. It does not read a consumer project today, so it should not be the primary place
  for installed-mode metadata.

The natural seam is the existing `CopyTree` action. Symlink mode should add a sibling action
for directory links, then carry that proof into `ManifestEntry` and `status`.

## 3. CLI contract

Add an opt-in install mode flag:

```sh
aart install code-review --profile tabnine --link
aart install --bundle backend --profile tabnine --link
```

Equivalent long-form spelling is acceptable if the CLI wants an extensible enum:

```sh
aart install code-review --profile tabnine --install-mode symlink
aart install code-review --profile tabnine --install-mode copy
```

Proposal: expose `--link` as the friendly flag and model it internally as
`Request.install_mode = "symlink" | "copy"`.

Default remains copy:

```sh
aart install code-review --profile tabnine
```

### Local-source requirement

Symlink mode is valid only when the source root is a durable local checkout:

- `--source DIR`: allowed.
- editable default source rooted at the local `agent-artifacts` checkout: allowed.
- remote `--repo` snapshot/cache: rejected with `USAGE (2)`.

Reason: linking to cache materialization would make installs depend on cache retention and
would be surprising to agents inspecting the manifest later.

## 4. Linkable targets

Symlink mode applies to install actions that place a directory tree into the project.

| Artifact type | Current install action | Symlink behavior |
| --- | --- | --- |
| `skill` | `CopyTree(skills/<name>, profile skills dir)` | Link the installed skill directory to the source skill directory. |
| `hook` | `CopyTree(hooks/<name>, scripts dir)` plus `MergeJson` registration | Link the hook payload directory, still merge the registration normally. |
| `guideline` | `WriteFile` | Not linkable in v1. |
| `memory` | `WriteFile` | Not linkable in v1. |
| `mcp` | `MergeJson` only | Not linkable in v1. |

Selection behavior should mirror existing unsupported-profile behavior:

- Explicit by-name request for a non-linkable artifact with `--link`: `USAGE (2)`.
- Bundle or `--all` request with `--link`: install linkable targets as symlinks, install
  non-linkable targets normally, and emit a structured warning.

This makes bundle installs useful without hiding what happened.

## 5. Model and executor changes

Add a new action beside `CopyTree`:

```python
@dataclass(frozen=True, slots=True)
class SymlinkTree:
    src: str
    dst: str
```

Planning:

- `plan_skill(..., install_mode="symlink")` emits `SymlinkTree` instead of `CopyTree`.
- `plan_hook(..., install_mode="symlink")` emits `SymlinkTree` for the payload and keeps the
  existing `MergeJson` action.
- Write/merge-only planners ignore copy mode, but reject symlink mode when explicitly selected.

Execution:

- Create the parent directory for `dst`.
- If `dst` is already a symlink to the same resolved `src`, no-op.
- If `dst` exists and is not the same symlink, fail unless `--force` is explicitly wired into
  the plan/executor path for replacing managed installs.
- Use an absolute, normalized target in v1. Relative symlinks can be a later option.

Rendering:

```text
symlink-tree /path/to/catalog/skills/code-review -> /path/to/project/.claude/skills/code-review
```

JSON dry-run:

```json
{
  "action": "symlink-tree",
  "src": "/path/to/catalog/skills/code-review",
  "dst": "/path/to/project/.claude/skills/code-review"
}
```

## 6. Manifest metadata

The manifest must make the install mode visible even when no command output is available.
Existing manifests are treated as copy installs.

Add optional install metadata to `ManifestEntry`:

```json
{
  "artifact": "code-review",
  "type": "skill",
  "profile": "claude",
  "source": "local:/Users/mifi/code/agent-artifacts",
  "install": {
    "mode": "symlink",
    "requested_mode": "symlink",
    "links": [
      {
        "path": ".claude/skills/code-review",
        "target": "/Users/mifi/code/agent-artifacts/skills/code-review",
        "target_kind": "dir"
      }
    ]
  },
  "files": {
    ".claude/skills/code-review": ""
  },
  "installed_at": "2026-06-29T12:00:00Z"
}
```

For copy installs, new manifests may write:

```json
"install": { "mode": "copy", "requested_mode": "copy", "links": [] }
```

Parser compatibility:

- Missing `install` means `mode = "copy"`.
- Unknown future install fields should be ignored by old readers and preserved by new readers
  only if the model explicitly supports them.
- The existing `files` map stays in place so uninstall and prune can still identify managed
  paths.

Why an object instead of a flat `install_mode` field: hooks can be partly linked and partly
merged. The entry needs both an entry-level mode and per-link path details.

## 7. Status and agent-facing output

`aart status` is the installed-artifact list and should be the canonical agent-facing command.
It should show install mode in both human and JSON output.

Human output:

```text
repo: M1F1/agent-artifacts
1 installed artifact(s):

  skill/code-review  profile=claude  source=local:/Users/mifi/code/agent-artifacts  install=symlink
    .claude/skills/code-review: ok (symlink -> /Users/mifi/code/agent-artifacts/skills/code-review)
```

JSON output:

```json
{
  "repo": "M1F1/agent-artifacts",
  "installed": [
    {
      "artifact": "code-review",
      "type": "skill",
      "profile": "claude",
      "source": "local:/Users/mifi/code/agent-artifacts",
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
      },
      "files": [
        {
          "path": ".claude/skills/code-review",
          "state": "ok (symlink)",
          "kind": "symlink",
          "target": "/Users/mifi/code/agent-artifacts/skills/code-review",
          "target_exists": true
        }
      ]
    }
  ]
}
```

Suggested symlink states:

| State | Meaning |
| --- | --- |
| `ok (symlink)` | Destination is a symlink to the recorded target, and the target exists. |
| `missing` | Destination path is absent. |
| `broken symlink` | Destination symlink exists, but the target is missing. |
| `retargeted symlink` | Destination is a symlink, but points somewhere other than the manifest target. |
| `replaced` | Destination exists but is no longer a symlink. |

Exit code should remain `0` for status, matching today's "drift is informational" behavior.

## 8. Install, update, uninstall, check

Install:

- `install --json` should include install mode and link target for each installed entry.
- Human summary should show `install=copy` or `install=symlink`.
- Warnings for non-linkable bundle members must appear in both human and JSON forms.

Update:

- Copy installs behave as they do today.
- Symlink installs should not recopy linked trees. The target is already live.
- For symlink entries, `update` can still refresh merge actions such as hook registrations.
- JSON should report symlink entries as skipped/live-linked rather than pretending a copy
  happened.

Uninstall:

- Remove the symlink path itself, not the target directory.
- Continue to remove merge registrations for hooks and MCP entries using the manifest's merge
  proof.
- If the symlink was retargeted, require `--force` before removing it.

Check:

- Remote freshness checks remain meaningful for copied installs.
- For symlink installs, report the entry as live-linked/local. If the source is `local:<path>`,
  checking remote commit freshness is not authoritative for the installed bytes.

## 9. `list` versus `status`

Plain `aart list` should stay a catalog command. It answers "what artifacts does this source
offer?" and intentionally does not read a consumer project.

Installed mode belongs in:

- `.agent-artifacts/manifest.json`
- `aart status`
- `aart status --json`
- `aart install --json`
- `aart update --json`
- the `skills/agent-artifacts/SKILL.md` agent instructions

If the CLI later adds an installed-state list alias, it should be explicit, for example:

```sh
aart list --installed --project DIR
```

That alias can reuse `status` data internally. It should not overload plain catalog `list`
with project-local metadata.

## 10. Agent information contract

After implementation, update [`skills/agent-artifacts/SKILL.md`](../../skills/agent-artifacts/SKILL.md)
so agents know:

- Use `aart status --json` to inspect installed artifacts and install modes.
- Treat missing `install` metadata as `copy` for backward compatibility.
- For `install.mode == "symlink"`, changes under `install.links[].target` are live and do
  not require `aart update` to propagate.
- Report broken or retargeted links to the user instead of silently reinstalling.
- Prefer `--link` only when the user asks for shared/local/live installs.

This is important because agents should not infer from a directory's content alone whether it
is a managed copy or a live link.

## 11. Safety and security

- Symlink mode is explicit and visible. No hidden symlinks.
- Only local durable source roots are allowed.
- Record absolute normalized targets in the manifest.
- Do not follow a user-supplied symlink target outside the resolved artifact root when planning.
- Never remove a symlink target during uninstall; remove only the destination link.
- Detect and report broken links and retargeted links.
- Keep copy mode as the default for reproducibility.

## 12. Test plan

Add focused tests around the new contract:

- CLI parsing: `install --link` sets `Request.install_mode == "symlink"`.
- Planner: skill copy mode emits `CopyTree`; skill symlink mode emits `SymlinkTree`.
- Planner: hook symlink mode emits `SymlinkTree` plus `MergeJson`.
- Install command: `--link --source DIR` creates symlink, writes manifest install metadata,
  and includes mode in JSON output.
- Install command: `--link --repo OWNER/NAME` returns `USAGE (2)`.
- Bundle install: linkable entries are linked, non-linkable entries copy/merge with structured
  warnings.
- Manifest parse/dump: missing `install` defaults to copy; symlink metadata round-trips.
- Status JSON: reports `install.mode`, link target, and link state.
- Broken-link status: reports `broken symlink` without non-zero exit.
- Uninstall: removes destination symlink and does not delete target.
- Update: symlink skill is reported live-linked and not recopied.

## 13. Open questions

1. Flag spelling: only `--link`, or also `--install-mode copy|symlink`?
2. Bundle behavior: should non-linkable artifacts under `--link` warn-and-copy as proposed, or
   should the whole invocation fail unless an extra `--allow-copy-fallback` flag is present?
3. Link target form: absolute symlinks in v1, or relative symlinks when source and project have
   a stable relative path?
4. Retargeted symlink uninstall: always require `--force`, or remove if the manifest proves the
   path was originally managed?
5. Should `check` gain a dedicated `live_linked` state for symlink installs?
