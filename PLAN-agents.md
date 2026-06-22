# agent-artifacts — Implementation Plan: the `agents` artifact type (parallel, multi-agent)

Companion to [DESIGN-agents.md](DESIGN-agents.md) and continuation of [PLAN.md](PLAN.md). The
base system (WP-0…WP-24) is built; this plan adds the `agents` type, corrects the `tabnine`
profile, and adds the `vibe` profile as **work packages WP-25…WP-32**. It keeps PLAN.md's
ground rules verbatim (§1 there): functional core / imperative shell, frozen data, stdlib
only, `unittest`, disjoint file ownership, per-WP DoD.

Read order: §1 contract delta → §2 ownership map → §3 waves → §4 dependency graph → §5 work
packages → §6 critical path → §7 test strategy.

---

## 1. Contract delta (what WP-25 freezes)

One small gate, then fan out — same shape as WP-0. WP-25 lands the model additions every other
WP codes against:

```python
ArtifactType = Literal["skill","guideline","mcp","hook","agents"]   # + "agents"
AgentsMode   = Literal["replace","prepend","append","skip"]

@dataclass(frozen=True, slots=True)
class AgentsTarget:
    kind: Literal["file","dir"]      # "file": shared instruction file; "dir": copy <name>.md
    dest: str

@dataclass(frozen=True, slots=True)
class Profile:                       # every type-target now Optional (DESIGN-agents §5)
    name: str
    skills:     Optional[CopyTarget]      = None
    guidelines: Optional[GuidelineTarget] = None
    mcp:        Optional[MergeSpec]       = None
    hooks:      Optional[HookTarget]      = None
    agents:     Optional[AgentsTarget]    = None

# Request gains one field:
agents_mode: Optional[str] = None
```

**No new `Action`** (DESIGN-agents §8.1): all modes reuse `WriteFile`/`Warn`/`RemovePath`, so
`executor.py` is untouched. `ManifestEntry.type` widens automatically via `ArtifactType`.

---

## 2. Target file map (ownership — disjoint per WP)

```
agent-artifacts/
├── agent_artifacts/
│   ├── model.py                     # WP-25  (ArtifactType, AgentsTarget, Profile→Optional, Request)
│   ├── catalog.py                   # WP-26  (parse_agents, _INCLUDE_TYPES, _section_to_type)
│   ├── source.py                    # WP-26  (_scan_agents)
│   ├── planners.py                  # WP-27  (plan_agents, sentinel position, PLANNERS, _plan_one)
│   ├── profiles/builtin.py          # WP-28  (agents targets; tabnine fix; vibe; optional Nones)
│   ├── profiles/loader.py           # WP-28  (parse agents target; tolerate missing sections)
│   ├── commands/install.py          # WP-29  (gather agents text/existing/mode; None-guards)
│   ├── commands/uninstall.py        # WP-29  (agents block-strip; replace/dir remove; .bak restore)
│   ├── commands/update.py           # WP-29  (re-pull agents + apply mode)
│   ├── commands/status.py           # WP-29  (agents drift)
│   ├── commands/list.py             # WP-29  (agents in views + --type agents)
│   ├── cli.py                       # WP-30  (--agents-mode, --type agents, help)
│   └── tui.py                       # WP-30  (agents in type selector)
├── agents/                          # WP-31  (seed: agents/house.md)
├── bundles/base.json                # WP-31  (add includes.agents)
├── tests/fixtures/agents/…          # WP-31  (--source mirror)
├── tests/agents_test.py             # WP-27 (planner) + WP-26 (catalog) split by area
├── tests/{profiles,install,uninstall,update,status,list,cli,tui}_test.py  # extend in-place per WP
├── tests/e2e_test.py                # WP-32  (final gate)
└── README.md  DESIGN-agents.md PLAN-agents.md   # WP-32 docs / (these)
```

> **Shared-file note.** WP-29 and WP-30 extend several existing command/CLI test files. To keep
> ownership disjoint, each WP appends a **new test module** (`tests/agents_install_test.py`,
> etc.) rather than editing a sibling WP's tests; in-place edits to a *source* file are owned by
> exactly one WP as listed.

---

## 3. Wave schedule

| Wave | WPs | Parallel | Gate to exit |
| --- | --- | --- | --- |
| **A — contract** | WP-25 | 1 (blocking) | model imports; full existing suite still green |
| **B — core** | WP-26, WP-27, WP-28 | 3 | each module's unit tests green against WP-25 |
| **C — commands+surface** | WP-29, WP-30, WP-31 | 3 | command round-trips on a fixture `--source` |
| **D — gate** | WP-32 | 1 (final) | e2e green; docs install-tested |

---

## 4. Dependency graph

