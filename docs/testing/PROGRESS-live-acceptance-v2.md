# Live acceptance v2 — progress

Second live acceptance run, against the released `2.1.0` executable and the published registries.
Methodology unchanged: [DESIGN-live-acceptance-v1.md](DESIGN-live-acceptance-v1.md) governs, and
[the v1 record](PROGRESS-live-acceptance.md) is the prior run this one is read against — it is never
rewritten.

**Status: agent scope complete.** Curses and credential passes remain human-gated (design §10).
Analysis and the composed response are in
[DESIGN-subscription-identity-binding.md](../design/DESIGN-subscription-identity-binding.md) and
[PLAN-subscription-identity-binding.md](../plan/PLAN-subscription-identity-binding.md).

## What makes this run different from v1

v1 ran against `1.4.0` and authored both registries from empty. Its residue set produced the `2.0.0`
canonical remediation and the `2.1.0` subscription lifecycle. This run therefore has two jobs, and
they are deliberately not separated into two documents:

1. **Regression under the same stressors.** The v1 residues that the remediation claimed to answer
   are re-applied. A residue that returns is worth more than one that never existed.
2. **New stressors against the new structure.** Everything the remediation *added* — one canonical
   command family, one reconciliation plan, artifact dependencies, and now a full subscription
   lifecycle — is itself a new surface with its own edges. `LAS-31`+ are registered below.

Registries and consumer are no longer authored from empty: they are published content on the `2.0.0`
contract, which is the state a real user meets.

## Run header

Everything in this record is executed against this build; if it changes, the run restarts
(design §3).

| Field | Value |
|---|---|
| AART tag | `v2.1.0` |
| AART commit | `3aff63dbda1039a441e4a6a3561bfd98fd548824` |
| Wheel | `agent_artifacts-2.1.0-py3-none-any.whl` (473 423 bytes), **downloaded from the GitHub release** |
| Wheel sha256 | `a2edb0dc…4f47e` (release asset) |
| `aart --version` | `agent-artifacts 2.1.0` |
| Test venv | `$LA2_ROOT/venv` — only `agent-artifacts`, `pip`, `setuptools` |
| Platform | macOS (darwin 25.2.0), Python 3.11.0 |
| Registry A | `M1F1/agent-artifacts-registry` @ `7c7dd31` (published, `2.0.0` contract) |
| Registry B | `M1F1/agent-artifacts-registry-2` (published, `2.0.0` contract) |
| Local fixture registry | `$LA2_WORK/local-registry` — authored during the run, identity mutated on purpose |
| Sandbox root | `$LA2_ROOT` = `~/.aart-live-acceptance-2` |
| Prior run sandbox | `~/.aart-live-acceptance` (v1, untouched) |
| Started / last updated | 2026-08-13 |

```sh
export LA2_ROOT="$HOME/.aart-live-acceptance-2"
export LA2_HOME="$LA2_ROOT/home"
export LA2_WORK="$LA2_ROOT/work"
```

## New stressors registered for this run

The v1 register (`LAS-01`..`LAS-30`) carries over unchanged. Appended here, append-only:

| ID | Stressor | Why it is plausible |
|---|---|---|
| `LAS-31` | A data root written by the previous release is used by this one, and back | every real upgrade |
| `LAS-32` | A subscription is ended while its artifacts are still installed | the user changes their mind |
| `LAS-33` | An origin re-declares its identity at an unchanged origin and ref | v1's `LAF-28`, now with an exit |
| `LAS-34` | Two AART processes act on one data root at once | an agent and a human, or two agents |
| `LAS-35` | An operation is interrupted between its two durable writes | laptop lid, `^C`, OOM |
| `LAS-36` | The default registry is the alias that gets removed | the pointer outlives its target |
| `LAS-37` | A durable manifest outlives the source it came from | consequence of `LAS-32` |
| `LAS-38` | Review and finalize see different upstream state | slow human, fast upstream |
| `LAS-39` | The object store is read-only | shared machines, CI images |
| `LAS-40` | An artifact declares a dependency that lives in another registry | federation meets `requires` |

## Phase status

