# Live acceptance v1 — scenario map

The reproducible unit of this run. Design: [DESIGN-live-acceptance-v1.md](DESIGN-live-acceptance-v1.md).
Order and work packages: [PLAN-live-acceptance-v1.md](PLAN-live-acceptance-v1.md).

Every scenario has a stable ID. A future run re-executes these IDs and compares against the recorded
result, so **scenario text is append-only**: correcting a scenario means adding `LA-U-14a`, not
editing `LA-U-14` after it has been executed once.

Columns: **Mode** is `flag` / `TUI-text` / `TUI-curses` (design §2). **By** is `D` agent / `H` human.
`$P` = consumer project path, `$RA` / `$RB` = Registry A / B checkouts.

---

## Stressor register

Each scenario applies one or more named **stressors**; what remains afterwards is the **residue**
recorded as a finding (design §8). This register is the stressor-centric view of the same scenarios,
and it is what makes cross-scenario analysis possible: a component struck by several *unrelated*
stressors is a coupling hotspot, and a stressor that strikes several components is systemic.

The set is not invented. It is drawn from what this system actually does, and at least one entry has
already produced a real defect: the guideline-versus-memory clobber found during the memory-artifact
work is exactly the residue of `LAS-22`, discovered by applying that stressor rather than by reading
the code.

| ID | Stressor | Scenarios |
|---|---|---|
| `LAS-01` | Cold start from an empty checkout | `LA-R-01`, `LA-R-17` |
| `LAS-02` | Repeated application of a generator (idempotency) | `LA-R-03`, `LA-R-06`, `LA-R-07` |
| `LAS-03` | Drift in managed registry content | `LA-R-04`, `LA-R-10` |
| `LAS-04` | Drift in an installed artifact | `LA-U-12`, `LA-U-13` |
| `LAS-05` | Name collision across sources | `LA-R-19`, `LA-S-08`, `LA-S-09` |
| `LAS-06` | Federation — a second remote source | `LA-R-17`, `LA-S-02`, `LA-S-07` |
| `LAS-07` | Network absent | `LA-U-20`, `LA-U-21` |
| `LAS-08` | Cold cache | `LA-0-04`, `LA-U-21` |
| `LAS-09` | History replacement (force-push) | `LA-R-25` |
| `LAS-10` | Mid-flow abandonment | `LA-R-22`, `LA-U-27` |
| `LAS-11` | Unattended input on stdin | `LA-R-21`, `LA-R-23`, `LA-U-26` |
| `LAS-12` | Degraded terminal — curses unavailable | every `TUI-text` scenario |
| `LAS-13` | Relocated environment (`HOME` override) | `LA-0-03`, `LA-0-04`, `LA-U-08` |
| `LAS-14` | Credential absent, then present | `LA-M-01`, `LA-M-03` |
| `LAS-15` | Partial failure inside an effect queue | `LA-M-04` |
| `LAS-16` | Rollback after effects were applied | `LA-M-05` |
| `LAS-17` | Duplicate registration | `LA-S-03` |
| `LAS-18` | Broken configuration | `LA-S-05`, `LA-S-06` |
| `LAS-19` | Upstream change and upstream removal | `LA-R-20`, `LA-U-14`, `LA-U-15` |
| `LAS-20` | Alternate translation target (non-`claude` profile) | `LA-U-23`, `LA-U-24`, `LA-U-25` |
| `LAS-21` | Symlink instead of copy | `LA-U-07`, `LA-U-14`, `LA-U-19` |
| `LAS-22` | Two artifact types contending for one destination | `LA-U-10` |
| `LAS-23` | Scope switch, project ↔ user | `LA-U-08`, `LA-U-28` |
| `LAS-24` | Rendering switch (`--json`) | `LA-U-06` |
| `LAS-25` | Import manifest present vs absent (mode resolution) | `LA-R-28` |
| `LAS-26` | Partial install of a bundle with an internal sibling dependency | `LA-U-29`, `LA-U-30` |
| `LAS-27` | Legacy upstream against the current protocol floor | `LA-R-29`, `LA-R-30` |
| `LAS-28` | Artifact carrying a setup installer | `LA-M-07` |
| `LAS-29` | Ambient working directory decides which role surface is offered | `LA-0-05` |
| `LAS-30` | One maintainer family pointed at the other family's workspace shape | `LA-R-11`, `LA-R-12`, `LA-R-13` |
| `LAS-57` | A check that found nothing, against a check that never ran | `LA-R-31`, `LA-R-32`, `LA-R-33` |

