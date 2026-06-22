# agent-artifacts — Design: the `agents` artifact type (for review)

Companion to [DESIGN.md](DESIGN.md). This adds a **fifth artifact type** — `agents`, the
per-harness top-level instruction file (`CLAUDE.md` / `AGENTS.md` / …) — plus two riders the
same change touches: **correcting the `tabnine` profile paths** against the official Tabnine
CLI docs, and **adding a `vibe` profile** for Mistral Vibe.

As with the parent design, this document is **what** and **why**; the **how** is in
[PLAN-agents.md](PLAN-agents.md) and should be read after this is approved.

> **Decisions already taken** (in review, before this draft): type name = **`agents`**;
> default install mode = **`prepend`**; per-profile type support is made **optional** so a
> harness can decline a type it can't express; tabnine MCP target = **`.tabnine/agent/settings.json` · `mcpServers`** (per directive — see §6.1 for the doc caveat).

---

## 1. Goal and scope

Every harness reads a single top-level instruction document the model sees on every turn:
Claude Code reads `CLAUDE.md`, OpenCode / Codex / Mistral Vibe read `AGENTS.md`, and so on.
Today agent-artifacts can *append* topical **guidelines** into that file (sentinel blocks),
but it cannot manage the file as **the team's house instructions** — own it, seed it, or
inject a canonical preamble/postamble. That is what the `agents` type is for.

**In scope**
- A new artifact type `agents`, grouped by type in its own `agents/` source directory, a
  first-class member of bundles (`includes.agents`).
- Four install modes against the consumer's instruction file: **replace**, **prepend**,
  **append**, **skip** (default **prepend**).
- Clean, idempotent re-install and clean uninstall for every mode.
- Per-profile mapping for `claude`, `opencode`, `tabnine`, and a new `vibe` profile.
- Corrected `tabnine` paths; `Profile` type-targets become optional.

**Out of scope (unchanged from parent §1)**
- External artifact sources, per-artifact semver, signing.
- A TOML writer (so Mistral Vibe MCP/hooks are deferred — §7.2).

## 2. Naming — why `agents`

The generic term for "the top-level instruction file" was chosen as **`agents`** (directory
`agents/`, type `"agents"`, bundle section `includes.agents`). It mirrors the emerging
cross-tool **`AGENTS.md`** convention, so the source name matches what most harnesses already
call the file.

- **Type vs. filename.** `agents` is *our* harness-agnostic type. The concrete destination
  **filename is per-profile** (`CLAUDE.md` for Claude, `AGENTS.md` for OpenCode/Vibe). One
  source artifact, many destination filenames — exactly the artifact/profile split of parent §4.
- **Deliberate departure from the singular-type convention.** Existing types are singular
  (`skill`/`guideline`/`mcp`/`hook`). `agents` is intentionally the collective noun: it names
  *the AGENTS.md document*, not "one agent". `agent` (singular) was rejected because it reads
  as "a sub-agent."
- **Known future-collision caveat.** Both Tabnine and Mistral Vibe also have a *separate*
  "custom agents / sub-agents" concept (`~/.vibe/agents/*.toml`, Tabnine `agents` settings).
  If we ever add a type for **those**, it must be named distinctly (`subagents` or
  `agentdefs`) to avoid clashing with this instruction-file type. Recorded here so the name is
  used eyes-open.

## 3. The `agents` artifact

### 3.1 Source layout

A flat markdown file per artifact, like guidelines:

```
agent-artifacts/
└── agents/
    ├── house.md            # the team's canonical AGENTS.md / CLAUDE.md content
    └── security-preamble.md
```

- **`name = key`** (parent §4): `agents/house.md` is referenced as `house` under a bundle's
  `includes.agents`.
- **Optional frontmatter.** `description` (for `list`), and an optional **`mode:`** declaring
  this artifact's *preferred* install mode (overridable per §3.4). Body below the frontmatter
  is the instruction content, written verbatim into the destination file.

```markdown
---
description: House rules every repo gets (build, test, PR etiquette).
mode: prepend
---
# Engineering house rules
- Run `make test` before every PR.
- ...
```

### 3.2 The four install modes

The mode governs how our content combines with whatever already lives in the consumer's
instruction file. All four are always available; the default is **`prepend`**.

| Mode | Behaviour when the destination file… exists / is absent | Reversible by |
| --- | --- | --- |
| **`prepend`** *(default)* | inject our content **at the top**, wrapped in a removable sentinel block; foreign content untouched below / create the file with our block | strip our block |
| **`append`** | same, but our block goes **at the bottom** / create the file with our block | strip our block |
| **`replace`** | **overwrite the whole file** with our content (back up prior content to `<file>.agent-artifacts-bak`; requires `--force` when the file is non-empty) / write our content as the file | remove our file / restore `.bak` |
| **`skip`** | **do nothing** (leave the file as-is, emit a notice) / create the file with our content | remove our file (only if we created it) |

