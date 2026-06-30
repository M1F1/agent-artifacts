# agent-artifacts (`aart`)

**One catalog of AI artifacts. Every agentic harness on your team, in sync.**

`agent-artifacts` installs your team's **skills, guidelines, MCP servers, hooks, and memory
files** from a single source-of-truth repo into whichever AI coding harness each developer
uses — Tabnine, Claude Code, OpenCode, or Vibe — translating one definition into each
harness's native file layout.

Write a skill once. Ship it everywhere. Then *check for drift* and re-sync on demand.

Zero runtime dependencies (Python stdlib only). Works fully offline.

---

## Quick Start

From this catalog repo, install the CLI:

```sh
pip install -e .
```

Then install the onboarding skill into your project harness:

```sh
cd /path/to/your/project
aart install agent-artifacts --profile tabnine
```

This installs the onboarding skill into your harness, for example
`.tabnine/agent/skills/agent-artifacts/` for Tabnine. For another harness, replace
`tabnine` with `claude`, `opencode`, or `vibe`, or pass a comma-separated list.

Prefer the interactive flow?

```sh
aart
```

The bare `aart` command opens a profile-first TUI for install, update, and remove flows.

Prefer more command line examples?

```sh
aart list
aart install code-review --profile tabnine
aart install --bundle backend --profile tabnine,claude
aart status
```

**TL;DR:** ask an agent to use the `agent-artifacts` skill for guided onboarding. It will ask
what you are trying to do, explain the relevant `aart` options, recommend a plan, wait for your
confirmation, and then run the right commands.

---

## User Mode: Install Artifacts Into A Project

User mode is for developers working inside an application repo. You install the `aart` tool,
then use the reviewed artifact catalog shipped inside that tool. You should not need to know
where the catalog repo lives or pass catalog source flags for normal use.

### What You Can Install

| Type | What it is | Lands as (Tabnine example) |
|------|------------|---------------------------|
| **skill** | A reusable `SKILL.md` capability | `.tabnine/agent/skills/<name>/` |
| **guideline** | A standalone reference doc | `.tabnine/guidelines/<name>.md` |
| **mcp** | An MCP server definition | merged into `.tabnine/agent/settings.json` |
| **hook** | An event hook + its scripts | merged into `.tabnine/agent/settings.json` |
| **memory** | The top-level instruction file | `TABNINE.md` (or `CLAUDE.md`, `AGENTS.md`) |

Each harness has a **profile** that knows where every type belongs, so the same artifact
installs correctly into `.claude/`, `.opencode/`, `.tabnine/`, or `.vibe/`.

MCP artifacts can be a single `mcp/<name>.json` file, or a directory like
`mcp/<name>/mcp.json` with supporting docs such as `SETUP.md`. Harness installs merge only the
JSON server definition; setup docs stay in the catalog for humans.

Artifacts can declare that they only fit specific profiles. JSON descriptors use:

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

Markdown/frontmatter artifacts use the same field as a dotted key:

```markdown
---
name: code-review
compatibility.profiles: tabnine, claude
---
```

An explicit incompatible install is a usage error. Bundle and `--all` installs skip
incompatible targets with a warning and include machine-readable skip reasons in JSON output.
The TUI uses the same compatibility rules, so profile selection hides artifacts that do not
apply.

### Use The Installed Catalog

The installed `aart` package carries the reviewed catalog, so the tool already knows which
artifacts are available.

```sh
aart list
aart list --type skill
aart list --bundle backend

aart install code-review --profile tabnine
aart install --bundle backend --profile tabnine,claude
aart install --all --profile tabnine --dry-run
```

Bundles are curated sets such as "base" or "backend". They can include multiple artifact types
and can extend other bundles, so team setup is one command instead of a pile of paths.

### Live-Link From A Local Catalog Checkout

Use `--link` when you want artifacts installed into your project to stay connected to a local
catalog checkout instead of being copied as a snapshot.

```sh
aart install code-review --profile tabnine --link
```

`--link` is opt-in and local-only. By default, `aart` uses the artifact catalog located beside
the installed tool itself. Under the hood, the install source resolves to that local package
root, and linkable directory artifacts are symlinked from there into your project. If `aart` was
installed in editable mode from a local `agent-artifacts` checkout, those symlinks point back to
that checkout.

Copy remains the default install mode. With `--link`, changes propagate only when the local
source path changes, for example after local edits, `git pull`, branch switches, or
`aart upstream update` in the catalog. Use `aart status --json` to see whether an installed
artifact is `copy` or `symlink` and where a link points. Pass `--source DIR` only when you want
to link from a different local catalog checkout than the one used by the installed `aart`.

### Check, Update, And Uninstall

Every install is recorded in `.agent-artifacts/manifest.json` with files, hashes, source
commit, install mode, and link targets. Freshness checks are opt-in, never ambient.

```sh
aart status
aart status --json

aart check
aart update
aart update --prune

aart uninstall code-review --profile tabnine
aart uninstall --all --profile tabnine --dry-run
```

