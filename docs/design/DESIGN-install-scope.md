# Design: project and user installation scopes

Status: implemented for issue #19

## 1. Context

`aart` currently treats the consumer project as both the destination root and the manifest root.
That is correct for repository-owned configuration, but it cannot express harness configuration
that should apply to every project of the current user. Issue #19 introduces an explicit
`project | user` scope without deriving user paths from project paths: every built-in harness
declares a separately vetted user target for each supported artifact type.

This slice builds on #17's structured outcomes and #18's immutable Install confirmation. It also
defines the scope values that #20 setup and #21 wizard state will consume, so scope resolution is
kept in the domain/application boundary rather than terminal code.

## 2. Goals and non-goals

### Goals

- Add frozen `InstallScope = project | user` data to `Request`; omission remains `project`.
- Add `--scope` to install, status, check, update, and uninstall.
- Reject `--scope user --project DIR` as a usage error before source resolution or mutation.
- Give every built-in profile explicit user targets or a stable one-line unsupported reason.
- Resolve user targets against one injected home directory and retain absolute destinations.
- Keep project and user manifests separate: project state remains
  `<project>/.agent-artifacts/manifest.json`; user state is
  `<home>/.agent-artifacts/manifest.json`.
- Make status/update/uninstall operate only on the chosen manifest and its recorded effects.
- Ask scope in both TUI frontends before source, manifest, or artifact choices are loaded.
- Show every resolved user destination and require confirmation before user-global install.
- Test all user mutations with a temporary home and never touch the developer's real harness files.

### Non-goals

