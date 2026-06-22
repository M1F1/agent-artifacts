# agent-artifacts (`aa`)

**One catalog of AI artifacts. Every agentic harness on your team, in sync.**

`agent-artifacts` installs your team's **skills, guidelines, MCP servers, hooks, and memory
files** from a single source-of-truth repo into whichever AI coding harness each developer
uses — Claude Code, OpenCode, Tabnine, or Vibe — translating one definition into each
harness's native file layout.

Write a skill once. Ship it everywhere. Then *check for drift* and re-sync on demand.

Zero runtime dependencies (Python stdlib only). Works fully offline.

---

## Quick start

```sh
pip install -e .          # editable install: run `aa` from any project folder
aa                        # bare invocation → interactive TUI (browse / install / remove)
```

Prefer the command line?

```sh
aa list                                   # see the catalog
aa install code-review --profile claude   # install one artifact for Claude Code
aa install --bundle backend --profile claude,tabnine   # install a whole team set
aa status                                 # what's installed here + has it drifted?
```

---

## What you can install

| Type | What it is | Lands as (Claude example) |
|------|------------|---------------------------|
| **skill** | A reusable `SKILL.md` capability | `.claude/skills/<name>/` |
| **guideline** | A standalone reference doc | `.claude/guidelines/<name>.md` |
| **mcp** | An MCP server definition | merged into `.mcp.json` |
| **hook** | An event hook + its scripts | merged into `.claude/settings.json` |
| **memory** | The top-level instruction file | `CLAUDE.md` (or `AGENTS.md`, `TABNINE.md`) |

Each harness has a **profile** that knows where every type belongs, so the same artifact
installs correctly into `.claude/`, `.opencode/`, `.tabnine/`, or `.vibe/` — you never have to
remember the paths.

---

## The features that matter

### 📦 Bundles — ship a curated set, not one file at a time
A bundle is a named group of artifacts. Bundles **`extend`** other bundles (composition with
cycle detection) and can **`pin`** specific artifacts to a commit, so "the backend team's
setup" is one install command and stays reproducible.

```sh
aa install --bundle backend --profile claude
```

### 🌐 Local *or* remote source — same result either way
Pull from a GitHub repo, or from a local checkout for offline / air-gapped work. Both produce
an identical catalog; nothing downstream cares which you used.

```sh
aa install code-review --repo your-org/ai-catalog          # remote (GitHub)
aa install code-review --version v2.1 --repo your-org/...   # pin a branch/tag/SHA
aa install code-review --source ./catalog-checkout         # local, no network
```

### 🔄 Drift detection & re-sync — know when you're behind, fix it on demand
Every install is recorded in a manifest (files, hashes, source commit). That unlocks a clean
sync workflow — and freshness checks are **always opt-in, never ambient**:

- **`aa status`** — *local, no network.* Lists what's installed and flags each file as
  `ok` / `drift` / `missing`, so you see local edits at a glance.
- **`aa check`** — *remote, opt-in.* Compares your installed commit against the source's
  `main` and tells you exactly which artifacts (and whether the CLI itself) fell behind,
  then suggests the next command.
- **`aa update`** — re-pulls and re-applies. Local edits are respected: a true conflict is
  written to a `.agent-artifacts-new` sidecar instead of clobbering your work (override with
  `--force`). `--prune` drops entries no longer in the set.

### 🧠 Memory files without the clobber
Installing a memory artifact wraps it in invisible HTML-comment sentinels (`prepend` by
default) so it can be updated or removed later **without touching your hand-written notes** in
the same file. Want a clean overwrite instead? `--memory-mode replace --force`.

### 🛟 Safe and scriptable by default
`--dry-run` prints the plan and touches nothing. `--json` emits machine-readable output for
agents and CI. Every command returns a **structured exit code** (`0` ok · `2` usage · `3`
network · `4` conflict · `5` corrupt manifest) so automation can branch on the result.

### ⬆️ Self-update, offline
`aa upgrade` reinstalls the CLI itself from the source via `pip install --no-index` — from a
prebuilt local wheel when one is present, no package index required.

---

## Command reference

| Command | Network | Does |
|---------|:------:|------|
| `aa list` | — | List catalog artifacts (`--type`, `--bundle`, `--json`) |
| `aa install` | on remote | Install artifacts/bundles into one or more profiles |
| `aa status` | no | Show installed artifacts + local drift |
| `aa check` | yes | Compare installed/CLI commit against the source |
| `aa update` | on remote | Re-pull and re-apply; `--prune`, `--force` |
| `aa uninstall` | no | Reverse installed files and merge entries |
| `aa upgrade` | offline-capable | Reinstall the CLI itself |

Global flags work on any subcommand: `--repo OWNER/NAME`, `--source DIR`, `--project DIR`.

> **Agents:** there's a dedicated skill at [`skills/agent-artifacts/SKILL.md`](skills/agent-artifacts/SKILL.md)
> teaching an agent to drive this CLI (always `--json`, never the TUI).

---

## Developer workflow

```sh
make test       # full unittest suite + bash E2E round-trip
make validate   # catalog integrity + a "no non-stdlib imports" gate
make wheel      # stamp the commit and build the offline dist/*.whl
```

To auto-bump the version and rebuild the wheel on every commit, enable the git hook:

```sh
chmod +x .git/hooks/pre-commit
```
