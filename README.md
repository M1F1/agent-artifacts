# agent-artifacts

Install a team's AI artifacts — **skills, guidelines, MCP configs, and hooks** — from one
source-of-truth repo into multiple agentic harnesses (OpenCode, Claude Code, Tabnine, …).
Zero runtime dependencies, functional core, offline-installable. Used by humans and agents.

> **Status (this branch).** The pure core, all command modules, profiles, the source
> resolver, and the offline build/install path are implemented and tested. The final
> `argparse` ↔ command wiring (WP-19) has **not** landed here yet, so `agent-artifacts
> --help` / `--version` work, but each subcommand currently prints a scaffold notice instead
> of running. The command/flag surface documented below is the intended, frozen interface
> (it matches the implemented `commands/*.run` and the `Request` model); the examples become
> live once WP-19 wires the parser. The offline install in [Install](#install-offline-no-external-index)
> is fully working today.

---

## The model

- **One source of truth.** A single GitHub repo holds the artifacts (`skills/`,
  `guidelines/`, `mcp/`, `hooks/`), the bundles that group them (`bundles/`), and this CLI.
- **Harnesses are data.** Each target tool (claude, opencode, tabnine, …) is one **profile**
  record describing where each artifact type goes and how merge-type artifacts (MCP, hooks)
  are merged into the harness's shared config. Adding a harness is adding a record — never
  branching code. See [Add a harness](#add-a-harness-in-one-record).
- **`main` + optional pins.** The default version axis is the tip of `main`. Where
  reproducibility matters, pin an artifact (or a whole operation) to a specific commit/tag.
  The manifest always records the **resolved commit**, never bare `main`.
- **Freshness is opt-in, never ambient.** Routine commands make no network call. `status` is
  purely local (on-disk drift). `check` is the explicit, separate command that compares your
  installed commits against `main` and tells you what changed.
- **Functional core, imperative shell.** Every command computes an immutable **Plan** (a
  tuple of file/JSON actions) with pure code, then a thin shell executes it. That is why
  `--dry-run` is free and `--json` just serializes the same Plan.
- **Zero dependencies.** Python standard library only; installs with no external index.

See [`DESIGN.md`](DESIGN.md) for the full rationale and [`PLAN.md`](PLAN.md) for the build plan.

---

## Install (offline, no external index)

Requires Python ≥ 3.10 to run (the build step needs 3.11+ for stdlib `tomllib`). No PyPI,
no network, no `setuptools`/`wheel` package needed — the wheel is a pure-Python
`py3-none-any` build produced with the standard library alone.

```sh
python3 scripts/build_wheel.py                       # -> dist/agent_artifacts-<v>-py3-none-any.whl
pip install --no-index dist/agent_artifacts-*.whl
```

Verify:

```sh
agent-artifacts --help        # or the short alias:
aa --help
aa --version                  # agent-artifacts 0.1.0
```

Or point pip at a directory of prebuilt wheels (also index-free, verified offline):

```sh
pip install --no-index --find-links /path/to/dist agent-artifacts
```

Installing directly from a checkout is possible too, but pip's metadata step still needs a
build backend on the machine — so this path only works in an environment that already has
`setuptools` **and** `wheel` installed (it never fetches them, but it does require them):

```sh
pip install --no-index --no-build-isolation .   # requires setuptools + wheel already present
```

For a clean, dependency-free offline install, prefer the `build_wheel.py` path above — it
needs nothing but the standard library. Both console scripts (`agent-artifacts`, `aa`) are
entry points to the same core.

---

## Usage

```sh
agent-artifacts list      [--bundle B] [--type skill|guideline|mcp|hook] [--version REF] [--source DIR] [--json]
agent-artifacts install   [NAME…] [--bundle B…] [--all] [--profile P[,P…]] [--version REF]
                          [--source DIR] [--dry-run] [--yes] [--force] [--json]
agent-artifacts status    [--json]                  # LOCAL only: installed + on-disk drift, no network
agent-artifacts check     [--version REF] [--json]  # REMOTE, opt-in: installed/CLI commit vs main + what changed
agent-artifacts update    [--bundle B] [--profile P] [--prune] [--dry-run] [--force] [--yes] [--json]
agent-artifacts uninstall [NAME…] [--bundle B] [--all] [--dry-run] [--yes] [--json]
agent-artifacts upgrade   [--version REF]           # reinstall the tool itself (offline-capable)
agent-artifacts                                     # TTY → TUI; else help
aa …                                                # short alias, identical behavior
```

### Global flags

| Flag | Meaning |
| --- | --- |
| `--repo ORG/REPO` | Source-of-truth GitHub repo (default is compiled in; private repos read `$GITHUB_TOKEN`). |
| `--project DIR` | Consumer project to install into (default: current directory). |
| `--source DIR` | Install from a local checkout instead of GitHub — fully offline / air-gapped. Recorded in the manifest as `local:<abspath>`. |
| `--version REF` | Resolve the whole operation at a commit/tag instead of the tip of `main`. |
| `--json` | Machine-readable output (for agents / CI). |
| `--dry-run` | Print the Plan and exit without touching disk (where the command supports writes). |
| `--yes` | Assume "yes" — don't prompt (agent / non-interactive mode). |
| `--force` | Authorize overwrites: conflicting files and colliding MCP/hook merge entries. |

There is **no** `--no-selfcheck` flag — there is no ambient self-check to suppress.

The examples below use the seed catalog shipped in this repo: skill `code-review`, guideline
`python-style`, MCP `postgres`, hook `block-secrets`, and bundles `base` and `backend`
(`backend` extends `base` and adds the `postgres` MCP).

### `list` — browse the catalog

Read-only. Shows artifacts (grouped by type) and bundles. `--source`/`--version` choose where
the catalog comes from; no network when `--source` is local.

```sh
aa list                              # everything: artifacts + bundles
aa list --type skill                 # only skills (bundles hidden when --type is given)
aa list --bundle backend             # what the 'backend' bundle resolves to
aa list --source . --json            # read this checkout, emit JSON
```

### `install` — copy/merge artifacts into harnesses

Select artifacts by name, by `--bundle`, or `--all`; choose one or more harnesses with
`--profile`. Skills/guidelines/hook-scripts are copied; MCP and hook registrations are merged
into the harness's shared config.

```sh
# install a bundle into Claude Code, offline from this checkout, no prompts:
aa install --bundle base --profile claude --source . --yes

# preview first (no disk writes), as JSON:
aa install --bundle backend --profile claude --source . --dry-run --json

# specific artifacts into two harnesses at once:
aa install code-review postgres --profile claude,opencode --source .

# pin the whole operation to a commit, and authorize overwriting a colliding MCP entry:
aa install --all --profile claude --version a1b2c3d --force
```

A conflicting file is never silently overwritten: without `--force` the new version is written
alongside as `<file>.agent-artifacts-new` with a warning. A colliding MCP/hook entry aborts
(exit 4) unless `--force` is given.

### `status` — local drift (no network)

Reads `<project>/.agent-artifacts/manifest.json`: what is installed, from which commit, and
whether any installed file changed on disk versus its recorded install hash. Works fully
offline.

```sh
aa status
aa status --json
```

### `check` — remote freshness (opt-in)

The only routine command that talks to the network. Resolves `main` to a SHA, compares it
against the commit each artifact (and the CLI itself) was installed from, reports *what*
changed, and suggests the next step (`update` for artifacts, `upgrade` for the tool). Fail-soft:
any network/auth error prints one line and exits non-zero without changing anything.

```sh
aa check
aa check --json
aa check --version v1.2.0            # compare against a specific ref instead of main
```

### `update` — re-pull installed artifacts

Re-pulls installed artifacts from `main` (or their pins) and applies the update policy. Clean
files are overwritten; locally-changed files are kept (conflicts get a `.agent-artifacts-new`
sibling unless `--force`). `--prune` removes manifest entries (and their files/merge entries)
that no longer resolve.

```sh
aa update --dry-run                  # preview the update Plan
aa update --profile claude --yes
aa update --prune --force
```

### `uninstall` — reverse an install

Removes what was installed and **only** what was installed: copied files, and our own MCP/hook
merge entries (left untouched if they were since changed by someone else). An otherwise-empty
config file we created may be cleaned up.

```sh
aa uninstall code-review --dry-run
aa uninstall --bundle base --yes
aa uninstall --all --yes
```

### `upgrade` — update the tool itself

Reinstalls `agent-artifacts` from the source (or a release's prebuilt wheel) with
`pip install --no-index` — never from PyPI. Always explicit, never automatic.

```sh
aa upgrade
aa upgrade --version v1.3.0
```

---

## Exit codes

Stable across commands — useful with `--yes` / `--json` in agents and CI.

| Code | Name | Meaning |
| ---: | --- | --- |
| `0` | OK | Success (including a `--dry-run` that planned cleanly). |
| `1` | ERROR | Generic failure. |
| `2` | USAGE | Bad invocation — unknown artifact/bundle/profile name, or no profile selected. |
| `3` | NETWORK | Network / remote failure (e.g. `check`/`update`/`upgrade` with no connectivity). |
| `4` | CONFLICT | A merge collision (MCP/hook) needs `--force` to overwrite. |
| `5` | CORRUPT_MANIFEST | The consumer manifest is unreadable; the tool refuses to touch files. |

---

## Add a harness in one record

A profile is **data**. Built-in profiles (`claude`, `opencode`, `tabnine`) live in
[`agent_artifacts/profiles/builtin.py`](agent_artifacts/profiles/builtin.py). You can add or
override a harness without touching engine code in either of two ways.

A profile declares, per artifact type, the target location and (for merge types) a merge spec.
The field names match the loader and model:

- `skills` → `{ "dir": "<path with optional <name> placeholder>" }`
- `guidelines` → `{ "mode": "copy" | "append-sentinel", "dest": "<dir or file>" }`
- `mcp` → a merge spec: `{ "file", "json_path", "mode": "key", "identity"?, "entry_template"? }`
- `hooks` → `{ "scripts_dir", "events": { <abstract> : <json_path> }, "merge": <merge spec, mode "list"> }`

### Option A — built-in (Python record)

Add a `Profile` to `agent_artifacts/profiles/builtin.py` and register it in the builtins map:

```python
_ANTIGRAVITY = Profile(
    name="antigravity",
    skills=CopyTarget(dir=".antigravity/skills/<name>/"),
    guidelines=GuidelineTarget(mode="append-sentinel", dest="AGENTS.md"),
    mcp=MergeSpec(file=".antigravity/config.json", json_path="mcp.servers", mode="key"),
    hooks=HookTarget(
        scripts_dir=".antigravity/hooks/<name>/",
        events=MappingProxyType({"PreToolUse": "hooks.PreToolUse"}),
        merge=MergeSpec(
            file=".antigravity/config.json",
            json_path="hooks",
            mode="list",
            identity=("matcher", "command"),
            entry_template=MappingProxyType(
                {"matcher": "${matcher}", "command": "${command}"}
            ),
        ),
    ),
)
# add to the builtins map: "antigravity": _ANTIGRAVITY
```

### Option B — per-project override (no code, no rebuild)

Drop a `<project>/.agent-artifacts/profiles.json`. Records here add to or replace built-ins by
name. The keys are exactly the loader's field names
([`agent_artifacts/profiles/loader.py`](agent_artifacts/profiles/loader.py)):

```json
{
  "antigravity": {
    "name": "antigravity",
    "skills":     { "dir": ".antigravity/skills/<name>/" },
    "guidelines": { "mode": "append-sentinel", "dest": "AGENTS.md" },
    "mcp":        { "file": ".antigravity/config.json", "json_path": "mcp.servers", "mode": "key" },
    "hooks": {
      "scripts_dir": ".antigravity/hooks/<name>/",
      "events": { "PreToolUse": "hooks.PreToolUse", "PostToolUse": "hooks.PostToolUse" },
      "merge": {
        "file": ".antigravity/config.json",
        "json_path": "hooks",
        "mode": "list",
        "identity": ["matcher", "command"],
        "entry_template": { "matcher": "${matcher}", "command": "${command}" }
      }
    }
  }
}
```

Then `aa install … --profile antigravity`. No engine changes — the same pure planners build
the Plan from the record.

For reference, the built-in `claude` profile maps skills to `.claude/skills/<name>/`,
guidelines into `CLAUDE.md` (sentinel block), MCP into `.mcp.json` under `mcpServers`, and
hooks into `.claude/settings.json` under `hooks.<event>` with the entry shape
`{ "matcher": …, "hooks": [ { "type": "command", "command": … } ] }`.

---

## Author a hook

A hook is a hybrid: it may ship script files that land on disk (like a skill) and its
*registration* is merged into the harness's shared config (like an MCP entry). Layout under
`hooks/<name>/`:

```
hooks/block-secrets/
├── hook.json            # tool-agnostic descriptor
└── scripts/guard.py     # optional payload, copied to disk
```

The descriptor ([`hooks/block-secrets/hook.json`](hooks/block-secrets/hook.json)) is
harness-agnostic:

```json
{
  "name": "block-secrets",
  "description": "Block writes that introduce obvious secrets.",
  "events": ["PreToolUse"],
  "matcher": "Edit|Write|MultiEdit",
  "command": "python3 ${SCRIPT_DIR}/guard.py",
  "files": ["scripts/guard.py"]
}
```

- `name` — must equal the folder name (`name = key`; this is what bundles reference).
- `events` — abstract event names; each profile maps them to its harness's concrete event keys
  (the profile's `hooks.events`).
- `matcher` — optional selector (e.g. which tools fire the hook); harness-dependent.
- `command` — the shell command. `${SCRIPT_DIR}` resolves to wherever the profile copied this
  hook's scripts, so the command keeps working in each harness's layout.
- `files` — the payload copied to disk (skill mechanics).

**How it installs.** The scripts in `files` are copied into the profile's `hooks.scripts_dir`
(for `claude`, `.claude/hooks/<name>/`). The registration is rendered through the profile's
`entry_template` and merged — list-mode, deduped by `identity` — into the profile's hook config
file. For `claude` this appends under `hooks.PreToolUse` in `.claude/settings.json`:

```json
{ "matcher": "Edit|Write|MultiEdit",
  "hooks": [ { "type": "command", "command": "python3 .claude/hooks/block-secrets/guard.py" } ] }
```

The manifest records **both** the copied files and the merge entry, so `uninstall` reverses
both — removing only our entry, never others'. Hooks run commands, so `check`/`status` surface
exactly which hook commands a profile would register, and every merge is previewable with
`--dry-run`. See `DESIGN.md` §5.4 (hook format) and §10 (the merge engine).

Add a hook to a bundle by listing its name under `hooks` in `bundles/<bundle>.json`:

```json
{ "name": "base", "includes": { "hooks": ["block-secrets"] } }
```
