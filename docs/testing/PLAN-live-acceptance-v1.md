# Live acceptance v1 — execution plan

Design: [DESIGN-live-acceptance-v1.md](DESIGN-live-acceptance-v1.md).
Scenario detail: [live-acceptance-scenarios.md](live-acceptance-scenarios.md).
Running record: [PROGRESS-live-acceptance.md](PROGRESS-live-acceptance.md).

Status: **not started.** No work package below has been executed.

---

## Conventions

- Work packages are `LA-<phase><n>`; scenarios are `LA-<phase>-<nn>` and are defined in the scenario
  map, not here.
- Every WP states **preconditions**, **steps**, **assertions**, and **evidence**. A WP whose
  preconditions fail is `blocked`, never `failed` (design §4).
- `D` = driven by agent, `H` = driven by human (Michal).
- Findings are recorded, not fixed (design §8).

Environment, fixed for the whole run:

```sh
export LA_ROOT="$HOME/.aart-live-acceptance"     # sandbox root, outside the repos under test
export LA_HOME="$LA_ROOT/home"                   # sandbox HOME for user-scope scenarios
export LA_WORK="$LA_ROOT/work"                   # checkouts of the three fixture repos
```

User-scope scenarios run as `HOME="$LA_HOME" aart …`. This is load-bearing beyond the destination
paths: [io/cache.py](../../agent_artifacts/io/cache.py) puts the object cache under
`~/.cache/agent-artifacts`, so overriding `HOME` isolates the cache too, and the offline scenarios
would otherwise silently read a warm real cache.

---

## Phase 0 — harness preparation

### LA-0.1 · Pin the executable · `D`

**Steps.** Record `git rev-parse HEAD` of this checkout; `make wheel`; install into a dedicated
venv; record `aart --version`.
**Assertions.** The version reported matches the wheel; no non-stdlib import is pulled in.
**Evidence.** Commit SHA + wheel filename + version, written to PROGRESS as the run header.

> Everything after this point is executed against **this** build. If it changes, the run restarts.

### LA-0.2 · Build the coverage ledger · `D`

**Steps.** Derive the leaf-subcommand inventory from `build_parser()` and diff it against the ledger
in this document.
**Assertions.** The two agree. A mismatch means this plan is stale and is fixed before anything runs.

### LA-0.3 · Establish the sandbox · `D`

**Steps.** Create `$LA_ROOT`; verify `HOME="$LA_HOME" aart status --scope user` resolves under the
sandbox and not under the real `~`.
**Assertions.** No path under the real `~` is touched. This is asserted, not assumed — the whole
isolation strategy rests on `expanduser` honouring `HOME`.
**Evidence.** The resolved user-scope root.

### LA-0.4 · Resolve the two maintainer surfaces · `D`

**Steps.** Establish what makes the TUI offer `MAINTAINER_ACTIONS` (7) versus
`CANONICAL_MAINTAINER_ACTIONS` (11).
**Assertions.** The condition can be stated in one sentence. If it cannot, file a `question` finding
— an operator cannot predict which menu they will get either.
**Evidence.** The condition, and which fixture reaches which menu.

### LA-0.5 · `upgrade` · `D`

**Steps.** `aart upgrade --dry-run --wheel <wheel>`, then `--source-checkout`.
**Assertions.** Dry run mutates nothing.
**Note.** Only the dry-run path is exercised: a real `upgrade` would break the LA-0.1 pin.

---

## Phase R — seed the registries (maintainer role)

Both registries are authored from empty. `aart registry` never commits or pushes, so every WP ends
with an explicit human-visible `git push` (design §10).

### LA-R1 · Registry A from empty · `D` — canonical CLI path

**Preconditions.** LA-0 complete.
**Steps.** Clone Registry A; empty the worktree; `registry init` → `scaffold` → `format` →
`validate --strict --frozen` → `lock` → `build` → `audit` → `test --compatibility all` → `diff`.
**Assertions.** Each command's stated effect from
[maintainer-commands-v1.md](../registry/maintainer-commands-v1.md) matches observed behaviour;
`--check` variants return `0` when current and `1` on drift; `--json` renders the documented
envelope where present.
**Covers.** `registry init|scaffold|format|validate|lock|build|audit|test|diff`.