| Phase | WPs | Status | Note |
|---|---|---|---|
| LA2-0 harness | 0.1 – 0.3 | **complete** | 3/3 pass; 2 findings, one of them from the coverage ledger itself |
| LA2-S subscription lifecycle | S1 – S9 | **complete** | 9 scenarios; the new commands work, and three residues sit behind them |
| LA2-U consumer regression | U1 – U5 | **complete** | 3 of v1's 4 consumer majors are fixed; 1 persists; 1 root-caused |
| LA2-X stressors | X1 – X6 | **complete** | concurrency, interruption, read-only, upgrade, federation |
| LA2-T TUI text front-end | T1 – T2 | **complete** | both new Sources actions reached and finalized over a pty |
| LA2-H human-gated | — | **not started** | curses pass and MCP credential pass remain Michal's (design §10) |

## Scenario results

| ID | Result | Finding | Note |
|---|---|---|---|
| `LA2-0-01` | pass | — | the **release asset** wheel installs into a clean venv, reports `2.1.0`, embeds commit `3aff63d`, pulls in no non-stdlib dependency |
| `LA2-0-02` | **fail** | `LAF-29` | `build_parser()` yields **6 top-level / 33 leaves**. Diffed against v1's 49: the `2.0.0` removals are all accounted for except one — **`source doctor` is gone and no release document says so**, while `tui_sources.py` still tells the operator to run it |
| `LA2-0-03` | pass | — | `HOME` override isolates completely: no path under the real `~` is read or written, and the first refusal a new operator meets (`no-source-configured`) names `aart source add --help`, which parses |
| `LA2-0-04` | pass | `LAF-30` | the release wheel and a local `make wheel` at the tagged commit are **content-identical in all 163 members** and differ only in zip timestamps, so the published artifact cannot be verified by rebuilding |
| `LA2-S-01` | pass | — | both published registries subscribe cleanly; `la-a` takes the default-registry flag |
| `LA2-S-02` | pass | — | `source add` of an already-configured alias refuses and names `sync`, `resubscribe`, **and** `remove` — the v1 dead end (`LAF-28`) is closed on the alias path |
| `LA2-S-03` | pass | — | the same origin under a new alias refuses and names the alias that holds it, plus the ref escape hatch |
| `LA2-S-04` | pass | — | `source remove` review states both effects (forget the alias, clear the default), states what it keeps, and writes nothing; `--yes` then clears the entry, the default, and exactly one origin directory |
| `LA2-S-05` | pass | — | after removal the installed artifacts are untouched on disk and `status` reports them `source-unavailable` — the designed outcome |
| `LA2-S-06` | **fail** | `LAF-31` | …but **they cannot be uninstalled**. `marketplace uninstall` returns `artifact-not-found` with empty remediation, and `source remove`'s own review names "uninstalled" as a valid exit. Workaround: re-add the source, then uninstall |
| `LA2-S-07` | **fail** | `LAF-32` | the identity refusal from `source sync` prints its message but **not its remediation** in text mode; the `aart source resubscribe` line is present in `--json` only. The whole `SL-5` remediation is invisible on the likeliest path |
| `LA2-S-08` | pass | — | `source resubscribe` review renders both identities, both revisions, and both snapshot digests, writes nothing, and `--yes` adopts. Resubscribing an unchanged identity is refused and names `sync` |
| `LA2-S-09` | **fail** | `LAF-33`, `LAF-34` | adoption succeeds and **orphans every installation made under the previous identity**: permanently `source-unavailable`, `update` reports `selected canonical installations were not found`, and the review promises `update-available`/`removed-upstream` instead. Separately, running review and `--yes` as two commands adopts whatever is upstream at the second call, not the transition that was read |
| `LA2-U-01` | pass | — | 44-artifact federated union across both published registries; install of two `la-a` artifacts into a fresh consumer, `status: current` |
| `LA2-U-02` | **pass (v1 fixed)** | — | v1 `LAF-20`: bare `marketplace update` with no coordinate no longer crashes; it reconciles the whole scope and returns a well-formed envelope |
| `LA2-U-03` | **pass (v1 fixed)** | — | v1 `LAF-25`: after an upstream payload change and `source sync`, `status` reports `update-available`, and `update` pulls it |
| `LA2-U-04` | **pass (v1 fixed)** | — | v1 `LAF-26`: an artifact deleted upstream reports `removed-upstream`, and `update --prune` removes it from disk and from the manifest |
| `LA2-U-05` | **fail (v1 persists)** | `LAF-17` | teardown still litters: after uninstalling everything, `.agent-artifacts/manifest.json`, `.agent-artifacts/state.lock` and the empty `.claude/skills` survive, and `git status --porcelain` reports `?? .agent-artifacts/` on a repo that was clean before |
| `LA2-U-06` | **fail (v1 root-caused)** | `LAF-35` | v1 `LAF-16` reproduced and **explained**: two review-only runs two seconds apart produce different `plan_digest`/`review_digest` with every other field identical. The input is `source_age_seconds`, carried into `_plan_review_value` — the consent digest is a clock |
| `LA2-X-01` | pass | — | `LAS-34`: two `source sync` of one alias in parallel both report `unchanged`; no corruption |
| `LA2-X-02` | pass (residue) | `LAF-31` | `LAS-34`: `marketplace install` racing `source remove` — the removal wins, the install fails cleanly having written nothing, and reports the same misleading `artifact-not-found` |
| `LA2-X-03` | pass (residue) | `LAF-36` | `LAS-35`: a `SIGKILL`ed `source add` leaves `sync.lock`; every source operation is then refused with `source synchronization is already running` for the full 300 s stale window. It **does** self-heal, and the retry then succeeds — but nothing says the holder is dead, nothing reports the age, and the command that used to repair source state was removed (`LAF-29`) |
| `LA2-X-04` | **pass** | — | `LAS-35`: the removal ordering invariant holds. With the store directory deleted and the configuration intact, `source health` reports `missing; never synchronized` and `source sync` republishes it — a half-applied removal is repairable, which is exactly what the ordering was chosen for |
| `LA2-X-05` | **pass** | — | `LAS-31`: a `2.0.0` data root is read by `2.1.0` with no migration (`list`, `health`, `status`, `sync` all clean), and `2.0.0` reads it back afterwards. `compatibility-v9.md`'s downgrade claim holds live |
| `LA2-X-06` | pass (residue) | `LAF-40` | `LAS-39`: a read-only object store fails before touching the project — typed, names the exact path, writes nothing — but the message is a raw `[Errno 13]` string with empty remediation |
| `LA2-X-07` | **fail** | `LAF-37` | a registry whose `aart-registry.json` and `aart-source.json` declare **different** identities is refused by `registry validate --strict --frozen` (`registry and source identities differ`) and **accepted by the consumer**: `source sync` publishes it and `marketplace install` installs from it. The `source_id` the entire identity model is anchored on is the one no consumer-side gate checks |
| `LA2-X-08` | pass (question) | `LAF-38` | `LAS-40`: `requires` is intra-registry only — `registry build` refuses `skill/la-probe requires missing skill/using-residues` when the dependency lives in another configured registry. Defensible, and nowhere documented, while the marketplace federates freely at consumption |
| `LA2-T-01` | **pass** | — | over a pty with `TERM=dumb`, the Sources stage offers `a/s/i/r`, and `i` walks review → `[y/N]` → `Sources: loc now follows la-local-registry-v5`, rendering the same review as flag mode |
| `LA2-T-02` | **pass** | — | `r` walks the removal review and finalizes; the alias disappears from the stage and from `source list` in the same session |