```
                         WP-25  contract (model)   [GATE]
              ┌───────────────┼───────────────┐
            WP-26           WP-27            WP-28
          catalog+source   planner+sentinel  profiles (tabnine fix + vibe)
              └───────────────┼───────────────┘
                            WP-29  commands  ── co-lands with ── WP-28 (None-guards ↔ vibe None targets)
                              │
                            WP-30  cli+tui          WP-31  seed content + fixtures
                              └───────────┬───────────┘
                                        WP-32  docs + e2e  [FINAL GATE]
```

**Co-landing constraint:** WP-28 introduces the first profile with `None` targets (`vibe`
mcp/hooks). The command-side `None`-guards that make that safe live in WP-29. Merge them
together (or WP-28 before WP-29) so the suite never sees a `None` target without its guard.

---

## 5. Work packages

Format mirrors PLAN.md §5 — **WP-N · Title** *(wave · parallel-safe · size)* — Owns / Depends /
Build / Done when.

### WP-25 · Contract extension *(A · blocking · S)*
- **Owns:** `model.py`.
- **Depends:** none (base system).
- **Build:** add `"agents"` to `ArtifactType`; add `AgentsMode`, `AgentsTarget`; make all five
  `Profile` type-targets `Optional[...] = None` and add `agents`; add `Request.agents_mode`.
  Confirm **no new `Action`** is needed.
- **Done when:** `import agent_artifacts.model` works; **the entire existing WP-0…24 suite is
  still green** (built-ins still construct because new fields default to `None`).

### WP-26 · Catalog & source scan *(B · yes · S)*
- **Owns:** `catalog.py`, `source.py`, `tests/agents_catalog_test.py`.
- **Depends:** WP-25.
- **Build:** `parse_agents(text, name) -> Result[Artifact]` (`root="agents/<name>.md"`, optional
  frontmatter; validate a declared `name`/`mode`); add `"agents"` to `_INCLUDE_TYPES`; map
  `agents`/`agent` in `_section_to_type`. In `source.py`: `_AGENTS_DIR="agents"`,
  `_scan_agents()` (mirror `_scan_guidelines`), wire into `catalog()` + docstring.
- **Done when:** an `agents/*.md` source parses; a bundle referencing `includes.agents`
  resolves; `validate_catalog` flags a dangling `agents` ref.