The register is **append-only during a run**. A stressor discovered mid-run is added as `LAS-25`+
with the scenario that revealed it — that is a result in itself, since it means the design missed a
way the system can be pushed.

**The numbering continues across runs, not within this file.** `LAS-31`..`LAS-40` are defined in
[PROGRESS-live-acceptance-v2.md](PROGRESS-live-acceptance-v2.md), `LAS-41`..`LAS-48` in
[v3](PROGRESS-live-acceptance-v3.md), and `LAS-49`..`LAS-56` in
[setup-build](PROGRESS-live-acceptance-setup-build.md). A new stressor therefore starts at `LAS-57`,
not at the next number after the table above. That the table above stops at `LAS-30` while the
namespace runs to `LAS-56` is what `LAF-87` records.

---

## Phase 0 — harness

| ID | Title | Mode | By | Invocation | Expected |
|---|---|---|---|---|---|
| `LA-0-01` | Pin the build | flag | D | `make wheel`; install; `aart --version` | version matches wheel; SHA recorded |
| `LA-0-02` | Inventory matches plan | flag | D | derive leaves from `build_parser()` | 49 leaves, equal to the ledger |
| `LA-0-03` | HOME isolation holds | flag | D | `HOME=$LA_HOME aart status --scope user --json` | user root under `$LA_HOME`; real `~` untouched |
| `LA-0-04` | Cache follows HOME | flag | D | inspect `$LA_HOME/.cache/agent-artifacts` after a sync | cache created in sandbox, not in real `~` |
| `LA-0-05` | Maintainer menu switch | TUI-text | D | enter maintainer role from a registry checkout, then from a non-registry dir | the two menus differ; condition stateable in one sentence |
| `LA-0-06` | Upgrade dry run | flag | D | `aart upgrade --dry-run --wheel <w>` | reports plan; mutates nothing |

## Phase R — registry authoring