`aart status` is local and uses no network. `aart check` tells you whether the installed tool
or installed artifacts are behind the reviewed source. `aart update` reapplies reviewed
artifacts while respecting local edits; true conflicts are written to `.agent-artifacts-new`
sidecars unless you use `--force`.

Memory artifacts wrap installed content in invisible HTML-comment sentinels, so updates and
uninstalls do not touch your hand-written notes in the same instruction file. Use
`--memory-mode replace --force` only when you want a clean overwrite.

---

## Maintainer Mode: Curate The Catalog

Maintainer mode is for people editing the source-of-truth catalog repo itself. In this repo,
you add or edit artifacts under `skills/`, `guidelines/`, `mcp/`, `hooks/`, and `memory/`,
compose them into `bundles/`, and optionally track third-party origins in `upstreams.json`.

Consumer `aart update` never talks directly to third-party upstream repos. Maintainers import
or update artifacts here, review the diff, and merge the catalog change. Users then install or
update from the reviewed catalog.

### Configure GitHub Access

Maintainer commands that read GitHub use `GITHUB_TOKEN` when it is present. This is useful for
private repos, GitHub Enterprise repos, and higher rate limits. Prefer a fine-grained,
read-only token with access only to the catalog/upstream repos the command needs. On macOS,
store the token in Keychain, then export `GITHUB_TOKEN` from that secret in your shell config:

```sh
# Store once in macOS Keychain. The prompt input is hidden; -U updates an existing item.
printf "GitHub token: "
IFS= read -r -s GITHUB_TOKEN; echo
security add-generic-password -U \
  -a "$USER" \
  -s GITHUB_TOKEN \
  -w "$GITHUB_TOKEN"
unset GITHUB_TOKEN

# Add this to ~/.zshrc so new terminals set GITHUB_TOKEN from Keychain.
export GITHUB_TOKEN="$(security find-generic-password \
  -a "$USER" \
  -s GITHUB_TOKEN \
  -w 2>/dev/null)"
```

Do not put the raw token itself in `~/.zshrc`; keep only the Keychain lookup there. For GitHub
Enterprise, also set `GITHUB_API_URL` or use the per-source `api_url` metadata shown below.

### Validate The Catalog

Run these from the catalog repo root:

```sh
aart list --source .
aart list --source . --json
make validate
```

Use `--source .` when you want the CLI to read the working tree you are editing, not the
catalog bundled inside the installed package.

### Test A Catalog Source

Maintainers can point ordinary list/install/update commands at a local checkout or published
remote catalog to verify catalog changes before users receive a new tool build.

```sh
aart list --source .
aart install --bundle backend --source . --profile tabnine --dry-run

aart list --repo your-org/ai-catalog
aart install code-review --repo your-org/ai-catalog --profile tabnine --dry-run
aart install code-review --version v2.1 --repo your-org/ai-catalog --profile tabnine --dry-run
```

### Create Or Edit Artifacts Manually

Artifacts live in predictable locations:

| Type | Catalog path | Required entry point |
|------|--------------|----------------------|
| **skill** | `skills/<name>/` | `SKILL.md` with `name: <name>` frontmatter |
| **guideline** | `guidelines/<name>.md` | optional frontmatter |
| **mcp** | `mcp/<name>.json` or `mcp/<name>/` | JSON with `name` and `server` |
| **hook** | `hooks/<name>/` | `hook.json` with `name`, `events`, and `command` |
| **memory** | `memory/<name>.md` | optional frontmatter and optional `mode` |

After editing, validate and smoke-test the install plan:

```sh
aart list --source . --type skill
aart install code-review --source . --profile tabnine --dry-run
aart install --bundle backend --source . --profile tabnine --dry-run
make validate
```

### Create Or Edit Bundles

Bundles live in `bundles/<name>.json`. A bundle can include artifacts, extend other bundles,
and pin selected artifacts to a ref for reproducible installs.

```json
{
  "name": "backend",
  "description": "Backend team set: extends base with database tooling.",
  "extends": ["base"],
  "includes": {
    "skills": ["code-review"],
    "guidelines": ["python-style"],
    "mcp": ["postgres"],
    "hooks": ["block-secrets"],
    "memory": ["house"]
  },
  "pins": {
    "code-review": "a1b2c3d"
  }
}
```

To create a bundle, add a new `bundles/<name>.json`. To edit one, change `includes`,
`extends`, or `pins`, then validate and dry-run the bundle against the profiles your team uses:

```sh
aart list --source . --bundle backend
aart install --bundle backend --source . --profile tabnine,claude --dry-run
make validate
```

`includes` supports `skills`, `guidelines`, `mcp`, `hooks`, and `memory`. `extends` composes
other bundles with cycle detection. `pins` maps artifact names to a branch, tag, or SHA.

### Adopt And Track One External Artifact

Use `aart upstream add` when you already know the GitHub URL of one artifact. A `/tree/` URL
vendors a directory artifact such as a skill, hook, or directory-shaped MCP. A `/blob/` URL
vendors a single-file artifact such as a guideline, flat MCP, or memory file.

