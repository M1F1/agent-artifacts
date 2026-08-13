# Live acceptance v1 — design

Status: **design only, not executed.** The execution order lives in
[PLAN-live-acceptance-v1.md](PLAN-live-acceptance-v1.md), the reproducible scenario map in
[live-acceptance-scenarios.md](live-acceptance-scenarios.md), and the running record in
[PROGRESS-live-acceptance.md](PROGRESS-live-acceptance.md).

---

## 1. Why this exists

[system-matrix-v1.md](system-matrix-v1.md) is **hermetic**: thirteen scenarios, each in a fresh
child process with its own temporary `HOME`, `TMPDIR`, and XDG roots, with external HTTP forced to a
loopback refusal endpoint. It proves the core logic holds under controlled conditions, and it is the
right gate for CI.

By construction it cannot prove any of the following:

- that a registry **authored by the real maintainer commands and pushed to real GitHub** is
  consumable by the real client;
- that two registries **federate** when both are genuinely remote, rather than two local fixtures;
- that the TUI's two front-ends reach the same dispatch **on a real TTY**;
- that a real `~` layout survives `install` → `update` → `uninstall` and is left clean;
- that the 49 leaf subcommands **exist and behave as their own `--help` claims**.

Live acceptance closes exactly that gap. It is the **live** complement of the hermetic matrix, never
a replacement, and it never runs in default CI.

| | hermetic (`system-matrix`) | live (this document) |
|---|---|---|
| dependencies | fixtures, loopback-refused HTTP | real GitHub, real network, real `~` |
| driver | exact `unittest` IDs | real `aart` process, real terminal |
| runs | every commit, in CI | on demand, before a release |
| determinism | required | best-effort; findings are the output |
| failure means | regression | regression **or** a real-world gap the fixtures never modelled |

## 2. Vocabulary

Fixed here so the plan, the scenario map and the findings all use one set of words. This resolves a
collision already in the tree: [DESIGN.md §13](../design/DESIGN.md) says *"one core, two skins"*
(meaning TUI vs flag mode) while [tui.py](../../agent_artifacts/tui.py) says *"two front-ends, one
body"* (meaning curses vs text). Those are two different splits on two different levels.

| level | values | chosen by |
|---|---|---|
| **mode** | `TUI` / `flag mode` | TTY **and** absence of a subcommand ([cli.py `_run_bare`](../../agent_artifacts/cli.py)) |
| **front-end** (inside TUI only) | `curses` / `text` | the environment — curses is preferred and **degrades** when it cannot initialise |
| **rendering** (inside flag mode) | prose / `--json` | the `--json` flag |
| **consent handoff** | — | the transition where an agent stops and returns the decision to a human |

Two rules follow from this table and both are load-bearing for the test:

1. **`--json` is a rendering, not a mode.** It must change the encoding of the output and nothing
   else — same effects, same consent gates, same exit codes. Any scenario where `--json` changes
   *behaviour* is a finding, not a feature.
2. **The text front-end is not an agent surface.** It is an emergency rendering of a human surface.
   It presents numbered choices on stdin, which makes it trivially pipeable — and piping it is
   exactly how an automated caller would step past a consent gate that defaults to No. The plan
   deliberately *does* pipe it (§6), because that is the cheapest way to get reproducible coverage;
   the fact that piping works at all is recorded as a finding rather than treated as a feature.

## 3. Fixture topology

Four live elements plus the executable under test.

| Element | Identity | Role | Lifecycle |
|---|---|---|---|
| **Registry A** | `M1F1/agent-artifacts-registry` (public) | primary canonical registry | contents replaced from empty by maintainer commands |
| **Registry B** | `M1F1/agent-artifacts-registry-2` (public) | second federated registry | contents replaced from empty by maintainer commands |
| **Consumer** | `M1F1/agent-artifacts-live-acceptance-project` (new, private) | a repo pretending to be a team project | created fresh, reset between phases |
| **Sandbox HOME** | `$LA_ROOT/home` | user-scope destination | recreated per phase; one final real-`~` pass |
| **AART under test** | this checkout, installed from `make wheel` | the executable | pinned to one commit for the whole run |

**Registry A and B carry deliberately different content**, because a single registry cannot exercise
federation, qualified identity, or collision:

- **Registry A** — skills sourced from the *superpowers* framework, plus MCP entries for GitHub and
  Context7, plus at least one guideline, hook and memory artifact so all five artifact types are
  live.
