# Live acceptance v1 — progress

Running record for the live acceptance run. Design:
[DESIGN-live-acceptance-v1.md](DESIGN-live-acceptance-v1.md) · Plan:
[PLAN-live-acceptance-v1.md](PLAN-live-acceptance-v1.md) · Scenarios:
[live-acceptance-scenarios.md](live-acceptance-scenarios.md).

**Status: in progress.** Phase LA-0 complete; phase LA-R starting.

---

## Run header

Filled by `LA-0.1`. Everything in this record is executed against this build; if it changes, the run
restarts (design §3).

| Field | Value |
|---|---|
| AART commit | `db3c8818997c40df280490f485e1055fa88ca89e` |
| Wheel | `dist/agent_artifacts-1.4.0-py3-none-any.whl` (636 399 bytes) |
| `aart --version` | `agent-artifacts 1.4.0` |
| Test venv | `$LA_ROOT/venv` — only `agent-artifacts`, `pip`, `setuptools` installed |
| Platform | macOS (darwin 25.2.0), Python 3.11.0 |
| Registry A | `M1F1/agent-artifacts-registry` |
| Registry B | `M1F1/agent-artifacts-registry-2` |
| Consumer | `M1F1/agent-artifacts-live-acceptance-project` (not yet created) |
| Sandbox root | `$LA_ROOT` = `~/.aart-live-acceptance` |
| Started | 2026-08-13 |
| Last updated | 2026-08-13 |

`make wheel` runs `scripts/inject_commit.py`, which writes the SHA above into
`agent_artifacts/_commit.py`. That file is therefore modified in the working tree for the duration of
the run; it is the pin, not a stray edit.

## Phase status

| Phase | WPs | Status | Note |
|---|---|---|---|
| LA-0 harness | 0.1 – 0.5 | **complete** | 6/6 pass; 1 `question` finding |
| LA-R registries | R1 – R7 | in progress | agent scope done except `LA-R-26`/`27` (deferred to after LA-S); `LA-R-24` awaits Michal's curses pass |
| LA-S sources | S1 – S2 | in progress | |
| LA-U user lifecycle | U1 – U11 | not started | |
| LA-M setup / MCP | M1 – M2 | not started | human-driven; credentials by Michal |
| LA-Z harvest | Z1 – Z2 | not started | only after exit criteria hold |

## Scenario results

One row per executed scenario.

