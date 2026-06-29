# agent-artifacts (`aart`)

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
pip install -e .          # editable install: run `aart` from any project folder
aart                      # bare invocation -> profile-first TUI (install / update / remove)
```

Prefer the command line?

```sh
aart list                                   # see the catalog
aart install code-review --profile claude   # install one artifact for Claude Code
aart install --bundle backend --profile claude,tabnine   # install a whole team set
aart status                                 # what's installed here + has it drifted?
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

MCP artifacts can be a single `mcp/<name>.json` file, or a directory like
`mcp/<name>/mcp.json` with supporting docs such as `SETUP.md`. Harness installs merge only the
JSON server definition; setup docs stay in the catalog for humans.

Artifacts can also declare that they are only aligned with specific profiles. JSON descriptors
use an explicit compatibility object:

```json
{
  "name": "tabnine-postgres",
  "compatibility": {
    "profiles": ["tabnine"]
  },
  "server": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-postgres"]
  }
}
```

Markdown/frontmatter artifacts use the same field as a flat dotted key:

```markdown
---
name: code-review
compatibility.profiles: claude, tabnine
---
```

An explicit incompatible install is a usage error. Bundle and `--all` installs skip
incompatible targets with a warning and include machine-readable skip reasons in JSON output.

The interactive TUI uses the same rules. It asks for profile(s) first, then action, then shows
only artifacts and bundles that make sense for that profile selection. For example, choosing
`vibe` hides MCP and hook artifacts; choosing `tabnine` can show Tabnine-only artifacts. Bundle
rows remain selectable, with partial bundles labelled when some contents are hidden for the
selected profile(s).

---

## The features that matter

### 📦 Bundles — ship a curated set, not one file at a time
A bundle is a named group of artifacts. Bundles **`extend`** other bundles (composition with
cycle detection) and can **`pin`** specific artifacts to a commit, so "the backend team's
setup" is one install command and stays reproducible.

```sh
aart install --bundle backend --profile claude
```

### 🌐 Local *or* remote source — same result either way
Pull from a GitHub repo, or from a local checkout for offline / air-gapped work. Both produce
an identical catalog; nothing downstream cares which you used.

```sh
aart install code-review --repo your-org/ai-catalog          # remote (GitHub)
aart install code-review --version v2.1 --repo your-org/...   # pin a branch/tag/SHA
aart install code-review --source ./catalog-checkout         # local, no network
```

Private repos, GitHub Enterprise repos, and higher-rate-limit remote installs use
`GITHUB_TOKEN` when it is present in the environment. Prefer a fine-grained, read-only token
with access only to the catalog/upstream repos the command needs. On macOS, keep the token in
Keychain instead of committing it, pasting it into shell history, or writing the raw token into
`~/.zshrc`:

```sh
# Store once. The prompt input is hidden; -U updates an existing Keychain item.
printf "GitHub token: "
IFS= read -r -s AART_GITHUB_TOKEN; echo
security add-generic-password -U \
  -a "$USER" \
  -s agent-artifacts.github-token \
  -w "$AART_GITHUB_TOKEN"
unset AART_GITHUB_TOKEN

# Use for one command without leaving the token in your long-lived shell environment.
GITHUB_TOKEN="$(security find-generic-password \
  -a "$USER" \
  -s agent-artifacts.github-token \
  -w)" \
  aart install code-review --repo your-org/private-ai-catalog --profile claude

# Or export for the current terminal session, then unset it when finished.
export GITHUB_TOKEN="$(security find-generic-password \
  -a "$USER" \
  -s agent-artifacts.github-token \
  -w)"
# Run aart commands here.
unset GITHUB_TOKEN
```

For a permanent convenience setup, add the Keychain lookup (not the raw token) to a trusted
shell config such as `~/.zshrc` or `~/.zprofile`:

```sh
# ~/.zshrc
export GITHUB_TOKEN="$(security find-generic-password \
  -a "$USER" \
  -s agent-artifacts.github-token \
  -w 2>/dev/null || true)"
```

