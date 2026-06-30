---
name: agent-artifacts
description: Guide users and maintainers through the agent-artifacts CLI (aart). Use when Codex needs to help decide, plan, install, link, update, check, uninstall, validate, curate bundles, or maintain upstream-tracked AI artifacts. The skill requires gathering requirements first, explaining available CLI options, proposing a plan, getting user confirmation, and only then executing mutating commands.
---

# Agent-Artifacts CLI Decision Skill

Use this skill to help a user or catalog maintainer work with `agent-artifacts` (`aart`), the
CLI that installs team AI artifacts: skills, guidelines, MCP servers, hooks, and memory files.

Your job is not only to run commands. Your job is to help the user choose the right path, make
the tradeoffs visible, and execute only after the user confirms the proposed plan.

## Non-Negotiable Operating Rules

- Never launch the bare TUI (`aart` with no args). Use explicit subcommands.
- Use `--json` for commands that support it and parse JSON instead of scraping human text.
- Use `--dry-run` before mutating commands unless the user explicitly says to skip preview.
- Use `--yes` only after the user confirms the plan for a mutating operation.
- Never use `--force` unless the user explicitly authorizes overwrites/removals after seeing
  the risk.
- Check exit codes: `0` ok, `1` error, `2` usage, `3` network, `4` conflict, `5` corrupt
  manifest.
- Treat `.agent-artifacts/manifest.json` as the installed-state source of truth. Do not infer
  install mode only from files on disk.
- Present example commands in fenced `sh` code blocks that users can copy directly.
- When the user has not already chosen a harness, use `tabnine` as the first profile example.
- If the user asks for an action that may edit their project or catalog, first gather enough
  requirements, present options, recommend a plan, and ask for confirmation.

## Conversation Workflow

Follow this sequence before executing anything that changes files.

1. **Classify the user**
   - **User mode**: The user is inside an application repo and wants to install, link, update,
     check, or remove artifacts for their agent harness.
   - **Maintainer mode**: The user is editing the `agent-artifacts` catalog repo, adding or
     updating artifacts, bundles, or upstream tracking metadata.
   - **Developer mode**: The user is changing the CLI implementation or tests.

2. **Gather requirements**
   Ask only the missing questions that materially affect the command:
   - target project directory, if not cwd;
   - harness profile: `tabnine`, `claude`, `opencode`, or `vibe`;
   - artifact name, bundle name, type filter, or "all";
   - desired mode: copy install, live-link install, update, check, uninstall, maintainer import;
   - source expectation: installed catalog, local catalog checkout, remote catalog, upstream URL;
   - safety constraints: dry-run only, allow writes, allow force, preserve local changes.

3. **Inspect current state when useful**
   Prefer a local, non-mutating command before recommending changes:
   ```sh
   aart list --json
   aart status --json
   aart list --source . --json
   ```

4. **Present options**
   Show the user 2-4 realistic choices. Include what each option changes, its risks, and when
   it is appropriate. Mark one as recommended when the requirements point clearly that way.

5. **Propose a plan and ask for confirmation**
   Include exact commands, whether they are dry-run or mutating, and expected outcomes. Do not
   run mutating commands until the user confirms.

6. **Execute confirmed plan**
   Run commands, parse outputs, summarize results, and explain next steps. If an exit code is
   non-zero, stop and explain before trying another mutating command.

## User Mode: Installing Into A Project

Normal users should rely on the catalog bundled with the installed `aart` tool. Do not push
remote catalog details onto normal users unless they ask for them.

### Discover Available Artifacts

Use when the user asks what can be installed:

```sh
aart list --json
aart list --type skill --json
aart list --bundle backend --json
```

Summarize artifact names, types, descriptions when present, and bundle contents.

### Install From The Installed Catalog

Use for ordinary installs:

```sh
aart install code-review --profile tabnine --dry-run --json
aart install code-review --profile tabnine --yes --json

aart install --bundle backend --profile tabnine,claude --dry-run --json
aart install --bundle backend --profile tabnine,claude --yes --json
```

