# Live acceptance — the readable receipt (`RR-9`)

`2.6.0`, contract v14, walked on a real machine with a real Docker daemon and a real Keychain.

**No patched executable.** `2.5.0`'s run needed a patch to observe anything at all (`LAF-51`), and
[`DESIGN-readable-receipt.md`](../design/DESIGN-readable-receipt.md) §6 criterion 7 makes not repeating
that a criterion rather than a hope. Everything below runs the wheel built from the committed tree.

## Run root

| | |
|---|---|
| Executable | `agent_artifacts-2.6.0-py3-none-any.whl`, installed with `pip --no-deps` into a fresh venv |
| `HOME` | `~/.aart-live-acceptance-4/home` — isolated, so the operator's own data root is untouched |
| Project | `~/.aart-live-acceptance-4/work` |
| Docker | server `29.5.2` |
| Registry A | `github.com/M1F1/agent-artifacts-registry` — three setup-bearing packages |
| Registry B | `github.com/M1F1/agent-artifacts-registry-2` — none, which is what makes it the refusal case |
| Consumer | `github.com/M1F1/agent-artifacts-live-acceptance-project` — eleven installations |

## Scenario map

| # | Scenario | Registry | Criterion | Status |
|---|---|---|---|---|
| 1 | `marketplace setup` at a terminal prints effects, capabilities and the manual alternative before approval | A | §6.1 | **pass** |
| 2 | `receipt show` prints the same account afterwards | A | §6.1 | **pass** |
| 3 | `receipt verify` reports a Keychain item stored by an unattended run as present and empty | A | §6.2 | **pass** |
| 4 | `receipt undo` without `--yes` changes nothing and prints what it would reverse | A | §6.4 | **pass** |
| 5 | `receipt undo --yes` reverses what it said it would and keeps what it said it would | A | §6.3 | **partial** — no published artifact builds an image, so the `preexisting` tag half is unreachable (`LAF-67`) |
| 6 | `receipt verify` reports an orphaned run directory and does not remove it | A | §6.5 | **fail** — `LAF-66` |
| 7 | A build failing on its last instruction reports that instruction and its exit code | A | §6.6 | **not walked** — `LAF-67` |
| 8 | The three actions refuse cleanly against an installation with no setup record | B | `RR-1` | **pass** |
| 9 | The consumer repository still reports eleven `current` and a clean `git diff` | consumer | `RR-9` | **pass** |

## Findings

Recorded live, numbered from `LAF-65`, and clustered at the end. Nothing is fixed mid-run.

| ID | Scenario | One line |
|---|---|---|
| `LAF-65` | 2 | The receipt's own `rollback` line says *no command reverses a completed setup* — written by the release that ships one |
| `LAF-66` | 6 | The orphan-run-directory probe scans the project root; runs live under the data root, so the claim answers `true` without ever looking |
| `LAF-67` | 5, 7 | No published artifact uses `docker.build@1`, so two of the design's seven acceptance criteria cannot be walked against published content at all |
| `LAF-68` | 9 | The consumer repository's `main` still pins AART `2.0.0`; the `2.5.0` pin move is an open, unmerged PR, so its CI has never exercised `2.5.0` |
| `LAF-69` | 6 | `DOC009` catches a document that calls a closed finding open, and not the reverse — so the register moving `LAF-61` back to `open` left two release documents claiming `visible` and `docs-check` stayed green |

### `LAF-65` — the receipt tells the operator there is no command, and there is

`receipt show` on a record written by `2.6.0`, minutes after `2.6.0` shipped `receipt undo`:

```text
rollback  no command reverses a completed setup; undo mcp/github-docker in claude
          (project) from the recorded receipt, then re-run setup
```

The sentence was true when it was written into the recipe path and is false now. It is not a stale
document — it is a field this release *writes*, so every record created from here on carries a
statement the same executable contradicts. An operator who reads the receipt rather than the release
notes is told to do by hand what one command does.