### WP-27 · Agents planner & sentinel *(B · yes · M)*
- **Owns:** `planners.py`, `tests/agents_planner_test.py`.
- **Depends:** WP-25 (integrates with WP-26's `Artifact`).
- **Build:** generalize `_replace_sentinel_block` to accept `position ∈ {"top","bottom"}`
  (guideline behaviour unchanged); add `agents_sentinel_markers(name)` (HTML-comment, type-
  scoped — DESIGN-agents §3.3). Implement `plan_agents(artifact, target, text, existing_text,
  exists, *, mode, force) -> Result[Plan]` for all four modes + `kind="dir"` copy (DESIGN-agents
  §3.2/§8.1), including the `replace` `.bak` + `--force` (CONFLICT code 4) path. Register in
  `PLANNERS`; add the `agents` branch to `_plan_one` (gather `agents:{name}`,
  `existing-agents:{profile}:{name}`, `exists`, resolved `mode`); manifest proof via `files`.
- **Done when:** golden `Plan` per mode (prepend/append idempotent re-install; replace with &
  without `--force`; skip present/absent; dir-copy) asserted.

### WP-28 · Profiles: tabnine fix + vibe + optional targets *(B · yes · M)*
- **Owns:** `profiles/builtin.py`, `profiles/loader.py`, `tests/agents_profiles_test.py`.
- **Depends:** WP-25.
- **Build:**
  - Add `agents` targets: `claude`→`CLAUDE.md` (file), `opencode`→`AGENTS.md` (file),
    `tabnine`→`.tabnine/guidelines/` (dir).
  - **Fix tabnine** (DESIGN-agents §6): mcp → `.tabnine/agent/settings.json` · `mcpServers`;
    hooks → scripts `.tabnine/agent/hooks/<name>/`, merge `.tabnine/agent/settings.json` ·
    `hooks.<event>`, events `PreToolUse→BeforeTool`, `PostToolUse→AfterTool`, `Stop→SessionEnd`.
  - **Add `vibe`** (DESIGN-agents §7): agents `AGENTS.md` (file), skills `.vibe/skills/<name>/`,
    guidelines `AGENTS.md` (append-sentinel), **mcp `None`, hooks `None`**.
  - `loader.py`: parse an `agents` target from the override dict; treat any **missing** type
    section as `None` (not a KeyError) so partial profiles load.
- **Done when:** `vibe` loads as a partial profile; corrected tabnine paths asserted; an
  override file adding an `agents` target merges; a partial override (omitting `mcp`) loads.

### WP-29 · Commands wiring *(C · yes · M)*
- **Owns:** `commands/{install,uninstall,update,status,list}.py`, `tests/agents_commands_test.py`.
- **Depends:** WP-26, WP-27, WP-28 (co-land — see §4).
- **Build:**
  - `install.py`: for each `agents` artifact gather body (`agents:{name}`), per-file-profile
    existing dest text (`existing-agents:{profile}:{name}`) + `exists`; **resolve mode**
    (`request.agents_mode` → frontmatter `mode:` → `prepend`). **`None`-guard** every
    `prof.<type>.…` access (today `prof.mcp.file` / `prof.guidelines.mode` are unconditional —
    must skip when `None`). Implement the **unsupported-type policy** (DESIGN-agents §5):
    by-name request for a `None` type → USAGE `Err`; bundle/`--all` expansion → `Warn`+skip.
  - `uninstall.py`: `agents` reversal — HTML-comment block-strip for prepend/append (mirror the
    guideline `_apply_sentinel`), else remove the file; restore `<dest>.agent-artifacts-bak`
    when present.
  - `update.py`/`status.py`/`list.py`: re-pull+re-apply mode; drift via `classify`; include
    `agents` + honor `--type agents`.
- **Done when:** install→status→uninstall round-trips an `agents` artifact in each mode on a
  fixture source; replace leaves a `.bak`; uninstall restores it; installing an unsupported
  type by-name errors, via bundle warns+skips.

### WP-30 · CLI & TUI *(C · yes · S)*
- **Owns:** `cli.py`, `tui.py`, `tests/agents_cli_test.py`.
- **Depends:** WP-25 (integrates with WP-29).
- **Build:** `cli.py` — `--agents-mode {replace,prepend,append,skip}` (default unset → planner
  applies `prepend`), accept `--type agents`, route into `Request.agents_mode`, help text. `tui.py`
  — include `agents` in the type selector; no logic duplicated from the command core.
- **Done when:** `aa install --agents-mode replace …` parses & dispatches; `aa list --type
  agents` filters; `--help` documents the flag; headless TUI fallback lists `agents`.

### WP-31 · Seed content & fixtures *(C · yes · S)*
- **Owns:** `agents/house.md`, `bundles/base.json` (add `includes.agents`), `tests/fixtures/agents/…`
  (+ fixture bundle mirror).
- **Depends:** WP-26 (parser).
- **Build:** one real `agents/house.md` (frontmatter `description` + `mode: prepend`); add
  `"agents": ["house"]` to the `base` bundle; mirror into `tests/fixtures/` for `--source`.
- **Done when:** content validates under `validate_catalog`; usable as a `--source` for WP-29/32.

### WP-32 · Docs & end-to-end gate *(D · final · M)*
- **Owns:** `README.md`, `tests/e2e_test.py` (extend), DESIGN-agents/PLAN-agents open-q updates.
- **Depends:** WP-29, WP-30, WP-31.
- **Build:** README — "author an `agents` artifact," the four modes + precedence, the `vibe`
  profile, the corrected tabnine paths (+ the §6.1 MCP caveat). e2e — temp project + local
  `--source`: install→status→update→uninstall for `agents` across **{claude (file), vibe (file),
  tabnine (dir)}** and **all four modes**; golden Plan snapshots; `--dry-run`/`--json`/`--force`;
  the unsupported-type skip/err paths; `.bak` create+restore on replace.
- **Done when:** `python -m unittest discover` green; **no non-stdlib imports**; offline wheel
  still installs; copy-paste README install works. **Final green-light.**

---

## 6. Critical path

`WP-25 → WP-27 → WP-29 → WP-30 → WP-32.`

Everything else (catalog/source WP-26, profiles WP-28, seed WP-31) hangs off the gate and runs
in parallel. Shorten by staffing WP-25, then WP-27+WP-28 together (so WP-29 unblocks with both
the planner and the new profiles), then WP-29.

Solo/sequential fallback: follow the path and pull WP-26/28/31 in opportunistically — the split
collapses onto one worker, same order.

---

## 7. Test strategy & Definition of Done (delta to PLAN.md §8)

- **Unit (per WP):** stdlib `unittest`; pure modules (catalog/planner/profiles) tested with
  plain data + **golden `Plan`** assertions for all four modes; IO/command modules with tmp dirs.
- **Regression gate (WP-25):** the **whole existing suite stays green** after the model change —
  the proof that making `Profile` targets optional + adding `agents` is backward-compatible.
- **Integration (WP-32):** real-fs temp project, local `--source`, full round-trips for `agents`
  × 3 profile kinds × 4 modes; unsupported-type skip/err; replace `.bak` restore.
- **Global DoD (unchanged):** `unittest discover` green; **zero non-stdlib imports** (CI grep
  gate); offline wheel installs; `--dry-run` mutates nothing; idempotent re-install yields a
  byte-identical sentinel block.