Decision notes:
- Use a named artifact when the user knows exactly what they want.
- Use a bundle when the user wants a team-standard setup.
- Use `--all` only when the user explicitly wants the entire catalog for a profile.
- If an artifact is incompatible with a profile, explain whether it is a usage error (explicit
  by-name) or a warning/skip (bundle or `--all`).

### Live-Link Install

Use `--link` when the user wants local/live propagation instead of a copied snapshot.

Default command:

```sh
aart install code-review --profile tabnine --link --dry-run --json
aart install code-review --profile tabnine --link --yes --json
```

Explain the mechanics:
- `--link` is opt-in and local-only.
- Without `--source`, `aart` uses the catalog located beside the installed tool itself.
- If `aart` was installed editable from a local `agent-artifacts` checkout, symlinks point back
  to that checkout.
- Pass `--source DIR` only when the user wants a different local catalog checkout.

```sh
aart install code-review --source /path/to/agent-artifacts --profile tabnine --link --dry-run --json
```

- Changes propagate only when the local source path changes: local edits, `git pull`, branch
  switch, or `aart upstream update` in the catalog.
- Use `aart status --json` to show `install.mode`, link targets, and broken/retargeted links.

Never present `--repo` as a live-link option. Remote snapshots cannot be symlink install
targets.

### Check, Update, And Uninstall

Use status before changing installed artifacts:

```sh
aart status --json
```

For freshness:

```sh
aart check --json
```

For update:

```sh
aart update --dry-run --json
aart update --yes --json
aart update --prune --dry-run --json
```

For uninstall:

```sh
aart uninstall code-review --profile tabnine --dry-run --json
aart uninstall code-review --profile tabnine --yes --json
```

Handle conflicts:
- Exit `4` means local drift/conflict. Explain the `.agent-artifacts-new` sidecar or changed
  symlink state.
- Ask before re-running with `--force`.
- For symlink installs, uninstall removes the destination symlink, not the source target.

## Maintainer Mode: Curating The Catalog

Maintainers edit the catalog repo, validate it, manage bundles, and optionally track upstream
origins in `upstreams.json`. Maintainer commands may use `--source`, `--repo`, `GITHUB_TOKEN`,
and `aart upstream ...`.

### Configure GitHub Access

Use `GITHUB_TOKEN` for private repos, GitHub Enterprise repos, and higher rate limits. On
macOS, recommend Keychain:

```sh
printf "GitHub token: "
IFS= read -r -s GITHUB_TOKEN; echo
security add-generic-password -U \
  -a "$USER" \
  -s GITHUB_TOKEN \
  -w "$GITHUB_TOKEN"
unset GITHUB_TOKEN

export GITHUB_TOKEN="$(security find-generic-password \
  -a "$USER" \
  -s GITHUB_TOKEN \
  -w 2>/dev/null)"
```

Tell the user not to put the raw token in shell config files. For GitHub Enterprise, use
`GITHUB_API_URL` or per-source `api_url`.

### Validate A Local Catalog

Run from the catalog repo root:

```sh
aart list --source . --json
aart list --source . --type skill --json
make validate
```

Use `--source .` so the CLI reads the working tree, not the installed package's bundled
catalog.

### Create Or Edit Artifacts

Catalog layout:

| Type | Path | Required entry point |
|------|------|----------------------|
| skill | `skills/<name>/` | `SKILL.md` with matching `name:` frontmatter |
| guideline | `guidelines/<name>.md` | optional frontmatter |
| mcp | `mcp/<name>.json` or `mcp/<name>/` | JSON with `name` and `server` |
| hook | `hooks/<name>/` | `hook.json` with `name`, `events`, and `command` |
| memory | `memory/<name>.md` | optional frontmatter and optional `mode` |

After edits:

```sh
aart install <name> --source . --profile tabnine --dry-run --json
make validate
```

### Create Or Edit Bundles

Bundles live at `bundles/<name>.json`. They support:
- `description`: human summary;
- `extends`: other bundles to compose;
- `includes`: artifact lists by type (`skills`, `guidelines`, `mcp`, `hooks`, `memory`);
- `pins`: artifact name to branch/tag/SHA.