- **Registry B** — skills sourced from *Matt Pocock*'s collection, the `residuality` bundle from
  `M1F1/residues-architecture-framework`, an MCP entry for Atlassian, and **at least one artifact
  whose unqualified name collides with one in Registry A**. The collision is intentional: it is the
  only way to test that an unqualified reference fails and a qualified one resolves, against real
  remotes.

The residuality repository is chosen for two structural properties, not for its subject matter:

- it ships a real `agent-artifacts.import.json`, where the superpowers and Pocock collections do
  not — so the same run exercises **manifest-mode and heuristic-mode import side by side**, and can
  check that `--mode auto` picks correctly between them;
- its ten skills form **one bundle with an internal dependency** — every `residual-NN-*` stage skill
  resolves a kernel at `../using-residues/`, a *sibling relative path*. That makes a partial bundle
  install a genuinely sharp stressor: installing a stage skill without the kernel produces a
  structurally valid artifact with a dangling internal reference, which no per-artifact validation
  is obliged to notice.

The second property is the more interesting one, because it is a failure mode the hermetic fixtures
have no reason to model.

The AART executable is **pinned for the whole run**. If a finding is fixed mid-run, the run is
either restarted or the fix is recorded as applying only to scenarios executed after it. Silent
mid-run upgrades make the whole record uninterpretable.

## 4. Phase model

```
LA-0  prepare      harness, sandbox, pinned wheel, coverage ledger
  │
LA-R  seed         Registry A + B authored via maintainer actions          ← seeding
  │
LA-S  wire         both registries added as configured sources             ← seeding
  │
LA-U  consume      full user lifecycle in the consumer repo                ← the actual test
  │
LA-M  setup/MCP    installers requiring credentials                        ← human-gated, last
  │
LA-Z  harvest      holistic agent skill + README update                    ← only when green
```

The distinction between **seeding** and **the actual test** is not cosmetic. LA-R and LA-S are the
*arrange* step for LA-U. That produces a reporting rule:

> A scenario whose precondition was never satisfied is **blocked**, not **failed**.

Without this rule one broken `registry lock` in LA-R renders as twenty install failures in LA-U, and
the findings ledger stops meaning anything. Every blocked scenario records the ID of the finding
that blocked it.

## 5. Coverage rule

The inventory is derived, not authored: `build_parser()` currently exposes **15 top-level commands /
49 leaf subcommands**, with constrained flags enumerated in the plan.

> Every leaf subcommand is either **covered** by at least one scenario, or **deferred** with a
> written reason. There is no third state.

"Deferred with a reason" is a legitimate outcome; §11 names the five subcommands excluded from v1 by
decision. An unlisted subcommand, by contrast, is a hole in the test — the ledger in the plan exists
so that a hole is visible rather than discovered later.

**Two maintainer surfaces exist and both must be covered.** [tui.py](../../agent_artifacts/tui.py)
defines `MAINTAINER_ACTIONS` (7 entries — upstream/catalog oriented: health, validate, add, import,
check, update, user) *and* `CANONICAL_MAINTAINER_ACTIONS` (11 entries — registry oriented: validate,
scaffold, promote-native, import-foreign, update-upstream, lock, build, audit, diff, init, user). The
TUI switches between them at runtime. **The switch condition is not yet established** and confirming
it is itself a task in LA-0 — if the condition is hard to state, that is a finding about the product,
not only about the test.

## 6. Execution split

| Surface | Driven by | Why |
|---|---|---|
| flag mode, prose + `--json` | agent | scriptable, fully reproducible |
| TUI **text** front-end | agent, choices piped to stdin | reproducible; see the caveat in §2 |
| TUI **curses** front-end | **human (Michal)** | cannot be driven programmatically; this is the real TTY path |
| anything requiring credentials | **human (Michal)** | see §10 |

Curses coverage is deliberately **narrow and last within its phase**: the human pass covers the
consent-critical screens (install review, setup approval, uninstall confirmation) rather than
re-walking every screen the text front-end already covered. Both front-ends fold input into the same
`WizardSession` and dispatch through the same command handlers, so the text pass carries the
behavioural coverage and the curses pass carries the rendering and TTY coverage.

Each curses scenario is written in the map as an explicit keystroke walkthrough with a stated
expected end state, so the human pass is a checklist rather than an exploration.

## 7. Evidence

Every executed scenario records: scenario ID, exact command or keystrokes, exit code, whether the
`--json` envelope was well-formed where applicable, and a one-line observed result. Prose output is
**not** pasted wholesale — the hermetic runner already avoids capturing child output because those
paths exercise credential redaction, and the same caution applies here for a stronger reason: this
run touches real credentials in LA-M.

