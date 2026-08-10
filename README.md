# agent-artifacts (`aart`)

> [!IMPORTANT]
> The current implementation is `0.1.x` and still uses the monolithic tool-plus-catalog model
> documented below. The approved AART 1.0 direction separates the compiler from federated artifact
> sources and optional registries. See the
> [AART 1.0 PRD](docs/product/PRD-aart-1.0.md),
> [technical specification](docs/design/SPEC-aart-1.0.md), and
> [implementation plan](PLAN.md) with its [progress ledger](PROGRESS.md), plus the
> [tracking issue #27](https://github.com/M1F1/agent-artifacts/issues/27).

The `1.0.0a1` migration now provides the canonical compiler, federated sources, registry quality
gate, and a fail-closed public export boundary. The operational reference marketplace lives in the
independently versioned
[`M1F1/agent-artifacts-registry`](https://github.com/M1F1/agent-artifacts-registry) repository; it
is never embedded in the AART wheel. See the
[publication boundary](docs/registry/publication-boundary-v1.md) and
[company-registry bootstrap](docs/registry/company-bootstrap-v1.md).

**One catalog of AI artifacts. Every agentic harness on your team, in sync.**

`agent-artifacts` installs your team's **skills, guidelines, MCP servers, hooks, and memory
files** from a single source-of-truth repo into whichever AI coding harness each developer
uses — Tabnine, Claude Code, OpenCode, or Vibe — translating one definition into each
harness's native file layout.

Write a skill once. Ship it everywhere. Then *check for drift* and re-sync on demand.

Zero runtime dependencies (Python stdlib only). Works fully offline.

---

## Requirements

- Python 3.10 or newer.
- `pip`, `pip3`, or `pipx` to install the CLI.
- Nothing else is required to run `aart`: no extra Python packages, Node packages, services, or
  network access.

The CLI uses only the Python standard library after installation.

---

## Quick Start

From this catalog repo, install the CLI:

```sh
pip install -e .
```

If `pip` or `pip3` is unavailable in your environment, try an editable `pipx` install:

```sh
pipx install -e .
```

If you changed this repo and need to rebuild the installed `aart` tool, prefer:

```sh
aart upgrade
```

You can force a reinstall with your package manager, but `aart upgrade` is the intended refresh
path for an already installed local tool.

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

The bare `aart` command first asks which path you need:

- **User** installs, updates, or removes harness artifacts from reviewed catalog subscriptions.
- **Maintainer** can enter the same User workflows or curate a local catalog and its tracked
  third-party upstreams through guided, preview-first operations.

Both paths are available in the full-screen TUI and its plain-text fallback.
The first screen explains the controls. Every later screen starts with a text marker stepper, so
progress is still clear without color and in narrow terminals:

```text
[x] How it works -> [x] Role -> [x] Sources -> [x] Harness -> [●] Action
[ ] Scope -> [ ] Mode -> [ ] Artifacts -> [ ] Review
Stage: Action
Enter = choose · b / back = previous · q / quit = quit
```

Use Backspace in the full-screen TUI or `b`/`back` in the fallback to move back exactly one
applicable stage. Confirmed choices, the artifact/bundle basket, and the curses cursor/scroll
position are retained. If an earlier edit makes only some basket rows invalid, the wizard removes
only those rows and prints the reason. Quitting with a non-empty basket asks before discarding it.

The **Sources** stage reads the user configuration and managed source pointers without fetching or
writing. It shows registry/direct/local kind, enabled/default state, current/stale/offline/invalid/
incompatible health, organization-required or recommended status, and exact locally derived
company review. Registry use remains optional unless organization policy names a required source;
an unconfigured user may continue without sources and exit cleanly. Toggling sources creates an
immutable enable/disable/default request. That request is saved only with the final reviewed
`Finalize`, never while browsing or moving back. See
[`source-management-v1.md`](docs/tui/source-management-v1.md).

Artifact and bundle selectors explain every choice in one line. In the full-screen selector,
press `?` to open the complete description for the highlighted row. In the plain-text fallback,
enter `?N` (for example `?3`) to repeat the complete description for item N.

For every consumer action, both frontends ask for an installation scope before loading
scope-specific state or choices:

- **Project (recommended)** configures only the current repository and remains the default.
- **User** configures the selected harness for the current user.

For Install, both frontends then ask for an installation mode before artifact selection:

- **Copy (recommended)** installs an independent snapshot and remains the default.
- **Symlink** live-links supported skill and hook directories to a local catalog. Copy-only
  individual rows are disabled with a reason; mixed bundles disclose projected linked/copied
  counts and keep file/merge artifacts in Copy mode.

Before applying an Install, the confirmation view shows the catalog source, selected scope,
resolved destination paths, harnesses, requested mode, selected rows, projected mode counts, and
the ordered setup queue for setup-capable artifacts.
User destinations are absolute. Symlink is rejected for a remote source before artifact selection;
use flag mode with `--source DIR --link` to choose a durable local checkout.

Install, Update, Uninstall, Status, and Maintainer paths all end at a separate **Review** stage.
`Finalize` is the only wizard decision that can dispatch the reviewed request. Back/edit, quit,
cursor movement, source reads, validation, and Maintainer dry-run previews do not apply changes.
For a canonical registry, Review shows the exact snapshot/review digest, managed-file diff,
quality/security evidence, conversion warnings, and recovery commands. Finalize rechecks that
exact plan and applies it once. Legacy Maintainer add/import/update retains its established
`validate -> dry-run -> apply -> validate` compatibility flow. Neither path commits or pushes.

Every completed action ends with an explicit outcome summary in command mode and both TUI
frontends. A successful no-op is not silent and is distinct from an empty selection:

```text
Updated 0 artifacts; all 5 selected artifacts are already up to date.
No installed artifacts matched the selected harness and filters.
Removed 0 artifacts; no files were changed.
Cancelled; no changes were made.
```

Install summaries list the actual `copy` or `symlink` mode per artifact, including copy fallback
inside a mixed bundle. Update and uninstall summaries keep skipped, conflicted, failed,
already-absent, and preserved-user-content items visible. Warnings appear with the outcome, and
recoverable failures end with a `next:` instruction while retaining their established non-zero
exit code.

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

## User Mode: Install Artifacts Into A Project Or User Profile

User mode is for developers configuring an application repo or their harness-wide user profile.
You install the `aart` tool, then use the reviewed artifact catalog shipped inside that tool. You
should not need to know where the catalog repo lives or pass catalog source flags for normal use.

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

### Project And User Scopes

Project scope is the default and preserves the existing repository-local behavior. User scope
uses explicit destinations verified for each harness and stores separate state in
`~/.agent-artifacts/manifest.json`. Project state stays in
`<project>/.agent-artifacts/manifest.json`; status, update, and uninstall read only the selected
scope and never cross between them.

```sh
aart install code-review --profile claude --scope user
aart status --scope user
aart update --scope user
aart uninstall code-review --profile claude --scope user
```

`--scope user` cannot be combined with `--project`. If both project and user configuration exist,
the harness's own precedence rules decide which configuration it applies; `aart` does not merge
the two manifests. An unsupported user-global artifact type is rejected with a reason when
selected directly and skipped with a warning in broad `--all` or bundle selections.

| Harness | Supported user-global artifact types |
|---|---|
| Claude Code | skill, guideline, MCP, hook, memory |
| OpenCode | skill, MCP, memory |
| Tabnine | guideline, MCP |
| Mistral Vibe | skill |

User-global destinations include Claude's `~/.claude/` files and `~/.claude.json`, OpenCode's
`~/.config/opencode/` tree, Tabnine's `~/.tabnine/` configuration, and Vibe's
`~/.vibe/skills/`. The exact target matrix and official references are recorded in
`docs/design/DESIGN-install-scope.md`.

MCP artifacts can be a single `mcp/<name>.json` file, or a directory like
`mcp/<name>/mcp.json` with supporting docs such as `SETUP.md`. Harness installs merge only the
JSON server definition. `SETUP.md` stays optional human reference; guided setup is declared by a
strict `setup/installer.json` contract.

### Reviewed Setup Installers On macOS

A directory-shaped artifact may include `setup/installer.json`. The static version-1 recipe
declares its purpose, HTTPS help links, required tools, capabilities, secret prompts, and exact
module steps. Catalog discovery validates and hashes it but never executes it. The TUI shows the
ordered queue before final installation, finishes the ordinary artifact install, leaves curses,
and then processes setup items sequentially in the foreground.

Shared modules cover macOS Keychain, owned shell/file blocks, owned JSON values, directories,
digest-pinned Docker pulls, fixed-argv verification, and restart notices. Before mutation, setup
shows the reviewed source identity, recipe and plan hashes, targets/argv, capabilities, and
rollback limits. Consent is per effect and defaults to No. One item is one transaction: failure
rolls back that item's completed reversible steps, preserves earlier successful items, and
continues unless Stop was explicitly selected.

Flag-mode artifact installation never auto-runs setup. Use the setup runner after the matching
artifact/profile has been installed:

```sh
aart setup run mcp/atlassian --profile tabnine --scope user
aart setup status --scope user --json
aart setup retry --profile tabnine --scope user
aart setup rollback mcp/atlassian --profile tabnine --scope user
```

Project setup state lives at `<project>/.agent-artifacts/setup-state.json`; User state lives at
`~/.agent-artifacts/setup-state.json`. It stores terminal status, source/installer/plan hashes,
timestamps, safe retry/rollback commands, and non-secret ownership receipts. It never stores
input values or captured credential output. Every incomplete item prints a retry command; the TUI
offers a preselected retry of only incomplete items.

For Keychain steps, production runs `/usr/bin/security add-generic-password ... -w` with a final
value-less `-w`, allowing the system tool to own the hidden prompt. The safe default preserves an
existing item; reviewed replacement is explicit and not automatically reversible. Managed shell blocks contain
only a Keychain lookup. A new shell then puts the value in its environment, which child processes
can inherit; close/reopen the shell and restart the harness as instructed. GUI apps may not read
`.zshrc`.

Non-macOS hosts record `unsupported` before invoking effect adapters. An optional hash-bound
custom entrypoint may implement the reviewed `plan/apply/verify/rollback` protocol in a private
`0700` run directory with a minimal environment and `shell=False`; it remains trusted reviewed
code, not a sandbox. Catalog authors should use
[`skills/author-aart-installer/SKILL.md`](skills/author-aart-installer/SKILL.md) and the full trust
model in [`docs/design/DESIGN-setup-installers.md`](docs/design/DESIGN-setup-installers.md).

Artifacts can declare that they only fit specific profiles. JSON descriptors use:

```json
{
  "name": "tabnine-postgres",
  "description": "Let Tabnine inspect and query PostgreSQL databases.",
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
description: Review changes for bugs, risks, and maintainability problems.
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

Choose **Symlink** (spelled `--link` in flag mode) when you want supported artifacts installed into
your project to stay connected to a local catalog checkout instead of using the default **Copy**
snapshot.

```sh
aart install code-review --profile tabnine --link
```

`--link` is opt-in and local-only. By default, `aart` uses the artifact catalog located beside
the installed tool itself. Under the hood, the install source resolves to that local package
root, and linkable directory artifacts are symlinked from there into your project. If `aart` was
installed in editable mode from a local `agent-artifacts` checkout, those symlinks point back to
that checkout.

Copy remains the recommended default install mode. With Symlink/`--link`, changes propagate only when the local
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
or installed artifacts are behind the reviewed source. Each installed manifest entry records its
catalog subscription (the packaged catalog, a local checkout, or a GitHub repo/ref), so a later
`aart update` reopens the correct reviewed source without asking you to enter the repository
again. One project may update entries from several recorded subscriptions in one safely planned
operation. An explicit `--source` or `--repo` overrides and replaces the recorded subscription for
the selected entries.

`aart update` respects local edits; true conflicts are written to `.agent-artifacts-new` sidecars
unless you use `--force`.

Memory artifacts wrap installed content in invisible HTML-comment sentinels, so updates and
uninstalls do not touch your hand-written notes in the same instruction file. Use
`--memory-mode replace --force` only when you want a clean overwrite.

---

## Maintainer Mode: Curate The Catalog

Canonical AART 1.0 registries and empty Git checkouts use the digest-bound Maintainer workflow.
The TUI offers init, scaffold, native promotion, controlled legacy conversion, one-reference
upstream update, lock, build, validate, audit/security evidence, and deterministic diff. Mutating
actions are rejected before preview unless the displayed absolute path is a writable local Git
checkout. Review binds the exact snapshot, changed paths, and plan digest; Finalize fails stale
instead of silently rebuilding a different plan. Read-only validate/audit/diff also recheck their
snapshot and never require a checkout.

Detailed forms run in the plain terminal after the curses action selector closes, so Git/network
diagnostics and full diffs stay visible. Conversion always identifies the built-in importer and
shows warnings. Outcomes distinguish applied paths, no-op, failed checks, and read-only observed
drift, then print exact `git diff`, registry validate, and audit commands. AART never commits,
pushes, or writes consumer managed snapshots/CAS from this path. See
[`maintainer-curation-v1.md`](docs/tui/maintainer-curation-v1.md).

The following section documents the retained 0.1.x catalog compatibility workflow.

Maintainer mode is for people editing the source-of-truth catalog repo itself. In this repo,
you add or edit artifacts under `skills/`, `guidelines/`, `mcp/`, `hooks/`, and `memory/`,
compose them into `bundles/`, and optionally track third-party origins in `upstreams.json`.

Consumer `aart update` never talks directly to third-party upstream repos. Maintainers import
or update artifacts here, review the diff, and merge the catalog change. Users then install or
update from the reviewed catalog.

In the interactive Maintainer path, the absolute active catalog checkout is always shown. Every
add, import, or upstream update runs catalog validation, shows a dry-run preview, asks for explicit
confirmation, applies through the same command core, validates again, and leaves the Git working
tree for you to review. `aart` never commits catalog mutations automatically.

### Configure GitHub Access

Maintainer commands that read GitHub use `GITHUB_TOKEN` when it is present. This is useful for
private repos, GitHub Enterprise repos, and higher rate limits. Prefer a fine-grained,
read-only token with access only to the catalog/upstream repos the command needs. On macOS,
store the token in Keychain, then export `GITHUB_TOKEN` from that secret in your shell config:

```sh
# Store/update in macOS Keychain. A final value-less -w lets `security` own the hidden prompt.
/usr/bin/security add-generic-password -U \
  -a "$USER" \
  -s GITHUB_TOKEN \
  -w

# Add this to ~/.zshrc so new terminals set GITHUB_TOKEN from Keychain.
export GITHUB_TOKEN="$(/usr/bin/security find-generic-password \
  -a "$USER" \
  -s GITHUB_TOKEN \
  -w 2>/dev/null)"
```

Do not put the raw token itself in `~/.zshrc`; keep only the Keychain lookup there. For GitHub
Enterprise, also set `GITHUB_API_URL` or use the per-source `api_url` metadata shown below.

### Validate The Catalog

Run these from the catalog repo root:

```sh
aart upstream validate --source .
aart upstream health --source .
aart list --source .
aart list --source . --json
make validate
```

`upstream health` summarizes artifact counts by type, tracked and untracked artifacts, validation
errors, and tracked origins requiring attention. A missing `upstreams.json` is valid and means the
catalog currently has no tracked third-party origins.

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
| **skill** | `skills/<name>/` | `SKILL.md` frontmatter with `name` and `description` |
| **guideline** | `guidelines/<name>.md` | frontmatter with `description` |
| **mcp** | `mcp/<name>.json` or `mcp/<name>/` | JSON with `name`, `description`, and `server` |
| **hook** | `hooks/<name>/` | `hook.json` with `name`, `description`, `events`, and `command` |
| **memory** | `memory/<name>.md` | frontmatter with `description`; optional `mode` |

Every artifact and bundle needs a concise, inviting `description`. Put it in Markdown
frontmatter for skills, guidelines, and memory files, and in the JSON descriptor for MCPs, hooks,
and bundles. The value must be a non-empty single-line string; block scalars and continued lines
are rejected by catalog validation.

Write the user benefit first and make the row useful before installation:

```text
Good: Let your agent inspect and query PostgreSQL databases.
Good: Prevent edits that appear to introduce secrets.
Avoid: PostgreSQL MCP implementation.
Avoid: A hook artifact.
```

Aim for one short sentence, use an active verb where practical, and do not repeat only the
artifact type. Run `aart upstream validate --source .` after editing; validation reports the
artifact name and canonical descriptor path for missing, blank, non-string, or multiline values.
`aart list --source .` and `aart list --source . --json` expose the same normalized description.

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
| `aart setup` | no by default | Review/run/retry/status/rollback declarative artifact setup |
| `aart upgrade` | offline-capable | Reinstall the CLI itself |

### Maintainer Commands

| Command | Network | Does |
|---------|:------:|------|
| `aart list/install/update --source DIR` | no | Test a local catalog checkout |
| `aart list/install --repo OWNER/NAME` | yes | Test a published remote catalog |
| `aart upstream validate` | no | Validate a local catalog and its upstream metadata |
| `aart upstream health` | if origins are tracked | Summarize catalog coverage and upstream attention |
| `aart upstream add` | yes | Adopt one upstream artifact from a GitHub URL and track it |
| `aart upstream scan` | yes | Scan a GitHub repo/path for importable artifacts |
| `aart upstream import` | yes | Batch-vendor selected GitHub artifacts and optionally create/update a bundle |
| `aart upstream check` | yes | Check tracked vendored artifact origins |
| `aart upstream update` | yes | Import tracked upstream changes into the catalog repo |

Canonical registry commands surfaced by the AART 1.0 Maintainer wizard are documented in
[`maintainer-commands-v1.md`](docs/registry/maintainer-commands-v1.md). They operate only on the
explicit registry checkout and share the same pure plans and exact-digest apply boundary as the
flag-mode registry command family.

**Context-dependent options:** Instead of exposing every option globally, `agent-artifacts`
strictly attaches options only to the commands that consume them.

**Catalog source** — Normal users rely on the catalog bundled with the installed tool. Maintainers
can override that source with `--repo OWNER/NAME` (remote) or `--source DIR` (local checkout)
when testing or maintaining a catalog. These are mutually exclusive. `--source` cannot be
combined with `--version` since a local checkout has no ref to resolve. Remote-only commands
like `check` and `upgrade` accept `--repo`/`--version` but not `--source`.

**Consumer scope** — Commands that modify or inspect harness configuration (`install`, `update`,
`uninstall`, `status`, `check`, `setup`) accept `--scope project|user`; Project is the default. In Project
scope, `--project DIR` selects the consumer directory (default: cwd). User scope uses explicit
harness-global destinations and separate state under the user's home, so `--scope user` and
`--project` are mutually exclusive. Catalog-only commands (`list`) and self-updaters (`upgrade`)
do not accept either option.

**Maintainer upstream** — `aart upstream ...` operates on the catalog repo, using `--source DIR`
to mean the catalog directory to maintain and defaulting to cwd. It never targets a consumer
project and intentionally does not accept `--repo` or `--project`.

`--dry-run` prints the plan and touches nothing. `--json` emits machine-readable output for
agents and CI. Every command returns a structured exit code (`0` ok, `1` generic error,
`2` usage, `3` network, `4` conflict, `5` corrupt manifest). Supplying an unrecognized option
is a usage error, and `--all` cannot be combined with named artifacts or `--bundle`.

Mutating command JSON includes a canonical `summary` object. Human output is rendered from the
same immutable result, so counts and item identities cannot diverge between frontends:

```json
{
  "summary": {
    "action": "update",
    "selected": 2,
    "changed": 1,
    "no_changes": false,
    "counts": {"changed": 1, "up_to_date": 1},
    "modes": {"copy": 2},
    "items": [
      {
        "key": "skill/code-review@claude",
        "status": "changed",
        "artifact": "code-review",
        "type": "skill",
        "profile": "claude",
        "mode": "copy",
        "detail": null
      },
      {
        "key": "skill/testing@claude",
        "status": "up_to_date",
        "artifact": "testing",
        "type": "skill",
        "profile": "claude",
        "mode": "copy",
        "detail": null
      }
    ],
    "warnings": [],
    "recovery": [],
    "dry_run": false
  }
}
```

Existing command-specific JSON fields remain available. Consumers should use `summary` for final
selected/changed counts, status item lists, actual modes, warnings, and safe recovery guidance.

> **Agents:** there's a dedicated skill at [`skills/agent-artifacts/SKILL.md`](skills/agent-artifacts/SKILL.md)
> teaching an agent to drive this CLI (always `--json`, never the TUI).

---

## Developer workflow

```sh
make quality          # canonical non-mutating local/CI gate suite
make test             # broad Python regression suite + bash E2E compatibility alias
make validate         # catalog integrity + zero-runtime-dependency import gate
make packaging-check  # build/import a wheel in a throwaway source copy
make wheel            # release build: stamps the commit and writes dist/*.whl
make version-check    # validate source version consistency and stable-release policy
make version-show     # print the current canonical version
make version-next-alpha  # preview the next 1.0.0aN without changing files
```

The quality tools are required only for development and CI; the installed AART runtime remains
zero-dependency. Install the dev extra to run the same gates as GitHub Actions:

```sh
pip install -e ".[dev]"   # adds Ruff, mypy, coverage, and wheel smoke tooling
make lint                 # ruff: real-bug + import-hygiene checks
make format               # ruff: auto-format (format-check to verify only)
make typecheck            # mypy over agent_artifacts/
make unit                 # broad stdlib unittest discovery
make integration          # Python end-to-end/integration modules
make e2e                  # real shell-driven CLI round trip
make coverage             # branch-aware ratcheted coverage report
make docs-check           # Markdown links/fences and PLAN/PROGRESS consistency
```

`make quality` runs every non-mutating check in that order using temporary Ruff/mypy/coverage and
packaging locations, then verifies that repository files are byte-for-byte unchanged. CI invokes
that same command on Python 3.10 and the latest stable feature series, currently Python 3.14.

Version changes are deliberate release actions. The development train starts at `1.0.0a1`:

```sh
make version-bump-alpha                # explicitly write the next 1.0.0aN
make version-set VERSION=1.0.0rc1      # explicitly write another validated prerelease
```

Setting or tagging stable `1.0.0` fails closed until every task through `REL01` is complete.
Generated `dist/*.whl` files are local/release outputs and are not committed; GitHub release jobs
verify that the tag and source version match before building and uploading a wheel.

Enable the repository-owned pre-commit hook with:

```sh
git config core.hooksPath .githooks
```

The hook is non-mutating: it checks synchronized versions and staged whitespace only. It never
bumps a version, builds a wheel, or stages files.