```sh
aart upstream add skill/domain-modeling \
  https://github.com/mattpocock/skills/tree/main/skills/engineering/domain-modeling \
  --dry-run

aart upstream add skill/domain-modeling \
  https://github.com/mattpocock/skills/tree/main/skills/engineering/domain-modeling
```

This fetches the artifact, copies the whole tree or file into the catalog, and writes a
tracked origin to `upstreams.json`. The `TYPE/NAME` key must match the upstream artifact's own
declared name.

```json
{
  "version": 1,
  "artifacts": {
    "skill/domain-modeling": {
      "source": {
        "kind": "github",
        "repo": "mattpocock/skills",
        "ref": "main",
        "path": "skills/engineering/domain-modeling"
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

Use `--ref` or `--path` when a branch name contains slashes or the URL needs overriding. Use
`--force` to replace an existing catalog destination, and `--dry-run` to preview before writing.

For GitHub Enterprise or mixed-host catalogs, add per-source API metadata:

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

### Scan And Import From An External GitHub Repo

Use `scan` when you do not know which artifacts a repo contains yet. Use `import` to vendor
the selected candidates into this catalog, optionally creating or extending a bundle.

```sh
aart upstream scan https://github.com/org/superpowers/tree/main --json

aart upstream import https://github.com/org/superpowers/tree/main --dry-run
aart upstream import https://github.com/org/superpowers/tree/main \
  --select skill/code-review \
  --select memory/house \
  --bundle superpowers \
  --bundle-mode append
```

Useful import flags:

- `--select TYPE/NAME` imports specific candidates; repeat it for multiple artifacts.
- `--bundle NAME` creates or updates a bundle with imported artifacts.
- `--bundle-description TEXT` sets the description for a created/replaced bundle.
- `--bundle-mode append|replace|fail` controls what happens when the bundle already exists.
- `--mode auto|manifest|heuristic` controls candidate discovery.
- `--interactive` prompts for candidate selection.

### Check And Update Tracked Upstreams

Once artifacts are tracked in `upstreams.json`, maintainers can check for upstream changes and
stage reviewed updates into the catalog working tree.

```sh
aart upstream check --all --json
aart upstream check --bundle backend

aart upstream update skill/code-review --dry-run
aart upstream update --bundle backend
aart upstream update --all --force
```

`upstream check` reports whether tracked origins are up to date, changed, missing upstream, or
locally drifted. `upstream update` writes ordinary working-tree diffs and updates
`upstreams.json` sync metadata. Review those diffs like any other catalog change before merge.

---

## Command Reference

### User Commands

| Command | Network | Does |
|---------|:------:|------|
| `aart list` | no | List artifacts shipped with the installed tool (`--type`, `--bundle`, `--json`) |
| `aart install` | no | Install shipped artifacts/bundles into one or more profiles |
| `aart status` | no | Show installed artifacts, install mode, link state, and local drift |
| `aart check` | yes | Compare installed/CLI commit against the source |
| `aart update` | no by default | Re-apply reviewed artifacts; `--prune`, `--force` |
| `aart uninstall` | no | Reverse installed files and merge entries |
| `aart upgrade` | offline-capable | Reinstall the CLI itself |

### Maintainer Commands

| Command | Network | Does |
|---------|:------:|------|
| `aart list/install/update --source DIR` | no | Test a local catalog checkout |
| `aart list/install --repo OWNER/NAME` | yes | Test a published remote catalog |
| `aart upstream add` | yes | Adopt one upstream artifact from a GitHub URL and track it |
| `aart upstream scan` | yes | Scan a GitHub repo/path for importable artifacts |
| `aart upstream import` | yes | Batch-vendor selected GitHub artifacts and optionally create/update a bundle |
| `aart upstream check` | yes | Check tracked vendored artifact origins |
| `aart upstream update` | yes | Import tracked upstream changes into the catalog repo |

**Context-dependent options:** Instead of exposing every option globally, `agent-artifacts`
strictly attaches options only to the commands that consume them.

**Catalog source** — Normal users rely on the catalog bundled with the installed tool. Maintainers
can override that source with `--repo OWNER/NAME` (remote) or `--source DIR` (local checkout)
when testing or maintaining a catalog. These are mutually exclusive. `--source` cannot be
combined with `--version` since a local checkout has no ref to resolve. Remote-only commands
like `check` and `upgrade` accept `--repo`/`--version` but not `--source`.

**Consumer project** — Commands that modify or inspect the consumer project (`install`,
`update`, `uninstall`, `status`, `check`) accept `--project DIR` (default: cwd). Catalog-only
commands (`list`) and self-updaters (`upgrade`) do not.

**Maintainer upstream** — `aart upstream ...` operates on the catalog repo, using `--source DIR`
to mean the catalog directory to maintain and defaulting to cwd. It never targets a consumer
project and intentionally does not accept `--repo` or `--project`.

`--dry-run` prints the plan and touches nothing. `--json` emits machine-readable output for
agents and CI. Every command returns a structured exit code (`0` ok, `1` generic error,
`2` usage, `3` network, `4` conflict, `5` corrupt manifest). Supplying an unrecognized option
is a usage error, and `--all` cannot be combined with named artifacts or `--bundle`.

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