`AART_DEBUG=1` exists ([tui.py](../../agent_artifacts/tui.py)) and is the sanctioned way to capture a
traceback for a finding. It is off by default so that scenarios observe default behaviour.

## 8. Findings discipline — stressors and residues

**Record, do not fix.** Two independent reasons, and the second is the important one.

The mechanical reason: a fix mid-run invalidates every scenario already executed against the pinned
build (§3).

The architectural reason: **the findings of this run are not a defect list, they are residues.** Each
scenario applies a named *stressor* to the system; what remains afterwards is the *residue*. A single
residue read on its own invites a local patch that makes that one symptom go away. Read as a set,
residues reveal where the structure is actually brittle — and the correct response is usually one
change answering many of them at once, not many changes answering one each. This run is deliberately
organised so that the second reading is possible, following the residuality approach the maintainer
works in (see `M1F1/residues-architecture-framework`).

Fixing as you go destroys precisely this. Each local patch removes a data point and changes the
system under test, so the set never accumulates and the composition never becomes visible. **The
value of this run is proportional to how many residues survive to the analysis in §13.**

### The one-way adaptation rule

A project invariant, stated here because it governs how findings are **classified**, not merely how
they are fixed:

> **AART never adapts to a registry or to a consumer repo.** When a repo carries artifacts authored
> against an older AART, the only move is an attempt to subscribe **under the current rules**. If
> that attempt fails, that is an acceptable outcome. AART's code does not change to accommodate it —
> the other side adapts.

Two consequences bind this run, and getting them backwards would make the whole legacy branch of the
findings ledger wrong:

- **A legacy source being rejected is correct behaviour and is not a finding.** It must not be filed
  as one, and it must not be worked around by loosening anything in AART.
- **The finding is the opposite case**: a below-floor source that AART silently absorbs. That would
  mean the protocol floor is advisory rather than enforced, and it is `major` even when everything
  downstream appears to work.

A deliberate one-way conversion run by a maintainer (`registry migrate`) does **not** violate the
rule. There the other party is adapting, on purpose, as an explicit act — which is exactly the
direction the rule prescribes.

### The critical-fix gate

Narrow on purpose. A finding is fixed mid-run **only** when both hold:

1. it blocks the remainder of the run outright, and
2. there is no workaround.

Everything else — including `major` breakage of a documented capability — is recorded and worked
around. When a workaround exists, it is used and written into the scenario, and the underlying
finding stays open. A fix that passes the gate is recorded with the commit, and every scenario
executed before it is marked as belonging to the previous build.

### Records

Finding IDs are `LAF-NN`; stressor IDs are `LAS-NN` and are registered in
[live-acceptance-scenarios.md](live-acceptance-scenarios.md). Each finding carries: scenario ID,
**stressor ID**, affected component, severity, one-line symptom, reproduction, and what it blocks.

The stressor and component fields are what make the incidence matrix in
[PROGRESS-live-acceptance.md](PROGRESS-live-acceptance.md) fillable. Without them the ledger is a bug
list again.

| Severity | Meaning |
|---|---|
| `critical` | blocks the remainder of the run with no workaround — the only fix-now case |
| `major` | a documented capability is broken or absent |
| `minor` | works, but output, help text, or ergonomics mislead |
| `question` | behaviour is defensible but undocumented; needs a decision, not a fix |

`question` matters more than it looks, and doubly so here: under a residual reading, "is this on
purpose?" is often the first visible edge of a stressor the design never considered. Filing those as
bugs produces a ledger nobody trusts and buries the most interesting signal in it.

### Two properties to watch for during the run

Both are cheap to notice while executing and expensive to reconstruct afterwards:

- **Attractors** — the same end state reached from unrelated stressors. Three different stressors
  producing the same failure shape is a much stronger signal than three unrelated failures, and it
  usually names the component that needs to change.
- **Criticality** — a small stressor producing a disproportionate residue. These mark where the
  system sits on an edge, and they are the findings most likely to reappear as production incidents.

Note both in the scenario row as they are observed; §13 aggregates them.

## 9. Teardown and repeatability

The tool's whole purpose is installing and removing files, so leftovers are both a correctness
question and a repeatability question. Teardown is therefore itself an assertion, not housekeeping:

- **Consumer repo** — after the uninstall scenarios, the worktree must be byte-identical to its
  pre-install state. `git status --porcelain` empty is the assertion. Any residue is a finding.