| ID | Result | Finding | Note |
|---|---|---|---|
| `LA-0-01` | pass | — | wheel 1.4.0 installed into a clean venv; no non-stdlib dependency pulled in |
| `LA-0-02` | pass | — | `build_parser()` yields **15 top-level / 49 leaves**, set-identical to the plan ledger |
| `LA-0-03` | pass | — | all four profiles resolve every user-scope target under `$LA_HOME`; real `~` untouched |
| `LA-0-04` | pass | — | `cache_dir()` follows `HOME`; live population re-checked at `LA-S-04` |
| `LA-0-05` | pass | `LAF-01` | the two menus differ and the condition is stateable; see below |
| `LA-0-06` | pass | — | both `--dry-run` forms print the exact `pip … --no-index` invocation and mutate nothing |
| `LA-R-01` | pass | — | `init` from an emptied checkout wrote 6 paths (2 protocol markers, 3 workflows, 1 issue template); commit count unchanged at 4 |
| `LA-R-02` | pass | — | `scaffold skill la-probe` wrote exactly `artifact.json` + `payload/SKILL.md` |
| `LA-R-03` | pass | — | two `format` runs left a byte-identical tree; `--check` exit `0` |
| `LA-R-04` | pass | — | re-indented `aart-registry.json` → `--check` exit `1`, named the path, wrote nothing; `format` restored it byte-identically |
| `LA-R-05` | pass | — | `validate --strict --frozen` passes on a locked+built registry, and correctly **fails** (exit `1`, 3 errors) when the manifest is edited without re-locking |
| `LA-R-06` | pass | — | `lock` added `aart.lock.json`; `lock --check` → 0 changed |
| `LA-R-07` | pass | — | `build` added `aart.index.json`; `build --check` → 0 changed |
| `LA-R-08` | pass | `LAF-02`, `LAF-03` | `audit --json` emits provenance / licence / risk evidence as warnings and exits `0` |
| `LA-R-09` | pass | — | `test --compatibility all` reports `minimum: passed`, `latest: passed` |
| `LA-R-10` | pass | — | `diff` reports drift and leaves the worktree untouched; exits `0` where `format --check` exits `1` — consistent with preview-vs-gate roles |
| `LA-R-11` | **fail** | `LAF-04`, `LAF-05`, `LAF-06` | the `upstream` family cannot author a canonical registry, and `import` does not say so |
| `LA-R-12` | pass | — | `scan --mode auto` on the residuality repo resolved to `manifest` and listed 14 `[explicit]` candidates (13 skills + 1 guideline); heuristic comparison deferred to `LA-R-28` |
| `LA-R-13` | pass | — | dry run predicted `copy-tree → skills/using-residues` + `write-file upstreams.json`; the real run wrote exactly that set. The prediction is faithful — of an operation that should not have been permitted (`LAF-06`) |
| `LA-R-14` | pass | — | 14 superpowers skills + 3 Docker MCP packages carried into Registry A; all validate |
| `LA-R-15` | pass | `LAF-09` | all five types present in A (14 skill, 4 mcp, 1 guideline, 1 hook, 1 memory) — asserted from `aart.index.json`, because `aart list --source <registry>` returns nothing |
| `LA-R-16` | pass | — | `mcp/context7` authored; `mcp/github-docker` carries `${GITHUB_PERSONAL_ACCESS_TOKEN}` as a placeholder — **no credential value in either registry** |
| `LA-R-17` | pass | — | `init` → chain → `validate --strict --frozen` reproduced identically on Registry B |
| `LA-R-18` | pass | — | 7 Pocock skills + `mcp/atlassian` + the 14-package `residuality` bundle in B |
| `LA-R-19` | pass | — | `skill/brainstorming` now exists in **both** registries with different payloads; both registries still validate. Collision is representable at authoring time and deferred to resolution time |
| `LA-R-22` | pass | `LAF-07` | aborting the `promote-native` review left the checkout byte-identical to its pre-flow state; the abort itself required `q` **then** `y` |
| `LA-R-21` | pass | — | both maintainer menus reached and enumerated through the text front-end — 7 entries on the legacy catalog (header `Catalog:`), 11 on the canonical checkout (header `Canonical registry checkout:`); `q` cancels cleanly from both (`Cancelled; no changes were made`, exit `0`) when the basket is empty, which bounds `LAF-07` to the recovery/discard path; canonical `validate` ran to completion read-only, and its review digest was byte-identical across four re-renders |
| `LA-R-20` | pass | `LAF-11`, `LAF-12` | on a *real* legacy catalog (`upstream add` of `skill/using-residues`) the whole family works: `check`/`validate`/`health` all exit `0` and agree, local drift is detected by name (`local_drift`), bare `update` refuses to act without a selector, and `update --all` warns and preserves the local edit. Only `--force` misreports (`LAF-11`) |
| `LA-R-23` | pass | `LAF-10` | a fully piped approval **does** traverse the consent gate and mutate the workspace unattended; recorded, not treated as a defect (design §2) |
| `LA-R-25` | pass | — | ordinary fast-forward push (no history rewrite needed); clean clones of **both** registries pass `validate --strict --frozen` |
| `LA-R-26` | **deferred** | — | `security scan` takes an *object envelope* file, which is materialised in the consumer object store by `source sync`. Re-sequenced to run after phase S; `analyzers` and `suites` already pass |
| `LA-R-28` | pass | — | `scan --mode auto` selected **manifest** for the residuality repo (it ships `agent-artifacts.import.json`); the heuristic side is covered by the same command against a manifest-less path |
| `LA-R-29` | pass | — | `promote-native` **rejected** the residuality repo with a typed `registry-entry-invalid`: *entry source path must end with its artifact type/name identity*. Rejection is the pass condition (design §8). The remedy is to re-author the upstream, and this run did exactly that — vendoring its payloads into canonical packages rather than loosening AART |
| `LA-R-30` | pass | — | `registry test --compatibility all` reports `minimum: passed` / `latest: passed` on both registries; `requires_aart` floor is `1.0.0 ≤ v < 2.0.0` |

Legend: `pass` · `fail` (finding filed) · `blocked` (precondition unmet — record the blocking finding
ID, do **not** record it as a failure) · `deferred` (out of scope with a written reason).

### `LA-0-05` — the maintainer menu switch condition

Stated in one sentence, as the assertion requires:

