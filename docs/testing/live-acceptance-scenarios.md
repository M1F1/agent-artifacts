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
| `LAS-13` | Relocated environment (`HOME` override) | `LA-0-03`, `LA-0-04`, `LA-U-08`, `LA-M-08`, `LA-M-11` |
| `LAS-14` | Credential absent, then present | `LA-M-01`, `LA-M-03`, `LA-M-09`, `LA-M-10` |
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
| `LAS-62` | An operator accepts every default the tool itself offers | `LA-0-11`, `LA-0-12` |
| `LAS-63` | A command surface advertises a capability no command can run | `LA-R-42` |
| `LAS-64` | One runtime reaches two different layers for two neighbouring commands | `LA-R-43` |
| `LAS-65` | Every command run before anything at all is configured | `LA-0-13` |
| `LAS-66` | A consumer that reads only the machine channel and never the prose | `LA-0-14` |
| `LAS-67` | A command that says it changes nothing, watched at the disk | `LA-U-36` |
| `LAS-68` | The durable store watched across a whole install and uninstall | `LA-U-37` |
| `LAS-69` | An origin withdrawn after its content has been seen | `LA-U-38` |
| `LAS-70` | An instruction file the operator also writes in, by hand, after the install | `LA-U-39` |
| `LAS-71` | A shared config file two artifacts and the operator all write into | `LA-U-40` |
| `LAS-72` | A repository that can only be reached without a network | `LA-S-17` |
| `LAS-73` | A source tree holding a file type the snapshot format cannot carry | `LA-S-18` |
| `LAS-57` | A check that found nothing, against a check that never ran | `LA-R-31`, `LA-R-32`, `LA-R-33` |
| `LAS-58` | A reserved marker file is present and cannot be read | `LA-S-14`, `LA-S-15`, `LA-S-16` |
| `LAS-59` | The same defect reached by authoring instead of by copying | `LA-R-34`, `LA-R-35`, `LA-R-36` |
| `LAS-32` | A persisted record read by a later executable than wrote it | `LA-M-12`, `LA-M-13`, `LA-M-14`, `LA-M-15` |
| `LAS-61` | A compatibility window declared by a release that is no longer the running one | `LA-R-37`..`LA-R-41` |
| `LAS-33` | The last subscription removed while installed artifacts remain | `LA-S-11`, `LA-S-12`, `LA-S-13` |
| `LAS-60` | A destination AART shares with the operator, emptied | `LA-U-31`..`LA-U-35` |

The register is **append-only during a run**. A stressor discovered mid-run is added as `LAS-25`+
with the scenario that revealed it — that is a result in itself, since it means the design missed a
way the system can be pushed.

