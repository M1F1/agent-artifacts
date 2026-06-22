---
name: agent-artifacts
description: Drive the agent-artifacts CLI (aa) to install, sync, and check team AI artifacts (skills, guidelines, MCP servers, hooks, memory) across harnesses
---

# Driving the `agent-artifacts` CLI (`aa`)

You can run `agent-artifacts` (alias **`aa`**) to install and sync a team's AI artifacts —
**skills, guidelines, MCP servers, hooks, and memory files** — from a source-of-truth catalog
into the harness directories of the current project.

## Operating rules (read first)

- **Always use the `aa` subcommands with explicit arguments. Never launch the bare TUI** (`aa`
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

### `aa list` — discover the catalog
```sh
aa list --json                 # everything
aa list --type skill --json    # one type: skill|guideline|mcp|hook|memory
aa list --bundle backend --json
```
When asked "what's available", run this and summarize.

### `aa install <NAME...> --profile <P>` — install artifacts or bundles
```sh
aa install code-review --profile claude --yes --json
aa install --bundle backend --profile claude,tabnine --yes --json   # a curated team set
aa install --all --profile claude --yes --json                      # whole catalog
```
- A **bundle** installs a named, possibly-pinned set in one go (`--bundle NAME`).
- **`--dry-run`** prints the plan and touches nothing — use it to preview before committing.
- **`--force`** authorizes overwriting locally-modified files / merge collisions. Only use it
  when the user has authorized overwrites.
- **Memory files** (`CLAUDE.md` / `AGENTS.md` / `TABNINE.md`) default to `prepend` mode,
  wrapping the content in sentinels so it's safely removable later. If the user wants a clean
  file with no tracking markers, add `--memory-mode replace --force`.

### `aa status` — local drift (no network)
```sh
aa status --json
```
Lists installed artifacts; each file is `ok` / `drift` (locally modified) / `missing`. Use this
first whenever the user asks "what's installed" or "did anything change locally".

### `aa check` — remote freshness (opt-in, network)
```sh
aa check --json
```
Compares the installed commit against the catalog's `main`. Reports which artifacts fell behind
and whether the CLI itself is behind, with a suggested next command. Exit `3` = couldn't reach
the remote (changes nothing).

### `aa update` — re-pull and re-apply
```sh
aa update --yes --json                 # everything
aa update code-review --yes --json     # restrict by name (or --bundle / --profile)
aa update --prune --yes --json         # also remove entries dropped from the set
```
Respects local edits: a genuine conflict is written to a `<file>.agent-artifacts-new` sidecar
and the command exits `4` — re-run with `--force` to overwrite. Preview with `--dry-run`.

### `aa uninstall <NAME...> --profile <P>` — reverse an install
```sh
aa uninstall code-review --profile claude --yes --json
```
Removes installed files and merge entries. `--force` removes entries even if locally modified.

### `aa upgrade` — update the CLI itself (offline-capable)
```sh
aa upgrade            # reinstalls via pip --no-index (local wheel if present)
aa upgrade --dry-run  # print the pip command only
```

## Typical workflows

- **"Install the house rules / standard skills for me"** → `aa install --bundle base --profile <theirs> --yes --json`, then summarize what landed.
- **"Am I up to date?"** → `aa status --json` (local) and, if a remote catalog is configured, `aa check --json` (remote). Report drift and the suggested command.
- **"Sync me to the latest"** → `aa update --yes --json`. If it exits `4`, tell the user about the conflict sidecar and ask before re-running with `--force`.
- **Conflict / usage / network failure** → read the exit code and the JSON/stderr message, explain it, and only escalate to `--force` with the user's authorization.