Legend: `pass` · `fail` (finding filed) · `blocked` · `deferred`.

## Findings — residues

**Record, do not fix** (design §8). Numbering continues from v1.

| ID | Sev | Scenario | Stressor | Component | Symptom | Reproduction | Blocks |
|---|---|---|---|---|---|---|---|
| `LAF-33` | major | `LA2-S-09` | `LAS-33` | `installation/model.SourceEvidence.declared_id` ↔ `source resubscribe` | **Adoption orphans everything installed under the old identity, permanently.** Each installation record pins `source.declared_id`; `resubscribe` rebinds the configuration and the snapshot store but nothing rebinds the records. After adoption `status` reports `source-unavailable` forever, `update` reports `selected canonical installations were not found`, and the resubscription review explicitly promises the opposite ("installed artifacts … surface as update-available or removed-upstream through the normal reconciliation"). Only uninstall+reinstall recovers. **Criticality:** one string changes upstream and every installation from that source stops being reconciled | subscribe to a local registry, install one artifact, change `source_id` upstream, `source resubscribe --yes`, then `marketplace status` | nothing — but it makes the `2.1.0` feature answer the subscription and not the installations |
| `LAF-31` | major | `LA2-S-06`, `LA2-X-02` | `LAS-32`, `LAS-37` | `commands.marketplace.uninstall` ↔ source resolution | **An installed artifact cannot be uninstalled once its source subscription is gone.** `marketplace uninstall` resolves through the source before it removes files it already recorded, so it returns `artifact-not-found: artifact <name> in source <alias> was not found` with empty remediation, exit `1`. `source remove`'s own review names uninstalling as one of the two valid exits. Uninstall needs the manifest, not the source | install from a source, `source remove --alias <a> --yes`, then `marketplace uninstall <a>/<coord> --yes` | nothing — re-adding the source restores the path |
| `LAF-35` | major | `LA2-U-06` | `LAS-24` | `installation/model._plan_review_value` | **The consent digest is a clock.** `_plan_review_value` includes `source_age_seconds`, so `plan_digest` — and the `review_digest` derived from it — changes every second on a completely unchanged workspace. Two review-only runs two seconds apart differ in exactly that one field's consequence; back-to-back runs inside one second agree. This is v1's `LAF-16`, whose input the v1 run deliberately did not chase. The review→finalize contract cannot bind a decision across two invocations, which is the workflow the review text prescribes | `marketplace install <coord> --json` twice, two seconds apart, and diff: only `review_digest` and `plan_digest` differ | nothing directly; it is the mechanism behind `LAF-34` |
| `LAF-34` | major | `LA2-S-09` | `LAS-38` | `commands.source._resubscribe` | **The transition guard binds within one process only.** `SourceIdentityTransition` is re-validated at finalize, but the CLI recomputes the review inside the same `--yes` invocation, so a human who reviews in one command and finalizes in another adopts whatever the origin declares at the second call. The review says "re-run it with `--yes` to adopt this exact identity change"; re-running adopts a different one. It is at least reported afterwards (`la-local-registry -> la-local-registry-v3`) | `source resubscribe --alias loc`, change `source_id` again upstream, `source resubscribe --alias loc --yes` → adopts the newer identity without a word | nothing |
| `LAF-37` | major | `LA2-X-07` | `LAS-33` | source snapshot compilation ↔ `registry validate` | **The consumer does not check the identity agreement the maintainer gate enforces.** A registry whose `aart-registry.json` `registry_id` and `aart-source.json` `source_id` disagree fails `registry validate --strict --frozen` with `registry and source identities differ`, and syncs, publishes, and installs perfectly. The value the whole identity model — including `resubscribe` — pins is the one no consumer-side gate validates. Same shape as v1's `LAF-24`/`LAF-27`, inverted: there publication was laxer than consumption, here consumption is laxer than publication | edit `source_id` in a registry without editing `registry_id`; `registry validate` fails; `source sync` publishes; `marketplace install` installs | nothing |
| `LAF-32` | major | `LA2-S-07` | `LAS-33` | `commands.source` text renderer | **Text mode drops the remediation of per-source diagnostics.** `aart source sync` on a changed identity prints `error: resolved source changed its declared source identity` and stops; the `aart source resubscribe --alias <a>` line that `2.1.0` exists to deliver appears only under `--json`. The renderer that most operators use is the one that hides the fix | `aart source sync --alias <a>` against a re-identified origin, then the same with `--json` | nothing — but it silently voids `SL-5` on the default path |
| `LAF-29` | major | `LA2-0-02` | `LAS-29` | `cli.build_parser` ↔ `tui_sources._availability_reason` ↔ release documents | **`source doctor` was removed in `2.0.0` and no release document records it.** `compatibility-v8.md`'s removed-command table lists nine top-level verbs and not this one, so a `1.x` user reading the migration finds nothing. Meanwhile `tui_sources.py:389` still renders `source state is invalid; run source doctor before enabling it` in the Sources stage. `tests/source_remediation_test.py` cannot catch it: that guard parses `Diagnostic.remediation`, and this string is a display reason | `aart source doctor` → `invalid choice`; `grep -n "source doctor" agent_artifacts/` → `tui_sources.py:389` | nothing; it removes the only repair route named by `LAF-36` |
| `LAF-36` | minor | `LA2-X-03` | `LAS-35` | `io.source_store` lock reporting | A `SIGKILL`ed source operation leaves `sync.lock`, and for the full 300 s stale window every source operation is refused with `source synchronization is already running` / `retry after the active synchronization completes`. Nothing is running; the holder's pid is dead and recorded in `owner.json`. The lock **does** self-heal and the retry then succeeds, so the defect is the reporting: no age, no "the holder appears to have crashed", no override, and no repair command since `source doctor` was removed | start `source add` against a large registry, `kill -9` it after 1 s, retry → blocked; retry after 300 s → succeeds | nothing for 300 s, everything for 300 s |
| `LAF-40` | minor | `LA2-X-06` | `LAS-39` | `marketplace install` object-store preparation | A read-only object store fails with `cannot prepare artifact object store: [Errno 13] Permission denied: …/objects/sha256` — correctly typed, correctly before any project write, and with **empty remediation** and a raw errno string. Same family as v1's `LAF-19`: the failure names a path and not a next step | `chmod -w <data-root>/objects`, then install an artifact whose object is not yet materialized | nothing |
| `LAF-30` | question | `LA2-0-04` | `LAS-02` | `scripts/build_wheel.py` | The published wheel is **content-reproducible but not byte-reproducible**: rebuilding at the tagged commit yields all 163 members byte-identical and a different archive digest, because zip entry timestamps are build time. A user who verifies the release by rebuilding gets a mismatch and no explanation. `SOURCE_DATE_EPOCH` would settle it; whether byte-reproducibility is a goal is the decision | `gh release download v2.1.0`, `make wheel`, compare `shasum` (differs) then compare members (identical) | nothing |
| `LAF-38` | question | `LA2-X-08` | `LAS-40` | `registry build` dependency resolution | `requires` resolves **within one registry only**. An artifact that depends on one published in another configured registry cannot be built: `skill/la-probe requires missing skill/using-residues`. The consumer federates across sources freely, so the maintainer-side restriction is invisible until publication fails, and no document states it. Registry B works around it by vendoring the kernel into the same registry | declare `requires` naming an artifact that exists only in another registry, `registry build` | authoring across registries |
| `LAF-39` | question | `LA2-S-01` | `LAS-11` | `cli` source subcommand contract | `source add` is the only lifecycle verb that mutates without `--yes`. `sync`, `resubscribe`, and `remove` all review first; `add` writes configuration and publishes a snapshot on the first invocation, documented in its own help ("No interactive confirmation is required because all origin/default choices are explicit command arguments"). Defensible — and it means the first command a new operator runs is the one that does not show them a review | `aart source add --help` → no `--yes`; every sibling has one | nothing |
| `LAF-17` | minor | `LA2-U-05` | `LAS-10` | `marketplace uninstall` teardown | **Unchanged from v1.** Uninstalling everything leaves `.agent-artifacts/manifest.json`, `.agent-artifacts/state.lock`, and the empty profile directories, so `git status --porcelain` reports `?? .agent-artifacts/` on a repo that was clean before install. `state-migration.lock` is gone, so the litter is smaller; the assertion still fails | install into a clean checkout, uninstall everything, `git status --porcelain` | fails the teardown assertion |

