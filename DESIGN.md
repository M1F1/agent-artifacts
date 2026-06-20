# agent-artifacts — Design (for review)

One source of truth for a team's AI artifacts (skills, guidelines, MCP configs, **hooks**)
plus a tool, `agent-artifacts` (short alias `aa`), that installs selected sets (bundles)
into multiple agentic harnesses (OpenCode, Claude Code, Tabnine, … and future ones such as
Hermes or Antigravity). Used both by humans and by agents.

This document describes **what** we build and **why**. The implementation plan ("how")
follows separately, after review of this design.

---

## 0. What changed from the first draft

This revision folds in eight directives. Map for the reviewer:

| # | Directive | Where it lands |
| --- | --- | --- |
| 1 | **Hooks** as a fourth artifact type | §2, §4, §5.4, §6, §10, §12 |
| 2 | Rename the app to **agent-artifacts** (`aa` alias) | everywhere; paths in §4, §11, §13 |
| 3 | Freshness check is **opt-in, a separate command** — never on every invocation | §8 (rewritten), §13 |
| 4 | **Zero external Python dependencies** (stdlib only) | §3, §14, §15 |
| 5 | **pip-installable with no external index** (fully offline) | §15 (new) |
| 6 | CLI and all logic in a **functional style** | §14 (new), and reflected in §8–§10 |
| 7 | **Easily add new harnesses** (Hermes, Antigravity, …) as data, not code | §11 (rewritten) |
| 8 | Design first → your review → detailed plan | this doc is step 1 |

---

## 1. Goal and scope

The problem is not authoring AI artifacts — it is keeping them maintained and in sync across
a multi-repo setup. After a while several copies of the same skill float around and nobody
knows which one is canonical. The answer: one source of truth (a GitHub repo) plus a small
installer tuned to the real audience — a team on GitHub using more than one AI harness.

**In MVP scope:** four artifact types, bundles as sets, install / update / uninstall,
opt-in freshness checking against `main`, multi-harness (OpenCode, Claude Code, Tabnine,
extensible), human + agent modes, offline-capable, zero runtime dependencies.

**Out of MVP scope (on purpose):** external artifact sources, per-artifact semver, package
signing, time-released content dosing.

## 2. Glossary

- **Artifact** — a single named unit of one of four types (skill / guideline / mcp / hook).
  It physically lives in exactly one place in the repo.
- **Type** — `skill`, `guideline`, `mcp`, or `hook`. Determines format and install mechanics.
- **Bundle** — a named set of artifacts (a table of contents). Holds no files, only
  references artifacts by name. May extend other bundles.
- **Harness** — a concrete AI tool that consumes artifacts (OpenCode, Claude Code, Tabnine,
  …). Adding one is a data change (see **Profile**), not a code change.
- **Profile** — the data mapping each artifact type to a harness's target locations and merge
  rules (where skills go, where MCP/hook config is merged, how guidelines are attached).
- **Pin** — fixing an artifact (or a whole install) to a specific commit/tag of the source
  repo instead of the tip of `main`.
- **Plan** — an immutable, side-effect-free description of the file/JSON changes an operation
  *would* make. The pure core produces a Plan; the imperative shell executes it (§14). This
  is what makes `--dry-run` free and the logic testable.
- **Consumer manifest** — the record, kept in the consuming project, of what was installed
  (artifact, type, bundle, source commit, files/entries, hashes).
- **Source of truth** — the GitHub repo holding artifacts, bundles, and the `agent-artifacts`
  code.

## 3. Architecture

One repo (monorepo) holds **artifacts + bundles + CLI code**. Releases are not tag-based —
the default axis is the **tip of `main`**, with an optional pin where reproducibility matters.

```
   source-of-truth repo (GitHub)            consumer project (local)
   ┌──────────────────────────────┐         ┌────────────────────────────────┐
   │ skills/ guidelines/ mcp/ hooks/│  aa     │ .opencode/skills/…              │
   │ bundles/                      │ ──────▶ │ .claude/skills/… .claude/hooks/…│
   │ agent_artifacts/ (CLI code)   │ (copy/  │ opencode.json (merged MCP)      │
   │ main = axis, optional pin     │  merge) │ .claude/settings.json (hooks)   │
   └──────────────────────────────┘         │ .agent-artifacts/manifest.json  │
                                            └────────────────────────────────┘
```