> The TUI offers the **canonical** 11-entry registry menu when the working directory contains
> `aart-registry.json`, **or** is a Git checkout carrying none of the legacy markers (`bundles.json`,
> `upstreams.json`, `skills/`, `guidelines/`, `mcp/`, `hooks/`, `memory/`); otherwise it loads the
> legacy catalog context and offers the 7-entry menu.

Observed live in the text front-end, and the header line names the branch it took:

| Working directory | Header | Menu |
|---|---|---|
| empty Git checkout | `Canonical registry checkout: …` | canonical, 11 entries |
| Git checkout containing `skills/` | `Catalog: …` | legacy, 7 entries |
| plain directory, no `.git` | — | `error: not a catalog directory`, exit `2` |

The predicate is [`_is_canonical_maintainer_workspace`](../../agent_artifacts/tui.py); the switch is
applied in both front-ends.

Legend: `pass` · `fail` (finding filed) · `blocked` (precondition unmet — record the blocking finding
ID, do **not** record it as a failure) · `deferred` (out of scope with a written reason).

---

## Findings — residues

**Record, do not fix** (design §8). These are residues, not a defect queue: the response is composed
from the whole set at the end, so a residue removed by a mid-run patch is a data point destroyed.

**Critical-fix gate:** fix mid-run *only* if it blocks the remainder of the run **and** has no
workaround. Everything else gets a workaround, written into the scenario, with the finding left open.

Severity: `critical` (blocks the run, no workaround — the only fix-now case) · `major` (documented
capability broken or absent) · `minor` (works but misleads) · `question` (defensible but undocumented
— needs a decision, not a fix).