### Fixed since v1 — verified, not assumed

| v1 finding | v1 symptom | v2 result |
|---|---|---|
| `LAF-28` critical | a re-identified origin made a subscription terminal | **fixed** — `LA2-S-02`, `LA2-S-08`; recovery uses shipped commands only |
| `LAF-20` major | bare `marketplace update` crashed with a raw traceback | **fixed** — `LA2-U-02`; reconciles the scope, well-formed envelope |
| `LAF-25` major | `status` never reported that an update was available | **fixed** — `LA2-U-03`; reports `update-available` |
| `LAF-26` major | `update --prune` removed nothing | **fixed** — `LA2-U-04`; removes from disk and manifest, and `removed-upstream` is now a reported status |
| `LAF-16` major | review digest unstable, input unidentified | **root-caused, not fixed** — `LAF-35` names the input |
| `LAF-17` minor | teardown litter | **persists** |

## Attractors

Four, and they are what the composed response answers. Each is one end state reached from unrelated
stressors — which is a much stronger signal than the count of findings behind it.

### A1 — "the subscription is gone" is always reported as "the artifact was not found"

`LAF-31` (subscription removed), `LA2-X-02` (subscription removed underneath a running install), and
v1's `LAF-19` (cold cache, nothing to resolve from) all arrive at
`artifact-not-found: artifact <name> in source <alias> was not found`, with empty remediation. The
artifact name is the one part of the request that was never wrong. Resolution reports the leaf it
failed to reach instead of the subscription it failed to resolve through.