### `LAF-66` — the orphan probe looks where runs are not

`orphan_run_directories` scans `<project_root>/.agent-artifacts/setup-runs/`
(`setup_verify_probes.py:110`). Real runs are created under `run_root`, and
`setup_engine/application.py:457` passes `run_root=location.data_root`. The two are never the same
directory.

Measured, with a real record and a real leftover directory:

| Orphan placed at | `no-orphan-run-directory` reports |
|---|---|
| `<project>/.agent-artifacts/setup-runs/<hash16>-killed42` — where the probe looks | `false`, named with its full path, left in place |
| `<data_root>/.agent-artifacts/setup-runs/<hash16>-killed` — where runs actually are | **`true`, "no working copy was left behind"** |

So `LAF-61` is not `visible` after all. The claim reports a confident `true` in every scope without
looking at the directory it is about — which is the precise failure the three-status design was
written to prevent: *a verifier that quietly passes what it cannot see is worse than no verifier*.
This one passes what it never looked for.

**It also invalidates scenario 6's first result.** The orphan that `verify` found was one this run had
planted where the probe looks. That evidence was self-confirming, and finding out why is the only
reason the second measurement was taken. A scenario that constructs its own subject proves the
construction.

### `LAF-67` — the acceptance criteria assume an artifact the registry does not publish

All three setup-bearing packages in the published Registry A — `mcp/github-docker`,
`mcp/github-enterprise-docker`, `mcp/postgres-docker` — declare
`[docker-pull, keychain, managed-file, network]`. None uses `docker.build@1`.

Design §6 criterion 3 wants an undo that *removes the image tag … and restores a `preexisting` tag's
original binding*, and criterion 6 wants *a build that fails on its last instruction*. Neither is
reachable from published content, because `2.5.0`'s build-context work was accepted against a local
fixture and nothing was ever published that uses it. The criteria were written against the code, not
against the catalog the run would have.

### `LAF-68` — the acceptance repository is two releases behind its own purpose

`main` of `agent-artifacts-live-acceptance-project` installs eleven artifacts and pins
`AART_VERSION: 2.0.0`. The move to `2.5.0` exists as open PR #1, raised and never merged. So the
repository whose job is to reconcile committed state against what the registries publish has never run
its reconcile on `2.5.0`, and the `2.6.0` pin move queues behind an unmerged one.

Reconciling it here with the `2.6.0` executable passes — eleven installations, every one `current`,
`ok: true`, and `git diff --exit-code` returning 0 — so nothing is *wrong* with the committed state.
What is missing is that CI ever proved it for the last release. Merging the pin is the maintainer's,
not this run's.

### `LAF-69` — the gate that only catches optimism in one direction

Found by using the register rather than by testing it. `LAF-66` moved `LAF-61` from `visible` to
`open`, and at that moment `compatibility-v14.md` and `release-checklist-v14.md` both still said
`visible`. `make docs-check` was run immediately afterwards and **passed**.

`DOC009` fails a document that lists as *shipped open* a finding the register records as `closed` —
a document being pessimistic about something already fixed. The reverse is not checked: a document
may claim `closed` or `visible` for a finding the register records as `open`, and nothing objects.

That is the more dangerous direction. The first is a stale worry; the second is a claim of safety
that is not there — precisely the shape of `LAF-66` one level up, a check that answers confidently
about a state it does not inspect. The register was built so that closure is a lookup rather than
prose, and the lookup is enforced in the one direction that cannot mislead an operator.

The two release documents were corrected by hand, which is the evidence that the gate did not do it.
`RR-7`'s own claim — *four rules, each with a test that makes it fail* — is true and insufficient:
every rule can be made to fail, and one of them fails at only half the disagreements it is about.

Not fixed in this run. Fixing it means `DOC009` reading a disposition claim out of prose, which is
the thing the register exists to stop documents doing, so the fix is a design question rather than a
predicate change.

## Evidence