That makes new terminal sessions ready for `aart` without repeating the export command. The
tradeoff is that every process started from that shell can inherit `GITHUB_TOKEN`, so avoid
`export GITHUB_TOKEN=ghp_...` with the raw secret and prefer the one-command form above when
you want narrower exposure.

For GitHub Enterprise, also set `GITHUB_API_URL` or use the per-source `api_url` field shown
in the maintainer section below.

For shared local development, directory artifacts can be live-linked from a local checkout:

```sh
aart install code-review --source /Users/me/code/agent-artifacts --profile claude --link
```

`--link` is opt-in and local-only. It creates symlinks for directory artifacts such as skills
and hook payloads, while copy remains the default. Changes propagate only when that local
checkout changes (local edits, `git pull`, branch switches, or `aart upstream update` in the
catalog). Use `aart status --json` to see whether an installed artifact is `copy` or `symlink`
and where a link points.

### 🔄 Drift detection & re-sync — know when you're behind, fix it on demand
Every install is recorded in a manifest (files, hashes, source commit). That unlocks a clean
sync workflow — and freshness checks are **always opt-in, never ambient**:

- **`aart status`** — *local, no network.* Lists what's installed and flags each file as
  `ok` / `drift` / `missing`, so you see local edits at a glance.
- **`aart check`** — *remote, opt-in.* Compares your installed commit against the source's
  `main` and tells you exactly which artifacts (and whether the CLI itself) fell behind,
  then suggests the next command.
- **`aart update`** — re-pulls and re-applies. Local edits are respected: a true conflict is
  written to a `.agent-artifacts-new` sidecar instead of clobbering your work (override with
  `--force`). `--prune` drops entries no longer in the set.

### 🧭 Maintainer upstream tracking — adopt by URL, then review changes
Catalog maintainers vendor artifacts from other repos and track where they came from in
`upstreams.json`. **Adopt one by pasting its GitHub URL** — the browser link to the folder, no
hand-editing:

```sh
# A /tree/ link to a skill folder; aart decomposes repo, ref, and path for you:
aart upstream add skill/domain-modeling \
  https://github.com/mattpocock/skills/tree/main/skills/engineering/domain-modeling
```

This fetches the directory, copies the **whole tree** into `skills/domain-modeling/`, and writes
the tracking entry below. MCP can also be adopted from a `/tree/` link when the directory has
`mcp.json` or `<name>.json` plus docs like `SETUP.md`; installing it into a harness still
merges only the config. A `/blob/` link adopts a single-file artifact (guideline/mcp/memory).
The key's name must match the upstream's own `name:`. Use `--ref`/`--path` to override when a
branch name contains slashes, `--force` to overwrite an existing copy, and `--dry-run` to preview.

Then check or import upstream changes into this repo as ordinary working-tree diffs:

```sh
aart upstream scan https://github.com/org/superpowers/tree/main --json
aart upstream import https://github.com/org/superpowers/tree/main --bundle superpowers --dry-run
aart upstream import https://github.com/org/superpowers/tree/main --bundle superpowers
aart upstream check --all --json
aart upstream update skill/code-review --dry-run
aart upstream update --bundle backend
```

Maintainer commands that read GitHub (`upstream add`, `scan`, `import`, `check`, and `update`)
use the same `GITHUB_TOKEN` environment variable. That lets maintainers vendor artifacts from
private upstream repos without embedding credentials in `upstreams.json` or command history.

`aart upstream add` writes a fully-formed entry — identical to a hand-authored one:

```json
{
  "version": 1,
  "artifacts": {
    "skill/code-review": {
      "source": {
        "kind": "github",
        "repo": "example/review-skills",
        "ref": "main",
        "path": "skills/code-review"
      },
      "last_synced": {
        "sha": "abc123",
        "content_hash": "sha256:...",
        "synced_at": "2026-06-22T10:00:00Z"
      }
    }
  }
}
```

For GitHub Enterprise or mixed-host catalogs, add a per-source API URL:

```json
{
  "source": {
    "kind": "github",
    "repo": "platform/review-skills",
    "api_url": "https://github.my-company.com/api/v3",
    "ref": "main",
    "path": "skills/code-review"
  }
}
```