`prepend`/`append` are **idempotent**: re-installing replaces our existing same-named block in
place (byte-identical), never stacking duplicates. `replace` is the only destructive mode and
is gated by `--force` + a `.bak` backup, consistent with parent §16 ("never a silent
overwrite"). `skip` is "seed if missing" — the safe choice for files a consumer hand-authored.

### 3.3 Sentinel format (prepend / append)

Our injected block is wrapped in **HTML-comment** sentinels, name- and type-scoped:

```
<!-- >>> agent-artifacts agents:house >>> -->
…our content…
<!-- <<< agent-artifacts agents:house <<< -->
```

Two deliberate choices:
- **HTML comments, not `#` headings.** The existing *guideline* sentinels use `# >>> … >>>`,
  which render as spurious H1 headings. Because the `agents` file **is** the instruction
  context the model reads every turn, we use HTML comments so the markers are invisible in
  rendered markdown and ignored by agents. (Switching guidelines to the same is a possible
  later polish; out of scope here.)
- **Type-scoped marker** (`agents:<name>`) so an `agents` block and a same-named *guideline*
  block can coexist in one file (e.g. both target `AGENTS.md`) without either clobbering the
  other on install/uninstall.

The sentinel placement helper is a generalization of the existing
`planners._replace_sentinel_block` to take a `position` (`"top"` | `"bottom"`); the existing
guideline path keeps its current behaviour.

### 3.4 Mode resolution (precedence)

The effective mode for an artifact×install is resolved, highest wins:

1. **CLI flag** `--agents-mode {replace,prepend,append,skip}` (applies to the whole invocation).
2. **Artifact frontmatter** `mode:` (per-artifact preference).
3. **Built-in default** `prepend`.

(A per-bundle mode override is **deliberately excluded** — decided in review (2026-06-22): a
bundle selects *which* agents docs to ship, never *how* they merge. Mode comes only from the
flag → frontmatter → default. See §9.)

### 3.5 How this differs from `guideline`

They share the sentinel mechanism but model different intents, and stay **separate types**
(the request was explicit: its own type, own directory, own bundle section):

| | `guideline` | `agents` |
| --- | --- | --- |
| Unit | one of many topical rule docs | *the* house instruction document |
| Scope of edit | a **named block** inside a shared file (co-exists with other guidelines) | the **whole file** (replace) or a single canonical block at top/bottom |
| Modes | `copy` \| `append-sentinel` | `replace` \| `prepend` \| `append` \| `skip` |
| Destination filename | per-profile rules location | per-profile **instruction file** (`CLAUDE.md`/`AGENTS.md`) |

## 4. Profile mapping (the new `agents` target)

A profile gains an optional `agents` target describing **where** the instruction file lives
for that harness and **what kind** of destination it is:

```python
AgentsMode = Literal["replace", "prepend", "append", "skip"]

@dataclass(frozen=True, slots=True)
class AgentsTarget:
    kind: Literal["file", "dir"]   # "file": single shared instruction file (modes apply)
    dest: str                       # the file (kind="file") OR a directory (kind="dir", copy)
```

- **`kind="file"`** — a single shared instruction file; all four modes apply.
- **`kind="dir"`** — the harness has **no** single instruction file (Tabnine), so the artifact
  is **copied** into the directory as `<name>.md`. The content-merge modes don't apply;
  `skip` still means "don't overwrite an existing same-named file."

Per built-in profile (verified paths cited in §6):

| Profile | `agents` → | kind |
| --- | --- | --- |
| `claude` | `CLAUDE.md` | file |
| `opencode` | `AGENTS.md` | file |
| `vibe` | `AGENTS.md` | file |
| `tabnine` | `.tabnine/guidelines/` (as `<name>.md`) | dir |

## 5. `Profile` becomes type-optional (model change)

Today `Profile` requires a target for **every** type. Two forces make that wrong now: Mistral
Vibe can't express JSON MCP/hooks (§7.2), and Tabnine's hooks/MCP were already "best-effort
guesses." So **every artifact-type target on a `Profile` becomes `Optional`, defaulting to
`None`** = "this harness does not support this type."

```python
@dataclass(frozen=True, slots=True)
class Profile:
    name: str
    skills:     Optional[CopyTarget]      = None
    guidelines: Optional[GuidelineTarget] = None
    mcp:        Optional[MergeSpec]       = None
    hooks:      Optional[HookTarget]      = None
    agents:     Optional[AgentsTarget]    = None
```

**Installer behaviour when a selected artifact's type is `None` for a target profile:**
- **Explicit by-name** request (`aa install postgres --profile vibe`) → **error** (USAGE):
  the user asked for something the harness can't do; tell them.
- **Bundle / `--all` expansion** → **skip with a warning** (`Warn`): a broad set legitimately
  contains types a given harness doesn't support; don't fail the whole install.

This also tightens parent §11: "adding a harness = one record" now honestly allows a *partial*
record.

## 6. Corrected `tabnine` profile

The current `tabnine` record carries best-effort guesses (parent §19). Verified against the
official Tabnine docs, corrected as follows. **Already-correct cells are kept**; only the
wrong ones change.

| Type | Target (corrected) | Status vs. current code |
| --- | --- | --- |
| skills | `.tabnine/agent/skills/<name>/` | ✅ already correct — keep |
| guidelines | `.tabnine/guidelines/<name>.md` (copy) | ✅ already correct — keep |
| agents | `.tabnine/guidelines/` (dir copy, `<name>.md`) | ➕ new |
| **mcp** | **`.tabnine/agent/settings.json` · `mcpServers` · key** | ⚠️ changed (was `.tabnine/config.json`) — see §6.1 |
| **hooks** | scripts `.tabnine/agent/hooks/<name>/`; merge **`.tabnine/agent/settings.json` · `hooks.<event>` · list**; events **`BeforeTool`/`AfterTool`/`SessionEnd`** | 🔧 changed (was `.tabnine/hooks/` + `.tabnine/config.json` + Claude event names) |

Sources: [Agent Skills](https://docs.tabnine.com/main/getting-started/tabnine-cli/features/agent-skills),
[Agent Guidelines](https://docs.tabnine.com/main/getting-started/tabnine-agent/guidelines),
[CLI Settings Reference](https://docs.tabnine.com/main/getting-started/tabnine-cli/features/settings/settings-reference)
(settings.json has top-level `hooks` + `hooksConfig`; hook events include `BeforeTool`,
`AfterTool`, `BeforeAgent`, `AfterAgent`, `Notification`, `SessionStart`, `SessionEnd`,
`PreCompress`, `BeforeModel`, `AfterModel`, `BeforeToolSelection`).

### 6.1 Note on the MCP target (doc caveat)

The MCP target is set to **`.tabnine/agent/settings.json` · `mcpServers`** per direction. The
**published docs differ** and this should be verified in-environment (parent §19 style):
- The documented home for MCP server *definitions* is the standalone **`.tabnine/mcp_servers.json`**
  (key `mcpServers`) — [MCP intro/setup](https://docs.tabnine.com/main/getting-started/tabnine-agent/mcp-intro-and-setup),
  [MCP config examples](https://docs.tabnine.com/main/getting-started/tabnine-agent/mcp-examples-and-advanced-usage).
- The CLI's `settings.json` documents an MCP key named **`mcp`** (governance only:
  `serverCommand`/`allowed`/`excluded`), **not** `mcpServers`.

Because this is one `MergeSpec` (data, parent §11), switching the file later is a one-line
record change with no engine impact. The hooks target genuinely *does* live in
`settings.json`, so co-locating MCP there keeps everything Tabnine under `.tabnine/agent/` —
internally consistent, just flagged against the docs.

### 6.2 Hook event vocabulary

The abstract event names map per-harness (the `events` map already in `HookTarget`):

| abstract (ours) | claude | tabnine | opencode |
| --- | --- | --- | --- |
| `PreToolUse` | `PreToolUse` | `BeforeTool` | *(unverified)* |
| `PostToolUse` | `PostToolUse` | `AfterTool` | *(unverified)* |
| `Stop` | `Stop` | `SessionEnd` | *(unverified)* |

## 7. New `vibe` profile (Mistral Vibe)

Named **`vibe`** (the CLI is `vibe`; config lives under `.vibe/`). Verified layout
([repo](https://github.com/mistralai/mistral-vibe), [docs: agents](https://docs.mistral.ai/vibe/code/cli/agents),
[docs: config](https://docs.mistral.ai/mistral-vibe/terminal/configuration)):

### 7.1 Supported now

| Type | Target |
| --- | --- |
| agents | `AGENTS.md` (file) |
| skills | `.vibe/skills/<name>/` (copy; SKILL.md format) |
| guidelines | `AGENTS.md` (append-sentinel) |

(`agents` and `guideline` both touch `AGENTS.md` but use distinct sentinel markers — §3.3 —
so they coexist cleanly.)

### 7.2 Deferred: MCP and hooks (TOML)

Mistral Vibe stores MCP under `[[mcp_servers]]` in **`config.toml`** and hooks in
**`.vibe/hooks.toml`** — both **TOML**. The merge engine (parent §10) emits **JSON**, and the
Python **stdlib has no TOML writer** (`tomllib` is read-only, 3.11+). Honoring the zero-dep
rule (parent §3), `vibe.mcp` and `vibe.hooks` are **`None`** in MVP (§5 makes that legal).

Forward path (not MVP): a `format: "json" | "toml"` field on `MergeSpec` plus a tiny TOML
emitter, slotted in behind the existing **renderer registry** escape hatch (parent §10/§14) —
no change to the merge planner's logic, only its serializer. Recorded in §9.

## 8. Mechanics: model, plan, manifest, commands

### 8.1 No new `Action` is needed

Every mode reduces to actions that already exist (parent §14) — this is why the change is
small and the executor is untouched:

| Mode | Emitted actions |
| --- | --- |
| `prepend`/`append` | one `WriteFile(dest, merged-with-sentinel-block)` |
| `replace` | optional `WriteFile(<dest>.agent-artifacts-bak, prior)` + `WriteFile(dest, ours)` (or `Err` code 4 without `--force`) |
| `skip` | `WriteFile(dest, ours)` if absent, else `Warn` (no-op) |
| dir copy (tabnine) | `WriteFile(<dir>/<name>.md, ours)` (or no-op on `skip`+exists) |

`plan_agents(artifact, target, text, existing_text, exists, *, mode, force) -> Result[Plan]`
is a new pure planner, added to the `PLANNERS` dispatch dict and a new branch in
`planners._plan_one`. It is the agents analogue of `plan_guideline`.

### 8.2 Catalog / source / bundles

- `catalog.parse_agents(text, name)` → `Artifact(type="agents", name, root="agents/<name>.md")`;
  frontmatter optional (a declared `name`/`mode` is validated).
- `_INCLUDE_TYPES` gains `"agents"`; `_section_to_type` maps `agents`/`agent` → `agents`.
- `source.Source` scans `agents/*.md` (a new `_scan_agents`, mirroring `_scan_guidelines`).
- `validate_catalog` covers `agents` automatically (it resolves every bundle).

### 8.3 Manifest & uninstall

`ManifestEntry.type` now includes `"agents"`; **no new field** is required. Proof of install
is the `files` map (parent §12). Uninstall reuses the existing inverse machinery:
- `prepend`/`append` → the destination carries our HTML-comment markers → **strip our block**
  (the agents analogue of the guideline sentinel strip), preserving foreign content; delete
  the file only if stripping empties a file we created.
- `replace` / dir-copy → our file → **remove** it; if a sibling `<dest>.agent-artifacts-bak`
  exists (replace over foreign content), **restore** it.

`update` re-pulls the artifact and re-applies the resolved mode (idempotent for sentinel
modes); `status` reports `agents` entries and on-disk drift via the same `classify` path;
`list` includes `agents` and honors `--type agents`.

### 8.4 CLI surface (delta to parent §13)

```
aa install … [--agents-mode replace|prepend|append|skip]   # default: prepend
aa list      [--type agents]                                # agents included in views
```

`Request` gains `agents_mode: Optional[str] = None`. Agent mode (`--yes/--json`) and exit
codes are unchanged; a `replace` needing `--force` returns the existing CONFLICT code (4).

## 9. Open questions / verify items (parent §19 style)

1. **Tabnine MCP location** (§6.1) — directive says `.tabnine/agent/settings.json · mcpServers`;
   docs say `.tabnine/mcp_servers.json`. Verify against the installed CLI; it's a one-line
   record fix either way.
2. **OpenCode hook events / `AGENTS.md` vs `opencode.json`** — still unverified (parent §19.1/3).
3. **Vibe MCP/hooks via TOML** (§7.2) — promote from "deferred" once a stdlib TOML emitter +
   `MergeSpec.format` land; until then `vibe` is a legitimate partial profile.
4. **Replace-mode recovery** — `<dest>.agent-artifacts-bak` is the MVP safety net; revisit if a
   richer undo/history is wanted.

**Decided non-goal (2026-06-22):** a *per-bundle* `agents` mode override is **not** added — the
install mode comes only from `--agents-mode` → artifact frontmatter `mode:` → default `prepend`.
A bundle selects *which* agents docs to ship, never *how* they merge.