### Scenario 1 — the review prints where the decision is made

`marketplace setup … --authorize-untrusted-source`, no `--yes`, no `--json`, at a terminal:

```text
Setup review: mcp/github-docker@claude (project)
  purpose         Pull the reviewed GitHub MCP image, keep its token in macOS Keychain, and expose
                  only a Keychain lookup to new shells.
  capabilities    keychain, filesystem, docker, network, process
  required tools  /usr/bin/security, docker
Manual alternative
  instructions  SETUP.md
  source        https://github.com/M1F1/agent-artifacts-registry/blob/c4727300…/SETUP.md
Effects
1. Pull a digest-pinned Docker image …
2. Store a secret in macOS Keychain …
3. Add a Keychain environment lookup …
4. Show a restart notice …
Setup: planned=1, failures=0
```

`LAF-54` closed live: the whole review, at the terminal, before approval. The count is last, after the
content it used to replace. And the planning refusal that preceded it printed the reason, the artifact
key and the manual route rather than `planned=0, failures=1` alone — `LAF-52`, closed live.

### Scenario 3 — the empty secret is detectable

The Keychain step ran with no terminal, and `marketplace setup` reported `configured`. The record
agrees with itself: step 2 carries `created: False, replaced: False`. `verify`:

```text
false: Keychain item service='aart/mcp/github-docker' account='default'
  claim   keychain-holds-value
  detail  the item is missing or empty; a Keychain step run without a terminal exits 0
          having stored nothing
Verification: true=3, false=1, unknown=0
```

Exit code `1`, measured directly rather than through a pipe — the first measurement read `tail`'s
status and was discarded. `LAF-55` closed live: the condition that reported success is now a false
claim with a non-zero exit.

### Scenario 4 — review-first, held by digests

`.zshrc` and the persisted record, hashed before and after an undo without `--yes`:

```text
before: 783722ba… 4bc726f2…
after:  783722ba… 4bc726f2…
```

Byte-identical. `--expect sha256:deadbeef` with `--yes` refuses and names both digests, exit `1`, and
`.zshrc` survives it. The correct digest applies: `.zshrc` is gone, the pre-existing image is
untouched, `Undo outcome: skipped — Setup rollback completed`.

### Scenario 8 — three absences, three sentences

Against Registry B, which publishes no setup-bearing package, all three actions refuse identically and
none crashes:

| Condition | Message |
|---|---|
| installed, no setup run | `registry-b/skill/grilling is installed and no setup run has been recorded for it` |
| never installed | `no installation of registry-b/skill/prototype in project scope for profile claude` |
| pointer's target gone | `points at setup record setup-d03bf30d… and that record is not present under the data root` |

Each carries remediation. This is what Registry B is in the plan for, and it is the one thing in this
run that went exactly as the plan said it would.

## Clusters

**D1 — the release contradicts itself in the artefact the operator reads.** `LAF-65`. The receipt is
the thing this whole release exists to make readable, and the field naming its own recovery route is
the one field that was not updated when the route was built. Nothing tests a record's prose against
the shipped command surface, which is the same shape as the remediation guard that already exists for
`Diagnostic` strings and does not reach here.

**D2 — a check whose question is narrower than the claim it licenses.** `LAF-66`, `LAF-69`. The
orphan probe answers *is there a leftover run directory* by looking in a directory runs are never
created in; `DOC009` answers *do the documents agree with the register* by checking one of the two
ways they can disagree. Neither reports a failure, and neither has looked. The design named this
failure mode in its own §3.2 and the implementation walked into it twice — the three-status
mechanism protects against *asking and failing*, not against *asking the wrong question
confidently*, and no mechanism at all protects a gate's predicate from being half its heading.

The two are one attractor: a check is written against the case its author had in mind, and the claim
it is then quoted for is the general one. `LAF-66` was found by planting a subject; `LAF-69` was
found by the register disagreeing with two documents while its own gate stayed green. Both were
found by use, not by test, which is the property that makes them a cluster rather than two bugs.