| ID | Title | Mode | By | Invocation | Expected |
|---|---|---|---|---|---|
| `LA-R-01` | Init from empty | flag | D | `aart registry init --source $RA --source-id la-registry-a --display-name "…"` | protocol markers + CI + inert reporting templates written; no commit, no push |
| `LA-R-02` | Scaffold one artifact | flag | D | `aart registry scaffold --source $RA --profile claude --install-mode copy --install-scope project` | one manifest + starter payload |
| `LA-R-03` | Format is idempotent | flag | D | `registry format` twice, then `--check` | second run changes nothing; `--check` exits `0` |
| `LA-R-04` | Check detects drift | flag | D | perturb a managed JSON; `registry format --check` | exits `1`, names the path, writes nothing |
| `LA-R-05` | Strict frozen validate | flag | D | `registry validate --strict --frozen` | passes on a fully locked/built registry |
| `LA-R-06` | Lock resolves references | flag | D | `registry lock`, then `lock --check` | exact commits + digests; `--check` exits `0` |
| `LA-R-07` | Build the index | flag | D | `registry build`, then `build --check` | payload-free index; `--check` exits `0` |
| `LA-R-08` | Audit evidence | flag | D | `registry audit --json` | review/provenance/setup/license/risk evidence reported |
| `LA-R-09` | Compatibility test | flag | D | `registry test --compatibility all` | minimum and latest both reported |
| `LA-R-10` | Diff is non-mutating | flag | D | `registry diff` on a drifted checkout | shows drift; worktree unchanged |
| `LA-R-11` | Add an upstream | flag | D | `upstream add --source $RA --path … --ref …` | one tracked upstream |
| `LA-R-12` | Scan modes agree | flag | D | `upstream scan --mode auto\|heuristic\|manifest` | `auto` result is explainable from the other two |
| `LA-R-13` | Import dry run predicts | flag | D | `upstream import --dry-run` then real import | written set equals predicted set |
| `LA-R-14` | Superpowers skills land | flag | D | import into `$RA` | skills appear in `list --type skill` |
| `LA-R-15` | All five types present | flag | D | `list --type {skill,guideline,mcp,hook,memory}` | each type non-empty in `$RA` |
| `LA-R-16` | GitHub + Context7 MCP entries | flag | D | author MCP artifacts in `$RA` | present, **no credentials in the registry** |
| `LA-R-17` | Registry B authored | flag | D | LA-R-01..09 against `$RB` | same outcomes on a second remote |
| `LA-R-18` | Pocock skills + Atlassian MCP | flag | D | import into `$RB` | present |
| `LA-R-19` | Deliberate name collision | flag | D | author a name in `$RB` that exists in `$RA` | authoring succeeds; collision deferred to resolution time |
| `LA-R-20` | Upstream check/update | flag | D | `upstream check --all`, `upstream update --dry-run` | drift reported; dry run mutates nothing |
| `LA-R-21` | Maintainer text walkthrough | TUI-text | D | piped choices through both action menus | reaches the same outcome as the flag equivalent |
| `LA-R-22` | Mid-flow quit is inert | TUI-text | D | quit at the review screen | nothing written |
| `LA-R-23` | Piped stdin vs consent | TUI-text | D | pipe an approval sequence into a mutating flow | **record whether it proceeds unattended** (design §2) |
| `LA-R-24` | Maintainer curses walkthrough | TUI-curses | H | see walkthrough below | screens legible; review states effects before applying |
| `LA-R-25` | Push both registries | flag | D→H | `git push --force` after review | clean clone passes `validate --strict --frozen` |
| `LA-R-26` | Security evidence | flag | D | `security scan --index --lock --cache`, `show`, `analyzers`, `suites` | evidence emitted |
| `LA-R-27` | Verify is reproducible | flag | D | `security verify …` twice on unchanged inputs | byte-identical result |
| `LA-R-28` | Manifest vs heuristic import | flag | D | `upstream scan --mode auto` on the residuality repo (has `agent-artifacts.import.json`) and on a manifest-less collection | `auto` picks manifest for the first, heuristic for the second; the choice is explainable |
| `LA-R-29` | **Legacy manifest is rejected, not absorbed** | flag | D | import the residuality repo if its manifest predates the current protocol floor | **typed migration error naming what to change.** Rejection is the pass condition, not a finding (design §8, one-way adaptation). The finding is silent absorption |
| `LA-R-30` | Compatibility floor is stated | flag | D | `registry test --compatibility minimum`; per-artifact compatibility of the imported bundle | the floor and the offending artifact are both named in the failure |
| `LA-R-31` | **A completed upstream check says so** | flag | D | `registry audit --check-upstream` on a registry that vendors nothing | one `info` line stating the check ran and found nothing to check |
| `LA-R-32` | The same audit without the flag | flag | D | `registry audit` on the same registry | no such line — its absence is what tells an operator the check did not run |
| `LA-R-33` | The counts on a real vendored copy | flag | D | `registry audit --check-upstream` on a registry holding a vendored package, upstream current | `n up-to-date, 0 changed, 0 unreachable`; needs an upstream the runner controls, which `LAF-43` denies |

## Phase S — sources