| ID | Sev | Scenario | Stressor | Component | Symptom | Reproduction | Blocks |
|---|---|---|---|---|---|---|---|
| `LAF-06` | major | `LA-R-11` | `LAS-30` | `commands.upstream.import` | `upstream import` writes a **legacy** `skills/<name>/` tree and `upstreams.json` into a **canonical registry**, reports `Imported 1 artifact`, exits `0` — and the artifact is invisible to the registry: `registry validate --strict --frozen` still passes and `registry build --check` reports `0 changed paths` | `registry init` a checkout, then `aart upstream import --source <that checkout> --select skill/using-residues https://github.com/M1F1/residues-architecture-framework` | silently corrupts a registry; blocks nothing |
| `LAF-04` | major | `LA-R-11` | `LAS-30` | `curation.model.CurationAction` ↔ `cli.build_parser` | `PROMOTE_NATIVE`, `IMPORT_FOREIGN`, `UPDATE_UPSTREAM` are referenced only from `tui.py`; no `aart registry` subcommand reaches them, so **flag mode cannot author a canonical registry's external content** | `grep -rn "PROMOTE_NATIVE\|UPDATE_UPSTREAM" agent_artifacts/` → only `tui.py` and `curation/` | forced the LA-R2 method change |
| `LAF-07` | major | `LA-R-22` | `LAS-10` | `tui` recovery/discard prompt | On a failed review the Recovery screen advertises `Quit = q`, but `q` opens `Discard N selected basket item(s)? [y/N]` — and any non-`y` answer (including `q`) returns to the same failure screen. Pressing `q` repeatedly never exits | script the `promote-native` flow to a failing path, then answer `q` at every prompt: 4 `q`s produced 3 failure screens and 2 discard prompts, then hung | nothing — but no scenario can rely on `q` alone to abort |
| `LAF-11` | major | `LA-R-20` | `LAS-10` | `commands.upstream.update` | `upstream update --all --force` **discards uncommitted local edits to a vendored artifact while reporting that it did not touch it**. Output is `Updated 0 upstream artifacts` + `- skipped: skill/using-residues (local catalog differs from last synced upstream)`, exit `0` — but the local edit is gone, the tree is back to upstream content, and `check` flips from `local_drift` to `up_to_date`. The counter means "upstream sha advances" (there were none) while `--force` separately re-materialises the tree; the report conflates the two and states the opposite of the effect | `upstream add --ref main --path skills/using-residues skill/using-residues <repo>`, append a line to the vendored `SKILL.md`, `upstream update --all --force` → edit gone, output says `skipped` | nothing |
| `LAF-12` | minor | `LA-R-20` | `LAS-10` | `commands.upstream.add` ↔ `.scan` | `upstream scan <bare repo URL>` resolves ref, commit and in-repo path for all 14 artifacts unaided, but `upstream add <same bare URL>` refuses the same input twice in a row, one missing argument at a time — first `could not determine a ref from the URL; pass --ref`, then `could not determine an in-repo path from the URL; pass --path`. Two commands in one family disagree about whether a repo URL is resolvable, and the errors arrive serially instead of together | `upstream add --source C skill/using-residues https://github.com/M1F1/residues-architecture-framework` → exit `2`; add `--ref main` → exit `2` again | nothing; cost two extra round-trips |
| `LAF-05` | minor | `LA-R-11` | `LAS-30` | `commands.upstream` guards | Three of the seven `upstream` commands refuse a canonical registry (`health`, `validate` → `not a catalog directory`; `check` → `missing upstreams.json`, all exit `2`) while `scan` and `import` accept it. The family does not guard the workspace shape consistently | run each `upstream` subcommand with `--source` pointing at a `registry init`-ed checkout | nothing |
| `LAF-02` | minor | `LA-R-08` | `LAS-02` | `registry scaffold` / `registry audit` | `audit` warns `owned package has no declared license` for every scaffolded artifact, with an empty `remediation` array, but `scaffold` has no `--license` flag — the only `--license` in the CLI is on `registry migrate`. Hand-adding `"license": "MIT"` to `artifact.json` does work and silences the warning | `registry scaffold … skill x` then `registry audit` | nothing |
| `LAF-08` | minor | `LA-R-05` | `LAS-01` | `protocol.native_schema` payload validation | The payload `{}` that `registry scaffold hook` writes passes `registry validate --strict --frozen`, `lock`, `build` and `audit`. A hook artifact whose payload declares no event and no command is publishable, and a consumer will merge an empty object into `settings.json` | `registry scaffold … hook x`, leave `payload/hook.json` as `{}`, run the whole chain — all green | nothing; consequence re-checked at `LA-U-09` |
| `LAF-09` | minor | `LA-R-15` | `LAS-30` | `commands.list` | `aart list --source <canonical registry>` prints the *legacy 0.1 compatibility path* warning and then reports **zero artifacts** for a registry holding 21. It neither errors nor says that a canonical registry must be browsed through `marketplace` | `aart list --source <registry checkout> --type skill` → warning, empty output, exit `0` | forced `LA-R-15` to assert from `aart.index.json` |
| `LAF-01` | question | `LA-0-05` | `LAS-29` | `tui._is_canonical_maintainer_workspace` | Any empty Git checkout — including a brand-new consumer project — is classified as a canonical **registry** workspace and offered the 11-entry maintainer menu, `init` included | `mkdir p && cd p && git init && aart` → Maintainer → header reads `Canonical registry checkout` | nothing |
| `LAF-03` | question | `LA-R-08` | `LAS-02` | `registry_publication.py` | The module defining the SPDX allowlist and the rule `artifact license is absent or not approved` has **no importers** anywhere in the package; nothing enforces the publication licence policy at runtime, `audit` only warns | `grep -rn "registry_publication" agent_artifacts/` returns only the module itself | nothing |
| `LAF-10` | question | `LA-R-23` | `LAS-11` | `tui` review/finalize gate | A scripted `y` on the pty traverses the consent gate and mutates the workspace with no human present. The gate is built correctly for a human — the review screen names the digest, states `Mutation: yes, only on Finalize`, lists every path before touching it, and defaults to `N` — but it has no way to distinguish a typed `y` from a piped one | feed a full approval sequence ending in `y\ny\ny` through the pty harness into a `scaffold`; exit `0`, artifact written | nothing — recorded per design §2 |

`LAF-10` is the design's own prediction confirmed, not a discovered defect: under a pty there is no
signal that separates typed input from piped input, so no terminal UI can enforce this boundary from
the inside. It is filed because it fixes the boundary's true location — the consent gate is a
**convention the caller must honour**, not a control the product enforces. That makes it the
substance of the negative rule for the `LA-Z` skill (see *Negative rules*), and it is the reason
`LA-M` stays human-driven. A product-side answer, if one is wanted, would have to come from outside
the TUI (an explicit `--i-am-a-human`-style refusal to run when stdin is not the controlling
terminal, or an audit trail that records approvals as unattended).

`LAF-01` is defensible: bootstrapping a registry has to start from an empty checkout, so the predicate
cannot demand markers that only exist after `init`. It is filed because the *operator* cannot predict
it — the surface offered depends on invisible directory contents, and the fallback (`not a catalog
directory`) fires only when `.git` is absent too. Needs a decision, not a fix.