### A2 — identity is pinned in four places and only two of them are maintained

| Where | What it pins | Maintained by |
|---|---|---|
| `config.json` | alias → origin, ref | `add`, `remove` |
| managed snapshot store | origin → declared identity | `sync`, `resubscribe`, `remove` |
| each installation record | `declared_id` at install time | **nothing** (`LAF-33`) |
| the registry's own two files | `registry_id` vs `source_id` | `registry validate` only, never the consumer (`LAF-37`) |

`2.1.0` closed the first two and left the other two. That is why the new commands feel complete from
the source side and incomplete from the project side.

### A3 — remediation exists in the envelope but not on the path the operator takes

`LAF-32` (text renderer drops it), `LAF-29` (the named command no longer exists), `LAF-40` and
v1 `LAF-19` (empty remediation), `LAF-36` (a message that states the wrong cause). `SL-5` proved
every remediation *string* names a real command; nothing proves the string is *shown*, or that a
non-`Diagnostic` message is one at all.

### A4 — review-first is a property of a process, not of a decision

`LAF-35` (the digest is a clock) and `LAF-34` (the transition is only rechecked in-process) are the
same defect seen from the consumer and the source side. Both mean the same thing: **the artefact a
human reads cannot be carried to the command that acts on it.** Every guard is real inside one
invocation and absent between two, which is exactly the workflow the review text asks for.