| ID | Title | Mode | By | Invocation | Expected |
|---|---|---|---|---|---|
| `LA-S-01` | Add Registry A as default | flag | D | `source add --kind registry-git --alias la-a --location … --default` | added, marked default |
| `LA-S-02` | Add Registry B | flag | D | `source add --kind registry-git --alias la-b --location … --no-default` | added, not default |
| `LA-S-03` | Duplicate alias rejected | flag | D | re-add `la-a` | typed failure, no duplicate |
| `LA-S-04` | List / sync / health | flag | D | `source list\|sync\|health --json` | well-formed envelopes |
| `LA-S-05` | Doctor is read-only | flag | D | `source doctor` (no `--apply`) | diagnoses; mutates nothing |
| `LA-S-06` | Doctor applies | flag | D | `source doctor --apply` on a broken config | repairs, reports what changed |
| `LA-S-07` | Marketplace browse | flag | D | `marketplace list --json` | union of both registries; digests verified |
| `LA-S-08` | **Unqualified collision fails** | flag | D | resolve the colliding name unqualified | fails with an actionable message |
| `LA-S-09` | **Qualified collision resolves** | flag | D | resolve the same name qualified by source | resolves to the intended artifact |
| `LA-S-10` | Marketplace health | flag | D | `marketplace health --environment …` | reports per-source health |

## Phase U — user lifecycle

| ID | Title | Mode | By | Invocation | Expected |
|---|---|---|---|---|---|
| `LA-U-01` | List is inert | flag | D | `list --type … --bundle … --source …` | nothing written |
| `LA-U-02` | Install dry run | flag | D | `install --dry-run --profile claude --scope project` | predicted path set recorded |
| `LA-U-03` | **Dry run equals real run** | flag | D | real install; compare written paths | sets identical |
| `LA-U-04` | Review without `--yes` | flag | D | `install` without `--yes` | reviews only; no effect |
| `LA-U-05` | Status after install | flag | D | `status --json` | every installed artifact reported, no drift |
| `LA-U-06` | `--json` invariance | flag | D | repeat LA-U-02..05 with `--json` | same effects, same exit codes, only encoding differs |
| `LA-U-07` | Symlink mode | flag | D | `install --link` | entries reported live by `status` / `check` |
| `LA-U-08` | User scope | flag | D | `HOME=$LA_HOME install --scope user` | lands under sandbox home only |
| `LA-U-09` | Memory modes | flag | D | `--memory-mode replace\|prepend\|append\|skip` | sentinel-wrapped block per mode; `skip` writes nothing |
| `LA-U-10` | Guideline ≠ memory file | flag | D | install both types | separate destinations; no clobber, no false drift |
| `LA-U-11` | `--all` and `--bundle` | flag | D | `install --all`, `install --bundle …` | selection matches the request |
| `LA-U-12` | Drift is reported | flag | D | hand-edit an installed file; `status` | drift reported, not silently repaired |
| `LA-U-13` | Check vs upstream | flag | D | `check --json` | distinguishes local drift from upstream change |
| `LA-U-14` | Update preserves links | flag | D | `update` with symlinked entries | links stay live |
| `LA-U-15` | Update prune | flag | D | `update --prune` after removing an artifact upstream | stale entry removed |
| `LA-U-16` | Uninstall dry run | flag | D | `uninstall --dry-run` | predicted removals |
| `LA-U-17` | **Clean teardown** | flag | D | `uninstall --all`; `git status --porcelain` | **empty**; sentinel stripped; no orphan symlink |
| `LA-U-18` | Marketplace install | flag | D | `marketplace install --mode copy` | installs from the registry index |
| `LA-U-19` | Marketplace symlink mode | flag | D | `marketplace install --mode symlink` | links live |
| `LA-U-20` | Offline warm cache | flag | D | `marketplace status --offline` with warm cache | succeeds without Git |
| `LA-U-21` | Offline cold cache | flag | D | same with cache cleared | typed failure; no Git access |
| `LA-U-22` | Marketplace update/uninstall | flag | D | `marketplace update`, `uninstall` | lifecycle closes cleanly |
| `LA-U-23` | opencode smoke | flag | D | install → status → uninstall | clean round trip |
| `LA-U-24` | tabnine smoke | flag | D | install → status → uninstall | clean round trip; MCP-location caveat expected |
| `LA-U-25` | vibe smoke | flag | D | install → status → uninstall | clean round trip |
| `LA-U-26` | User text walkthrough | TUI-text | D | piped: source → profile → artifacts → review | equals the flag-mode outcome |
| `LA-U-27` | User curses walkthrough | TUI-curses | H | see walkthrough below | install review states effects before applying |
| `LA-U-28` | **Real `~` round trip** | flag | D→H | inventory `~/.claude`; install/status/uninstall `--scope user`; re-inventory | inventories identical |
| `LA-U-29` | Whole bundle installs | flag | D | `install --bundle residuality` | all 10 skills + guideline land; `../using-residues/` resolves from each stage skill |
| `LA-U-30` | **Partial bundle leaves a dangling reference** | flag | D | install `residual-03-stressors` **without** `using-residues` | record whether anything warns; a structurally valid artifact with a broken sibling path is the residue to look for |