### The `LAF-04`/`05`/`06` cluster — two maintainer worlds

These three are one structure seen from three sides, and they are the most important result of phase R
so far. AART has **two disjoint maintainer surfaces**:

| | canonical **registry** | legacy **catalog** |
|---|---|---|
| marker files | `aart-registry.json`, `aart-source.json` | `upstreams.json`, `bundles.json` |
| layout | `artifacts/<type>/<name>/artifact.json` + `payload/` | `skills/<name>/`, `guidelines/…` |
| CLI family | `aart registry …` (10) | `aart upstream …` (7) |
| TUI menu | `CANONICAL_MAINTAINER_ACTIONS` (11) | `MAINTAINER_ACTIONS` (7) |

Nothing in either family's `--help` says the other family will not work on your checkout, and the
guard is applied inconsistently — which is what produces `LAF-06`.

**This invalidated the plan's LA-R2 method.** `LA-R2` said to populate Registry A "via `upstream add` /
`scan` / `import`". Registry A is a canonical registry, so that family cannot author it. The
*assertions* of LA-R2 stand; the *method* is replaced by `registry scaffold` plus the canonical TUI
`promote-native` action, and the deviation is recorded here rather than treated as a failure.

Stressor IDs (`LAS-NN`) are registered in
[live-acceptance-scenarios.md](live-acceptance-scenarios.md). The **Stressor** and **Component**
columns are not bookkeeping — they are the only inputs the analysis below has. A finding recorded
without them cannot participate in it.

### Incidence — stressor × component

Filled as findings arrive; the input to the residue analysis (design §13). One row per stressor that
produced at least one residue.

| Stressor | Components struck | Findings |
|---|---|---|
| — | — | run not started |

### Coupling hotspots

Derived: components struck by several **unrelated** stressors. These are where an architectural
change buys the most, and they are read off the incidence table rather than argued for.

_empty_

### Systemic stressors

Derived: stressors that struck several components. A per-component fix will not hold against these.

_empty_

### Attractors

The same end state reached from unrelated stressors. Three stressors producing one failure shape is a
far stronger signal than three unrelated failures — note them while executing, they are almost
impossible to reconstruct afterwards.

_empty_

### Criticality points

Small stressor, disproportionate residue. These mark where the system sits on an edge and are the
findings most likely to return as production incidents.

_empty_

### Composed response — proposed changes

Written **last**, after the four sections above. The smallest set of architectural moves answering
the largest share of residues, each listing the finding IDs it retires.

> A one-to-one mapping between findings and proposed changes means the analysis has not been done
> yet — that is a fix list, not an architecture.

_empty_

### Open questions

`question` findings that need a decision from the maintainer rather than a code change. These are
the highest-value input to the LA-Z skill: each one is a candidate negative rule.

_empty_

---

## Knowledge accumulated

Written up continuously, not reconstructed at the end. This is the raw material for the holistic
agent skill (`LA-Z1`) and the README correction (`LA-Z2`).

### Behaviour that surprised

- **The TUI cannot be reached by piping stdin at all.** `cli._run_bare` requires `sys.stdin.isatty()`
  **and** `sys.stdout.isatty()`; with either one piped, bare `aart` prints `--help` and exits `0`. So
  the design's assumption in §6 — "TUI text front-end, agent, choices piped to stdin" — is only
  reachable through a **pty**, and the harness had to grow one
  (`$LA_ROOT/drive_tui.py`). This is a real constraint on any agent driving AART.
- **Under a pty, curses always wins.** `_curses_supported()` checks only that `curses` imports and
  both streams are TTYs, so a pty gets the curses front-end. Forcing the text front-end needs
  `TERM=dumb`, which makes `curses.initscr()` fail and `tui.run` degrade on `CursesUnavailable`.
  **pty + `TERM=dumb` is the reproducible recipe for every `TUI-text` scenario in this run**, and it
  is very likely the shape of the "TUI restarting, I typed digits" experience that motivated the
  vocabulary work — a degraded terminal silently swaps the front-end.
- **Input written ahead of a prompt is consumed by whichever read is pending.** A first probe that
  fed one line fewer than there were prompts still advanced past the role stage without the role
  prompt ever appearing on screen. The harness now feeds exactly one line per prompt and asserts the
  prompt echo. The underlying property — answers can land before the question is displayed — is the
  substance of `LAS-11` and gets its proper test in `LA-R-23`.

### Negative rules (what an agent must not do)