## Criticality

`LAF-33` is the disproportionate one. The stressor is a single string changing in an upstream file.
The residue is that every installation made from that source stops being reconciled — permanently,
silently, and while the tool reports `ok: true`. It is also the one residue that lands squarely on
the feature this release shipped, which is the most useful place for a residue to land.

## The three `question` findings — decided 2026-08-14

`question` means "defensible but undocumented; needs a decision, not a fix" (design §8). All three
were decided by the maintainer; the reasoning is in
[DESIGN-subscription-identity-binding.md](../design/DESIGN-subscription-identity-binding.md) §7 and
the work is planned, so none of them stays open in this ledger.

| Finding | Decision | Lands as |
|---|---|---|
| `LAF-30` byte-reproducible wheel | build it reproducibly — verifiability outweighs build freedom | `SI-8`, `2.2.0` |
| `LAF-38` cross-registry `requires` | keep it intra-registry, deliberately, and say so in three places | `SI-9`, `2.2.0` |
| `LAF-39` `source add` without a review | give it one — but it breaks every existing caller, so it is a major | `SI-10`, `3.0.0`; help-text half in `2.2.0` |

## Positive results worth keeping

- The removal ordering invariant is real (`LA2-X-04`): a store deleted under an intact configuration
  is repaired by `source sync`, exactly as `DESIGN-source-subscription-lifecycle.md` argued.
- `2.0.0` ↔ `2.1.0` data-root compatibility holds in both directions with no migration
  (`LA2-X-05`), which is `compatibility-v9.md` verified rather than asserted.
- Concurrency is safe where it was tested (`LA2-X-01`, `LA2-X-02`): no corruption, no partial write,
  the loser fails cleanly.
- Both new Sources actions reach the text front-end and render the same review as flag mode
  (`LA2-T-01`, `LA2-T-02`).
- Three of v1's four consumer majors are genuinely fixed, verified by re-applying the original
  stressors rather than by reading the changelog.

## Not executed — human-gated

Per design §10, and unchanged from v1: the curses pass (both roles) and the MCP credential pass are
Michal's. Nothing in this run typed a credential or drove curses.