Two design spines:

- **Functional core, imperative shell** (§14). Every decision is a pure function over
  immutable data; all IO (network, filesystem, stdout) lives at the edges. Operations
  compute a **Plan** (pure), then a thin shell executes it.
- **Harnesses are data** (§11). A profile is a record; adding Hermes/Antigravity is adding a
  record, never branching code.

The CLI installs once as a local package (offline wheel or `pip install --no-index`, §15),
**with zero runtime dependencies** (Python stdlib only).

## 4. Source-of-truth repo structure

Artifacts are grouped **by type**; bundles are a separate composition layer. An artifact
exists in one place regardless of how many bundles include it.

```
agent-artifacts/
├── skills/                      # type: skill (open Agent Skills standard)
│   ├── code-review/SKILL.md
│   └── test-writer/SKILL.md
├── guidelines/                  # type: guideline (team rules, markdown)
│   ├── python-style.md
│   └── api-conventions.md
├── mcp/                         # type: mcp (MCP server defs, JSON)
│   ├── postgres.json
│   └── github.json
├── hooks/                       # type: hook (event automations + optional scripts)
│   ├── block-secrets/
│   │   ├── hook.json
│   │   └── scripts/guard.py
│   └── format-on-write/
│       └── hook.json
├── bundles/                     # composition layer — tables of contents only
│   ├── base.json
│   └── backend.json
├── agent_artifacts/             # CLI code (stdlib only, functional)
├── dist/                        # prebuilt offline wheel (for index-free pip install, §15)
└── .github/workflows/           # CI: validation + release injects commit into the CLI
```

Rule: **name = key.** A skill's folder name and a guideline/mcp/hook's file/folder name equal
the name bundles reference. Bundle manifests carry no paths — only names; the type directory
follows from the section the name appears under.

## 5. Artifact types

### 5.1 Skills
Folder `skills/<name>/` with a `SKILL.md` (YAML frontmatter: `name`, `description`, plus
optional `scripts/`, `references/`, `assets/`). Install = **copy** the whole tree into the
profile's skills directory.

### 5.2 Guidelines / rules
File `guidelines/<name>.md`. Optional frontmatter (`description`). Install = attach to the
profile's rules location. The *attach strategy* is per-profile data (copy as a separate file,
or append into `CLAUDE.md`/`AGENTS.md` inside a sentinel-marked block for clean removal) —
see §11.

### 5.3 MCP configs
File `mcp/<name>.json` describing one MCP server in a tool-agnostic shape:

```json
{
  "name": "postgres",
  "description": "MCP server for PostgreSQL",
  "server": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-postgres"],
    "env": { "DATABASE_URL": "${DATABASE_URL}" }
  }
}
```

A single MCP file is **self-contained**. Install is **not a file copy** but **merging** the
entry into the harness's shared config (§10).

