# agent-artifacts (`aart`)

> [!IMPORTANT]
> The current implementation is stable `1.0.0`. It separates the compiler from
> federated artifact sources and optional registries; the retained 0.1 compatibility sections are
> marked below. See the
> [AART 1.0 PRD](docs/product/PRD-aart-1.0.md),
> [technical specification](docs/design/SPEC-aart-1.0.md), and
> [implementation plan](PLAN.md) with its [progress ledger](PROGRESS.md), the
> [1.0 release checklist](docs/release/release-checklist-v1.md), plus the
> [tracking issue #27](https://github.com/M1F1/agent-artifacts/issues/27).

The `1.0.0` release provides the canonical compiler, federated sources, registry quality
gate, and a fail-closed public export boundary. The operational reference marketplace lives in the
independently versioned
[`M1F1/agent-artifacts-registry`](https://github.com/M1F1/agent-artifacts-registry) repository; it
is never embedded in the AART wheel. See the
[publication boundary](docs/registry/publication-boundary-v1.md) and
[company-registry bootstrap](docs/registry/company-bootstrap-v1.md).

**One artifact protocol. Any reviewed source. Every supported agentic harness in sync.**

`agent-artifacts` compiles and installs **skills, guidelines, MCP servers, hooks, and memory
files** from zero or more native sources and optional registries into whichever AI coding harness
each developer uses — Tabnine, Claude Code, OpenCode, or Vibe — translating one canonical
definition into each harness's native file layout.

Write a skill once. Ship it everywhere. Then *check for drift* and re-sync on demand.

Zero runtime dependencies (Python stdlib only). Works fully offline.

---

## Requirements

- Python 3.10 or newer.
- `pip` to install the local editable checkout or prebuilt wheel.
- Nothing else is required to run `aart`: no extra Python packages, Node packages, services, or
  network access.

The CLI uses only the Python standard library after installation.

---

## Quick Start

Install a local checkout without consulting a package index:

```sh
python -m pip install --no-index --no-deps --no-build-isolation -e /path/to/agent-artifacts
```

Or build and install the zero-runtime-dependency wheel:

```sh
cd /path/to/agent-artifacts
make wheel
python -m pip install --no-index --no-deps dist/agent_artifacts-1.0.0-py3-none-any.whl
```

An installed AART replaces itself only from an explicit reviewed local input. Preview first:

```sh
aart upgrade --source-checkout /path/to/agent-artifacts --dry-run
aart upgrade --source-checkout /path/to/agent-artifacts
# or: aart upgrade --wheel /path/to/agent_artifacts-1.0.0-py3-none-any.whl
```

These paths always pass `--no-index --no-deps` to pip. Editable replacement also disables build
isolation. AART 1.0 does not infer a repository, contact PyPI/Nexus, or update itself automatically.
See [local delivery and environment recreation](docs/distribution/local-delivery-v1.md).

Then open the TUI, configure and sync one or more source repositories, and install from the local
marketplace:

```sh
cd /path/to/your/project
aart
```

For an agent or other non-interactive caller, configure the exact source first and then read the
canonical local marketplace as JSON:

```sh
aart source add \
  --alias company-registry \
  --kind registry-git \
  --location https://github.example.com/company/agent-artifacts-registry.git \
  --ref main \
  --json
aart marketplace list --json
```

`source add` fetches, validates, and stores a managed immutable snapshot before it writes the
origin configuration. `source list --json` reports configured-origin health. The existing
`list/install/update/setup --source` and `--repo` commands remain explicit 0.1 compatibility
adapters; canonical agent install/update lifecycle commands are a follow-up, so callers must not
assume that `source add` reroutes those legacy commands.

The bare `aart` command first asks which path you need:

- **User** installs, updates, or removes harness artifacts from reviewed catalog subscriptions.
- **Maintainer** can enter the same User workflows or curate a local catalog and its tracked
  third-party upstreams through guided, preview-first operations.

Both paths are available in the full-screen TUI and its plain-text fallback.
The first screen explains what aart does. Every later screen starts with a text marker stepper and
ends with one pinned status bar, so progress and controls are clear without color and in narrow
terminals. A trailing `…` marks a path that is still a projection, because the remaining stages
depend on choices not yet made:

```text
✓ How it works → ✓ Role → ✓ Sources → ✓ Harness → ▸ Action → …
...
space=toggle, enter=confirm, b=back, ?=details, a=add, q=quit    2 selected   5-12 of 48
```

The bar is the only place keys are documented. When the terminal is too narrow for all of it, it
drops the row range first, then the selection count, then hints from the right — never `enter` or
`q`, so a screen always states its way forward and its way out.

Use `b` (Backspace also works) in the full-screen TUI or `b`/`back` in the fallback to move back
exactly one applicable stage. Confirmed choices, the artifact/bundle basket, and the curses
cursor/scroll position are retained. If an earlier edit makes only some basket rows invalid, the wizard removes
only those rows and prints the reason. Quitting with a non-empty basket asks before discarding it.

The ordinary **Sources** screen reads the user configuration and managed source pointers without
fetching or writing. It shows registry/direct/local kind, enabled/default state,
current/stale/offline/invalid/incompatible health, organization-required or recommended status,
and exact locally derived company review. Its explicit **Add source** action is a separate reviewed
flow: it synchronizes and validates a snapshot, then saves the new origin. Registry use remains
optional unless organization policy names a required source; an unconfigured user may continue
without sources and exit cleanly. If policy requires several aliases, Add saves each approved,
synchronized source one at a time; marketplace content remains blocked until all required aliases
are enabled. Toggling sources creates an immutable enable/disable/default request. That request is
saved only with the final reviewed `Finalize`, never while browsing or moving back. See
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
- **Symlink** links supported skill and hook directories to immutable managed objects outside the
  Python environment. Copy-only individual rows are disabled with a reason; mixed bundles disclose
  projected linked/copied counts and keep file/merge artifacts in Copy mode.

Before applying an Install, the confirmation view shows the catalog source, selected scope,
resolved destination paths, harnesses, requested mode, selected rows, projected mode counts, and
the ordered setup queue for setup-capable artifacts.
User destinations are absolute. The canonical marketplace materializes verified source content in
the managed object store before linking it. The bounded 0.1 CLI path still requires an explicit
local `--source DIR --link`.

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

For people, launch `aart` with no subcommand and follow the guided source, cart, review, and
Finalize flow. For agents or automation, configure one explicit source and inspect the resulting
local marketplace with JSON:

```sh
aart source add --alias reference --kind registry-git \
  --location https://github.com/M1F1/agent-artifacts-registry.git \
  --ref main --default --json
aart source list --json
aart marketplace list --json
```

`marketplace list` is deliberately read-only. The canonical non-interactive lifecycle runs over the
same configured sources:

```sh
aart marketplace install reference/skill/code-review --profile claude --json
aart marketplace install reference/skill/code-review --profile claude --json --yes
aart marketplace install reference/collection/residuality --profile claude --json --yes
aart marketplace status --profile claude --json
aart marketplace health reference/collection/residuality \
  --environment .agent-artifacts/runtime-environment.json --json
aart marketplace update reference/skill/code-review --profile claude --json --yes
aart marketplace uninstall reference/skill/code-review --profile claude --json --yes
```

Artifacts are addressed as `<source>/<kind>/<name>[@<version>]`. Collections use
`<source>/collection/<name>` and expand to the exact versioned member coordinates compiled into the
marketplace; collections themselves have no `@<version>` suffix. A shorter `<kind>/<name>` is
accepted only when exactly one configured source provides it; otherwise the command fails and names
every valid coordinate rather than picking one. The TUI exposes the same compatible collections as
guided bundle rows.

Artifacts may also publish advisory runtime requirements such as Python versions in the optional
`com.m1f1.runtime-requirements` manifest extension. The consuming repository describes one concrete
runtime in JSON and asks `marketplace health` to compare it. AART does not probe or install runtimes,
and `satisfied`, `unsatisfied`, or `unknown` results never affect whether an artifact can be
installed. See
[`runtime-requirements-v1.md`](docs/marketplace/runtime-requirements-v1.md) for the schemas and
responsibility boundary.

**Without `--yes` every lifecycle command stops after Review** and prints the exact plan it would
apply, changing nothing. This is the non-interactive equivalent of the TUI's Finalize prompt, and
`--yes` finalizes precisely the plan that was just reviewed. Setup authorizations are never implied:
`--authorize-untrusted-source`, `--authorize-custom-entrypoint`, and `--approve-setup-effects` each
have to be passed explicitly, and omitting one denies rather than prompts.

Bare `aart list` and `aart install` remain legacy compatibility commands, not configured-marketplace
onboarding.

---

## User Mode: Install Artifacts Into A Project Or User Profile

User mode is for developers configuring an application repo or their harness-wide user profile.
You install the `aart` tool, configure the reviewed sources or registries you want, and use their
compiled union as a local marketplace. The wheel never ships an operational registry.

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

The TUI is the guided human way to choose project/user scope, Copy/Symlink, and an install/update
review; `aart marketplace install/update/uninstall/status/setup` is the equivalent agent surface
over the same configured sources. The remaining flag-mode lifecycle commands below are retained
only for an explicit external legacy catalog:

```sh
aart install code-review --profile claude --scope user --source /path/to/legacy-catalog
aart status --scope user
aart update --scope user --source /path/to/legacy-catalog
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

An external legacy 0.1 source can describe an MCP as a single `mcp/<name>.json` file or a
directory such as `mcp/<name>/mcp.json` with supporting docs. A canonical registry instead owns
`artifacts/mcp/<name>/`, with a manifest and `payload/` directory. Harness installs merge only the
JSON server definition. Guided setup is declared by a strict `setup/installer.json` contract, and
every package that declares one also ships a validated package-root `SETUP.md`.

### Reviewed Setup Installers On macOS

A directory-shaped artifact may include `setup/installer.json`. The static recipe
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

#### Declining Automation

Every setup review ends with a `Manual alternative` block, and answering No to a consent prompt is
a supported way to finish — not an error path. The block names the package's `SETUP.md` and where
to read it: a commit-pinned HTTPS blob URL when the reviewed source has one, otherwise the local
path inside the materialized source. The document is prose written for a person; AART never parses
it, and a custom entrypoint must open with `# AART manual setup: see ../SETUP.md` so the route is
visible when reading the script instead.

```text
Manual alternative
  instructions  mcp/atlassian/SETUP.md
  source        https://github.com/acme/catalog/blob/<commit>/mcp/atlassian/SETUP.md
  status        No setup effect has run.
```

The `status` line is a claim about effects, not about your intent. `No setup effect has run.`
appears only when nothing was attempted; after a cancelled, failed, or partially rolled-back run
it reads `Automated setup is incomplete; manual action may be needed.` instead. Declining setup
never rolls back the artifact payload that was already installed, and following the manual route
is never recorded as consent to the automation.

Setup recipes support exactly one revision: `schema_version` and `protocol_version` must both be
`2`, which is also what makes `SETUP.md` mandatory. A recipe declaring the superseded `1`/`1` pair
is refused when the catalog is read, with the migration named in the error — raise both fields to
`2` and add the package-root document. Nothing is validated retroactively and nothing is rewritten
in place: setup state recorded by an earlier run stays readable exactly as written.

Flag-mode artifact installation never auto-runs setup. The following setup runner is legacy
installed-state compatibility; the canonical equivalents are the TUI's setup review and
`aart marketplace setup`:

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
code, not a sandbox. The current public-registry `author-aart-installer` skill is a legacy import
and does not yet teach the required `SETUP.md`; `REG02` will rewrite it as a registry-owned skill
before it is advertised for the new workflow.
Until then, catalog authors should follow the full trust model in
[`docs/design/DESIGN-setup-installers.md`](docs/design/DESIGN-setup-installers.md).

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

### Use The Configured Marketplace

The installed `aart` package carries the compiler/tooling, schemas, profiles, and importers — not
an operational artifact catalog. Configure and sync one or more registry, direct Git, or local
sources in the TUI; their union becomes the local marketplace. A registry is optional.

Agents use the same explicit sources without opening the TUI:

```sh
aart source add --alias team --kind source-git \
  --location https://github.com/example/team-agent-artifacts.git --ref main --json
aart marketplace list --json
```

The old flag-mode catalog reader remains only for 0.1 compatibility and therefore requires an
explicit source:

```sh
aart list --source /path/to/catalog
aart list --repo your-org/legacy-catalog
aart install code-review --profile tabnine --source /path/to/catalog
```

These commands print a compatibility warning and never reinterpret the path/repository as a
canonical source alias.

Bundles are curated sets such as "base" or "backend". They can include multiple artifact types
and can extend other bundles, so team setup is one command instead of a pile of paths.

### Managed Symlink Installation

Choose **Symlink** when you want supported artifact trees installed without copying their payload
bytes into every harness destination. Canonical AART links the destination to an immutable object
under its user data directory, never to the Python environment and never directly to a moving Git
checkout. Source sync/update publishes and selects a new immutable object; deleting or recreating
the editable/wheel environment leaves existing links valid.

The bounded legacy flag mode retains its local-checkout `--link` behavior:

```sh
aart install code-review --profile tabnine --source /path/to/catalog --link
```

Copy remains the recommended default. Canonical Symlink changes only after a reviewed AART update;
editing or pulling the original source does not silently change an installed artifact. Use
`aart status` to see the recorded mode and link health. The legacy flag path requires
`--source DIR` and remains explicitly outside this immutable-object guarantee.

### Check, Update, And Uninstall

Every install is recorded in `.agent-artifacts/manifest.json` with files, hashes, source
commit, install mode, and link targets. Freshness checks are opt-in, never ambient.

The following are installed-state/legacy lifecycle commands. They do not turn a configured
marketplace into an implicit source; use `aart marketplace status/update/uninstall` or the TUI for
canonical marketplace lifecycle work, and provide `--source` for any legacy catalog lookup:

```sh
aart status
aart status --json

aart check
aart update --source /path/to/legacy-catalog
aart update --prune --source /path/to/legacy-catalog

aart uninstall code-review --profile tabnine
aart uninstall --all --profile tabnine --dry-run
```

`aart status` is local and uses no network. `aart check` tells you whether the installed tool
or installed artifacts are behind the reviewed source. Each installed manifest entry records its
source identity (a configured local checkout or Git repository/ref), so a later
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

### Legacy 0.1 catalog compatibility (external checkout)

The following section documents the retained 0.1.x workflow for an explicit external catalog
checkout. The AART tool repository intentionally contains no operational artifact catalog.

Maintainer mode can open a source-of-truth legacy catalog repo. In that external checkout, authors
add or edit artifacts under `skills/`, `guidelines/`, `mcp/`, `hooks/`, and `memory/`, compose
them into `bundles/`, and optionally track third-party origins in `upstreams.json`.

Consumer `aart update` never talks directly to third-party upstream repos. Maintainers import or
update artifacts in that checkout, review the diff, and merge the catalog change. Users then
install or update from the reviewed source.

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
```

`upstream health` summarizes artifact counts by type, tracked and untracked artifacts, validation
errors, and tracked origins requiring attention. A missing `upstreams.json` is valid and means the
catalog currently has no tracked third-party origins.

Use `--source .` when you want the CLI to read the external working tree you are editing. In
contrast, `make validate` validates the code-only AART tool checkout and rejects embedded
legacy/canonical catalog paths, including dangling root symlinks.

### Test A Catalog Source

Maintainers can point ordinary list/install/update commands at a local checkout or published
remote catalog to verify catalog changes before users receive the reviewed source revision.

```sh
aart list --source .
aart install --bundle backend --source . --profile tabnine --dry-run

aart list --repo your-org/ai-catalog
aart install code-review --repo your-org/ai-catalog --profile tabnine --dry-run
aart install code-review --version v2.1 --repo your-org/ai-catalog --profile tabnine --dry-run
```

### Create Or Edit Artifacts Manually

In an external legacy checkout, artifacts live in predictable locations:

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
```

### Create Or Edit Bundles

In an external legacy checkout, bundles live in `bundles/<name>.json`. A bundle can include
artifacts, extend other bundles, and pin selected artifacts to a ref for reproducible installs.

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
| `aart source add` | source-dependent | Validate/snapshot one canonical registry/direct/local source, then persist it |
| `aart source list` | no | Show configured origins and managed snapshot health |
| `aart source sync` | source-dependent | Refresh managed snapshots for configured sources; never changes source identity or policy |
| `aart source health` | no | Per-source pointer, revision, and snapshot age; exits non-zero if an enabled source is unhealthy |
| `aart source doctor` | no | Report the source-store layout and any legacy directories; migrates only with `--apply` |
| `aart marketplace list` | no | List the configured canonical marketplace (`--json` is agent-safe) |
| `aart marketplace health --environment PATH` | no | Compare advisory requirements with a repository-supplied runtime inventory; never blocks installation |
| `aart marketplace install/update/uninstall/status/setup` | no (local snapshots) | Canonical JSON lifecycle over configured sources; reviews only unless `--yes` is passed |
| `aart list/install/update/setup --source DIR` or `--repo OWNER/NAME` | source-dependent | Explicit 0.1 compatibility catalog commands; not canonical marketplace lifecycle commands |
| `aart status` / `aart check` | local / source-dependent | Legacy installed-state compatibility inspection |
| `aart update` / `aart uninstall` / `aart setup` | varies | Legacy installed-state compatibility commands; prefer the `aart marketplace` equivalents |
| `aart migrate state` | no | Dry-run/apply/rollback explicit 0.1 installation state |
| `aart upgrade --wheel FILE` | no | Reinstall the CLI from one exact local wheel, index-free |
| `aart upgrade --source-checkout DIR` | no | Reinstall editable from one exact local checkout, index-free |

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

**Catalog source** — Normal users use the configured federated marketplace; the executable wheel
contains no implicit operational catalog. Legacy `list/install/update/setup --source DIR` and
`--repo OWNER/NAME` remain explicit 0.1 compatibility adapters and print a deprecation warning.
They are mutually exclusive and are never reinterpreted as canonical aliases. `--source` cannot be
combined with `--version` since a local checkout has no ref to resolve. The retained remote
compatibility path for `check` accepts `--repo`/`--version`. `upgrade` accepts neither: it requires
exactly one local `--wheel` or `--source-checkout`.

**Installation-state migration** — Review before applying, and use the durable receipt to roll
back from a later process:

```bash
aart migrate state --from 0.1 --dry-run
aart migrate state --from 0.1 --apply
aart migrate state --from 0.1 --rollback
```

Project scope is the default. Add `--scope user` for the old home-global manifest. If equal
`TYPE/NAME` artifacts exist in multiple enabled sources, pass the exact repeatable mapping
`--source-map TYPE/NAME@PROFILE=ALIAS`; AART never chooses by marketplace order during migration.

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

> **Agents:** the dedicated
> [`agent-artifacts` skill in the public reference registry](https://github.com/M1F1/agent-artifacts-registry/tree/main/artifacts/skill/agent-artifacts)
> teaches an agent to drive this CLI (always `--json`, never the human TUI).

---

## Developer workflow

```sh
make quality          # canonical non-mutating local/CI gate suite
make test             # broad Python regression suite + bash E2E compatibility alias
make validate         # code-only repository boundary + zero-runtime-dependency import gate
make packaging-check  # build/import a wheel in a throwaway source copy
python scripts/distribution_smoke.py --json  # editable -> wheel -> recreated environment lifecycle
make system-matrix    # all 13 hermetic AART 1.0 acceptance/fault scenarios
make release-check REGISTRY=/path/to/agent-artifacts-registry  # stable release checklist
make wheel            # release build: stamps the commit and writes dist/*.whl
make version-check    # validate source version consistency and stable-release policy
make version-show     # print the current canonical version
make version-next-alpha  # preview the next 1.0.0aN without changing files
```

The quality tools are required only for development and CI; the installed AART runtime remains
zero-dependency. Install the dev extra to run the same gates as GitHub Actions:

```sh
pip install -e ".[dev]"   # adds the editable build backend and quality/smoke tooling
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

Version changes are deliberate release actions. A prerelease train is finalized explicitly:

```sh
make version-bump-alpha                # explicitly write the next 1.0.0aN
make version-set VERSION=1.0.0rc1      # explicitly write another validated prerelease
make version-finalize                  # prerelease -> stable core after every release task passes
```

Setting, finalizing, or tagging stable `1.0.0` fails closed until every task through `REL01` is
complete. See the [changelog](CHANGELOG.md), [compatibility matrix](docs/release/compatibility-v1.md),
and [0.1.x migration guide](docs/release/migration-v1.md).
Generated `dist/*.whl` files are local/release outputs and are not committed; GitHub release jobs
verify that the tag and source version match before building and uploading a wheel.

Enable the repository-owned pre-commit hook with:

```sh
git config core.hooksPath .githooks
```

The hook is non-mutating: it checks synchronized versions and staged whitespace only. It never
bumps a version, builds a wheel, or stages files.
