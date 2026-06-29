---
name: agent-artifacts
description: Drive the agent-artifacts CLI (aart) to install, sync, and check team AI artifacts (skills, guidelines, MCP servers, hooks, memory) across harnesses
---

# Driving the `agent-artifacts` CLI (`aart`)

You can run `agent-artifacts` (alias **`aart`**) to install and sync a team's AI artifacts —
**skills, guidelines, MCP servers, hooks, and memory files** — from a source-of-truth catalog
into the harness directories of the current project.

## Operating rules (read first)

- **Always use the `aart` subcommands with explicit arguments. Never launch the bare TUI** (`aart`
  with no args) — it needs an interactive terminal you don't have.
- **Pass `--json` on every command** that supports it (`list`, `install`, `status`, `check`,
  `update`, `uninstall`) and parse the result instead of scraping human text.
- **Pass `--yes`** on mutating commands so they never wait for a prompt.
- **Check the exit code**, it is the contract:
  `0` ok · `1` error · `2` usage (bad name/bundle/profile) · `3` network · `4` conflict (needs
  `--force`) · `5` corrupt manifest.
- With no `--repo`/`--source`, the CLI reads its **own bundled catalog** (the install root).
  Add `--repo OWNER/NAME` for a remote catalog or `--source DIR` for a local checkout.
- Operations apply to the **current project directory** unless you pass `--project DIR`.

## Profiles (target harnesses)

`claude` · `opencode` · `tabnine` · `vibe`. Pick the one matching the user's harness; pass
several with `--profile claude,tabnine`. Not every harness supports every type (e.g. `vibe`
has no MCP/hooks) — installing an unsupported type by name is a usage error; via a bundle it's
skipped with a warning.

## Commands

### `aart list` — discover the catalog
```sh
aart list --json                 # everything
aart list --type skill --json    # one type: skill|guideline|mcp|hook|memory
aart list --bundle backend --json
```
When asked "what's available", run this and summarize.

### `aart install <NAME...> --profile <P>` — install artifacts or bundles
```sh
aart install code-review --profile claude --yes --json
aart install --bundle backend --profile claude,tabnine --yes --json   # a curated team set
aart install --all --profile claude --yes --json                      # whole catalog
aart install code-review --source /path/to/catalog --profile claude --link --yes --json
```
- A **bundle** installs a named, possibly-pinned set in one go (`--bundle NAME`).
- **`--dry-run`** prints the plan and touches nothing — use it to preview before committing.
- **`--force`** authorizes overwriting locally-modified files / merge collisions. Only use it
  when the user has authorized overwrites.
- **`--link`** is opt-in and local-only. It symlinks supported directory artifacts (skills and
  hook payloads) to the local catalog checkout; copy remains the default. Use it only when the
  user asks for local/shared/live installs.
- **Memory files** (`CLAUDE.md` / `AGENTS.md` / `TABNINE.md`) default to `prepend` mode,
  wrapping the content in sentinels so it's safely removable later. If the user wants a clean
  file with no tracking markers, add `--memory-mode replace --force`.

### `aart status` — local drift (no network)
```sh
aart status --json
```
Lists installed artifacts; each file is `ok` / `drift` (locally modified) / `missing`, with
`install.mode` showing `copy` or `symlink`. For `install.mode == "symlink"`, changes under
`install.links[].target` are live and do not need `aart update` to propagate. Report broken,
replaced, or retargeted symlinks to the user instead of silently reinstalling. Use this first
whenever the user asks "what's installed" or "did anything change locally".

### `aart check` — remote freshness (opt-in, network)
```sh
aart check --json
```
Compares the installed commit against the catalog's `main`. Reports which artifacts fell behind
and whether the CLI itself is behind, with a suggested next command. Exit `3` = couldn't reach
the remote (changes nothing).

### `aart update` — re-pull and re-apply
```sh
aart update --yes --json                 # everything
aart update code-review --yes --json     # restrict by name (or --bundle / --profile)
aart update --prune --yes --json         # also remove entries dropped from the set
```
Respects local edits: a genuine conflict is written to a `<file>.agent-artifacts-new` sidecar
and the command exits `4` — re-run with `--force` to overwrite. Preview with `--dry-run`.

### `aart uninstall <NAME...> --profile <P>` — reverse an install
```sh
aart uninstall code-review --profile claude --yes --json
```
Removes installed files and merge entries. `--force` removes entries even if locally modified.

### `aart upgrade` — update the CLI itself (offline-capable)
```sh
aart upgrade            # reinstalls via pip --no-index (local wheel if present)
aart upgrade --dry-run  # print the pip command only
```

## Typical workflows

- **"Install the house rules / standard skills for me"** → `aart install --bundle base --profile <theirs> --yes --json`, then summarize what landed.
- **"Am I up to date?"** → `aart status --json` (local) and, if a remote catalog is configured, `aart check --json` (remote). Report drift and the suggested command.
- **"Sync me to the latest"** → `aart update --yes --json`. If it exits `4`, tell the user about the conflict sidecar and ask before re-running with `--force`.
- **Conflict / usage / network failure** → read the exit code and the JSON/stderr message, explain it, and only escalate to `--force` with the user's authorization.