- **Sandbox HOME** — destroyed and recreated between phases. Before destruction, its tree is listed
  so that a user-scope uninstall leaving residue is caught rather than deleted.
- **Real `~` pass** — the final scenario set, run once, with an explicit inventory of `~/.claude/`
  before and after. This is the only point where the run can touch the working configuration, and it
  is the one place a human should be watching.
- **Registries** — left in their final authored state; they are the deliverable of LA-R, not
  garbage.

## 10. Safety boundaries

- **Credentials are entered by the human, never by the agent.** LA-M is last precisely so that
  everything credential-free is already green before any secret is in play. The agent prepares the
  command, states exactly what it will do, and hands over — a *consent handoff* in the sense of §2.
- **Registry A and B are force-replaced** on the maintainer's explicit instruction, without a backup
  branch, also on their explicit instruction. Recorded here so the decision is attributable.
- **The real-`~` pass is opt-in and last.** Everything before it runs against the sandbox HOME.
- **`aart registry` never commits or pushes** ([maintainer-commands-v1.md](../registry/maintainer-commands-v1.md)).
  Publication is a separate, deliberate `git push` — which makes the push a natural consent
  checkpoint rather than a side effect.

## 11. Out of scope

- Performance, load, concurrency beyond what the hermetic `concurrent-sync-install` scenario covers.
- Windows and Linux. This run is macOS only; per-platform behaviour stays with the hermetic matrix.
- Harnesses other than the four built-in profiles (`claude`, `opencode`, `tabnine`, `vibe`).
- Full-matrix coverage of every profile. Per the maintainer's decision the matrix is **`claude` in
  full, the other three smoke-only** (`install` / `status` / `uninstall`). A per-harness translation
  bug outside `claude` will therefore only be caught if it is gross.
- **The migration surface** — `migrate state`, `registry migrate`. Exercising them means synthesising
  a legacy 0.1.x catalog, which is its own body of work.
- **The reporting surface** — `reporting validate-event`, `reporting validate-issue`,
  `reporting aggregate`. Aggregation needs accumulated usage events that this run does not generate.

These five subcommands are excluded **by decision**, not carried as debt. No assertion in this plan
depends on them, so their absence does not weaken the run; a future version that wants them brings
its own fixtures rather than inheriting a gap from v1.

One conditional exception is written into the plan: the migration exclusion rests on there being no
legacy fixture, and the residuality repository may turn out to be one. If it does, the plan records
an open question rather than re-expanding scope by itself.

## 12. Exit criteria

The run is complete when all of the following hold:

1. All 49 leaf subcommands are accounted for: 44 covered, 5 explicitly out of scope per §11.
2. Both registries are authored, pushed, and consumable end to end.
3. The full user lifecycle passes on `claude`, and smoke passes on the other three profiles.
4. Both TUI front-ends have been exercised; consent-critical screens have a human curses pass.
5. Teardown assertions pass — clean consumer worktree, inventoried sandbox and real `~`.
6. Every failure is filed as `LAF-NN` with a reproduction, and none is silently fixed.

Exit does **not** require zero findings. A run that ends with a well-formed findings ledger and a
complete coverage table has succeeded; that ledger is the product.

## 13. Downstream deliverables

Deferred until the criteria in §12 hold, and named here so knowledge is accumulated with a target in
mind rather than reconstructed afterwards:

- **A residue analysis — first, and gating the other two.** Read the whole findings set as one
  object rather than a queue:
  1. fill the incidence matrix (stressor × affected component) from the recorded findings;
  2. find the components struck by many unrelated stressors — those are the coupling hotspots, and
     they are where change buys the most;
  3. find the stressors that strike many components — those are systemic, and a per-component fix
     will not hold against them;
  4. name the attractors and the criticality points collected during the run (§8);
  5. **only then** propose changes, as a composition: the smallest set of architectural moves that
     answers the largest share of the residues.

  The output is an ordered set of proposed changes with the finding IDs each one answers, so a
  reviewer can see that a single change retires many residues. A one-to-one mapping between findings
  and proposed fixes is a signal the analysis has not been done yet.

- **A holistic agent skill** — the trigger-plus-contract shape already reasoned through in
  [PROGRESS-tui-program.md](../plan/PROGRESS-tui-program.md): a short skill that orients an agent to
  the real command surface, the consent boundary, and the negative rules. Live acceptance is where
  the negative rules are actually discovered — every `question` finding is a candidate line.
- **A README update** — corrected against observed behaviour rather than intent.

Both are written **only after** the run is green, because a skill authored from a broken run teaches
the workarounds instead of the tool.