### 5.4 Hooks (new)
Hooks are **event automations**: on some harness event (a tool is about to run, a prompt was
submitted, a session ended…) the harness runs a command. A hook is a **hybrid** of a skill
(it may ship script files that must land on disk) and an MCP config (its *registration* is
merged into the harness's shared config). Folder `hooks/<name>/`:

```
hooks/block-secrets/
├── hook.json            # tool-agnostic descriptor
└── scripts/guard.py     # optional payload, copied to disk like a skill
```

`hook.json` (tool-agnostic):

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

- `events` — abstract event names; a profile maps them to a harness's concrete event keys.
- `matcher` — optional selector (e.g. which tools the hook fires for); harness-dependent.
- `command` — the shell command; `${SCRIPT_DIR}` resolves to where the profile copied this
  hook's scripts (so the command keeps working wherever the harness expects scripts).
- `files` — payload copied to disk (skill mechanics, §9).

Install = **copy scripts (like a skill) + merge the registration into the harness's hook
config (like MCP, §10)**. Not every harness models hooks identically; the profile carries the
target shape as data (§10, §11).

## 6. Bundles — composition model

A bundle is `bundles/<name>.json`: the table of contents of a set. An artifact does not know
which bundles include it (it stays clean and portable).

```json
{
  "name": "backend",
  "description": "Backend team set",
  "extends": ["base"],
  "includes": {
    "skills":     ["code-review", "db-migrations"],
    "guidelines": ["python-style"],
    "mcp":        ["postgres"],
    "hooks":      ["block-secrets"]
  },
  "pins": { "code-review": "a1b2c3d" }
}
```

- **`includes`** — artifacts by name, grouped by type (now including `hooks`).
- **`extends`** — compose from other bundles: `backend` = everything in `base` plus its own
  `includes`. Builds sets from bricks without duplication.
- **`pins`** — optional pinning of selected artifacts to a commit/tag (§7). The same artifact
  may appear in several bundles with different pins.

**Resolving a bundle** (pure function, at install time): expand `extends` (union of
`includes`, cycle detection), merge `pins` (more-derived bundle overrides base; on conflict
the derived wins, with a warning), and validate every name resolves to an existing artifact.

**CI validation:** every reference must resolve to an existing artifact; missing → build
error, never a silent skip. That keeps manifest and disk honest.

## 7. Versioning: `main` + pin

- **Default channel: `main`.** Install without a pin takes artifacts from the tip of `main`.
- **Pin** = fix to a specific commit/tag. The unit of a pin is **the whole repo state at that
  commit** (not a single file): "take `code-review` from `a1b2c3d`" means "fetch the repo
  snapshot at `a1b2c3d` and extract `skills/code-review/`".
- **Mixed versions are allowed:** in one install, one artifact can come from `main` and
  another be pinned to an older commit (e.g. after a regression in a newer skill).
- **Mechanics:** for a set with several distinct pins, the tool fetches one repo snapshot per
  used commit (tarball, cached) and extracts the right artifacts from each.
- **No per-artifact semver.** We say "from commit/tag X", not "version 2.1.0 of this skill".
- **Pin levels:** global (`--version <ref>` for the whole operation) and per-artifact (`pins`
  in a bundle). The manifest always records the **resolved concrete commit**, never bare
  "main".

## 8. Freshness as an explicit command (opt-in)

> **Change from the first draft.** The original design ran a self-check on **every** command.
> This is removed. `agent-artifacts` performs **no network call and no `main` comparison
> unless you run a command that needs it.** Freshness is a deliberate, separate action.

- **No ambient self-check.** Routine commands do not phone home. `status` (below) is purely
  local. There is no per-invocation timeout, no background TTL cache, no surprise stderr line.
- **`status` — local only, no network.** Reads the consumer manifest: what is installed, from
  which commit, and on-disk drift (files changed locally vs. the recorded install hash). Works
  fully offline.
- **`check` — remote, opt-in.** The explicit freshness command. It:
  1. resolves `main` to a SHA — `GET /repos/{repo}/commits/main`;
  2. compares against the commit each artifact was installed from (and against the CLI's own
     build commit, §15);
  3. uses `GET /compare/{base}...{head}` to report *what* changed — which installed artifacts
     moved, and whether the CLI code itself moved — and prints the suggested next step
     (`agent-artifacts update` for artifacts, `agent-artifacts upgrade` for the tool);
  4. is **fail-soft**: any network/timeout/auth error prints one clear line and exits without
     touching anything.
- **`update`** re-pulls installed artifacts from `main` (or pins) and applies the update
  policy (§9/§10). **`upgrade`** reinstalls the tool itself from `main` (§15). Neither ever
  runs automatically — only on request.

Fetch mechanics (used by `install`/`update`/`upgrade`/`check`): `GET
/repos/{repo}/tarball/{ref}` (stdlib `urllib` + `tarfile`), unpacked to
`~/.cache/agent-artifacts/<repo>/<sha>/`. A commit snapshot is immutable, so it caches
permanently; `main` is resolved to a SHA first, then fetched by SHA.

## 9. Install and copy policy (skills, guidelines, hook scripts)

We copy physically (no symlinks) — portable, survives CI, works air-gapped. Operations are
idempotent; writes are atomic per artifact (staging → move).

The manifest records each file's hash at install. The per-file update policy is a **pure
decision function** `classify(disk, base, new)` (`disk` = current on-disk state, `base` =
hash at install, `new` = repo version):

| State | Decision |
| --- | --- |
| file missing from disk | recreate from `new` |
| `disk == base`, `new == base` | nothing (current) |
| `disk == base`, `new != base` | **overwrite** with `new` (clean update) |
| `disk != base`, `new == base` | keep local change, record "drift" |
| `disk != base`, `new != base` | **conflict**: keep local, write `<file>.agent-artifacts-new` alongside, warn (unless `--force`) |

Files removed in the new version → removed (if clean). New files → added. This table is data:
`classify` returns a value; a second pure function turns that value into a Plan **Action**
(§14), so `--dry-run` shows exactly these decisions without doing them.

Hook **scripts** follow this same policy. The hook **registration** follows the merge policy
(§10).

## 10. Merge engine (MCP + hooks)

MCP entries and hook registrations differ from skills/guidelines: they live in a **shared
harness file** (e.g. `opencode.json`, `.claude/settings.json`) alongside entries that are not
ours. So install = **merge**, governed by one generic, pure merge planner driven by a
per-profile **MergeSpec** (data):

```
MergeSpec(file, json_path, mode, identity, entry_template?)
   mode = "key"   → set one key under json_path           (MCP: name → server)
   mode = "list"  → append one entry to an array at json_path, deduped by `identity`
                    (hooks: append to hooks.<event>)
   entry_template → optional declarative shape that renders the tool-agnostic descriptor
                    into the harness's entry shape (hooks vary by harness)
```

- **MCP (`mode="key"`).** Load (or create) the harness config, descend to the profile's JSON
  path, set `name → server`. Identity = the key.
- **Hooks (`mode="list"`).** Render the descriptor through the profile's `entry_template`
  (a pure `render(template, descriptor)` fills `${matcher}`, `${command}`, …), then append to
  the array at the profile's event path, deduped by `identity` (e.g. matcher+command). For
  Claude Code this produces, under `hooks.PreToolUse`:
  ```json
  { "matcher": "Edit|Write|MultiEdit",
    "hooks": [ { "type": "command", "command": "python3 .claude/hooks/block-secrets/guard.py" } ] }
  ```
- **Overwrite protection.** If an entry with the same identity already exists and differs from
  ours → **ask for permission** (agent mode without `--force`/`--yes`: abort with a clear
  message; with `--force`: overwrite). Existing non-colliding entries are never touched.
- **Clean extraction.** The manifest records what we added: file, JSON path, mode, identity,
  inserted value hash, and whether we created the file. Uninstall removes **only our entry**
  (and only if the value is still ours — otherwise it asks), never others'; an empty file we
  created may be cleaned up.

Adding a harness whose hook/MCP shape is expressible as a `MergeSpec` + `entry_template` is a
pure data change. For a genuinely exotic shape, a profile may name a pure `renderer` function
(a lookup in a small registry, §14) — still functional, still no branching in the engine.

## 11. Harness profiles (data, easily extended)

A profile is **data**, not branches in code. Profiles are built in (zero-config), overridable
by `<project>/.agent-artifacts/profiles.json`. You can install to several at once. **Adding a
harness = adding one record** — that is the whole point of directive #7.

A profile record, per artifact type, declares the target location and (for merge types) a
MergeSpec:

```jsonc
// built-in: profiles/claude
{
  "name": "claude",
  "skills":     { "mode": "copy",  "dir": ".claude/skills/<name>/" },
  "guidelines": { "mode": "append-sentinel", "file": "CLAUDE.md" },
  "mcp":        { "merge": { "file": ".mcp.json", "json_path": "mcpServers", "mode": "key" } },
  "hooks": {
    "scripts_dir": ".claude/hooks/<name>/",
    "events": { "PreToolUse": "hooks.PreToolUse", "PostToolUse": "hooks.PostToolUse", "Stop": "hooks.Stop" },
    "merge": {
      "file": ".claude/settings.json", "mode": "list",
      "identity": ["matcher", "command"],
      "entry_template": { "matcher": "${matcher}", "hooks": [ { "type": "command", "command": "${command}" } ] }
    }
  }
}
```

Current built-in profiles (concrete paths are **defaults to verify** in your environment, §19):

| Profile | Skills → | Guidelines → | MCP → (file · JSON path) | Hooks → |
| --- | --- | --- | --- | --- |
| `opencode` | `.opencode/skills/<name>/` | `AGENTS.md` (sentinel) | `opencode.json` · `mcp.<name>` | TBD (verify event model) |
| `claude` | `.claude/skills/<name>/` | `CLAUDE.md` (sentinel) | `.mcp.json` · `mcpServers.<name>` | `.claude/settings.json` · `hooks.<event>` |
| `tabnine` | `.tabnine/agent/skills/<name>/` | `.tabnine/guidelines/` (copy) | Tabnine settings (verify) | TBD (verify) |

**Future harnesses (e.g. Hermes, Antigravity).** Adding one is a new record — illustrative
stub, paths to fill when we target it:

```jsonc
// profiles/antigravity  (ILLUSTRATIVE — paths unverified)
{
  "name": "antigravity",
  "skills":     { "mode": "copy", "dir": ".antigravity/skills/<name>/" },
  "guidelines": { "mode": "append-sentinel", "file": "AGENTS.md" },
  "mcp":        { "merge": { "file": ".antigravity/config.json", "json_path": "mcp.servers", "mode": "key" } },
  "hooks":      { "scripts_dir": ".antigravity/hooks/<name>/", "events": { /* … */ }, "merge": { /* … */ } }
}
```

No engine code changes — `install` reads the record and the same pure planners (§9, §10)
produce the Plan. If a new harness has a truly novel shape, it supplies a named pure renderer
(one entry in the renderer registry, §14); everything else stays data.

## 12. Consumer manifest

`<project>/.agent-artifacts/manifest.json`. Entry key: `(artifact, profile)`. Different types
carry different "proof of install": files (skill/guideline), a merged entry (mcp), or **both**
(hook).

```json
{
  "repo": "org/agent-artifacts",
  "installed": [
    {
      "artifact": "code-review", "type": "skill", "bundle": "backend",
      "profile": "claude", "source": "pin:a1b2c3d",
      "files": { ".claude/skills/code-review/SKILL.md": "sha256:…" },
      "installed_at": "2026-06-19T10:00:00Z"
    },
    {
      "artifact": "postgres", "type": "mcp", "bundle": "backend",
      "profile": "claude", "source": "main:9f8e7d6",
      "merge": { "file": ".mcp.json", "json_path": "mcpServers.postgres", "mode": "key",
                 "value_hash": "sha256:…", "created_file": false, "overwrote": false },
      "installed_at": "2026-06-19T10:00:00Z"
    },
    {
      "artifact": "block-secrets", "type": "hook", "bundle": "base",
      "profile": "claude", "source": "main:9f8e7d6",
      "files": { ".claude/hooks/block-secrets/guard.py": "sha256:…" },
      "merge": { "file": ".claude/settings.json", "json_path": "hooks.PreToolUse", "mode": "list",
                 "identity": { "matcher": "Edit|Write|MultiEdit",
                               "command": "python3 .claude/hooks/block-secrets/guard.py" },
                 "value_hash": "sha256:…", "created_file": false, "overwrote": false },
      "installed_at": "2026-06-19T10:00:00Z"
    }
  ]
}
```

`source` is always a resolved commit (`main:<sha>` or `pin:<sha>`), never bare "main". A hook
entry carries **both** `files` and `merge` — uninstall reverses both.

## 13. CLI interface

One core, two skins (TTY with no targets → TUI; otherwise flag mode). TUI in `curses`
(stdlib) with an `input()` fallback. Agent mode: `--yes`, `--json`, unambiguous exit codes.
Both `agent-artifacts` and `aa` are entry points to the same core.

```
agent-artifacts list      [--bundle B] [--type skill|guideline|mcp|hook] [--version REF] [--source DIR] [--json]
agent-artifacts install   [NAME…] [--bundle B…] [--all] [--profile P[,P…]] [--version REF]
                          [--source DIR] [--dry-run] [--yes] [--force] [--json]
agent-artifacts status    [--json]                  # LOCAL only: installed + on-disk drift, no network
agent-artifacts check     [--version REF] [--json]  # REMOTE, opt-in: installed/CLI commit vs main + what changed
agent-artifacts update    [--bundle B] [--profile P] [--prune] [--dry-run] [--force] [--yes] [--json]
agent-artifacts uninstall [NAME…] [--bundle B] [--all] [--dry-run] [--yes] [--json]
agent-artifacts upgrade   [--version REF]            # reinstall the tool itself from main (offline-capable)
agent-artifacts                                      # TTY → TUI; else help
aa …                                                 # short alias, identical behavior
```

Global: `--repo`, `--project`, `--source DIR`. `--source DIR` installs from a local checkout
(offline / air-gapped). `--force` authorizes overwrites (conflicting files, colliding merge
entries). `--dry-run` prints the Plan (§14) and exits without touching disk. There is **no**
`--no-selfcheck` flag — there is no ambient self-check to suppress (§8).

## 14. Functional programming architecture

The CLI and all logic are written in a **functional core, imperative shell** style, stdlib
only. The goal: decision logic that is pure, immutable, and testable without a filesystem or
network; all effects pushed to the edges and represented as data.

**Immutable data, no behavioral classes.**
- Records are `@dataclass(frozen=True, slots=True)` or `typing.NamedTuple`; collections are
  `tuple` / `frozenset` / read-only `MappingProxyType`. Nothing mutates in place.
- The domain is **data + functions**, not objects with methods. Inheritance/polymorphism is
  replaced by **dispatch dictionaries** keyed by a value (the artifact `type`, the Action
  kind, the merge `mode`, the renderer name).

**Effects as data (the Plan).** Operations never touch disk directly. They compute a Plan — a
`tuple` of immutable Actions:

```
Action = CopyTree(src, dst)
       | WriteFile(path, content)
       | MergeJson(file, json_path, mode, value, identity, entry_template)
       | RemovePath(path)
       | WriteManifest(entries)
       | Warn(message)
```

- `plan(request, catalog, manifest, profiles) -> Plan` is **pure** — given the same inputs it
  always yields the same Plan. It composes smaller pure functions: `resolve_bundle`,
  `classify` (§9), the merge planner (§10), manifest diffing.
- `execute(plan) -> Report` is the **only** effectful function: a dispatch over Action kinds
  to small IO performers. `--dry-run` simply renders the Plan instead of executing it; `--json`
  serializes it. Same Plan, different interpreter.

**Errors as values.** Domain failures are returned, not thrown: a `Result = Ok(value) |
Err(reason)` (frozen) with `map`/`bind` helpers to chain steps; validation **accumulates**
errors into a tuple (so `agent-artifacts install` reports every bad reference at once, not the
first). Exceptions are reserved for genuinely exceptional IO at the shell boundary.

**Composition over control flow.** `functools.reduce` to fold pins/extends; `map`/`filter`/
comprehensions and `itertools` for transforms; `functools.partial` to specialize planners per
profile; `functools.lru_cache` for pure memoization (e.g. parsing a fetched catalog). Small
functions, composed; the type→operation table is a dict, not a class hierarchy:

```python
PLANNERS = {                      # value-keyed dispatch, not subclasses
    "skill":     plan_skill,
    "guideline": plan_guideline,
    "mcp":       plan_mcp,
    "hook":      plan_hook,
}
RENDERERS = { "default": render_template }   # escape hatch for exotic harness shapes (§10/§11)
```

Why this matters here: install/update/uninstall become "build a Plan, then run it." The Plan
is inspectable (`--dry-run`, `--json`), golden-testable, and free of IO — which is exactly the
safety property a tool that edits other people's config files needs.

## 15. Packaging and offline install (no external index, zero deps)

**Zero runtime dependencies.** Standard library only. `pyproject.toml` declares
`dependencies = []`. Nothing to resolve, nothing to fetch at install time.

**Install via pip with no external index.** Two fully-offline paths, no PyPI, no network:

1. **Prebuilt wheel (primary).** The repo ships a pure `py3-none-any` wheel under `dist/`
   (committed and/or attached to releases). Because there are no dependencies, installing it
   never reaches an index:
   ```
   pip install --no-index ./dist/agent_artifacts-<version>-py3-none-any.whl
   # or, anywhere on the machine:
   pip install --no-index --find-links /path/to/dist agent-artifacts
   ```
2. **From a checkout (secondary).** Build-isolation off, so pip uses the already-present
   setuptools instead of fetching a backend:
   ```
   pip install --no-index --no-build-isolation .
   ```

`pipx install --no-index …` works the same for an isolated user install. Distribution name
`agent-artifacts`; import package `agent_artifacts`; two console-script entry points
(`agent-artifacts`, `aa`) → `agent_artifacts.cli:main`. Target Python ≥ 3.10 (for
`dataclass(slots=True)`).

**Build commit injection (`__commit__`).** Release/build writes the source SHA into a
generated `agent_artifacts/_commit.py` (`COMMIT = "<sha>"`; fallback `"unknown"` for dev
installs) before packaging. It is consulted **only** by `check` and `upgrade` (§8) — never on
a normal command.

**`upgrade` stays index-free.** It fetches the source tarball (or the release's prebuilt
wheel) and installs it with `pip install --no-index` — it never pulls from PyPI. Self-update
is always explicit (§16), never automatic.

## 16. Error modes and resilience

- `check`/`update`/`upgrade` with no network → one clear fail-soft line, exit non-zero, no
  changes; routine commands need no network at all (§8).
- Private repo without a token → "set GITHUB_TOKEN", non-zero exit.
- File conflict → never a silent overwrite (`.agent-artifacts-new` + warning).
- MCP/hook merge collision → ask for permission; agent mode without `--force` aborts.
- Corrupt manifest → the tool refuses to touch files and offers `--repair`.
- Bundle referencing a missing artifact → validation error (locally and in CI).
- Every destructive Plan is previewable with `--dry-run` before it runs.

## 17. Security and trust

- **Stateless = zero-config:** default repo compiled in, override via env/flag; the only
  optional secret is `GITHUB_TOKEN` for a private repo. Cache and manifest are disposable
  local data, not configuration.
- **Vendoring:** third-party skills (e.g. Superpowers) are copied into the repo and governed
  like our own; bundles only group them. No fetching from foreign repos in MVP.
- **Merge is careful:** MCP/hook merges never delete others' entries; overwrite only on
  consent. Hooks run commands — `check`/`status` surface exactly which hook commands a profile
  would register, and merges are previewable via `--dry-run` before anything is written.

## 18. Conscious choices and non-goals

- **Tags/semver as the axis** — rejected for `main` + pin (simpler; reproducibility preserved
  by pins where needed).
- **Per-artifact semver** — out of MVP (a package registry per artifact).
- **External artifact sources** — out of MVP (would turn the "table of contents" into a second
  npm).
- **npm / GitHub Packages** — Python shop; GitHub Packages has no PyPI; an npm rail buys
  nothing.
- **Symlinks as default** — fragile; copying is predictable.
- **Ambient self-check on every command** — removed this revision; replaced by explicit
  `check` (§8).
- **Automatic self-update** — supply-chain risk; stays informational + explicit `upgrade`.
- **Tool marketplace** — vendor lock-in; we want multi-harness.
- **Persistent global config** — would break statelessness.

## 19. Open questions to verify (before/after MVP)

1. **Skill, MCP, and hook locations per harness.** §11's table is best-effort defaults.
   Confirm: where Tabnine reads workspace skills and stores MCP config; the exact MCP key in
   `opencode.json`; OpenCode's hook/plugin event model; Claude Code's hook event set and
   `settings.json` shape (project vs. `.local`).
2. **Guideline attach strategy** — separate file vs. sentinel-marked block in
   `AGENTS.md`/`CLAUDE.md`, per profile (the `mode` field in §11).
3. **Hook event vocabulary** — the tool-agnostic `events` names and their per-harness mapping;
   confirm whether a declarative `entry_template` covers all target harnesses or some need a
   named renderer (§10).
4. **`bundles/` as a folder (one file per bundle)** — assumed; confirm it beats a single
   `bundles.json` at your set count.
5. **`__commit__` injection at build** — release/install records `git rev-parse HEAD` so
   `check`/`upgrade` have a reference point (§15).
6. **Committing the prebuilt wheel vs. release-only asset** — decide whether `dist/*.whl`
   lives in the repo (truly offline clone-and-install) or only on releases (§15).
```