Consumer `aart update` still updates from this reviewed catalog, not directly from third-party
upstream repos.

### 🧠 Memory files without the clobber
Installing a memory artifact wraps it in invisible HTML-comment sentinels (`prepend` by
default) so it can be updated or removed later **without touching your hand-written notes** in
the same file. Want a clean overwrite instead? `--memory-mode replace --force`.

### 🛟 Safe and scriptable by default
`--dry-run` prints the plan and touches nothing. `--json` emits machine-readable output for
agents and CI. Every command returns a **structured exit code** (`0` ok · `2` usage · `3`
network · `4` conflict · `5` corrupt manifest) so automation can branch on the result.

### ⬆️ Self-update, offline
`aart upgrade` reinstalls the CLI itself from the source via `pip install --no-index` — from a
prebuilt local wheel when one is present, no package index required.

---

## Command reference

| Command | Network | Does |
|---------|:------:|------|
| `aart list` | source-dependent | List catalog artifacts (`--type`, `--bundle`, `--json`) |
| `aart install` | source-dependent | Install artifacts/bundles into one or more profiles; `--link` for local live-linked directory artifacts |
| `aart status` | no | Show installed artifacts + local drift |
| `aart check` | yes | Compare installed/CLI commit against the source |
| `aart update` | source-dependent | Re-pull and re-apply; `--prune`, `--force` |
| `aart upstream add` | yes | Adopt an upstream artifact from a GitHub URL (vendor + track) |
| `aart upstream scan` | yes | Scan a GitHub repo/path for batch-importable artifacts |
| `aart upstream import` | yes | Batch-vendor selected GitHub artifacts and optionally create a bundle |
| `aart upstream check` | yes | Maintainer check for tracked vendored artifact origins |
| `aart upstream update` | yes | Import tracked upstream changes into the catalog repo |
| `aart uninstall` | no | Reverse installed files and merge entries |
| `aart upgrade` | offline-capable | Reinstall the CLI itself |

`source-dependent` means no network for the bundled catalog or `--source DIR`, and network when
using a GitHub `--repo`.

**Context-Dependent Options:** Instead of exposing every option globally, `agent-artifacts` strictly attaches options only to the commands that consume them:

**Catalog source** — Commands like `list`, `install`, and `update` accept `--repo OWNER/NAME` (remote) or `--source DIR` (local checkout). These are mutually exclusive. (`--source` cannot be combined with `--version` since a local checkout has no ref to resolve). Remote-only commands like `check` and `upgrade` accept `--repo`/`--version` but not `--source`.

**Consumer project** — Commands that modify or inspect the consumer project (`install`, `update`, `uninstall`, `status`, `check`) accept `--project DIR` (default: cwd). Catalog-only commands (`list`) or self-updaters (`upgrade`) do not.

**Maintainer upstream** — `aart upstream …` operates on the *catalog repo* (using `--source DIR` to mean the catalog directory to maintain, defaulting to cwd), never a consumer project. It intentionally does not accept `--repo` or `--project`.

Supplying an unrecognized option is a usage error (exit `2`). Likewise, `--all` cannot be combined with named artifacts or `--bundle`.

> **Agents:** there's a dedicated skill at [`skills/agent-artifacts/SKILL.md`](skills/agent-artifacts/SKILL.md)
> teaching an agent to drive this CLI (always `--json`, never the TUI).

---

## Developer workflow

```sh
make test       # full unittest suite + bash E2E round-trip
make validate   # catalog integrity + a "no non-stdlib imports" gate
make wheel      # stamp the commit and build the offline dist/*.whl
```

**Optional linting / formatting / type checking.** These are *not* required to run, test,
or build the CLI — the runtime stays zero-dependency. Install the dev extra to use them:

```sh
pip install -e ".[dev]"   # adds ruff + mypy
make lint                 # ruff: real-bug + import-hygiene checks
make format               # ruff: auto-format (format-check to verify only)
make typecheck            # mypy over agent_artifacts/
```

To auto-bump the version and rebuild the wheel on every commit, enable the git hook:

```sh
chmod +x .git/hooks/pre-commit
```