### LA-R2 · Populate Registry A with real content · `D`

**Steps.** Bring in *superpowers* skills plus GitHub and Context7 MCP entries via
`upstream add` / `scan` / `import` (exercise `--mode auto|heuristic|manifest`), then re-run the
`format` → `lock` → `build` → `audit` chain.
**Assertions.** All five artifact types (`skill`, `guideline`, `mcp`, `hook`, `memory`) are present
and appear in `list --type <t>`; `upstream import --dry-run` predicts what the real run does.
**Covers.** `upstream add|scan|import|validate|health|check|update`.

### LA-R3 · Registry B, with a deliberate collision · `D`

**Steps.** Same chain against Registry B, seeded with *Matt Pocock* skills, the Atlassian MCP entry,
and the `residuality` bundle from `M1F1/residues-architecture-framework` (10 skills + 1 guideline,
declared in that repo's own `agent-artifacts.import.json`). Include **at least one artifact name that
collides with Registry A**.
**Assertions.** The collision is representable at authoring time — a registry that cannot express it
is itself a finding. `upstream import --mode manifest` consumes the declared manifest; `--mode auto`
selects manifest here and heuristic for the manifest-less collections in LA-R2, and the choice is
explainable.
**Legacy check (`LA-R-29`, `LA-R-30`).** The residuality repository may predate the current AART
protocol floor. If it does, the assertion is the project's own stated principle: **a below-floor
source is rejected with a typed migration error naming what to change, never silently absorbed.**

Read the outcome in the right direction (design §8, one-way adaptation):

| Observed | Verdict |
|---|---|
| rejected with a typed, actionable error | **pass** — this is the designed behaviour, file nothing |
| rejected with an unclear or untyped error | `minor` — the rejection is right, the message is not |
| silently absorbed and imported | `major` — the floor is advisory rather than enforced |

If the source is rejected, **the remedy is to re-author the residuality artifacts against the current
protocol, never to loosen AART.** Doing that re-authoring is a separate piece of work and is not part
of this run; Registry B proceeds with whatever content is admissible, and the excluded artifacts are
recorded.
**Setup effects.** Some residuality skills may declare a setup installer. Any artifact with setup
effects is reviewed in LA-M1 (no effects) and executed only in LA-M2, regardless of whether it needs
credentials. Discovering an installer here does not license running it here.
**Covers.** Repeats LA-R1/R2 commands against a second remote, plus the manifest-mode import path.

### LA-R4 · Maintainer TUI, text front-end · `D`

**Steps.** Walk the maintainer role through the text front-end with piped choices, covering both
action menus discovered in LA-0.4.
**Assertions.** The TUI reaches the same outcome as the equivalent flag-mode command; the stepper
shows a coherent path; a mid-flow quit mutates nothing.
**Findings note.** Whether piped stdin traverses consent gates unattended is recorded here
regardless of outcome (design §2).

### LA-R5 · Maintainer TUI, curses · `H`

**Steps.** Michal walks the scripted curses walkthrough for the maintainer role.
**Assertions.** Screens render legibly at a normal terminal size; the review screen states the
effect before it happens; quit is always available.

### LA-R6 · Publish · `D` prepares, `H` confirms

**Steps.** Review the diff, then force-push both registries.
**Assertions.** Post-push, a clean clone of each passes `registry validate --strict --frozen`.
**Note.** First outward-facing effect of the run.

### LA-R7 · Security evidence · `D`

**Steps.** `security scan` over the authored registries; `show`, `analyzers`, `suites`, `verify`.
**Assertions.** `verify` is reproducible across two invocations on unchanged inputs.
**Covers.** `security scan|show|verify|analyzers|suites`.

---

## Phase S — wire the sources

### LA-S1 · Add both registries · `D`

**Steps.** `source add --kind registry-git` for A and B, one as `--default`; then `source list`,
`sync`, `health`, `doctor`.
**Assertions.** `--json` on each is well-formed; `doctor` without `--apply` mutates nothing;
re-adding the same alias fails cleanly rather than duplicating.
**Covers.** `source add|list|sync|health|doctor`.

### LA-S2 · Federation and collision · `D`

**Steps.** `marketplace list`, `marketplace health`; resolve the colliding name unqualified, then
qualified.
**Assertions.** **Unqualified fails, qualified resolves.** This is the live counterpart of the
hermetic `collision` scenario and the single most valuable assertion in phase S.
**Covers.** `marketplace list|health`.

---

## Phase U — user lifecycle (consumer repo)

Consumer repo: `M1F1/agent-artifacts-live-acceptance-project`, created fresh and private.
Matrix: **`claude` in full; `opencode`, `tabnine`, `vibe` smoke-only** (design §11).

### LA-U1 · Browse before install · `D`

`list` with `--type`, `--bundle`, `--source`, `--version`, prose and `--json`.
**Assertions.** `list` mutates nothing; every artifact seeded in phase R is visible.

### LA-U2 · Install, project scope, copy mode · `D`

**Steps.** `install --dry-run` first, then the real run; `--profile claude`, `--scope project`.
**Assertions.** Dry run's predicted paths equal the real run's written paths — *the* assertion of
this WP. Without `--yes` the command only reviews. `status` then reports what was installed.

### LA-U3 · The `--json` invariance check · `D`

**Steps.** Re-run representative commands from LA-U2 with `--json`.
**Assertions.** Identical effects and exit codes; only the encoding differs (design §2, rule 1).
Any divergence is filed as `major`.

### LA-U4 · Install variants · `D`

`--link` (symlink), `--scope user` under `$LA_HOME`, `--memory-mode` across
`replace|prepend|append|skip`, `--all`, `--bundle`, `--force`.
**Assertions.** Symlinked entries report as live in `status` / `check`; the memory sentinel block is
written per mode; guidelines never share a destination file with memory.

### LA-U5 · Drift, check, update · `D`

**Steps.** Hand-edit an installed artifact; `status`; `check`; `update --dry-run`; `update`;
`update --prune`.
**Assertions.** Drift is reported rather than silently overwritten; `check` distinguishes drift from
an upstream change; linked entries stay live across `update`.

### LA-U6 · Uninstall and teardown assertion · `D`

**Steps.** `uninstall --dry-run`, `uninstall`, then `uninstall --all`.
**Assertions.** `git status --porcelain` in the consumer repo is **empty**; the memory sentinel block
is stripped; guideline copies are removed; no orphaned symlink remains. Residue is a finding
(design §9).

### LA-U7 · Marketplace-driven lifecycle · `D`

`marketplace install|update|uninstall|status`, including `--mode copy|symlink` and `--offline`.
**Assertions.** The `--offline` path succeeds from a warm cache and returns a typed failure without
touching Git when the cache is cold.

### LA-U8 · Three-profile smoke · `D`

`install` → `status` → `uninstall` for `opencode`, `tabnine`, `vibe`.
**Note.** The open tabnine MCP-location caveat is expected to surface here; if it does, it is filed,
not fixed.

### LA-U9 · User TUI, text front-end · `D`
### LA-U10 · User TUI, curses · `H`

As LA-R4 / LA-R5, for the user role: source selection, profile selection, install review, uninstall
confirmation.

### LA-U11 · Real-`~` pass · `D` prepares, `H` watches

**Steps.** Inventory `~/.claude/`; one `install --scope user` + `status` + `uninstall` cycle against
the **real** home; re-inventory.
**Assertions.** The inventory is identical before and after. Runs once, last in phase U, and is the
only scenario permitted to touch the working configuration.

---

## Phase M — setup and MCP installers · `H` drives

Last by design: everything credential-free is green before any secret is in play.

### LA-M1 · Setup review without effects · `D`

**Steps.** `marketplace setup` **without** approval flags; `setup status`.
**Assertions.** Nothing is executed; the review states each effect, its entrypoint, and its trust
status before requesting approval.

### LA-M2 · Approved setup run · `H`

**Steps.** Michal supplies credentials for the GitHub, Context7, and Atlassian MCP entries and runs
`setup run` with the explicit approval flags (`--approve-setup-effects`,
`--authorize-custom-entrypoint`, `--authorize-untrusted-source` as required).
**Assertions.** Per-item terminal outcomes are retained; `setup retry` resumes only failed items;
`setup rollback` restores the prior state; no credential appears in any output captured into the
record.
**Boundary.** The agent prepares and explains the command; **it never types a credential**
(design §10).
**Covers.** `setup run|retry|status|rollback`, `marketplace setup`.

---

## Phase Z — harvest · after §12 exit criteria hold

### LA-Z1 · Holistic agent skill · `D`
### LA-Z2 · README correction · `D`

Written from the accumulated record, not from intent. Every `question` finding is a candidate
negative rule for the skill.

---

## Coverage ledger — all 49 leaf subcommands

| Subcommand | WP | Subcommand | WP |
|---|---|---|---|
| `list` | LA-U1 | `upstream validate` | LA-R2 |
| `install` | LA-U2/U4 | `upstream health` | LA-R2 |
| `status` | LA-U2/U5 | `upstream check` | LA-R2 |
| `check` | LA-U5 | `upstream update` | LA-R2 |
| `update` | LA-U5 | `upstream add` | LA-R2 |
| `uninstall` | LA-U6 | `upstream scan` | LA-R2 |
| `upgrade` | LA-0.5 (dry-run only) | `upstream import` | LA-R2 |
| `setup run` | LA-M2 | `registry init` | LA-R1 |
| `setup retry` | LA-M2 | `registry scaffold` | LA-R1 |
| `setup status` | LA-M1 | `registry format` | LA-R1 |
| `setup rollback` | LA-M2 | `registry validate` | LA-R1 |
| `migrate state` | **out of scope (v1)** | `registry lock` | LA-R1 |
| `source add` | LA-S1 | `registry build` | LA-R1 |
| `source list` | LA-S1 | `registry audit` | LA-R1 |
| `source sync` | LA-S1 | `registry test` | LA-R1 |
| `source health` | LA-S1 | `registry diff` | LA-R1 |
| `source doctor` | LA-S1 | `registry migrate` | **out of scope (v1)** |
| `marketplace list` | LA-S2 | `security scan` | LA-R7 |
| `marketplace health` | LA-S2 | `security show` | LA-R7 |
| `marketplace install` | LA-U7 | `security verify` | LA-R7 |
| `marketplace update` | LA-U7 | `security analyzers` | LA-R7 |
| `marketplace uninstall` | LA-U7 | `security suites` | LA-R7 |
| `marketplace status` | LA-U7 | `reporting validate-event` | **out of scope (v1)** |
| `marketplace setup` | LA-M1/M2 | `reporting validate-issue` | **out of scope (v1)** |
| | | `reporting aggregate` | **out of scope (v1)** |

**Covered: 44. Out of scope: 5** — the two migration commands (`migrate state`, `registry migrate`)
and the three reporting commands (`reporting validate-event|validate-issue|aggregate`).

This is a **scope decision, not a gap to close later** (design §11). The migration surface would
require synthesising a legacy 0.1.x catalog and the reporting surface would require accumulated usage
events; both are separate bodies of work whose absence does not weaken any assertion this run makes.
A future run that wants them adds them as a v2 phase with its own fixtures — it does not inherit them
as debt from v1.

### One conditional re-opening — maintainer's call

The reason the migration commands were excluded is the absence of a legacy fixture. If `LA-R-29`
shows that `M1F1/residues-architecture-framework` is a **genuine below-floor source**, that reason
disappears: the fixture exists, for free, and `registry migrate --legacy-source` becomes testable at
near-zero marginal cost.

This does not conflict with the one-way adaptation rule (design §8). `registry migrate` is a
deliberate conversion the *other party* runs to come up to the current protocol — the direction the
rule prescribes. What the rule forbids is AART bending at runtime to consume a below-floor source,
which is `LA-R-29`'s concern, not this one.

This is **not** re-included automatically. If the condition triggers, it is recorded as an open
question in PROGRESS and the maintainer decides. Scope that re-expands on its own is how a test plan
stops being finishable.

## Exit criteria

Restated from design §12 as a checklist to tick in PROGRESS: coverage table complete · both
registries consumable from a clean clone · `claude` lifecycle green · three-profile smoke green ·
both front-ends exercised · teardown assertions pass · every failure filed as `LAF-NN`.

Zero findings is **not** required. A complete coverage table plus a well-formed findings ledger is
the deliverable.