- Infer unsupported global locations from project paths.
- Add a TOML writer for Vibe MCP/hooks.
- Convert OpenCode hook descriptors into plugins or invent a global Tabnine skill/memory format.
- Migrate or combine existing project and user manifests.
- Change project target paths, project defaults, install-mode semantics, or manifest entry schema.
- Add post-install setup (#20) or the persistent full wizard/back stack (#21).

## 3. Domain model and pure resolution

The model adds:

```text
InstallScope = project | user

ProfileTargets
  skills/guidelines/mcp/hooks/memory: optional target records
  unsupported: ArtifactType -> one-line reason

Profile
  existing fields: project targets (backward compatible)
  user: ProfileTargets

Request
  scope: InstallScope = project
  user_home: optional internal adapter injection
```

`user_home` is not a public CLI option. Production resolves it with `expanduser("~")`; tests and
embedded callers may supply a temporary directory. A pure `profile_for_scope(profile, scope,
home)` transformation returns the existing project profile unchanged or an equivalent profile
whose user targets are absolute. Planners therefore continue to consume the same `Profile`
contract and remain unaware of scope.

Target support and reasons are pure profile data. A missing user target is valid only when the
profile gives an unsupported reason. Choice builders use the same resolver as command execution,
preventing preview/execution path drift.

## 4. Official user-target matrix

The following paths were checked against current official documentation on 2026-08-06. `~` is a
template resolved against the selected user's home, not `os.getcwd()` and not the project path.

| Harness | Skills | Guidelines | MCP | Hooks | Memory |
| --- | --- | --- | --- | --- | --- |
| Claude Code | `~/.claude/skills/<name>/` | `~/.claude/rules/` | `~/.claude.json` · `mcpServers` | scripts in managed `~/.claude/hooks/<name>/`; registration in `~/.claude/settings.json` · `hooks.PreToolUse` | `~/.claude/CLAUDE.md` |
| OpenCode | `~/.config/opencode/skills/<name>/` | unsupported: no standalone global guideline discovery target | `~/.config/opencode/opencode.json` · `mcp` | unsupported: catalog hook descriptors are not OpenCode plugin modules | `~/.config/opencode/AGENTS.md` |
| Tabnine | unsupported: no documented Agent Skills discovery location | `~/.tabnine/guidelines/` | `~/.tabnine/mcp_servers.json` · `mcpServers` | unsupported: official CLI hook page does not declare a user-global discovery target | unsupported: official CLI documents project-root `TABNINE.md`, not a global memory file |
| Mistral Vibe | `~/.vibe/skills/<name>/` | unsupported: no global standalone guideline discovery target | unsupported: official target is TOML `~/.vibe/config.toml`, while the merge core is JSON-only | unsupported: official target is TOML `~/.vibe/hooks.toml`, while the merge core is JSON-only | unsupported: no documented always-loaded global instruction file |

Primary references:

- Claude Code: [skills](https://code.claude.com/docs/en/slash-commands),
  [memory and rules](https://code.claude.com/docs/en/memory),
  [directory/settings/hooks scopes](https://code.claude.com/docs/en/claude-directory), and
  [MCP scopes](https://code.claude.com/docs/en/mcp).
- OpenCode: [skills](https://opencode.ai/docs/skills),
  [global configuration](https://opencode.ai/docs/config/),
  [rules](https://opencode.ai/docs/rules/), and
  [MCP servers](https://opencode.ai/docs/mcp-servers/).
- Tabnine: [guidelines](https://docs.tabnine.com/main/getting-started/tabnine-agent/guidelines),
  [MCP setup](https://docs.tabnine.com/main/getting-started/tabnine-agent/mcp-intro-and-setup),
  [CLI hooks](https://docs.tabnine.com/main/getting-started/tabnine-cli/features/hooks), and
  [CLI memory commands](https://docs.tabnine.com/main/getting-started/tabnine-cli/features/commands).
- Mistral Vibe: [configuration and VIBE_HOME](https://docs.mistral.ai/vibe/code/cli/configuration),
  [skills](https://docs.mistral.ai/vibe/code/cli/skills),
  [MCP](https://docs.mistral.ai/vibe/code/cli/mcp-servers), and
  [hooks](https://docs.mistral.ai/vibe/code/cli/hooks).

The Claude hook script directory is an `aart`-managed payload location; the officially discovered
part is the global `settings.json` registration. Commands in the registration use the resolved
absolute script path, so they are independent of the current repository.

## 5. Scope roots, state, and safety

```text
project scope
  effect base: project root
  state root:  project root
  manifest:    <project>/.agent-artifacts/manifest.json

user scope
  effect paths: absolute targets from the scoped profile
  state root:   resolved user home
  manifest:     <home>/.agent-artifacts/manifest.json
```

The user manifest can hold several harness profiles. Existing manifest identity
`(artifact, profile)` keeps those entries independent, and files/merge proofs contain resolved
absolute paths. Entries already record harness, source/subscription, requested/actual install
mode, managed files/hashes, merge identity/hash, and link targets. They do not serialize MCP
descriptors, environment values, credentials, or merged configuration contents.

All action helpers accept absolute paths, so planners need no new effect types. Rebase preserves an
absolute destination; status/update/uninstall also preserve it rather than joining it beneath the
current project. Saving state is redirected through `manifest_root(request)`, never through the
effect base.

## 6. CLI and TUI behavior

CLI examples:

```sh
aart install code-review --profile claude --scope user
aart status --scope user
aart update --scope user
aart uninstall code-review --profile claude --scope user
```

`--scope project` is the default and preserves current behavior. If project and user configuration
both exist, harness-native precedence applies; `aart` never merges their manifests and an action
touches only the explicitly selected scope.

The User TUI sequence becomes:

```text
Harness(es) -> Action -> Scope -> [Install mode] -> scope-specific choices -> Confirm/apply
```

Status selects a scope and immediately renders that scope's manifest. For mutation flows, source,
profile, and manifest loading occur only after scope selection. Unsupported user rows are hidden
when every selected profile rejects them; mixed bundles keep only supported targets and disclose
the hidden count/reason through existing choice metadata.

Install confirmation gains `scope` and `destinations`. User destinations are resolved absolute
paths for every selected artifact/profile effect, de-duplicated in stable order. An affirmative
answer is required before dispatch. Project confirmation keeps its existing root-oriented output.

## 7. DDD and functional boundaries

- Domain: `InstallScope`, immutable profile target data, `Request`, manifest entries and effects.
- Pure application layer: home-template expansion, profile projection, support decisions,
  destination projection, state-root selection, choice filtering, and confirmation rendering.
- Imperative shell: obtain the production home, read/write the selected manifest, resolve sources,
  execute effects, and read terminal input.
- Anti-corruption boundary: the TUI emits one `Request`; command/planner/executor code remains the
  only mutation path.
- Errors-as-values: invalid scope combinations and unsupported explicit selections return usage
  errors; broad selections become structured skips.

## 8. Risks and mitigations

- **Real-home writes in tests:** all command lifecycle tests inject `Request.user_home` and assert
  no path escapes the fixture.
- **Preview/execution mismatch:** both consume the same scoped-profile resolver.
- **Relative-path leakage:** scoped user profiles are absolute before planner invocation; tests
  inspect manifest effects and dry-run actions.
- **Cross-scope removal:** each command loads only `manifest_root(request)`; paired project/user
  fixtures prove the other state and effects remain unchanged.
- **Cross-harness overwrite:** install two profiles into one user manifest and verify both entries
  and destinations survive update/uninstall selection.
- **Custom profiles:** existing flat records remain project targets. An optional nested `user`
  record follows the same target schema; omitted types are treated as unsupported and may declare
  a stable reason in `user.unsupported` for a better CLI/TUI explanation.

## 9. Acceptance mapping

- Core/CLI scope and compatibility default: sections 3 and 6.
- TUI ordering, status, resolved destinations, and confirmation: section 6.
- Vetted per-harness targets and unsupported reasons: section 4.
- Separate state and scope-confined lifecycle: section 5.
- Recorded non-secret user state and multi-harness identity: section 5.
- `--scope user --project` early usage failure: sections 2 and 6.
- Fake-home tests and unchanged project behavior: sections 2 and 8.
- README/help precedence and examples: section 6 and implementation plan.
