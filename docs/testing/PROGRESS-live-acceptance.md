# Live acceptance v1 — progress

Running record for the live acceptance run. Design:
[DESIGN-live-acceptance-v1.md](DESIGN-live-acceptance-v1.md) · Plan:
[PLAN-live-acceptance-v1.md](PLAN-live-acceptance-v1.md) · Scenarios:
[live-acceptance-scenarios.md](live-acceptance-scenarios.md).

**Status: not started.** Design and plan are written; no scenario has been executed.

---

## Run header

Filled by `LA-0.1`. Everything in this record is executed against this build; if it changes, the run
restarts (design §3).

| Field | Value |
|---|---|
| AART commit | _pending_ |
| Wheel | _pending_ |
| `aart --version` | _pending_ |
| Platform | macOS (darwin 25.2.0) |
| Registry A | `M1F1/agent-artifacts-registry` |
| Registry B | `M1F1/agent-artifacts-registry-2` |
| Consumer | `M1F1/agent-artifacts-live-acceptance-project` (not yet created) |
| Sandbox root | `$LA_ROOT` = `~/.aart-live-acceptance` |
| Started | _pending_ |
| Last updated | 2026-08-13 |

## Phase status

| Phase | WPs | Status | Note |
|---|---|---|---|
| LA-0 harness | 0.1 – 0.5 | not started | |
| LA-R registries | R1 – R7 | not started | |
| LA-S sources | S1 – S2 | not started | |
| LA-U user lifecycle | U1 – U11 | not started | |
| LA-M setup / MCP | M1 – M2 | not started | human-driven; credentials by Michal |
| LA-Z harvest | Z1 – Z2 | not started | only after exit criteria hold |

## Scenario results

One row per executed scenario. Empty until the run starts.

| ID | Result | Finding | Note |
|---|---|---|---|
| — | — | — | run not started |

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
| — | — | — | — | — | none recorded yet | — | — |

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

_empty_

### Negative rules (what an agent must not do)

Seeded from the reasoning already recorded in
[PROGRESS-tui-program.md](../plan/PROGRESS-tui-program.md); confirmed or corrected by observation.

- **AART never adapts to a registry or a consumer repo.** A legacy source is offered subscription
  under the current rules; if it cannot subscribe, that is an acceptable outcome and AART's code does
  not change. Rejection is correct behaviour and is not a finding — silent absorption is.
  — _to confirm in `LA-R-29`_
- The TUI is where a human supplies consent. Piping choices into the text front-end is a test-only
  affordance, not a supported way to drive the tool. — _to confirm in `LA-R-23`_
- `--json` is a rendering, never a mode: it must not imply `--yes` or change any effect.
  — _to confirm in `LA-U-06`_
- `aart registry` never commits or pushes; publication is a separate deliberate act.
  — _to confirm in `LA-R-25`_

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
- **2026-08-13** — **one-way adaptation** recorded as a governing invariant (design §8): AART never
  adapts to a registry or a consumer repo; a legacy repo gets an attempt to subscribe under current
  rules and failure is an acceptable outcome. This inverts how the legacy branch is scored —
  rejection is now the pass condition and silent absorption is the `major` finding — and fixes the
  remedy direction: re-author the artifacts, never loosen AART.