**The numbering continues across runs, not within this file.** `LAS-31`..`LAS-40` are defined in
[PROGRESS-live-acceptance-v2.md](PROGRESS-live-acceptance-v2.md), `LAS-41`..`LAS-48` in
[v3](PROGRESS-live-acceptance-v3.md), and `LAS-49`..`LAS-56` in
[setup-build](PROGRESS-live-acceptance-setup-build.md). A new stressor therefore starts at `LAS-57`,
not at the next number after the table above. That the table above stops at `LAS-30` while the
namespace runs to `LAS-56` is what `LAF-87` records.
[setup-build](PROGRESS-live-acceptance-setup-build.md). A new stressor therefore starts above the
highest id in use anywhere, not at the next number after the table above. That the table stops at
`LAS-30` while the namespace runs past `LAS-56` is what `LAF-87` records.

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
| `LA-0-11` | The wizard's own defaults, authored | flag | D | `registry init --minimum-version 1.0.0 --maximum-version 2.0.0 --yes`, then `registry validate` — the literals `_curation_request` offers at both `INIT` prompts | a registry this AART accepts, or a refusal at `init` rather than at the command `init` advises next |
| `LA-0-12` | The flag defaults, authored | flag | D | `registry init` with neither version flag, then `registry validate` | `validate` passes; the control for `LA-0-11` |
| `LA-0-13` | Every leaf invoked cold | flag | D | derive the leaves from `build_parser()`, run each with no arguments in an empty directory under a sandbox `HOME` | every leaf refuses or answers; no traceback reaches the operator, and the count of leaves is recorded |
| `LA-0-14` | The machine channel, cold | flag | D | every leaf that accepts `--json`, run with it in the same empty state; parse stdout | valid JSON on stdout, carrying `schema_version`, the operation, and a typed code per diagnostic. A leaf with no `--json` is named, with what its consumer is |

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
| `LA-R-42` | The analyzer surface, taken at its word | flag | D | `security analyzers`, then `security suites`, then read `security scan --help` for any way to select a suite or a provider | either a flag that runs what the first two commands advertise, or the two listings say plainly that nothing runs them |
| `LA-R-43` | A command that skips the layer that owns it | flag | D | `registry init` in a throwaway Git checkout, then `registry format`; separately, ask which function the command reached | `format` succeeds *and* the application-layer entry point for it has a caller — one runtime reaching one layer |
| `LA-R-31` | **A completed upstream check says so** | flag | D | `registry audit --check-upstream` on a registry that vendors nothing | one `info` line stating the check ran and found nothing to check |
| `LA-R-32` | The same audit without the flag | flag | D | `registry audit` on the same registry | no such line — its absence is what tells an operator the check did not run |
| `LA-R-33` | The counts on a real vendored copy | flag | D | `registry audit --check-upstream` on a registry holding a vendored package, upstream current | `n up-to-date, 0 changed, 0 unreachable`; needs an upstream the runner controls, which `LAF-43` denies |
| `LA-R-34` | **An authored descriptor that starts nothing is named** | flag | D | scaffold `mcp`, replace `payload/mcp.json` with the harness shape `{"mcpServers": …}`, `registry audit` | the audit fails and names the package and the shape the descriptor needs; no vendoring anywhere in the registry |
| `LA-R-35` | An authored descriptor launching a withheld file | flag | D | scaffold a second `mcp`, point `command`/`args` at `payload/index.js`, `registry audit` | the audit fails and names the file the consumer never receives |
| `LA-R-36` | **The refusal stops at the maintainer's boundary** | flag | D | on the same registry: `registry validate --strict --frozen`, then `source add` + `marketplace install` of the faulty artifact from a consumer project | validate passes, the subscription and install still succeed, and the merged entry is the empty object the audit describes |
| `LA-R-37` | The executable still starts | flag | A | `aart --version` from the installed wheel | the entry point imports and reports `2.6.0`; `RS-02` moves an import into `cli.py`, and an entry point that fails to import fails after every unit test has passed |
| `LA-R-38` | The declared window is the running release's | flag | A | `aart registry init --help` | both defaults are derived, not typed: `2.6.0` and `3.0.0` on a `2.6.0` executable |
| `LA-R-39` | The window reaches the manifest | flag | A | `registry init --yes`, then read `requires_aart` out of `aart-registry.json` | `min_inclusive` `2.6.0`, `max_exclusive` `3.0.0` — the registry admits the AART that wrote it |
| `LA-R-40` | The removed values were inert | flag | A | `registry scaffold mcp atlassian --yes` under a `main` wheel and under the branch wheel, then `diff -r` the two workspaces | byte-identical trees. `RS-02` deletes values nothing read; a difference here would mean something did |
| `LA-R-41` | The written registry is accepted | flag | A | `registry validate --source .` against the workspace the branch wheel authored | `passed` — the window it declared is one it satisfies |

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
| `LA-S-17` | A local repository offered as an upstream | flag | D | `source add --kind source-git` and `--kind registry-git` with `file:///…` and with a plain absolute path to a real Git repository | refused, and the refusal says which part of the location is unacceptable |
| `LA-S-18` | A source tree containing a symlink | flag | D | `source add --kind source-local` on a tree with one symlink under an artifact payload | refused, naming the path and the reason; nothing is added |
| `LA-S-14` | **An unreadable registry marker is refused** | flag | D | `source add` a local source whose root `aart-registry.json` is missing a required field, is not JSON, and is a directory | each is refused, naming the file and what the parser could not read; nothing is configured |
| `LA-S-15` | The same break upstream, at sync | flag | D | subscribe while healthy, break the marker, `source sync` | the sync fails and the working subscription survives — last-known-good snapshot, `status` still `current` |
| `LA-S-16` | A source with no marker is unaffected | flag | D | `source add` the same source with no `aart-registry.json` | added and published; the refusal is about a marker that is there, not one that is absent |
| `LA-S-11` | **The project is still readable after the last subscription goes** | flag | D | install, `source remove --alias … --yes`, then `marketplace status` | exits `0` and reports the installation as `source-unavailable`; the installed file is still on disk |
| `LA-S-12` | Fetching still refuses without a source | flag | D | `marketplace install`, `update`, `list`, `setup` after the same removal | each refuses with `no-source-configured` and names how to configure one |
| `LA-S-13` | The lifecycle closes without a source | flag | D | `marketplace uninstall <coordinate>` using the coordinate `LA-S-11` printed | review, then apply; the installed file is gone and the next `status` selects nothing |

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
| `LA-U-36` | The review that says it changes nothing | flag | D | after `source add`, run `marketplace install <coordinate>` **without** `--yes`, then count files under the durable object store | the store holds what it held before, or the help text says what a review writes. `LA-U-31`..`LA-U-35` are taken by run documents — see `LAF-87` |
| `LA-U-37` | The store watched across install and uninstall | flag | D | record object files, shard directory mtimes, object birth times, the reference index and `locks/` before a review, after `install --yes` and after `uninstall --yes` | every deposit has a reference, or something can remove the ones that do not |
| `LA-U-38` | An origin withdrawn | flag | D | `source add`, one command that resolves an artifact, then `source remove --yes`; count what is left under the object store | the content of a removed source is gone, or a command can say it is still there and remove it |
| `LA-U-39` | The managed block, four ways | flag | D | install and uninstall a `memory` artifact at project scope in four states: no instruction file; an unowned file present; an unowned file with `--force`; and a forced install whose file the operator then edits by hand | each uninstall removes the block and nothing else — the file AART made goes, the file it did not stays with the operator's bytes intact |
| `LA-U-40` | The config merge, three ways | flag | D | install and uninstall `mcp` artifacts whose effect is `merge-json`: one alone; two, uninstalled in install order and in reverse; and one into a `.mcp.json` the operator wrote first | the file AART created does not outlive the last entry in it; the operator's own entries survive; the order of uninstall does not change the result |
| `LA-U-31` | **The created merge file goes with its last identity** | flag | D | clean repo; install one `mcp`; uninstall; `git status --porcelain` | `.mcp.json` is gone and the repository is clean, not `{"mcpServers":{}}` left untracked |
| `LA-U-32` | The same for a list merge | flag | D | clean repo; install one `hook`; uninstall | `.claude/settings.json` is gone, not `{"hooks":{"PreToolUse":[]}}` |
| `LA-U-33` | **The operator's own file is never removed** | flag | D | commit `.mcp.json` as `{"mcpServers":{}}` **before** installing; install; uninstall | the file survives byte-identical; `git status` clean because nothing changed, not because nothing is there |
| `LA-U-34` | A created file holding anything else is kept | flag | D | install; add a key AART did not write; uninstall | the file survives with that key intact and the container empty |
| `LA-U-35` | **Reclamation depends on uninstall order** | flag | D | install two `mcp` artifacts separately, uninstall in install order, then repeat in reverse | install order: the file stays; reverse order: it goes. Record the asymmetry — the effect that created the file is the only one entitled to remove it |

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
| `LA-M-08` | Docker step sees the user's docker config | flag | D | run a `docker.pull@1` recipe for a **public** image with `HOME` set; read the receipt | pull succeeds and the run completes; `RS-12`'s widened environment breaks nothing that worked |
| `LA-M-09` | A private image without credentials says why | flag | D | same recipe against an image in a namespace this machine cannot read, `DOCKER_CONFIG` pointed at an empty directory | the recorded detail carries docker's own words — `pull access denied` — not a bare `docker pull failed` |
| `LA-M-10` | A private image with credentials | flag | H | credentials supplied by Michal; the company base image | the pull authenticates. **Human-gated**: the agent supplies no credentials |
| `LA-M-11` | Rollback removes the tag from the daemon that built it | flag | H | `docker.build@1` under a non-default docker context, then rollback | the tag is removed from the context that holds it. **Human-gated**: needs a second daemon or context on the machine |
| `LA-M-12` | A fresh record verifies its own rollback line | flag | D | real `marketplace setup`, then `receipt verify` | the `rollback-command-runs` claim is `true`; the recorded command is the one this executable accepts |
| `LA-M-13` | A record written before the undo command | flag | D | set the record's `rollback_command` to the pre-`2.6.0` sentence, then `receipt verify` | the claim is `false`, names the command that works today, and the record file's digest is unchanged |
| `LA-M-14` | The earlier executable says nothing | flag | D | the same aged record, `receipt verify` from the `main` wheel | no such claim; `true=3, false=0` where the fix reports `true=3, false=1` |
| `LA-M-15` | The advice the claim gives works | flag | D | run the command the claim names | the managed block and the file the run created are gone |

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

### `LA-U-27a` — the scope selector, after `LAF-64`

Added when `LAF-64` closed. The selector is the one screen whose plumbing changed, and the change is
invisible from outside unless these three still hold:

1. At the **Installation scope** screen, Enter on *Project* advances with Project selected, and
   Enter on *User* advances with User selected.
2. Backspace at that screen goes back a stage and does **not** cancel the wizard.
3. `q` at that screen quits, and nothing is installed.

Any of the three answering "cancel" where it used to answer "chosen" is the defect `LAF-64`
described, arriving from the other side.

---

## Recording rules

- Result per scenario goes in [PROGRESS-live-acceptance.md](PROGRESS-live-acceptance.md) as
  `pass` / `fail` / `blocked` / `deferred`, with the finding ID when not `pass`.
- Do not paste raw prose output into the record. Phase M touches real credentials and the redaction
  paths are exactly what this run is exercising (design §7).
- `AART_DEBUG=1` only when capturing a traceback for a finding; never as the default.