## Phase M — setup and MCP · human-driven

| ID | Title | Mode | By | Invocation | Expected |
|---|---|---|---|---|---|
| `LA-M-01` | Setup review only | flag | D | `marketplace setup` without approval flags | lists each effect, entrypoint, trust status; executes nothing |
| `LA-M-02` | Setup status before run | flag | D | `setup status --json` | nothing queued as done |
| `LA-M-03` | Approved run | flag | H | `setup run` + explicit approval flags, credentials supplied by Michal | per-item terminal outcomes retained |
| `LA-M-04` | Retry resumes failures only | flag | H | `setup retry` | succeeded items are not re-run |
| `LA-M-05` | Rollback restores | flag | H | `setup rollback` | prior state restored exactly |
| `LA-M-06` | No credential leakage | flag | H | inspect all captured output | no secret in any recorded artefact |
| `LA-M-07` | Skill-carried installer | flag | D review / H run | any residuality skill declaring setup effects | reviewed in `LA-M-01` with no effect; executed here only after explicit approval |

---

## Curses walkthroughs (human passes)

Written as checklists so `LA-R-24` and `LA-U-27` are executed identically each run. Keystrokes are
recorded during the first pass and appended here — until then the steps are stated by intent.

### `LA-R-24` — maintainer, curses

1. `cd $RA && aart` on a real TTY → onboarding screen appears.
2. Select role **Maintainer** → maintainer action menu appears.
3. Confirm the menu is the **canonical** set (11 entries) and matches LA-0-05's stated condition.
4. Choose **Validate** → review screen states what will be read and that nothing is written.
5. Confirm; observe the result screen; note legibility at the default terminal width.
6. Return, choose **Audit**, confirm, observe.
7. Quit from a review screen without confirming → assert nothing was written.

### `LA-U-27` — user, curses

1. `cd $P && aart` on a real TTY.
2. Select role **User** → source selection lists both `la-a` and `la-b`.
3. Select profile **claude**.
4. Select two artifacts, one from each registry.
5. On the install review screen, assert: destination paths shown, install mode shown, and the
   default action is **not** "apply".
6. Confirm → install completes; screen reports what was written.
7. Re-enter, choose uninstall, confirm the review screen states removals before applying.
8. Quit mid-flow once → assert nothing changed.

---

## Recording rules

- Result per scenario goes in [PROGRESS-live-acceptance.md](PROGRESS-live-acceptance.md) as
  `pass` / `fail` / `blocked` / `deferred`, with the finding ID when not `pass`.
- Do not paste raw prose output into the record. Phase M touches real credentials and the redaction
  paths are exactly what this run is exercising (design §7).
- `AART_DEBUG=1` only when capturing a traceback for a finding; never as the default.