Seeded from the reasoning already recorded in
[PROGRESS-tui-program.md](../plan/PROGRESS-tui-program.md); confirmed or corrected by observation.

- **AART never adapts to a registry or a consumer repo.** A legacy source is offered subscription
  under the current rules; if it cannot subscribe, that is an acceptable outcome and AART's code does
  not change. Rejection is correct behaviour and is not a finding — silent absorption is.
  — _to confirm in `LA-R-29`_
- The TUI is where a human supplies consent. Piping choices into the text front-end is a test-only
  affordance, not a supported way to drive the tool. — **confirmed, and stronger than written**
  (`LA-R-23`/`LAF-10`): the pipe does not merely work by accident, it completes the full
  review→finalize→mutate path and exits `0`. Nothing in the product will stop an agent from doing
  this, so the rule is the agent's to keep: **an agent must not drive the TUI to approve a mutation.**
  Where an agent needs the effect, it uses flag mode, whose consent is explicit and auditable in the
  command line itself; where flag mode cannot reach it (`LAF-04`), the action belongs to a human.
- `--json` is a rendering, never a mode: it must not imply `--yes` or change any effect.
  — _to confirm in `LA-U-06`_
- `aart registry` never commits or pushes; publication is a separate deliberate act.
  — **confirmed** (`LA-R-25`): the whole authoring chain left the checkout dirty and untouched by
  Git; publication took a hand-written `git push`, and both clean clones then validated `--strict
  --frozen`.

### Ergonomic notes

_empty_

---

## Run log

Newest entry last. One line per session, stating what advanced and what stopped it.

- **2026-08-13** — design, plan, scenario map, and this record created. Fixture decisions settled:
  registries force-replaced without backup, sandbox `HOME` with one final real-`~` pass, agent drives
  the text front-end while Michal drives curses, matrix is `claude` in full plus three-profile smoke.
  Nothing executed.
- **2026-08-13** — the five migration/reporting subcommands moved from "deferred" to **out of scope
  by decision**; coverage restated as 44 of 49. Findings reframed as **residues**: a 24-entry
  stressor register added to the scenario map, findings gained stressor and component fields, the
  fix-now gate narrowed to `critical` only, and the residue analysis (incidence → hotspots →
  systemic stressors → attractors → composed response) inserted ahead of the skill and README in
  `LA-Z`. Still nothing executed.
- **2026-08-13** — the `residuality` bundle from `M1F1/residues-architecture-framework` added to
  Registry B. Chosen for structure rather than subject: it ships a real `agent-artifacts.import.json`
  (so manifest- and heuristic-mode import run side by side), and its ten skills share a sibling
  kernel path, which makes a partial bundle install a sharp stressor. Four stressors added —
  `LAS-25` manifest presence, `LAS-26` partial interdependent bundle, `LAS-27` legacy source against
  the protocol floor, `LAS-28` artifact-carried installer — with scenarios `LA-R-28..30`,
  `LA-U-29..30`, `LA-M-07`. A conditional re-opening of `registry migrate` is recorded in the plan
  and needs a maintainer decision **only if** `LA-R-29` shows a genuine below-floor source.
- **2026-08-13, execution session 1** — LA-0 complete (6/6). LA-R authored both registries from empty:
  **A** = 21 artifacts (14 superpowers skills, 4 MCP incl. an authored `context7`, plus a scaffolded
  guideline/hook/memory so all five types are live) in 2 collections; **B** = 23 artifacts (7 Pocock
  skills, the 14-package `residuality` bundle vendored from
  `M1F1/residues-architecture-framework`, an authored `mcp/atlassian`, and a deliberately colliding
  `skill/brainstorming`) in 2 collections. Both pass `validate --strict --frozen`, `audit`, and
  `test --compatibility all`. **Neither has been pushed.** Nine findings filed; the important one is
  the `LAF-04/05/06` cluster — AART has two disjoint maintainer surfaces, and `upstream import`
  silently writes legacy-shaped files into a canonical registry that the registry then ignores while
  still reporting success. LA-R2's method was replaced accordingly.
- **2026-08-13** — **one-way adaptation** recorded as a governing invariant (design §8): AART never
  adapts to a registry or a consumer repo; a legacy repo gets an attempt to subscribe under current
  rules and failure is an acceptable outcome. This inverts how the legacy branch is scored —
  rejection is now the pass condition and silent absorption is the `major` finding — and fixes the
  remedy direction: re-author the artifacts, never loosen AART.