**D3 — acceptance that cannot reach the code it accepts.** `LAF-67`, `LAF-68`. Two criteria are
unwalkable because no published artifact uses the module they are about, and the repository that
reconciles published content has not moved past `2.0.0`. Both are the same defect: the acceptance
surface is assumed rather than derived, so a criterion can be written for content that does not exist
and nobody finds out until someone tries to walk it.

## Run log

Written live, in order, so the sequence that produced each finding is recoverable.

1. Built `agent_artifacts-2.6.0-py3-none-any.whl` from the committed tree; installed it with
   `pip install --no-deps` into a fresh venv under `~/.aart-live-acceptance-4/venv`. No patch, at any
   point — Design §6 criterion 7.
2. `HOME=~/.aart-live-acceptance-4/home`, project at `.../work`, so the operator's own data root is
   never read or written. Every command below ran with that `HOME`.
3. Registry A added and `mcp/github-docker` installed into project scope for profile `claude`.
   `marketplace setup` without `--yes` and without `--json`: scenario 1, **pass**, and `LAF-52` and
   `LAF-54` closed live in the same output.
4. `marketplace setup --yes --approve-setup-effects`, unattended. Docker pull and managed block
   succeeded; the Keychain step reported `configured` having stored nothing — the `LAF-55` condition,
   produced by running with no terminal rather than by typing a secret. **No secret was entered at
   any point in this run.**
5. `receipt show`: scenario 2, **pass** — and the `rollback` line in the printed record contradicts
   the executable printing it. `LAF-65` recorded, not fixed.
6. `receipt verify`: scenario 3, **pass**. `keychain-holds-value` is `false` with the detail that
   explains it, `true=3, false=1, unknown=0`, exit `1`. The first exit-code measurement read `tail`'s
   status through a pipe and was discarded; the re-measurement redirected to a file. No finding — a
   wrong measurement discarded before it was recorded is not a residue.
7. `receipt undo` without `--yes`, then with `--expect sha256:deadbeef`, then with the real digest:
   scenario 4, **pass**, held by hashes of `.zshrc` and the persisted record either side of each.
8. Scenario 5 walked as far as the catalog allows. The reversal half passes; the `preexisting` image
   tag half is unreachable because no published artifact uses `docker.build@1` — **partial**,
   `LAF-67`. Scenario 6 of the design's criteria (a build failing on its last instruction) is
   unreachable for the same reason and is reported **not walked** rather than dropped: it was walked
   against a local fixture during `RR-2B` and that is a unit test, not this run.
9. Orphan directory planted at `<project>/.agent-artifacts/setup-runs/` — `verify` found it. That
   result was self-confirming, because the placement was chosen by reading the probe. Re-planted at
   the real run root: `verify` answered `true: no working copy was left behind`. Scenario 6
   reclassified **fail**, `LAF-66` recorded, `LAF-61` moved back to `open` in the register.
10. Registry B, which publishes no setup-bearing package: all three actions refuse with three
    distinct sentences, each carrying remediation. Scenario 8, **pass**.
11. Consumer repository reconciled with the `2.6.0` executable: eleven installations, all `current`,
    `ok: true`, `git diff --exit-code` returns 0. Scenario 9, **pass** — and `main` still pins
    `2.0.0` with the `2.5.0` move sitting in an unmerged PR. `LAF-68`. **PR #1 was not merged by this
    run**; the pin is the maintainer's.
12. Register updated from the run: `LAF-61` back to `open`, rows for `LAF-65`..`LAF-68`. `make
    docs-check` then passed while two release documents still said `visible` — `LAF-69`, found by
    using the register rather than by testing it.

## What this run did not do

The release is **not tagged, not pushed, and not published**. `scripts/release.py` and the checklist
describe those steps; performing them is the maintainer's. The consumer repository's PR #1 is open and
was left open. No credential was typed, and no curses session was driven.