Validate bundle changes:

```sh
aart list --source . --bundle backend --json
aart install --bundle backend --source . --profile tabnine,claude --dry-run --json
make validate
```

### Adopt One External Artifact

Use when the maintainer has a specific GitHub URL:

```sh
aart upstream add skill/domain-modeling \
  https://github.com/mattpocock/skills/tree/main/skills/engineering/domain-modeling \
  --dry-run --json
```

Explain:
- `/tree/` URLs vendor directory artifacts such as skills, hooks, and directory MCP artifacts.
- `/blob/` URLs vendor single-file artifacts such as guidelines, flat MCP, and memory files.
- The `TYPE/NAME` key must match the upstream artifact's own declared name.
- Use `--ref`, `--path`, `--force`, and `--dry-run` as needed.

After preview and confirmation:

```sh
aart upstream add skill/domain-modeling <github-url> --json
```

### Scan And Batch Import External Repos

Use `scan` when the maintainer does not know what a repo contains:

```sh
aart upstream scan https://github.com/org/superpowers/tree/main --json
```

Use `import` after presenting candidates:

```sh
aart upstream import https://github.com/org/superpowers/tree/main --dry-run --json
aart upstream import https://github.com/org/superpowers/tree/main \
  --select skill/code-review \
  --select memory/house \
  --bundle superpowers \
  --bundle-mode append \
  --json
```

Explain import flags:
- `--select TYPE/NAME`: import specific candidates.
- `--bundle NAME`: create/update a bundle with imported artifacts.
- `--bundle-description TEXT`: set description for created/replaced bundle.
- `--bundle-mode append|replace|fail`: choose existing-bundle behavior.
- `--mode auto|manifest|heuristic`: choose discovery mode.
- `--interactive`: prompt for candidate selection only when an interactive terminal is safe.

### Check And Update Tracked Upstreams

Use for artifacts already tracked in `upstreams.json`:

```sh
aart upstream check --all --json
aart upstream check --bundle backend --json
aart upstream update skill/code-review --dry-run --json
aart upstream update --bundle backend --dry-run --json
```

After confirmation:

```sh
aart upstream update skill/code-review --json
aart upstream update --bundle backend --json
```

Review working-tree diffs before committing. Never delete local catalog work just because an
upstream path disappeared.

## Option Presentation Template

When the user request is ambiguous, respond with a concise choice set:

```text
I see three viable paths:
1. Install from the reviewed catalog (recommended): ...
2. Live-link from a local checkout: ...
3. Maintainer import/update: ...

My recommendation: ...
Proposed plan:
- Run ...
- Preview ...
- If you confirm, run ...

Please confirm which path you want.
```

Then wait. Do not execute mutating commands before confirmation.

## Failure Handling

These exit codes are implemented by the CLI. Recovery is the agent's job: stop, explain the
message, and ask before trying a riskier command.

- `1 error`: generic failure or unexpected local IO/planning problem, such as "cannot read",
  "could not hash", or an internal invalid mode. Do not retry blindly; inspect stdout/stderr,
  identify the file or operation that failed, and ask before repairing local files.
- `2 usage`: bad invocation, unknown artifact/bundle/profile, unsupported profile/type
  combination, or incompatible flags. Ask for corrected inputs.
- `3 network`: remote source/check/import failure. Explain repo/API/token access, mention
  `GITHUB_TOKEN` when private GitHub access is plausible, and suggest retry only when the
  failure looks transient.
- `4 conflict`: local drift, merge collision, replace-over-existing-file, import destination
  conflict, or changed symlink path. Summarize what would be overwritten or removed and ask
  before using `--force`.
- `5 corrupt manifest`: `.agent-artifacts/manifest.json` could not be parsed. Stop and ask
  whether to inspect, back up, edit, restore, or remove that manifest; there is no automatic
  repair command.
- Some error paths print plain text even when `--json` was passed. If parsing JSON fails,
  fall back to the exit code plus stdout/stderr, then explain the failure instead of retrying
  blindly.
